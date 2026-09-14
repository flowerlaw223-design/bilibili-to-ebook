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


# 界面外壳的高频词：浏览器书签栏、Office 菜单、地址栏……录屏共享时 OCR 全是这些
# 只认「Office 功能区 / 浏览器外壳」独有的痕迹。
# 踩过的坑：早先用了"工具/设计/搜索/格式/设置"这类泛词，结果把讲技术方案的
# PPT 整本判成菜单栏（49 张 -> 2 张）。泛词绝不能用来判界面。
UI_WORDS = re.compile(
    r"(另存为|兼容性模式|已保存到|工具箱|页眉|页脚|批注|修订|字数统计|缩放比例|"
    r"默认版式|邮件合并|目录级别|样式窗格|阅读模式|沉浸式阅读)")
# 泛化的菜单词：单独出现说明不了问题（技术 PPT 里也有"工具""设计""格式"），
# 必须配合下一条判据一起用
MENU_WORDS = re.compile(r"(文件|开始|插入|引用|邮件|视图|审阅|帮助|格式|窗口|编辑|"
                        r"工具箱|另存为|批注|页眉|页脚)")
# 虚词密度：真正的句子离不开"的了是在和就也都很"，菜单栏里几乎没有
FUNC_CHARS = re.compile(r"[的了是在和就也都很把被让对与及其这那有为以并而且但]")
URLISH = re.compile(r"(www\.|https?://|\.com|\.cn|\.net|\.org|VPN)", re.I)
# 浏览器书签栏、导航站的品牌名 —— 一屏里堆上三四个就基本可以确定是书签栏
BRANDS = re.compile(
    r"(百度|京东|淘宝|天猫|小红书|知乎|微博|豆瓣|哔哩|bilibili|唯品会|58同城|"
    r"1688|网易|腾讯|新浪|搜狐|贴吧|抖音|快手|美团|携程|去哪儿|12306)", re.I)


def looks_like_ui_chrome(text: str) -> bool:
    """判断这段 OCR 是不是"界面外壳"而不是内容。

    录屏共享时，画面文字最多的那一帧往往就是浏览器书签栏 / Office 菜单栏，
    而我们的选帧又偏爱文字多的帧 —— 结果就是主动挑中垃圾。
    这里判定为外壳的，图注就退化成中性的"视频 XX:XX 处画面"，宁可朴素不要垃圾。
    """
    t = text or ""
    if len(re.findall(r"[\u4e00-\u9fff]", t)) < 4:
        return True                       # 几乎没有中文，多半是菜单/路径
    if URLISH.search(t):
        return True
    if len(BRANDS.findall(t)) >= 3:
        return True                        # 书签栏
    if len(UI_WORDS.findall(t)) >= 3:
        return True                        # Office 功能区专属痕迹
    # 菜单栏特征：一堆菜单词，却没有一句像人话
    if len(MENU_WORDS.findall(t)) >= 3:
        density = len(FUNC_CHARS.findall(t)) / max(1, len(t))
        if density < 0.03:
            return True
    return False


def _grams(text: str, n: int = 4) -> set:
    """句子级指纹：字符 n-gram。

    为什么不用字符集合（1-gram）：滚动文档滚两行，看到的句子全变了，
    但两屏中文共享大量常用字，1-gram 相似度还很高 —— 拦不住"几乎一样的两张图"。
    4-gram 能抓住"同一句话"，实测把相邻图的重复度从"人眼一样"压到 1~2%。
    """
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def _img_sig(path, w: int = 32, h: int = 18):
    """单元格化灰度签名，用于"这两张图长得像不像"。版式相同、文字不同的两屏，
    文字指标量不出来，但像素会很像 —— 这道闸门专治这种情况。"""
    try:
        from PIL import Image
        import numpy as np
        a = np.asarray(Image.open(path).convert("L").resize((w, h)), dtype="float32") / 255.0
        return (a - a.mean()) / (a.std() + 1e-6)
    except Exception:
        return None


