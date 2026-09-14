# -*- coding: utf-8 -*-
"""Phase 4：自动切章 —— 让单视频也能"一条命令出书"。

三级策略（按可靠性排序，前一级失败自动降级）：
  1. **简介时间点**：UP 主在视频简介里写的 "00:00 章节名"，最权威；
  2. **幻灯片标题卡**：从 Phase 6 的 OCR 数据里找"短文本段"——正片内容页 80+ 字，
     标题卡只有二三十字，且带 GEN/第X章/数字编号等标记。实测能把人工切的章
     复现到 30 秒以内；
  3. **时长兜底**：按固定分钟数切，标题用该章第一张幻灯片的标题或"第N章"。
"""
from __future__ import annotations
import json, re
from pathlib import Path
from .paths import WorkDir

# 幻灯片每帧都有的装饰元素（导航条/角标），只在"清点"时用，绝不删单个汉字
CHROME_WORDS = {"gen0", "gen1", "gen2", "gen3", "gen4", "gen5", "gen6",
                "结论", "终论", "genol", "genoi"}
PAGE_RE = re.compile(r"\b\d{1,3}\s*/\s*\d{1,3}\b")


def _tokens(text: str) -> set:
    """单字母也算 token：幻灯片角落的 'G' 之类 OCR 残渣每帧都有，必须能被识别成装饰。"""
    return set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z][A-Za-z0-9_\-]*", text))


def detect_chrome(frames_ocr: list[dict], ratio: float = 0.4,
                  gram_ratio: float = 0.6, gram_min: int = 2,
                  isolated_ratio: float = 0.3) -> set:
    """找出几乎每帧都出现的装饰元素（角标、常驻标题栏、页码）。

    两类都抓：
      1. 单词级：拉丁词、装饰词；
      2. 汉字长 n-gram：中文没空格，单字频率毫无意义（"的"当然每帧都有），
         必须用 4 字以上的片段 —— 常驻标题栏"我的面试复盘"就是靠这个抓出来的。
    """
    n = max(1, len(frames_ocr))
    freq: dict = {}
    grams: dict = {}
    isolated: dict = {}
    for o in frames_ocr:
        raw = o.get("text", "") or ""
        for t in _tokens(raw):
            freq[t] = freq.get(t, 0) + 1
        seen = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", raw):
            for size in range(gram_min, min(9, len(run) + 1)):
                for i in range(len(run) - size + 1):
                    seen.add(run[i:i + size])
        for g in seen:
            grams[g] = grams.get(g, 0) + 1
        # 被空格单独隔开的汉字 —— 多是图标被 OCR 认成的单字（"品""白""心"）
        for ch in re.findall(r"(?<!\S)[\u4e00-\u9fff](?!\S)", raw):
            isolated[ch] = isolated.get(ch, 0) + 1

    chrome = {w.lower() for w in CHROME_WORDS}
    for t, c in freq.items():
        if c >= n * ratio and (len(t) > 1 or t.isascii()):
            chrome.add(t.lower())
    for g, c in grams.items():
        if len(g) >= gram_min and c >= n * gram_ratio:
            chrome.add(g)
    for ch, c in isolated.items():
        if c >= n * isolated_ratio:
            chrome.add(ch)
    return chrome


