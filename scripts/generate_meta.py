# -*- coding: utf-8 -*-
"""Step 5：生成 B站简介、标签 tag、封面配置 cover.json。
时间轴章节从 timeline.json 自动提取，与视频完全对齐。
注意：本步骤在渲染（Step 4）之前执行，确保 cover.json 已就绪。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, SRC, OUT, load_config, load_json, save_json, log

cfg = load_config()
tl = load_json(os.path.join(SRC, "timeline.json"), {})
items = tl.get("items", [])
fps = tl.get("fps", 30)


def fmt_time(frame):
    s = int(frame / fps)
    return f"{s // 60:02d}:{s % 60:02d}"


def build_chapters():
    """选取代表性的分镜作为章节：开头、topic、关键 data、lesson、outro。"""
    picked = []
    for it in items:
        v = it.get("visual")
        if v in ("hook", "title", "topic", "lesson", "outro") or (v == "data" and it.get("big")):
            picked.append(it)
    # 控制章节数量 12-16
    if len(picked) > 15:
        step = len(picked) / 15
        picked = [picked[int(i * step)] for i in range(15)]
    lines = []
    for it in picked:
        label = it.get("big") or it.get("label") or it.get("text", "")[:14]
        lines.append(f"{fmt_time(it['startFrame'])} {label}")
    return lines


def build_description():
    title = cfg.get("article_title", "今天这盘面")
    mood = cfg.get("market_mood", "")
    date = cfg.get("date_label", "")
    chapters = "\n".join(build_chapters())
    tags = cfg.get("tags") or [
        "A股", "A股复盘", "股票", "财经", "盘面吐槽", "上证指数",
        "投资理财", "干货分享", "股市", "每日复盘",
    ]
    tag_line = " ".join("#" + t for t in tags)

    # 从分镜里挑几条金句做简介正文
    punches = [it["text"] for it in items if it.get("visual") == "punch"][:4]
    punch_text = " ".join(punches)

    desc = f"""{title}

{date}的A股，市场情绪：{mood}。
{punch_text}

本期用吐槽的方式，把当天盘面从盘前预期、竞价、盘中走势到收盘数据完整捋一遍。

━━━━━━━━━━━━━━━
⏱ 时间轴（点击跳转）
━━━━━━━━━━━━━━━
{chapters}

━━━━━━━━━━━━━━━
如果这期让你笑中带泪，别忘了【一键三连】👍🪙⭐
点赞投币收藏，明天接着渡劫～
评论区聊聊：今天你手里那只，绿得发光了吗？

{tag_line}

⚠️ 免责声明：本视频仅为市场复盘与娱乐化表达，所有内容不构成任何投资建议。股市有风险，入市需谨慎。
"""
    return desc, tags


def main():
    desc, tags = build_description()
    out_desc = os.path.join(OUT, "B站简介.md")
    with open(out_desc, "w", encoding="utf-8") as f:
        f.write(desc)
    out_tags = os.path.join(OUT, "tags.txt")
    with open(out_tags, "w", encoding="utf-8") as f:
        f.write(" ".join("#" + t for t in tags) + "\n")

    # 封面配置：主标题固定为栏目名，文章名来自配置
    cover = {
        "show_name": cfg.get("show_name", "A股盘面吐槽大会"),
        "article_title": cfg.get("article_title", "今天这盘面"),
        "episode": cfg.get("episode", ""),
        "date_label": cfg.get("date_label", ""),
        "market_mood": cfg.get("market_mood", ""),
        "ticker": cfg.get("ticker", ""),
        "stats": cfg.get("cover_stats", []),
    }
    save_json(os.path.join(SRC, "cover.json"), cover)
    log(f"简介生成：{out_desc}")
    log(f"标签生成：{out_tags}（{len(tags)} 个）")
    log("封面配置：src/cover.json")


if __name__ == "__main__":
    main()
