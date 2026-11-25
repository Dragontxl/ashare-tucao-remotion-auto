# -*- coding: utf-8 -*-
"""Step 2b：从腾讯免费接口抓取真实行情（指数 + 配置的个股），缓存为 JSON。
数据源：ifzq.gtimg.cn（稳定、无需密钥）。自动取最新交易日数据，不硬编码日期。
"""
import os
import sys
import json
import time
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MARKET_DATA, load_config, save_json, log

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(2)


def tx_kline(code, n=30):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"
    node = get_json(url)["data"][code]
    key = "qfqday" if "qfqday" in node else "day"
    rows = []
    for p in node[key]:
        rows.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                     "high": float(p[3]), "low": float(p[4]), "volume": float(p[5])})
    return {"name": code, "kline": rows}


def tx_trends(code):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}"
    node = get_json(url)["data"][code]["data"]
    rows = []
    for line in node["data"]:
        p = line.split()
        t = p[0]
        rows.append({"time": t[:2] + ":" + t[2:], "price": float(p[1]), "volume": float(p[2])})
    return {"name": code, "date": node.get("date"), "trends": rows}


def fetch(code):
    k = tx_kline(code, 30)
    t = tx_trends(code)
    save_json(os.path.join(MARKET_DATA, f"{code}_kline.json"), k)
    save_json(os.path.join(MARKET_DATA, f"{code}_trends.json"), t)
    last = k["kline"][-1]
    log(f"{code}: {last['date']} 收{last['close']} | 分时{len(t['trends'])}点 日期{t['date']}")
    return last["date"]


def main():
    cfg = load_config()
    index_code = cfg.get("index_code", "sh000001")
    stocks = cfg.get("stocks", [])
    targets = [index_code] + [s["code"] for s in stocks]
    targets = list(dict.fromkeys(targets))  # 去重保序
    trade_date = None
    for code in targets:
        try:
            d = fetch(code)
            if code == index_code:
                trade_date = d
            time.sleep(0.5)
        except Exception as e:
            log(f"抓取失败 {code}: {type(e).__name__} {e}")
    # 记录数据日期，供图表与文案使用
    save_json(os.path.join(MARKET_DATA, "meta.json"), {
        "trade_date": trade_date,
        "index_code": index_code,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    log("真实行情抓取完成")


if __name__ == "__main__":
    main()
