# -*- coding: utf-8 -*-
"""把「教育部 2025 认可竞赛目录」与「西交 A/B 类名单」合并成一张总表。

输入:
  data/seed/moj_2025_catalog.json   84 项教育部目录(含官网)
  data/seed/xjtu_ab_list.json       西交 A/B 名单 19 项(旧版, 不完整)
  data/curated/ee_relevance.json    电气相关度人工研判 + 两表对应关系

输出:
  data/seed/competitions_master.csv    CSV(UTF-8 BOM, 可直接导入飞书/Notion/Excel)
  data/seed/competitions_master.md     便于阅读的 Markdown 版

设计原则:
- 缺失字段留空, 不猜测。
- 西交类别只对西交名单里明确出现的赛事填写; 其余写 "未认定(待核)"。
- 保留 provenance 列, 每条能追溯来源。
"""
import csv
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
CURATED = os.path.join(ROOT, "data", "curated", "ee_relevance.json")

HEADERS = ["竞赛名称", "电气相关度", "西交类别", "西交名单用名", "级别", "归口部门",
           "教育部目录", "教育部目录序号", "主办单位", "官网",
           "相关理由", "专项负责人", "数据来源", "最后核对"]

UNKNOWN_CAT = "未认定(待核)"
SOURCE_MOE = "教育部2025目录"
SOURCE_XJTU = "西交A/B名单(旧版)"
SOURCE_BOTH = "教育部2025目录+西交A/B名单(旧版)"
SOURCE_C = "电气学院C类列表"
TODAY = "2026-09-23"


def norm_name(s):
    """竞赛名归一化, 用于把 C 类列表和目录里的同名赛事对上。"""
    s = re.sub(r"[（）()【】\[\]“”\"'\s·、,，。\-—–_/\\]", "", s or "")
    return s.lower()


def load():
    with open(os.path.join(SEED, "moj_2025_catalog.json"), encoding="utf-8") as f:
        moe = json.load(f)
    with open(os.path.join(SEED, "xjtu_ab_list.json"), encoding="utf-8") as f:
        xjtu = json.load(f)
    with open(CURATED, encoding="utf-8") as f:
        cur = json.load(f)
    ccls_path = os.path.join(ROOT, "data", "curated", "xjtu_ee_c_class.json")
    ccls = json.load(open(ccls_path, encoding="utf-8")) if os.path.exists(ccls_path) else {"items": []}
    return moe, xjtu, cur, ccls


def build():
    moe, xjtu, cur, ccls = load()
    relevance = {int(k): v for k, v in cur["moe_relevance"].items()}
    x2m = {k: v for k, v in cur["xjtu_to_moe"].items() if not k.startswith("_")}
    xjtu_only = {r["key"]: r for r in cur["xjtu_only"]}

    # 反查: 教育部序号 -> 西交条目
    moe_to_xjtu = defaultdict(list)
    for xkey, mno in x2m.items():
        if mno is not None:
            moe_to_xjtu[mno].append(xkey)
    xjtu_by_key = {}
    for it in xjtu["items"]:
        xjtu_by_key["%s|%s" % (it["section"], it["no"])] = it

    rows = []
    used_xjtu = set()

    # ---- 1) 教育部 84 项 ----
    for it in moe["items"]:
        no = it["no"]
        rel = relevance.get(no, {"score": "", "reason": ""})
        keys = moe_to_xjtu.get(no, [])
        xn = xjtu_by_key.get(keys[0]) if keys else None
        if xn:
            used_xjtu.add(keys[0])
        # 名称以教育部目录的**现行名称**为准(如"互联网+"已更名为"中国国际大学生创新大赛"),
        # 西交旧名单里的叫法单独保留一列, 便于对照。
        moe_name = it["name"]
        xjtu_name = xn["name"] if xn else ""
        alias = xjtu_name if (xjtu_name and xjtu_name != moe_name) else ""
        rows.append({
            "竞赛名称": moe_name,
            "电气相关度": rel["score"],
            "西交类别": xn["xjtu_category"] if xn else UNKNOWN_CAT,
            "西交名单用名": alias,
            "级别": xn["level"] if xn else "",
            "归口部门": xn["owner_dept"] if xn else "",
            "教育部目录": "是",
            "教育部目录序号": no,
            "主办单位": xn["organizer"] if xn else "",
            "官网": it.get("url") or "",
            "相关理由": rel["reason"],
            "数据来源": SOURCE_BOTH if xn else SOURCE_MOE,
            "最后核对": TODAY,
        })

    # ---- 2) 只在西交名单里、教育部 84 项没有的赛事 ----
    for key, it in xjtu_by_key.items():
        if key in used_xjtu:
            continue
        info = xjtu_only.get(key, {})
        rows.append({
            "竞赛名称": it["name"],
            "电气相关度": info.get("score", ""),
            "西交类别": it["xjtu_category"],
            "西交名单用名": "",
            "级别": it["level"],
            "归口部门": it["owner_dept"],
            "教育部目录": "否",
            "教育部目录序号": "",
            "主办单位": it["organizer"],
            "官网": "",
            "相关理由": info.get("reason", ""),
            "数据来源": SOURCE_XJTU,
            "最后核对": TODAY,
        })

    # ---- 3) 电气学院 C 类列表 ----
    # 这是**学院级**认定(电气工程学院学生竞赛管理委员会), 与学校级 A/B 不同层级。
    # 能对上目录里已有赛事的就补一个 C 类标注; 对不上的新增条目。
    c_rows = []
    for c in ccls.get("items", []):
        nm = norm_name(c["name"])
        target = None
        # 3a) 显式指定优先(原文名称与目录不一致时, 由 curated 文件写明)
        want_no = c.get("_match_moe")
        if want_no:
            for r in rows:
                if r["教育部目录序号"] == want_no:
                    target = r
                    break
        # 3b) 否则按名称匹配: 相等, 或一方包含另一方(短的 >= 6 字)
        if target is None:
            for r in rows:
                rn = norm_name(r["竞赛名称"])
                if rn == nm or (len(nm) >= 6 and len(rn) >= 6 and
                                (nm in rn or rn in nm)):
                    target = r
                    break
        if target is not None:
            target["专项负责人"] = c.get("contact", "")
            # 不覆盖学校级 A/B 认定, 只补空的
            if target["西交类别"] == UNKNOWN_CAT:
                target["西交类别"] = ccls["category"]
            if SOURCE_C not in target["数据来源"]:
                target["数据来源"] += "+" + SOURCE_C
            if c.get("_name_note"):
                target["相关理由"] = (target["相关理由"] + "；" +
                                  c["_name_note"]).strip("；")
        else:
            c_rows.append({
                "竞赛名称": c["name"],
                "电气相关度": "",
                "西交类别": ccls["category"],
                "西交名单用名": "",
                "级别": "",
                "归口部门": "电气学院",
                "教育部目录": "否",
                "教育部目录序号": "",
                "主办单位": "",
                "官网": "",
                "相关理由": c.get("_name_note", "") or "电气工程学院认定的 C 类竞赛。",
                "专项负责人": c.get("contact", ""),
                "数据来源": SOURCE_C,
                "最后核对": TODAY,
            })
    rows.extend(c_rows)

    # ---- 4) 排序: 电气相关度降序, 其次教育部序号 ----
    def sort_key(r):
        s = r["电气相关度"]
        s = s if isinstance(s, int) else -1
        mno = r["教育部目录序号"]
        return (-s, mno if isinstance(mno, int) else 999, r["竞赛名称"])

    rows.sort(key=sort_key)
    return rows, len(c_rows)


