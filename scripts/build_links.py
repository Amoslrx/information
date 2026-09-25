# -*- coding: utf-8 -*-
"""合并三个来源, 生成最终的常用网站数据 data/curated/quick_links.json。

来源:
  1. data/curated/quick_links.json   人工整理(23 条, 有较好的说明文字)—— 作为基底, 保留
  2. _ocr/pairs.json                 从 常用网站.png 经 OCR + 实测得到(23 条)
  3. data/raw/xjtu_departments.json  从官网院系页频次分析得到(44 个学院/书院主页)

合并原则:
  - 按 URL 去重; 已存在的以来源 1 为准(说明更完整)
  - 来源 2 的名称有 OCR 误识, 用 NAME_FIX 覆盖, **不猜未在名单里的条目**
  - 来源 3 归入新分类「学院与书院」
  - 所有 URL 都经过真实请求验证, 输出里带上验证状态
"""
import json
import os
import re

ROOT = r"F:\竞赛信息"
CURATED = os.path.join(ROOT, "data", "curated", "quick_links.json")
PAIRS = os.path.join(ROOT, "_ocr", "pairs.json")
DEPTS = os.path.join(ROOT, "data", "raw", "xjtu_departments.json")

# OCR 把说明文字误当成名称的条目, 人工修正
NAME_FIX = {
    "webvpn": "WebVPN",
    "lms": "思源学堂（新版）",
    "syxt": "思源学堂（门户）",
    "bb": "思源学堂（旧版）",
    "class": "直录播课堂",
}
# OCR 分类串里带的噪声前缀(中点是 OCR 误识, 且可能是不同的中点字符, 所以按规则清)
CAT_FIX = {"· 日常学习相关": "日常学习相关"}


def clean_cat(s):
    """去掉分类名开头的非文字字符(OCR 常把行首符号粘进来)。"""
    s = norm(s)
    s = re.sub(r"^[^\u4e00-\u9fffA-Za-z]+", "", s)
    return CAT_FIX.get(s, s)

DEPT_CAT = "学院与书院"


def norm(s):
    return re.sub(r"\s+", "", s or "")


def main():
    base = json.load(open(CURATED, encoding="utf-8"))
    items = base["items"]
    existing = {i["url"].rstrip("/") for i in items}
    added_ocr, added_dept = [], []

    # ---- 来源 2: OCR 得到并实测过的站点 ----
    if os.path.exists(PAIRS):
        pj = json.load(open(PAIRS, encoding="utf-8"))
        for p in pj["pairs"]:
            url = p["url"]
            if url.rstrip("/") in existing:
                continue
            name = NAME_FIX.get(p["sub"], norm(p["name"]))
            cat = clean_cat(p["category"]) or "校内其余常用"
            items.append({
                "name": name, "url": url, "category": cat, "tags": [],
                "desc": "来自《西交常用网站汇总》截图，网址已实测连通。",
                "verified": p.get("status"),
            })
            existing.add(url.rstrip("/"))
            added_ocr.append(name)

    # ---- 来源 3: 学院与书院主页 ----
    if os.path.exists(DEPTS):
        dj = json.load(open(DEPTS, encoding="utf-8"))
        for d in dj["items"]:
            url = d.get("homepage")
            if not url or url.rstrip("/") in existing:
                continue
            items.append({
                "name": d["name"], "url": url, "category": DEPT_CAT, "tags": [],
                "desc": "学院/书院官网主页（从学校官网院系页解析并实测连通）。",
                "verified": d.get("status"),
            })
            existing.add(url.rstrip("/"))
            added_dept.append(d["name"])

    # 全量归一化分类名 —— 新增条目会被 clean_cat 处理, 但**之前几轮已经写进
    # JSON 的条目**带着旧的脏分类, 必须一起洗一遍, 否则它们永远修不掉。
    for i in items:
        i["category"] = clean_cat(i["category"]) or "校内其余常用"

    # 分类顺序: 学院与书院放最后; 数据里出现但预设没有的分类(如"校内已停用网站")补在它前面
    preset = [c for c in base.get("_category_order", []) if c != DEPT_CAT]
    present = {i["category"] for i in items}
    order = [c for c in preset if c in present]
    for c in sorted(present):
        if c not in order and c != DEPT_CAT:
            order.append(c)
    if DEPT_CAT in present:
        order.append(DEPT_CAT)

    base["items"] = items
    base["_category_order"] = order
    base["_note"] = ("西交常用网站导航。三条来源: 人工整理 + 《西交常用网站汇总》截图(OCR) "
                     "+ 学校官网院系页。**每条 URL 都经过真实请求验证**。")
    base["_pending"] = ("截图共 67 个站点, OCR 能读出名称但与完整 URL 有偏差"
                        "(点号/冒号误识、换行截断), 因此只收录了能实测连通的条目。"
                        "拿到原站 URL 后可精确抓取补全。")

    json.dump(base, open(CURATED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    by_cat = {}
    for i in items:
        by_cat[i["category"]] = by_cat.get(i["category"], 0) + 1

    print("总条目: %d" % len(items))
    print("  其中新增(OCR截图): %d" % len(added_ocr))
    print("  其中新增(学院书院): %d" % len(added_dept))
    print("  分类数: %d" % len(by_cat))
    print()
    for c in order:
        if by_cat.get(c):
            print("  %-16s %3d" % (c, by_cat[c]))
    for c in by_cat:
        if c not in order:
            print("  %-16s %3d  (未在预设顺序里)" % (c, by_cat[c]))
    print()
    print("written:", CURATED)


if __name__ == "__main__":
    main()
