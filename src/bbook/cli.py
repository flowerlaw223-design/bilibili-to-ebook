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
        print("  %-8s %s" % (k, v or "❌ 未找到"))
    print("中文字体：%s" % (find_font() or "❌ 未找到（封面生成将跳过）"))
    try:
        import faster_whisper  # noqa
        print("faster-whisper：✅")
    except ImportError:
        print("faster-whisper：❌ 未安装（pip install faster-whisper）")


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
        print("⚠️ 未登录或已过期：请重新登录 B 站后重新导出 cookie，否则拿不到官方字幕（可改用 ASR）")
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

    if wd.chapters.exists():
        print("⑤ 构建电子书")
        B.build_markdown(wd)
        B.build_epub(wd)
        B.build_docx(wd)
        B.audit(wd)
        wd.mark("build")
        print("\n✅ 完成：%s" % wd.epub)
    else:
        print("\n⚠️ 缺少 %s —— 章节划分需要人工/LLM 决策，请填写后重跑 build。" % wd.chapters)
        print("   模板：见 examples/chapters.example.json")


def main(argv=None):
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

    p = add("clean", cmd_clean, help="Phase 3：清洗 + 术语归正")
    p.add_argument("workdir"); p.add_argument("--terms")

    p = add("build", cmd_build, help="Phase 7-8：构建并审计")
    p.add_argument("workdir")

    p = add("run", cmd_run, help="一键跑通全流程")
    p.add_argument("url"); p.add_argument("--workdir"); p.add_argument("--cookies")
    p.add_argument("--terms", default="terms/ai-coding.json")
    p.add_argument("--model", default="small"); p.add_argument("--lang", default="zh")

    a = ap.parse_args(argv)
    rc = a.func(a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
