# -*- coding: utf-8 -*-
"""Phase 2（路 B）：本地 ASR。模型自动下载，带镜像回退与断点续传。"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
from .paths import WorkDir

DEFAULT_REPO = "Systran/faster-whisper-{size}"

def model_home() -> Path:
    """模型缓存目录：多个工作目录 / 多个分 P 共用一份，避免重复下载 460MB。"""
    env = os.environ.get("BBOOK_MODEL_DIR")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "bbook" / "models"
MIRRORS = ["https://hf-mirror.com", "https://huggingface.co"]
MODEL_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]

ZH_PROMPT = ("以下是一段中文讲解视频，可能涉及人工智能、大语言模型、Agent、"
             "编程与工程等领域的术语，请准确转写。")


def ensure_model(model_dir: Path, size: str = "small") -> Path:
    """把模型文件拉到本地目录。不使用 huggingface_hub（实测常失败），直接 HTTP 拉取。"""
    import requests
    model_dir = Path(model_dir)
    if (model_dir / "model.bin").exists() and (model_dir / "config.json").exists():
        return model_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    repo = DEFAULT_REPO.format(size=size)
    env_ep = os.environ.get("HF_ENDPOINT")
    mirrors = ([env_ep] if env_ep else []) + [m for m in MIRRORS if m != env_ep]
    last_err = None
    for ep in mirrors:
        try:
            for fn in MODEL_FILES:
                out = model_dir / fn
                if out.exists() and out.stat().st_size > 0:
                    continue
                url = "%s/%s/resolve/main/%s" % (ep.rstrip("/"), repo, fn)
                t0 = time.time()
                with requests.get(url, stream=True, timeout=60,
                                  headers={"User-Agent": "Mozilla/5.0"}) as r:
                    if r.status_code != 200:
                        raise RuntimeError("%s -> HTTP %s" % (fn, r.status_code))
                    tmp = out.with_suffix(out.suffix + ".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1024 * 512):
                            f.write(chunk)
                    tmp.replace(out)
                print("  %-18s %7.1f MB  %.0fs" % (fn, out.stat().st_size / 1048576,
                                                    time.time() - t0), flush=True)
            return model_dir
        except Exception as e:  # 换镜像重试
            last_err = e
            print("  [warn] 镜像 %s 失败: %s" % (ep, str(e)[:120]), flush=True)
    raise RuntimeError("模型下载失败：%s" % last_err)


def transcribe(wd: WorkDir, audio: Path, size: str = "small", language: str = "zh",
               prompt: str = ZH_PROMPT, threads: int | None = None,
               model_dir: Path | None = None) -> dict:
    from faster_whisper import WhisperModel
    if model_dir:
        model_dir = Path(model_dir)
    else:
        # 优先复用工作目录里的旧副本，否则用全局缓存
        local = wd.p("models", "faster-whisper-%s" % size)
        model_dir = local if (local / "model.bin").exists() else             model_home() / ("faster-whisper-%s" % size)
    ensure_model(model_dir, size)
    threads = threads or max(4, (os.cpu_count() or 8) // 2)
    print("加载模型 %s（%d 线程）..." % (model_dir.name, threads), flush=True)
    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=threads)

    t0 = time.time()
    segs, info = model.transcribe(str(audio), language=language, vad_filter=True,
                                  beam_size=5, initial_prompt=prompt,
                                  condition_on_previous_text=False)
    out, n = [], 0
    for s in segs:
        n += 1
        out.append({"start": round(s.start, 2), "end": round(s.end, 2),
                    "text": s.text.strip()})
        if n % 100 == 0:
            print("  已转写 %d 段 | 用时 %.1f 分钟 | 进度 %.1f/%.1f 分钟"
                  % (n, (time.time() - t0) / 60, s.start / 60, (info.duration or 0) / 60),
                  flush=True)
    wd.asr.write_text(__import__("json").dumps(out, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print("完成：%d 段 / %d 字 / 用时 %.1f 分钟"
          % (n, sum(len(o["text"]) for o in out), (time.time() - t0) / 60), flush=True)
    return {"segments": n, "chars": sum(len(o["text"]) for o in out),
            "duration": info.duration}
