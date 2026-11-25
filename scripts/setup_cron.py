# -*- coding: utf-8 -*-
"""创建/更新 cron-job.org 定时任务。

默认：每周一至周五 17:25（Asia/Shanghai）POST GitHub workflow_dispatch，
触发 ashare-tucao-remotion-auto 生成视频并自动上传 B站。

用法：
    python scripts/setup_cron.py                 # 创建或更新
    python scripts/setup_cron.py --dry-run       # 只打印，不调用 API
    python scripts/setup_cron.py --time 17:25
    python scripts/setup_cron.py --no-upload     # 只生成，不上传（调试用）

配置读取顺序：
    cron-job.org API Key: --api-key / CRONJOB_API_KEY / config.cronjob.api_key
    GitHub PAT:           --github-token / GH_PAT / config.github.pat
    仓库:                  --repo / GH_OWNER + GH_REPO / config.github.owner + repo
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, log  # noqa: E402

CRON_API = "https://api.cron-job.org"
DEFAULT_TITLE = "A股盘面吐槽 17:25 生成并上传B站"


def resolve_repo(cfg, explicit):
    if explicit:
        if "/" not in explicit:
            raise SystemExit("--repo 需要 owner/repo 格式")
        return explicit
    gh = cfg.get("github", {}) if isinstance(cfg.get("github"), dict) else {}
    owner = os.environ.get("GH_OWNER") or gh.get("owner")
    repo = os.environ.get("GH_REPO") or gh.get("repo")
    if not owner or not repo:
        raise SystemExit("未配置仓库：请传 --repo owner/repo，或在 config.github 中填写 owner/repo")
    return f"{owner}/{repo}"


def resolve_token(cfg, explicit):
    gh = cfg.get("github", {}) if isinstance(cfg.get("github"), dict) else {}
    token = explicit or os.environ.get("GH_PAT") or gh.get("pat")
    if not token:
        raise SystemExit("未配置 GitHub PAT：请传 --github-token，或设置 GH_PAT，或在 config.github.pat 中填写")
    return token


def resolve_cron_key(cfg, explicit):
    cj = cfg.get("cronjob", {}) if isinstance(cfg.get("cronjob"), dict) else {}
    key = explicit or os.environ.get("CRONJOB_API_KEY") or cj.get("api_key")
    if not key:
        raise SystemExit("未配置 cron-job.org API Key：请传 --api-key，或设置 CRONJOB_API_KEY，或在 config.cronjob.api_key 中填写")
    return key


def parse_time(value):
    try:
        hh, mm = str(value).strip().split(":", 1)
        hour, minute = int(hh), int(mm)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, AttributeError):
        raise SystemExit(f"时间格式应为 HH:MM，例如 17:25，收到：{value}")


def redact(value, keep=8):
    value = str(value or "")
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "..." + value[-4:]


def build_job(args, repo, gh_token):
    hour, minute = parse_time(args.time)
    title = args.title or DEFAULT_TITLE
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
           f"{args.workflow}/dispatches")
    # 注意：workflow_dispatch API 只接受字符串，传布尔值会返回 422
    # `Invalid request. For 'additionalProperties', true is not a string.`
    inputs = {"upload": "false" if args.no_upload else "true"}
    if args.force:
        inputs["force"] = "true"
    body = json.dumps({"ref": args.ref, "inputs": inputs},
                      ensure_ascii=False, separators=(",", ":"))
    return {
        "title": title,
        "url": url,
        "enabled": True,
        "saveResponses": True,
        "requestMethod": 1,  # POST
        "requestTimeout": 30,
        "redirectSuccess": False,
        "folderId": 0,
        "type": 0,
        "schedule": {
            "timezone": "Asia/Shanghai",
            "hours": [hour],
            "minutes": [minute],
            "mdays": [-1],
            "months": [-1],
            "wdays": [1, 2, 3, 4, 5],
            "expiresAt": 0,
        },
        "extendedData": {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {gh_token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            "body": body,
        },
    }


def api_request(method, path, key, payload=None, allow=()):
    import requests

    resp = requests.request(
        method,
        f"{CRON_API}{path}",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "ashare-tucao-auto",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 300 and resp.status_code not in tuple(allow):
        raise SystemExit(f"cron-job.org API 失败：HTTP {resp.status_code} {resp.text[:500]}")
    if not resp.text.strip():
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


def find_job(jobs, title):
    for item in jobs.get("jobs", []) or []:
        if item.get("title") == title:
            return item
    return None


def main():
    ap = argparse.ArgumentParser(description="创建/更新 cron-job.org 定时任务")
    ap.add_argument("--title", default=DEFAULT_TITLE)
    ap.add_argument("--time", default="17:25", help="Asia/Shanghai 时区的 HH:MM")
    ap.add_argument("--ref", default="main", help="GitHub 分支/标签")
    ap.add_argument("--workflow", default="generate.yml", help="workflow 文件名")
    ap.add_argument("--repo", help="owner/repo")
    ap.add_argument("--api-key", help="cron-job.org API Key")
    ap.add_argument("--github-token", help="GitHub PAT（写入 cron 请求头）")
    ap.add_argument("--no-upload", action="store_true", help="只生成，不上传 B站")
    ap.add_argument("--force", action="store_true", help="非交易日也运行")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    repo = resolve_repo(cfg, args.repo)
    gh_token = resolve_token(cfg, args.github_token)
    cron_key = resolve_cron_key(cfg, args.api_key)
    job = build_job(args, repo, gh_token)

    print("=" * 60)
    print(f"仓库：{repo}")
    print(f"时间：每周一至周五 {args.time}（Asia/Shanghai）")
    print(f"URL：{job['url']}")
    print(f"Body：{job['extendedData']['body']}")
    print(f"GitHub PAT：{redact(gh_token)}")
    print("=" * 60)

    if args.dry_run:
        safe = json.loads(json.dumps(job, ensure_ascii=False))
        safe["extendedData"]["headers"]["Authorization"] = f"Bearer {redact(gh_token)}"
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0

    existing = find_job(api_request("GET", "/jobs", cron_key), job["title"])
    if existing:
        job_id = existing["jobId"]
        # cron-job.org：更新用 PATCH /jobs/{jobId}（PUT 会 404）
        api_request("PATCH", f"/jobs/{job_id}", cron_key, {"job": job}, allow=(404, 405))
        log(f"已更新 cron-job.org 任务：jobId={job_id}")
    else:
        result = api_request("PUT", "/jobs", cron_key, {"job": job})
        job_id = result.get("jobId")
        log(f"已创建 cron-job.org 任务：jobId={job_id}")

    detail = api_request("GET", f"/jobs/{job_id}", cron_key)
    jd = detail.get("jobDetails", {}) or {}
    log(f"标题：{jd.get('title')}")
    log(f"下次执行：{jd.get('nextExecution')}")
    schedule = jd.get("schedule", {}) or {}
    log(f"时区/时间：{schedule.get('timezone')} "
        f"{schedule.get('hours')}:{schedule.get('minutes')} wdays={schedule.get('wdays')}")
    log(f"启用：{jd.get('enabled')}")
    body = ((jd.get("extendedData") or {}).get("body")) or ""
    log(f"Body：{body}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
