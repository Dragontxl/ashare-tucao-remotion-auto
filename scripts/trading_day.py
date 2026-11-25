# -*- coding: utf-8 -*-
"""交易日判定。

复用 F:/Programs/asharesource/summary_today 的「东方财富财经早餐存在性」逻辑：
当天存在「东方财富财经早餐 M月D日」即代表是交易日。

用法：
    python scripts/trading_day.py            # 判定今天
    python scripts/trading_day.py 20260821   # 判定指定日期
"""
import json
import os
import sys
import time
import uuid
from urllib.parse import urljoin

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import cn_date, date8, parse_date8  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_EASTMONEY_BREAKFAST_API = (
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
    "?client=web&biz=web_news_col&column=1207&order=1&needInteractData=0"
    "&page_index={page_index}&page_size={page_size}&req_trace={trace}&"
    "fields=code,showTime,title,mediaName,summary,image,url,uniqueUrl,Np_dst"
    "&types=1,20&callback=_emcb"
)
_EASTMONEY_BREAKFAST_HEADERS = dict(HEADERS)
_EASTMONEY_BREAKFAST_HEADERS.update({"Referer": "https://stock.eastmoney.com/a/czpnc.html"})

PAGE_SIZE = 150  # 盘后新闻多，扩大到 150 条避免早餐被挤到后面
MAX_PAGES = 3


def _parse_response(text):
    t = (text or "").strip()
    if t.startswith("_emcb("):
        t = t[6:]
    if t.endswith(");"):
        t = t[:-2]
    elif t.endswith(")"):
        t = t[:-1]
    data = json.loads(t)
    return (data.get("data") or {}).get("list", []) or []


def _first_breakfast(items, cn_date_str):
    """在条目列表中找「东方财富财经早餐 {cn_date}」，返回 (title, href) 或 None。"""
    target = f"东方财富财经早餐 {cn_date_str}"
    for it in items:
        title = it.get("title", "") or ""
        if target in title:
            href = it.get("url") or it.get("uniqueUrl") or ""
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = urljoin("https://finance.eastmoney.com", href)
            return title, href
    return None


def find_eastmoney_breakfast(cn_date_str, timeout=15):
    """东方财富财经早餐存在性校验。命中返回 (title, href)，否则 None。"""
    for page in range(1, MAX_PAGES + 1):
        api = _EASTMONEY_BREAKFAST_API.format(
            page_index=page, page_size=PAGE_SIZE, trace=uuid.uuid4()
        )
        items = None
        for attempt in range(2):
            try:
                resp = requests.get(api, headers=_EASTMONEY_BREAKFAST_HEADERS, timeout=timeout)
                resp.raise_for_status()
                items = _parse_response(resp.text)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[TRADING] 东方财富早餐接口失败（第{page}页，第{attempt + 1}次）：{e}")
                if attempt == 0:
                    time.sleep(2)
        if items is None:
            continue
        found = _first_breakfast(items, cn_date_str)
        if found:
            return found
        if len(items) < PAGE_SIZE:
            break
    return None


def check_trading_day(value=None):
    """判定交易日。

    返回 (status, reason)：
      status=True  交易日
      status=False 非交易日（周末 / 无财经早餐）
      status=None  无法判定（接口异常），由调用方决定是否继续
    """
    dt = parse_date8(value)
    # 周末直接判定，不消耗接口请求
    if dt.weekday() >= 5:
        return False, f"{dt.month}月{dt.day}日是周末，非交易日"

    cn = f"{dt.month}月{dt.day}日"
    try:
        found = find_eastmoney_breakfast(cn)
    except Exception as e:  # noqa: BLE001
        return None, f"交易日判定接口异常：{type(e).__name__} {e}"
    if found:
        return True, f"命中「{found[0]}」，判定为交易日"
    return False, f"未命中「东方财富财经早餐 {cn}」，判定为非交易日"


def is_trading_day(value=None):
    """兼容旧接口：仅返回布尔值，无法判定时返回 False。"""
    status, _ = check_trading_day(value)
    return status is True


def main():
    value = sys.argv[1] if len(sys.argv) > 1 else date8()
    dt = parse_date8(value)
    status, reason = check_trading_day(value)
    label = {True: "交易日", False: "非交易日", None: "无法判定"}[status]
    print(f"{dt.strftime('%Y%m%d')}（{cn_date(dt)}）：{label} - {reason}")
    return 0 if status is not False else 1


if __name__ == "__main__":
    sys.exit(main())
