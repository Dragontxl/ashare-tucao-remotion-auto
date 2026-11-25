# -*- coding: utf-8 -*-
"""Step 2a：从 timeline.json 中自动提取股票名称，补入 config.stocks。

从新浪财经接口下载完整 A 股代码+名称列表，构建名称字典，
扫描分镜的 text 字段提取候选名，在字典中精确匹配股票代码，
将新发现的股票追加到 config.stocks（不覆盖已有配置）。

这样后续 fetch_market_data.py 能抓取行情，make_charts.py 能生成个股图表，
StockVideo.tsx 的 matchChart 能将 text 场景中的股票名匹配到对应图表。

用法：
  python scripts/extract_stocks.py          # 扫描并补入股票
  python scripts/extract_stocks.py --dry   # 只扫描不写入
  python scripts/extract_stocks.py --refresh   # 强制重新下载股票列表
"""
import argparse
import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SRC, load_config, save_config, load_json, save_json, log

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

# 股票列表缓存文件
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STOCK_LIST_FILE = os.path.join(DATA_DIR, "a_stock_list.json")
STOCK_LIST_TTL = 7 * 24 * 3600  # 7 天有效

# 停用词：这些词即使被拆分出来也不是股票名，直接过滤
STOP_WORDS = {
    "涨停", "跌停", "板块", "资金", "指数", "市场", "个股", "机构", "游资",
    "主力", "散户", "情绪", "方向", "主线", "龙头", "高位", "低位", "放量",
    "缩量", "突破", "回踩", "支撑", "压力", "成交", "涨幅", "跌幅", "上涨",
    "下跌", "封单", "竞价", "开盘", "收盘", "尾盘", "盘面", "复盘", "概念",
    "连板", "炸板", "飘红", "净流入", "净流出", "赚钱效应", "整数关口", "前高",
    "抄底", "避雷", "追高", "谨慎", "建议", "点赞", "关注", "银行", "光伏",
    "医药", "算力", "硬件", "半导体", "光通信", "液冷", "黄金", "贵金属",
    "股票", "证券", "大盘", "沪深", "深证", "上证", "创业板", "科创板",
    "证伪", "新股", "旧股", "牛股", "妖股", "黑马", "白马", "权重", "题材",
    "热点", "风口", "轮动", "补涨", "回调", "反弹", "探底", "冲高", "回落",
    "光头", "阳线", "阴线", "十字", "量能", "量增", "量缩",
    "封板", "开板", "破板", "回封",
    "A股", "H股", "美股", "港股", "中概", "富时", "道指", "纳指",
    "英伟达", "科技", "硬件",
    "全封板", "封单", "封死",
    "翻倍", "增倍", "同增", "同比",
    "集体", "集体发疯", "没人", "没人爱", "没人理",
    "可以", "别慌", "别去", "别碰", "注意", "小心",
    "依然", "还是", "结果", "这时候",
    "点赞关注", "下周一见", "不构成", "仅为",
    "内容", "行情", "走势", "后市", "市看",
    "新高", "新低",
    "市场情绪", "板块涨停", "批量涨停",
    "严重", "明显", "急剧", "瞬间", "还在",
    "抢筹", "抢算力", "抢糖", "发糖",
    "批量", "全线", "全线飘红",
    "今天", "明天", "昨天", "后天",
    "看医", "看医药",
    "光伏银行",
}

# 常见后缀/前缀词——股票名不会以这些字开头或结尾
INVALID_PREFIXES = {
    "一", "两", "三", "几", "上", "下", "不", "没", "有", "是",
    "在", "到", "对", "把", "被", "让", "给", "从", "向", "往",
}
INVALID_SUFFIXES = {
    "了", "的", "是", "在", "有", "着", "过", "都", "也", "还",
    "就", "才", "又", "再", "只", "更", "最", "太", "很",
}


# ---------- 下载完整 A 股列表 ----------

def _fetch_page(node, page, page_size=80):
    """从新浪接口抓取一页股票数据。"""
    params = urllib.parse.urlencode({
        "page": str(page),
        "num": str(page_size),
        "sort": "symbol",
        "asc": "1",
        "node": node,
    })
    url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA_LIST[page % len(UA_LIST)],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://finance.sina.com.cn/",
        "Cache-Control": "no-cache",
    })
    raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
    if not raw or raw.strip() in ("", "null"):
        return []
    return json.loads(raw)


def download_stock_list():
    """下载全部 A 股（上海 + 深圳）代码和名称，返回 [{code, name}, ...]。"""
    all_stocks = []
    seen = set()
    for node, label in [("sh_a", "上海A股"), ("sz_a", "深圳A股")]:
        log(f"下载{label}...")
        page = 1
        consecutive_fail = 0
        max_pages = 80
        while page <= max_pages:
            try:
                data = _fetch_page(node, page)
            except Exception as e:
                consecutive_fail += 1
                if consecutive_fail >= 3:
                    log(f"  {label} 第{page}页失败，停止（已获取{len(all_stocks)}只）")
                    break
                time.sleep(2 * consecutive_fail)
                page += 1
                continue
            if not isinstance(data, list) or len(data) == 0:
                log(f"  {label} 第{page}页：空，停止（已获取{len(all_stocks)}只）")
                break
            consecutive_fail = 0
            for item in data:
                symbol = item.get("symbol", "")
                name = item.get("name", "")
                if symbol and name:
                    code = symbol  # 保留 sh/sz 前缀，如 sh600000
                    if code not in seen:
                        seen.add(code)
                        all_stocks.append({"code": code, "name": name})
            if len(data) < 80:
                log(f"  {label} 完成，共{len(data)}条")
                break
            if page % 10 == 0:
                log(f"  {label} 第{page}页，累计{len(all_stocks)}只")
            time.sleep(0.3 + page % 3 * 0.1)
            page += 1
        if node == "sh_a":
            time.sleep(3)  # 两个节点之间间隔，避免反爬
    log(f"股票列表下载完成：共 {len(all_stocks)} 只")
    return all_stocks


