# -*- coding: utf-8 -*-
"""Phase 6：抽帧 + OCR + 幻灯片识别 → 章节配图。

思路（针对"口播 + PPT"型中文长视频）：
1. 按固定间隔抽帧（默认 10 秒一帧）；
2. 用 rapidocr 识别每帧文字，**丢弃画面底部字幕带**（否则每帧都有文字，无法区分幻灯片）；
3. 相邻帧按字符集合相似度聚类成"幻灯片段"，取文字最丰富的一帧作代表；
4. 过滤掉时间过短或文字过少的段（多半是人脸镜头）；
5. 按时间戳把入选幻灯片分配到章节，并记录其所在段落位置，供构建阶段插图。
"""
from __future__ import annotations
import json, re, subprocess, sys
from pathlib import Path
from .paths import WorkDir, find_tool


def download_video(wd: WorkDir, url: str, max_height: int = 720,
                   cookies: str | None = None) -> Path:
    from .fetch import _ytdlp
    existing = sorted(p for p in wd.root.glob("video.*") if p.suffix != ".part")
    if existing:
        return existing[0]
    args = ["-f", "bv*[height<=%d]/b[height<=%d]/b" % (max_height, max_height),
            "-o", str(wd.p("video.%(ext)s"))]
    if cookies:
        args += ["--cookies", cookies]
    args.append(url)
    _ytdlp(args)
    files = sorted(p for p in wd.root.glob("video.*") if p.suffix != ".part")
    if not files:
        raise RuntimeError("视频下载失败")
    return files[0]


def extract_frames(wd: WorkDir, video: Path, interval: int = 10,
                   width: int = 960) -> list[Path]:
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg")
    out_dir = wd.p("frames")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not list(out_dir.glob("f_*.jpg")):
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
               "-vf", "fps=1/%d,scale=%d:-2" % (interval, width),
               "-q:v", "3", str(out_dir / "f_%05d.jpg")]
        subprocess.run(cmd, check=True)
    return sorted(out_dir.glob("f_*.jpg"))


