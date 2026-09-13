# -*- coding: utf-8 -*-
"""bbook —— 命令行入口。

    python -m bbook doctor
    python -m bbook probe  <url>
    python -m bbook run    <url> [--workdir DIR] [--terms terms/ai-coding.json]
    python -m bbook clean  <workdir> --terms terms/ai-coding.json
    python -m bbook build  <workdir>
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

from .paths import WorkDir, tool_report, find_font
from . import fetch as F
from . import text as T
from . import book as B


def _slug(url: str, meta: dict | None = None) -> str:
    if meta and meta.get("id"):
        return re.sub(r"[^A-Za-z0-9_-]", "", str(meta["id"]))
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    return m.group(1) if m else "work"


def cmd_doctor(a):
    print("外部工具：")
    for k, v in tool_report().items():
        print("  %-8s %s" % (k, v or "[X] 未找到"))
    print("中文字体：%s" % (find_font() or "[X] 未找到（封面生成将跳过）"))
    try:
        import faster_whisper  # noqa
        print("faster-whisper：[OK]")
    except ImportError:
        print("faster-whisper：[X] 未安装（pip install faster-whisper）")


def cmd_probe(a):
    wd = WorkDir(a.workdir or Path("work") / _slug(a.url))
    meta = F.probe(wd, a.url, a.cookies)
    print("标题：%s\nUP主：%s\n时长：%s 秒\n分P：%d"
          % (meta["title"], meta["uploader"], meta["duration"], len(meta["parts"])))
    print("授权：%s" % (meta["license"] or "未标注"))
    print("简介前 200 字：\n%s" % meta["description"][:200])


def cmd_cookies(a):
    r = F.check_cookies(a.cookies)
    print("cookie 条数 %s | 登录状态 %s | code=%s | 用户=%s"
          % (r.get("count"), r.get("ok"), r.get("code"), r.get("uname")))
    if not r.get("ok"):
        print("[!] 未登录或已过期：请重新登录 B 站后重新导出 cookie，否则拿不到官方字幕（可改用 ASR）")
    return 0 if r.get("ok") else 2


def cmd_subs(a):
    print(F.list_subs(a.url, a.cookies))


def cmd_audio(a):
    wd = WorkDir(a.workdir or Path("work") / _slug(a.url))
    p = F.download_audio(wd, a.url, a.cookies)
    print("音频：%s (%.1f MB)" % (p, p.stat().st_size / 1048576))


def cmd_asr(a):
    from . import asr as A
    wd = WorkDir(a.workdir)
    files = sorted(wd.p("audio").glob("*"))
    if not files:
        sys.exit("工作目录下没有音频文件，请先运行 audio 阶段")
    A.transcribe(wd, files[0], size=a.model, language=a.lang)


def cmd_frames(a):
    from . import frames as FR
    wd = WorkDir(a.workdir)
    FR.run(wd, url=a.url, interval=a.interval, max_height=a.max_height,
           max_per_chapter=a.per_chapter, min_chars=a.min_chars, cookies=a.cookies)


def cmd_series(a):
    from . import series as S
    wd = WorkDir(a.workdir or Path("work") / (_slug(a.url) + "-series"))
    parts = [int(x) for x in a.parts.split(",")] if a.parts else None
    S.run(wd, a.url, limit=a.limit, parts=parts, cookies=a.cookies,
          terms=Path(a.terms) if a.terms else None, model=a.model,
          frames=not a.no_frames, frame_interval=a.interval, per_chapter=a.per_chapter)
    print("\n构建电子书")
    B.build_markdown(wd)
    B.build_epub(wd)
    B.build_docx(wd)
    B.audit(wd)
    print("产物：%s" % wd.epub)


def cmd_chapters(a):
    from . import chapters as C
    wd = WorkDir(a.workdir)
    C.auto(wd, strategy=a.strategy, minutes=a.minutes)
    if a.build:
        B.build_markdown(wd); B.build_epub(wd); B.build_docx(wd); B.audit(wd)


def cmd_clean(a):
    wd = WorkDir(a.workdir)
    T.run(wd, Path(a.terms) if a.terms else None)


def cmd_build(a):
    wd = WorkDir(a.workdir)
    B.build_markdown(wd)
    B.build_epub(wd)
    B.build_docx(wd)
    res = B.audit(wd)
    print("产物：%s" % wd.epub)
    return 0 if res.get("ok") else 1


def cmd_run(a):
    wd = WorkDir(a.workdir or Path("work") / _slug(a.url))
    print("工作目录：%s" % wd.root)

    if not wd.done("probe"):
        meta = F.probe(wd, a.url, a.cookies)
        wd.mark("probe")
        print("① 元数据：%s（%s 秒）" % (meta["title"], meta["duration"]))
    else:
        meta = json.loads(wd.meta.read_text(encoding="utf-8"))

    subs = []
    if a.cookies and not wd.done("subs"):
        try:
            subs = F.download_subs(wd, a.url, a.cookies)
            wd.mark("subs")
            print("② 官方字幕：%s" % ([p.name for p in subs] or "无"))
        except F.FetchError as e:
            print("② 官方字幕获取失败，转 ASR：%s" % str(e)[:120])

    if not subs and not wd.done("audio"):
        p = F.download_audio(wd, a.url, a.cookies)
        wd.mark("audio")
        print("② 音频：%s (%.1f MB)" % (p.name, p.stat().st_size / 1048576))

    if not wd.asr.exists():
        from . import asr as A
        files = sorted(wd.p("audio").glob("*"))
        print("③ 转写中（本地 CPU，不花钱，请等待）...")
        A.transcribe(wd, files[0], size=a.model, language=a.lang)
    wd.mark("asr")

    print("④ 清洗与术语归正")
    T.run(wd, Path(a.terms) if a.terms else None)
    wd.mark("clean")

    if not a.no_frames and not wd.p("figures.json").exists():
        print("⑤ 抽帧配图")
        from . import frames as FR
        try:
            FR.run(wd, url=a.url, interval=a.interval, per_chapter=a.per_chapter)
        except Exception as e:
            print("  [warn] 配图失败，跳过：%s" % str(e)[:140])

    if not wd.chapters.exists():
        print("⑥ 自动切章")
        from . import chapters as C
        C.auto(wd, strategy=a.chapter_strategy, minutes=a.chapter_minutes)

    print("⑦ 构建电子书")
    B.build_markdown(wd)
    B.build_epub(wd)
    B.build_docx(wd)
    B.audit(wd)
    wd.mark("build")
    print("\n[OK] 完成：%s" % wd.epub)
    print("   章节标题若想改，编辑 %s 后重跑：bbook build %s" % (wd.chapters, wd.root))


def _fix_console_encoding():
    """Windows 控制台默认 GBK，有两个坑：

    1. 打印 emoji 时 GBK 编不出来 → UnicodeEncodeError 直接崩；
    2. 输出被管道/重定向捕获时，若按 GBK 编码，下游（CI、日志、Agent）读到的
       会是乱码。

    策略：交互式控制台保留原编码但把不可编码字符降级为 '?'；
    被重定向/管道时切到 UTF-8，保证下游拿到正确文本。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv=None):
    _fix_console_encoding()
    ap = argparse.ArgumentParser(prog="bbook", description="B 站视频 → 电子书")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.set_defaults(func=fn)
        return p

    add("doctor", cmd_doctor, help="检查本机依赖")

    p = add("probe", cmd_probe, help="Phase 1：取元数据")
    p.add_argument("url"); p.add_argument("--workdir"); p.add_argument("--cookies")

    p = add("cookies", cmd_cookies, help="检测 cookie 是否仍登录")
    p.add_argument("cookies")

    p = add("subs", cmd_subs, help="列出可用字幕轨")
    p.add_argument("url"); p.add_argument("--cookies")

    p = add("audio", cmd_audio, help="只下载音频")
    p.add_argument("url"); p.add_argument("--workdir"); p.add_argument("--cookies")

    p = add("asr", cmd_asr, help="Phase 2：本地转写")
    p.add_argument("workdir"); p.add_argument("--model", default="small"); p.add_argument("--lang", default="zh")

    p = add("frames", cmd_frames, help="Phase 6：抽帧 + OCR + 章节配图")
    p.add_argument("workdir"); p.add_argument("--url")
    p.add_argument("--interval", type=int, default=10, help="抽帧间隔秒数")
    p.add_argument("--max-height", type=int, default=720)
    p.add_argument("--per-chapter", type=int, default=3, help="每章最多几张图")
    p.add_argument("--min-chars", type=int, default=20, help="判定幻灯片的最少字数")
    p.add_argument("--cookies")

    p = add("series", cmd_series, help="多 P / 合集 → 一整本书")
    p.add_argument("url"); p.add_argument("--workdir")
    p.add_argument("--limit", type=int, help="只处理前 N 个分 P")
    p.add_argument("--parts", help="指定分 P，逗号分隔，如 1,3,5")
    p.add_argument("--terms", default="terms/ai-coding.json")
    p.add_argument("--cookies"); p.add_argument("--model", default="small")
    p.add_argument("--no-frames", action="store_true")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--per-chapter", type=int, default=3)

    p = add("chapters", cmd_chapters, help="Phase 4：自动切章（简介时间点 / 幻灯片标题卡 / 时长兜底）")
    p.add_argument("workdir")
    p.add_argument("--strategy", default="auto",
                   choices=["auto", "description", "slides", "time"])
    p.add_argument("--minutes", type=float, default=8.0, help="时长兜底时每章分钟数")
    p.add_argument("--build", action="store_true", help="切完章顺手重建电子书")

    p = add("clean", cmd_clean, help="Phase 3：清洗 + 术语归正")
    p.add_argument("workdir"); p.add_argument("--terms")

    p = add("build", cmd_build, help="Phase 7-8：构建并审计")
    p.add_argument("workdir")

    p = add("run", cmd_run, help="一键跑通全流程")
    p.add_argument("url"); p.add_argument("--workdir"); p.add_argument("--cookies")
    p.add_argument("--terms", default="terms/ai-coding.json")
    p.add_argument("--model", default="small"); p.add_argument("--lang", default="zh")
    p.add_argument("--no-frames", action="store_true", help="跳过抽帧配图")
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--per-chapter", type=int, default=3)
    p.add_argument("--chapter-strategy", default="auto",
                   choices=["auto", "description", "slides", "time"])
    p.add_argument("--chapter-minutes", type=float, default=8.0)

    a = ap.parse_args(argv)
    rc = a.func(a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
