# -*- coding: utf-8 -*-
"""把《2025年教育部认可的全国大学生学科竞赛目录清单》PDF 抽出的文本解析为结构化 JSON。

输入: data/raw/moj_2025_catalog.txt   (由 pypdf 从 PDF 抽取, 含 "=== PAGE n ===" 分隔)
输出: data/seed/moj_2025_catalog.json

设计原则(与调研结论一致):
- 只做确定性解析, 不猜测缺失字段; 解析不到的写 null 并在 warnings 里记录。
- 保留 source_url / source_version, 每条记录可追溯。
"""
import json
import os
import re
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "raw", "moj_2025_catalog.txt")
DST_DIR = os.path.join(ROOT, "data", "seed")
DST = os.path.join(DST_DIR, "moj_2025_catalog.json")

SOURCE_URL = (
    "https://ifcen.sysu.edu.cn/sites/default/files/2026-01/"
    "2025%E5%B9%B4%E6%95%99%E8%82%B2%E9%83%A8%E8%AE%A4%E5%8F%AF%E7%9A%84"
    "%E5%85%A8%E5%9B%BD%E5%A4%A7%E5%AD%A6%E7%94%9F%E5%AD%A6%E7%A7%91%E7%AB%9E"
    "%E8%B5%9B%E7%9B%AE%E5%BD%95%E6%B8%85%E5%8D%95.pdf"
)
SOURCE_DESC = "2025年教育部认可的全国大学生学科竞赛目录清单(84项)"

# 条目起始: "12、全国大学生..." / "12、\"挑战杯\"..."
ITEM_RE = re.compile(r"^(\d{1,3})\s*[、.,]\s*(.+)$")
PAGE_RE = re.compile(r"^===\s*PAGE\s+(\d+)\s*===$")
URL_RE = re.compile(r"^(?:https?://|www\.)\S+$")
# URL 折行续片段: 无空格、无中日韩字符, 仅 URL 安全字符
CONT_RE = re.compile(r"^[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$")


def load_lines():
    with open(SRC, encoding="utf-8") as f:
        return [ln.strip() for ln in f]


def is_noise(line: str) -> bool:
    return (not line) or line.startswith("===")


def parse():
    lines = load_lines()
    items = []          # [{no, name, url, url_kind, page}]
    warnings = []
    cur = None
    page = 0

    for ln in lines:
        m = PAGE_RE.match(ln)
        if m:
            page = int(m.group(1))
            continue
        if is_noise(ln):
            continue

        # 目录正文之前的说明段落: 在遇到第 1 条之前跳过
        m = ITEM_RE.match(ln)
        if m:
            no = int(m.group(1))
            # 只有当编号紧随已知序列(首条为1, 之后 +1)时才认为是新条目,
            # 避免把 "2024 年 3 月 22 日" 之类误判为条目。
            expect = (items[-1]["no"] + 1) if items else 1
            if no == expect:
                cur = {"no": no, "name": m.group(2).strip(), "url": None,
                       "url_kind": None, "page": page}
                items.append(cur)
                continue
            # 编号跳跃(原文缺号)时也接受, 但记录警告
            if items and no == items[-1]["no"] + 2:
                cur = {"no": no, "name": m.group(2).strip(), "url": None,
                       "url_kind": None, "page": page}
                items.append(cur)
                warnings.append("目录编号不连续: 从 %d 跳到 %d" % (items[-2]["no"], no))
                continue

        if cur is None:
            continue

        # URL 行
        if URL_RE.match(ln):
            if cur["url"] is None:
                cur["url"] = ln
                cur["url_kind"] = "url"
            else:
                # 续行(长 URL 被 PDF 折行切成两段)
                cur["url"] += ln
                warnings.append("条目 %d URL 折行拼接" % cur["no"])
            continue

        # URL 的后续折行片段: 不含空格/CJK, 只由 URL 安全字符组成
        if (cur["url"] is not None and cur["url_kind"] == "url"
                and CONT_RE.match(ln) and cur["url"] != ln):
            cur["url"] += ln
            warnings.append("条目 %d URL 跨页折行拼接: +%s" % (cur["no"], ln[:24]))
            continue

        # 非 URL 行: 可能是名称续行, 或"微信公众号:"/"主办单位:"之类补充说明
        if cur["url"] is None and len(ln) <= 40 and not ln.startswith(("主办单位", "微信公众号")):
            cur["name"] += ln
            continue
        if ln.startswith("微信公众号"):
            cur["url"] = ln.split("：", 1)[-1].strip()
            cur["url_kind"] = "wechat_mp"
            continue
        if ln.startswith("主办单位"):
            cur["organizer"] = ln.split("：", 1)[-1].strip()
            continue
        warnings.append("条目 %s 忽略无法归类行: %s" % (cur["no"], ln[:40]))

    # 规整
    for it in items:
        it["name"] = re.sub(r"\s+", " ", it["name"]).strip()
        u = it.get("url")
        if u and it.get("url_kind") == "url":
            if u.lower().startswith("http://") or u.lower().startswith("https://"):
                it["url_scheme_ok"] = True
            else:
                # "www.xxx.com" 形式, 补 scheme 但保留原始值
                it["url_scheme_ok"] = False
                it["url_normalized"] = "http://" + u
            it["url_domain"] = urllib.parse.urlparse(
                it.get("url_normalized") or u).netloc.lower()
    return items, warnings


def main():
    items, warnings = parse()
    os.makedirs(DST_DIR, exist_ok=True)

    missing_url = [it["no"] for it in items if not it.get("url")]
    payload = {
        "source": {"title": SOURCE_DESC, "url": SOURCE_URL,
                   "retrieved_by": "scripts/parse_moe_catalog.py"},
        "schema_version": 1,
        "count": len(items),
        "items": items,
        "qa": {
            "missing_url": missing_url,
            "warnings": warnings,
        },
    }
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("parsed items : %d" % len(items))
    print("with url    : %d" % sum(1 for i in items if i.get("url")))
    print("missing url : %s" % (missing_url or "none"))
    print("warnings    : %d" % len(warnings))
    for w in warnings[:12]:
        print("   -", w)
    print("written     : %s" % DST)


if __name__ == "__main__":
    main()
