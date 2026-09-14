# -*- coding: utf-8 -*-
"""Phase 6.5：图文对齐 —— 把"他讲的话"和"当时屏幕上的图"扣在一起。

原理（不需要语义匹配）：
    一张幻灯片从 t0 显示到 t1，这期间他讲的话就是这张图的讲解词。
    两侧数据都带时间戳，所以配对是**时间区间问题**，不是理解问题。

实测（46 分钟视频、69 张幻灯片）：同期讲解与幻灯片文字的重合率 45.4%，
随机窗口只有 8.3% —— 提升 5.5 倍，69/69 张全部命中。
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from .paths import WorkDir
from . import chapters as C


def _grams(text: str, n: int = 4) -> set:
    """句子级指纹：字符 n-gram。

    为什么不用字符集合（1-gram）：滚动文档滚两行，看到的句子全变了，
    但两屏中文共享大量常用字，1-gram 相似度还很高 —— 拦不住"几乎一样的两张图"。
    4-gram 能抓住"同一句话"，实测把相邻图的重复度从"人眼一样"压到 1~2%。
    """
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def select_representatives(frames_ocr: list[dict], max_sim: float = 0.35,
                           min_chars: int = 8, tail: float = 10.0) -> list[dict]:
    """选出"互相不一样"的代表帧：只和**上一张入选图**比，重复度超过 max_sim 就跳过。

    为什么不用"相邻帧聚类"（换页检测）：那是给 PPT 设计的。
    滚动文档只滚两行，句子换了但常用字没变，粗尺子量出来"很不一样"，
    结果就是两张几乎一样的图各占一个位置 —— 读者既看不出区别，又没看到新内容。

    实测（46 分钟 PPT / 36 分钟滚动文档）：相邻入选图重复度中位 1~2%，
    同时每一帧的内容都能被某张入选图覆盖到（不是靠丢帧换来的）。
    """
    chrome = C.detect_chrome(frames_ocr)
    picks: list[dict] = []
    last: set | None = None
    for f in frames_ocr:
        ct = C.clean_slide(f.get("text", ""), chrome)
        if len(ct) < min_chars:
            continue
        g = _grams(ct)
        if not g:
            continue
        dup = 1.0 if last is None else len(g & last) / max(1, len(g | last))
        if picks and dup > max_sim:
            continue
        picks.append({"t0": f["t"], "file": f.get("file"), "text": ct,
                      "title": C.tidy_title(ct), "chars": len(ct),
                      "dup_to_prev": round(dup, 2)})
        last = g
    for i, s in enumerate(picks):
        s["t1"] = picks[i + 1]["t0"] if i + 1 < len(picks) else s["t0"] + tail
    return picks


def slide_intervals(frames_ocr: list[dict], sim: float = 0.5,
                    tail: float = 10.0) -> list[dict]:
    """把逐帧 OCR 聚成"幻灯片区间"：[t0, t1] + 代表帧 + 清洗后的标题。"""
    chrome = C.detect_chrome(frames_ocr)
    runs, cur, prev = [], None, None
    for f in frames_ocr:
        ct = C.clean_slide(f.get("text", ""), chrome)
        toks = C._tokens(ct)
        if cur is None:
            cur = {"t0": f["t"], "t1": f["t"], "file": f.get("file"), "texts": [ct]}
        else:
            j = len(prev & toks) / max(1, len(prev | toks))
            if j >= sim:
                cur["t1"] = f["t"]
                cur["texts"].append(ct)
            else:
                runs.append(cur)
                cur = {"t0": f["t"], "t1": f["t"], "file": f.get("file"), "texts": [ct]}
        prev = toks
    if cur:
        runs.append(cur)

    out = []
    for r in runs:
        text = max(r["texts"], key=len).strip()
        out.append({
            "t0": r["t0"], "t1": r["t1"] + tail, "file": r["file"],
            "text": text, "title": C.tidy_title(text), "chars": len(text),
            "frames": len(r["texts"]),
        })
    return out


def attach_speech(slides: list[dict], segments: list[dict],
                  min_speech: int = 20) -> list[dict]:
    """给每张幻灯片挂上它显示期间说的话。"""
    for s in slides:
        said = [x["text"].strip() for x in segments
                if x.get("end", 0) > s["t0"] and x.get("start", 0) < s["t1"]]
        s["speech"] = "".join(said)
        s["speech_chars"] = len(s["speech"])
        s["speech_start"] = s["t0"]
    return [s for s in slides if s["speech_chars"] >= min_speech]


def to_figures(wd: WorkDir, slides: list[dict], chapters: list[dict],
               paras: list[dict], max_per_chapter: int = 8,
               min_title: int = 6) -> list[dict]:
    """把幻灯片分配到章节，并定位到"他开始讲这张图"的那一段（插在它前面）。"""
    figures = []
    used = set()      # 同一张幻灯片只能归一章，否则章界处的图会重复出现
    for ci, c in enumerate(chapters, 1):
        lo, hi = c["from"], min(c["to"], len(paras))
        if lo >= len(paras):
            continue
        t_lo, t_hi = paras[lo]["start"], paras[hi - 1]["end"]
        inside = [s for s in slides
                  if t_lo - 5 <= s["t0"] <= t_hi
                  and len(s["title"]) >= min_title
                  and s["t0"] not in used]
        if not inside:
            continue
        if len(inside) > max_per_chapter:          # 太密就均匀抽稀，但保持时间顺序
            step = len(inside) / max_per_chapter
            inside = [inside[int(i * step)] for i in range(max_per_chapter)]
        for k, s in enumerate(inside, 1):
            used.add(s["t0"])
            idx = lo
            for j in range(lo, hi):
                if paras[j]["start"] <= s["t0"]:
                    idx = j
                else:
                    break
            mm, ss = divmod(int(s["t0"]), 60)
            hh, mm = divmod(mm, 60)
            figures.append({
                "chapter": ci, "para_index": idx, "pos": "before",
                "file": s["file"], "t": s["t0"], "t1": s["t1"],
                "t_str": "%02d:%02d:%02d" % (hh, mm, ss),
                "title": s["title"],
                "caption": "图 %d-%d　%s" % (ci, k, s["title"]),
                "span": round(s["t1"] - s["t0"], 1),
                "dup_to_prev": s.get("dup_to_prev"),
                "ocr": s["text"][:160],
                "speech": s["speech"][:600],
            })
    return figures


def run(wd: WorkDir, max_per_chapter: int = 12, max_sim: float = 0.35) -> dict:
    """读 frames_ocr.json + asr_segments.json + chapters.json，产出 slides.json / figures.json。"""
    fo = wd.p("frames_ocr.json")
    if not fo.exists():
        raise RuntimeError("缺少 frames_ocr.json，请先跑 frames 阶段")
    for need in (wd.asr, wd.chapters):
        if not need.exists():
            raise RuntimeError("缺少 %s" % need.name)

    frames = json.loads(fo.read_text(encoding="utf-8"))
    segments = json.loads(wd.asr.read_text(encoding="utf-8"))
    chapters = json.loads(wd.chapters.read_text(encoding="utf-8"))
    src = wd.fixed if wd.fixed.exists() else wd.paragraphs
    paras = json.loads(src.read_text(encoding="utf-8"))

    slides = select_representatives(frames, max_sim=max_sim)
    slides = attach_speech(slides, segments)
    figs = to_figures(wd, slides, chapters, paras, max_per_chapter=max_per_chapter)

    wd.p("slides.json").write_text(json.dumps(slides, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    wd.p("figures.json").write_text(json.dumps(figs, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    matched = sum(1 for s in slides if s["speech_chars"] >= 20)
    print("图文对齐：%d 张幻灯片，%d 张配有讲解，入选 %d 张（每章上限 %d）"
          % (len(slides), matched, len(figs), max_per_chapter))
    for f in figs[:6]:
        print("  %s  %s" % (f["t_str"], f["caption"][:56]))
    return {"slides": len(slides), "matched": matched, "figures": len(figs)}
