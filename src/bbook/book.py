# -*- coding: utf-8 -*-
"""Phase 7–8：构建 EPUB / DOCX / Markdown，并做结构审计。

EPUB 有两条路径：
  A. pandoc（质量最好，推荐）
  B. 纯 Python 兜底（零外部依赖，pandoc 缺失或版本过旧时自动启用）
"""
from __future__ import annotations
import html, json, os, re, subprocess, zipfile
from pathlib import Path
from .paths import WorkDir, find_tool, find_font

EPUB_MIME = b"application/epub+zip"


# ---------------------------------------------------------------- 封面
def make_cover(wd: WorkDir, title: str, subtitle: str = "", footer: str = "",
               width: int = 1200, height: int = 1600) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  [warn] 未安装 Pillow，跳过封面生成")
        return None
    font_path = find_font()
    if not font_path:
        print("  [warn] 未找到中文字体，跳过封面生成")
        return None

    img = Image.new("RGB", (width, height), (18, 22, 32))
    d = ImageDraw.Draw(img)
    for y in range(height):
        k = y / height
        d.line([(0, y), (width, y)], fill=(int(18 + 26 * k), int(22 + 30 * k), int(32 + 52 * k)))
    f_big = ImageFont.truetype(font_path, int(width * 0.08))
    f_mid = ImageFont.truetype(font_path, int(width * 0.043))
    f_sml = ImageFont.truetype(font_path, int(width * 0.028))

    d.rectangle([width * 0.053, width * 0.053, width * 0.947, height - width * 0.053],
                outline=(96, 150, 226), width=4)
    y = height * 0.27
    for line in title.split("\n"):
        d.text((width * 0.108, y), line, font=f_big, fill=(255, 255, 255))
        y += width * 0.105
    d.line([(width * 0.11, y + 20), (width * 0.11 + 340, y + 20)], fill=(96, 150, 226), width=6)
    if subtitle:
        d.text((width * 0.108, y + 60), subtitle, font=f_mid, fill=(160, 200, 246))
    if footer:
        d.text((width * 0.108, height - width * 0.16), footer, font=f_sml, fill=(150, 165, 190))
    wd.cover.parent.mkdir(parents=True, exist_ok=True)
    img.save(wd.cover)
    return wd.cover


# ---------------------------------------------------------------- Markdown
def build_markdown(wd: WorkDir) -> Path:
    J = lambda p, d=None: json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else d
    paras = J(wd.fixed, [])
    chapters = J(wd.chapters, [])
    meta = J(wd.book_meta, {})
    terms = J(wd.terms, [])
    quotes = J(wd.quotes, [])
    figures = J(wd.p("figures.json"), [])
    if not paras:
        raise RuntimeError("缺少 %s，请先运行 clean 阶段" % wd.fixed)

    def first_at(kw):
        key = re.split(r"[（(/]", kw)[0].strip()
        for p in paras:
            if key and key in p["text"]:
                return p["t"]
        return ""

    L = ["---"]
    for k, v in (("title", meta.get("title", "未命名")),
                 ("subtitle", meta.get("subtitle", "")),
                 ("author", meta.get("author", "")),
                 ("lang", meta.get("lang", "zh-CN")),
                 ("rights", meta.get("rights", ""))):
        if v:
            L.append('%s: "%s"' % (k, str(v).replace('"', "'")))
    L += ["---", ""]
    if meta.get("about"):
        L += ["# 关于本书", ""] + meta["about"].split("\n") + [""]

    L += ["# 目录与时间轴", "", "| 章 | 标题 | 视频时间 | 字数 |", "|---|---|---|---|"]
    for i, c in enumerate(chapters, 1):
        seg = paras[c["from"]:min(c["to"], len(paras))]
        L.append("| %d | %s | %s | %d |" % (i, c["title"], seg[0]["t"] if seg else "-",
                                            sum(len(p["text"]) for p in seg)))
    L.append("")

    for i, c in enumerate(chapters, 1):
        seg = paras[c["from"]:min(c["to"], len(paras))]
        L += ["# 第%d章 %s" % (i, c["title"]), ""]
        link = meta.get("time_link")
        if seg:
            ts = seg[0]["t"]
            head = "> 视频时间点：%s 起" % ts
            if link:
                secs = int(seg[0]["start"])
                head += "（[跳转原片](%s&t=%d)）" % (link, secs)
            L += [head, ""]
        if c.get("intro"):
            L += ["【本章导读】" + c["intro"], ""]
        fig_at = {}
        for f in figures:
            if f.get("chapter") == i:
                fig_at.setdefault(f.get("para_index"), []).append(f)
        for j, p in enumerate(seg, start=c["from"]):
            L += [p["text"], ""]
            for f in fig_at.get(j, []):
                img = wd.p("frames", f["file"])
                if img.exists():
                    # 用相对路径（相对 book.md 所在目录）：pandoc 对 Windows 反斜杠绝对路径不可靠
                    rel = img.relative_to(wd.root).as_posix()
                    L += ["![%s](%s){width=6.5in}" % (f["caption"], rel), ""]

    if terms:
        L += ["# 附录A · 术语表", "", "| 术语 | 说明 | 出现位置 |", "|---|---|---|"]
        for t in terms:
            L.append("| %s | %s | %s |" % (t.get("term", ""), t.get("desc", ""),
                                           t.get("at") or first_at(t.get("term", ""))))
        L.append("")
    if quotes:
        L += ["# 附录B · 金句集", ""]
        L += ["- %s（%s）" % (q.get("text", ""), q.get("at", "")) for q in quotes]
        L.append("")
    if meta.get("source_note"):
        L += ["# 附录C · 版权与来源说明", ""] + meta["source_note"].split("\n") + [""]

    wd.book_md.write_text("\n".join(L), encoding="utf-8")
    print("book.md: %d 字 | 正文 %d 字 | %d 章 | 配图 %d 张"
          % (len("\n".join(L)), sum(len(p["text"]) for p in paras), len(chapters), len(figures)))
    return wd.book_md


