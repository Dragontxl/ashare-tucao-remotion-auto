# -*- coding: utf-8 -*-
"""写入 GitHub Actions Secrets（本地一次性配置用）。

用法：
    # 从文件写入（推荐用于 B站 Cookie）
    python scripts/set_secret.py BILIBILI_COOKIES --file config/bilibili_cookies.json

    # 直接写入字符串
    python scripts/set_secret.py AGNES_API_KEY --value "sk-..."

    # 指定仓库 / Token（默认读取 config/config.json 的 github 字段）
    python scripts/set_secret.py R2_BUCKET_NAME --value "bucket" \
        --repo Dragontxl/ashare-tucao-remotion-auto --token ghp_xxx

依赖：requests、PyNaCl（requirements.txt 已包含）。
"""
import argparse
import base64
import json
import os
import sys

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


def read_value(args):
    if args.file:
        with open(args.file, "rb") as f:
            return f.read()
    if args.value is not None:
        return args.value.encode("utf-8")
    raise SystemExit("请通过 --file 或 --value 提供 Secret 内容")


def put_secret(repo, token, name, value):
    """写入一个 GitHub Actions Secret。value 为 bytes。"""
    import requests
    from nacl import encoding, public

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ashare-tucao-auto",
    }

    key_resp = requests.get(f"{API}/repos/{repo}/actions/secrets/public-key",
                            headers=headers, timeout=30)
    if key_resp.status_code != 200:
        raise RuntimeError(f"读取公钥失败：HTTP {key_resp.status_code} {key_resp.text[:300]}")
    key_data = key_resp.json()
    key_id = key_data["key_id"]
    public_key = key_data["key"]

    pk = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk)
    encrypted = base64.b64encode(sealed.encrypt(value)).decode("utf-8")

    put_resp = requests.put(
        f"{API}/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=30,
    )
    if put_resp.status_code not in (201, 204):
        raise RuntimeError(f"写入失败：HTTP {put_resp.status_code} {put_resp.text[:300]}")


def main():
    ap = argparse.ArgumentParser(description="写入 GitHub Actions Secret")
    ap.add_argument("name", help="Secret 名称，如 BILIBILI_COOKIES")
    ap.add_argument("--file", help="从文件读取内容")
    ap.add_argument("--value", help="直接指定字符串内容")
    ap.add_argument("--repo", help="owner/repo")
    ap.add_argument("--token", help="GitHub PAT（默认读 GH_PAT 或 config.github.pat）")
    args = ap.parse_args()

    cfg = load_config()
    repo = resolve_repo(cfg, args.repo)
    token = resolve_token(cfg, args.token)
    value = read_value(args)

    try:
        put_secret(repo, token, args.name, value)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

    log(f"已写入 Secret：{args.name} -> {repo}（{len(value)} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
