#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 7 · 文风索引：调 stylefit/build_index.py，参数从 config 补全。

  python scripts/07_stylefit_index.py
  python scripts/07_stylefit_index.py --no-attrib      # 不用归属文件，纯自动抓

产出 cache/<name>/index.json：人物×功能台词、描写意图、搭配表、用词表、
零频黑名单、场景词典、场景片段、统计靶。
"""
import os
import sys
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-attrib", action="store_true")
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--extra", default="", help="额外参数，原样传给 build_index.py")
    a = ap.parse_args()

    cfg = project.load(a.config)
    name = cfg.get("name") or "book"
    corpus = a.corpus or cfg["paths"]["chunks"]
    out = a.out or os.path.join(cfg["paths"]["cache"], name)
    attrib = project.artifact(cfg, "attrib.json")
    if a.no_attrib or not os.path.isfile(attrib):
        attrib = ""
    names = ",".join(cfg.get("names") or [])

    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "build_index.py"),
           "--corpus", corpus, "--out", out, "--names", names,
           "--config", os.path.join(ROOT, "config", "stylefit")]
    if attrib:
        cmd += ["--attrib", attrib]
    if a.extra:
        cmd += a.extra.split()

    print("$ %s" % " ".join(cmd))
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