# ---------------------------------------------------------------- EPUB：pandoc
def build_epub_pandoc(wd: WorkDir) -> Path | None:
    pandoc = find_tool("pandoc")
    if not pandoc:
        return None
    cmd = [pandoc, wd.book_md.name, "-o", wd.epub.name, "--toc", "--toc-depth=2",
           "--metadata", "lang=zh-CN"]
    if wd.cover.exists():
        cmd.append("--epub-cover-image=" + wd.cover.name)
    # 必须在工作目录下执行：pandoc 按 cwd（而非输入文件所在目录）解析相对图片路径，
    # 否则插图会变成指向 EPUB 外部的死链。
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       cwd=str(wd.root))
    if r.returncode != 0:
        print("  [warn] pandoc 构建失败，将回退到内置构建器：%s" % (r.stderr or "")[-200:])
        return None
    return wd.epub


# ---------------------------------------------------------------- EPUB：纯 Python
def _xhtml(title: str, body: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">\n'
            "<head><meta charset=\"utf-8\"/><title>%s</title>"
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
            "<body>\n%s\n</body></html>\n" % (html.escape(title), body))


def build_epub_pure(wd: WorkDir) -> Path:
    """零依赖 EPUB3 构建器：pandoc 不可用时的兜底。"""
    md = wd.book_md.read_text(encoding="utf-8")
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)          # 去 YAML 头
    md = re.sub(r"^\|[^\n]*\|\s*$", "", md, flags=re.M)            # 去表格
    meta = json.loads(wd.book_meta.read_text(encoding="utf-8")) if wd.book_meta.exists() else {}
    title = meta.get("title", "ebook")
    blocks = re.split(r"(?m)^# ", md)[1:]
    docs, toc = [], []
    for i, blk in enumerate(blocks, 1):
        lines = blk.split("\n")
        head = lines[0].strip()
        body = []
        for ln in lines[1:]:
            ln = ln.rstrip()
            if not ln:
                body.append("")
            elif ln.startswith("> "):
                body.append("<blockquote>%s</blockquote>" % html.escape(ln[2:]))
            else:
                body.append("<p>%s</p>" % html.escape(ln))
        name = "ch%03d.xhtml" % i
        docs.append((name, head, _xhtml(head, "\n".join(body))))
        toc.append((name, head))
    style = ("body{font-family:serif;line-height:1.75;margin:1.2em;}\n"
             "h1{font-size:1.5em;margin:1.4em 0 0.8em;}\n"
             "p{text-indent:2em;margin:0.55em 0;}\n"
             "blockquote{color:#555;border-left:3px solid #ccc;padding-left:.8em;margin:.8em 0;}\n")

    wd.epub.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wd.epub, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), EPUB_MIME, zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/style.css", style)
        for name, _, body in docs:
            z.writestr("OEBPS/" + name, body)
        if wd.cover.exists():
            z.writestr("OEBPS/cover.png", wd.cover.read_bytes())

        manifest = "\n".join(
            '<item id="%s" href="%s" media-type="application/xhtml+xml"/>' % (n[:-6], n)
            for n, _, _ in docs)
        if wd.cover.exists():
            manifest += ('\n<item id="cover-image" href="cover.png" media-type="image/png" '
                         'properties="cover-image"/>')
        manifest += '\n<item id="css" href="style.css" media-type="text/css"/>'
        spine = "\n".join('<itemref idref="%s"/>' % n[:-6] for n, _, _ in docs)
        nav_lis = "\n".join('<li><a href="%s">%s</a></li>' % (n, html.escape(h))
                            for n, h in toc)
        z.writestr("OEBPS/nav.xhtml", _xhtml("目录", "<nav epub:type=\"toc\" id=\"toc\">"
                                             "<h1>目录</h1><ol>%s</ol></nav>" % nav_lis))
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                   'unique-identifier="bookid">\n'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
                   '<dc:identifier id="bookid">urn:uuid:%s</dc:identifier>\n'
                   "<dc:title>%s</dc:title><dc:language>zh-CN</dc:language>\n"
                   "</metadata>\n<manifest>\n%s\n</manifest>\n<spine>\n%s\n</spine>\n"
                   "</package>" % (__import__("uuid").uuid4(), html.escape(title),
                                   manifest, spine))
    print("  [fallback] 使用内置 EPUB 构建器生成（%d 章）" % len(docs))
    return wd.epub


