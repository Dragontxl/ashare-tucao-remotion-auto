# -*- coding: utf-8 -*-
"""Step 1：原始复盘文本 -> 犀利毒舌吐槽文稿 + 分镜 sentences.json。
优先调用 LLM（OpenAI 兼容接口）；无 API Key 时使用内置的确定性降级生成器。
"""
import os
import json
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (ROOT, INPUT_DIR, SRC, CONFIG_DIR, load_config, save_config,
                    save_json, call_llm, extract_json, has_llm_key, llm_settings,
                    date8, cn_date_from_8, log)

VISUALS = ["hook", "title", "data", "punch", "topic", "text", "lesson", "outro"]
TONES = ["negative", "positive", "warn", "neutral"]
# 仅 data/text 场景允许配图；图表键与 public/charts 下的文件名对应
CHART_KEYS = {"timeline", "kline", "global", "gold", "sectors", "breadth"}
# 供 make_charts.py 画图的真实汇总数据
SUMMARY_LIST_KEYS = ("breadth", "global_market", "precious_metal")


# 只有标题、没有内容的 lesson 镜头会在成片里显示成空卡片，必须拦截
LESSON_HEADINGS = {"核心策略", "风险提示", "规避方向", "最后忠告", "操作建议", "后市展望",
                   "交易策略", "风险规避", "总结", "提示", "忠告", "策略"}


def lesson_text_ok(text):
    """lesson 的 text 必须是能朗读的完整句子，不能是 4 字标题。"""
    t = str(text or "").strip()
    if len(t) < 10:
        return False
    return t.rstrip("：:") not in LESSON_HEADINGS


LESSON_LEAD_SUFFIX = ("方向", "策略", "提示", "建议", "忠告", "原则", "结论", "要点", "总结")


def strip_lesson_lead(item):
    """去掉 lesson 正文开头重复的小标题，如“回避方向：受……”“最后忠告：……”。"""
    if item.get("visual") != "lesson":
        return
    m = re.match(r"^([^：:，,。！？]{2,8})[：:]\s*(.+)$", item.get("text", ""))
    if not m:
        return
    lead, rest = m.group(1).strip(), m.group(2).strip()
    if not rest or len(rest) < 10:
        return
    if lead == item.get("big") or lead.endswith(LESSON_LEAD_SUFFIX):
        item["text"] = rest


# ── 数字结论一致性校验 ────────────────────────────────────────────
# 大模型经常把「涨停 57 家、跌停 44 家」写成「跌停比涨停还多」，
# 数字对但结论反了。这里按真实家数做确定性纠正，避免成片出现事实错误。
_COUNT_WORDS = ("涨停", "跌停", "上涨家数", "下跌家数", "上涨", "下跌")
_CNT_RE = re.compile(
    r"(涨停|跌停|上涨家数|下跌家数|上涨|下跌)\s*(\d{1,5})\s*(?:多)?\s*家")
# A 比 B 还多 / 少 / 高 / 低
_CMP_BEFORE = re.compile(
    r"(涨停|跌停|上涨家数|下跌家数|上涨|下跌)(?:家数|家|数量)?\s*比\s*"
    r"(涨停|跌停|上涨家数|下跌家数|上涨|下跌)(?:家数|家|数量)?\s*"
    r"(?:还|都|也|更)?\s*(多|少|高|低)")
# A 多于 / 少于 / 高于 / 低于 / 超过 / 大于 B
_CMP_REL = re.compile(
    r"(涨停|跌停|上涨家数|下跌家数|上涨|下跌)(?:家数|家|数量)?\s*"
    r"(多于|少于|高于|低于|超过|大于|小于)\s*"
    r"(涨停|跌停|上涨家数|下跌家数|上涨|下跌)(?:家数|家|数量)?")

_FLIP_WORD = {"多": "少", "少": "多", "高": "低", "低": "高"}
_FLIP_REL = {"多于": "少于", "少于": "多于", "高于": "低于", "低于": "高于",
             "超过": "少于", "大于": "小于", "小于": "大于"}
_CLAIM_MORE_REL = {"多于", "高于", "超过", "大于"}


