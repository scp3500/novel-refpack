#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 11 · 验收：调 stylefit/verify.py，语料与缓存路径从 config 补全。

  python scripts/11_verify.py --text 我的稿子.txt
  python scripts/11_verify.py --text 我的稿子.txt --ref-pattern '(猫|尾巴|摸头)'
  python scripts/11_verify.py --prewarm
  python scripts/11_verify.py --diff v1.txt v2.txt
  python scripts/11_verify.py --text 我的稿子.txt --json --guide out/guide.md --html out/report.html

判据（看 docs/PITFALLS.md）：
  Layer 0  无异常脚本、零频词与照抄片段
  门槛层   全部落在同类参考段范围内（长稿 >800 字查尺度不变项 + 滑窗）
  逐句 z   台词与叙述都落在 ±0.3（越接近 0 越像）
  0 频探针 倍数 ≤ 1.05
"""
import os
import sys
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project      # noqa: E402
from lib import textio       # noqa: E402


def _has_flag(args, flag):
    return any(x == flag or x.startswith(flag + "=") for x in args)


def _is_stdout_json(args):
    for i, x in enumerate(args):
        if x == "--json=-":
            return True
        if x == "--json":
            if i + 1 >= len(args) or args[i + 1].startswith("-") or args[i + 1] == "-":
                return True
    return False


def _inject_default_log_history(args, default_path):
    """若用户传了不带路径的 --log-history，则自动补全为 work/logs/verify_history.jsonl。"""
    out = []
    i = 0
    n = len(args)
    while i < n:
        x = args[i]
        out.append(x)
        if x == "--log-history":
            if i + 1 >= n or args[i + 1].startswith("-"):
                out.append(default_path)
        i += 1
    return out


def main():
    textio.ensure_utf8_stdio()
    argv = sys.argv[1:]
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--config", default=None)
    ap.add_argument("--corpus", default=None)
    yes, rest = ap.parse_known_args(argv)

    want_help = (
        "-h" in rest
        or "--help" in rest
        or not (
            _has_flag(rest, "--text")
            or _has_flag(rest, "--prewarm")
            or _has_flag(rest, "--diff")
        )
    )
    if want_help:
        cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "verify.py"), "--help"]
        print("$ %s" % " ".join(cmd))
        sys.exit(subprocess.call(cmd))

    cfg = project.load(yes.config)
    corpus = yes.corpus or cfg["paths"]["chunks"]
    out = os.path.join(cfg["paths"]["cache"], cfg.get("name") or "book")

    extra = list(rest)
    # 若未显式传 --examples 且不是 --prewarm，则自动探测 work/out/例子.txt
    if not _has_flag(extra, "--prewarm") and not _has_flag(extra, "--examples"):
        default_examples = os.path.join(cfg["paths"]["out"], "例子.txt")
        if os.path.isfile(default_examples):
            extra += ["--examples", default_examples]

    # 若传了裸 --log-history，默认落盘到 cfg["paths"]["logs"]/verify_history.jsonl
    default_hist = os.path.join(cfg["paths"]["logs"], "verify_history.jsonl")
    extra = _inject_default_log_history(extra, default_hist)

    cmd = [
        sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "verify.py"),
        "--corpus", corpus, "--out", out,
    ] + extra

    # 纯 JSON 输出到 stdout 时，命令回显改走 stderr，避免破坏管道 JSON 解析
    banner = "$ %s" % " ".join(cmd)
    if _is_stdout_json(extra):
        sys.stderr.write(banner + "\n")
    else:
        print(banner)
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
