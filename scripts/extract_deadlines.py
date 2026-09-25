# -*- coding: utf-8 -*-
"""抓取通知详情页正文, 提取「报名截止时间」, 用于标出正在报名的竞赛。

为什么必须抓正文:
  列表页只有标题和发布日期, **报名截止时间几乎都写在正文里**
  (实测: 随机 14 个详情页, 11 个能提出含截止语义的日期片段)。

提取策略(打分, 不是"找到第一个日期就用"):
  对正文里每个日期, 取前后 40 字上下文打分:
    +3 附近有 报名/注册/申报/提交/报送
    +2 附近有 截止/截至/止于/之前/前
    +1 附近有 校内/选拔/征集
    -6 附近有 发布/来源/发布时间/编辑 (那是通知自身的元信息, 不是截止时间)
  取最高分且 >= 通知发布日期的日期。分数低于阈值的一律留空 —— **宁缺勿错**,
  因为站点上给出错误的截止时间比不给更糟。

日期归一化:
  支持 "2026年9月22日" / "2026-09-22" / "9月22日"(按通知年份推断) / "9.22"
  跨年处理: 若推断出的月份早于通知月份 3 个月以上, 认为说的是次年。

输入:  data/seed/notices.json
输出:  data/seed/deadlines.json
"""
import json
import os
import re
import ssl
import urllib.request
import urllib.error
import gzip
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
NOTICES = os.path.join(SEED, "notices.json")
DST = os.path.join(SEED, "deadlines.json")

MAX_AGE_DAYS = 700        # 只看这段时间内的通知(更老的截止时间已无意义)
MIN_SCORE = 4             # 低于这个分数不输出截止时间
DELAY = 0.25

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
     "Accept-Language": "zh-CN,zh;q=0.9", "Accept-Encoding": "gzip, deflate"}

# 只要标题里出现这些词, 才值得去抓正文看截止时间
INTEREST = ("报名", "选拔", "征集", "申报", "招募", "组织参加", "组织开展", "举办", "开展")


def strip_html(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&ldquo;", "“"), ("&rdquo;", "”"),
                 ("&mdash;", "—"), ("&hellip;", "…"), ("&lt;", "<"), ("&gt;", ">")):
        h = h.replace(a, b)
    return re.sub(r"\s+", " ", h)


def fetch(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        return b.decode("utf-8", "replace")


DATE_PATS = [
    re.compile(r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})\s*日?"),
    re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
]


def find_dates(text, notice_year, notice_month):
    """返回 [(标准日期, 起始位置, 结束位置, 匹配原文)]"""
    out = []
    for m in DATE_PATS[0].finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.append(("%04d-%02d-%02d" % (y, mo, d), m.start(), m.end(), m.group(0)))
    for m in DATE_PATS[1].finditer(text):
        mo, d = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        # 只按通知年份推断; 月份比通知早 3 个月以上时算次年
        y = notice_year + 1 if mo < notice_month - 2 else notice_year
        out.append(("%04d-%02d-%02d" % (y, mo, d), m.start(), m.end(), m.group(0)))
    return out


POS = [("报名", 3), ("注册", 3), ("申报", 3), ("提交", 3), ("报送", 3), ("征集", 2),
       ("截止", 2), ("截至", 2), ("止于", 2), ("之前", 2), ("前", 1),
       ("校内", 1), ("选拔", 1), ("参赛", 1)]
NEG = [("发布时间", -6), ("来源", -6), ("编辑", -6), ("点击数", -6), ("附件", -3),
       ("上一条", -5), ("下一条", -5), ("版权所有", -6)]


def score_at(text, s, e):
    ctx = text[max(0, s - 40):min(len(text), e + 40)]
    sc = 0
    for w, v in POS:
        if w in ctx:
            sc += v
    for w, v in NEG:
        if w in ctx:
            sc += v
    return sc


def extract(title, date, body):
    y, mo = int(date[:4]), int(date[5:7])
    best = (None, -99)
    for iso, s, e, raw in find_dates(body, y, mo):
        if iso < date:          # 早于通知发布的日期不可能是"本次报名截止"
            continue
        sc = score_at(body, s, e)
        if sc > best[1]:
            best = (iso, sc)
    return best


def work(n):
    try:
        html = fetch(n["url"])
    except urllib.error.HTTPError as ex:
        return {"url": n["url"], "error": "HTTP %s" % ex.code}
    except Exception as ex:
        return {"url": n["url"], "error": type(ex).__name__}
    body = strip_html(html)
    dl, sc = extract(n["title"], n["date"], body)
    time.sleep(DELAY)
    return {"url": n["url"], "title": n["title"], "noticeDate": n["date"],
            "deadline": dl, "score": sc, "bodyLen": len(body),
            "snippet": body[:0] or ""}


def main():
    data = json.load(open(NOTICES, encoding="utf-8"))
    items = data["items"]

    import datetime
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=MAX_AGE_DAYS)).isoformat()

    todo = [n for n in items
            if n.get("is_competition")
            and n["date"] >= cutoff
            and any(k in n["title"] for k in INTEREST)]
    # 已提取过的跳过, 支持增量
    prev = {}
    if os.path.exists(DST):
        try:
            prev = {r["url"]: r for r in json.load(open(DST, encoding="utf-8"))["items"]}
        except Exception:
            prev = {}
    todo = [n for n in todo if n["url"] not in prev]

    print("候选通知: %d 条(竞赛相关 + 含报名类关键词 + %d 天内, 已去除抓过的)" % (len(todo), MAX_AGE_DAYS))
    if not todo:
        print("没有新的需要抓取")
    else:
        with ThreadPoolExecutor(max_workers=4) as ex:
            got = list(ex.map(work, todo))
        for r in got:
            prev[r["url"]] = r
        print("本轮抓取: %d, 成功 %d, 失败 %d" % (
            len(got), sum(1 for r in got if "error" not in r),
            sum(1 for r in got if "error" in r)))

    allr = list(prev.values())
    ok = [r for r in allr if r.get("deadline") and r.get("score", 0) >= MIN_SCORE]

    out = {"source": "通知详情页正文", "method": "日期上下文打分(见 scripts/extract_deadlines.py)",
           "min_score": MIN_SCORE, "count": len(allr), "with_deadline": len(ok),
           "items": allr}
    os.makedirs(SEED, exist_ok=True)
    json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print()
    print("累计尝试: %d, 提取到截止时间: %d (%.0f%%)" % (
        len(allr), len(ok), 100.0 * len(ok) / max(len(allr), 1)))
    print("（分数阈值 %d, 低于阈值的一律留空 —— 宁可没有, 不给错的）" % MIN_SCORE)
    print()
    print("=== 提取样例(分数最高的 12 条) ===")
    for r in sorted(ok, key=lambda x: -x["score"])[:12]:
        print("  [%2d] %s  截止 %s  %s" % (r["score"], r["noticeDate"], r["deadline"],
                                           r["title"][:40]))
    print()
    print("written:", DST)


if __name__ == "__main__":
    main()