def _canon_count_word(word):
    """把「上涨/下跌」统一成 summary 里的「上涨家数/下跌家数」。"""
    return {"上涨": "上涨家数", "下跌": "下跌家数"}.get(word, word)


def _summary_counts(summary):
    counts = {}
    for it in (summary or {}).get("breadth") or []:
        label, value = it.get("label"), it.get("value")
        if label in _COUNT_WORDS and isinstance(value, (int, float)):
            counts[_canon_count_word(label)] = int(value)
    return counts


def _text_counts(text):
    counts = {}
    for m in _CNT_RE.finditer(text):
        counts[_canon_count_word(m.group(1))] = int(m.group(2))
    return counts


def _clean_punct(text):
    t = re.sub(r"[，,、；;：:]{2,}", "，", text)
    t = re.sub(r"^[，,、；;：:\s]+", "", t)
    t = re.sub(r"[，,、；;：:]+\s*([。！？!?])", r"\1", t)
    t = re.sub(r"[，,、；;：:]+$", "", t)
    t = t.strip()
    if t and not t.endswith(("。", "！", "？", "!", "?")):
        t += "。"
    return t


def _flip_match(m, regex):
    """把矛盾比较句的方向词反过来（多↔少、多于↔少于）。"""
    g = m.group(0)
    base = m.start(0)
    if regex is _CMP_BEFORE:
        gi = 3
        flipped = _FLIP_WORD[m.group(gi)]
    else:
        gi = 2
        flipped = _FLIP_REL[m.group(gi)]
    s, e = m.start(gi) - base, m.end(gi) - base
    return g[:s] + flipped + g[e:]


def _fix_count_text(text, summary_counts):
    """纠正「跌停比涨停还多」这类与真实家数矛盾的比较句。"""
    local = dict(summary_counts or {})
    local.update(_text_counts(text))
    stated = set(_text_counts(text))
    changed = False

    def make_repl(regex):
        def repl(m):
            nonlocal changed
            if regex is _CMP_BEFORE:
                a = _canon_count_word(m.group(1))
                b = _canon_count_word(m.group(2))
                claim_more = m.group(3) in ("多", "高")
            else:
                a = _canon_count_word(m.group(1))
                b = _canon_count_word(m.group(3))
                claim_more = m.group(2) in _CLAIM_MORE_REL
            va, vb = local.get(a), local.get(b)
            if va is None or vb is None or va == vb:
                return m.group(0)          # 没有真实数字可比，保持原样
            if (va > vb) == claim_more:
                return m.group(0)          # 结论正确
            changed = True
            if a in stated or b in stated:
                return ""                  # 句中已有数字，直接删掉错误结论
            return _flip_match(m, regex)   # 否则把方向词反过来
        return repl

    out = _CMP_BEFORE.sub(make_repl(_CMP_BEFORE), text)
    out = _CMP_REL.sub(make_repl(_CMP_REL), out)
    return (_clean_punct(out) if changed else text), changed


def fix_count_claims(sentences, summary):
    """逐句纠正涨跌家数/涨跌停家数的矛盾结论，返回被修改的句子列表。"""
    base = _summary_counts(summary)
    changes = []
    for it in sentences:
        old = it.get("text", "")
        new, changed = _fix_count_text(old, base)
        if changed and new:
            it["text"] = new
            changes.append((old, new))
    return changes


def chart_file(raw, visual):
    """把 LLM 给的 chart 键规范成 charts/xxx.png；非法或场景不符时返回 None。"""
    if visual not in ("data", "text"):
        return None
    key = str(raw or "").strip().lower()
    if key.startswith("charts/"):
        key = key[len("charts/"):]
    if key.endswith(".png"):
        key = key[:-len(".png")]
    return f"charts/{key}.png" if key in CHART_KEYS else None


def _num(value, lo=-100000.0, hi=100000.0):
    """把值转成有限数字；非法值返回 None。"""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x < lo or x > hi:
        return None
    return int(x) if x.is_integer() else round(x, 4)