def clean_slide(text: str, chrome: set) -> str:
    """去掉页码、角标与高频装饰词，保留正文。

    带保险丝：如果照规则清完之后剩下的汉字不到原文的三成，说明判定错了
    （典型场景：样本很少时，每帧都一样的正文被当成"角标"整段删掉），
    这时退回只去页码。宁可留点噪声，也不能把正文吃光。
    """
    raw = text or ""
    n_all = len(re.findall(r"[\u4e00-\u9fff]", raw))
    t = PAGE_RE.sub(" ", raw)
    t = re.sub(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_\-/\.]*|\d+", 
               lambda m: "" if (m.group(0).isascii() and m.group(0).lower() in chrome)
               else (" " if (m.group(0) in chrome) else m.group(0)), t)
    for g in sorted((c for c in chrome if not c.isascii() and len(c) >= 2),
                    key=len, reverse=True):        # 常驻标题栏：长的先清
        t = t.replace(g, " ")
    t = re.sub(r"(?:^|\s)([\u4e00-\u9fff])(?=\s|$)",
               lambda m: " " if m.group(1) in chrome else m.group(0), t)   # 孤立单字噪声
    t = re.sub(r"[&§@#]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if n_all >= 8 and len(re.findall(r"[\u4e00-\u9fff]", t)) < n_all * 0.3:
        return PAGE_RE.sub(" ", raw).strip()       # 保险丝：清过头了，退回轻清
    return t


def slide_segments(frames_ocr: list[dict], sim: float = 0.5) -> list[dict]:
    """按"与上一帧的相似度"切分幻灯片。

    注意：不能拿"累积 token 集合"去比 —— 中文单字重叠率高，集合越滚越大，
    几十帧下来会把整段视频并成一块。只比相邻两帧才是稳定的换页检测。
    """
    chrome = detect_chrome(frames_ocr)
    segs, cur, prev = [], None, None
    for o in frames_ocr:
        ct = clean_slide(o.get("text", ""), chrome)
        s = _tokens(ct)
        if cur is None:
            cur = {"t": o["t"], "texts": [ct], "toks": set(s)}
        else:
            j = len(prev & s) / max(1, len(prev | s))
            if j >= sim:
                cur["texts"].append(ct)
                cur["toks"] |= s
            else:
                segs.append(cur)
                cur = {"t": o["t"], "texts": [ct], "toks": set(s)}
        prev = s
    if cur:
        segs.append(cur)
    out = []
    for s in segs:
        best = max(s["texts"], key=len).strip()
        out.append({"t": s["t"], "text": best, "chars": len(best)})
    return out


# ---------------------------------------------------------------- 策略 1：简介时间点
TS_RE = re.compile(r"^\s*[\(\[]?((?:\d{1,2}:)?\d{1,2}:\d{2})[\)\]]?\s*[-–—:：]?\s*(.+?)\s*$")


def parse_description(desc: str) -> list[dict]:
    out = []
    for line in (desc or "").splitlines():
        m = TS_RE.match(line.strip().lstrip("·-•* "))
        if not m:
            continue
        parts = [int(x) for x in m.group(1).split(":")]
        secs = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
        title = m.group(2).strip()
        if title:
            out.append({"t": secs, "title": title})
    return out


# ---------------------------------------------------------------- 策略 2：幻灯片标题卡
TITLE_MARK = re.compile(r"(GEN\s*\d|第\s*[一二三四五六七八九十\d]+\s*[章代]|"
                        r"^\d{1,2}\s|[·｜|]|规律\s*\d|结论|终论|前瞻|小结|总结)", re.I)


def pick_title_cards(segs: list[dict], max_chars: int = 48, min_chars: int = 4) -> list[dict]:
    """标题卡 = 带结构标记（GEN/第X章/规律）且明显偏短的页。

    阈值曾尝试做成"随视频自适应"（取分段长度中位数的一半），但在幻灯片长度比较
    均匀的视频上会把阈值压到 20 出头，导致一张卡都识别不出来 —— 已回退为固定值，
    该值在 46 分钟真实视频上验证可用（内容页 74~213 字 vs 标题卡 20~45 字）。
    """
    cards = []
    for s in segs:
        t = s["text"]
        if not (min_chars <= len(t) <= max_chars):
            continue
        if not TITLE_MARK.search(t):
            continue
        cards.append(s)
    # 合并时间过近的标题卡（同一张卡被切成两段）
    merged = []
    for c in cards:
        if merged and c["t"] - merged[-1]["t"] < 30:
            if len(c["text"]) > len(merged[-1]["text"]):
                merged[-1] = c
            continue
        merged.append(c)
    return merged


JUNK_PREFIX = re.compile(
    r"^(?:[&§@#]+|[lI1]\s?\d{1,4}[A-Za-z]{0,3}|\d{1,3}|Geno|GENO|EO|OE)\s*", re.I)


def tidy_title(text: str, max_len: int = 38) -> str:
    """把 OCR 出来的幻灯片文字整成能当标题/图注的样子。

    保留词间空格（OCR 本来就按文本块分了空格，全删会变成一坨），
    只清掉开头的导航条残渣和页码。
    """
    t = (text or "").strip()
    t = re.sub(r"[&§@#]+\s*[A-Za-z]?\d*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for _ in range(3):                       # 残渣可能叠好几层
        t2 = JUNK_PREFIX.sub("", t).strip()
        if t2 == t:
            break
        t = t2
    marks = list(re.finditer(r"(GEN\s*\d|规律\s*\d|第\s*[一二三四五六七八九十\d]+\s*[章代])",
                             t, re.I))
    if marks and marks[-1].start() < 40:     # 前面都是导航条
        t = t[marks[-1].start():]
    t = re.sub(r"^(GEN\s*\d)\s*[/·]?\s*", r"\1 ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -_·./")
    if len(t) > max_len:
        cut = t[:max_len]
        sp = cut.rfind(" ")
        t = (cut[:sp] if sp > max_len * 0.5 else cut).rstrip() + "…"
    return t or "未命名"


def chapters_from_slides(paras: list[dict], cards: list[dict]) -> list[dict]:
    if not cards:
        return []
    bounds = [c["t"] for c in cards]
    chapters, cursor = [], 0
    for i, c in enumerate(cards):
        lo_t = bounds[i]
        hi_t = bounds[i + 1] if i + 1 < len(cards) else float("inf")
        frm = max(cursor, next((j for j, p in enumerate(paras) if p["end"] >= lo_t), len(paras)))
        to = max(frm, next((j for j, p in enumerate(paras) if p["start"] >= hi_t), len(paras)))
        if to <= frm:
            continue
        cursor = to
        chapters.append({"title": tidy_title(c["text"]), "from": frm, "to": to,
                         "intro": "", "auto": "slides"})
    if chapters and chapters[0]["from"] > 0:      # 补上开篇
        chapters.insert(0, {"title": "开篇", "from": 0, "to": chapters[0]["from"],
                            "intro": "", "auto": "slides"})
    return chapters


# ---------------------------------------------------------------- 策略 3：时长兜底
def chapters_by_time(paras: list[dict], minutes: float = 8.0, titles: list[dict] | None = None) -> list[dict]:
    if not paras:
        return []
    span = paras[-1]["end"] - paras[0]["start"]
    n = max(1, round(span / 60 / minutes))
    size = max(1, len(paras) // n)
    chapters = []
    for i in range(0, len(paras), size):
        seg = paras[i:i + size]
        lo_t = seg[0]["start"]
        # 只在"看起来像标题"时才拿来当章名：随便抓一句正文当标题会产出垃圾
        # （实测出现过"你想让我们在 阅读中构建什么？"这种）
        title = None
        for t in (titles or []):
            if t["t"] <= lo_t and TITLE_MARK.search(t["text"] or ""):
                title = t["text"]
        chapters.append({"title": tidy_title(title) if title else "第%d章" % (len(chapters) + 1),
                         "from": i, "to": min(i + size, len(paras)), "intro": "",
                         "auto": "time"})
    return chapters


# ---------------------------------------------------------------- 入口
def auto(wd: WorkDir, strategy: str = "auto", minutes: float = 8.0) -> dict:
    src = wd.fixed if wd.fixed.exists() else wd.paragraphs
    if not src.exists():
        raise RuntimeError("缺少清洗后的段落文件，请先运行 clean 阶段")
    paras = json.loads(src.read_text(encoding="utf-8"))

    meta = {}
    if wd.meta.exists():
        try:
            meta = json.loads(wd.meta.read_text(encoding="utf-8"))
        except Exception:
            pass

    chapters, used = [], "none"

    if strategy in ("auto", "description"):
        marks = parse_description(meta.get("description", ""))
        if len(marks) >= 3:
            bounds = [m["t"] for m in marks]
            for i, m in enumerate(marks):
                hi = bounds[i + 1] if i + 1 < len(marks) else float("inf")
                frm = next((j for j, p in enumerate(paras) if p["end"] >= m["t"]), len(paras))
                to = next((j for j, p in enumerate(paras) if p["start"] >= hi), len(paras))
                if to > frm:
                    chapters.append({"title": tidy_title(m["title"]), "from": frm,
                                     "to": to, "intro": "", "auto": "description"})
            if len(chapters) >= 3:
                used = "description"

    segs = []
    fo = wd.p("frames_ocr.json")
    if not chapters and fo.exists() and strategy in ("auto", "slides"):
        segs = slide_segments(json.loads(fo.read_text(encoding="utf-8")))
        cards = pick_title_cards(segs)
        chapters = chapters_from_slides(paras, cards)
        if len(chapters) >= 3:
            used = "slides (%d 张标题卡)" % len(cards)
        else:
            chapters = []

    if not chapters:
        titles = [s for s in segs if len(s["text"]) <= 48]
        chapters = chapters_by_time(paras, minutes, titles)
        used = "duration fallback"

    wd.chapters.write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
    print("自动切章：%s → %d 章" % (used, len(chapters)))
    for i, c in enumerate(chapters, 1):
        print("  第%2d章 %-34s 段落 %d-%d" % (i, c["title"], c["from"] + 1, c["to"]))
    return {"strategy": used, "chapters": len(chapters)}
