# -*- coding: utf-8 -*-
"""Step 0：获取复盘原文。

默认来源：交易日当日的 https://ashare.ldragon.xyz/summary_today/<date>_summary_today.docx
支持：默认 URL / 自定义 URL / 本地 docx / 本地 txt / md。

用法：
    python scripts/fetch_article.py                     # 抓今天
    python scripts/fetch_article.py --date 20260821
    python scripts/fetch_article.py --source https://example.com/a.docx
    python scripts/fetch_article.py --source input/manual.docx
    python scripts/fetch_article.py --source input/article.md
"""
import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DEFAULT_ARTICLE_BASE_URL, DEFAULT_ARTICLE_PATTERN, INPUT_DIR,
                    date8, load_config, log)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def default_article_url(date8_str, cfg=None):
    """交易日当日的默认复盘文档地址。"""
    art = (cfg or {}).get("article", {})
    base = (art.get("base_url") or DEFAULT_ARTICLE_BASE_URL).rstrip("/") + "/"
    pattern = art.get("pattern") or DEFAULT_ARTICLE_PATTERN
    return base + pattern.format(date=date8_str)


def is_url(source):
    return bool(re.match(r"^https?://", (source or "").strip(), re.I))


def download_file(url, dest, retries=3, interval=20, timeout=60):
    """下载文件到 dest，带重试。返回 dest。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                status = getattr(resp, "status", 200)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            if len(data) < 1024:
                raise RuntimeError(f"文件过小（{len(data)} 字节），可能不是有效文档")
            with open(dest, "wb") as f:
                f.write(data)
            log(f"已下载复盘文档：{url} -> {dest}（{len(data)} 字节）")
            return dest
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"下载失败（第 {attempt}/{retries} 次）：{e}")
            if attempt < retries and interval > 0:
                log(f"{interval}s 后重试……")
                time.sleep(interval)
    raise RuntimeError(f"复盘文档下载失败：{url}（{last_err}）")


def _docx_text_with_python_docx(path):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    lines = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = (p.text or "").strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if "heading" in style or "标题" in style:
                level = 1
                m = re.search(r"(\d+)", style)
                if m:
                    level = max(1, min(6, int(m.group(1))))
                lines.append("#" * level + " " + text)
            else:
                lines.append(text)
        elif tag == "tbl":
            table = Table(child, doc)
            rows = []
            for row in table.rows:
                cells = [c.text.replace("\n", " ").strip() for c in row.cells]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                lines.append("")
                lines.extend(rows)
                lines.append("")
    return "\n\n".join(lines).strip()


def _docx_text_with_zip(path):
    """不依赖 python-docx 的兜底解析：直接读 word/document.xml。"""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    for p in root.findall(".//w:p", ns):
        texts = [t.text or "" for t in p.findall(".//w:t", ns)]
        line = "".join(texts).strip()
        if line:
            out.append(line)
    return "\n\n".join(out).strip()


def extract_docx_text(path):
    try:
        text = _docx_text_with_python_docx(path)
    except Exception as e:  # noqa: BLE001
        log(f"python-docx 解析失败（{e}），改用 XML 兜底解析")
        text = _docx_text_with_zip(path)
    if not text:
        raise RuntimeError(f"未能从 docx 提取到文本：{path}")
    return text


def read_article_file(path):
    """读取 docx / md / txt 为纯文本。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return extract_docx_text(path)
    if ext in (".md", ".markdown", ".txt", ".text"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    raise RuntimeError(f"不支持的文件类型：{ext}（请使用 docx / md / txt）")


def fetch_article(source=None, date8_str=None, cfg=None, dest=None,
                  retries=None, interval=None):
    """获取原文并写入 input/article.md。

    source 为空 / "auto" 时使用交易日当日的默认 URL。
    返回 (本地文件路径, 来源说明)。
    """
    cfg = cfg or load_config()
    date8_str = date8_str or date8()
    art = cfg.get("article", {})
    # CI 可通过环境变量延长等待（17:25 触发时 docx 可能刚发布）
    if retries is None:
        retries = int(os.environ.get("ARTICLE_RETRIES") or art.get("retries", 3))
    if interval is None:
        interval = int(os.environ.get("ARTICLE_RETRY_INTERVAL") or art.get("retry_interval", 20))
    dest = dest or os.path.join(INPUT_DIR, "article.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    source = (source or "").strip()
    if not source or source.lower() == "auto":
        url = default_article_url(date8_str, cfg)
        tmp = os.path.join(INPUT_DIR, f"{date8_str}_summary_today.docx")
        download_file(url, tmp, retries=retries, interval=interval)
        text = extract_docx_text(tmp)
        origin = url
    elif is_url(source):
        ext = os.path.splitext(urllib.parse.urlparse(source).path)[1].lower()
        if ext not in (".docx", ".md", ".markdown", ".txt", ".text"):
            ext = ".docx"
        tmp = os.path.join(INPUT_DIR, f"{date8_str}_source{ext}")
        download_file(source, tmp, retries=retries, interval=interval)
        text = read_article_file(tmp)
        origin = source
    else:
        if not os.path.exists(source):
            raise FileNotFoundError(f"原文文件不存在：{source}")
        text = read_article_file(source)
        origin = os.path.abspath(source)

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < 50:
        raise RuntimeError(f"原文内容过短（{len(text)} 字），请检查来源：{origin}")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    log(f"原文已保存：{dest}（{len(text)} 字）")
    return dest, origin


def preview_article(source=None, date8_str=None, cfg=None, max_chars=1200):
    """供前端预览：返回前若干字符。"""
    path, origin = fetch_article(source, date8_str, cfg)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return {
        "origin": origin,
        "chars": len(text),
        "preview": text[:max_chars],
    }


def main():
    ap = argparse.ArgumentParser(description="获取A股复盘原文")
    ap.add_argument("--source", default="auto",
                    help="auto=当日默认URL，或自定义URL / 本地 docx、md、txt 路径")
    ap.add_argument("--date", default=date8(), help="交易日 YYYYMMDD，默认今天")
    ap.add_argument("--out", default=os.path.join(INPUT_DIR, "article.md"))
    ap.add_argument("--retries", type=int, default=None)
    ap.add_argument("--retry-interval", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    path, origin = fetch_article(args.source, args.date, cfg, dest=args.out,
                                 retries=args.retries, interval=args.retry_interval)
    print(f"来源：{origin}")
    print(f"输出：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
