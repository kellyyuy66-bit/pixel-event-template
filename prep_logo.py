# -*- coding: utf-8 -*-
"""把会徽原图处理成 assets/logo.png：裁掉白边 + 圆形透明蒙版 + 缩放。

日常使用不必执行：assets/logo.png 已经备好，build.py 直接内联它。
只有更换会徽时才需要：
    1) 用新图覆盖 assets/logo-src.png（白底、正方形最佳）
    2) 运行 python prep_logo.py
    3) 再运行 python build.py
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'assets', 'logo-src.png')
OUT = os.path.join(ROOT, 'assets', 'logo.png')
SIZE = 400
PAD = 4
SS = 4


def main():
    if not os.path.isfile(SRC):
        print('[x] 找不到原始会徽：%s' % SRC)
        return 1

    im = Image.open(SRC).convert('RGB')
    w, h = im.size
    print('[i] 原图尺寸 %dx%d' % (w, h))

    # 白底图：找出非白区域并裁掉四周空白
    mask = im.convert('L').point(lambda v: 255 if v < 245 else 0)
    box = mask.getbbox()
    if box:
        left, top, right, bottom = box
        left = max(0, left - PAD)
        top = max(0, top - PAD)
        right = min(w, right + PAD)
        bottom = min(h, bottom + PAD)
        im = im.crop((left, top, right, bottom))
        print('[i] 裁剪为 %s' % (box,))

    im = im.resize((SIZE, SIZE), Image.LANCZOS)

    # 圆形透明蒙版：先按 4 倍超采样画圆再缩放，得到平滑边缘
    m = Image.new('L', (SIZE * SS, SIZE * SS), 0)
    ImageDraw.Draw(m).ellipse((0, 0, SIZE * SS - 1, SIZE * SS - 1), fill=255)
    m = m.resize((SIZE, SIZE), Image.LANCZOS)

    out = im.convert('RGBA')
    out.putalpha(m)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.save(OUT, 'PNG', optimize=True)

    print('[√] 已生成 %s（%.0f KB）' % (OUT, os.path.getsize(OUT) / 1024))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
