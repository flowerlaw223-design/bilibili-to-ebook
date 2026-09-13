# -*- coding: utf-8 -*-
"""多 P / 合集 → 一整本书。

设计：**一个分 P 一个工作目录**，各 P 独立跑完 Phase 1–6，最后统一合并：
    work/<id>/
      series.json         合集与分 P 清单
      part-001/           该 P 的完整中间产物（与单视频工作目录同构）
      part-002/
      cleaned_paragraphs_final.json   合并后的正文（chapter 边界 = 分 P 边界）
      figures.json        合并后的配图（图注已换算为全局段落索引）
      chapters.json       一章 = 一个分 P，标题取自 B 站分 P 名
      book.md / book.epub / book.docx
"""
from __future__ import annotations
import json, re, urllib.request
from pathlib import Path

from .paths import WorkDir, find_tool
from . import fetch as F

UA = F.UA
VIEW_API = "https://api.bilibili.com/x/web-interface/view?bvid=%s"


def _bvid(url: str) -> str | None:
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    return m.group(1) if m else None


def clean_part_title(name: str) -> str:
    """分 P 名往往带编号和画质后缀：'3-3.基础Hardless项目搭建-1080P 高清-AVC' → '基础Hardless项目搭建'"""
    t = name or ""
    t = re.sub(r"[-_]\s*\d{3,4}[Pp].*$", "", t)          # 去画质后缀
    t = re.sub(r"[-_]\s*(高清|标清|超清|AVC|HEVC|AV1)\b.*$", "", t, flags=re.I)
    t = re.sub(r"^\s*\d+[-.]\d*[.、\s]*", "", t)          # 去 '3-3.' / '12.' 之类编号
    t = re.sub(r"^\s*\d+[.、\s]+", "", t)
    return t.strip(" -_·.") or (name or "未命名").strip()


def list_parts(url: str, cookies: str | None = None) -> list[dict]:
    """取分 P 清单。优先用 B 站 view 接口 —— yt-dlp 对合集里每个 P 返回的是同一个标题，不可用。"""
    bv = _bvid(url)
    if bv:
        try:
            req = urllib.request.Request(VIEW_API % bv,
                                         headers={"User-Agent": UA,
                                                  "Referer": "https://www.bilibili.com/"})
            d = json.load(urllib.request.urlopen(req, timeout=30)).get("data") or {}
            pages = d.get("pages") or []
            if pages:
                return [{"index": p.get("page"), "title": p.get("part") or "",
                         "duration": p.get("duration"), "cid": p.get("cid"),
                         "url": "%s?p=%s" % (url.split("?")[0], p.get("page"))}
                        for p in pages]
        except Exception:
            pass
    # 兜底：yt-dlp
    out = F._ytdlp(["--flat-playlist", "-J", url])
    d = json.loads(out)
    return [{"index": e.get("playlist_index") or i + 1,
             "title": e.get("title") or "", "duration": e.get("duration"),
             "url": e.get("url") or e.get("webpage_url") or url}
            for i, e in enumerate(d.get("entries") or [])]


