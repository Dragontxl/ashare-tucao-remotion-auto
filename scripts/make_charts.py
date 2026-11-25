# -*- coding: utf-8 -*-
"""Step 2c：生成视频所需图表（真实数据优先，字体跨平台）。
生成的图表文件：
  timeline.png  指数分时（真实）
  kline.png     指数日K（真实）
  stock_*.png   个股分时+日K（真实，按 config.stocks）
  global.png    全球市场对比（原文提取，缺失则不生成）
  gold.png      贵金属（原文提取，缺失则不生成）
  sectors.png   板块/个股涨跌对比（真实个股涨跌）
  breadth.png   市场情绪（原文提取，缺失则不生成）

生成完成后写入 src/charts_manifest.json，渲染端只会引用真实存在的图表。
"""
import os
import sys
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (CHARTS, MARKET_DATA, SRC, load_config, load_json, save_json,
                    find_chinese_font, log)

cfg = load_config()
INDEX = cfg.get("index_code", "sh000001")
STOCKS = cfg.get("stocks", [])
SUMMARY = cfg.get("summary") or {}  # 可选：从原文提取的汇总数字

# 字体（跨平台）
FONT_PATH = find_chinese_font()
if FONT_PATH:
    from matplotlib import font_manager
    fp = font_manager.FontProperties(fname=FONT_PATH)
    plt.rcParams["font.family"] = fp.get_name()
    log(f"使用中文字体：{FONT_PATH}")
else:
    from matplotlib import font_manager
    fp = font_manager.FontProperties(family="sans-serif")
    log("警告：未找到中文字体，图表中文可能显示为方块。CI 请安装 fonts-noto-cjk")
plt.rcParams["axes.unicode_minus"] = False

DARK = "#0b1020"; CARD = "#131a2e"
UP = "#ff4d5e"; DOWN = "#25e08a"   # A股：涨红跌绿
TEXT = "#eef3ff"; MUTED = "#9fb2d8"; GRID = "#2a3552"; ACCENT = "#ffb02e"
META = load_json(os.path.join(MARKET_DATA, "meta.json"), {})
DATE = META.get("trade_date", "")
DATE_LABEL = f"{DATE[5:7]}月{DATE[8:10]}日" if DATE and len(DATE) >= 10 else cfg.get("date_label", "")
# 图表页脚只保留日期，不再标注数据来源
NOTE = DATE_LABEL


def load(name):
    return load_json(os.path.join(MARKET_DATA, name), None)


def title(ax, text, size=24):
    ax.set_title(text, color=TEXT, fontsize=size, fontweight="bold", pad=18, fontproperties=fp)


def note(fig, text=NOTE):
    fig.text(0.5, 0.02, text, color="#6b7da3", fontsize=12, ha="center", fontproperties=fp)


def style_ax(ax):
    ax.set_facecolor(CARD)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.5)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=12)


GENERATED = []


def finish(fig, name):
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(os.path.join(CHARTS, name), dpi=110, facecolor=DARK, bbox_inches="tight")
    plt.close(fig)
    GENERATED.append(f"charts/{name}")
    log(f"生成图表 {name}")


def drop(name):
    """删除过期图表：宁可没有图，也不让旧图/假数据出现在视频里。"""
    path = os.path.join(CHARTS, name)
    if os.path.exists(path):
        os.remove(path)
        log(f"删除过期图表 {name}")