def load_stock_dict(refresh=False):
    """加载 A 股名称字典 {name: code}。优先用缓存，过期或 --refresh 时重新下载。"""
    if not refresh and os.path.exists(STOCK_LIST_FILE):
        try:
            with open(STOCK_LIST_FILE, encoding="utf-8") as f:
                cached = json.load(f)
            age = time.time() - cached.get("updated_at", 0)
            if age < STOCK_LIST_TTL:
                log(f"使用缓存股票列表（{len(cached.get('stocks', []))} 只，{age/3600:.1f}小时前）")
                return {s["name"]: s["code"] for s in cached["stocks"]}, cached["stocks"]
            else:
                log(f"缓存已过期（{age/86400:.1f}天），重新下载")
        except Exception:
            pass

    stocks = download_stock_list()
    os.makedirs(DATA_DIR, exist_ok=True)
    save_json(STOCK_LIST_FILE, {"updated_at": time.time(), "stocks": stocks})
    log(f"股票列表已缓存到 {STOCK_LIST_FILE}")
    return {s["name"]: s["code"] for s in stocks}, stocks


# ---------- 候选提取与匹配 ----------

def extract_candidates(timeline_data):
    """从 timeline.json 的 items 中提取候选股票名。

    策略：
      1. 提取所有连续中文字符段
      2. 长度 2-6 的完整段直接作为候选（独立短语可能是股票名）
      3. 长度 > 6 的长段，只提取前缀（3-6字）和后缀（3-6字）
         ——股票名通常出现在短语的开头或结尾，不会散落在中间
      4. 过滤停用词、停用词子串、非法前缀/后缀
    """
    candidates = set()
    items = timeline_data.get("items", [])
    for scene in items:
        text = scene.get("text", "")
        if not text:
            continue
        runs = re.findall(r'[\u4e00-\u9fff]+', text)
        for run in runs:
            n = len(run)
            if n < 2:
                continue
            candidates_for_run = []
            if 2 <= n <= 6:
                candidates_for_run.append(run)
            elif n > 6:
                for length in (3, 4, 5, 6):
                    candidates_for_run.append(run[:length])
                    candidates_for_run.append(run[-length:])
            for cand in candidates_for_run:
                if not cand or len(cand) < 2:
                    continue
                if cand in STOP_WORDS:
                    continue
                if any(cand in sw and cand != sw for sw in STOP_WORDS):
                    continue
                if cand[0] in INVALID_PREFIXES:
                    continue
                if cand[-1] in INVALID_SUFFIXES:
                    continue
                candidates.add(cand)
    return candidates


def match_stock(name, stock_dict):
    """在完整 A 股字典中精确匹配。

    返回 code（如 sh600183）或 None。
    """
    if name in stock_dict:
        return stock_dict[name]
    return None


def main():
    ap = argparse.ArgumentParser(description="从 timeline.json 自动提取股票名称")
    ap.add_argument("--dry", action="store_true", help="只扫描不写入配置")
    ap.add_argument("--refresh", action="store_true", help="强制重新下载股票列表")
    args = ap.parse_args()

    cfg = load_config()
    timeline_path = os.path.join(SRC, "timeline.json")
    timeline_data = load_json(timeline_path)
    if not timeline_data:
        log("未找到 timeline.json，跳过股票提取")
        return 0

    # 加载完整 A 股列表
    stock_dict, _ = load_stock_dict(refresh=args.refresh)
    log(f"A 股字典：{len(stock_dict)} 只股票")

    candidates = extract_candidates(timeline_data)
    log(f"从 timeline.json 发现 {len(candidates)} 个候选名称")

    # 已配置的股票名称集合
    existing_stocks = cfg.get("stocks", [])
    existing_names = {s.get("name") for s in existing_stocks}

    new_stocks = []
    matched_count = 0
    for name in sorted(candidates):
        if name in existing_names:
            continue
        code = match_stock(name, stock_dict)
        if code:
            matched_count += 1
            # 用字典中的标准名称
            std_name = name
            if std_name in existing_names:
                continue
            file_name = f"stock_{code}.png"
            new_stock = {
                "code": code,
                "name": std_name,
                "file": file_name,
                "label": "",
            }
            new_stocks.append(new_stock)
            existing_names.add(std_name)
            log(f"  匹配：{name} → {code}")

    if new_stocks and not args.dry:
        cfg["stocks"] = list(existing_stocks) + new_stocks
        save_config(cfg)
        log(f"已追加 {len(new_stocks)} 只股票到 config.stocks（图表文件名：{', '.join(s['file'] for s in new_stocks)}）")
    elif new_stocks and args.dry:
        log(f"[DRY] 将追加 {len(new_stocks)} 只股票（未写入）")
    else:
        log("没有新发现的股票，无需更新配置")

    log(f"匹配结果：{matched_count} 个候选命中，{len(candidates) - matched_count} 个未命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