def plan(wd: WorkDir, url: str, cookies: str | None = None,
         limit: int | None = None, parts: list[int] | None = None) -> dict:
    allp = list_parts(url, cookies)
    if parts:
        sel = [p for p in allp if p["index"] in parts]
    elif limit:
        sel = allp[:limit]
    else:
        sel = allp
    for i, p in enumerate(sel, 1):
        p["dir"] = "part-%03d" % i
        p["chapter_title"] = clean_part_title(p["title"])
    series = {"url": url, "bvid": _bvid(url), "total_parts": len(allp),
              "selected": len(sel), "parts": sel}
    wd.p("series.json").write_text(json.dumps(series, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return series


def run(wd: WorkDir, url: str, limit: int | None = None, parts: list[int] | None = None,
        cookies: str | None = None, terms: Path | None = None, model: str = "small",
        frames: bool = True, frame_interval: int = 15, per_chapter: int = 3,
        max_height: int = 720) -> dict:
    from . import asr as A, text as T, frames as FR, book as B

    series = plan(wd, url, cookies, limit, parts)
    print("合集：%d 个分 P，本次处理 %d 个" % (series["total_parts"], series["selected"]))

    for i, p in enumerate(series["parts"], 1):
        pw = WorkDir(wd.root / p["dir"])
        print("\n===== [%d/%d] P%s %s =====" % (i, series["selected"], p["index"],
                                                p["chapter_title"]))
        if not pw.meta.exists():
            m = F.probe(pw, p["url"], cookies)
            print("  元数据 ok：%s 秒" % m.get("duration"))
        if not pw.asr.exists():
            audio = F.download_audio(pw, p["url"], cookies)
            print("  音频 %.1f MB" % (audio.stat().st_size / 1048576))
            A.transcribe(pw, audio, size=model)
        if not pw.fixed.exists():
            T.run(pw, terms)
        if frames and not pw.p("figures.json").exists():
            try:
                FR.run(pw, url=p["url"], interval=frame_interval,
                       max_height=max_height, max_per_chapter=per_chapter)
            except Exception as e:
                print("  [warn] 该 P 配图失败，跳过：%s" % str(e)[:140])

    return merge(wd, series, per_chapter=per_chapter)


def merge(wd: WorkDir, series: dict, per_chapter: int = 3) -> dict:
    """把所有分 P 的段落 / 配图 / 章节合成一本书。"""
    from . import book as B
    merged, chapters, figures = [], [], []
    for i, p in enumerate(series["parts"], 1):
        pw = WorkDir(wd.root / p["dir"])
        src = pw.fixed if pw.fixed.exists() else pw.paragraphs
        paras = json.loads(src.read_text(encoding="utf-8")) if src.exists() else []
        base = len(merged)
        for q in paras:
            q = dict(q)
            q["part"] = i
            q["part_index"] = p["index"]
            merged.append(q)
        chapters.append({"title": p["chapter_title"], "from": base, "to": len(merged),
                         "part": p["index"], "duration": p.get("duration"),
                         "intro": ""})

        fp = pw.p("figures.json")
        if fp.exists():
            for f in json.loads(fp.read_text(encoding="utf-8")):
                f = dict(f)
                f["para_index"] = base + f["para_index"]
                f["chapter"] = i
                f["rel"] = "%s/frames/%s" % (p["dir"], f["file"])
                figures.append(f)

    wd.fixed.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    wd.chapters.write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
    wd.p("figures.json").write_text(json.dumps(figures, ensure_ascii=False, indent=1),
                                    encoding="utf-8")

    total_min = sum((p.get("duration") or 0) for p in series["parts"]) / 60
    meta = {
        "title": re.sub(r"^[^\w\u4e00-\u9fff]+", "", series["parts"][0]["title"] or "") or "合集",
        "subtitle": "%d 集合集 · 共 %d 个分 P · 约 %.0f 分钟" % (len(series["parts"]),
                                                            series["total_parts"], total_min),
        "author": "视频作者：B站 UP 主",
        "rights": "内容版权归原作者所有，本电子书仅供个人学习使用。",
        "about": "本书由 B 站合集自动转换而成：每个分 P 对应一章，正文为语音转写并经分段、"
                 "术语归正整理，未增删事实。",
        "source_note": "来源：%s\n合集共 %d 个分 P，本书收录 %d 个。\n"
                       "转换方式：yt-dlp 音频 → faster-whisper 本地转写 → 清洗与术语归正 → "
                       "抽帧配图 → pandoc 生成 EPUB3。" % (series["url"], series["total_parts"],
                                                          len(series["parts"])),
    }
    wd.book_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    if not wd.cover.exists():
        B.make_cover(wd, meta["title"][:12] + "\n合集精读", meta["subtitle"][:20],
                     "B站视频精读电子书")

    print("\n合并完成：%d 个分 P / %d 章 / %d 段 / %d 张配图"
          % (len(series["parts"]), len(chapters), len(merged), len(figures)))
    return {"parts": len(series["parts"]), "chapters": len(chapters),
            "paragraphs": len(merged), "figures": len(figures)}