def normalize_summary(raw):
    """校验 LLM 输出的 summary：只保留真实、可画图的数字。"""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in SUMMARY_LIST_KEYS:
        items = raw.get(key)
        if not isinstance(items, list):
            continue
        cleaned = []
        for it in items[:8]:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label", "")).strip()[:16]
            value = _num(it.get("value"), -10000, 100000)
            if label and value is not None:
                cleaned.append({"label": label, "value": value})
        if cleaned:
            out[key] = cleaned
    note = str(raw.get("breadth_note", "")).strip()
    if note:
        out["breadth_note"] = note[:60]
    return out


def extract_summary(article):
    """从原文中确定性提取涨跌家数等真实数字（LLM 失败时的兜底）。"""
    text = re.sub(r"\s+", "", article or "")
    out = {}

    def count(pattern):
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    up = count(r"上涨家数[^0-9]{0,8}(\d+)\s*多?家")
    down = count(r"下跌家数[^0-9]{0,8}(\d+)\s*多?家")
    limit_up = count(r"涨停\s*(\d+)\s*家")
    limit_down = count(r"跌停\s*(\d+)\s*家")
    breadth = []
    if up is not None:
        breadth.append({"label": "上涨家数", "value": up})
    if down is not None:
        breadth.append({"label": "下跌家数", "value": down})
    if limit_up is not None:
        breadth.append({"label": "涨停", "value": limit_up})
    if limit_down is not None:
        breadth.append({"label": "跌停", "value": limit_down})
    if breadth:
        out["breadth"] = breadth

    notes = []
    m = re.search(r"炸板率[^0-9]{0,4}([\d.]+)%", text)
    if m:
        notes.append(f"炸板率 {m.group(1)}%")
    m = re.search(r"连板家数[^0-9]{0,6}(\d+)家", text)
    if m:
        notes.append(f"连板 {m.group(1)} 家")
    if notes:
        out["breadth_note"] = "，".join(notes)
    return out


def merge_summary(primary, fallback):
    """LLM 结果优先，缺失的字段用原文正则提取补齐。"""
    out = dict(primary or {})
    for key, value in (fallback or {}).items():
        if not out.get(key):
            out[key] = value
    return out


