#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并 sums 各分片 → sums_latest.json.gz"""
import argparse, glob, gzip, json, os
ap = argparse.ArgumentParser(); ap.add_argument("--in", dest="ind", default="parts")
ap.add_argument("--out", default="sums_latest.json.gz"); a = ap.parse_args()
rows, pages, total = {}, {}, None
for p in sorted(glob.glob(os.path.join(a.ind, "**", "sumpart_*.json.gz"), recursive=True)):
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f: j = json.load(f)
    except Exception as e:
        print("skip", p, e); continue
    for r in j.get("rows") or []:
        c = str(r.get("f12") or "")
        if c: rows[c] = r
    for pn in j.get("ok_pages") or []: pages[pn] = 1
    total = j.get("total") or total
out = {"date": None, "total": total, "n": len(rows), "pages": sorted(pages), "rows": list(rows.values())}
with gzip.open(a.out, "wt", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False)
print(f"合并 {len(rows)} 只 / 页 {len(pages)}/{56} total={total} → {a.out}")
