# -*- coding: utf-8 -*-
"""清洗 Windows OCR 的输出, 并提取候选网址。

背景: Windows OCR 对中文识别不错, 但会把 URL 弄坏 ——
  ':' -> '：' (全角), '.' -> '·' 或 '/' , 且中文字之间会插空格。
所以本脚本只信"名称与说明", 网址一律标为"候选", 必须再逐条实测才能用。

输入: _ocr/ocr.txt
输出: _ocr/cleaned.txt   清洗后的文本(便于通读)
      _ocr/urls.json     候选网址(未验证)
"""
import json
import os
import re

ROOT = r"F:\竞赛信息"
SRC = os.path.join(ROOT, "_ocr", "ocr.txt")
CLEAN = os.path.join(ROOT, "_ocr", "cleaned.txt")
URLS = os.path.join(ROOT, "_ocr", "urls.json")

CJK = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"


def despace_cjk(s):
    """去掉中文字符之间的空格: '放 在 前 面' -> '放在前面'"""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"([%s])\s+(?=[%s])" % (CJK, CJK), r"\1", s)
    return s


def fix_url_fragment(s):
    """把 OCR 弄坏的 URL 片段尽量还原(仅用于生成候选, 不可直接使用)。"""
    s = s.replace("：", ":").replace("·", ".").replace("。", ".")
    s = re.sub(r"\s+", "", s)
    s = s.replace("https:/", "https://").replace("http:/", "http://")
    s = re.sub(r"^https?://+", "https://", s)
    # 常见误识: xxx.edu/cn -> xxx.edu.cn ; xxx.edu/com -> xxx.edu.com
    s = re.sub(r"\.(edu|com|org|net|gov)/(cn|com|org|net|gov)\b", r".\1.\2", s)
    return s


def main():
    raw = open(SRC, encoding="utf-8").read()
    lines = [despace_cjk(l.strip()) for l in raw.splitlines()]

    cleaned = []
    cands = []
    for l in lines:
        if not l:
            continue
        cleaned.append(l)
        # 含 URL 特征的行
        if re.search(r"(xjtu|https?|www\.|\.cn|\.edu)", l, re.I):
            for m in re.finditer(r"\S*(?:xjtu|https?://|www\.)\S*", l):
                frag = fix_url_fragment(m.group(0))
                if len(frag) >= 6:
                    cands.append(frag)

    open(CLEAN, "w", encoding="utf-8").write("\n".join(cleaned))

    # 去重并归类
    uniq = []
    seen = set()
    for c in cands:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    # 提取域名, 便于统计
    domains = {}
    for c in uniq:
        m = re.search(r"(?:https?://)?([a-z0-9\-\.]*xjtu[a-z0-9\-\.]*)", c, re.I)
        if m:
            d = m.group(1).strip(".")
            domains[d] = domains.get(d, 0) + 1

    json.dump({"note": "OCR 提取的候选, 未经连通性验证, 不可直接使用",
               "candidates": uniq, "domains": domains},
              open(URLS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("清洗后文本行数: %d -> %s" % (len(cleaned), CLEAN))
    print("候选网址片段  : %d 个 -> %s" % (len(uniq), URLS))
    print("识别到域名    : %d 个" % len(domains))
    print()
    print("=== 候选域名(按出现次数) ===")
    for d, n in sorted(domains.items(), key=lambda kv: -kv[1])[:40]:
        print("  %-42s x%d" % (d, n))


if __name__ == "__main__":
    main()
