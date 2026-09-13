# -*- coding: utf-8 -*-
"""Phase 1–2：元数据 / 音频 / 字幕 / 弹幕 获取（B 站优先，兼容通用 yt-dlp 站点）。"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from .paths import WorkDir, find_tool

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class FetchError(RuntimeError):
    pass


def _ytdlp(args: list[str], timeout: int = 900) -> str:
    exe = find_tool("yt-dlp")
    if not exe:
        raise FetchError("未找到 yt-dlp，请先安装：pip install yt-dlp")
    cmd = [exe, "--no-warnings", "--user-agent", UA] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if r.returncode != 0:
        raise FetchError((r.stderr or r.stdout or "yt-dlp 失败")[-600:])
    return r.stdout


def probe(wd: WorkDir, url: str, cookies: str | None = None) -> dict:
    """Phase 1：拉元数据（标题/UP/时长/分P/简介）。无需登录。"""
    args = ["--skip-download", "-J"]
    if cookies:
        args += ["--cookies", cookies]
    args.append(url)
    out = _ytdlp(args)
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise FetchError("元数据解析失败：%s" % e)
    slim = {
        "id": data.get("id"), "title": data.get("title"),
        "uploader": data.get("uploader") or data.get("channel"),
        "duration": data.get("duration"), "webpage_url": data.get("webpage_url"),
        "description": data.get("description") or "",
        "license": data.get("license") or "",
        "chapters": data.get("chapters") or [],
        "parts": [{"index": e.get("playlist_index"), "title": e.get("title"),
                   "duration": e.get("duration"), "url": e.get("url")}
                  for e in (data.get("entries") or [])],
    }
    wd.meta.write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
    return slim


def list_subs(url: str, cookies: str | None = None) -> str:
    args = ["--skip-download", "--list-subs"]
    if cookies:
        args += ["--cookies", cookies]
    args.append(url)
    return _ytdlp(args)


def download_subs(wd: WorkDir, url: str, cookies: str | None = None,
                  langs: str = "ai-zh,zh-CN,zh-Hans,zh") -> list[Path]:
    """路 A：登录后取官方 CC / AI 字幕。"""
    args = ["--skip-download", "--write-subs", "--sub-langs", langs,
            "-o", str(wd.p("sub.%(ext)s"))]
    if cookies:
        args += ["--cookies", cookies]
    args.append(url)
    _ytdlp(args)
    return sorted(wd.root.glob("sub.*"))


def download_audio(wd: WorkDir, url: str, cookies: str | None = None,
                   fmt: str = "30280/bestaudio/best") -> Path:
    """路 B 前置：只下音频（体积小、速度快），无需登录。"""
    existing = sorted(wd.p("audio").glob("*"))
    if existing:
        return existing[0]
    args = ["-f", fmt, "-x", "--audio-format", "m4a",
            "-o", str(wd.p("audio", "audio.%(ext)s"))]
    if cookies:
        args += ["--cookies", cookies]
    args.append(url)
    _ytdlp(args)
    files = sorted(wd.p("audio").glob("*"))
    if not files:
        raise FetchError("音频下载失败：未产生文件")
    return files[0]


def download_danmaku(wd: WorkDir, url: str) -> list[Path]:
    """可选信号：弹幕（无需登录），可用于标注观众关注热点。"""
    try:
        _ytdlp(["--skip-download", "--write-subs", "--sub-langs", "danmaku",
                "-o", str(wd.p("danmaku.%(ext)s")), url])
    except FetchError:
        return []
    return sorted(wd.root.glob("danmaku.*"))


def check_cookies(cookies: str) -> dict:
    """检测 cookie 是否仍然登录有效（B 站 nav 接口）。"""
    import http.cookiejar, urllib.request
    jar = http.cookiejar.MozillaCookieJar(cookies)
    jar.load(ignore_discard=True, ignore_expires=True)
    req = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        d = json.load(opener.open(req, timeout=20))
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200], "count": len(jar)}
    return {"ok": bool(d.get("data", {}).get("isLogin")), "code": d.get("code"),
            "uname": d.get("data", {}).get("uname"), "count": len(jar)}