def build_epub(wd: WorkDir) -> Path:
    return build_epub_pandoc(wd) or build_epub_pure(wd)


def build_docx(wd: WorkDir) -> Path | None:
    pandoc = find_tool("pandoc")
    if not pandoc:
        return None
    r = subprocess.run([pandoc, wd.book_md.name, "-o", wd.docx.name, "--toc"],
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=str(wd.root))
    return wd.docx if r.returncode == 0 else None


# ---------------------------------------------------------------- 审计
def audit(wd: WorkDir) -> dict:
    paras = json.loads(wd.fixed.read_text(encoding="utf-8"))
    src_chars = sum(len(p["text"]) for p in paras)
    res = {"src_chars": src_chars, "paragraphs": len(paras)}
    if not wd.epub.exists():
        res["ok"] = False
        return res
    with zipfile.ZipFile(wd.epub) as z:
        names = z.namelist()
        res["mimetype_ok"] = z.read("mimetype") == EPUB_MIME
        res["entries"] = len(names)
        res["xhtml_files"] = len([n for n in names if n.endswith(".xhtml")])
        try:
            res["chapters"] = len(json.loads(wd.chapters.read_text(encoding="utf-8")))
        except Exception:
            res["chapters"] = 0
        res["has_cover"] = any("cover" in n.lower() and n.lower().endswith((".png", ".jpg"))
                               for n in names)
        res["images"] = len([n for n in names
                             if n.lower().endswith((".png", ".jpg", ".jpeg"))])
        plain = re.sub(r"<[^>]+>", "", "".join(
            z.read(n).decode("utf-8", "ignore") for n in names if n.endswith(".xhtml")))
        present = sum(1 for p in paras if p["text"][:24] in plain)
        res["covered"] = present
        res["coverage"] = round(present / max(1, len(paras)) * 100, 1)
    res["ok"] = bool(res["mimetype_ok"] and res.get("coverage", 0) >= 98)
    print("审计：mimetype=%s | 条目 %d | 章节 %d/%d | 封面 %s | 图片 %d | 覆盖 %d/%d (%s%%) -> %s"
          % (res["mimetype_ok"], res["entries"], res["chapters"], res["xhtml_files"],
             res["has_cover"], res.get("images", 0),
             res["covered"], res["paragraphs"], res["coverage"],
             "PASS" if res["ok"] else "FAIL"))
    return res
