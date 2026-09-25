# -*- coding: utf-8 -*-
"""多源抓取西安交通大学各站点的竞赛相关通知。

源清单(每个源的 HTML 结构都实测过):
  1. pec  实践教学中心·竞赛     http://pec.xjtu.edu.cn/cxcy/js.htm      17 页
  2. ee   电气学院·通知公告     http://ee.xjtu.edu.cn/jzxx.htm          48 页
  3. jwc  教务处·教学通知       https://jwc.xjtu.edu.cn/jxxx/jxtz2.htm  620 页

设计要点:
  - **只爬每个源的前 N 页**, 再与已有的 notices.json 按 URL 合并。
    这样每周跑一次很便宜, 而历史会逐周累积, 不会因为只爬前几页而丢数据。
  - 每次都对**全部**记录重跑竞赛名匹配, 这样改进匹配规则后能立刻生效。
  - 各源结构不同, 用 per-source 的正则与 URL 规则描述, 加新源只需加一条配置。
  - 礼貌抓取: 请求间隔 + 自定义 UA + 失败即停不重试风暴。

robots.txt 实测: pec / ee / jwc 均返回 404(未禁止)。只抓通知列表页, 不抓正文。

输出: data/seed/notices.json
"""
import csv
import gzip
import html as htmllib
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
DST = os.path.join(SEED, "notices.json")
MASTER = os.path.join(SEED, "competitions_master.csv")

DELAY = 0.4          # 每次请求之间的间隔(秒)
TIMEOUT = 25

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------- 源配置
# 每个源:
#   key/label   标识与展示名
#   site        所属站点简称
#   page_url(n) 第 n 页的列表地址
#   pattern     在该页 HTML 上匹配 (日期, 链接, 标题) 的正则
#   max_pages   每次最多爬多少页(前 N 页 = 最新的 N 页)
#   normalize   可选, 对匹配到的标题做清理
#
# 注意各源字段顺序不同:
#   pec : <span class="date-list">日期</span><a href title="标题">
#   ee  : <a href><span>日期</span><h3>标题</h3></a>
#   jwc : <a href><i>[分类]</i>标题</a><span>日期</span>
SOURCES = [
    {
        "key": "pec",
        "label": "实践教学中心 · 竞赛",
        "site": "实践教学中心",
        "base": "http://pec.xjtu.edu.cn/cxcy/js",
        "page_url": lambda n, b: (b + ".htm") if n == 1 else ("%s/%d.htm" % (b, n)),
        "pattern": re.compile(
            r'<span class="date-list">\s*(\d{4}-\d{2}-\d{2})\s*</span>\s*'
            r'<a\s+href="([^"]+)"[^>]*?title="([^"]*)"', re.S),
        "order": ("date", "url", "title"),
        "max_pages": 17,
    },
    {
        "key": "ee",
        "label": "电气学院 · 通知公告",
        "site": "电气学院",
        "base": "http://ee.xjtu.edu.cn/jzxx",
        "page_url": lambda n, b: (b + ".htm") if n == 1 else ("%s/%d.htm" % (b, n)),
        "pattern": re.compile(
            r'<a\s+href="([^"]*info/\d+/\d+\.htm)">\s*'
            r'<span>\s*(\d{4}-\d{2}-\d{2})\s*</span>\s*'
            r'<h3>(.*?)</h3>', re.S),
        "order": ("url", "date", "title"),
        # 实测: 前 10 页 100 条里竞赛相关 0 条 —— 这个栏目实际是行政通知
        # (转专业、推免实施细则、直博生确认、选课计划)。竞赛内容不在官网,
        # 学院主要通过公众号发布。所以只保留 3 页做兜底, 靠 is_competition
        # 过滤在页面上屏蔽噪声。
        "max_pages": 3,
    },
    {
        "key": "jwc",
        "label": "教务处 · 教学通知",
        "site": "教务处",
        "base": "https://jwc.xjtu.edu.cn/jxxx/jxtz2",
        "page_url": lambda n, b: (b + ".htm") if n == 1 else ("%s/%d.htm" % (b, n)),
        "pattern": re.compile(
            r'<a\s+href="([^"]*info/\d+/\d+\.htm)">'
            r'(?:<i>\s*\[[^\]]*\]\s*</i>)?'
            r'(.*?)</a>\s*<span>\s*(\d{4}-\d{2}-\d{2})\s*</span>', re.S),
        "order": ("url", "title", "date"),
        "max_pages": 5,
    },
]

