#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 11 · 验收：调 stylefit/verify.py，语料与缓存路径从 config 补全。

  python scripts/11_verify.py --text 我的稿子.txt
  python scripts/11_verify.py --text 我的稿子.txt --ref-pattern '(猫|尾巴|摸头)'

判据（看 docs/PITFALLS.md）：
  门槛层 全部落在同类参考段范围内
  逐句 z 台词与叙述都落在 ±0.3（越接近 0 越像）
  0 频探针 倍数 ≤ 1.05
"""
import os
import sys
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project      # noqa: E402


def main():
    argv = sys.argv[1:]
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--config", default=None)
    ap.add_argument("--corpus", default=None)
    yes, rest = ap.parse_known_args(argv)
    if not any(x == "--text" or x.startswith("--text=") for x in rest):
        argv = ["--help"]

    cfg = project.load(yes.config)
    corpus = yes.corpus or cfg["paths"]["chunks"]
    out = os.path.join(cfg["paths"]["cache"], cfg.get("name") or "book")

    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "verify.py"),
           "--corpus", corpus, "--out", out] + rest
    if argv == ["--help"]:
        cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "verify.py"), "--help"]
    print("$ %s" % " ".join(cmd))
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
