# -*- coding: utf-8 -*-
import json
from pathlib import Path

from bbook import chapters as C
from conftest import FIXTURES


def load_frames():
    return json.loads((FIXTURES / "frames_ocr.json").read_text(encoding="utf-8"))


def test_parse_description_timestamps():
    desc = (FIXTURES / "description.txt").read_text(encoding="utf-8")
    marks = C.parse_description(desc)
    assert len(marks) == 5
    assert marks[0]["t"] == 0
    assert marks[1]["t"] == 260                      # 04:20
    assert marks[1]["title"] == "工具调用的觉醒"
    assert marks[-1]["t"] == 38 * 60 + 40


def test_chrome_detection_only_hits_decoration():
    chrome = C.detect_chrome(load_frames())
    low = {c.lower() for c in chrome}
    assert "gen0" in low and "结论" in low
    # 关键：绝不能把正文里的单个汉字当噪声删掉
    assert not ({"代", "演", "变"} & chrome)


def test_title_cards_and_tidy_title():
    segs = C.slide_segments(load_frames())
    cards = C.pick_title_cards(segs)
    titles = [C.tidy_title(c["text"]) for c in cards]
    assert len(cards) >= 3, "至少应识别出 GEN1/GEN2/GEN3 三张标题卡"
    assert any(t.startswith("GEN1") for t in titles)
    for t in titles:
        assert "&" not in t and "&l" not in t, "OCR 噪声未清理: %s" % t
        assert not t.startswith("0"), "编号前缀未清理: %s" % t
        assert t != "未命名"


def test_chapters_from_slides_are_contiguous():
    paras = [{"start": i * 10.0, "end": i * 10.0 + 9, "t": "00:00:%02d" % i,
              "text": "第%d段正文内容用于测试切章边界是否连续" % i} for i in range(40)]
    segs = C.slide_segments(load_frames())
    chapters = C.chapters_from_slides(paras, C.pick_title_cards(segs))
    assert len(chapters) >= 3
    for a, b in zip(chapters, chapters[1:]):
        assert a["to"] <= b["from"], "章节区间重叠了"
    assert chapters[0]["from"] == 0
    assert chapters[-1]["to"] == len(paras)


def test_duration_fallback():
    paras = [{"start": i * 30.0, "end": i * 30.0 + 25, "t": "t", "text": "x" * 50}
             for i in range(60)]           # 30 分钟
    chapters = C.chapters_by_time(paras, minutes=10)
    assert len(chapters) == 3
    assert chapters[0]["from"] == 0 and chapters[-1]["to"] == 60


def test_auto_prefers_description(tmp_path):
    from bbook.paths import WorkDir
    wd = WorkDir(tmp_path / "w")
    paras = [{"start": i * 10.0, "end": i * 10.0 + 9, "t": "00:00:%02d" % i,
              "text": "正文"} for i in range(300)]
    wd.fixed.write_text(json.dumps(paras, ensure_ascii=False), encoding="utf-8")
    wd.meta.write_text(json.dumps({
        "description": (FIXTURES / "description.txt").read_text(encoding="utf-8")
    }, ensure_ascii=False), encoding="utf-8")
    res = C.auto(wd)
    assert res["strategy"] == "description"
    assert res["chapters"] == 5
    assert json.loads(wd.chapters.read_text(encoding="utf-8"))[1]["title"] == "工具调用的觉醒"


def test_auto_falls_back_to_slides_then_time(tmp_path):
    from bbook.paths import WorkDir
    wd = WorkDir(tmp_path / "w2")
    paras = [{"start": i * 10.0, "end": i * 10.0 + 9, "t": "00:00:%02d" % i,
              "text": "正文"} for i in range(40)]
    wd.fixed.write_text(json.dumps(paras, ensure_ascii=False), encoding="utf-8")
    wd.meta.write_text(json.dumps({"description": "没有时间点的简介"}, ensure_ascii=False),
                       encoding="utf-8")
    wd.p("frames_ocr.json").write_text(
        json.dumps(load_frames(), ensure_ascii=False), encoding="utf-8")
    assert C.auto(wd)["strategy"].startswith("slides")

    # 连 OCR 都没有 → 时长兜底
    wd.p("frames_ocr.json").unlink()
    assert C.auto(wd)["strategy"] == "duration fallback"
