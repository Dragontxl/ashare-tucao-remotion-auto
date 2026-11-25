# -*- coding: utf-8 -*-
"""Step 4：用 Remotion 渲染视频与封面（本地 / CI 通用）。

为什么不是「开 4 个 render 进程」？
------------------------------------------------------------------
参考项目 F:/Programs/pexel-remotion 的「4 路」其实是 4 个 GitHub Actions
job（4 台机器，见其 matrix.shard: [1,2,3,4]），每台机器再处理若干短镜头。
在单机上开 4 个 1080p render 进程，等于 4 套 node + Chrome + ffmpeg +
webpack，实测峰值约 3.9-4.2GB；再叠加系统里已有的 Chrome（约 5GB），
16GB 机器会直接触发 malloc 失败。

本项目的单机方案：
1. 先 `remotion bundle` 打包一次，所有渲染共用，避免重复 webpack。
2. 单进程开 N 个渲染 tab（`--concurrency=N`，默认 4），这是 Remotion 官方
   的并行渲染方式；实测 4 tab 峰值仅约 1.6GB。
3. 按可用内存和 CPU 自动决定 tab 数；失败时 tab 数 4 → 2 → 1 降级，
   编码档位 veryfast/crf20 → ultrafast/crf22。
4. 按帧区间分块渲染，某块失败只重跑该块，最后 ffmpeg 无损拼接并混音。

环境变量：
    RENDER_CONCURRENCY=4       # 期望的渲染 tab 数（默认 config.render.concurrency）
    RENDER_CHUNK_FRAMES=3200   # 单块帧数
    RENDER_FORCE=1             # 强制重新渲染
    RENDER_SKIP_BUNDLE=1       # 复用 out/_bundle
"""
import os
import sys
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, PUBLIC, OUT, load_config, load_json, log

cfg = load_config()
tl = load_json(os.path.join(ROOT, "src", "timeline.json"), {})
TOTAL = int(tl.get("totalFrames") or 0)
if TOTAL <= 0:
    raise RuntimeError("src/timeline.json 无有效 totalFrames，请先运行 build_audio.py")

RENDER_CFG = cfg.get("render", {}) if isinstance(cfg.get("render"), dict) else {}
WANT_TABS = int(os.environ.get("RENDER_CONCURRENCY") or RENDER_CFG.get("concurrency", 4))
WANT_TABS = max(1, min(WANT_TABS, 16))
CHUNK_FRAMES = int(os.environ.get("RENDER_CHUNK_FRAMES")
                   or RENDER_CFG.get("chunk_frames", 3200))
MEMORY_PER_TAB_GB = float(RENDER_CFG.get("memory_per_tab_gb", 0.45))
MEMORY_RESERVE_GB = float(RENDER_CFG.get("memory_reserve_gb", 0.8))
FORCE = os.environ.get("RENDER_FORCE", "").lower() in ("1", "true", "yes")
SKIP_BUNDLE = os.environ.get("RENDER_SKIP_BUNDLE", "").lower() in ("1", "true", "yes")
MIN_SEGMENT_BYTES = 100_000
MAX_ATTEMPTS = 4

ENCODE_ARGS = [
    "--codec=h264",
    "--pixel-format=yuv420p",
    "--muted",                 # 分段不带音轨，最后统一混入完整配音
    "--image-format=jpeg",
    "--jpeg-quality=85",
]
# 质量与内存的两档编码：先 veryfast，失败后降到 ultrafast
PRESETS = [
    {"preset": "veryfast", "crf": "20"},
    {"preset": "ultrafast", "crf": "22"},
]

BUNDLE_DIR = os.path.join(OUT, "_bundle")
SEGMENT_DIR = os.path.join(OUT, "_segments")


# ── 环境 ────────────────────────────────────────────────────────────────

def npx():
    return "npx.cmd" if os.name == "nt" else "npx"


def chrome_args():
    exe = os.environ.get("CHROME_EXECUTABLE", "")
    candidates = [exe]
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("PROGRAMW6432"), r"C:\Program Files", r"D:\Program Files",
                 r"C:\Program Files (x86)", r"D:\Program Files (x86)"):
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    candidates += ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
    for c in candidates:
        if c and os.path.exists(c):
            return [f"--browser-executable={c}"]
    return []


def run(cmd, desc):
    log(f"{desc} ...")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"命令失败（{desc}）：{' '.join(cmd)}")


# ── 资源准入 ────────────────────────────────────────────────────────────

def available_gb():
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:  # noqa: BLE001
        return None


def cpu_count():
    return os.cpu_count() or 2


