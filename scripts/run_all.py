# -*- coding: utf-8 -*-
"""全流程编排：

  交易日判定 -> 获取当日复盘文档 -> 毒舌文稿 -> 配音/时间轴
  -> 真实行情/图表 -> 4 路并发渲染视频/封面 -> 简介/标签 ->（可选）上传B站

用法：
  python scripts/run_all.py                          # 全流程（默认抓当日复盘 docx）
  python scripts/run_all.py --steps 1,2              # 只跑指定步骤
  python scripts/run_all.py --date 20260821          # 指定交易日
  python scripts/run_all.py --article input/a.docx   # 指定原文（本地或URL）
  python scripts/run_all.py --upload                 # 完成后上传B站
  python scripts/run_all.py --force                  # 非交易日也强制运行
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (ROOT, INPUT_DIR, CONFIG_DIR, SCRIPTS, date8, date8_from,
                    cn_date_from_8, load_config, log)

STEP_SCRIPTS = {
    1: "generate_script.py",
    2: "build_audio.py",
    2.5: "extract_stocks.py",   # 从时间轴提取股票名，补入 config.stocks（须在抓取行情前）
    3: "fetch_market_data.py",
    3.5: "make_charts.py",
    5: "generate_meta.py",   # 先生成 cover.json / 简介 / 标签（渲染依赖 cover.json）
    4: "render_video.py",    # 再渲染视频与封面
}
STEP_NAMES = {
    1: "生成毒舌文稿",
    2: "配音与时间轴",
    2.5: "提取股票名称",
    3: "抓取行情数据",
    3.5: "生成图表",
    5: "生成简介与标签",
    4: "并发渲染视频/封面",
}


def parse_steps(value):
    if not value or value == "all":
        return list(STEP_SCRIPTS.keys())
    steps = []
    for x in str(value).split(","):
        x = x.strip()
        if not x:
            continue
        num = float(x)
        num = int(num) if num.is_integer() else num
        if num not in STEP_SCRIPTS:
            raise ValueError(f"未知步骤：{x}（可选 1,2,2.5,3,3.5,4,5）")
        steps.append(num)
    return steps


def run_script(script, env=None):
    log("=" * 56)
    log(f"运行 {script}")
    log("=" * 56)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)], env=env)
    if r.returncode != 0:
        raise RuntimeError(f"步骤失败：{script}（退出码 {r.returncode}）")


def run_upload(date8_str, cfg):
    """调用 B站上传脚本。"""
    # generate_script.py 在子进程中已把 LLM 生成的标题写回 config.json，
    # 必须重新加载，否则会用旧的 __AUTO__ 哨兵值作为上传标题。
    cfg = load_config()
    video = os.path.join(ROOT, "out", "video_final.mp4")
    cover = os.path.join(ROOT, "out", "cover.png")
    if not os.path.exists(video):
        raise FileNotFoundError(f"视频不存在，无法上传：{video}")
    bili = cfg.get("bilibili", {}) if isinstance(cfg.get("bilibili"), dict) else {}
    cookies = os.environ.get("BILIBILI_COOKIES_FILE") or bili.get("cookies_file") \
        or os.path.join(CONFIG_DIR, "bilibili_cookies.json")
    cmd = [
        sys.executable, os.path.join(SCRIPTS, "upload_bilibili.py"),
        "--video", video,
        "--cover", cover if os.path.exists(cover) else "",
        "--cookies", cookies,
        "--title", cfg.get("article_title") or f"A股盘面吐槽 {cn_date_from_8(date8_str)}",
        "--desc-file", os.path.join(ROOT, "out", "B站简介.md"),
        "--tags-file", os.path.join(ROOT, "out", "tags.txt"),
        "--date", date8_str,
        "--work-dir", os.path.join(ROOT, "out", "bilibili_work"),
    ]
    if bili.get("headless") is False:
        cmd.append("--show-browser")
    log("=" * 56)
    log("上传到 B站")
    log("=" * 56)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"B站上传失败（退出码 {r.returncode}）")


def main():
    ap = argparse.ArgumentParser(description="A股盘面吐槽大会 全流程")
    ap.add_argument("--steps", default="all", help="all 或逗号分隔步骤号：1,2,3,3.5,4,5")
    ap.add_argument("--date", default=date8(), help="交易日 YYYYMMDD，默认今天")
    ap.add_argument("--article", default="auto",
                    help="auto=当日默认URL；也支持自定义URL / 本地 docx、md、txt")
    ap.add_argument("--force", action="store_true", help="非交易日也强制运行")
    ap.add_argument("--no-trading-check", action="store_true", help="跳过交易日检测")
    ap.add_argument("--strict-trading-check", action="store_true",
                    help="交易日接口异常时也停止（默认异常时继续并告警）")
    ap.add_argument("--skip-llm", action="store_true", help="使用内置降级文稿生成器")
    ap.add_argument("--concurrency", type=int, default=0,
                    help="渲染并发路数，默认取 config.render.concurrency（4）")
    ap.add_argument("--upload", action="store_true", help="全部完成后上传B站")
    ap.add_argument("--no-fetch-article", action="store_true", help="不下载原文，直接使用 input/article.md")
    args = ap.parse_args()

    date8_str = date8_from(args.date)
    log(f"运行日期：{date8_str}（{cn_date_from_8(date8_str)}）")
    cfg = load_config()

    steps = parse_steps(args.steps)
    need_pipeline = any(s in steps for s in (1, 2, 3, 3.5, 4, 5))

    # ---------- 0. 交易日判定 ----------
    if need_pipeline and not args.no_trading_check:
        from trading_day import check_trading_day
        status, reason = check_trading_day(date8_str)
        log(f"交易日判定：{reason}")
        if status is False and not args.force:
            print("[SKIP] 非交易日，流程停止。", flush=True)
            return 0
        if status is False and args.force:
            log("已指定 --force，非交易日继续运行")
        if status is None:
            if args.strict_trading_check and not args.force:
                print(f"[SKIP] 交易日判定失败且启用了严格模式，流程停止：{reason}", flush=True)
                return 0
            log("交易日判定接口异常，默认继续运行（可加 --strict-trading-check 改为停止）")
    elif not need_pipeline:
        log("仅运行部分步骤，跳过交易日判定")

    # ---------- 0.5 获取原文 ----------
    env = os.environ.copy()
    env["RUN_DATE"] = date8_str
    env["PYTHONUNBUFFERED"] = "1"
    if args.skip_llm:
        env["SKIP_LLM"] = "1"
    if args.concurrency and args.concurrency > 0:
        env["RENDER_CONCURRENCY"] = str(args.concurrency)

    article_path = os.path.join(INPUT_DIR, "article.md")
    fetch_needed = need_pipeline and 1 in steps and not args.no_fetch_article
    if fetch_needed:
        from fetch_article import fetch_article
        print("[STEP] 0/6 获取复盘原文", flush=True)
        try:
            article_path, origin = fetch_article(args.article, date8_str, cfg)
            log(f"原文来源：{origin}")
        except Exception as e:
            if args.force:
                print(f"[ERROR] 原文获取失败：{e}", flush=True)
                print("[ERROR] 非交易日强制运行时，当日默认复盘文档可能不存在。", flush=True)
                print("[ERROR] 请使用 --article 指定自定义原文 URL 或本地文件路径。", flush=True)
                print("[ERROR] 或使用 --no-fetch-article 跳过原文获取（需配合 --skip-llm）。", flush=True)
                sys.exit(1)
            else:
                print(f"[ERROR] 原文获取失败：{e}", flush=True)
                sys.exit(1)
    env["ARTICLE_PATH"] = article_path

    total = len(steps) + (1 if args.upload else 0)
    for idx, s in enumerate(steps, 1):
        print(f"[STEP] {idx}/{total} {STEP_NAMES[s]}", flush=True)
        run_script(STEP_SCRIPTS[s], env=env)

    if args.upload:
        print(f"[STEP] {total}/{total} 上传B站", flush=True)
        run_upload(date8_str, cfg)

    log("=" * 56)
    log("全流程完成！产物在 out/ 目录：")
    log("  out/video_final.mp4")
    log("  out/cover.png")
    log("  out/B站简介.md")
    log("  out/tags.txt")
    if args.upload:
        log("  out/bilibili_result.json（B站上传结果）")
    log("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
