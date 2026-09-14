# -*- coding: utf-8 -*-
"""选帧逻辑的回归测试：相邻两张必须"看得出区别"，同时不能靠丢内容换。"""
import json

from bbook import align as A
from conftest import FIXTURES


def load_frames():
    return json.loads((FIXTURES / "frames_ocr.json").read_text(encoding="utf-8"))


def _jac(a, b):
    return len(a & b) / max(1, len(a | b))


def test_consecutive_picks_are_distinct():
    """相邻入选帧的句子级重复度必须低于阈值 —— 防止"滚两行"占两个位置。"""
    picks = A.select_representatives(load_frames(), max_sim=0.35)
    assert len(picks) >= 3
    gs = [A._grams(p["text"]) for p in picks]
    for a, b in zip(gs, gs[1:]):
        assert _jac(a, b) <= 0.35 + 1e-6


def test_near_duplicate_frames_collapse():
    """同一张幻灯片重复出现时，只应选出一张。"""
    base = [{"t": 0, "file": "a.jpg", "text": "这是同一张幻灯片上的完整句子内容用于测试"},
            {"t": 10, "file": "b.jpg", "text": "这是同一张幻灯片上的完整句子内容用于测试"},
            {"t": 20, "file": "c.jpg", "text": "这是同一张幻灯片上的完整句子内容用于测试"}]
    assert len(A.select_representatives(base)) == 1


def test_scrolled_content_is_not_dropped():
    """滚动文档：不能为了"不一样"而漏内容 —— 每一帧都要被某张入选图覆盖到。"""
    frames = load_frames()
    picks = A.select_representatives(frames, max_sim=0.35)
    pg = [A._grams(p["text"]) for p in picks]
    worst = 1.0
    for f in frames:
        g = A._grams(f["text"])
        if g:
            worst = min(worst, max(_jac(g, p) for p in pg))
    assert worst >= 0.2, "有帧的内容完全没被任何入选图覆盖到"


def test_picks_carry_time_and_title():
    picks = A.select_representatives(load_frames())
    for p in picks:
        assert p["t1"] >= p["t0"]
        assert p["title"] and p["file"]
