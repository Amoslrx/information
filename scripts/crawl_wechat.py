# -*- coding: utf-8 -*-
"""抓取微信公众号文章的「标题 + 日期 + 摘要 + 公众号名」。

## 为什么只能做到这个程度

微信公众号没有公开 API。实测过的三条路:
  1. 单篇文章 URL 直接抓  -> **可以**, 正文完整(但需要有 URL)
  2. 公众号历史消息列表   -> **不行**, profile_ext 返回空壳页, 需要微信客户端登录态
  3. 搜狗微信搜索         -> **可以拿标题/日期/摘要, 但拿不到真实文章 URL**
     结果里的 /link?url=... 点击会被 antispider 拦; 页面 HTML 里也没有
     mp.weixin.qq.com 直链(实测 0 个)。

所以本站收录的是「线索」: 让你知道**有什么文章、什么时候发的、大概讲什么**,
正文需要自己在微信里看。站点上会给一个"去搜狗搜这条"的按钮 ——
反爬针对的是无 cookie 的程序请求, 真人浏览器通常能点进去。

## 实测的索引新鲜度
搜狗微信的索引**不是**全过期: 查"南洋书院 活动"最新能到 2026-09-16(查询当天 09-26)。
新鲜度取决于查询词, 冷门词会返回很旧的结果。

输入: 无
输出: data/seed/wechat.json
"""
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
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
DST = os.path.join(SEED, "wechat.json")

DELAY = 1.6          # 搜狗有反爬, 请求间隔给足
TIMEOUT = 25

# 查询词: 分三组。搜狗匹配的是文章内容, 所以"书院名 + 活动类词"最好用。
# 书院名用官方的全称("西安交通大学南洋书院"就是它的公众号名)。
QUERIES = [
    # 1) 周活动预告系列 —— 最直接对应"有什么活动、能加德育分"
    "一周活动早知道 南洋书院",
    "南洋书院 活动预告",
    "彭康书院 活动",
    "文治书院 活动",
    "崇实书院 活动预告",
    "启德书院 活动预告",
    "宗濂书院 活动",
    "仲英书院 活动",
    "励志书院 活动",
    "钱学森书院 活动",
    # 2) 用户点名的重要活动
    "星荧夜跑",
    "校园大使 西安交通大学",
    "西安交通大学 运动会",
    "西安交通大学 德育积分",
    # 3) 竞赛与实践(与站点其他板块互补)
    "腾飞杯 西安交通大学",
    "西安交通大学 社会实践 书院",
    "西安交通大学电气学院 竞赛",
    "西安交通大学电气学院 活动预告",
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://weixin.sogou.com/",
}

BLOCK_RE = re.compile(r'<li id="sogou_vr_11002601_box_')
TITLE_RE = re.compile(r'uigs="article_title_\d+"[^>]*>(.*?)</a>', re.S)
SNIP_RE = re.compile(r'<p class="txt-info"[^>]*>(.*?)</p>', re.S)
ACC_RE = re.compile(r'<span class="all-time-y2">(.*?)</span>', re.S)
TS_RE = re.compile(r"timeConvert\('(\d+)'\)")


