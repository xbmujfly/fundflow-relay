#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：东财 fflow/daykline 的 lmt 语义与两主机差异（在 runner 上跑，日志即结果）

背景：2026-10-05 用 history.yml 跑 lmt=750 时，每只只回 1 天 → 需要判定是哪一层把历史截断了。
"""
import json
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HOSTS = ["push2delay.eastmoney.com", "push2his.eastmoney.com"]
F1 = "f1,f2,f3,f7"
F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
CODES = [("1.600519", "600519"), ("0.000001", "000001")]


def egress():
    for u in ("https://api.ipify.org", "http://ip.3322.net"):
        try:
            with urllib.request.urlopen(u, timeout=8) as r:
                return r.read().decode("utf-8", "replace").strip()[:40]
        except Exception:
            continue
    return "?"


def probe(host, secid, lmt):
    url = (f"https://{host}/api/qt/stock/fflow/daykline/get"
           f"?lmt={lmt}&klt=101&secid={secid}&fields1={F1}&fields2={F2}")
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                  "Referer": "https://quote.eastmoney.com/"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        j = json.loads(body)
        kl = (j.get("data") or {}).get("klines") or []
        span = (kl[0].split(",")[0], kl[-1].split(",")[0]) if kl else None
        return f"rows={len(kl):<5} span={span} {int((time.time()-t0)*1000)}ms"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"{type(e).__name__}"
    return "?"


print(f"出口 IP = {egress()}", flush=True)
for host in HOSTS:
    for lmt in (0, 15, 750, 2500):
        print(f"--- {host} lmt={lmt} ---", flush=True)
        for secid, code in CODES:
            print(f"    {code}: {probe(host, secid, lmt)}", flush=True)
            time.sleep(0.4)
