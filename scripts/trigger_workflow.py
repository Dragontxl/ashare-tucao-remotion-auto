# -*- coding: utf-8 -*-
"""手动触发 GitHub Actions 工作流（本地调试用）。

用法：
    python scripts/trigger_workflow.py                 # 默认 upload=true
    python scripts/trigger_workflow.py --no-upload     # 只生成，不上传
    python scripts/trigger_workflow.py --wait          # 触发后等待完成
    python scripts/trigger_workflow.py --date 20261125 --force
"""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, log  # noqa: E402

API = "https://api.github.com"


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
        raise SystemExit("未配置 GitHub PAT：请传 --token，或设置 GH_PAT，或在 config.github.pat 中填写")
    return token


def headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ashare-tucao-auto",
    }


def main():
    ap = argparse.ArgumentParser(description="手动触发 GitHub Actions")
    ap.add_argument("--repo", help="owner/repo")
    ap.add_argument("--token", help="GitHub PAT")
    ap.add_argument("--ref", default="main")
    ap.add_argument("--workflow", default="generate.yml")
    ap.add_argument("--date", default="", help="交易日 YYYYMMDD")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--upload-only", action="store_true")
    ap.add_argument("--wait", action="store_true", help="等待工作流结束")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--interval", type=int, default=15)
    args = ap.parse_args()

    cfg = load_config()
    repo = resolve_repo(cfg, args.repo)
    token = resolve_token(cfg, args.token)

    import requests

    # workflow_dispatch API 只接受字符串；传布尔值会 422
    inputs = {"upload": "false" if args.no_upload else "true"}
    if args.date:
        inputs["date"] = args.date
    if args.force:
        inputs["force"] = "true"
    if args.skip_llm:
        inputs["skip_llm"] = "true"
    if args.upload_only:
        inputs["upload_only"] = "true"

    dispatched_at = datetime.datetime.now(datetime.timezone.utc)
    url = f"{API}/repos/{repo}/actions/workflows/{args.workflow}/dispatches"
    resp = requests.post(url, headers=headers(token),
                         json={"ref": args.ref, "inputs": inputs}, timeout=30)
    if resp.status_code != 204:
        raise SystemExit(f"触发失败：HTTP {resp.status_code} {resp.text[:500]}")
    log(f"已触发 {repo} / {args.workflow}（ref={args.ref}，inputs={inputs}）")

    if not args.wait:
        log("未指定 --wait，可到 GitHub Actions 页面查看运行状态。")
        return 0

    # 找到刚创建的 run
    run = None
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        r = requests.get(
            f"{API}/repos/{repo}/actions/workflows/{args.workflow}/runs?per_page=10",
            headers=headers(token), timeout=30)
        if r.status_code == 200:
            for item in r.json().get("workflow_runs", []) or []:
                created = item.get("created_at", "")
                try:
                    dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if dt >= dispatched_at - datetime.timedelta(seconds=10):
                    run = item
                    break
        if run:
            break
        time.sleep(3)

    if not run:
        raise SystemExit("未找到刚触发的运行记录，请到 Actions 页面确认。")

    run_id = run["id"]
    log(f"运行地址：{run['html_url']}")
    while time.time() < deadline:
        r = requests.get(f"{API}/repos/{repo}/actions/runs/{run_id}",
                         headers=headers(token), timeout=30)
        if r.status_code == 200:
            data = r.json()
            status = data.get("status")
            conclusion = data.get("conclusion")
            log(f"状态：{status} / {conclusion or '-'}")
            if status == "completed":
                return 0 if conclusion == "success" else 1
        time.sleep(max(5, args.interval))
    raise SystemExit("等待超时，请到 Actions 页面查看。")


if __name__ == "__main__":
    sys.exit(main())
