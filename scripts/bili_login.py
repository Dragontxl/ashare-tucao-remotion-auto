#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B站 本地扫码登录助手

为什么需要它：
    B站 的 SESSDATA 是 httpOnly Cookie，浏览器控制台复制不到；
    手动从开发者工具里翻也不方便。这个脚本打开一个真实 Chrome 窗口，
    你扫码确认后由 Playwright 直接把全部 Cookie 导出到
    config/bilibili_cookies.json，全程不需要手工复制。

用法（项目根目录）：

    python scripts/bili_login.py              # 扫码登录并保存
    python scripts/bili_login.py --check      # 只校验已有 Cookie 是否有效
    python scripts/bili_login.py --timeout 600

可选参数：
    --cookies PATH     Cookie 保存路径，默认 config/bilibili_cookies.json
    --timeout SECONDS  等待扫码的秒数，默认 300
    --check            不打开浏览器，只检查现有 Cookie
    --status-file PATH 供 Web 控制台轮询的状态文件
    --log-file PATH    额外追加一份日志（Web 控制台读取）

扫码来源：B站 App → 我的 → 扫一扫。
"""
import argparse
import json
import os
import sys
import time

# Windows / 企业代理环境：使用系统证书库
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

# Windows 控制台默认 GBK，直接输出 emoji/中文会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COOKIES = os.path.join(ROOT, "config", "bilibili_cookies.json")

BILI_LOGIN_URL = "https://passport.bilibili.com/login"
BILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_log_path = None


# ── 输出 ────────────────────────────────────────────────────────────────

def log(msg=""):
    print(msg, flush=True)
    if _log_path:
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass


def write_status(path, **data):
    if not path:
        return
    data.setdefault("updated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ── Cookie 解析 ─────────────────────────────────────────────────────────

def parse_cookie_file(path):
    """把 JSON 数组 / JSON 对象 / 纯文本 Cookie 统一成 [{name, value}, ...]。"""
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []

    if raw.startswith("[") or raw.startswith("{"):
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ("cookies", "data", "result"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, list):
            out = []
            for c in data:
                if isinstance(c, dict) and c.get("name") and c.get("value"):
                    out.append({"name": str(c["name"]), "value": str(c["value"])})
            return out
        if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
            return [{"name": k, "value": v} for k, v in data.items()]
        return []

    out = []
    for part in raw.replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip():
            out.append({"name": name.strip(), "value": value.strip()})
    return out


def normalize_cookies(raw_cookies):
    """Playwright cookie -> 上传器可用的 JSON 结构。"""
    cookies = []
    for c in raw_cookies:
        domain = c.get("domain") or ""
        if "bilibili" not in domain and "biligame" not in domain:
            continue
        if not c.get("name") or c.get("value") in (None, ""):
            continue

        same_site = c.get("sameSite") or "Lax"
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"

        item = {
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", False)),
            "sameSite": same_site,
        }
        expires = c.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            item["expirationDate"] = int(expires)
        cookies.append(item)
    return cookies


# ── Cookie 校验 ─────────────────────────────────────────────────────────

def check_cookies(cookies_path):
    """用 nav 接口验证 Cookie 是否仍然登录，返回 (ok, message, profile)。"""
    if not os.path.exists(cookies_path):
        return False, f"未找到 Cookie 文件：{cookies_path}", {}

    try:
        cookies = parse_cookie_file(cookies_path)
    except (OSError, ValueError) as exc:
        return False, f"Cookie 文件无法解析：{exc}", {}

    if not cookies:
        return False, "Cookie 文件为空或格式不正确", {}
    if not any(c["name"] == "SESSDATA" for c in cookies):
        return False, "缺少 SESSDATA，需要重新扫码登录", {}

    header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    try:
        import requests
        resp = requests.get(
            BILI_NAV_API,
            headers={"Cookie": header, "User-Agent": UA, "Referer": "https://www.bilibili.com/"},
            timeout=20,
        )
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"请求 B站 接口失败：{exc}", {}

    if body.get("code") != 0:
        return False, f"Cookie 已失效（{body.get('message') or body.get('code')}），请重新扫码", {}

    data = body.get("data") or {}
    if not data.get("isLogin"):
        return False, "未登录状态，Cookie 已失效，请重新扫码", {}

    profile = {"uname": data.get("uname"), "mid": data.get("mid"),
               "vip": (data.get("vipStatus") == 1)}
    return True, f"已登录：{data.get('uname')}（UID {data.get('mid')}）", profile


# ── 浏览器扫码 ──────────────────────────────────────────────────────────

def launch_browser(playwright):
    """优先使用本机 Chrome / Edge，退回 Playwright 自带 Chromium。"""
    errors = []
    for kwargs in (
        {"channel": "chrome", "headless": False},
        {"channel": "msedge", "headless": False},
        {"headless": False},
    ):
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 逐个降级尝试
            errors.append(f"{kwargs.get('channel', 'chromium')}: {exc}")

    raise SystemExit(
        "无法启动浏览器。请确认已安装 Chrome/Edge，或执行：\n"
        "   python -m playwright install chromium\n"
        "详情：\n   " + "\n   ".join(errors)
    )


def wait_for_login(context, timeout):
    """等待用户扫码，直到出现 SESSDATA + DedeUserID。"""
    deadline = time.time() + timeout
    last_hint = 0.0

    while time.time() < deadline:
        raw = context.cookies()
        names = {c["name"] for c in raw}
        if "SESSDATA" in names and "DedeUserID" in names:
            # 登录成功的瞬间 Cookie 还在陆续写入，稍等再完整导出
            time.sleep(1.5)
            return context.cookies()

        now = time.time()
        if now - last_hint > 15:
            log(f"⏳ 等待扫码…（剩余 {int(deadline - now)}s）")
            last_hint = now
        time.sleep(1)

    raise SystemExit("等待超时，未检测到登录成功。请重新运行后尽快扫码。")


def fetch_bili_profile(page):
    """借用已登录的页面读取用户信息，便于确认登录的是哪个账号。"""
    try:
        data = page.evaluate(
            "async () => {"
            f"  const r = await fetch('{BILI_NAV_API}', {{ credentials: 'include' }});"
            "  return await r.json();"
            "}"
        )
        if isinstance(data, dict) and data.get("code") == 0:
            return data.get("data") or {}
    except Exception:  # noqa: BLE001 - 仅用于展示，失败不影响主流程
        pass
    return {}


def run_browser_login(timeout):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "未安装 Playwright。请先执行：\n"
            "   pip install playwright\n"
            "   python -m playwright install chromium"
        )

    log("🌐 正在启动浏览器，请稍候…")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
        page = context.new_page()

        try:
            page.goto(BILI_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            log("")
            log("📱 请在弹出的浏览器窗口中用「B站 App → 扫一扫」登录，并在手机上确认。")
            log("   （登录成功后窗口会自动关闭）")
            log("")

            raw_cookies = wait_for_login(context, timeout)
            profile = fetch_bili_profile(page)
            if profile.get("uname"):
                log(f"✅ B站 登录成功：{profile['uname']}（UID {profile.get('mid')}）")
            else:
                log("✅ B站 登录成功（已获取登录 Cookie）")

            cookies = normalize_cookies(raw_cookies)
            if not any(c["name"] == "SESSDATA" for c in cookies):
                raise SystemExit("未获取到 SESSDATA，登录可能未完成，请重试。")

            log(f"🍪 已导出 {len(cookies)} 个 B站 Cookie")
            return cookies, profile
        finally:
            context.close()
            browser.close()


# ── 入口 ────────────────────────────────────────────────────────────────

def main():
    global _log_path

    parser = argparse.ArgumentParser(description="B站 扫码登录助手（自动导出 Cookie）")
    parser.add_argument("--cookies", default=DEFAULT_COOKIES, help="Cookie 保存路径")
    parser.add_argument("--timeout", type=int, default=300, help="等待扫码的秒数（默认 300）")
    parser.add_argument("--check", action="store_true", help="只校验现有 Cookie，不打开浏览器")
    parser.add_argument("--status-file", help="Web 控制台轮询的状态文件")
    parser.add_argument("--log-file", help="额外日志文件")
    args = parser.parse_args()

    cookies_path = os.path.abspath(args.cookies)
    _log_path = args.log_file
    if _log_path:
        os.makedirs(os.path.dirname(os.path.abspath(_log_path)), exist_ok=True)
        try:
            open(_log_path, "w", encoding="utf-8").close()
        except OSError:
            _log_path = None

    # 校验模式
    if args.check:
        ok, message, _ = check_cookies(cookies_path)
        log(("✅ " if ok else "❌ ") + message)
        write_status(args.status_file, state="ok" if ok else "failed", message=message,
                     has_cookies=os.path.exists(cookies_path))
        return 0 if ok else 1

    write_status(args.status_file, state="running", message="等待扫码登录")
    try:
        cookies, profile = run_browser_login(args.timeout)
    except SystemExit as exc:
        message = str(exc) or "登录失败"
        write_status(args.status_file, state="failed", message=message)
        log(f"❌ {message}")
        return 1
    except Exception as exc:  # noqa: BLE001
        message = f"登录过程出错：{exc}"
        write_status(args.status_file, state="failed", message=message)
        log(f"❌ {message}")
        return 1

    os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
    with open(cookies_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    log(f"💾 Cookie 已保存：{cookies_path}")

    ok, message, _ = check_cookies(cookies_path)
    if ok:
        log(f"✅ {message}")
    else:
        log(f"⚠️ {message}")

    write_status(
        args.status_file,
        state="ok" if ok else "failed",
        message=message,
        has_cookies=True,
        uname=profile.get("uname"),
        mid=profile.get("mid"),
        count=len(cookies),
    )
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("⚠️ 已取消。")
        write_status(None)
        sys.exit(130)