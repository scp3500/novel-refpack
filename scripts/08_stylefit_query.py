#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 8 · 查索引：把 stylefit/query.py 的 --index 用 config 自动补上。

  python scripts/08_stylefit_query.py --list
  python scripts/08_stylefit_query.py --stats
  python scripts/08_stylefit_query.py --who 白夜 --func 让步接受
  python scripts/08_stylefit_query.py --colloc 耳朵的动作
  python scripts/08_stylefit_query.py --zero

写正文之前先查这个。凡是「这个动作该配哪个动词」「这个人这种处境会说什么」，
答案都在书里，不在你的语感里。
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
    ap.add_argument("--index", default=None)
    known, rest = ap.parse_known_args(argv)

    cfg = project.load(known.config)
    idx = known.index or os.path.join(cfg["paths"]["cache"],
                                      cfg.get("name") or "book", "index.json")
    if not os.path.isfile(idx):
        raise SystemExit("没有索引：%s\n先跑 scripts/07_stylefit_index.py" % idx)

    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "query.py"),
           "--index", idx] + rest
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