SYSTEM_PROMPT = """你是一名犀利毒舌、幽默风趣的A股财经吐槽博主，粉丝称你的节目为"盘面吐槽大会"。
你的风格：短句、有梗、节奏快、反讽尖锐、金句频出，但数据必须真实、不编造。
你会把枯燥的复盘数据变成让人又笑又心酸的口播稿。常使用的手法：反转、比喻、拟人、谐音、夸张对比。

你必须输出严格的 JSON（不要任何多余文字），结构如下：
{
  "article_title": "视频/文章标题，犀利有梗，10-16字",
  "hook_title": "开场主题大标题，如《如何优雅地亏钱》，4-10字",
  "date_label": "日期标签，如 11月20日",
  "market_mood": "市场情绪四字总结，如 极度冰点",
  "ticker": "底部滚动行情快讯文案，把原文中的关键指数/个股涨跌串成一行，用空格分隔，如：上证 3533.79 -1.22%  沪金 -6%  工商银行 +3%",
  "summary": {
    "breadth": [{"label":"上涨家数","value":297},{"label":"下跌家数","value":4800},{"label":"涨停","value":30},{"label":"跌停","value":61}],
    "breadth_note": "炸板率 28.6%，连板仅 4 家",
    "global_market": [{"label":"日经225","value":-5.0},{"label":"韩国综指","value":-5.21}],
    "precious_metal": [{"label":"沪金主力","value":-6.0}]
  },
  "sentences": [
    {"id":1,"text":"口播文案（一句，20字以内最佳）","visual":"hook|title|data|punch|topic|text|lesson|outro","big":"大字（仅 data/title 需要，如 -1.41%）","label":"小标签（可选）","tone":"negative|positive|warn|neutral","chart":"timeline|kline|global|gold|sectors|breadth|"}
  ]
}

规则：
1. 分镜 35-55 句，覆盖原文的：盘前预期、竞价、盘中走势、各板块表现、收盘数据、龙虎榜、后市建议。
2. visual 分配：开头1句 hook + 1句 title；板块介绍用 topic；关键数字用 data（必须填 big）；吐槽金句用 punch（text 要犀利）；过渡句用 text；结尾风险提示用 lesson 2-4句（每句都必须是完整口播句，不能只写标题）；最后一句 outro 引导点赞收藏。
3. 数据全部来自用户原文，禁止编造数字。
4. tone 遵循A股习惯：下跌/利空=negative，上涨/利好=positive，警示/反讽=warn，中性=neutral。
5. 每句 text 独立成句、口语化，适合配音朗读；不要出现 Markdown、括号注释、英文。
6. big 字段只放最核心的数字或短语，简短有力。
7. chart 字段（画面配图，务必与文字语义严格对应）：只有 data/text 场景可填，且仅当该句明确在讲对应图表的内容时才填：
   - timeline：指数分时走势、开盘/盘中/尾盘、日内最高最低、指数点位
   - kline：日K线、技术形态、支撑/压力、连续多日走势
   - global：外围市场（日经、韩股、港股、美股、亚太）
   - gold：黄金/白银/贵金属/金价
   - sectors：板块或个股涨跌对比、资金流向、某板块表现
   - breadth：涨跌家数、涨停跌停家数、连板、炸板、市场情绪
   与以上都不直接相关时留空字符串 ""；hook/title/punch/topic/lesson/outro 一律留空。
   宁可留空，也不要勉强配一张不相关的图。
8. 同一张图最多只给一个镜头配图。多个镜头都在讲同类数据时，只给最合适的一句填 chart，其余留空。
9. summary 字段只填原文中明确出现的真实数字，禁止编造：
   - breadth：涨跌家数/涨停/跌停/连板等「家数」，value 用整数；
   - global_market / precious_metal：涨跌幅百分比，value 用数字，跌为负数；
   - breadth_note：炸板率、连板断层等一句话补充；
   - 原文没有的字段留空数组 [] 或空字符串 ""。
10. lesson 分镜必须有实质内容，禁止只给标题：
   - text 必须是 12 字以上的完整口播句，讲清"做什么 / 不做什么 / 为什么"，例如"明天别急着追，机器人前排回踩再接"；
   - 小标题放 big（4-6字，如"核心策略""风险提示"），标题不参与朗读；
   - 严禁输出 {"text":"核心策略"}、{"text":"风险提示"}、{"text":"规避方向"}、{"text":"最后忠告"} 这类只有标题、没有内容的空镜头。
11. 涉及涨跌家数/涨跌停家数的比较，必须先核对数字再下结论，数字与结论必须一致：
   - 跌停家数 < 涨停家数时，禁止说"跌停比涨停多"；
   - 涨停家数 < 跌停家数时，禁止说"涨停比跌停多"；
   - 上涨家数 < 下跌家数时，禁止说"上涨家数比下跌家数多"；
   - 拿不准就不要做比较，只报数字。"""


def generate_with_llm(cfg, article):
    run_date = os.environ.get("RUN_DATE") or date8()
    user = (f"日期上下文：{cn_date_from_8(run_date)}\n"
            f"以下是今日A股复盘原文，请据此生成毒舌吐槽口播稿：\n\n{article}")
    last_err = None
    for attempt in range(1, 3):
        try:
            reply = call_llm(cfg, SYSTEM_PROMPT, user, json_mode=True)
            data = extract_json(reply)
            return normalize(data, cfg, article)
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"LLM 文稿解析失败（第 {attempt}/2 次）：{type(e).__name__} {e}")
            if attempt == 1:
                if "LESSON_TOO_SHORT" in str(e):
                    user += ("\n\n上一版把 lesson 分镜写成了空标题，不合格。"
                             "请重写：每句 lesson 的 text 必须是 12 字以上完整口播句，"
                             "小标题放到 big 字段，不能只写“核心策略”“风险提示”这类词。"
                             "只输出一个合法 JSON 对象，不要 Markdown 代码围栏。")
                else:
                    user += "\n\n重要：只输出一个合法 JSON 对象，不要 Markdown 代码围栏，不要任何解释文字。"
    raise last_err


