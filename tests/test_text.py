# -*- coding: utf-8 -*-
import json, re
from pathlib import Path

from bbook import text as T
from conftest import FIXTURES

TERMS = Path(__file__).resolve().parents[1] / "terms" / "ai-coding.json"


def load_segs():
    return json.loads((FIXTURES / "asr_segments.json").read_text(encoding="utf-8"))


def test_paragraphs_merge_and_drop_filler():
    segs = load_segs()
    paras, dropped = T.to_paragraphs(segs)
    assert dropped >= 2, "纯语气词行应被丢弃"
    assert len(paras) < len(segs), "短句应被合并成更少的自然段"
    assert all(p["text"].strip() for p in paras)
    assert all(re.fullmatch(r"\d{2}:\d{2}:\d{2}", p["t"]) for p in paras)
    # 时间戳单调不减，且首段时间为 0
    starts = [p["start"] for p in paras]
    assert starts == sorted(starts)
    assert int(paras[0]["t"].split(":")[0]) == 0


def test_term_map_fixes_cjk_adjacent_latin():
    """回归测试：中文与拉丁字符之间没有词边界，旧的 \b 写法会漏掉'的Jason'。"""
    paras = [{"start": 0, "end": 1, "t": "00:00:00",
              "text": "模型可以输出结构化的Jason对象，open cloud 用 sort.md 定义身份"}]
    m = T.load_term_map(TERMS)
    out, hits = T.apply_terms(paras, m)
    t = out[0]["text"]
    assert hits >= 3
    assert "JSON" in t and "Jason" not in t
    assert "OpenClaw" in t
    assert "SOUL.md" in t


def test_term_map_keeps_persona_and_fixes_month_sign():
    paras = [{"start": 0, "end": 1, "t": "00:00:00",
              "text": "这是Persona的第一次产品化，每一次月签背后都有逻辑，方声 calling 改变了这一点"}]
    out, _ = T.apply_terms(paras, T.load_term_map(TERMS))
    t = out[0]["text"]
    assert "Persona" in t, "Persona 不应被误改成 Python"
    assert "跃迁" in t and "月签" not in t
    assert "function calling" in t


def test_run_writes_artifacts(tmp_path):
    from bbook.paths import WorkDir
    wd = WorkDir(tmp_path / "w")
    (wd.asr).write_text(json.dumps(load_segs(), ensure_ascii=False), encoding="utf-8")
    res = T.run(wd, TERMS)
    assert res["paragraphs"] > 0
    assert wd.fixed.exists() and wd.p("paragraphs_final.txt").exists()
    assert "JSON" in wd.fixed.read_text(encoding="utf-8")