def allowed_tabs(requested):
    """按可用内存与 CPU 核数计算本次渲染 tab 数。"""
    limit = min(requested, max(1, cpu_count()))
    avail = available_gb()
    if avail is None:
        return max(1, min(limit, 2)), None
    fit = int((avail - MEMORY_RESERVE_GB) // MEMORY_PER_TAB_GB)
    if fit < 1:
        fit = 1
    return max(1, min(limit, fit)), avail


# ── 打包 ────────────────────────────────────────────────────────────────

def ensure_bundle():
    if SKIP_BUNDLE and os.path.isdir(BUNDLE_DIR):
        log(f"复用已有 bundle：{BUNDLE_DIR}")
        return BUNDLE_DIR
    if os.path.isdir(BUNDLE_DIR):
        import shutil
        shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
    run([npx(), "remotion", "bundle", "src/index.ts",
         "--out-dir", BUNDLE_DIR, "--log=error"], "打包 Remotion 项目")
    if not os.path.isdir(BUNDLE_DIR):
        raise RuntimeError(f"打包失败，未生成目录：{BUNDLE_DIR}")
    log(f"打包完成：{BUNDLE_DIR}")
    return BUNDLE_DIR


# ── 分块 ────────────────────────────────────────────────────────────────

def split_ranges(total, size):
    """按固定大小切分 0..total-1，返回 [(start, end), ...]，首尾相接无空隙。"""
    size = max(1, size)
    ranges = []
    start = 0
    while start < total:
        end = min(start + size - 1, total - 1)
        ranges.append((start, end))
        start = end + 1
    return ranges


def segment_path(index):
    return os.path.join(SEGMENT_DIR, f"part{index}.mp4")


def segment_ready(index):
    p = segment_path(index)
    return (not FORCE) and os.path.exists(p) and os.path.getsize(p) > MIN_SEGMENT_BYTES


def render_segment(index, start, end, entry, tabs, quality):
    """渲染单个分块（tab 并发），只尝试一次。"""
    out = segment_path(index)
    if os.path.exists(out):
        try:
            os.remove(out)
        except OSError:
            pass
    q = PRESETS[min(quality, len(PRESETS) - 1)]
    args = [npx(), "remotion", "render", entry, "StockRecap", out,
            f"--frames={start}-{end}",
            f"--concurrency={tabs}",
            f"--x264-preset={q['preset']}",
            f"--crf={q['crf']}",
            "--log=error"] + ENCODE_ARGS + chrome_args()
    log(f"渲染第{index}块（帧 {start}-{end}，{tabs} tab，{q['preset']}/crf{q['crf']}）")
    r = subprocess.run(args, cwd=ROOT)
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > MIN_SEGMENT_BYTES
    if not ok:
        if os.path.exists(out) and os.path.getsize(out) <= MIN_SEGMENT_BYTES:
            try:
                os.remove(out)
            except OSError:
                pass
        raise RuntimeError(f"第{index}块失败（帧 {start}-{end}，退出码 {r.returncode}）")
    log(f"第{index}块完成：{out}")
    return out


# ── 主渲染流程 ──────────────────────────────────────────────────────────

def render_video():
    os.makedirs(SEGMENT_DIR, exist_ok=True)
    ranges = split_ranges(TOTAL, CHUNK_FRAMES)
    todo = [(i + 1, s, e) for i, (s, e) in enumerate(ranges)
            if FORCE or not segment_ready(i + 1)]

    if todo:
        entry = ensure_bundle()
    else:
        entry = BUNDLE_DIR if os.path.isdir(BUNDLE_DIR) else "src/index.ts"

    tabs, avail = allowed_tabs(WANT_TABS)
    if avail is not None:
        log(f"可用内存 {avail:.1f}GB / {cpu_count()} 核，"
            f"渲染并发 {tabs} 个 tab（期望 {WANT_TABS}）")
    else:
        log(f"未安装 psutil，按 {tabs} 个 tab 渲染")

    if not todo:
        log("所有分块已完成，跳过渲染（RENDER_FORCE=1 可强制重来）")
    else:
        log(f"视频总帧 {TOTAL}，共 {len(ranges)} 块，待渲染 {len(todo)} 块")

    quality = 0
    for index, start, end in todo:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                render_segment(index, start, end, entry, tabs, quality)
                break
            except Exception as exc:  # noqa: BLE001
                log(f"{exc}")
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError(f"第{index}块重试 {MAX_ATTEMPTS} 次仍失败") from exc
                # 降级：减少 tab，必要时切换更省内存的编码档位
                if tabs > 1:
                    tabs = max(1, tabs // 2)
                elif quality < len(PRESETS) - 1:
                    quality += 1
                    q = PRESETS[quality]
                    log(f"切换编码档位：{q['preset']}/crf{q['crf']}")
                else:
                    log("等待内存释放后重试……")
                    time.sleep(15)
                log(f"{max(8, attempt * 8)} 秒后重试第{index}块（{tabs} tab）")
                time.sleep(max(8, attempt * 8))

    files = [segment_path(i + 1) for i in range(len(ranges))]
    missing = [p for p in files
               if not (os.path.exists(p) and os.path.getsize(p) > MIN_SEGMENT_BYTES)]
    if missing:
        raise RuntimeError("分块缺失，无法拼接：" + ", ".join(missing))

    merged = os.path.join(OUT, "video_silent.mp4")
    concat = os.path.join(SEGMENT_DIR, "concat.txt")
    with open(concat, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{p}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
         "-c", "copy", merged], f"拼接 {len(files)} 块视频")

    final = os.path.join(OUT, "video_final.mp4")
    voice = os.path.join(PUBLIC, "voiceover.mp3")
    run(["ffmpeg", "-y", "-i", merged, "-i", voice,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", final], "合成音轨")
    log(f"视频成品：{final}")
    return final


def render_cover():
    out = os.path.join(OUT, "cover.png")
    if os.path.exists(out) and not FORCE:
        log(f"封面已存在，跳过（RENDER_FORCE=1 可强制重来）：{out}")
        return out
    entry = BUNDLE_DIR if os.path.isdir(BUNDLE_DIR) else "src/index.ts"
    run([npx(), "remotion", "still", entry, "Cover", out,
         "--frame=0"] + chrome_args() + ["--log=error"], "渲染封面")
    log(f"封面成品：{out}")
    return out


def main():
    render_video()
    render_cover()
    log("渲染全部完成")


if __name__ == "__main__":
    main()