def plot_index_timeline():
    d = load(f"{INDEX}_trends.json")
    k = load(f"{INDEX}_kline.json")
    if not d or not k or len(k["kline"]) < 2:
        log("跳过 timeline.png：缺少指数数据")
        drop("timeline.png")
        return
    prev = k["kline"][-2]["close"]
    trends = d["trends"]
    times = [p["time"] for p in trends]
    prices = [p["price"] for p in trends]
    xs = np.arange(len(prices))
    color = DOWN if prices[-1] < prev else UP

    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor(DARK); style_ax(ax)
    ax.fill_between(xs, prices, prev, color=color, alpha=0.12)
    ax.plot(xs, prices, color=color, lw=2.4)
    ax.axhline(prev, color=MUTED, ls="--", lw=1.3)
    ax.text(1, prev, f"昨收 {prev:.2f}", color=MUTED, fontsize=13, fontproperties=fp, va="bottom")

    lo_i = int(np.argmin(prices)); hi_i = int(np.argmax(prices))
    ax.scatter([lo_i], [prices[lo_i]], color=ACCENT, s=70, zorder=5)
    ax.annotate(f"最低 {prices[lo_i]:.2f} {times[lo_i]}", (lo_i, prices[lo_i]),
                xytext=(20, -48), textcoords="offset points", color=ACCENT,
                fontsize=13, fontweight="bold", fontproperties=fp,
                arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.5))
    ax.scatter([hi_i], [prices[hi_i]], color=UP, s=55, zorder=5)
    ax.annotate(f"最高 {prices[hi_i]:.2f} {times[hi_i]}", (hi_i, prices[hi_i]),
                xytext=(-140, 22), textcoords="offset points", color=UP,
                fontsize=13, fontweight="bold", fontproperties=fp,
                arrowprops=dict(arrowstyle="->", color=UP, lw=1.5))
    chg = (prices[-1] / prev - 1) * 100
    ax.scatter([len(prices) - 1], [prices[-1]], color=TEXT, s=60, zorder=5)
    ax.annotate(f"收盘 {prices[-1]:.2f} {chg:+.2f}%", (len(prices) - 1, prices[-1]),
                xytext=(-160, -46), textcoords="offset points", color=TEXT,
                fontsize=13, fontweight="bold", fontproperties=fp,
                arrowprops=dict(arrowstyle="->", color=TEXT, lw=1.5))
    ticks = [i for i, t in enumerate(times) if t in ("09:30", "10:30", "11:30", "13:00", "14:00", "15:00")]
    if ticks:
        ax.set_xticks(ticks); ax.set_xticklabels([times[i] for i in ticks], fontproperties=fp)
    ax.set_xlim(0, len(prices) - 1)
    ax.set_ylabel("指数点位", color=MUTED, fontsize=14, fontproperties=fp)
    title(ax, f"{cfg.get('index_name','上证指数')} · {DATE_LABEL}分时走势")
    note(fig); finish(fig, "timeline.png")


def plot_index_kline():
    d = load(f"{INDEX}_kline.json")
    if not d or len(d["kline"]) < 5:
        log("跳过 kline.png：缺少指数K线")
        drop("kline.png")
        return
    rows = d["kline"][-20:]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor(DARK)
    for a in (ax, ax2):
        style_ax(a)
    xs = np.arange(len(rows))
    for i, r in enumerate(rows):
        c = UP if r["close"] >= r["open"] else DOWN
        ax.plot([i, i], [r["low"], r["high"]], color=c, lw=1.6, zorder=2)
        y0, y1 = min(r["open"], r["close"]), max(r["open"], r["close"])
        ax.add_patch(plt.Rectangle((i - 0.32, y0), 0.64, max(y1 - y0, 0.6),
                                   facecolor=c, edgecolor=c, lw=1, zorder=3))
        ax2.bar(i, r["volume"] / 1e8, color=c, alpha=0.7, width=0.64)
    last = rows[-1]; li = len(rows) - 1
    ax.annotate(f"{last['date'][5:]} 收{last['close']:.2f}\n最低探{last['low']:.2f}",
                xy=(li, last["low"]), xytext=(li - 6, last["low"] - 28),
                color=ACCENT, fontsize=13, fontweight="bold", fontproperties=fp,
                arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.5))
    title(ax, f"{cfg.get('index_name','上证指数')} · 近20日日K线")
    ax.set_ylabel("点位", color=MUTED, fontsize=13, fontproperties=fp)
    ax2.set_ylabel("成交量(亿手)", color=MUTED, fontsize=12, fontproperties=fp)
    ax2.set_xticks(xs[::3])
    ax2.set_xticklabels([r["date"][5:] for r in rows][::3], rotation=40, ha="right", fontproperties=fp)
    note(fig); finish(fig, "kline.png")


