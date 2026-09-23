# -*- coding: utf-8 -*-
"""爬取西安交通大学实践教学中心「竞赛」栏目通知列表。

来源: http://pec.xjtu.edu.cn/cxcy/js.htm  (第 1 页)
      http://pec.xjtu.edu.cn/cxcy/js/N.htm  (第 N 页, 实测共 17 页)
      robots.txt 返回 404(即未禁止), 页面为纯 HTML + 稳定分页, 无验证码。

输出: data/seed/notices.json
      - 每条通知: 标题 / 发布日期 / 详情 URL / 抓取时间
      - 尝试把通知标题关联到 competitions_master 里的竞赛(保守匹配, 宁缺勿错)

页面结构(实测):
    <li><i></i><span class="date-list">2026-09-23</span>
        <a href="../info/1191/5526.htm" target="_blank" title="标题">标题</a></li>
"""
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "data", "seed", "notices.json")
MASTER = os.path.join(ROOT, "data", "seed", "competitions_master.csv")

BASE = "http://pec.xjtu.edu.cn/cxcy/js"
SOURCE = BASE + ".htm"
HOST = "http://pec.xjtu.edu.cn"
MAX_PAGES = 30          # 安全上限; 遇到 404 即停
DELAY = 0.4             # 请求间隔, 对学校站点友好一些

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": SOURCE,
    "Accept-Language": "zh-CN,zh;q=0.9",
}

ITEM_RE = re.compile(
    r'<span class="date-list">\s*(\d{4}-\d{2}-\d{2})\s*</span>\s*'
    r'<a\s+href="([^"]+)"[^>]*?title="([^"]*)"',
    re.S)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.read()


def page_url(n):
    return SOURCE if n == 1 else "%s/%d.htm" % (BASE, n)


def abs_url(href):
    href = html.unescape(href).strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return HOST + href
    # 形如 ../info/1191/5526.htm  ->  http://pec.xjtu.edu.cn/info/1191/5526.htm
    return HOST + "/" + href.lstrip("./")


def load_competitions():
    """从总表读取竞赛名, 用于把通知关联到竞赛。"""
    if not os.path.exists(MASTER):
        return []
    import csv
    with open(MASTER, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# 匹配时要去掉的通用前后缀, 否则"全国大学生"之类会导致大量误匹配
STRIP_PREFIX = ["全国大学生", "中国大学生", "全国高校", "中国高校", "全国",
                "国际大学生", "大学生"]
STRIP_SUFFIX = ["竞赛", "大赛", "比赛", "挑战赛", "赛", "(CULSC)", "（CULSC）"]
# 太短的词容易误匹配, 低于该长度不作为关键词
MIN_KEYWORD = 6


def keywords_of(name):
    """为一个竞赛名生成用于匹配通知标题的关键词。

    要点: 通知标题里很少写完整赛名。例如
      "中国机器人大赛（暨RoboCup中国大赛）" 在标题里是 "2026中国机器人大赛暨RoboCup机器人世界杯中国赛"
    —— 所以除了全名, 还要按 "暨"/括号切出子串, 并去掉常见前后缀。
    """
    n = re.sub(r"[“”\"'（）()·\-\s]", "", name)
    parts = {n}
    # 按 "暨" 切分, 并单独取出括号内的内容
    for piece in re.split(r"暨", n):
        if len(piece) >= MIN_KEYWORD:
            parts.add(piece)
    for inner in re.findall(r"[（(]([^）)]*)[）)]", n):
        if len(inner) >= MIN_KEYWORD:
            parts.add(inner)
    # 去掉括号后剩下的主干也要留一份
    stem = re.sub(r"[（(][^）)]*[）)]", "", n)
    if len(stem) >= MIN_KEYWORD:
        parts.add(stem)

    kws = set()
    for p in parts:
        kws.add(p)
        for pre in STRIP_PREFIX:
            if p.startswith(pre) and len(p) - len(pre) >= MIN_KEYWORD:
                kws.add(p[len(pre):])
        for suf in STRIP_SUFFIX:
            if p.endswith(suf) and len(p) - len(suf) >= MIN_KEYWORD:
                kws.add(p[: -len(suf)])
    return {k for k in kws if len(k) >= MIN_KEYWORD}


def build_matcher(comps):
    """返回 [(keyword, 竞赛名, 教育部序号)] , 关键词长的优先。"""
    idx = []
    for c in comps:
        for kw in keywords_of(c["竞赛名称"]):
            idx.append((kw, c["竞赛名称"], c.get("教育部目录序号") or ""))
    idx.sort(key=lambda t: -len(t[0]))
    return idx


def match_notice(title, idx):
    """保守匹配: 命中最长的关键词, 且要求关键词确实出现在标题里。"""
    t = re.sub(r"[“”\"'（）()·\-\s]", "", title)
    for kw, name, no in idx:
        if kw in t:
            return name, no, kw
    return None, None, None


def main():
    comps = load_competitions()
    idx = build_matcher(comps)
    print("已载入竞赛 %d 条, 生成关键词 %d 个" % (len(comps), len(idx)))

    notices, seen = [], set()
    pages_ok = 0
    for n in range(1, MAX_PAGES + 1):
        url = page_url(n)
        try:
            status, raw = fetch(url)
        except Exception as e:
            print("  第 %2d 页 停止: %s" % (n, str(e)[:60]))
            break
        text = raw.decode("utf-8", "replace")
        hits = ITEM_RE.findall(text)
        if not hits:
            print("  第 %2d 页 无条目, 停止" % n)
            break
        pages_ok += 1
        for date, href, title in hits:
            u = abs_url(href)
            if u in seen:
                continue
            seen.add(u)
            title = html.unescape(title).strip()
            cname, cno, kw = match_notice(title, idx)
            notices.append({
                "title": title,
                "date": date,
                "url": u,
                "competition": cname,
                "moe_no": cno,
                "matched_keyword": kw,
                "source_page": n,
            })
        print("  第 %2d 页: %d 条 (累计 %d)" % (n, len(hits), len(notices)))
        time.sleep(DELAY)

    notices.sort(key=lambda x: (x["date"], x["title"]), reverse=True)
    matched = sum(1 for x in notices if x["competition"])

    payload = {
        "source": {
            "title": "西安交通大学实践教学中心 · 竞赛通知",
            "url": SOURCE,
            "host": HOST,
            "pages_crawled": pages_ok,
            "crawler": "scripts/crawl_xjtu_notices.py",
            "note": "robots.txt 返回 404(未禁止); 页面为纯 HTML 稳定分页",
        },
        "schema_version": 1,
        "count": len(notices),
        "matched_count": matched,
        "items": notices,
    }
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print()
    print("抓取页数 : %d" % pages_ok)
    print("通知条数 : %d" % len(notices))
    print("已关联竞赛: %d (%.0f%%)" % (matched, 100.0 * matched / max(len(notices), 1)))
    if notices:
        print("日期范围 : %s ~ %s" % (min(n["date"] for n in notices),
                                      max(n["date"] for n in notices)))
    print("written  : %s" % DST)
    print()
    print("=== 最近 8 条 ===")
    for n in notices[:8]:
        tag = ("→ " + n["competition"][:20]) if n["competition"] else ""
        print("  %s  %s  %s" % (n["date"], n["title"][:44], tag))


if __name__ == "__main__":
    sys.exit(main())
