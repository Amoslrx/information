# -*- coding: utf-8 -*-
"""把推断出的年度节律生成 ICS 日历订阅文件。

设计取舍:
  节律是从历史通知统计出来的**窗口**(例如"电子设计竞赛往年 3–5 月发通知"),
  不是精确日期。日历事件的做法:
    - 事件起点 = 窗口起始月的 1 日, 持续 14 天 —— "该开始盯通知了";
    - RRULE:FREQ=YEARLY —— 订阅一次, 每年自动出现, 这是"产品走向用户"的关键;
    - VALARM 提前 7 天提醒;
    - 描述里写清完整窗口、观测年数、依据通知日期和免责说明, 不做无根据的断言。

输出:
  site/calendar/all.ics        全部可推断节律的竞赛
  site/calendar/ee-core.ics    仅电气相关度 >= 4 的核心竞赛
"""
import hashlib
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed")
OUT = os.path.join(ROOT, "site", "calendar")

PRODID = "-//XJTU EE Competition Info//competitions.ics//CN"
CAL_NAME = "西交电气 · 竞赛年度节律"
ALARM_DAYS = 7
EVENT_DAYS = 14
EE_CORE_MIN = 4


# ---------- ICS 基础格式 ----------

def esc_text(s):
    """ICS TEXT 值转义: 反斜杠、分号、逗号、换行。"""
    return (str(s or "")
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line):
    """按 RFC 5545 折行: 每行不超过 75 个八位组, 折行处以单个空格开头。

    注意必须按 UTF-8 **字节**计数, 且不能把一个多字节字符切开。
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > 75:
            parts.append(cur)
            cur = b" "            # 续行标记, 计入 75 字节
        cur += cb
    parts.append(cur)
    return "\r\n".join(p.decode("utf-8") for p in parts)


def dtstamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event_dates(window_start, now=None):
    """返回 (DTSTART, DTEND) 的 YYYYMMDD。窗口起始月若已过, 则用明年。"""
    now = now or datetime.now()
    year = now.year
    if window_start < now.month:
        year += 1
    start = datetime(year, window_start, 1)
    end = start.fromordinal(start.toordinal() + EVENT_DAYS)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


# ---------- 事件 ----------

def stable_uid(rec):
    """事件的稳定标识。

    必须是**确定性**的: 日历客户端靠 UID 判断"这是同一个事件的新版本"。
    如果每次生成都换 UID, 客户端会把它当成新事件, 逐年堆积重复项。
    所以不能用 Python 的 hash()(每个进程随机化), 也不能用生成时间。
    优先用教育部目录序号(稳定且短), 否则用竞赛名的 md5。
    """
    if rec.get("moeNo"):
        return "moe%d" % rec["moeNo"]
    return "h" + hashlib.md5(rec["competition"].encode("utf-8")).hexdigest()[:12]


def make_event(rec, stamp, now=None):
    ds, de = event_dates(rec["windowStart"], now)
    uid = "xjtu-ee-comp-%s@competition-info" % stable_uid(rec)

    summary = "%s · 往年 %s 发通知" % (rec["competition"], rec["windowLabel"])

    desc = [
        "往年通知窗口：%s（覆盖 %d%% 的历史通知）" % (rec["windowLabel"], round(rec["coverage"] * 100)),
        "观测年数：%d 年（%s）" % (rec["yearsObserved"],
                              "、".join(str(y) for y in rec["years"])),
    ]
    if rec.get("stableMonths"):
        desc.append("稳定出现月份：" + "、".join("%d月" % m for m in rec["stableMonths"]))
    if rec.get("ee"):
        desc.append("电气相关度：%d/5" % rec["ee"])
    if rec.get("xjtuCat"):
        desc.append("西交认定：%s" % rec["xjtuCat"])
    if rec.get("dept"):
        desc.append("归口部门：%s" % rec["dept"])
    if rec.get("url"):
        desc.append("官网：" + rec["url"])
    if rec.get("evidence"):
        desc.append("依据通知日期：" + "、".join(rec["evidence"][:5]))
    desc.append("")
    desc.append("※ 这是从历史校内通知统计推断的窗口，不是官方赛程，具体以学校通知为准。")

    lines = [
        "BEGIN:VEVENT",
        "UID:" + uid,
        "DTSTAMP:" + stamp,
        "DTSTART;VALUE=DATE:" + ds,
        "DTEND;VALUE=DATE:" + de,
        "RRULE:FREQ=YEARLY",
        "SUMMARY:" + esc_text(summary),
        "DESCRIPTION:" + esc_text("\n".join(desc)),
        "TRANSP:TRANSPARENT",
    ]
    if rec.get("url"):
        lines.append("URL:" + rec["url"])
    lines += [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "TRIGGER:-P%dD" % ALARM_DAYS,
        "DESCRIPTION:" + esc_text("%s 往年此时开始发通知，可以去实践教学中心看最新通知" % rec["competition"]),
        "END:VALARM",
        "END:VEVENT",
    ]
    return lines


def build_calendar(records, cal_name, cal_desc, stamp, now=None):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + esc_text(cal_name),
        "X-WR-CALDESC:" + esc_text(cal_desc),
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:P7D",
        "X-PUBLISHED-TTL:P7D",
    ]
    for rec in records:
        lines += make_event(rec, stamp, now)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main():
    with open(os.path.join(SEED, "cadence.json"), encoding="utf-8") as f:
        d = json.load(f)
    items = d["items"]

    # 把 moeNo / 官网 从总表补进来(uid 需要稳定标识)
    import csv
    moe = {}
    with open(os.path.join(SEED, "competitions_master.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            no = r["教育部目录序号"].strip()
            moe[r["竞赛名称"].strip()] = int(no) if no.isdigit() else None
    for r in items:
        r["moeNo"] = moe.get(r["competition"])

    os.makedirs(OUT, exist_ok=True)
    stamp = dtstamp()
    now = datetime.now()

    core = [r for r in items if (r.get("ee") or 0) >= EE_CORE_MIN]

    targets = [
        ("all.ics", items, CAL_NAME,
         "从西交实践教学中心历史通知推断的竞赛年度节律。共 %d 个竞赛。" % len(items)),
        ("ee-core.ics", core, CAL_NAME + "（电气核心）",
         "仅电气相关度 >= %d 的竞赛。共 %d 个。" % (EE_CORE_MIN, len(core))),
    ]

    for fn, recs, name, desc in targets:
        text = build_calendar(recs, name, desc, stamp, now)
        path = os.path.join(OUT, fn)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        # 校验: 事件数、CRLF、折行
        n_ev = text.count("BEGIN:VEVENT")
        max_line = max(len(l.encode("utf-8")) for l in text.split("\r\n"))
        print("%-14s 事件 %-3d  %6.1f KB  最大行长 %d 字节 %s" % (
            fn, n_ev, len(text.encode("utf-8")) / 1024.0, max_line,
            "OK" if max_line <= 75 else "!! 超 75 字节"))

    print()
    print("节假日历示例(前 3 个事件):")
    for rec in items[:3]:
        ds, de = event_dates(rec["windowStart"], now)
        print("  %s ~ %s  %s · 往年 %s 发通知" % (ds, de, rec["competition"][:28], rec["windowLabel"]))
    print()
    print("输出目录:", OUT)


if __name__ == "__main__":
    main()
