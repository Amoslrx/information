# -*- coding: utf-8 -*-
"""从历史校内通知推断每个竞赛的「年度节律」——通常几月发通知。

为什么这么做: 学生真正缺的不是"有哪些竞赛", 而是"现在该关注什么"。
历史通知本身就隐含了节律。本脚本只用已有的 notices.json, 不新增抓取。

方法:
  1. 把每条通知按其关联竞赛 + 发布月份归集;
  2. 对每个竞赛, 找出能覆盖 >=60% 历史通知的**最短连续月份窗口**(月份环形, 可跨年);
  3. 同时统计"稳定月份"(在 >=2 个不同年份都出现过的月份);
  4. 按观测到的年数给置信度。

严谨性:
  - 这是**统计推断**, 不是官方赛程。窗口只说明"往年大概几月发通知"。
  - 年数 < 2 的竞赛不输出节律(样本不足, 宁缺勿错)。
  - 输出里保留 evidence(依据的通知日期), 便于人工核对与推翻。

输入: data/seed/notices.json, data/seed/competitions_master.csv
输出: data/seed/cadence.json
"""
import csv
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")

MIN_YEARS = 2          # 至少跨 2 个年度才给节律
COVERAGE = 0.60        # 窗口需覆盖至少 60% 的历史通知
MAX_WINDOW = 6         # 窗口最宽 6 个月, 再宽就没有指导意义了

MONTH_NAMES = ["一", "二", "三", "四", "五", "六",
               "七", "八", "九", "十", "十一", "十二"]


def month_label(m):
    return MONTH_NAMES[m - 1] + "月"


def load():
    with open(os.path.join(SEED, "notices.json"), encoding="utf-8") as f:
        notices = json.load(f)["items"]
    comps = {}
    with open(os.path.join(SEED, "competitions_master.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            comps[r["竞赛名称"].strip()] = r
    return notices, comps


def best_window(counts):
    """环形月份上, 覆盖率 >= COVERAGE 的最短连续窗口。返回 (start, end, coverage)。"""
    total = sum(counts.values())
    if total == 0:
        return None
    best = None
    for length in range(1, MAX_WINDOW + 1):
        for start in range(1, 13):
            months = [((start - 1 + i) % 12) + 1 for i in range(length)]
            cov = sum(counts.get(m, 0) for m in months) / float(total)
            if cov >= COVERAGE:
                end = months[-1]
                cand = (cov, -length, start, end)
                if best is None or cand > best:
                    best = cand
        if best is not None:
            break          # 已找到最短可行窗口, 不再加宽
    if best is None:
        return None
    cov, neg_len, start, end = best
    return start, end, cov


def build():
    notices, comps = load()

    # 竞赛 -> [(年, 月, 日期, 标题)]
    agg = defaultdict(list)
    for n in notices:
        c = n.get("competition")
        if not c:
            continue
        agg[c].append((int(n["date"][:4]), int(n["date"][5:7]), n["date"], n["title"]))

    out = []
    for name, recs in agg.items():
        years = sorted({y for y, _, _, _ in recs})
        if len(years) < MIN_YEARS:
            continue

        counts = defaultdict(int)
        for _, m, _, _ in recs:
            counts[m] += 1
        win = best_window(counts)
        if not win:
            continue
        start, end, cov = win

        # 稳定月份: 在 >=2 个不同年份都出现过的月份
        month_years = defaultdict(set)
        for y, m, _, _ in recs:
            month_years[m].add(y)
        stable = sorted(m for m, ys in month_years.items() if len(ys) >= 2)

        # 置信度: 看观测年数
        ny = len(years)
        conf = "high" if ny >= 4 else ("medium" if ny >= 3 else "low")

        row = comps.get(name, {})
        out.append({
            "competition": name,
            "ee": int(row["电气相关度"]) if str(row.get("电气相关度", "")).isdigit() else None,
            "xjtuCat": row.get("西交类别", ""),
            "url": row.get("官网", ""),
            "dept": row.get("归口部门", ""),
            "yearsObserved": ny,
            "years": years,
            "noticeCount": len(recs),
            "months": {str(m): counts[m] for m in sorted(counts)},
            "stableMonths": stable,
            "windowStart": start,
            "windowEnd": end,
            "windowLabel": (month_label(start) if start == end
                            else "%s–%s" % (month_label(start), month_label(end))),
            "coverage": round(cov, 3),
            "confidence": conf,
            "evidence": sorted({d for _, _, d, _ in recs}, reverse=True)[:8],
        })

    out.sort(key=lambda r: (-(r["ee"] or 0), -r["yearsObserved"], r["competition"]))

    # 全校节奏
    allm = defaultdict(int)
    for n in notices:
        allm[int(n["date"][5:7])] += 1

    return out, allm


def main():
    cadence, allm = build()
    payload = {
        "source": {
            "method": "从历史校内通知推断, 统计口径见 scripts/build_cadence.py",
            "input": "data/seed/notices.json",
            "caveat": "这是统计推断, 不是官方赛程。仅表示往年在这些月份发过通知。",
            "min_years": MIN_YEARS,
            "coverage_threshold": COVERAGE,
        },
        "schema_version": 1,
        "count": len(cadence),
        "monthHistogram": {str(m): allm.get(m, 0) for m in range(1, 13)},
        "items": cadence,
    }
    dst = os.path.join(SEED, "cadence.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("可推断节律的竞赛: %d 个" % len(cadence))
    print("全校通知月份分布: %s" % {m: allm.get(m, 0) for m in range(1, 13)})
    print()
    print("%-36s %-3s %-4s %-14s %s" % ("竞赛", "年数", "相关", "往年窗口", "覆盖"))
    print("-" * 82)
    for r in cadence[:18]:
        print("%-36s %-4d %-4s %-14s %.0f%%" % (
            r["competition"][:34], r["yearsObserved"], r["ee"],
            r["windowLabel"], r["coverage"] * 100))
    print()
    print("written:", dst)


if __name__ == "__main__":
    main()
