# -*- coding: utf-8 -*-
"""增量抓取校内通知详情页正文。

列表页只有标题。报名截止、联系人、报名表、具体安排几乎都写在正文里。
本脚本在已有 notices.json 上按 URL 补正文, 已抓过的默认跳过。

两条路(均实测):
  1. 实践教学中心 / 教务处 / 电气学院: 西交通用 CMS,
     正文在 <div class="v_news_content"> … </div>
  2. 校团委: SPA, HTML 壳里没有正文。用列表里已经拿到的 articleId:
     GET https://tuanwei.xjtu.edu.cn/api/v1/article?articleId=

不抓什么、为什么:
  - 不把全文塞进 site/data.js(会把静态站撑到数 MB, 双击打开也变慢)。
    站点只带「摘要 + 关键链接 + 联系人」, 全文留在 data/seed/notice_bodies.json
    给截止日期提取和以后检索用。
  - 不抓微信公众号正文。搜狗结果没有 mp.weixin 直链, 绕过 antispider
    需要登录态/验证码, 本项目不做。公众号页继续用标题+摘要线索。
  - 不抓全部历史。默认: 竞赛相关, 或近 MAX_AGE_DAYS 天内。更老的教学通知
    正文对「现在要报名」几乎没用, 省请求。

礼貌: 间隔 DELAY, 失败记 error 不重试风暴, 线程数很小。

输入:  data/seed/notices.json
输出:  data/seed/notice_bodies.json
"""
import argparse
import datetime
import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import zlib
from notice_content import Tree, cms_root, extract
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
NOTICES = os.path.join(SEED, "notices.json")
DST = os.path.join(SEED, "notice_bodies.json")

DELAY = 0.28
TIMEOUT = 25
MAX_AGE_DAYS = 540
MAX_EXCERPT = 480
WORKERS = 4

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
API_HEADERS = dict(HEADERS)
API_HEADERS["Accept"] = "application/json, text/plain, */*"
API_HEADERS["Referer"] = "https://tuanwei.xjtu.edu.cn/"



def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        elif r.headers.get("Content-Encoding") == "deflate":
            raw = zlib.decompress(raw)
        return raw.decode("utf-8", "replace")


def excerpt_of(text):
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= MAX_EXCERPT:
        return t
    cut = t[:MAX_EXCERPT]
    for sep in ("。", "；", ";", "！", "？"):
        i = cut.rfind(sep)
        if i >= MAX_EXCERPT * 0.55:
            return cut[:i + 1]
    return cut.rstrip() + "…"


def extract_contact(text):
    name, phone, email, qq = "", "", "", ""
    m = re.search(r"联系人[：: \t]*([^\s，,。；;（(、\n]{2,24})", text)
    if m:
        name = m.group(1).strip(" ：:、")
        name = re.split(r"\d|电话|手机", name, maxsplit=1)[0].strip(" ：:、")
    m = re.search(
        r"(?:联系电话|电话|手机|Tel)[：:\s]*((?:\+?86[-\s]?)?1\d{10}|\d{3,4}[-\s]?\d{7,8})",
        text, re.I)
    if m:
        phone = re.sub(r"\s+", "", m.group(1))
    if not phone:
        m = re.search(r"联系人[^\n]{0,40}?(1\d{10})(?!\d)", text)
        if m:
            phone = m.group(1)
    m = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text)
    if m:
        email = m.group(1)
    m = re.search(r"(?:QQ|qq)(?:交流群|群)?[：:\s]*(\d{5,12})", text)
    if m:
        qq = m.group(1)
    return name, phone, email, qq


def parse_cms(html, page_url):
    content = extract(cms_root(html, page_url), page_url)
    return content["body"], content["links"]


def parse_tuanwei(data, page_url):
    content = extract(Tree(data.get("content") or "").root, page_url, data.get("attachments"))
    return content["body"], content["links"]


def tuanwei_id(url):
    ids = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("id", [])
    return ids[0] if ids and ids[0].isdigit() else ""


def fetch_tuanwei(url):
    """Public article API adapter; never parse the SPA shell as an article."""
    aid = tuanwei_id(url)
    if not aid:
        raise ValueError("no_article_id")
    data = json.loads(fetch("https://tuanwei.xjtu.edu.cn/api/v1/article?articleId=" + aid,
                            headers=API_HEADERS))
    if data.get("success") is not True:
        raise ValueError("api_failure: " + str(data.get("message") or "fail"))
    article = data.get("data")
    if not isinstance(article, dict):
        raise ValueError("api_invalid_article")
    content = article.get("content") or ""
    if not isinstance(content, str):
        raise ValueError("api_invalid_content")
    return extract(Tree(content).root, url, article.get("attachments")), article


