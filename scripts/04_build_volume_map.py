#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 · 建卷映射：按 h2 把全文切成 volumes/vol_NN.txt，并记下每卷对应哪些分片。

  python scripts/04_build_volume_map.py

为什么要单独切一遍：一层摘要按 6 万字切，二层的单位是「卷/章」，
两者不对齐。这里用 sections.json 的字符偏移精确切卷，再回查它落在哪些分片里，
二层任务才知道该读哪几份摘要。

产出：
  volumes/vol_NN.txt   每个 h2 一段独立文本
  volume_map.json      [{i, h1, h2, chars, file, chunks:[...]}]
"""
import os
import re
import sys
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--range", type=int, default=None, help="只用前 N 卷（先跑通再全量）")
    a = ap.parse_args()

    cfg = project.load(a.config)
    raw = textio.read_text(os.path.join(cfg["paths"]["raw"], "_all.txt"))
    secs = textio.read_json(os.path.join(cfg["paths"]["raw"], "sections.json"), []) or []
    if not secs:
        raise SystemExit("缺 raw/sections.json，先跑 scripts/00_extract.py")

    # 偏移校验：sections.json 的 offset 必须能在正文里对上标题
    ok = 0
    for h in secs[:50]:
        seg = raw[h["offset"]:h["offset"] + len(h["title"]) + 6]
        if h["title"][:6] in seg:
            ok += 1
    print("偏移校验：%d / %d" % (ok, len(secs[:50])))

    chunk_text = {}
    for f in sorted(glob.glob(os.path.join(cfg["paths"]["chunks"], "chunk_*.txt"))):
        m = re.search(r"chunk_(\d+)", f)
        if m:
            chunk_text[int(m.group(1))] = textio.read_text(f)

    outdir = cfg["paths"]["volumes"]
    os.makedirs(outdir, exist_ok=True)
    h2s = [h for h in secs if h["level"] == 2]
    if not h2s:                       # 没识别出章节层级：退回用 h3
        h2s = [h for h in secs if h["level"] == 3]
        print("警告：没有 h2 标题，改用 h3（%d 个）" % len(h2s))
    if not h2s:
        raise SystemExit("sections.json 里没有任何章节标题，检查 Stage 0 的标题识别")

    if a.range:
        h2s = h2s[:a.range]

    vols = []
    for i, h in enumerate(h2s):
        if h.get("offset") is None:
            continue
        start = h["offset"]
        end = h2s[i + 1]["offset"] if i + 1 < len(h2s) else len(raw)
        for hh in secs:               # 不跨 h1 版块
            if hh["level"] == 1 and start < hh["offset"] < end:
                end = hh["offset"]
        body = raw[start:end].strip() + "\n"
        fn = "vol_%02d.txt" % (i + 1)
        textio.write_text(os.path.join(outdir, fn), body)
        ch = [n for n, t in chunk_text.items() if h["title"] in t]
        vols.append({"i": i + 1, "h1": h.get("h1", ""), "h2": h["title"],
                     "chars": len(body), "file": "volumes/" + fn, "chunks": ch})

    textio.write_json(os.path.join(ROOT, "volume_map.json"), vols)
    print("卷数：%d ｜ 合计 %d 字" % (len(vols), sum(v["chars"] for v in vols)))
    for v in vols:
        print("%3d  %-10s %-34s %6d  %s" % (
            v["i"], (v["h1"] or "")[:10], v["h2"][:34], v["chars"], v["file"]))
    print("→ volume_map.json")
    print("下一步：python scripts/05_run_volumes.py")


if __name__ == "__main__":
    main()