def select_representatives(frames_ocr: list[dict], max_sim: float = 0.35,
                           min_chars: int = 8, tail: float = 10.0,
                           window: int = 4, max_img_sim: float = 0.66,
                           frames_dir=None) -> list[dict]:
    """选出"互相不一样"的代表帧：只和**上一张入选图**比，重复度超过 max_sim 就跳过。

    为什么不用"相邻帧聚类"（换页检测）：那是给 PPT 设计的。
    滚动文档只滚两行，句子换了但常用字没变，粗尺子量出来"很不一样"，
    结果就是两张几乎一样的图各占一个位置 —— 读者既看不出区别，又没看到新内容。

    实测（46 分钟 PPT / 36 分钟滚动文档）：相邻入选图重复度中位 1~2%，
    同时每一帧的内容都能被某张入选图覆盖到（不是靠丢帧换来的）。
    """
    chrome = C.detect_chrome(frames_ocr)

    # 图像闸门必须先知道自己这条视频的"视觉基线"：
    # PPT 全场共用一套模板（相邻帧像素相似度中位 96%），滚动文档只有 57%。
    # 用固定阈值必然误伤模板统一的视频（实测把 PPT 那本从 49 张打到 2 张）。
    # 规则：闸门永远不低于本视频自己的基线。
    sigs_eff = {}
    eff_img_sim = max_img_sim
    if frames_dir is not None:
        sigs_all = [_img_sig(Path(frames_dir) / f["file"]) for f in frames_ocr
                    if f.get("file")]
        adj = [float((a * b).mean()) for a, b in zip(sigs_all, sigs_all[1:])
               if a is not None and b is not None]
        if adj:
            adj.sort()
            baseline = adj[len(adj) // 2]
            eff_img_sim = max(max_img_sim, baseline)
            for f, s in zip(frames_ocr, sigs_all):
                sigs_eff[f.get("file")] = s

    picks: list[dict] = []
    recent: list[tuple] = []          # 最近 window 张的 (文字指纹, 图像签名)
    for f in frames_ocr:
        ct = C.clean_slide(f.get("text", ""), chrome)
        if len(ct) < min_chars:
            continue
        if looks_like_ui_chrome(ct):
            continue                       # 界面外壳不是内容，别让它占一个图位
        g = _grams(ct)
        if not g:
            continue
        # 文字闸门：跟最近 window 张都比（只比上一张会漏掉"隔一张的近重复"）
        dup = 0.0
        for pg, _ in recent:
            dup = max(dup, len(g & pg) / max(1, len(g | pg)))
        if recent and dup > max_sim:
            continue
        # 图像闸门：版式相同、文字不同的两屏，靠像素拦
        sig = sigs_eff.get(f.get("file")) if sigs_eff else None
        if sig is not None:
            img_dup = 0.0
            for _, ps in recent:
                if ps is not None:
                    img_dup = max(img_dup, float((sig * ps).mean()))
            if recent and img_dup > eff_img_sim:
                continue
        else:
            img_dup = 0.0
        picks.append({"t0": f["t"], "file": f.get("file"), "text": ct,
                      "title": C.tidy_title(ct), "chars": len(ct),
                      "dup_to_prev": round(dup, 2), "img_dup": round(img_dup, 2)})
        recent.append((g, sig))
        if len(recent) > window:
            recent.pop(0)
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
                "caption": ("图 %d-%d　%s" % (ci, k, s["title"]))
                if not looks_like_ui_chrome(s["title"])
                else ("图 %d-%d　视频 %s 处画面" % (ci, k, "%02d:%02d:%02d" % (hh, mm, ss))),
                "caption_fallback": looks_like_ui_chrome(s["title"]),
                "span": round(s["t1"] - s["t0"], 1),
                "dup_to_prev": s.get("dup_to_prev"),
                "ocr": s["text"][:160],
                "speech": s["speech"][:600],
            })
    return figures


def run(wd: WorkDir, max_per_chapter: int = 12, max_sim: float = 0.35,
        max_img_sim: float = 0.66) -> dict:
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

    slides = select_representatives(frames, max_sim=max_sim, frames_dir=wd.p("frames"),
                                    max_img_sim=max_img_sim)
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
