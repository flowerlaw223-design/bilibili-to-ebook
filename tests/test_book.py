# -*- coding: utf-8 -*-
import json, re, zipfile
import xml.etree.ElementTree as ET

import pytest

from bbook import book as B
from bbook.paths import WorkDir

PARAS = [
    {"start": 0,  "end": 9,  "t": "00:00:00", "text": "第一章的正文内容，用于测试。" * 3},
    {"start": 10, "end": 19, "t": "00:00:10", "text": "第二段的正文内容。" * 3},
    {"start": 20, "end": 29, "t": "00:00:20", "text": "第二章的正文内容，用于测试。" * 3},
]
CHAPTERS = [
    {"title": "开场", "from": 0, "to": 2, "intro": "这是导读。"},
    {"title": "第二章标题", "from": 2, "to": 3, "intro": ""},
]
META = {"title": "测试书", "subtitle": "副标题", "author": "测试作者",
        "rights": "仅供测试", "about": "这是关于本书的说明。",
        "source_note": "来源：单元测试"}
TERMS = [{"term": "RAG", "desc": "检索增强生成"}]
QUOTES = [{"text": "这是一句金句。", "at": "结论"}]


def make_wd(tmp_path, with_figures=True, with_images=True):
    wd = WorkDir(tmp_path / "book")
    (wd.fixed).write_text(json.dumps(PARAS, ensure_ascii=False), encoding="utf-8")
    (wd.chapters).write_text(json.dumps(CHAPTERS, ensure_ascii=False), encoding="utf-8")
    (wd.book_meta).write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    (wd.terms).write_text(json.dumps(TERMS, ensure_ascii=False), encoding="utf-8")
    (wd.quotes).write_text(json.dumps(QUOTES, ensure_ascii=False), encoding="utf-8")
    if with_figures:
        figs = [{"chapter": 1, "para_index": 1, "file": "f_00001.jpg",
                 "t": 10, "t_str": "00:00:10", "caption": "图 1-1　视频 00:00:10 处画面"}]
        (wd.p("figures.json")).write_text(json.dumps(figs, ensure_ascii=False),
                                          encoding="utf-8")
        if with_images:
            (wd.p("frames", "f_00001.jpg")).write_bytes(tiny_jpeg())
    return wd


def tiny_jpeg():
    """一张 1x1 的合法 JPEG，避免依赖 Pillow。"""
    import base64
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
        "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")


def test_build_markdown_structure_and_figures(tmp_path):
    wd = make_wd(tmp_path)
    B.build_markdown(wd)
    md = wd.book_md.read_text(encoding="utf-8")
    assert "# 第1章 开场" in md and "# 第2章 第二章标题" in md
    assert "【本章导读】这是导读。" in md
    assert "附录A · 术语表" in md and "附录B · 金句集" in md
    assert md.index("![图 1-1")  # 配图已插入
    # 配图必须紧跟它所属的那一段（para_index=1 → 第 2 段）
    assert md.index("第二段的正文内容") < md.index("![图 1-1")


def test_figure_dropped_when_image_missing(tmp_path):
    wd = make_wd(tmp_path, with_images=False)
    B.build_markdown(wd)
    assert "![" not in wd.book_md.read_text(encoding="utf-8"), "图片不存在时不应输出引用"


def test_figure_survives_rechaptering(tmp_path):
    """回归：配图按段落索引定位，重新切章后不应丢失。"""
    wd = make_wd(tmp_path)
    chapters = json.loads(wd.chapters.read_text(encoding="utf-8"))
    chapters.append({"title": "新切的第三章", "from": 1, "to": 2, "intro": ""})
    wd.chapters.write_text(json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
    B.build_markdown(wd)
    assert "![图 1-1" in wd.book_md.read_text(encoding="utf-8")


def test_pure_epub_is_spec_conformant_and_embeds_images(tmp_path):
    wd = make_wd(tmp_path)
    B.build_markdown(wd)
    B.build_epub_pure(wd)

    with zipfile.ZipFile(wd.epub) as z:
        names = z.namelist()
        assert names[0] == "mimetype"
        assert z.read("mimetype") == B.EPUB_MIME
        for n in names:
            if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ET.fromstring(z.read(n).decode("utf-8"))     # 必须是合法 XML
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        assert "dcterms:modified" in opf, "EPUB3 必需项缺失"
        assert re.search(r'href="nav\.xhtml"[^>]*properties="nav"', opf), "nav 未声明"
        assert 'idref="nav"' not in opf, "nav 不应出现在 spine 里"
        assert any(n.startswith("OEBPS/media/") for n in names), "插图未嵌入"
        body = "".join(z.read(n).decode("utf-8") for n in names if n.endswith(".xhtml"))
        assert 'src="media/' in body, "插图未在正文中引用"
        assert "<figcaption>" in body, "图注缺失"


def test_build_epub_falls_back_without_pandoc(tmp_path, monkeypatch):
    wd = make_wd(tmp_path)
    B.build_markdown(wd)
    monkeypatch.setattr(B, "find_tool", lambda name: None)
    out = B.build_epub(wd)
    assert out == wd.epub and wd.epub.exists()


def test_audit_reports_coverage(tmp_path):
    wd = make_wd(tmp_path)
    B.build_markdown(wd)
    B.build_epub_pure(wd)
    res = B.audit(wd)
    assert res["mimetype_ok"] is True
    assert res["coverage"] == 100.0
    assert res["ok"] is True
    assert res["chapters"] == 2
