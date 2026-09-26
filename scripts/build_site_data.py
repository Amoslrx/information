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

# "校内选拔中" 的判定窗口(天): 这个天数内有校内选拔/校赛类通知, 且其截止时间
# 未过(或没提取到截止时间), 就认为该竞赛当前可以报名。
# 国家赛官网还没开放报名时, 校内选拔往往已经在跑了。
SELECT_WINDOW = 120

# ---------------------------------------------------------------- 通知归类
# 站点顶层按 5 大类组织, 依据是《西安交通大学本科生综合素质测评内容及评分标准》
# (xsc.xjtu.edu.cn/info/1038/13333.htm) 里的评分维度。
#
# **列表顺序即优先级**: 一条通知可能命中多个关键词, 取最靠前的类别。
# 例如「关于全国大学英语四、六级考试报名的通知」同时含"考试"(教学信息),
# 但等级考试更具体, 所以排在前面。
NOTICE_CATEGORIES = [
    ("等级考试", "学科竞赛", [
        "四六级", "四、六级", "四级", "六级", "CET", "计算机等级", "计算机二级",
        "等级考试", "普通话水平", "雅思", "托福", "专业八级", "外语水平考试",
    ]),
    ("思政学习", "思政学习", [
        "思政", "理论学习", "党课", "团课", "星航", "正心", "青马", "主题教育",
        "党校", "团校", "组织生活会", "主题党日", "最佳团日", "四史", "红色教育",
        "理论宣讲", "青年大学习", "党团", "党建", "团建", "团支部", "党支部",
        "党日", "团日", "党史",
    ]),
    ("学科竞赛", "学科竞赛", [
        "竞赛", "大赛", "挑战杯", "创新创业", "创新大赛", "擂台", "作品赛",
        "程序设计", "数学建模", "电子设计", "机器人大赛", "智能汽车", "节能减排",
        "大创", "国创",
    ]),
    ("文体竞赛", "文体竞赛", [
        "运动会", "田径", "篮球", "足球", "排球", "羽毛球", "乒乓球", "网球",
        "游泳", "体育竞赛", "健身", "文艺", "歌手", "舞蹈", "合唱", "乐团",
        "艺术团", "书法", "绘画", "摄影", "演讲", "辩论", "主持", "话剧",
        "戏曲", "晚会", "文化节", "飞盘", "体育",
    ]),
    ("社会实践", "社会实践", [
        "社会实践", "志愿服务", "志愿者", "支教", "三下乡", "西部计划", "挂职",
        "见习", "公益", "义工", "勤工助学", "研学",
        # 团委的叙事性新闻标题常写「青春志愿行」「实践周报」「社会实践归来」,
        # 不含完整词, 所以补上更短的词根。学科竞赛优先级更高, 不会被误吞。
        "实践", "志愿", "服务队", "返乡", "基层",
    ]),
    ("教学信息", "教学信息", [
        "选课", "评教", "教学评价", "考试", "补考", "缓考", "重修", "学籍",
        "成绩单", "辅修", "转专业", "培养方案", "学位", "毕业", "课表",
        "停开课", "调课", "教学", "课程", "放假", "注册", "学分", "劳动教育",
        "校历", "答辩", "教材", "试卷", "考勤", "上课", "教室", "开课", "分流",
    ]),
]


def classify_notice(title):
    """按标题关键词归类。返回 (类别, 大类)。

    刻意不用来源判断 —— 同一个来源(如教务处教学通知)会同时发各类内容,
    按来源归会错得离谱。
    """
    t = title or ""
    for name, group, kws in NOTICE_CATEGORIES:
        if any(k in t for k in kws):
            return name, group
    return "其他", "其他"


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
            "contact": (r.get("专项负责人") or "").strip(),
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
        cat, group = classify_notice(n["title"])
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
            "cat": cat,
            "group": group,
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

    import datetime as _dt

    def days_ago(d):
        try:
            a = _dt.date(*[int(x) for x in d.split("-")])
            b = _dt.date(*[int(x) for x in today.split("-")])
            return (b - a).days
        except Exception:
            return 99999

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

        # 校内选拔中: 近 SELECT_WINDOW 天内有"校内选拔/校赛"类通知, 且该通知的
        # 截止时间还没过(或没提取到截止时间)。国家赛官网还没开放报名时,
        # 校内选拔往往已经在跑了, 所以这一路也要算作"可以报名"。
        cands = [n for n in rel
                 if n["isCampus"]
                 and days_ago(n["date"]) <= SELECT_WINDOW
                 and (not n["deadline"] or n["deadline"] >= today)]
        c["isSelecting"] = bool(cands)
        c["selectNotice"] = cands[0] if cands else None
        # 站点上"可报名"= 有未过期截止时间, 或正在校内选拔
        c["isRecruiting"] = c["isOpen"] or c["isSelecting"]

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
    cat_dist = {}
    for c in comps:
        cat_dist[c["xjtuCat"]] = cat_dist.get(c["xjtuCat"], 0) + 1
    notice_cat = {}
    notice_group = {}
    for n in notices:
        notice_cat[n["cat"]] = notice_cat.get(n["cat"], 0) + 1
        notice_group[n["group"]] = notice_group.get(n["group"], 0) + 1
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
        "competitionsSelecting": sum(1 for c in comps if c.get("isSelecting")),
        "competitionsRecruiting": sum(1 for c in comps if c.get("isRecruiting")),
        "today": today,
        "noticeFrom": min(dates) if dates else "",
        "noticeTo": max(dates) if dates else "",
        "eeDist": ee_dist,
        "catDist": cat_dist,
        "noticeCat": notice_cat,
        "noticeGroup": notice_group,
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
            "信息按 5 大类组织（学科竞赛 / 文体竞赛 / 社会实践 / 思政学习 / 教学信息），"
            "口径参照《西安交通大学本科生综合素质测评内容及评分标准》"
            "（xsc.xjtu.edu.cn/info/1038/13333.htm）的评分维度。",
            "**分类是按标题关键词自动打的**，一条通知只归一类（取最具体的那类）。"
            "标题写得诗的（尤其团委的叙事性新闻）会落到「其他」，共 640 条。",
            "西交类别分三档: A类/B类 来自学校《学生学科/科技竞赛A类、B类项目列表》(旧版, 仅 2 页 19 项), "
            "C类 来自《电气工程学院C类竞赛列表》(2026-03-25)。标「未认定(待核)」的不代表学校未认定, "
            "只代表这两份名单里没有。",
            "C 类认定会随学校文件、学科竞赛排行榜及竞赛影响力动态调整, 以学院最新通知为准。",
            "电气相关度为 AI 初判, 需人工复核(改 data/curated/ee_relevance.json)。",
            "报名截止时间从通知正文按上下文打分提取, 只保留高置信度的; 标「校内选拔中」的依据是"
            "近 120 天内的校内选拔类通知, 不等于国家赛官网已开放报名。",
            "通知标题与竞赛的关联为关键词自动匹配, 可能有误。",
            "年度节律是从历史通知统计推断的窗口, 不是官方赛程。",
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
