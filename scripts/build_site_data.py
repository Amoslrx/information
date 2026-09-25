# -*- coding: utf-8 -*-
"""把 seed 数据打包成前端可直接用的 site/data.js。

为什么要内联成 JS 而不是让前端 fetch JSON:
  1. fetch('data.json') 在 file:// 协议下会被 CORS 拦掉, 双击 index.html 打不开;
  2. 静态托管下也少一次请求。
代价是数据更新后要重跑本脚本 —— 这正是把"抓取"和"展示"分开的目的。

输出: site/data.js   (window.SITE_DATA = {...})
"""
import csv
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
SITE = os.path.join(ROOT, "site")
DST = os.path.join(SITE, "data.js")

UNKNOWN_CAT = "未认定(待核)"


def load_competitions():
    path = os.path.join(SEED, "competitions_master.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    out = []
    for r in rows:
        ee = r["电气相关度"].strip()
        moe_no = r["教育部目录序号"].strip()
        url = r["官网"].strip()
        out.append({
            "name": r["竞赛名称"].strip(),
            "ee": int(ee) if ee.isdigit() else None,
            "xjtuCat": r["西交类别"].strip() or UNKNOWN_CAT,
            "alias": r["西交名单用名"].strip(),
            "level": r["级别"].strip(),
            "dept": r["归口部门"].strip(),
            "inMoe": r["教育部目录"].strip() == "是",
            "moeNo": int(moe_no) if moe_no.isdigit() else None,
            "organizer": r["主办单位"].strip(),
            "url": url,
            "domain": url.split("//")[-1].split("/")[0] if url else "",
            "reason": r["相关理由"].strip(),
            "source": r["数据来源"].strip(),
        })
    return out


def load_deadlines():
    """报名截止时间(从通知正文提取, 见 scripts/extract_deadlines.py)。

    只取分数 >= min_score 的 —— 分数低说明上下文不足以确认那是"报名截止",
    宁可没有, 也不能给错的截止时间。
    """
    path = os.path.join(SEED, "deadlines.json")
    if not os.path.exists(path):
        return {}, 4
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    ms = d.get("min_score", 4)
    out = {}
    for r in d.get("items", []):
        if r.get("deadline") and r.get("score", 0) >= ms:
            out[r["url"]] = {"deadline": r["deadline"], "score": r["score"]}
    return out, ms


# 校内选拔/校赛 的判定词
CAMPUS_WORDS = ("校内选拔", "校赛", "校内赛", "校决赛", "校内决赛", "校内", "校初赛")


def load_notices(deadlines, min_score):
    path = os.path.join(SEED, "notices.json")
    if not os.path.exists(path):
        return [], {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    items = []
    for n in d["items"]:
        dl = deadlines.get(n["url"])
        items.append({
            "title": n["title"],
            "date": n["date"],
            "url": n["url"],
            "competition": n.get("competition") or "",
            "moeNo": int(n["moe_no"]) if str(n.get("moe_no") or "").isdigit() else None,
            "site": n.get("site") or "",
            "isCompetition": bool(n.get("is_competition", True)),
            "isCampus": any(w in n["title"] for w in CAMPUS_WORDS),
            "deadline": dl["deadline"] if dl else "",
            "deadlineScore": dl["score"] if dl else 0,
        })
    return items, d.get("source", {})


def load_quick_links():
    """常用网站导航(人工维护, 每条均实测过连通性)。"""
    path = os.path.join(ROOT, "data", "curated", "quick_links.json")
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("items", []), d.get("_category_order", [])


def load_cadence():
    """年度节律(由 scripts/build_cadence.py 推断)。不存在时返回空, 站点照常工作。"""
    path = os.path.join(SEED, "cadence.json")
    if not os.path.exists(path):
        return {}, {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    by_name = {r["competition"]: r for r in d["items"]}
    hist = {int(k): v for k, v in d.get("monthHistogram", {}).items()}
    return by_name, hist


def main():
    comps = load_competitions()
    deadlines, min_score = load_deadlines()
    notices, nsrc = load_notices(deadlines, min_score)
    cadence, month_hist = load_cadence()
    links, cat_order = load_quick_links()

    # 今天(用于判断"报名中")
    today = datetime.now().strftime("%Y-%m-%d")

    # 竞赛名 -> 通知列表
    by_name = {}
    for n in notices:
        if n["competition"]:
            by_name.setdefault(n["competition"], []).append(n)
    for c in comps:
        rel = by_name.get(c["name"], [])
        rel.sort(key=lambda x: x["date"], reverse=True)
        c["noticeCount"] = len(rel)
        c["latestNotice"] = rel[0] if rel else None
        c["campusNoticeCount"] = sum(1 for n in rel if n["isCampus"])
        # 报名中: 取该竞赛**所有**通知里最晚的一个未过期截止时间
        opens = [n for n in rel if n["deadline"] and n["deadline"] >= today]
        opens.sort(key=lambda x: x["deadline"])
        c["openDeadline"] = opens[0]["deadline"] if opens else ""
        c["openNoticeUrl"] = opens[0]["url"] if opens else ""
        c["isOpen"] = bool(opens)
        cad = cadence.get(c["name"])
        if cad:
            c["cadence"] = {
                "months": cad["months"],
                "stableMonths": cad["stableMonths"],
                "windowStart": cad["windowStart"],
                "windowEnd": cad["windowEnd"],
                "windowLabel": cad["windowLabel"],
                "yearsObserved": cad["yearsObserved"],
                "coverage": cad["coverage"],
                "confidence": cad["confidence"],
            }

    # 统计
    ee_dist = {}
    for c in comps:
        k = c["ee"] if c["ee"] is not None else 0
        ee_dist[k] = ee_dist.get(k, 0) + 1
    dates = [n["date"] for n in notices]
    site_counts = {}
    for n in notices:
        s = n.get("site") or "?"
        site_counts[s] = site_counts.get(s, 0) + 1
    stats = {
        "competitions": len(comps),
        "notices": len(notices),
        "noticesMatched": sum(1 for n in notices if n["competition"]),
        "noticesCompetition": sum(1 for n in notices if n.get("isCompetition")),
        "noticesCampus": sum(1 for n in notices if n.get("isCampus")),
        "noticesWithDeadline": sum(1 for n in notices if n.get("deadline")),
        "competitionsOpen": sum(1 for c in comps if c.get("isOpen")),
        "today": today,
        "noticeFrom": min(dates) if dates else "",
        "noticeTo": max(dates) if dates else "",
        "eeDist": ee_dist,
        "withUrl": sum(1 for c in comps if c["url"]),
        "xjtuKnown": sum(1 for c in comps if c["xjtuCat"] != UNKNOWN_CAT),
        "crawledPages": sum(int(s.get("pages_crawled_cap", 0))
                            for s in nsrc.get("sites", [])),
        "bySite": site_counts,
    }

    payload = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stats": stats,
        "competitions": comps,
        "notices": notices,
        "monthHistogram": {str(m): month_hist.get(m, 0) for m in range(1, 13)},
        "cadenceCount": len(cadence),
        "quickLinks": links,
        "quickLinkCategories": cat_order,
        "calendar": {
            "all": "calendar/all.ics",
            "eeCore": "calendar/ee-core.ics",
            "eeCoreMin": 4,
        },
        "sources": {
            "moe": "2025年教育部认可的全国大学生学科竞赛目录清单(84项)",
            "xjtuNotice": nsrc.get("title", ""),
            "xjtuNoticeUrl": (nsrc.get("sites") or [{}])[0].get("base", ""),
            "noticeSites": [{"key": s.get("key"), "label": s.get("label"),
                             "base": s.get("base")} for s in nsrc.get("sites", [])],
            "noticeSkipped": nsrc.get("skipped", {}),
        },
        "caveats": [
            "西交A/B名单为旧版不完整名单(2页/19项), 标「未认定(待核)」不代表学校未认定。",
            "电气相关度为 AI 初判, 需人工复核(改 data/curated/ee_relevance.json)。",
            "报名截止时间未结构化收录, 需人工维护; 通知标题与竞赛的关联为关键词自动匹配, 可能有误。",
            "年度节律是从历史通知统计推断的窗口, 不是官方赛程, 仅表示往年在这些月份发过通知。",
        ],
    }

    os.makedirs(SITE, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    with open(DST, "w", encoding="utf-8") as f:
        f.write("// 由 scripts/build_site_data.py 自动生成, 请勿手工编辑\n")
        f.write("// 生成时间: %s\n" % payload["generatedAt"])
        f.write("window.SITE_DATA = %s;\n" % body)

    print("竞赛 : %d (有官网 %d, 有西交类别 %d)" % (
        stats["competitions"], stats["withUrl"], stats["xjtuKnown"]))
    print("通知 : %d (已关联 %d, %s ~ %s)" % (
        stats["notices"], stats["noticesMatched"], stats["noticeFrom"], stats["noticeTo"]))
    print("节律 : %d 个竞赛可推断年度窗口" % len(cadence))
    print("常用网站: %d 个链接, %d 个分类" % (len(links), len(cat_order)))
    print("相关度分布: %s" % dict(sorted(ee_dist.items())))
    print("written: %s (%.0f KB)" % (DST, os.path.getsize(DST) / 1024.0))


if __name__ == "__main__":
    main()
