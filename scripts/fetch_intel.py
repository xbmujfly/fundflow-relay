#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静外一手情报采集（在 GitHub Actions 上跑；本机出口访问不到的源由它代取）

产出 intel/latest.json：{ts, sources:{name:{ok,n,err}}, items:[{src,ts,title,url}]}
只取「标题+链接+时间」，不存正文（商业媒体 ToS 友好）。
"""
import json, os, re, time, urllib.request, html
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"}

def get(url, timeout=20, referer=None):
    h = dict(UA)
    if referer: h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def strip(x):
    x = re.sub(r"<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", html.unescape(x)).strip()

def rss_items(xml, limit=30):
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S)[:limit]:
        def g(t):
            m = re.search(rf"<{t}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", it, re.S)
            return strip(m.group(1)) if m else ""
        out.append({"title": g("title")[:200], "url": g("link"), "ts": g("pubDate") or g("dc:date")})
    return out

SOURCES = {
    "whitehouse": ("https://www.whitehouse.gov/presidential-actions/feed/", "rss"),
    "ustr": ("https://ustr.gov/rss.xml", "rss"),
    "fed": ("https://www.federalreserve.gov/feeds/press_all.xml", "rss"),
    "reuters": ("https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml", "rss"),
    "ap": ("https://apnews.com/hub/apf-topnews?output=rss", "rss"),
    "truthsocial_api": ("https://truthsocial.com/api/v1/accounts/lookup?acct=realDonaldTrump", "ts"),
}

def fetch_truthsocial():
    """Trump 真源（境外可达）：lookup 拿 id → 拉最新 20 条 statuses"""
    info = json.loads(get(SOURCES["truthsocial_api"][0]))
    uid = info.get("id")
    if not uid:
        raise RuntimeError("lookup 无 id")
    st = json.loads(get(f"https://truthsocial.com/api/v1/accounts/{uid}/statuses?limit=20&exclude_replies=true"))
    out = []
    for s in st:
        txt = strip(re.sub(r"<[^>]+>", " ", s.get("content") or ""))
        out.append({"title": txt[:200], "url": s.get("url") or "", "ts": s.get("created_at") or ""})
    return out

def main():
    res = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": {}, "items": []}
    for name, (url, kind) in SOURCES.items():
        try:
            items = fetch_truthsocial() if kind == "ts" else rss_items(get(url))
            res["sources"][name] = {"ok": True, "n": len(items)}
            for it in items[:20]:
                res["items"].append({"src": name, **it})
        except Exception as e:
            res["sources"][name] = {"ok": False, "n": 0, "err": f"{type(e).__name__}: {str(e)[:120]}"}
    os.makedirs("intel", exist_ok=True)
    with open("intel/latest.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res["sources"], ensure_ascii=False))

if __name__ == "__main__":
    main()