def normalize(data, cfg, article=""):
    """校验/补全 LLM 输出，保证分镜结构合法。"""
    sentences = data.get("sentences") or []
    out = []
    for i, s in enumerate(sentences, 1):
        visual = s.get("visual", "text")
        if visual not in VISUALS:
            visual = "text"
        tone = s.get("tone", "neutral")
        if tone not in TONES:
            tone = "neutral"
        item = {"id": i, "text": str(s.get("text", "")).strip(),
                "visual": visual, "tone": tone}
        if s.get("big"):
            item["big"] = str(s["big"]).strip()
        strip_lesson_lead(item)
        if s.get("label"):
            item["label"] = str(s["label"]).strip()
        chart = chart_file(s.get("chart"), visual)
        if chart:
            item["chart"] = chart
        if not item["text"]:
            continue
        out.append(item)
    if not out:
        raise ValueError("LLM 未生成有效分镜")
    # 重新编号，保证连续
    for i, it in enumerate(out, 1):
        it["id"] = i
    # 确保有开头和结尾
    if out[0]["visual"] not in ("hook", "title"):
        out[0]["visual"] = "hook"
        out[0].pop("chart", None)
    out[-1]["visual"] = "outro"
    out[-1].pop("chart", None)
    bad_lessons = [it["text"] for it in out
                   if it["visual"] == "lesson" and not lesson_text_ok(it["text"])]
    if bad_lessons:
        raise ValueError("LESSON_TOO_SHORT：" + " / ".join(bad_lessons))
    summary = merge_summary(normalize_summary(data.get("summary")), extract_summary(article))
    for old, new in fix_count_claims(out, summary):
        log(f"修正数字结论矛盾：{old} -> {new}")
    return {
        "article_title": data.get("article_title") or cfg.get("article_title", "盘面吐槽"),
        "hook_title": data.get("hook_title") or cfg.get("hook_title", "今天这盘面"),
        "date_label": data.get("date_label") or cfg.get("date_label", ""),
        "market_mood": data.get("market_mood") or cfg.get("market_mood", ""),
        "ticker": data.get("ticker") or cfg.get("ticker", ""),
        "summary": summary,
        "sentences": out,
    }


def fallback_generate(cfg, article):
    """无 API Key 时的确定性降级生成器：基于规则把原文拆成吐槽分镜。"""
    log("未检测到 LLM API Key，使用内置降级生成器（质量低于 LLM，配置 API Key 可获得毒舌文稿）")
    # 抽句
    text = article.replace("\r", "")
    parts = re.split(r"(?<=[。！？；\n])", text)
    lines = [p.strip() for p in parts if p.strip() and len(p.strip()) > 4]
    # 去重、截断
    seen = set()
    uniq = []
    for ln in lines:
        ln = re.sub(r"[#=【】\[\]·—]{2,}", " ", ln).strip()
        if ln not in seen and len(ln) < 120:
            seen.add(ln)
            uniq.append(ln)
    if not uniq:
        uniq = [article[:100] or "今天A股又渡劫了。"]

    def tone_of(s):
        if any(k in s for k in ("跌", "崩", "亏", "跌停", "利空", "重挫", "下杀", "抛售")):
            return "negative"
        if any(k in s for k in ("涨", "反弹", "利好", "涨停", "拉升", "护盘", "回购")):
            return "positive"
        return "neutral"

    def visual_of(s, idx):
        if idx == 0:
            return "hook"
        if idx == 1:
            return "title"
        if idx == len(uniq) - 1:
            return "outro"
        if any(k in s for k in ("跌停", "跌", "涨", "%", "点", "亿", "连板", "成交")) and len(s) < 40:
            return "data"
        if idx % 4 == 0:
            return "punch"
        if idx % 5 == 0:
            return "topic"
        return "text"

    def big_of(s):
        m = re.search(r"(-?\d+\.?\d*\s*%|\d+\.?\d*\s*亿|\d+\s*连板|\d+\s*家)", s)
        return m.group(1) if m else ""

    sentences = []
    for i, ln in enumerate(uniq):
        visual = visual_of(ln, i)
        item = {"id": i + 1, "text": ln if len(ln) <= 40 else ln[:38] + "…",
                "visual": visual, "tone": tone_of(ln)}
        if visual == "data":
            b = big_of(ln)
            if b:
                item["big"] = b
                item["label"] = ln[:16]
        if visual == "topic":
            item["label"] = ln[:10].rstrip("，。")
        sentences.append(item)

    # 插入固定开场/金句/结尾
    head = [
        {"id": 1, "text": "家人们，今天这盘面又上演了一出好戏——", "visual": "hook", "tone": "neutral"},
        {"id": 2, "text": f"《{cfg.get('hook_title','如何优雅地亏钱')}》", "visual": "title",
         "big": cfg.get("hook_title", "如何优雅地亏钱"), "label": cfg.get("date_label", "今日复盘"), "tone": "warn"},
    ]
    tail = [
        {"text": "最后说句正经的：", "visual": "lesson", "tone": "neutral"},
        {"text": "数据不会骗人，情绪会。别急着抄底。", "visual": "lesson", "tone": "warn"},
        {"text": "活着，比什么都重要。", "visual": "punch", "tone": "warn"},
        {"text": "今天的吐槽就到这，点赞收藏，明天接着渡劫。", "visual": "outro", "tone": "neutral"},
    ]
    body = [s for s in sentences if s["visual"] not in ("hook", "title", "outro")]
    merged = head + body + tail
    for i, it in enumerate(merged, 1):
        it["id"] = i
    return {
        "article_title": cfg.get("article_title") or "今天这盘面输得很有节奏",
        "hook_title": cfg.get("hook_title") or "如何优雅地亏钱",
        "date_label": cfg.get("date_label") or "今日",
        "market_mood": cfg.get("market_mood") or "情绪冰点",
        "ticker": cfg.get("ticker") or "",
        "summary": extract_summary(article),
        "sentences": merged,
    }


