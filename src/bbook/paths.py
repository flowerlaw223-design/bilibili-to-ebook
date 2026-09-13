# -*- coding: utf-8 -*-
"""路径、目录与外部工具探测：全部去掉硬编码，支持任意工作目录与跨平台。"""
from __future__ import annotations
import os, shutil, sys
from dataclasses import dataclass
from pathlib import Path

# 常见中文字体候选（跨平台）
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

TOOLS = {
    "yt-dlp": ["yt-dlp", "yt-dlp.exe"],
    "ffmpeg": ["ffmpeg", "ffmpeg.exe"],
    "pandoc": ["pandoc", "pandoc.exe"],
}


def find_font() -> str | None:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def find_tool(name: str) -> str | None:
    for cand in TOOLS.get(name, [name]):
        p = shutil.which(cand)
        if p:
            return p
    return None


def tool_report() -> dict:
    return {k: find_tool(k) for k in TOOLS}


@dataclass
class WorkDir:
    """一个视频对应一个工作目录，所有中间产物都落在里面。"""
    root: Path

    def __post_init__(self):
        self.root = Path(self.root).expanduser().resolve()
        for sub in ("audio", "models", "frames", "out"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def p(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    # ---- 规范产物路径（阶段之间只通过这些文件交接）----
    @property
    def meta(self):        return self.p("meta.json")
    @property
    def asr(self):         return self.p("asr_segments.json")
    @property
    def paragraphs(self):  return self.p("cleaned_paragraphs.json")
    @property
    def fixed(self):       return self.p("cleaned_paragraphs_final.json")
    @property
    def chapters(self):    return self.p("chapters.json")
    @property
    def terms(self):       return self.p("terms.json")
    @property
    def quotes(self):      return self.p("quotes.json")
    @property
    def book_meta(self):   return self.p("book_meta.json")
    @property
    def cover(self):       return self.p("cover.png")
    @property
    def book_md(self):     return self.p("book.md")
    @property
    def epub(self):        return self.p("book.epub")
    @property
    def docx(self):        return self.p("book.docx")
    @property
    def audit(self):       return self.p("EBOOK_AUDIT.md")
    @property
    def state(self):       return self.p("state.json")

    # ---- 断点续跑 ----
    def done(self, step: str) -> bool:
        import json
        if not self.state.exists():
            return False
        try:
            return step in json.loads(self.state.read_text(encoding="utf-8")).get("done", [])
        except Exception:
            return False

    def mark(self, step: str):
        import json
        data = {"done": []}
        if self.state.exists():
            try:
                data = json.loads(self.state.read_text(encoding="utf-8"))
            except Exception:
                pass
        d = set(data.get("done", []))
        d.add(step)
        data["done"] = sorted(d)
        self.state.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
