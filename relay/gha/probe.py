#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通道探针：在海外的 GitHub runner 上批量试各种"拿历史日资金流"的 URL 候选

背景（2026-09-27）
==============
· clist（快照）在 Azure IP 上约 43% 可用；但 **push2his（历史）几乎全被 RemoteDisconnected 秒断（~3%）**
  → 历史回补靠矩阵行不通（8 轮只抓到 252/5218 只）
· 所以急需一条"同口径 + 一次能拿全市场历史"的路。本脚本把候选 URL 一次试完，打印状态与响应片段。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
D = "2026-09-23"
UT = "b2884a393a59ad64002292a3e90d46a5"


def q(base, **kw):
    return base + "?" + urllib.parse.urlencode(kw, safe=":,+")


CANDS = [
    # ① clist 家族带日期（若支持 → 同口径一次拿全市场历史）
    ("clist@push2delay+date", "https://push2delay.eastmoney.com/api/qt/clist/get",
     dict(pn=1, pz=5, po=1, np=1, fltt=2, invt=2, fid="f62", fs=FS, date=D, fields="f12,f62,f124")),
    ("clist@push2delay+date2", "https://push2delay.eastmoney.com/api/qt/clist/get",
     dict(pn=1, pz=5, po=1, np=1, fltt=2, invt=2, fid="f62", fs=FS, fdate=D, fields="f12,f62,f124")),
    ("clist@push2+date", "https://push2.eastmoney.com/api/qt/clist/get",
     dict(pn=1, pz=5, po=1, np=1, fltt=2, invt=2, fid="f62", fs=FS, date=D, fields="f12,f62,f124")),
    ("clist@push2his", "https://push2his.eastmoney.com/api/qt/clist/get",
     dict(pn=1, pz=5, po=1, np=1, fltt=2, invt=2, fid="f62", fs=FS, fields="f12,f62,f124")),
    # ② push2his 单股 daykline：验 ut 参数 / 换 host
    ("fflow@push2his", "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
     dict(lmt=5, klt=101, secid="1.600519", fields1="f1,f2,f3,f7",
          fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63")),
    ("fflow@push2his+ut", "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
     dict(lmt=5, klt=101, secid="1.600519", ut=UT, fields1="f1,f2,f3,f7",
          fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63")),
    ("fflow@push2his-dly", "https://push2hisdelay.eastmoney.com/api/qt/stock/fflow/daykline/get",
     dict(lmt=5, klt=101, secid="1.600519", fields1="f1,f2,f3,f7",
          fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63")),
    ("fflow@push2delay", "https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get",
     dict(lmt=5, klt=101, secid="1.600519", fields1="f1,f2,f3,f7",
          fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63")),
    # ③ 多 secid 批量（若支持 → 一次多股）
    ("fflow@push2his batch5", "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
     dict(lmt=5, klt=101, secid="1.600519,0.000001,0.300750,1.601318,0.002415", fields1="f1,f2,f3,f7",
          fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63")),
    # ④ datacenter 里可能的资金流历史报表
    ("dc:RPT_VALUEANALYSIS_DET", "https://datacenter-web.eastmoney.com/api/data/v1/get",
     dict(reportName="RPT_VALUEANALYSIS_DET", columns="ALL", pageNumber=1, pageSize=3,
          filter=f"(TRADE_DATE='{D}')", source="WEB", client="WEB")),
    ("dc:RPT_DMSK_FUNDFLOW", "https://datacenter-web.eastmoney.com/api/data/v1/get",
     dict(reportName="RPT_DMSK_FUNDFLOW", columns="ALL", pageNumber=1, pageSize=3, source="WEB", client="WEB")),
    ("dc:RPT_ZJLX_HISTORY", "https://datacenter-web.eastmoney.com/api/data/v1/get",
     dict(reportName="RPT_ZJLX_HISTORY", columns="ALL", pageNumber=1, pageSize=3, source="WEB", client="WEB")),
    # ⑤ 东财"资金流向"排行页后端（老版）
    ("zjlx-old", "https://push2.eastmoney.com/api/qt/clist/get",
     dict(pn=1, pz=5, po=1, np=1, fltt=2, invt=2, fid="f62", fs=FS, fields="f12,f62", ut=UT)),
]


def main():
    print(f"== 通道探针（目标日 {D}）==", flush=True)
    for name, base, params in CANDS:
        url = q(base, **params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                      "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            ok = '"rc":0' in body and '"diff"' in body or '"klines"' in body or '"result"' in body
            print(f"  [{'✅' if ok else '🟡'}] {name:26s} HTTP {r.status}｜{body[:150]}", flush=True)
        except urllib.error.HTTPError as e:
            print(f"  [❌] {name:26s} HTTP {e.code}｜{e.read().decode('utf-8','replace')[:110]}", flush=True)
        except Exception as e:
            print(f"  [❌] {name:26s} {type(e).__name__}: {str(e)[:80]}", flush=True)


if __name__ == "__main__":
    main()