# 实测过但未纳入的源(记录原因, 免得以后重复调研):
SKIPPED = {
    "ee.xjtu.edu.cn/dtgh/txgz.htm": "电气学院·团学工作, 内容是党团活动(团组织生活会、党支部大会), 非竞赛; 且为图片卡片结构",
    "news.xjtu.edu.cn": "图文新闻门户, 列表项无日期, 内容以新闻报道而非通知为主, 信号弱",
    "gs.xjtu.edu.cn": "研究生院, 首页以招生/培养通知为主(录取通知书、导师培训), 与本科竞赛关系弱",
    "tuanwei.xjtu.edu.cn": "校团委, 是 Nuxt.js 单页应用(路由 /passage?id=N), 需要额外解析 __NUXT__ 载荷",
    "jwc竞赛专栏": "教务处无独立竞赛栏目 —— 实测创新大赛通知属于'教学通知'(jxtz2), 已包含在内",
}


# ---------------------------------------------------------------- 抓取
def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")


def clean_title(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- API 源
# 校团委是 Nuxt.js 单页应用: 页面内容全部由前端从 /api/v1 拉取, HTML 里没有数据
# (__NUXT__ 载荷是空的)。逆向它的 JS bundle 后拿到确切接口, 注意参数是**小写**的
# catalogId/page/limit —— 用大写的 Id/Page/Limit 会报"必填字段"错误。
#   GET /api/v1/catalogs                              -> 栏目树(拿到 catalogId)
#   GET /api/v1/secondCatalog?catalogId=&page=&limit= -> 二级栏目文章列表
# 返回 {"success":true,"data":{"total":476,"data":[
#         {"articleId":4760,"headline":"...","publish":"2026-09-14"}]}}
# 文章地址: https://tuanwei.xjtu.edu.cn/passage?id={articleId}
#
# 这一路很关键: 挑战杯、腾飞杯这类归口团委的竞赛, 通知只发在这里,
# 实践教学中心没有。
API_BASE = "https://tuanwei.xjtu.edu.cn/api/v1"
API_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://tuanwei.xjtu.edu.cn/",
}
API_SOURCES = [
    # 通知公告(id=9): 主力, 476 条, 首页 50 条里 40 条与竞赛相关
    {"key": "tuanwei", "label": "校团委 · 通知公告", "site": "校团委",
     "catalog_id": 9, "max_pages": 12, "limit": 50},
    # 团学快讯(id=14): 1053 条, 更新最勤, 竞赛类占比低但时效好
    {"key": "tuanwei_news", "label": "校团委 · 团学快讯", "site": "校团委",
     "catalog_id": 14, "max_pages": 4, "limit": 50},
    # 媒体聚焦(id=10) 与 活动预告(id=15): 量小, 顺带抓
    {"key": "tuanwei_media", "label": "校团委 · 媒体聚焦", "site": "校团委",
     "catalog_id": 10, "max_pages": 2, "limit": 50},
    {"key": "tuanwei_act", "label": "校团委 · 活动预告", "site": "校团委",
     "catalog_id": 15, "max_pages": 2, "limit": 50},
]


