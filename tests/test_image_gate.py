# -*- coding: utf-8 -*-
"""图像闸门：版式相同、文字不同的两屏，文字指标拦不住，靠像素拦。"""
import json

from bbook import align as A
from conftest import FIXTURES


def load_frames():
    return json.loads((FIXTURES / "frames_ocr.json").read_text(encoding="utf-8"))


def test_text_gate_only_would_let_these_through():
    """同一张幻灯片的不同滚动位置：句子级重复度可能很低，但其实是同一屏。"""
    a = "这是幻灯片上的第一句内容用于测试重复度判断"
    b = "完全不同的另一句话没有任何重叠部分在这里"
    ga, gb = A._grams(a), A._grams(b)
    assert len(ga & gb) / max(1, len(ga | gb)) < 0.35


def test_window_compares_with_several_previous_picks():
    """只跟上一张比会漏掉「隔一张的近重复」——这是实际踩到的 bug。"""
    import inspect
    sig = inspect.signature(A.select_representatives)
    assert sig.parameters["window"].default >= 2
    assert sig.parameters["max_img_sim"].default <= 0.8


def test_img_sig_is_scale_invariant(tmp_path):
    """签名要先归一化，否则亮度不同的两张图会被算成「不一样」。"""
    from PIL import Image, ImageDraw
    if A._img_sig is None:
        return
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    for path, off in ((a, 0), (b, 40)):
        im = Image.new("L", (64, 36), 80 + off)
        ImageDraw.Draw(im).rectangle([8, 8, 40, 28], fill=200 + off)
        im.save(path)
    sa, sb = A._img_sig(a), A._img_sig(b)
    assert sa is not None and sb is not None, "签名不该依赖 numpy，PIL 就够"
    assert A._sig_sim(sa, sb) > 0.95, "亮度不同但结构相同的图，应当判为高度相似"


def test_missing_frames_dir_does_not_crash():
    """没有帧文件时图像闸门应当自动跳过，而不是抛异常。"""
    picks = A.select_representatives(load_frames(), frames_dir=None)
    assert picks
