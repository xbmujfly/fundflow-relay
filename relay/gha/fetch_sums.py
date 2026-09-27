#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GHA 矩阵 · 抓全市场「当日+3日+5日+10日」主力净额（用于反推缺失交易日）

为什么用重叠（2026-09-27 实测数据驱动）
=====================================
· 东财对海外(Azure)IP **约 43% 可用**（28 job 里 12 成功、17 个 502）
· **可用的那个 IP 能吃约 7 页**（实测 chunk0 连抓 20 页 → ok=7）
· 全市场 5561 只、单页硬顶 100 行 → 56 页
→ 若每页只派 1 个 job，单页缺失概率 = 57%（太差）。
  改成 **重叠窗口**：job i 抓第 i+1, i+2, …, i+SPAN 页（环形），
  则每一页被 SPAN 个不同 job(不同 IP)各抓一次，单页缺失概率降到 0.57^SPAN。
  56 job × SPAN=8 → 单页缺失 ≈1%，一次跑基本抓全；merge 端按代码去重。

用法（runner 上）
====
    python3 fetch_range.py --job 3 --jobs 56 --pages 56 --span 8 --out parts
    python3 fetch_range.py --pages-list "7,23,41" --out parts     # 定向补缺页
    python3 fetch_range.py --chunk 0 --per-job 2 --total-pages 56 # 兼容旧的分片模式
产出：parts/part_<job>.json.gz = {job, pages(请求的), ok_pages, total, date, rows}
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
FIELDS = ("f12,f14,f2,f3,f62,f184,f66,f72,f78,f84,f124,"  # 当日(主力+四档+时间戳)
              "f267,f269,f271,f273,f275,"                  # 3日 主力/超大/大/中/小
              "f164,f166,f168,f170,f172,"                  # 5日 主力/超大/大/中/小
              "f174,f176,f178,f180,f182")                 # 10日 主力/超大/大/中/小
BASE = "https://push2delay.eastmoney.com/api/qt/clist/get"
CST = timezone(timedelta(hours=8))


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


def fetch(pn, pz=100, tries=2):
    """抓一页。失败快速放弃（这个 IP 被封时重试无用，省时间省配额）"""
    last = ""
    for k in range(tries):
        t0 = time.time()
        try:
            req = urllib.request.Request(page_url(pn, pz), headers={"User-Agent": UA,
                                                                    "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            d = j.get("data") or {}
            diff = d.get("diff") or []
            print(f"  page {pn}: ok rows={len(diff)} total={d.get('total')} ({time.time()-t0:.1f}s)", flush=True)
            return diff, d.get("total")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except Exception as e:
            last = f"{type(e).__name__}"
        print(f"  page {pn}: FAIL {last} ({time.time()-t0:.1f}s)", flush=True)
        if k + 1 < tries:
            time.sleep(1.5 * (k + 1))
    print(f"  page {pn}: 放弃（{last}）", flush=True)
    return [], None


def resolve_pages(a):
    if a.pages_list:
        import random
        ps = [int(x) for x in a.pages_list.replace(" ", "").split(",") if x]
        # 关键：每个 job 用自己的种子打乱顺序。
        # 若都按原顺序抓，IP 只能活 3-7 发 → 列表头部被反复重试、尾部永远轮不到。
        rnd = random.Random(a.job or 0)
        rnd.shuffle(ps)
        return ps, 0
    if a.job is not None:
        # 环形重叠：job i → i+1 … i+span（模 pages）
        return [((a.job + k) % a.pages) + 1 for k in range(a.span)], a.pages
    if a.chunk is not None:
        f = a.chunk * a.per_job + 1
        return list(range(f, f + a.per_job)), a.total_pages
    return [1], 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", type=int, default=None, help="本 job 序号（矩阵里从 0 开始）")
    ap.add_argument("--jobs", type=int, default=56)
    ap.add_argument("--pages", type=int, default=56, help="总页数（= ceil(全市场只数/100)）")
    ap.add_argument("--span", type=int, default=8, help="每个 job 抓几页（重叠窗口宽度）")
    ap.add_argument("--pages-list", default=None, help="定向补缺：逗号分隔的页码")
    ap.add_argument("--chunk", type=int, default=None, help="兼容旧分片模式")
    ap.add_argument("--per-job", type=int, default=2)
    ap.add_argument("--total-pages", type=int, default=90)
    ap.add_argument("--pz", type=int, default=100)
    ap.add_argument("--max-fail", type=int, default=3, help="连续几页失败就收工（IP 已死）")
    ap.add_argument("--out", default="parts")
    a = ap.parse_args()

    pages, total_pages = resolve_pages(a)
    if not pages:
        print("没有要抓的页 → 跳过", flush=True)
        return 0
    if a.job is not None and a.job >= a.jobs:
        print(f"job {a.job} >= jobs {a.jobs} → 跳过", flush=True)
        return 0

    tag = a.job if a.job is not None else (a.chunk if a.chunk is not None else "pl")
    print(f"== job={tag} 要抓 {len(pages)} 页: {pages}｜出口 IP={egress_ip()} ==", flush=True)

    rows, ok_pages, total, streak = [], [], None, 0
    for i, pn in enumerate(pages):
        diff, t = fetch(pn, a.pz)
        if diff:
            rows += diff
            ok_pages.append(pn)
            streak = 0
        else:
            streak += 1
            if streak >= a.max_fail:
                print(f"  连续 {streak} 页失败 → 本 IP 已死，收工（还剩 {len(pages)-i-1} 页没试）", flush=True)
                break
        if t:
            total = t
        if i + 1 < len(pages):
            time.sleep(0.4)

    date = None
    ts = [r.get("f124") for r in rows if isinstance(r.get("f124"), (int, float)) and r.get("f124")]
    if ts:
        date = datetime.fromtimestamp(max(ts), CST).strftime("%Y-%m-%d")

    if a.out != "-":
        os.makedirs(a.out, exist_ok=True)
        p = os.path.join(a.out, f"sumpart_{tag}.json.gz")
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(dict(job=tag, pages=pages, ok_pages=ok_pages, total=total, date=date, rows=rows),
                      f, ensure_ascii=False, separators=(",", ":"))
        print(f"✅ 写 {p}（{len(rows)} 行，成功 {len(ok_pages)}/{len(pages)} 页，日期 {date}）", flush=True)

    if not rows:
        print("本 job 没拿到任何数据（该出口被拒）", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
