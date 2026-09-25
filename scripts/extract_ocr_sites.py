# -*- coding: utf-8 -*-
"""从 OCR 文本里提取站点条目, 推导候选网址, 并逐条实测连通性。

思路:
  OCR 能可靠读出**网站名称**和 URL 的**第一行片段**(子域名), 但完整 URL 因为
  换行被截断、且 '.'/':' 常被误识为 '·'/'：'。西交的站点命名规律是
  <子域名>.xjtu.edu.cn, 所以用片段推导候选, 再**用真实请求验证**。
  最终只保留实测连通的 —— 导航站填错网址比缺条目更糟。

输入: _ocr/cleaned.txt
输出: _ocr/sites.json   {name?, sub, url, status, note}
"""
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = r"F:\竞赛信息"
SRC = os.path.join(ROOT, "_ocr", "cleaned.txt")
DST = os.path.join(ROOT, "_ocr", "sites.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")}

# 明显不是域名的噪声词
NOISE = {
    "https", "http", "www", "html", "htm", "jsp", "aspx", "cn", "edu", "com",
    "dataService", "index", "login", "cas", "vpn", "sso", "portal",
}


def extract_subdomains(lines):
    """从 OCR 文本里刮出可能的子域名 token。"""
    subs = {}
    for i, l in enumerate(lines):
        s = l.strip()
        # 形式一: 裸子域名, 如 "stu" / "hello" / "xsxb"
        if re.fullmatch(r"[a-z][a-z0-9]{1,14}", s) and s not in NOISE:
            subs.setdefault(s, []).append(i)
        # 形式二: 含 xjtu 的片段
        for m in re.finditer(r"([a-z0-9\-]{2,20})\s*[·/\.]\s*xjtu", s, re.I):
            t = m.group(1).lower().strip(".")
            if t and t not in NOISE and not t.isdigit():
                subs.setdefault(t, []).append(i)
    return subs


def probe(url):
    try:
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code          # 有响应就算存在(可能只是根路径没权限)
    except Exception as e:
        return "ERR:" + type(e).__name__


def main():
    lines = [l.strip() for l in open(SRC, encoding="utf-8").read().splitlines()]
    subs = extract_subdomains(lines)
    print("从 OCR 提取到候选子域名: %d 个" % len(subs))

    cands = []
    for sub in sorted(subs):
        for scheme in ("https", "http"):
            cands.append("%s://%s.xjtu.edu.cn/" % (scheme, sub))

    print("生成候选 URL: %d 个, 开始实测..." % len(cands))
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(probe, cands))

    bysub = {}
    for url, st in zip(cands, results):
        sub = url.split("//")[1].split(".")[0]
        ok = isinstance(st, int)
        cur = bysub.get(sub)
        # 优先保留能连通的, https 优先
        if cur is None or (ok and not cur["ok"]) or (ok == cur["ok"] and url.startswith("https")):
            bysub[sub] = {"sub": sub, "url": url, "status": st, "ok": ok}

    good = sorted([v for v in bysub.values() if v["ok"]], key=lambda x: x["sub"])
    bad = sorted([v for v in bysub.values() if not v["ok"]], key=lambda x: x["sub"])

    json.dump({"good": good, "bad": bad}, open(DST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print()
    print("=== 实测连通 (%d 个) ===" % len(good))
    for v in good:
        print("  [%s] https://%s.xjtu.edu.cn/" % (v["status"], v["sub"]))
    print()
    print("=== 连不上 (%d 个) ===" % len(bad))
    for v in bad:
        print("  [%s] %s.xjtu.edu.cn" % (str(v["status"])[:18], v["sub"]))
    print()
    print("written:", DST)


if __name__ == "__main__":
    main()
