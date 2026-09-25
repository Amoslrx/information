# -*- coding: utf-8 -*-
"""从西交官网的院系中转页里, 自动识别出各学院/书院的真实主页。

官网 https://www.xjtu.edu.cn/yxsz.htm 列出的院系链接指向的是校内中转页
(xynr.jsp?...wbtreeid=NNNN), 不是学院自己的网站。中转页里混有学院主页链接,
但也混着全站通用链接(网络中心、校友会、文明网...)。

区分办法: **频次分析**。
  - 全站通用链接会出现在几乎每个中转页里 -> 出现次数高
  - 某个学院自己的主页只出现在它自己的中转页里 -> 出现次数 = 1
再对候选 URL 做一次连通性实测, 只保留真的能打开的。

输出: data/raw/xjtu_departments.json
"""
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = r"F:\竞赛信息"
DST = os.path.join(ROOT, "data", "raw", "xjtu_departments.json")

BASE = "https://www.xjtu.edu.cn/"
LIST_URL = BASE + "yxsz.htm"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
     "Accept-Language": "zh-CN,zh;q=0.9", "Accept-Encoding": "gzip, deflate"}


def get(url, timeout=25):
    req = urllib.request.Request(url if url.startswith("http") else BASE + url, headers=H)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            b = gzip.decompress(b)
        return r.status, b.decode("utf-8", "replace")


def parse_list():
    """取院系列表: (名称, 相对链接)。"""
    _, h = get(LIST_URL)
    rows = re.findall(
        r'<a[^>]+href="([^"]+)"[^>]*>(?:\s|<[^>]+>)*([^<]{2,26}?(?:学院|书院|学部|中心|学系))'
        r'(?:\s|<[^>]+>)*</a>', h, re.S)
    seen, out = set(), []
    for href, name in rows:
        name = re.sub(r"\s+", "", name)
        if href.startswith(("javascript", "#")) or not name:
            continue
        key = (name, href)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "href": href})
    return out


def page_links(href):
    """取某个中转页里的绝对外链。"""
    try:
        _, h = get(href)
    except Exception:
        return []
    return sorted(set(re.findall(r'href="(https?://[^"]+)"', h)))


def probe(url):
    try:
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def main():
    depts = parse_list()
    print("院系列表: %d 项" % len(depts))

    # 抓每个中转页的链接
    with ThreadPoolExecutor(max_workers=5) as ex:
        all_links = list(ex.map(lambda d: page_links(d["href"]), depts))

    freq = Counter()
    for links in all_links:
        for u in links:
            freq[u] += 1

    results = []
    for d, links in zip(depts, all_links):
        # 候选: 出现次数少的(=非全站通用), 且不是导航/备案类
        cands = [u for u in links
                 if freq[u] <= 2
                 and "beian." not in u
                 and not re.search(r"(weibo|renren|t\.qq|passport)", u)]
        results.append({"name": d["name"], "href": d["href"], "candidates": cands})

    # 实测候选
    allc = sorted({u for r in results for u in r["candidates"]})
    print("候选链接: %d 个, 开始实测" % len(allc))
    with ThreadPoolExecutor(max_workers=8) as ex:
        stats = dict(zip(allc, ex.map(probe, allc)))

    for r in results:
        ok = [u for u in r["candidates"] if isinstance(stats.get(u), int)]
        r["homepage"] = ok[0] if ok else ""
        r["status"] = stats.get(ok[0]) if ok else None
        r["all_candidates"] = r.pop("candidates")

    got = [r for r in results if r["homepage"]]
    miss = [r for r in results if not r["homepage"]]

    json.dump({"source": LIST_URL, "items": results,
               "resolved": len(got), "unresolved": len(miss)},
              open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print()
    print("=== 识别到主页 (%d/%d) ===" % (len(got), len(results)))
    for r in got:
        print("  %-16s [%s] %s" % (r["name"], r["status"], r["homepage"]))
    if miss:
        print()
        print("=== 未识别 (%d) ===" % len(miss))
        for r in miss:
            print("  %-16s 候选: %s" % (r["name"], r["all_candidates"][:3]))
    print()
    print("written:", DST)


if __name__ == "__main__":
    main()
