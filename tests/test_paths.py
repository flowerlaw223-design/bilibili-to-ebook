# -*- coding: utf-8 -*-
from bbook.paths import WorkDir, find_font, find_tool, tool_report


def test_workdir_creates_subdirs(tmp_path):
    wd = WorkDir(tmp_path / "case")
    for sub in ("audio", "models", "frames", "out"):
        assert (wd.root / sub).is_dir()
    assert wd.book_md.parent == wd.root
    assert wd.p("a", "b").name == "b"


def test_resume_state(tmp_path):
    wd = WorkDir(tmp_path / "case")
    assert not wd.done("probe")
    wd.mark("probe")
    wd.mark("audio")
    assert wd.done("probe") and wd.done("audio")
    assert not wd.done("build")
    assert WorkDir(wd.root).done("probe"), "状态应能跨实例读取"


def test_tool_report_shape():
    rep = tool_report()
    assert set(rep) >= {"yt-dlp", "ffmpeg", "pandoc"}
    assert rep["ffmpeg"] is None or "ffmpeg" in rep["ffmpeg"].lower()
    assert find_font() is None or find_font().endswith((".ttc", ".ttf", ".otf"))
    assert find_tool("绝不存在的工具") is None
