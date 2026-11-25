# -*- coding: utf-8 -*-
"""扫码刷新 B站 Cookie，并自动写入 GitHub Actions Secret。

用法（项目根目录）：
    python scripts/refresh_bili_cookie.py

流程：
    1. 打开浏览器，用 B站 App 扫码登录
    2. Cookie 保存到 config/bilibili_cookies.json
    3. 自动调用 scripts/set_secret.py 写入 BILIBILI_COOKIES

如果只想刷新本地 Cookie、不写 GitHub Secret：
    python scripts/refresh_bili_cookie.py --no-upload-secret
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, CONFIG_DIR, log  # noqa: E402

COOKIES = os.path.join(CONFIG_DIR, "bilibili_cookies.json")


def main():
    ap = argparse.ArgumentParser(description="扫码刷新 B站 Cookie 并写入 GitHub Secret")
    ap.add_argument("--timeout", type=int, default=300, help="等待扫码秒数")
    ap.add_argument("--cookies", default=COOKIES)
    ap.add_argument("--no-upload-secret", action="store_true", help="只刷新本地 Cookie")
    args = ap.parse_args()

    login = os.path.join(ROOT, "scripts", "bili_login.py")
    r = subprocess.run([sys.executable, login, "--timeout", str(args.timeout),
                        "--cookies", args.cookies])
    if r.returncode != 0:
        raise SystemExit("扫码登录失败，未写入 Secret。")

    if args.no_upload_secret:
        log("已刷新本地 Cookie，未写入 GitHub Secret。")
        return 0

    set_secret = os.path.join(ROOT, "scripts", "set_secret.py")
    r = subprocess.run([sys.executable, set_secret, "BILIBILI_COOKIES",
                        "--file", args.cookies])
    if r.returncode != 0:
        raise SystemExit("Cookie 已刷新，但写入 GitHub Secret 失败。")
    log("B站 Cookie 已刷新并写入 GitHub Secret。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
