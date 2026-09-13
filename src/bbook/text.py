# -*- coding: utf-8 -*-
"""Phase 3：清洗与术语归正。

设计要点（都是踩过坑换来的）：
1. 中文与拉丁字符之间**不存在词边界**，所以术语替换一律用 lookaround，
   绝不能用 \b —— \bjason\b 在"的Jason"里永远匹配不到。
2. 术语表外置为 JSON，按领域可插拔（terms/*.json），不写死在代码里。
3. 只改明显的听写错误；拿不准的保留原样，不静默篡改。
"""
from __future__ import annotations
import json, re
from pathlib import Path

FILLER = re.compile(r"^(嗯+|啊+|呃+|哦+|唉+|然后呢?|就是|这个|那个|对吧|是吧|好吧|那么|"
                    r"所以说|你知道吗)[，。、！？…\s]*$")

ASCII_W = r"A-Za-z0-9"


def _pad(term: str) -> str:
    """给纯拉丁术语自动加 lookaround 边界（中文侧不加边界）。"""
    if re.fullmatch(r"[A-Za-z0-9 ._\-]+", term):
        return r"(?<![%s])%s(?![%s])" % (ASCII_W, re.escape(term), ASCII_W)
    return re.escape(term)


def load_term_map(path: Path | None) -> list[tuple[str, str]]:
    if not path or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("map", data) if isinstance(data, dict) else data
    if isinstance(rows, dict):
        rows = list(rows.items())
    # 长词优先，避免 "GPT" 抢先吃掉 "GPT-4o"
    return sorted([(str(a), str(b)) for a, b in rows], key=lambda x: -len(x[0]))


def apply_terms(paragraphs: list[dict], term_map: list[tuple[str, str]]) -> tuple[list[dict], int]:
    hits = 0
    compiled = [(_pad(a), b) for a, b in term_map]
    for p in paragraphs:
        t = p["text"]
        for pat, rep in compiled:
            t, n = re.subn(pat, rep, t, flags=re.I)
            hits += n
        p["text"] = t
    return paragraphs, hits


def to_paragraphs(segments: list[dict], max_len: int = 200,
                  min_sentence: int = 110, gap: float = 0.9) -> tuple[list[dict], int]:
    """把逐句字幕合并成自然段：遇长停顿 / 超长 / 句子结束且够长 就断段。"""
    keep, dropped = [], 0
    for s in segments:
        t = re.sub(r"\s+", " ", (s.get("text") or "").strip())
        if not t or FILLER.match(t):
            dropped += 1
            continue
        keep.append({"start": s["start"], "end": s["end"], "text": t})

    paras, cur = [], None
    for s in keep:
        if cur is None:
            cur = dict(s)
            continue
        g = s["start"] - cur["end"]
        cur["text"] += s["text"]
        cur["end"] = s["end"]
        if g > gap or len(cur["text"]) >= max_len or \
           (cur["text"].endswith(("。", "！", "？", "”")) and len(cur["text"]) >= min_sentence):
            paras.append(cur)
            cur = None
    if cur:
        paras.append(cur)

    for p in paras:
        m, sec = divmod(int(p["start"]), 60)
        h, m = divmod(m, 60)
        p["t"] = "%02d:%02d:%02d" % (h, m, sec)
        p["text"] = p["text"].strip()
    return paras, dropped


def run(wd, term_file: Path | None = None) -> dict:
    segments = json.loads(wd.asr.read_text(encoding="utf-8"))
    paras, dropped = to_paragraphs(segments)
    wd.paragraphs.write_text(json.dumps(paras, ensure_ascii=False, indent=1), encoding="utf-8")

    term_map = load_term_map(term_file)
    if term_map:
        paras, hits = apply_terms(paras, term_map)
    else:
        hits = 0
    wd.fixed.write_text(json.dumps(paras, ensure_ascii=False, indent=1), encoding="utf-8")
    wd.p("paragraphs_final.txt").write_text(
        "\n".join("[%s] %s" % (p["t"], p["text"]) for p in paras), encoding="utf-8")

    print("段落 %d 个 / %d 字 | 丢弃语气词 %d 段 | 术语归正 %d 处 | 术语表 %d 条"
          % (len(paras), sum(len(p["text"]) for p in paras), dropped, hits, len(term_map)))
    return {"paragraphs": len(paras), "chars": sum(len(p["text"]) for p in paras),
            "dropped": dropped, "term_hits": hits}