def crawl_api_source(src, stats):
    """爬一个 API 源(团委这种客户端渲染的站点)。"""
    out = []
    for page in range(1, src["max_pages"] + 1):
        q = urllib.parse.urlencode({"catalogId": src["catalog_id"],
                                    "page": page, "limit": src["limit"]})
        try:
            req = urllib.request.Request(API_BASE + "/secondCatalog?" + q,
                                         headers=API_HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            d = json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:
            print("    [%s] 第 %d 页停止: %s" % (src["key"], page, str(e)[:60]))
            break

        if not d.get("success"):
            print("    [%s] 第 %d 页接口报错: %s" % (
                src["key"], page, str(d.get("message"))[:50]))
            break
        block = d.get("data") or {}
        rows = block.get("data") or []
        if not rows:
            print("    [%s] 第 %d 页无数据, 停止" % (src["key"], page))
            break

        for it in rows:
            aid, head, pub = it.get("articleId"), it.get("headline"), it.get("publish")
            if not (aid and head and pub):
                continue
            out.append({
                "date": str(pub)[:10],
                "title": re.sub(r"\s+", " ", head).strip(),
                "url": "https://tuanwei.xjtu.edu.cn/passage?id=%s" % aid,
                "source": src["key"],
                "site": src["site"],
            })

        print("    [%s] 第 %2d 页: %d 条 (源累计 %d / 站内共 %s)" % (
            src["key"], page, len(rows), len(out), block.get("total")))
        if len(rows) < src["limit"]:
            break
        time.sleep(DELAY)
    stats[src["key"]] = stats.get(src["key"], 0) + len(out)
    return out


def crawl_source(src, stats):
    """爬一个源的前 max_pages 页, 返回通知列表。"""
    out = []
    for n in range(1, src["max_pages"] + 1):
        url = src["page_url"](n, src["base"])
        try:
            status, text = fetch(url)
        except Exception as e:
            print("    [%s] 第 %d 页停止: %s" % (src["key"], n, str(e)[:60]))
            break

        hits = src["pattern"].findall(text)
        if not hits:
            print("    [%s] 第 %d 页无匹配, 停止" % (src["key"], n))
            break

        idx = {name: i for i, name in enumerate(src["order"])}
        for h in hits:
            rec = {
                "date": h[idx["date"]],
                "title": clean_title(h[idx["title"]]),
                "url": urllib.parse.urljoin(url, htmllib.unescape(h[idx["url"]])),
                "source": src["key"],
                "site": src["site"],
            }
            if rec["title"] and rec["date"]:
                out.append(rec)

        stats[src["key"]] = stats.get(src["key"], 0) + len(hits)
        print("    [%s] 第 %2d 页: %d 条 (源累计 %d)" % (src["key"], n, len(hits), len(out)))
        time.sleep(DELAY)
    return out


# ---------------------------------------------------------------- 相关性分类
# 多源聚合后, 教务处/电气学院的通知里会混进大量与竞赛无关的内容
# (停水通知、考试安排、教材结算...)。按标题关键词打标, 站点默认只展示竞赛相关的。
COMPETITION_WORDS = [
    "竞赛", "大赛", "挑战杯", "选拔赛", "报名", "参赛", "创新创业", "创新大赛",
    "学科竞赛", "科技竞赛", "擂台", "赛区", "杯赛", "初赛", "复赛", "决赛",
    "校赛", "省赛", "国赛", "获奖", "佳绩", "夺冠", "特等奖", "一等奖", "二等奖",
    "三等奖", "金奖", "银奖", "晋级", "训练营", "集训", "战队",
]


def is_competition_related(title):
    return any(w in title for w in COMPETITION_WORDS)


# ---------------------------------------------------------------- 竞赛名匹配
STRIP_PREFIX = ["全国大学生", "中国大学生", "全国高校", "中国高校", "全国",
                "国际大学生", "大学生"]
STRIP_SUFFIX = ["竞赛", "大赛", "比赛", "挑战赛", "赛", "(CULSC)", "（CULSC）"]
MIN_KEYWORD = 6


def keywords_of(name):
    n = re.sub(r"[“”\"'（）()·\-\s]", "", name)
    parts = {n}
    for piece in re.split(r"暨", n):
        if len(piece) >= MIN_KEYWORD:
            parts.add(piece)
    for inner in re.findall(r"[（(]([^）)]*)[）)]", n):
        if len(inner) >= MIN_KEYWORD:
            parts.add(inner)
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


def load_competition_keywords():
    if not os.path.exists(MASTER):
        return []
    with open(MASTER, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    idx = []
    for c in rows:
        for kw in keywords_of(c["竞赛名称"]):
            idx.append((kw, c["竞赛名称"], c.get("教育部目录序号") or ""))
    idx.sort(key=lambda t: -len(t[0]))
    return idx


def match_notice(title, idx):
    t = re.sub(r"[“”\"'（）()·\-\s]", "", title)
    for kw, name, no in idx:
        if kw in t:
            return name, no, kw
    return None, None, None


# ---------------------------------------------------------------- 主流程
def load_existing():
    if not os.path.exists(DST):
        return []
    try:
        with open(DST, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def main():
    existing = load_existing()
    print("已有记录: %d 条(将按 URL 合并, 不丢历史)" % len(existing))

    fresh = []
    stats = {}
    for src in SOURCES:
        print("\n=== %s (%s) ===" % (src["label"], src["key"]))
        fresh.extend(crawl_source(src, stats))

    for src in API_SOURCES:
        print("\n=== %s (%s) ===" % (src["label"], src["key"]))
        fresh.extend(crawl_api_source(src, stats))

    # ---- 按 URL 合并: 新抓的覆盖旧的(标题可能被修正) ----
    merged = {}
    for n in existing:
        merged[n["url"]] = n
    added = 0
    for n in fresh:
        u = n["url"]
        if u not in merged:
            added += 1
        old = merged.get(u, {})
        old.update(n)                    # 保留旧记录里可能有的额外字段
        merged[u] = old

    # ---- 对整个集合重跑竞赛名匹配(改进规则后能立即生效) ----
    idx = load_competition_keywords()
    print("\n竞赛关键词: %d 个 (覆盖 %d 条竞赛)" % (len(idx), len(set(k[1] for k in idx))))
    items = list(merged.values())
    for n in items:
        cname, cno, kw = match_notice(n["title"], idx)
        n["competition"] = cname or ""
        n["moe_no"] = cno or ""
        n["matched_keyword"] = kw or ""
        n["is_competition"] = is_competition_related(n["title"])

    items.sort(key=lambda x: (x["date"], x["title"]), reverse=True)
    matched = sum(1 for n in items if n["competition"])
    comp_related = sum(1 for n in items if n["is_competition"])

    by_site = {}
    by_site_comp = {}
    for n in items:
        s = n.get("site", "?")
        by_site[s] = by_site.get(s, 0) + 1
        if n["is_competition"]:
            by_site_comp[s] = by_site_comp.get(s, 0) + 1

    payload = {
        "source": {
            "title": "西安交通大学 · 竞赛相关通知(多源聚合)",
            "sites": [{"key": s["key"], "label": s["label"], "base": s["base"],
                       "pages_crawled_cap": s["max_pages"]} for s in SOURCES],
            "skipped": SKIPPED,
            "crawler": "scripts/crawl_xjtu_notices.py",
            "note": ("只抓各源前 N 页的通知列表(不抓正文), 与历史记录按 URL 合并累积; "
                     "robots.txt 实测均为 404 未禁止"),
        },
        "schema_version": 2,
        "count": len(items),
        "matched_count": matched,
        "competition_related_count": comp_related,
        "by_site": by_site,
        "by_site_competition": by_site_comp,
        "items": items,
    }
    os.makedirs(SEED, exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 58)
    print("本次新抓 : %d 条" % len(fresh))
    print("新增(去重后): %d 条" % added)
    print("合并后总计 : %d 条" % len(items))
    print("其中竞赛相关: %d 条 (%.0f%%)" % (comp_related, 100.0 * comp_related / max(len(items), 1)))
    print("已关联到具体竞赛: %d (%.0f%%)" % (matched, 100.0 * matched / max(len(items), 1)))
    if items:
        print("日期范围   : %s ~ %s" % (min(n["date"] for n in items),
                                       max(n["date"] for n in items)))
    print("按来源(总/竞赛相关):")
    for k, v in sorted(by_site.items(), key=lambda kv: -kv[1]):
        print("    %-14s %4d / %4d 条" % (k, v, by_site_comp.get(k, 0)))
    print("written    : %s (%.0f KB)" % (DST, os.path.getsize(DST) / 1024.0))
    print()
    print("=== 最近 8 条竞赛相关 ===")
    for n in [x for x in items if x["is_competition"]][:8]:
        tag = ("-> " + n["competition"][:18]) if n["competition"] else ""
        print("  %s [%s] %s %s" % (n["date"], n.get("site", "?")[:5], n["title"][:36], tag))


if __name__ == "__main__":
    sys.exit(main())
