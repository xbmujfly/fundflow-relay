#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions 矩阵取数 · 单 job 抓指定页区间

设计要点（2026-09-27 实测决定的）
=============================
东财 push2 **按网络出口放行极少数请求**（校园网/IPv4热点/IPv6热点 都是发几发就被 RST），
而单页硬顶 100 行、全市场 5561 只 → 必须 56 次请求。
→ 唯一解：把 56 次请求摊到 **56 个不同的网络出口**。GitHub Actions 的矩阵里
   **每个 job 跑在独立 runner 上 = 独立公网 IP**，天然满足这个条件。

本脚本在 runner 上跑：只发 --per-job 次请求（默认 2 次，配额友好），
把结果写成 parts/part_<chunk>.json.gz，交给 merge job 汇总。

用法
====
    python3 fetch_range.py --chunk 0 --per-job 2 --out parts
    python3 fetch_range.py --from 1 --to 3 --out -            # 直接打印（自测用）
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
FIELDS = "f12,f2,f3,f62,f66,f72,f78,f84,f124"
BASE = "https://push2delay.eastmoney.com/api/qt/clist/get"


def page_url(pn, pz):
    q = dict(pn=pn, pz=pz, po=1, np=1, fltt=2, invt=2, fid="f62", fs=FS, fields=FIELDS)
    return BASE + "?" + urllib.parse.urlencode(q, safe=":,+")


def egress_ip():
    for u in ("https://api.ipify.org", "http://ip.3322.net"):
        try:
            with urllib.request.urlopen(u, timeout=8) as r:
                return r.read().decode("utf-8", "replace").strip()[:40]
        except Exception:
            continue
    return "?"


def fetch(pn, pz=100, tries=3):
    """抓一页；返回 (diff, total)。东财偶发 RST 时退避重试。"""
    last = ""
    for k in range(tries):
        t0 = time.time()
        try:
            req = urllib.request.Request(page_url(pn, pz), headers={"User-Agent": UA,
                                                                     "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=25) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            d = j.get("data") or {}
            diff = d.get("diff") or []
            print(f"  page {pn}: ok rows={len(diff)} total={d.get('total')} ({time.time()-t0:.1f}s)", flush=True)
            return diff, d.get("total")
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}"
            print(f"  page {pn}: FAIL {last} ({time.time()-t0:.1f}s)", flush=True)
            time.sleep(3 * (k + 1))
    print(f"  page {pn}: 放弃（{last}）", flush=True)
    return [], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=None, help="矩阵分片号（从 0 开始）")
    ap.add_argument("--per-job", type=int, default=2, help="每个 job 抓几页（越小越安全）")
    ap.add_argument("--from", dest="pfrom", type=int, default=None)
    ap.add_argument("--to", type=int, default=None)
    ap.add_argument("--pz", type=int, default=100)
    ap.add_argument("--out", default="parts")
    ap.add_argument("--total-pages", type=int, default=90, help="总页数；本分片起点超出则跳过（测试用）")
    a = ap.parse_args()

    if a.chunk is not None:
        a.pfrom = a.chunk * a.per_job + 1
        a.to = a.pfrom + a.per_job - 1
    if not a.pfrom:
        a.pfrom, a.to = 1, 1
    if a.pfrom > a.total_pages:
        print(f"chunk={a.chunk} 起点 {a.pfrom} > 总页数 {a.total_pages} → 跳过（测试模式）", flush=True)
        return 0
    a.to = min(a.to, a.total_pages)
    print(f"== chunk={a.chunk} pages {a.pfrom}-{a.to}｜出口 IP={egress_ip()} ==", flush=True)

    rows, total = [], None
    for pn in range(a.pfrom, a.to + 1):
        diff, total = fetch(pn, a.pz)
        if diff:
            rows += diff
        time.sleep(0.5)

    if not rows:
        print("本 job 没拿到数据（该出口可能被拒）", flush=True)
        return 1
    date = None
    ts = [r.get("f124") for r in rows if isinstance(r.get("f124"), (int, float)) and r.get("f124")]
    if ts:
        from datetime import datetime, timedelta, timezone
        date = datetime.fromtimestamp(max(ts), timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    if a.out == "-":
        print(json.dumps(dict(date=date, n=len(rows), sample=rows[:2]), ensure_ascii=False))
        return 0
    os.makedirs(a.out, exist_ok=True)
    p = os.path.join(a.out, f"part_{a.chunk if a.chunk is not None else 'x'}.json.gz")
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(dict(chunk=a.chunk, pages=[a.pfrom, a.to], date=date, rows=rows), f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"✅ 写 {p}（{len(rows)} 行，日期 {date}）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