def _tokenize(text: str) -> set:
    """中英混合分词：汉字按字，拉丁按词。"""
    han = set(re.findall(r"[\u4e00-\u9fff]", text))
    lat = set(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,}", text))
    return han | lat


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def ocr_frames(wd: WorkDir, frames: list[Path], interval: int,
               subtitle_band: float = 0.78, progress_every: int = 40) -> list[dict]:
    """识别每帧文字，丢弃底部字幕带。结果缓存在 frames_ocr.json。"""
    cache = wd.p("frames_ocr.json")
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if len(data) == len(frames):
                print("  复用已有 OCR 结果（%d 帧）" % len(data))
                return data
        except Exception:
            pass

    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    out = []
    for i, fp in enumerate(frames):
        try:
            res, _ = engine(str(fp))
        except Exception:
            res = None
        keep, dropped = [], 0
        for item in (res or []):
            box, text = item[0], item[1]
            ys = [p[1] for p in box]
            y_center = (min(ys) + max(ys)) / 2.0
            # 画面高度：scale 后宽度 960，按 16:9 估 540；用框的最大 y 归一化更稳
            if y_center > subtitle_band * 540:
                dropped += 1
                continue
            if text and text.strip():
                keep.append(text.strip())
        out.append({
            "index": i,
            "file": fp.name,
            "t": round((i + 0.5) * interval, 1),
            "text": " ".join(keep),
            "chars": sum(len(k) for k in keep),
            "dropped": dropped,
        })
        if (i + 1) % progress_every == 0:
            print("  OCR %d/%d 帧" % (i + 1, len(frames)), flush=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def group_slides(frames_ocr: list[dict], min_chars: int = 20,
                 min_span: float = 5.0, sim: float = 0.5) -> list[dict]:
    """把 OCR 结果聚成幻灯片段，选出代表帧。"""
    segs, cur = [], None
    for f in frames_ocr:
        toks = _tokenize(f["text"])
        if cur is None:
            cur = {"frames": [f], "tokens": toks}
            continue
        if _jaccard(cur["tokens"], toks) >= sim:
            cur["frames"].append(f)
            cur["tokens"] |= toks
        else:
            segs.append(cur)
            cur = {"frames": [f], "tokens": toks}
    if cur:
        segs.append(cur)

    slides = []
    for s in segs:
        best = max(s["frames"], key=lambda x: x["chars"])
        span = s["frames"][-1]["t"] - s["frames"][0]["t"] + 10
        if best["chars"] < min_chars or span < min_span:
            continue
        slides.append({
            "t": best["t"], "file": best["file"], "text": best["text"],
            "chars": best["chars"], "span": round(span, 1),
            "n_frames": len(s["frames"]),
        })
    return slides


def assign_to_chapters(wd: WorkDir, slides: list[dict],
                       max_per_chapter: int = 3) -> list[dict]:
    """按时间戳把幻灯片分配到章节，并定位到最近的段落（供插图）。"""
    paras = json.loads((wd.fixed if wd.fixed.exists() else wd.paragraphs)
                       .read_text(encoding="utf-8"))
    # 合集场景下每个分 P 没有自己的 chapters.json —— 此时把整个 P 当成一章处理，
    # 章号由 series.merge 在合并时重新编号。
    if wd.chapters.exists():
        chapters = json.loads(wd.chapters.read_text(encoding="utf-8"))
    else:
        chapters = [{"title": "", "from": 0, "to": len(paras)}]
    figures = []
    for ci, c in enumerate(chapters, 1):
        lo, hi = c["from"], min(c["to"], len(paras))
        t_lo = paras[lo]["start"] if lo < len(paras) else 0
        t_hi = paras[hi - 1]["end"] if hi - 1 < len(paras) else 1e9
        inside = [s for s in slides if t_lo <= s["t"] <= t_hi]
        if not inside:
            continue
        # 均匀取点，避免全挤在开头
        inside.sort(key=lambda x: x["t"])
        if len(inside) > max_per_chapter:
            step = len(inside) / max_per_chapter
            inside = [inside[int(i * step)] for i in range(max_per_chapter)]
        for k, s in enumerate(inside, 1):
            idx = lo
            for j in range(lo, hi):
                if paras[j]["start"] <= s["t"]:
                    idx = j
                else:
                    break
            mm, ss = divmod(int(s["t"]), 60)
            hh, mm = divmod(mm, 60)
            figures.append({
                "chapter": ci, "para_index": idx, "file": s["file"],
                "t": s["t"], "t_str": "%02d:%02d:%02d" % (hh, mm, ss),
                "caption": "图 %d-%d　视频 %02d:%02d:%02d 处画面" % (ci, k, hh, mm, ss),
                "ocr": s["text"][:120],
            })
    wd.p("figures.json").write_text(json.dumps(figures, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return figures


def run(wd: WorkDir, url: str | None = None, interval: int = 10,
        max_height: int = 720, max_per_chapter: int = 3,
        min_chars: int = 20, cookies: str | None = None) -> dict:
    video = None
    if url:
        video = download_video(wd, url, max_height, cookies)
        print("视频：%s (%.1f MB)" % (video.name, video.stat().st_size / 1048576))
    else:
        vs = sorted(p for p in wd.root.glob("video.*") if p.suffix != ".part")
        if not vs:
            raise RuntimeError("工作目录没有视频文件，请传 --url 或先下载")
        video = vs[0]

    frames = extract_frames(wd, video, interval)
    print("抽帧：%d 张（每 %d 秒一帧）" % (len(frames), interval))

    ocr = ocr_frames(wd, frames, interval)
    slides = group_slides(ocr, min_chars=min_chars)
    print("识别出候选幻灯片：%d 段" % len(slides))

    figures = assign_to_chapters(wd, slides, max_per_chapter)
    print("分配到章节的配图：%d 张" % len(figures))
    for f in figures:
        print("  第%s章 @%s  %s" % (f["chapter"], f["t_str"], f["file"]))
    return {"frames": len(frames), "slides": len(slides), "figures": len(figures)}