def clean(s):
    """去标签 + 解实体 + 去掉搜狗的高亮标记。"""
    s = re.sub(r"<!--.*?-->", "", s or "")
    s = re.sub(r"</?em>", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return r.status, r.geturl(), raw.decode("utf-8", "replace")


def search(query):
    """查一个关键词, 返回文章列表。失败返回 []。"""
    url = "https://weixin.sogou.com/weixin?type=2&query=" + urllib.parse.quote(query)
    try:
        status, final, body = fetch(url)
    except Exception as e:
        print("      [%s] 请求失败: %s" % (query[:16], str(e)[:50]))
        return []
    # 被反爬挡了会跳到 antispider
    if "antispider" in final or "请输入验证码" in body:
        print("      [%s] !! 触发反爬, 跳过" % query[:16])
        return []

    out = []
    blocks = BLOCK_RE.split(body)
    for b in blocks[1:]:
        t = TITLE_RE.search(b)
        if not t:
            continue
        ts = TS_RE.search(b)
        sn = SNIP_RE.search(b)
        ac = ACC_RE.search(b)
        d = ""
        if ts:
            try:
                d = datetime.datetime.fromtimestamp(int(ts.group(1))).strftime("%Y-%m-%d")
            except Exception:
                d = ""
        out.append({
            "title": clean(t.group(1)),
            "date": d,
            "snippet": clean(sn.group(1)) if sn else "",
            "account": clean(ac.group(1)) if ac else "",
            "query": query,
            # 拿不到真实文章 URL, 给一个搜狗搜索链接 —— 真人浏览器点通常能进去
            "searchUrl": "https://weixin.sogou.com/weixin?type=2&query=" +
                         urllib.parse.quote(clean(t.group(1))[:40]),
        })
    return out


def load_existing():
    if not os.path.exists(DST):
        return []
    try:
        with open(DST, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


def classify(title):
    """复用站点的 5 大类口径(与 build_site_data 保持一致)。"""
    KW = [
        ("等级考试", ["四六级", "四、六级", "四级", "六级", "CET", "计算机等级", "等级考试"]),
        ("思政学习", ["思政", "理论学习", "党课", "团课", "星航", "正心", "青马", "主题教育",
                      "党校", "团校", "党日", "团日", "四史", "党支部", "团支部", "党建", "团建"]),
        ("学科竞赛", ["竞赛", "大赛", "挑战杯", "创新创业", "创新大赛", "擂台", "作品赛",
                      "数学建模", "电子设计", "机器人", "腾飞杯", "智能汽车"]),
        ("文体竞赛", ["运动会", "田径", "篮球", "足球", "排球", "羽毛球", "乒乓球", "网球",
                      "游泳", "体育", "健身", "文艺", "歌手", "舞蹈", "合唱", "乐团", "艺术",
                      "书法", "绘画", "摄影", "演讲", "辩论", "主持", "话剧", "晚会", "文化节",
                      "夜跑", "游园"]),
        ("社会实践", ["社会实践", "志愿服务", "志愿者", "支教", "三下乡", "西部计划", "挂职",
                      "见习", "公益", "义工", "勤工助学", "研学", "实践", "志愿"]),
        ("教学信息", ["选课", "评教", "考试", "补考", "缓考", "重修", "学籍", "成绩单",
                      "辅修", "转专业", "培养方案", "学位", "毕业", "课程", "学分", "讲座",
                      "导师", "午餐会"]),
    ]
    for name, kws in KW:
        if any(k in title for k in kws):
            return name
    return "其他"


def main():
    existing = load_existing()
    seen = {(x.get("account", ""), x.get("title", "")) for x in existing}
    print("已有文章: %d 条" % len(existing))

    added = 0
    blocked = 0
    for i, q in enumerate(QUERIES, 1):
        print("  [%2d/%d] 查询: %s" % (i, len(QUERIES), q))
        rows = search(q)
        if not rows:
            blocked += 1
        for r in rows:
            key = (r["account"], r["title"])
            if not r["title"] or key in seen:
                continue
            seen.add(key)
            r["cat"] = classify(r["title"])
            existing.append(r)
            added += 1
        print("        命中 %d 条 (新增 %d, 累计 %d)" % (len(rows), added, len(existing)))
        time.sleep(DELAY)

    existing.sort(key=lambda x: (x.get("date") or "", x.get("title") or ""), reverse=True)
    by_cat, by_acc = {}, {}
    for x in existing:
        by_cat[x.get("cat", "其他")] = by_cat.get(x.get("cat", "其他"), 0) + 1
        if x.get("account"):
            by_acc[x["account"]] = by_acc.get(x["account"], 0) + 1

    payload = {
        "source": {
            "title": "微信公众号文章线索(标题/日期/摘要)",
            "engine": "搜狗微信搜索 https://weixin.sogou.com/",
            "crawler": "scripts/crawl_wechat.py",
            "queries": QUERIES,
            "limitation": ("微信没有公开 API。本站收录的是**线索**: 标题、日期、摘要、公众号名。"
                           "**没有正文, 也没有可直连的文章地址** —— 搜狗结果里的跳转被反爬拦截。"
                           "每条给了「去搜狗搜索」按钮, 真人浏览器点通常能进原文。"),
        },
        "schema_version": 1,
        "count": len(existing),
        "byCategory": by_cat,
        "byAccount": by_acc,
        "items": existing,
    }
    os.makedirs(SEED, exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print()
    print("=" * 56)
    print("本次新增 : %d 条" % added)
    print("文章总计 : %d 条" % len(existing))
    print("失败查询 : %d / %d" % (blocked, len(QUERIES)))
    print("按类别   : %s" % dict(sorted(by_cat.items(), key=lambda kv: -kv[1])))
    print("公众号 Top:")
    for a, n in sorted(by_acc.items(), key=lambda kv: -kv[1])[:10]:
        print("    %-28s %d" % (a, n))
    print("written  : %s (%.0f KB)" % (DST, os.path.getsize(DST) / 1024.0))


if __name__ == "__main__":
    sys.exit(main())