def crawl_one(n):
    url = n["url"]
    rec = {
        "url": url,
        "title": n.get("title", ""),
        "site": n.get("site", ""),
        "date": n.get("date", ""),
        "source": n.get("source") or n.get("site", ""),
        "fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "failed", "error": "", "contentHash": "",
        "body": "", "bodyHtml": "", "bodyLen": 0, "excerpt": "",
        "paragraphs": [], "tables": [], "blocks": [], "images": [], "attachments": [], "links": [],
        "contact": "", "phone": "", "email": "", "qq": "",
    }
    try:
        if urllib.parse.urlsplit(url).hostname == "tuanwei.xjtu.edu.cn":
            content, article = fetch_tuanwei(url)
            rec.update(title=article.get("headline") or rec["title"],
                       date=str(article.get("publish") or rec["date"])[:10],
                       source=article.get("source") or rec["source"])
        else:
            html = fetch(url)
            content = extract(cms_root(html, url), url)
        rec.update(content)
    except urllib.error.HTTPError as ex:
        rec["error"] = "HTTP %s" % ex.code
        return rec
    except Exception as ex:
        rec["error"] = type(ex).__name__ + ":" + str(ex)[:80]
        return rec

    body, links = rec["body"], rec["links"]
    if not body and not rec["images"] and not rec["attachments"]:
        rec["status"] = "empty"
        rec["error"] = "empty_content"
        return rec

    name, phone, email, qq = extract_contact(body)
    rec.update({
        "status": "success",
        "body": body,
        "bodyLen": len(body),
        "excerpt": excerpt_of(body),
        "links": links,
        "contact": name,
        "phone": phone,
        "email": email,
        "qq": qq,
    })
    return rec


def crawl_paced(n):
    try:
        return crawl_one(n)
    finally:
        time.sleep(DELAY)


def should_fetch(n, cutoff):
    if n.get("is_competition"):
        return True
    return (n.get("date") or "") >= cutoff


def load_prev():
    if not os.path.exists(DST):
        return {}
    with open(DST, encoding="utf-8") as f:
        return {r["url"]: r for r in json.load(f).get("items", []) if r.get("url")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本轮最多新抓多少条(0=不限制)")
    ap.add_argument("--force", action="store_true", help="已有正文也重抓")
    ap.add_argument("--url", action="append", default=[], help="只抓指定通知 URL，可重复指定；也可抽样列表外文章")
    args = ap.parse_args(argv)
    if args.limit < 0:
        ap.error("--limit 不能为负数")

    with open(NOTICES, encoding="utf-8") as f:
        notices = json.load(f)["items"]
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=MAX_AGE_DAYS)).isoformat()
    prev = load_prev()
    # Older cached images lack caption context. Upgrade from preserved HTML,
    # without requesting the page or changing its original fetch timestamp.
    for record in prev.values():
        if record.get("status") == "success" and record.get("bodyHtml") and any("context" not in i for i in record.get("images", [])):
            record.update(extract(Tree(record["bodyHtml"]).root, record["url"], record.get("attachments", [])))

    def have_ok(u):
        r = prev.get(u) or {}
        return (not args.force) and r.get("status") == "success" and "bodyHtml" in r and bool(r.get("contentHash"))

    todo = [n for n in notices if should_fetch(n, cutoff) and not have_ok(n["url"])]
    if args.url:
        by_url = {n["url"]: n for n in notices}
        todo = [by_url.get(u, {"url": u}) for u in dict.fromkeys(args.url) if not have_ok(u)]
    todo.sort(key=lambda x: x.get("date", ""), reverse=True)
    if args.limit:
        todo = todo[:args.limit]

    print("候选: %d 条 (竞赛相关 或 %s 之后; 已有正文 %d)" % (
        len(todo), cutoff, sum(1 for r in prev.values() if r.get("body"))))
    if todo:
        ok = fail = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(crawl_paced, n): n["url"] for n in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                rec = fut.result()
                old = prev.get(rec["url"], {})
                if rec["status"] != "success":
                    previous = old if old.get("status") == "success" else old.get("lastSuccess")
                    if previous:
                        rec["lastSuccess"] = previous
                    fail += 1
                else:
                    ok += 1
                prev[rec["url"]] = rec
                if i % 20 == 0 or i == len(todo):
                    print("  进度 %d/%d  成功 %d  失败 %d" % (i, len(todo), ok, fail))
        print("本轮: 成功 %d, 失败 %d" % (ok, fail))

    items = list(prev.values())
    items.sort(key=lambda x: x.get("fetchedAt", ""), reverse=True)
    good = [r for r in items if r.get("status") == "success"]
    payload = {
        "source": "校内通知详情页正文",
        "crawler": "scripts/crawl_notice_bodies.py",
        "schema_version": 2,
        "byStatus": {s: sum(r.get("status") == s for r in items) for s in ("success", "empty", "failed")},
        "maxAgeDays": MAX_AGE_DAYS,
        "count": len(items),
        "withBody": len(good),
        "items": items,
    }
    os.makedirs(SEED, exist_ok=True)
    with open(DST + ".tmp", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(DST + ".tmp", DST)

    print()
    print("累计: %d 条, 有正文 %d (%.0f%%)" % (
        len(items), len(good), 100.0 * len(good) / max(len(items), 1)))
    print("written: %s (%.0f KB)" % (DST, os.path.getsize(DST) / 1024.0))
    print("样例:")
    for r in [x for x in good if x.get("contact") or x.get("links")][:5]:
        print("  %s  联系人=%s  链接=%d  %s" % (
            r.get("site", ""), r.get("contact") or "-", len(r.get("links") or []),
            (r.get("title") or "")[:36]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
