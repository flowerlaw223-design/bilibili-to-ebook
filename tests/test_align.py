# -*- coding: utf-8 -*-
"""图文对齐的回归测试：这是本项目唯一"别人做不到"的能力，必须锁住行为。"""
import json

from bbook import align as A
from bbook.paths import WorkDir
from conftest import FIXTURES


def load_frames():
    return json.loads((FIXTURES / "frames_ocr.json").read_text(encoding="utf-8"))


def load_segs():
    return json.loads((FIXTURES / "asr_segments.json").read_text(encoding="utf-8"))


def test_slide_intervals_have_span_and_clean_title():
    slides = A.slide_intervals(load_frames())
    assert slides, "应至少切出一张幻灯片"
    for s in slides:
        assert s["t1"] >= s["t0"], "区间必须闭合"
        assert s["file"], "必须带代表帧文件名"
        assert "&" not in s["title"] and not s["title"].startswith("0")
    titles = [s["title"] for s in slides]
    assert any(t.startswith("GEN1") for t in titles)


def test_title_keeps_word_spacing():
    """OCR 本来按文本块分了空格，全删掉会变成一坨 —— 这条锁住它。"""
    assert " " in A.C.tidy_title("架构意义 大脑加四肢的第一次合体 在此之前")


def test_every_slide_gets_speech():
    slides = A.attach_speech(A.slide_intervals(load_frames()), load_segs())
    assert slides
    assert all(s["speech_chars"] > 0 for s in slides), "每张图都应该配上它显示期间的讲解"


def test_figures_are_unique_across_chapters():
    """章界处的幻灯片只应归一章，否则同一张图会出现两次。"""
    paras = [{"start": i * 10.0, "end": i * 10.0 + 9, "t": "00:00:%02d" % i, "text": "x"}
             for i in range(40)]
    chapters = [{"title": "A", "from": 0, "to": 20, "intro": ""},
                {"title": "B", "from": 20, "to": 40, "intro": ""}]
    slides = A.attach_speech(A.slide_intervals(load_frames()), load_segs())
    figs = A.to_figures(WorkDir.__new__(WorkDir), slides, chapters, paras)  # type: ignore
    times = [f["t"] for f in figs]
    assert len(times) == len(set(times)), "同一张幻灯片被重复分配了"


def test_figures_insert_before_the_paragraph():
    paras = [{"start": i * 10.0, "end": i * 10.0 + 9, "t": "00:00:%02d" % i, "text": "x"}
             for i in range(40)]
    chapters = [{"title": "A", "from": 0, "to": 40, "intro": ""}]
    slides = A.attach_speech(A.slide_intervals(load_frames()), load_segs())
    figs = A.to_figures(WorkDir.__new__(WorkDir), slides, chapters, paras)
    assert figs
    for f in figs:
        assert f["pos"] == "before"
        assert paras[f["para_index"]]["start"] <= f["t"] + 0.001


def test_run_writes_slides_and_figures(tmp_path):
    wd = WorkDir(tmp_path / "w")
    (wd.asr).write_text(json.dumps(load_segs(), ensure_ascii=False), encoding="utf-8")
    (wd.chapters).write_text(json.dumps([{"title": "A", "from": 0, "to": 3, "intro": ""}],
                                        ensure_ascii=False), encoding="utf-8")
    (wd.fixed).write_text(json.dumps(
        [{"start": i * 10.0, "end": i * 10.0 + 9, "t": "00:00:%02d" % i, "text": "正文"}
         for i in range(4)], ensure_ascii=False), encoding="utf-8")
    wd.p("frames_ocr.json").write_text(json.dumps(load_frames(), ensure_ascii=False),
                                       encoding="utf-8")
    res = A.run(wd)
    assert res["slides"] > 0 and res["figures"] > 0
    assert wd.p("slides.json").exists() and wd.p("figures.json").exists()
