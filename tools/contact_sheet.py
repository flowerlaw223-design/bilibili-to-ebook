# -*- coding: utf-8 -*-
"""contact_sheet.py —— 把入选的配图排成网格总览，用于快速目视验收。

用法: python tools/contact_sheet.py <workdir> [--cols 5] [--per-sheet 20]
"""
import json, sys, argparse
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--per-sheet", type=int, default=20)
    ap.add_argument("--thumb-w", type=int, default=360)
    a = ap.parse_args()

    from PIL import Image, ImageDraw, ImageFont
    wd = Path(a.workdir)
    figs = json.loads((wd / "figures.json").read_text(encoding="utf-8"))
    frames = {f["file"]: f for f in json.loads((wd / "frames_ocr.json").read_text(encoding="utf-8"))}
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)

    cols, per = a.cols, a.per_sheet
    tw = a.thumb_w
    th = int(tw * 9 / 16)
    pad, cap = 8, 26
    sheets = [figs[i:i + per] for i in range(0, len(figs), per)]
    out = []
    for si, group in enumerate(sheets, 1):
        rows = (len(group) + cols - 1) // cols
        W = cols * (tw + pad) + pad
        H = rows * (th + cap + pad) + pad + 30
        canvas = Image.new("RGB", (W, H), (24, 28, 36))
        d = ImageDraw.Draw(canvas)
        d.text((pad, 6), "配图总览 %d/%d　共 %d 张　（左上角时间点 = 视频进度）"
               % (si, len(sheets), len(figs)), font=font, fill=(200, 210, 225))
        for i, f in enumerate(group):
            r, c = divmod(i, cols)
            x = pad + c * (tw + pad)
            y = 30 + pad + r * (th + cap + pad)
            p = wd / "frames" / f["file"]
            try:
                im = Image.open(p).convert("RGB").resize((tw, th))
                canvas.paste(im, (x, y))
            except Exception:
                d.rectangle([x, y, x + tw, y + th], outline=(120, 130, 150))
            dup = f.get("dup_to_prev")
            tag = "%s  %s" % (f["t_str"], f["file"].replace("f_", "").replace(".jpg", ""))
            if dup is not None:
                tag += "  与前图重复 %d%%" % round(dup * 100)
            d.text((x + 2, y + th + 4), tag, font=font, fill=(180, 195, 215))
        o = wd / ("contact_sheet_%d.png" % si)
        canvas.save(o, quality=88)
        out.append(o)
        print("  %s  (%d 张, %.1f MB)" % (o.name, len(group), o.stat().st_size / 1048576))
    return out

if __name__ == "__main__":
    main()
