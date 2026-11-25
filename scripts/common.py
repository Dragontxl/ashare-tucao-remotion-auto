# -*- coding: utf-8 -*-
"""公共工具：路径、配置、日期、字体检测、LLM 调用。本地与 GitHub Actions 通用。"""
import os
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

# Windows 控制台默认 GBK，输出中文/emoji 时容易乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Windows / 企业代理环境：让 requests 使用系统证书库，避免 CERTIFICATE_VERIFY_FAILED
try:  # pragma: no cover - 仅环境适配
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
SCRIPTS = os.path.join(ROOT, "scripts")
CONFIG_DIR = os.path.join(ROOT, "config")
INPUT_DIR = os.path.join(ROOT, "input")
PUBLIC = os.path.join(ROOT, "public")
CHARTS = os.path.join(PUBLIC, "charts")
MARKET_DATA = os.path.join(SRC, "market_data")
AUDIO = os.path.join(SRC, "audio")
OUT = os.path.join(ROOT, "out")

for d in (SRC, CHARTS, MARKET_DATA, AUDIO, OUT):
    os.makedirs(d, exist_ok=True)

# ---------- 默认大模型（Agnes 3.0 Flash，OpenAI 兼容） ----------
DEFAULT_LLM_BASE_URL = "https://apihub.agnes-ai.com/v1"
DEFAULT_LLM_MODEL = "agnes-3.0-flash"
DEFAULT_LLM_API_KEY = ""

# ---------- 默认复盘文档地址 ----------
DEFAULT_ARTICLE_BASE_URL = "https://ashare.ldragon.xyz/summary_today/"
DEFAULT_ARTICLE_PATTERN = "{date}_summary_today.docx"

_SHANGHAI = timezone(timedelta(hours=8))


# ---------- 日期（统一使用 Asia/Shanghai 时区） ----------
def now_shanghai():
    return datetime.now(_SHANGHAI)


def date8(dt=None):
    """8 位日期 YYYYMMDD，如 20260821。"""
    dt = dt or now_shanghai()
    return dt.strftime("%Y%m%d")


def cn_date(dt=None):
    """中文月日，无前导零，如 8月21日。"""
    dt = dt or now_shanghai()
    return f"{dt.month}月{dt.day}日"


def parse_date8(value):
    """把 YYYYMMDD / YYYY-MM-DD 解析为 datetime；空值返回今天。"""
    if not value:
        return now_shanghai()
    value = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_SHANGHAI)
        except ValueError:
            continue
    raise ValueError(f"无法识别的日期：{value}（请使用 YYYYMMDD）")


def date8_from(value):
    return parse_date8(value).strftime("%Y%m%d")


def cn_date_from_8(value):
    dt = parse_date8(value)
    return f"{dt.month}月{dt.day}日"


# ---------- 配置 ----------
def load_config():
    """加载配置，config.json 不存在时从模板复制。"""
    path = os.path.join(CONFIG_DIR, "config.json")
    if not os.path.exists(path):
        import shutil
        shutil.copy(os.path.join(CONFIG_DIR, "config.example.json"), path)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


def save_config(cfg):
    save_json(os.path.join(CONFIG_DIR, "config.json"), cfg)
    # 同步一份给 Remotion 组件 import（剔除密钥等敏感字段）
    save_json(os.path.join(SRC, "config.json"), public_config(cfg))


def public_config(cfg):
    """去掉密钥/凭据，得到可以安全写入 src/config.json 的配置。"""
    out = json.loads(json.dumps(cfg, ensure_ascii=False))
    llm = out.get("llm")
    if isinstance(llm, dict):
        llm.pop("api_key", None)
    bili = out.get("bilibili")
    if isinstance(bili, dict):
        bili.pop("cookies", None)
        bili.pop("cookies_file", None)
    gh = out.get("github")
    if isinstance(gh, dict):
        gh.pop("pat", None)
    cron = out.get("cronjob")
    if isinstance(cron, dict):
        cron.pop("api_key", None)
    r2 = out.get("r2")
    if isinstance(r2, dict):
        r2.pop("access_key_id", None)
        r2.pop("secret_access_key", None)
    return out


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------- 中文字体检测（跨平台） ----------
FONT_CANDIDATES = [
    os.environ.get("CHINESE_FONT_PATH", ""),
    r"C:\Windows\Fonts\msyh.ttc",                       # Windows 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Linux Noto
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",           # Linux 文泉驿
    "/usr/share/fonts/opentype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",               # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",
]


def find_chinese_font():
    """返回第一个存在的中文字体路径；找不到返回 None（matplotlib 将用默认字体）。"""
    for p in FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


# ---------- LLM 调用（OpenAI 兼容接口） ----------
def llm_settings(cfg):
    """解析 LLM 配置：环境变量优先于 config.json。"""
    llm = cfg.get("llm", {}) if isinstance(cfg, dict) else {}
    return {
        "base_url": (os.environ.get("LLM_BASE_URL")
                     or os.environ.get("AGNES_BASE_URL")
                     or llm.get("base_url")
                     or DEFAULT_LLM_BASE_URL).rstrip("/"),
        "model": (os.environ.get("LLM_MODEL")
                  or os.environ.get("AGNES_MODEL")
                  or llm.get("model")
                  or DEFAULT_LLM_MODEL),
        "api_key": (os.environ.get("LLM_API_KEY")
                    or os.environ.get("AGNES_API_KEY")
                    or llm.get("api_key")
                    or DEFAULT_LLM_API_KEY),
        "temperature": llm.get("temperature", 0.9),
        "timeout": int(llm.get("timeout", 180)),
    }


def has_llm_key(cfg):
    return bool(llm_settings(cfg).get("api_key"))


def call_llm(cfg, system_prompt, user_prompt, json_mode=False, retries=3):
    """调用 OpenAI 兼容的 chat/completions。返回回复文本。

    Key 读取顺序：LLM_API_KEY / AGNES_API_KEY 环境变量 -> config.llm.api_key -> 内置默认。
    默认使用 Agnes 3.0 Flash。
    """
    s = llm_settings(cfg)
    if not s["api_key"]:
        raise RuntimeError("未配置 LLM API Key（config.llm.api_key 或环境变量 AGNES_API_KEY）")

    payload = {
        "model": s["model"],
        "temperature": s["temperature"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                f"{s['base_url']}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {s['api_key']}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=s["timeout"]) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise RuntimeError("模型返回内容为空")
            return content
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"LLM 调用失败（第 {attempt}/{retries} 次）：{type(e).__name__} {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    raise RuntimeError(f"LLM 调用失败：{last_err}")


def extract_json(text):
    """从 LLM 回复中提取 JSON（兼容 ```json 包裹与前后废话）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    # 截取第一个 { 或 [ 到最后一个 } 或 ]
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("LLM 回复中未找到 JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def log(msg):
    print(f"[ashare-tucao] {msg}", flush=True)
