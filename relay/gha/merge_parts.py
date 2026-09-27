#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并矩阵各 job 的 parts/*.json.gz → 正式产物 + 页码台账

· 按股票代码去重（重叠窗口必然有重复）
· 记录「哪些页抓到了」，写 relay/data/_progress.json（编排器据此补缺页）
· 页码缺 ≤ TOLERANCE 才落正式产物（默认 2 页 = 200 只，可接受；并在 payload 里标注 pages_missing）
· 缺得多就只写 _progress.json，正式文件留空，等补跑

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
TOLERANCE = 2          # 允许缺的页数


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="parts")
    ap.add_argument("--out", default="relay/data")
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS)
    ap.add_argument("--tolerance", type=int, default=TOLERANCE)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.parts, "**", "part_*.json.gz"), recursive=True))
    print(f"发现 {len(files)} 个 part 文件")
    rows, ok_pages, all_pages, totals, dates = [], set(), set(), [], set()
    for p in files:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"  ✗ {os.path.basename(p)} 读取失败 {e}")
            continue
        r = d.get("rows") or []
        rows += r
        ok_pages |= set(d.get("ok_pages") or [])
        all_pages |= set(d.get("pages") or [])
        if d.get("total"):
            totals.append(d["total"])
        if d.get("date"):
            dates.add(d["date"])
        if r:
            print(f"  ✓ {os.path.basename(p):16s} 行={len(r):4d} 页={sorted(d.get('ok_pages') or [])[:10]}…")

    seen, uniq = set(), []
    for r in rows:
        c = str(r.get("f12"))
        if c and c not in seen:
            seen.add(c)
            uniq.append(r)

    ts = [r.get("f124") for r in uniq if isinstance(r.get("f124"), (int, float)) and r.get("f124")]
    date = (datetime.fromtimestamp(max(ts), CST).strftime("%Y-%m-%d") if ts
            else (sorted(dates)[-1] if dates else None))
    total = max(totals) if totals else None
    n_pages = (total + 99) // 100 if total else (max(ok_pages) if ok_pages else 0)
    missing = [p for p in range(1, n_pages + 1) if p not in ok_pages]

    print(f"\n合并：{len(uniq)} 只（去重前 {len(rows)}）｜交易日={date}｜total={total}")
    print(f"页码：抓到 {len(ok_pages)}/{n_pages} 页｜缺 {len(missing)} 页 {missing[:20]}")

    os.makedirs(a.out, exist_ok=True)
    prog = dict(date=date, rows=len(uniq), total=total, pages_total=n_pages,
                pages_ok=sorted(ok_pages), pages_missing=missing,
                parts=len(files), built_at=datetime.now(CST).isoformat(timespec="seconds"))
    with open(os.path.join(a.out, "_progress.json"), "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=1)

    if not date or len(uniq) < a.min_rows:
        print(f"❌ 数据不足（{len(uniq)} < {a.min_rows}）→ 只写 _progress.json，不落正式文件")
        return 3
    if len(missing) > a.tolerance:
        print(f"⚠️ 缺页过多（{len(missing)} > {a.tolerance}）→ 只写 _progress.json，等补跑缺页")
        return 3

    fpath = os.path.join(a.out, f"fundflow_{date}.json.gz")
    packed = [[str(r.get("f12")), r.get("f62"), r.get("f66"), r.get("f72"),
               r.get("f78"), r.get("f84"), r.get("f2"), r.get("f3")] for r in uniq]
    payload = dict(date=date, rows=len(packed),
                   fetched_at=datetime.now(CST).isoformat(timespec="seconds"),
                   source="eastmoney.push2delay.clist.gha",
                   pages_total=n_pages, pages_missing=missing, data=packed)
    with gzip.open(fpath, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ 已写 {os.path.basename(fpath)}（{os.path.getsize(fpath)/1024:.0f}KB，{len(packed)} 只"
          + (f"，缺 {missing}" if missing else "") + "）")

    lj = os.path.join(a.out, "latest.json")
    meta = dict(date=date, file=os.path.basename(fpath), rows=len(packed),
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
    print(f"✅ latest.json → {date}｜index {len(idx)} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
