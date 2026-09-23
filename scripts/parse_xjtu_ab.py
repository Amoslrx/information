# -*- coding: utf-8 -*-
"""把西交《学生学科/科技竞赛 A 类、B 类项目列表》PDF 解析为结构化 JSON。

为什么用坐标法: 这份 PDF 的表格单元格是多行且垂直居中的, 纯文本抽取会把
"赛事名称"和"主办单位"的折行交错在一起(见 data/raw/xjtu_ab_layout.txt)。
pypdf 的 visitor_text 回调能给出每个文本片段的 (x, y), 据此按列切分、按行
分带, 才能可靠还原表格。

输入: data/raw/xjtu_ab_competitions.pdf
输出: data/seed/xjtu_ab_list.json

注意: 这是 2 页 / 19 项, 经核对是**不完整的旧版**名单(详见 调研结论与方案.md)。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tools"))
from pypdf import PdfReader  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "raw", "xjtu_ab_competitions.pdf")
DST = os.path.join(ROOT, "data", "seed", "xjtu_ab_list.json")

SOURCE_URL = ("http://pec.xjtu.edu.cn/system/_content/download.jsp"
              "?urltype=news.DownloadAttachUrl&owner=1723267192&wbfileid=5156266")

# 列边界(x 坐标), 由表头与正文实测得出
COL_NO_MAX = 120      # 编号 + 支持类别
COL_NAME_MAX = 300    # 赛事名称
COL_LEVEL_MAX = 355   # 级别
COL_ORG_MAX = 470     # 主办单位
# x >= COL_ORG_MAX      -> 归口部门

SECTION_RE = re.compile(r"^[一二]、(.+)$")


def collect_fragments(path):
    """返回 {page_index: [(y, x, text), ...]}"""
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        frags = []

        def visitor(text, cm, tm, font_dict, font_size):
            t = text.strip()
            if t:
                frags.append((round(tm[5], 1), round(tm[4], 1), t))

        page.extract_text(visitor_text=visitor)
        pages.append(frags)
    return pages


def group_lines(frags, tol=2.0):
    """同一 y(容差 tol) 的片段合成一行, 行内按 x 升序。返回按 y 降序的行列表。"""
    lines = []
    for y, x, t in sorted(frags, key=lambda f: (-f[0], f[1])):
        if lines and abs(lines[-1]["y"] - y) <= tol:
            lines[-1]["frags"].append((x, t))
        else:
            lines.append({"y": y, "frags": [(x, t)]})
    for ln in lines:
        ln["frags"].sort()
        ln["text"] = "".join(t for _, t in ln["frags"])
        ln["cells"] = {
            "no_cat": [(x, t) for x, t in ln["frags"] if x < COL_NO_MAX],
            "name": [(x, t) for x, t in ln["frags"] if COL_NO_MAX <= x < COL_NAME_MAX],
            "level": [(x, t) for x, t in ln["frags"] if COL_NAME_MAX <= x < COL_LEVEL_MAX],
            "org": [(x, t) for x, t in ln["frags"] if COL_LEVEL_MAX <= x < COL_ORG_MAX],
            "owner": [(x, t) for x, t in ln["frags"] if x >= COL_ORG_MAX],
        }
    return lines


def column_lines(lines, lo, hi):
    """取出每行在 x ∈ [lo, hi) 区间内的片段, 组成一个"列"。"""
    out = []
    for ln in lines:
        cell = [(x, t) for x, t in ln["frags"] if lo <= x < hi]
        if cell:
            out.append({"y": ln["y"], "frags": cell})
    return out


HEADER_EXACT = {"编号", "编", "号", "类别", "支持", "支持类别", "号类别", "编号支持类别"}
# 页脚形如 "- 1 -" / "- 2 -"; 抽取后会散成 org="-" owner="1-" 等片段
FOOTER_RE = re.compile(r"^[-\s]*\d+[-\s]*$")


def is_header(ln):
    """标题行 / 表头行 / 页脚 —— 它们会被拼进单元格, 必须排除。"""
    t = ln["text"]
    if any(tok in t for tok in ("项目列表", "赛事名称", "归口部门", "主办单位", "支持类别")):
        return True
    if SECTION_RE.match(t):
        return True
    compact = t.replace(" ", "").replace("\u3000", "")
    if compact in HEADER_EXACT:
        return True
    return bool(FOOTER_RE.match(compact))


def column_cells(frags, row_centers):
    """把一个列内的文本片段按 y 分组成单元格文本, 共 len(row_centers) 组。

    依据: 表格单元格在行内是**垂直居中**的, 所以"单元格组的 y 中心"应当贴近
    "该行中心的 y"。问题化为: 把按 y 降序排列的 m 个片段切成 k 段连续组,
    使 Σ|组中心 - 行中心| 最小 —— 经典 DP。

    这比"相邻行中心取中点分带"可靠: 后者对跨 5 行的长单元格(如第 8 行的
    主办单位)会把它的上半部分判给上一行。
    """
    m, k = len(frags), len(row_centers)
    if k == 0:
        return []
    if m == 0:
        return ["" for _ in range(k)]
    if m < k:
        # 片段数少于行数: 逐一对齐, 余下留空
        return ["".join(t for _, t in sorted(f["frags"])) for f in frags] + \
               ["" for _ in range(k - m)]

    INF = float("inf")
    prefix = [0.0]
    for f in frags:
        prefix.append(prefix[-1] + f["y"])
    dp = [[INF] * (k + 1) for _ in range(m + 1)]
    back = [[-1] * (k + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for r in range(1, k + 1):
        cy = row_centers[r - 1]
        for i in range(r, m + 1):          # 第 r 组至少占 1 个片段
            best, best_j = INF, -1
            for j in range(r - 1, i):      # 前 r-1 组各至少 1 个
                if dp[j][r - 1] == INF:
                    continue
                mean_y = (prefix[i] - prefix[j]) / (i - j)
                cost = dp[j][r - 1] + abs(mean_y - cy)
                if cost < best:
                    best, best_j = cost, j
            dp[i][r], back[i][r] = best, best_j

    groups, i = [], m
    for r in range(k, 0, -1):
        j = back[i][r]
        groups.append(frags[j:i])
        i = j
    groups.reverse()
    return ["".join(t for g in grp for _, t in sorted(g["frags"])) for grp in groups]


def assign_categories(row_centers, marks):
    """把跨行的合并类别单元格(A类项目/B类项目)分配给每一行。

    不能用"离哪个标记中心最近": 合并单元格的中心对齐的是**整组行的中点**, 所以
    组内靠下的行(如科技竞赛第 6 行 Robocon)会离下一个标记更近而判错。
    正确做法: 类别在表里是**连续分组**的, 于是把 n 行切成 k 段连续组, 使
    Σ|组中心 - 标记中心| 最小 —— 与 column_cells 同构的 DP。
    """
    n, k = len(row_centers), len(marks)
    if k == 0:
        return ["?"] * n
    if k == 1:
        return [marks[0]["label"]] * n
    if n < k:
        return ["?"] * n

    INF = float("inf")
    prefix = [0.0]
    for c in row_centers:
        prefix.append(prefix[-1] + c)
    dp = [[INF] * (k + 1) for _ in range(n + 1)]
    back = [[-1] * (k + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for g in range(1, k + 1):
        mc = marks[g - 1]["center"]
        for i in range(g, n + 1):
            best, bj = INF, -1
            for j in range(g - 1, i):
                if dp[j][g - 1] == INF:
                    continue
                mean_y = (prefix[i] - prefix[j]) / (i - j)
                cost = dp[j][g - 1] + abs(mean_y - mc)
                if cost < best:
                    best, bj = cost, j
            dp[i][g], back[i][g] = best, bj

    labels = ["?"] * n
    i = n
    for g in range(k, 0, -1):
        j = back[i][g]
        for t in range(j, i):
            labels[t] = marks[g - 1]["label"]
        i = j
    return labels


def parse(path):
    pages = collect_fragments(path)
    records = []
    sections = {}   # page_index -> [(y, section_title)]

    for pi, frags in enumerate(pages):
        lines = group_lines(frags)

        # 章节标题: 形如 "一、学科竞赛"。注意在 PDF 里它被拆成
        # [x=80]"一" [x=95]"、" [x=109]"学科竞赛" 三个片段, 必须先用整行文本匹配。
        for ln in lines:
            m = SECTION_RE.match(ln["text"])
            if m:
                sections.setdefault(pi, []).append((ln["y"], m.group(1)))

        # 行锚点: 级别列只有 国家级 / 国际级, 每行恰好一个, 垂直居中
        anchors = [ln for ln in lines
                   if any(re.fullmatch(r"(国家级|国际级|省级|省部级)", t)
                          for _, t in ln["cells"]["level"])]
        if not anchors:
            continue

        # 排除标题行/表头行, 否则会被拼进第 1 行的单元格
        body = [ln for ln in lines if not is_header(ln)]
        anchors = [ln for ln in body
                   if any(re.fullmatch(r"(国家级|国际级|省级|省部级)", t)
                          for _, t in ln["cells"]["level"])]
        if not anchors:
            continue
        centers = [ln["y"] for ln in anchors]          # y 降序 = 从上到下

        # 支持类别(A类项目/B类项目)是跨行的合并单元格:
        # PDF 里被拆成 [x=96]"A" [x=105]"类" 与下一行的 [x=95]"项目" 两个片段。
        cat_marks_raw = []
        for ln in body:
            cat_text = "".join(t for _, t in sorted(ln["cells"]["no_cat"])
                               if not t.isdigit())
            if re.fullmatch(r"[AB]\s*类|项目", cat_text.replace(" ", "")):
                cat_marks_raw.append((ln["y"], cat_text.replace(" ", "")))
        marks = []
        for y, t in sorted(cat_marks_raw, key=lambda v: -v[0]):
            if marks and abs(marks[-1]["ys"][-1] - y) <= 20:
                marks[-1]["parts"].append(t)
                marks[-1]["ys"].append(y)
            else:
                marks.append({"parts": [t], "ys": [y]})
        for mk in marks:
            joined = "".join(mk["parts"])
            mk["label"] = "A类" if "A" in joined else ("B类" if "B" in joined else "?")
            # 标记中心 = 组内所有片段的 y 均值(而非最上面那个片段)
            mk["center"] = sum(mk["ys"]) / len(mk["ys"])
        marks.sort(key=lambda m: -m["center"])   # 与行中心同序(从上到下)

        row_categories = assign_categories(centers, marks)

        # 逐列用 DP 还原单元格文本(见 column_cells 的注释)
        name_cells = column_cells(column_lines(body, COL_NO_MAX, COL_NAME_MAX), centers)
        level_cells = column_cells(column_lines(body, COL_NAME_MAX, COL_LEVEL_MAX), centers)
        org_cells = column_cells(column_lines(body, COL_LEVEL_MAX, COL_ORG_MAX), centers)
        owner_cells = column_cells(column_lines(body, COL_ORG_MAX, 10 ** 9), centers)
        # 编号列: 只取纯数字片段
        no_frags = []
        for ln in body:
            nums = [(x, t) for x, t in ln["cells"]["no_cat"] if t.strip().isdigit()]
            if nums:
                no_frags.append({"y": ln["y"], "frags": nums})
        no_cells = column_cells(no_frags, centers)

        for i, ln in enumerate(anchors):
            sect = None
            if pi in sections:
                above = [s for s in sections[pi] if s[0] > ln["y"]]
                if above:
                    sect = min(above, key=lambda s: s[0] - ln["y"])[1]

            nums = re.findall(r"\d+", no_cells[i])
            records.append({
                "section": sect,
                "no": int(nums[0]) if nums else None,
                "xjtu_category": row_categories[i],
                "name": name_cells[i],
                "level": level_cells[i],
                "organizer": org_cells[i],
                "owner_dept": owner_cells[i],
                "source_page": pi + 1,
                "source_y": ln["y"],
            })

    # 清理: 去掉原文中的排版噪声
    for r in records:
        r["name"] = re.sub(r"\s+", "", r["name"])
        r["organizer"] = re.sub(r"^Gsi", "", re.sub(r"\s+", "", r["organizer"]))
        r["owner_dept"] = re.sub(r"\s+", "", r["owner_dept"])
        r["level"] = re.sub(r"\s+", "", r["level"])
    return records


def main():
    recs = parse(SRC)
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    payload = {
        "source": {"title": "学生学科/科技竞赛 A 类、B 类项目列表",
                   "url": SOURCE_URL,
                   "warning": "经核对为不完整的旧版名单(2页/19项), 现行版本须向实践教学中心核对",
                   "retrieved_by": "scripts/parse_xjtu_ab.py"},
        "schema_version": 1,
        "count": len(recs),
        "items": recs,
    }
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("parsed: %d" % len(recs))
    print()
    for r in recs:
        print("[%s|%s|%-3s] %-34s %-6s %-30s -> %s" % (
            r["section"], r["xjtu_category"], r["no"], r["name"],
            r["level"], r["organizer"][:30], r["owner_dept"]))
    print()
    print("written:", DST)


if __name__ == "__main__":
    main()