def plot_stock(s):
    code, name, fname = s["code"], s["name"], s["file"]
    kd = load(f"{code}_kline.json"); td = load(f"{code}_trends.json")
    if not kd or not td or len(kd["kline"]) < 2 or not td["trends"]:
        log(f"跳过 {fname}：缺少 {name} 数据")
        drop(fname)
        return
    rows = kd["kline"][-15:]
    prev = kd["kline"][-2]["close"]; last = kd["kline"][-1]
    prices = [p["price"] for p in td["trends"]]
    xs = np.arange(len(prices))
    chg = (last["close"] / prev - 1) * 100
    color = UP if chg >= 0 else DOWN

    fig = plt.figure(figsize=(13, 7.5)); fig.patch.set_facecolor(DARK)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.28)
    ax1 = fig.add_subplot(gs[0]); style_ax(ax1)
    ax1.plot(xs, prices, color=color, lw=2)
    ax1.fill_between(xs, prev, prices, color=color, alpha=0.12)
    ax1.axhline(prev, color=MUTED, ls="--", lw=1.2)
    ax1.text(1, prev, f"昨收 {prev:.2f}", color=MUTED, fontsize=11, fontproperties=fp, va="bottom")
    ax1.set_title(f"{name} {DATE_LABEL}分时 {chg:+.2f}%", color=color,
                  fontsize=17, fontweight="bold", fontproperties=fp)
    ax1.set_xticks(xs[::max(1, len(prices) // 6)])

    ax2 = fig.add_subplot(gs[1]); style_ax(ax2)
    kx = np.arange(len(rows))
    for i, r in enumerate(rows):
        c = UP if r["close"] >= r["open"] else DOWN
        ax2.plot([i, i], [r["low"], r["high"]], color=c, lw=1.5)
        y0, y1 = min(r["open"], r["close"]), max(r["open"], r["close"])
        ax2.add_patch(plt.Rectangle((i - 0.32, y0), 0.64, max(y1 - y0, 0.01), facecolor=c, edgecolor=c, lw=1))
    ax2.set_title(f"{name} 近15日日K", color=TEXT, fontsize=17, fontweight="bold", fontproperties=fp)
    ax2.set_xticks(kx[::3])
    ax2.set_xticklabels([r["date"][5:] for r in rows][::3], rotation=40, ha="right", fontproperties=fp)
    note(fig)
    finish(fig, fname)
    log(f"  {name} {chg:+.2f}%")


def bar_chart(name, title_text, items, subtitle=NOTE):
    """通用横向条形图：items=[(label, value), ...] value 为百分比。"""
    if not items:
        return
    items = sorted(items, key=lambda x: x[1])
    labels = [i[0] for i in items]; vals = [i[1] for i in items]
    colors = [DOWN if v < 0 else UP for v in vals]
    fig, ax = plt.subplots(figsize=(11, 7)); fig.patch.set_facecolor(DARK); style_ax(ax)
    bars = ax.barh(labels, vals, color=colors, alpha=0.85)
    ax.axvline(0, color=MUTED, lw=1)
    # 数值标签画在柱体外侧，先按跨度预留空间，避免负值标签溢出到左侧股票名上
    lo = min(min(vals), 0.0)
    hi = max(max(vals), 0.0)
    span = (hi - lo) or 1.0
    pad = span * 0.22
    ax.set_xlim(lo - pad, hi + pad)
    ax.margins(x=0)
    for b, v in zip(bars, vals):
        ax.text(v + (span * 0.012 if v >= 0 else -span * 0.012), b.get_y() + b.get_height() / 2,
                f"{v:+.2f}%", va="center", ha="left" if v >= 0 else "right",
                color=TEXT, fontsize=13, fontproperties=fp, fontweight="bold")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))
    title(ax, title_text); note(fig, subtitle); finish(fig, name)


def plot_summary():
    # 全球市场：只使用原文提取的真实数据；没有就留白，不再拿上证指数冒充
    gm = SUMMARY.get("global_market")
    if gm:
        bar_chart("global.png", "全球市场表现对比",
                  [(x["label"], float(x["value"])) for x in gm], "")
    else:
        drop("global.png")

    # 贵金属：只使用原文提取的真实数据；没有就留白，不再硬编码 -6%/-9%
    pm = SUMMARY.get("precious_metal")
    if pm:
        bar_chart("gold.png", "贵金属市场表现",
                  [(x["label"], float(x["value"])) for x in pm], "")
    else:
        drop("gold.png")

    # 板块分化：用真实个股涨跌；没有真实数据就不画
    items = []
    for s in STOCKS:
        kd = load(f"{s['code']}_kline.json")
        if kd and len(kd["kline"]) >= 2:
            chg = (kd["kline"][-1]["close"] / kd["kline"][-2]["close"] - 1) * 100
            items.append((s["name"], chg))
    if items:
        bar_chart("sectors.png", "个股/板块涨跌分化", items)
    else:
        drop("sectors.png")

    # 市场情绪 breadth：只用原文的真实家数，禁止假数据兜底
    br = SUMMARY.get("breadth") or []
    counts = [(x["label"], float(x["value"])) for x in br
              if "率" not in x["label"] and "%" not in x["label"]]
    percents = [(x["label"], float(x["value"])) for x in br
                if "率" in x["label"] or "%" in x["label"]]
    if counts:
        labels = [i[0] for i in counts]
        vals = [i[1] for i in counts]
        fig, ax = plt.subplots(figsize=(11, 7)); fig.patch.set_facecolor(DARK); style_ax(ax)
        bars = ax.bar(labels, vals, color=[DOWN if "跌" in l else (UP if "涨" in l else ACCENT) for l in labels],
                      alpha=0.85)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{int(v)}家", ha="center", va="bottom",
                    color=TEXT, fontsize=14, fontweight="bold", fontproperties=fp)
        subtitle = " · ".join([f"{l} {v:g}%" for l, v in percents])
        if SUMMARY.get("breadth_note"):
            subtitle = (subtitle + " · " if subtitle else "") + str(SUMMARY["breadth_note"])
        title(ax, "市场情绪概览"); note(fig, subtitle or NOTE)
        finish(fig, "breadth.png")
    elif percents:
        labels = [i[0] for i in percents]
        vals = [i[1] for i in percents]
        fig, ax = plt.subplots(figsize=(11, 7)); fig.patch.set_facecolor(DARK); style_ax(ax)
        bars = ax.bar(labels, vals, color=ACCENT, alpha=0.85)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:g}%", ha="center", va="bottom",
                    color=TEXT, fontsize=14, fontweight="bold", fontproperties=fp)
        note(fig, SUMMARY.get("breadth_note") or NOTE)
        title(ax, "市场情绪概览")
        finish(fig, "breadth.png")
    else:
        drop("breadth.png")


def write_manifest():
    """记录本次真实生成的图表，渲染端据此过滤，避免引用不存在的图片。"""
    save_json(os.path.join(SRC, "charts_manifest.json"), {"files": sorted(GENERATED)})
    log(f"图表清单：{len(GENERATED)} 张")


def main():
    plot_index_timeline()
    plot_index_kline()
    for s in STOCKS:
        plot_stock(s)
    plot_summary()
    write_manifest()
    log("全部图表生成完成")


if __name__ == "__main__":
    main()
