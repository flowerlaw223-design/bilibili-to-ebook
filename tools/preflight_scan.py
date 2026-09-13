#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight_scan.py —— 发布前安全检查：防止 cookie / 凭据 / 大文件 / 版权风险内容被 git 带走

用法:
    python preflight_scan.py <要检查的目录> [--max-mb 5]

退出码: 0 = 通过, 1 = 发现阻断项
"""
import os, re, sys, argparse

NAME_PAT = re.compile(
    r'(cookie|credential|secret|tokens?(?![a-z])|password|passwd|\.env|\.pem|\.key$|'
    r'login data|trust tokens|id_rsa|\.netrc|\.npmrc|\.pypirc|serviceaccount)',
    re.I)
# 要求"键 = 值"形态，避免文档里提到 SESSDATA 这类词造成误报
SECRET_PAT = re.compile(
    r'((SESSDATA|bili_jct|DedeUserID|buvid3)\s*[=:]\s*["\x27]?[A-Za-z0-9%_,\-]{12,}'
    r'|gho_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}'
    r'|sk-[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16}'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
    r'|xox[baprs]-[A-Za-z0-9-]{10,}'
    r'|AIza[0-9A-Za-z\-_]{33,})')
RISK_DIR = re.compile(r'(chrome_|chrome_cap|cookies_work|cookies_copy|User Data|'
                      r'node_modules|\.venv|__pycache__|\.git$)', re.I)
COPYRIGHT_HINT = re.compile(r'(geekbang|极客时间|付费专栏|专栏导出|课程逐字稿|题库|\bexam\b|试卷|内部资料|付费课程)', re.I)
CODE_EXT = {'.py', '.js', '.ts', '.ps1', '.sh', '.bat', '.java', '.go', '.rs', '.c', '.cpp'}
TEXT_EXT = {'.txt', '.md', '.json', '.py', '.ps1', '.js', '.ts', '.yaml', '.yml',
            '.toml', '.ini', '.cfg', '.csv', '.html', '.xml', '.env', '.sh', '.bat'}
SKIP_EXT = {'.mp4', '.m4a', '.mp3', '.zip', '.exe', '.dll', '.so', '.wasm',
            '.node', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bin', '.onnx', '.tflite'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--max-mb', type=float, default=5.0)
    a = ap.parse_args()

    blocking, warnings = [], []
    n_files = n_bytes = 0
    limit = a.max_mb * 1024 * 1024

    root_abs = os.path.abspath(a.root)
    # 预先读取 .gitignore：已被忽略的目录不该再报阻断
    ignored = set()
    gi = os.path.join(root_abs, '.gitignore')
    if os.path.exists(gi):
        for ln in open(gi, encoding='utf-8', errors='ignore'):
            ln = ln.strip().rstrip('/')
            if ln and not ln.startswith('#'):
                ignored.add(ln)

    for dirpath, dirnames, filenames in os.walk(a.root):
        base = os.path.basename(dirpath)
        # 整个目录若已被 .gitignore 覆盖，直接跳过（它根本不会进仓库）
        if base in ignored and os.path.dirname(os.path.abspath(dirpath)) == root_abs:
            dirnames[:] = []
            continue
        if RISK_DIR.search(base):
            # 已被 .gitignore 覆盖，或位于扫描根目录自身 —— 都只提示不阻断；
            # 出现在子目录里且未被忽略，才说明有问题（嵌套仓库、忘删缓存）。
            at_root = (os.path.dirname(os.path.abspath(dirpath)) == root_abs
                       or base in ignored)
            (warnings if at_root else blocking).append(
                ('敏感目录', dirpath,
                 '已被 .gitignore 忽略或属根目录自身，不阻断' if at_root else '含登录态/依赖，禁止提交'))
            dirnames[:] = []
            continue
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            n_files += 1
            n_bytes += size
            if NAME_PAT.search(fn):
                ext0 = os.path.splitext(fn)[1].lower()
                if ext0 in CODE_EXT:
                    warnings.append(('代码含敏感词', fp, '%d B' % size))
                else:
                    blocking.append(('凭据文件', fp, '%d B' % size))
            if size > limit:
                warnings.append(('大文件', fp, '%.1f MB' % (size / 1048576)))
            ext = os.path.splitext(fn)[1].lower()
            if fn == os.path.basename(__file__):      # 扫描器自身含关键词，跳过自检
                continue
            if size <= 2 * 1048576 and ext in TEXT_EXT and ext not in SKIP_EXT:
                try:
                    txt = open(fp, encoding='utf-8', errors='ignore').read()
                except OSError:
                    continue
                m = SECRET_PAT.search(txt)
                if m:
                    blocking.append(('疑似明文凭据', fp, '命中: %s' % m.group(0)[:24]))
                # 降低噪声：正文里反复出现，或文件本身足够大，才判定为版权风险
                n_hint = len(COPYRIGHT_HINT.findall(txt[:4000]))
                if COPYRIGHT_HINT.search(fn) or n_hint >= 3 or (n_hint >= 1 and size > 20000):
                    warnings.append(('版权风险', fp, '疑似付费/受版权保护内容（命中 %d 次），确认后再决定' % n_hint))

    def dump(title, rows):
        print('\n== %s (%d) ==' % (title, len(rows)))
        for kind, fp, extra in rows[:40]:
            print('  [%s] %s  %s' % (kind, fp, extra))
        if len(rows) > 40:
            print('  ... 其余 %d 条省略' % (len(rows) - 40))

    print('扫描目录: %s' % a.root)
    print('文件数: %d   合计: %.2f GB' % (n_files, n_bytes / 1073741824))
    dump('阻断项（必须先处理）', blocking)
    dump('警告项（人工确认）', warnings)
    print('\n结论: %s' % ('❌ 不通过，禁止提交' if blocking else '✅ 通过'))
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