def write_csv(rows):
    dst = os.path.join(SEED, "competitions_master.csv")
    # utf-8-sig: Excel 直接打开不乱码; 飞书/Notion 导入也识别 BOM
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(rows)
    return dst


def write_md(rows):
    dst = os.path.join(SEED, "competitions_master.md")
    lines = [
        "# 竞赛总表(电气工程及其自动化视角)",
        "",
        "> 由 `scripts/build_master_table.py` 生成, 请勿手工编辑(改 `data/curated/ee_relevance.json`)。",
        "> **电气相关度为 AI 初判, 需人工复核。**",
        "> **西交类别来自旧版不完整名单(2页/19项), 标 `未认定(待核)` 的不代表学校未认定。**",
        "",
        "| " + " | ".join(HEADERS) + " |",
        "|" + "---|" * len(HEADERS),
    ]
    for r in rows:
        cells = []
        for h in HEADERS:
            v = str(r.get(h, "") or "").replace("|", "\\|")
            cells.append(v)
        lines.append("| " + " | ".join(cells) + " |")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return dst


def main():
    rows, c_new = build()
    c = write_csv(rows)
    m = write_md(rows)

    print("总行数: %d" % len(rows))
    print("  C类列表新增   : %d" % c_new)
    for cat in ("A类", "B类", "C类"):
        print("  西交%s        : %d" % (cat, sum(1 for r in rows if r["西交类别"] == cat)))
    print("  教育部目录条目 : %d" % sum(1 for r in rows if r["教育部目录"] == "是"))
    print("  西交独有条目   : %d" % sum(1 for r in rows if r["教育部目录"] == "否"))
    print("  有西交类别     : %d" % sum(1 for r in rows if r["西交类别"] != UNKNOWN_CAT))
    print("  有官网 URL     : %d" % sum(1 for r in rows if r["官网"]))
    print("  电气相关度>=4  : %d" % sum(1 for r in rows
                                    if isinstance(r["电气相关度"], int) and r["电气相关度"] >= 4))
    dist = defaultdict(int)
    for r in rows:
        dist[r["电气相关度"]] += 1
    print("  相关度分布     : %s" % dict(sorted(dist.items(), key=lambda kv: str(kv[0]))))
    print()
    print("CSV:", c)
    print("MD :", m)
    print()
    print("=== 电气相关度 5 的赛事(建议优先录入) ===")
    for r in rows:
        if r["电气相关度"] == 5:
            print("  [%s] %-34s | %s | %s" % (
                r["西交类别"], r["竞赛名称"], r["官网"][:44], r["相关理由"][:22]))


if __name__ == "__main__":
    main()
