# -*- coding: utf-8 -*-
"""把超长 PNG 竖切成若干片, 并用 Windows 内置 OCR 识别文字。

为什么这么做:
  常用网站.png 是 1917x23857 的超长截图, 直接丢给模型要切成十几片、很费 token。
  而 Windows 自带 OCR(Windows.Media.Ocr) 能离线识别中文, 且不需要联网。
  先切图(避开 OCR 的尺寸上限), 再 OCR, 最后正则提取网址 —— 成本几乎为零。

切图是**纯标准库**实现的(zlib + PNG 规范), 不依赖 Pillow:
  PNG = IHDR + IDAT(zlib 压缩的、每行带 1 字节滤波类型的扫描线) + IEND
  解码: zlib.decompress -> 逐行反滤波 -> 原始像素
  编码: 逐行加滤波类型 0(无滤波) -> zlib.compress -> 新 PNG

输出:
  _ocr/slice_00.png ... 切片
  _ocr/ocr.txt           OCR 全文
"""
import os
import re
import struct
import sys
import zlib

SRC = r"F:\竞赛信息\常用网站.png"
OUT = r"F:\竞赛信息\_ocr"
SLICE_H = 8000          # 每片高度, 留足余量避开 OCR 尺寸上限
MAX_OCR = 10000         # Windows OCR 的单边上限


# ------------------------------------------------------------------ PNG 解码
def png_read(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    pos, idat, ihdr = 8, [], None
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    w, h, depth, ctype, comp, filt, interlace = ihdr
    if depth != 8:
        raise ValueError("只支持 8 位深度, 实际 %d" % depth)
    if interlace != 0:
        raise ValueError("不支持隔行扫描")
    if ctype not in (2, 6):
        raise ValueError("只支持 RGB(2)/RGBA(6), 实际 color type=%d" % ctype)
    bpp = 3 if ctype == 2 else 4
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    out = bytearray(w * h * bpp)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:            # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:          # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:          # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:          # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, bpp, bytes(out)


# ------------------------------------------------------------------ PNG 编码
def png_write(path, w, h, bpp, pix, y0):
    ctype = 2 if bpp == 3 else 6
    stride = w * bpp
    raw = bytearray()
    for y in range(h):
        raw.append(0)                                   # 滤波类型 0
        s = (y0 + y) * stride
        raw += pix[s:s + stride]

    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body +
                struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    open(path, "wb").write(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    w, h, bpp, pix = png_read(SRC)
    print("源图: %d x %d, %d 通道" % (w, h, bpp))
    n = (h + SLICE_H - 1) // SLICE_H
    paths = []
    for i in range(n):
        y0 = i * SLICE_H
        hh = min(SLICE_H, h - y0)
        p = os.path.join(OUT, "slice_%02d.png" % i)
        png_write(p, w, hh, bpp, pix, y0)
        paths.append(p)
        print("  切片 %d: y=%5d..%-5d  %d 字节" % (i, y0, y0 + hh, os.path.getsize(p)))
    open(os.path.join(OUT, "slices.txt"), "w", encoding="utf-8").write("\n".join(paths))
    print("共 %d 片, 每片高 %d (OCR 上限 %d)" % (len(paths), SLICE_H, MAX_OCR))


if __name__ == "__main__":
    main()