def main():
    cfg = load_config()
    run_date = os.environ.get("RUN_DATE") or date8()
    # 期号与日期标签随运行日期自动更新（封面/角标使用）
    cfg["episode"] = "EP." + run_date[4:8]
    cfg["date_label"] = cn_date_from_8(run_date)

    article_path = os.environ.get("ARTICLE_PATH") or os.path.join(INPUT_DIR, "article.md")
    if not os.path.exists(article_path):
        raise FileNotFoundError(f"原始复盘文本不存在：{article_path}\n请放到 input/article.md 或先运行 fetch_article.py")
    with open(article_path, encoding="utf-8") as f:
        article = f.read()
    log(f"读取原始文本 {len(article)} 字：{article_path}")

    skip_llm = os.environ.get("SKIP_LLM", "").lower() in ("1", "true", "yes")
    use_llm = (not skip_llm) and has_llm_key(cfg)
    if use_llm:
        s = llm_settings(cfg)
        log(f"使用大模型：{s['model']} @ {s['base_url']}")
        try:
            result = generate_with_llm(cfg, article)
            log(f"LLM 生成成功：{len(result['sentences'])} 句分镜")
        except Exception as e:
            log(f"LLM 生成失败（{type(e).__name__}: {e}），回退到降级生成器")
            result = fallback_generate(cfg, article)
    else:
        result = fallback_generate(cfg, article)

    save_json(os.path.join(SRC, "sentences.json"), result["sentences"])
    # 汇总数据必须每次覆盖，避免沿用上一交易日的旧数字
    cfg["summary"] = result.get("summary") or {}
    # 把生成的元信息写回 config.json（供封面/简介/组件读取）
    for k in ("article_title", "hook_title", "date_label", "market_mood", "ticker"):
        if result.get(k):
            cfg[k] = result[k]
    # 用户在提交任务时手动填写的标题优先，不被大模型标题覆盖
    override_title = (os.environ.get("VIDEO_TITLE") or "").strip()
    if override_title:
        result["article_title"] = override_title
        cfg["article_title"] = override_title
        log(f"视频标题使用手动指定：{override_title}")
    save_config(cfg)
    log(f"文稿生成完成：{result['article_title']} | {len(result['sentences'])} 句")
    if cfg["summary"]:
        log(f"汇总数据：{json.dumps(cfg['summary'], ensure_ascii=False)}")
    log("原始文稿已保存：src/sentences.json")


if __name__ == "__main__":
    main()
