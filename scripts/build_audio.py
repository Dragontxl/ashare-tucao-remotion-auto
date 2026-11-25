# -*- coding: utf-8 -*-
"""Step 2a：逐句 TTS 配音 + 生成精确时间轴 timeline.json + 拼接完整音轨。"""
import os
import sys
import time
import asyncio
import subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, SRC, AUDIO, PUBLIC, load_config, load_json, save_json, log
import edge_tts

cfg = load_config()
FPS = int(cfg.get("fps", 30))
GAP = float(cfg.get("gap", 0.18))
VOICE = cfg.get("voice", "zh-CN-YunxiNeural")
RATE = cfg.get("rate", "+6%")

sentences = load_json(os.path.join(SRC, "sentences.json"))
if not sentences:
    raise FileNotFoundError("src/sentences.json 不存在，请先运行 generate_script.py")


def dur(path):
    """返回音频时长（秒）；文件损坏/缺失时返回 0，便于断点续传判断。"""
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        return 0.0
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True)
        return float(r.stdout.strip())
    except (ValueError, OSError):
        return 0.0


async def tts_save(text, out, retries=4):
    """带重试的 TTS 合成，应对网络抖动。"""
    last = None
    for attempt in range(retries):
        try:
            comm = edge_tts.Communicate(text, VOICE, rate=RATE)
            await comm.save(out)
            if dur(out) > 0.1:
                return
            last = RuntimeError("生成音频为空")
        except Exception as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise last


async def gen_all():
    # 断点续传：已存在且有效的片段跳过
    for s in sentences:
        out = os.path.join(AUDIO, f"seg_{s['id']:03d}.mp3")
        if dur(out) > 0.1:
            continue
        await tts_save(s["text"], out)
        log(f"[{s['id']:02d}/{len(sentences)}] {s['text'][:18]}...")


def main():
    asyncio.run(gen_all())

    timeline = []
    cursor = 0.0
    for i, s in enumerate(sentences):
        seg = os.path.join(AUDIO, f"seg_{s['id']:03d}.mp3")
        if not os.path.exists(seg):
            raise FileNotFoundError(f"配音片段缺失：{seg}")
        d = dur(seg)
        item = dict(s)
        item["startSec"] = round(cursor, 3)
        item["endSec"] = round(cursor + d, 3)
        item["startFrame"] = round(cursor * FPS)
        item["endFrame"] = round((cursor + d) * FPS)
        # 消除取整间隙：endFrame 延伸到下一句 startFrame（由下一段覆盖时修正）
        timeline.append(item)
        cursor = end = cursor + d + (GAP if i < len(sentences) - 1 else 0)

    # 消除场景间隙，避免切换瞬间闪现结尾卡
    for i in range(len(timeline) - 1):
        timeline[i]["endFrame"] = timeline[i + 1]["startFrame"]
    timeline[-1]["endFrame"] = round(cursor * FPS)

    total_frames = round(cursor * FPS)
    save_json(os.path.join(SRC, "timeline.json"), {
        "fps": FPS,
        "totalSec": round(cursor, 3),
        "totalFrames": total_frames,
        "items": timeline,
    })

    # 句间静音
    silence = os.path.join(AUDIO, "silence.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", str(GAP), silence], capture_output=True)

    listfile = os.path.join(AUDIO, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for i, s in enumerate(sentences):
            f.write(f"file 'seg_{s['id']:03d}.mp3'\n")
            if i < len(sentences) - 1:
                f.write("file 'silence.mp3'\n")

    voiceover = os.path.join(PUBLIC, "voiceover.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                    "-c:a", "libmp3lame", "-q:a", "2", voiceover], capture_output=True)

    actual = dur(voiceover)
    log(f"配音完成：{len(sentences)} 句 | 时长 {actual:.2f}s | 总帧 {total_frames}")
    log(f"音轨：{voiceover}")


if __name__ == "__main__":
    main()
