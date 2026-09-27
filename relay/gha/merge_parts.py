#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并矩阵各 job 的分片 → 跨轮累积 → 正式产物 + 缺页台账

关键设计：**跨轮累积**
====================
GitHub Actions 每个 run 的 merge job 只能看到**本次** run 的 artifacts。
但东财对海外 IP 只放行一半 → 一轮必然缺页。所以：
  仓库里存 _accum.json.gz（累加器）→ 每轮把新抓到的行并进去（按股票代码去重）
  → 缺页就写台账，由 workflow 自动再触发一轮（只抓缺的页）
  → 抓全了自然就落正式产物 fundflow_<date>.json.gz
新交易日自动重置累加器（日期变了就重来）。

产物格式与 relay/fetch_fundflow.py 一致，可直接被 common/pull_relay_data.py 入库。
"""
import argparse
import glob
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
MIN_ROWS = 3800
TOLERANCE = 0          # 缺页容忍度：0 = 必须抓全才落正式产物


def load_accum(path):
    if os.path.exists(path):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"date": None, "pages_ok": [], "data": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="parts")
    ap.add_argument("--out", default="relay/data")
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS)
    ap.add_argument("--tolerance", type=int, default=TOLERANCE)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    accum_path = os.path.join(a.out, "_accum.json.gz")

    # ① 本轮抓到的
    files = sorted(glob.glob(os.path.join(a.parts, "**", "part_*.json.gz"), recursive=True))
    run_rows, run_pages, totals, dates = [], set(), [], set()
    for p in files:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"  ✗ {os.path.basename(p)} 读取失败 {e}")
            continue
        run_rows += d.get("rows") or []
        run_pages |= set(d.get("ok_pages") or [])
        if d.get("total"):
            totals.append(d["total"])
        if d.get("date"):
            dates.add(d["date"])
    print(f"本轮：{len(files)} 个分片｜{len(run_rows)} 行｜{len(run_pages)} 页｜日期 {sorted(dates)}")

    run_date = sorted(dates)[-1] if dates else None
    total = max(totals) if totals else None

    # ② 累积（新交易日则重置）
    acc = load_accum(accum_path)
    if acc.get("date") and run_date and acc["date"] != run_date:
        print(f"⏭ 交易日变化 {acc['date']} → {run_date}，累加器重置")
        acc = {"date": None, "pages_ok": [], "data": []}
    if not acc.get("date") and run_date:
        acc["date"] = run_date
    if not acc.get("date"):
        print("❌ 本轮的日期都取不到 → 放弃")
        return 3

    seen = {r[0] for r in acc.get("data") or []}
    added = 0
    for r in run_rows:
        c = str(r.get("f12"))
        if c and c not in seen:
            seen.add(c)
            acc["data"].append([c, r.get("f62"), r.get("f66"), r.get("f72"),
                                r.get("f78"), r.get("f84"), r.get("f2"), r.get("f3")])
            added += 1
    pages_ok = sorted(set(acc.get("pages_ok") or []) | run_pages)
    acc["pages_ok"] = pages_ok
    if total and not acc.get("total"):
        acc["total"] = total
    print(f"累积：{len(acc['data'])} 只（本轮新增 {added}）｜累计 {len(pages_ok)} 页")

    with gzip.open(accum_path, "wt", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, separators=(",", ":"))

    n_pages = ((acc.get("total") or 0) + 99) // 100 or (max(pages_ok) if pages_ok else 0)
    missing = [p for p in range(1, n_pages + 1) if p not in set(pages_ok)]

    prog = dict(date=acc["date"], rows=len(acc["data"]), total=acc.get("total"),
                pages_total=n_pages, pages_ok=pages_ok, pages_missing=missing,
                run_added=added, parts=len(files),
                built_at=datetime.now(CST).isoformat(timespec="seconds"))
    with open(os.path.join(a.out, "_progress.json"), "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=1)
    print(f"台账：{len(acc['data'])}/{acc.get('total')} 只｜页 {len(pages_ok)}/{n_pages}｜缺 {missing[:20]}")

    # ③ 判定是否落正式产物
    if len(acc["data"]) < a.min_rows:
        print(f"❌ 累积仍不足（{len(acc['data'])} < {a.min_rows}）→ 只写台账，等下一轮")
        return 3
    if len(missing) > a.tolerance:
        print(f"⚠️ 还缺 {len(missing)} 页（> 容忍 {a.tolerance}）→ 只写台账，等下一轮补")
        return 3

    date = acc["date"]
    fpath = os.path.join(a.out, f"fundflow_{date}.json.gz")
    payload = dict(date=date, rows=len(acc["data"]),
                   fetched_at=datetime.now(CST).isoformat(timespec="seconds"),
                   source="eastmoney.push2delay.clist.gha",
                   pages_total=n_pages, pages_missing=missing, data=acc["data"])
    with gzip.open(fpath, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"🎉 已写 {os.path.basename(fpath)}（{os.path.getsize(fpath)/1024:.0f}KB，{len(acc['data'])} 只）")

    lj = os.path.join(a.out, "latest.json")
    meta = dict(date=date, file=os.path.basename(fpath), rows=len(acc["data"]),
                fetched_at=datetime.now(CST).isoformat(timespec="seconds"),
                pages_total=n_pages, pages_missing=missing)
    old = {}
    if os.path.exists(lj):
        try:
            old = json.load(open(lj, encoding="utf-8"))
        except Exception:
            pass
    if old.get("date") and old["date"] > date:
        print(f"⏭ latest.json 已指向更新的 {old['date']}，不回退")
    else:
        json.dump(meta, open(lj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    idx_path = os.path.join(a.out, "index.json")
    try:
        idx = json.load(open(idx_path, encoding="utf-8")).get("dates", [])
    except Exception:
        idx = []
    if date not in idx:
        idx.append(date)
    json.dump(dict(dates=sorted(idx)), open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ latest.json → {date}｜index {len(idx)} 天｜缺页 {missing or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
