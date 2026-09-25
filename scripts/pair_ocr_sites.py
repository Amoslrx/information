# -*- coding: utf-8 -*-
"""把 OCR 文本里的「网站名称」与已实测连通的子域名配对。

OCR 文本的卡片结构(实测):
    迎新系统            <- 名称
    hello               <- 子域名字段
    所属分类放在前面      <- 分类标记
    统一认证             <- 标签
    <说明...>
    点击跳转 / 复制网址

所以以 "所属分类" 为锚点向上找子域名, 再向上找名称, 就能配对。

输入: _ocr/cleaned.txt, _ocr/sites.json(已实测)
输出: _ocr/pairs.json
"""
import json
import os
import re

ROOT = r"F:\竞赛信息"
LINES = os.path.join(ROOT, "_ocr", "cleaned.txt")
SITES = os.path.join(ROOT, "_ocr", "sites.json")
DST = os.path.join(ROOT, "_ocr", "pairs.json")

# 分类标记: "所属分类放在前面" / "所属分类放在前面统一认证"(OCR 常把两行并一行)
CAT_RE = re.compile(r"^所属分类\s*(.*)$")
# 名称特征: 含中文且长度合理
NAME_RE = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9·\-（）()]{1,17}$")
# 明显不是名称/子域名的行
JUNK_RE = re.compile(r"(点击|复制|跳转|网址|说明$|手册$|登录$)")


def main():
    good = {v["sub"]: v for v in json.load(open(SITES, encoding="utf-8"))["good"]}
    lines = [l.strip() for l in open(LINES, encoding="utf-8").read().splitlines()]

    pairs, used = [], set()
    for i, l in enumerate(lines):
        m = CAT_RE.match(l)
        if not m:
            continue
        cat = m.group(1).strip()
        if not cat:                                  # 分类在下一行
            cat = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # 向上 6 行内找子域名与名称
        sub = name = None
        for j in range(i - 1, max(-1, i - 7), -1):
            t = lines[j].strip()
            if sub is None and t in good:
                sub = t
                continue
            if sub is not None and name is None and NAME_RE.match(t) and not JUNK_RE.search(t):
                name = t
                break
        if sub and name and sub not in used:
            used.add(sub)
            pairs.append({"name": name, "sub": sub, "url": good[sub]["url"],
                          "status": good[sub]["status"], "category": cat})

    # 没配上的连通站点单独列出
    unmatched = [s for s in good if s not in used]

    json.dump({"pairs": pairs, "unmatched_subdomains": unmatched},
              open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("配对成功: %d 组" % len(pairs))
    print()
    for p in pairs:
        print("  %-18s %-28s [%s] %s" % (p["name"], p["sub"] + ".xjtu.edu.cn",
                                         p["status"], p["category"][:16]))
    print()
    print("已连通但没配上名称的子域名 (%d 个): %s" % (len(unmatched), ", ".join(unmatched)))
    print()
    print("written:", DST)


if __name__ == "__main__":
    main()
