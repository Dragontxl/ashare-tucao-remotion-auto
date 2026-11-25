# -*- coding: utf-8 -*-
"""从 R2 下载已有产物并上传 B站（云端「仅上传」模式）。

用法：
    python scripts/upload_from_r2.py --date 20261120

流程：
    1. 列出 R2 中 `ashare-tucao/` 前缀的对象
    2. 找到匹配指定日期的最新运行记录
    3. 下载 video_final.mp4 / cover.png / B站简介.md / tags.txt 到 out/
    4. 调用 upload_bilibili.py 上传 B站
    5. 保存 bilibili_result.json 到 out/
"""
import argparse
import os
import sys
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, OUT, CONFIG_DIR, SCRIPTS, load_config, log, date8_from, cn_date_from_8


def r2_client():
    """创建 R2 (S3) 客户端。"""
    cfg = load_config()
    r2 = cfg.get("r2", {})
    # CI 中 GitHub Secrets 是权威来源，环境变量优先于 config.json
    bucket = os.environ.get("R2_BUCKET_NAME") or r2.get("bucket", "")
    access_key = os.environ.get("R2_ACCESS_KEY_ID") or r2.get("access_key_id", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY") or r2.get("secret_access_key", "")
    endpoint = os.environ.get("R2_ENDPOINT_URL") or r2.get("endpoint", "")

    if not bucket or not access_key or not secret_key or not endpoint:
        raise RuntimeError("R2 未配置：请检查 config.json 的 r2 字段或环境变量")

    import boto3
    from botocore.config import Config
    client = boto3.client(
        "s3",
        endpoint_url=endpoint.rstrip("/"),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    return client, bucket


def r2_prefix(cfg=None):
    """R2 对象前缀：环境变量 R2_PREFIX 优先，其次 config.r2.prefix。"""
    cfg = cfg or {}
    r2 = cfg.get("r2", {}) if isinstance(cfg.get("r2"), dict) else {}
    prefix = (os.environ.get("R2_PREFIX") or r2.get("prefix") or "ashare-tucao/").strip("/")
    return (prefix + "/") if prefix else ""


def find_latest_run(client, bucket, target_date8, prefix=None):
    """找到匹配指定日期的最新 R2 运行前缀。

    R2 前缀格式：<prefix>/YYYYMMDD_HHMMSS
    匹配策略：前缀中日期部分等于 target_date8
    """
    prefix = (prefix or "ashare-tucao/").strip("/") + "/"
    date_prefix = f"{target_date8}_"

    # 列出所有匹配前缀的对象
    all_prefixes = set()
    cursor = None
    while True:
        options = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if cursor:
            options["ContinuationToken"] = cursor
        resp = client.list_objects_v2(**options)
        for obj in resp.get("Contents", []):
            # 提取运行前缀：ashare-tucao/YYYYMMDD_HHMMSS/filename
            key = obj["Key"]
            parts = key[len(prefix):].split("/")
            if len(parts) >= 2:
                run_prefix = prefix + parts[0]
                all_prefixes.add(run_prefix)
        if resp.get("IsTruncated"):
            cursor = resp.get("NextContinuationToken")
        else:
            break

    # 筛选匹配日期的运行，取最新的（按时间戳排序）
    matching = [p for p in all_prefixes if p.endswith(date_prefix) or
                os.path.basename(p).startswith(date_prefix)]
    if not matching:
        # 退而求其次：找日期部分匹配的
        for p in all_prefixes:
            base = os.path.basename(p)
            if base[:8] == target_date8:
                matching.append(p)

    if not matching:
        raise RuntimeError(f"未找到 {target_date8} 的 R2 运行记录，无法下载产物")

    # 按时间戳降序排列，取最新
    matching.sort(reverse=True)
    return matching[0]


def download_from_r2(client, bucket, run_prefix, files):
    """从 R2 下载指定文件到 out/ 目录。"""
    os.makedirs(OUT, exist_ok=True)
    downloaded = {}
    for fname in files:
        key = f"{run_prefix}/{fname}"
        local_path = os.path.join(OUT, fname)
        try:
            client.download_file(bucket, key, local_path)
            size = os.path.getsize(local_path)
            downloaded[fname] = local_path
            log(f"已下载：{fname}（{size} 字节）")
        except Exception as e:
            log(f"下载失败：{fname} - {e}")
            downloaded[fname] = None
    return downloaded


def title_from_desc(path):
    """从 B站简介.md 的首行取文稿标题；取不到返回空串。"""
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip().lstrip("#").strip()
                if s:
                    return s[:80]
    except OSError:
        return ""
    return ""


def resolve_title(explicit, desc_path, cfg_title, date8_str):
    """标题优先级：手动填写 > 文稿标题（简介首行）> config > 日期兜底。"""
    if explicit and explicit.strip():
        return explicit.strip()[:80], "手动填写"
    t = title_from_desc(desc_path)
    if t:
        return t, "文稿标题（B站简介首行）"
    if cfg_title and str(cfg_title).strip():
        return str(cfg_title).strip()[:80], "config.article_title"
    return f"A股盘面吐槽 {cn_date_from_8(date8_str)}", "日期兜底"


def main():
    ap = argparse.ArgumentParser(description="从 R2 下载产物并上传 B站")
    ap.add_argument("--date", default=date8_from(""), help="交易日 YYYYMMDD")
    ap.add_argument("--run-prefix", default="", help="直接指定 R2 运行前缀（跳过查找）")
    ap.add_argument("--title", default="", help="视频标题；留空则用文稿标题")
    args = ap.parse_args()

    date8_str = date8_from(args.date)
    log(f"运行日期：{date8_str}（{cn_date_from_8(date8_str)}）")

    cfg = load_config()

    client, bucket = r2_client()

    # 找到运行前缀
    if args.run_prefix:
        run_prefix = args.run_prefix
    else:
        run_prefix = find_latest_run(client, bucket, date8_str, r2_prefix(cfg))
    log(f"使用 R2 运行前缀：{run_prefix}")

    # 下载产物文件
    files_to_download = ["video_final.mp4", "cover.png", "B站简介.md", "tags.txt"]
    downloaded = download_from_r2(client, bucket, run_prefix, files_to_download)

    # 检查视频是否存在
    video_path = downloaded.get("video_final.mp4")
    if not video_path or not os.path.exists(video_path):
        raise RuntimeError(f"视频文件不存在，无法上传。请确认 R2 中已有该日期的运行产物。")

    cover_path = downloaded.get("cover.png") or ""
    desc_path = downloaded.get("B站简介.md") or ""
    tags_path = downloaded.get("tags.txt") or ""

    # 调用 upload_bilibili.py
    bili = cfg.get("bilibili", {}) if isinstance(cfg.get("bilibili"), dict) else {}
    cookies = os.environ.get("BILIBILI_COOKIES_FILE") or bili.get("cookies_file") \
        or os.path.join(CONFIG_DIR, "bilibili_cookies.json")
    title, title_source = resolve_title(args.title, desc_path, cfg.get("article_title"), date8_str)
    log(f"视频标题：{title}（来源：{title_source}）")

    cmd = [
        sys.executable, os.path.join(SCRIPTS, "upload_bilibili.py"),
        "--video", video_path,
        "--cover", cover_path if os.path.exists(cover_path) else "",
        "--cookies", cookies,
        "--title", title,
        "--desc-file", desc_path if os.path.exists(desc_path) else "",
        "--tags-file", tags_path if os.path.exists(tags_path) else "",
        "--date", date8_str,
        "--work-dir", os.path.join(OUT, "bilibili_work"),
    ]
    if bili.get("headless") is False:
        cmd.append("--show-browser")

    log("=" * 56)
    log("上传到 B站")
    log("=" * 56)
    import subprocess
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"B站上传失败（退出码 {r.returncode}）")

    # 保存结果
    result_path = os.path.join(OUT, "bilibili_result.json")
    if os.path.exists(result_path):
        log(f"B站上传结果已保存：{result_path}")
    else:
        log("B站上传完成（结果文件未生成，可能由 upload_bilibili.py 内部处理）")

    log("=" * 56)
    log("仅上传B站模式完成！")
    log("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
