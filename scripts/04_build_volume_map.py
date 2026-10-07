#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 · 建卷映射：按 h2 把全文切成 volumes/vol_NN.txt，并记下每卷对应哪些分片。

  python scripts/04_build_volume_map.py

为什么要单独切一遍：一层摘要按 6 万字切，二层的单位是「卷/章」，
两者不对齐。这里用 sections.json 的字符偏移精确切卷，再用 manifest.json 里
每片的字符区间（start / end）求交集，算出每卷落在哪些分片里，
二层任务才知道该读哪几份摘要。

只看偏移、不看标题字符串：各卷章节重新编号（每卷都有「第一章」）、
一卷跨好几片（标题只出现在第一片）都不会映射错。

产出：
  volumes/vol_NN.txt   每个 h2 一段独立文本
  volume_map.json      [{i, h1, h2, start, end, chars, file, chunks:[...]}]
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio      # noqa: E402


def chunk_spans(raw, man):
    """[(片号, start, end)]：每片在 _all.txt 里的字符区间。

    新版 manifest 直接带 start/end；旧版没有，就按 01_split 的同一套规则
    （parse_units + 每片 units 个数）重放一遍。对不上返回 None。
    """
    if man and all(isinstance(m.get("start"), int) and isinstance(m.get("end"), int)
                   for m in man):
        return [(m["chunk"], m["start"], m["end"]) for m in man]
    units = [u for u in textio.parse_units(raw) if "\n".join(u["lines"]).strip()]
    spans, k = [], 0
    for m in man:
        n = int(m.get("units") or 0)
        if n <= 0 or k + n > len(units):
            return None
        first, last = units[k], units[k + n - 1]
        if (m.get("first") is not None and first["title"] != m["first"]) or \
                (m.get("last") is not None and last["title"] != m["last"]):
            return None
        spans.append((m["chunk"], first["start"], last["end"]))
        k += n
    return spans if k == len(units) else None


def content_range(raw, start, end):
    """去掉首尾空白后的区间。sections.json 的偏移可能指向标题前的换行，
    两边都收紧到实际文字再求交集，差一个字符也不会误判相邻片。"""
    seg = raw[start:end]
    s = start + (len(seg) - len(seg.lstrip()))
    e = start + len(seg.rstrip())
    return s, max(s, e)


def overlapping_chunks(raw, start, end, spans):
    vs, ve = content_range(raw, start, end)
    out = []
    for n, cs, ce in spans:
        cs, ce = content_range(raw, cs, ce)
        if min(ve, ce) > max(vs, cs):
            out.append(n)
    return out


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

    man = textio.read_json(project.artifact(cfg, "manifest.json"), None)
    if not man:
        raise SystemExit("缺 work/manifest.json，先跑 scripts/01_split.py")
    spans = chunk_spans(raw, man)
    if spans is None:
        raise SystemExit("manifest.json 和 raw/_all.txt 对不上（抽文本后没重新分片？）"
                         "\n重跑 scripts/01_split.py 再来")

    outdir = cfg["paths"]["volumes"]
    os.makedirs(outdir, exist_ok=True)

    def heads(level):
        return sorted((h for h in secs if h.get("level") == level
                       and isinstance(h.get("offset"), int)), key=lambda h: h["offset"])

    h2s = heads(2)
    if not h2s:                       # 没识别出章节层级：退回用 h3
        h2s = heads(3)
        print("警告：没有 h2 标题，改用 h3（%d 个）" % len(h2s))
    if not h2s:
        raise SystemExit("sections.json 里没有任何章节标题，检查 Stage 0 的标题识别")
    h1_offsets = [h["offset"] for h in heads(1)]

    # 结束位置要按全部卷算，--range 只是少写几卷，不能让最后一卷吞掉后文
    bounds = []
    for k, h in enumerate(h2s):
        start = h["offset"]
        end = h2s[k + 1]["offset"] if k + 1 < len(h2s) else len(raw)
        for o in h1_offsets:          # 不跨 h1 版块
            if start < o < end:
                end = o
        bounds.append((h, start, end))
    if a.range:
        bounds = bounds[:a.range]

    vols = []
    for i, (h, start, end) in enumerate(bounds, 1):
        body = raw[start:end].strip() + "\n"
        fn = "vol_%02d.txt" % i
        textio.write_text(os.path.join(outdir, fn), body)
        vols.append({"i": i, "h1": h.get("h1", ""), "h2": h["title"],
                     "start": start, "end": end, "chars": len(body),
                     "file": "volumes/" + fn,
                     "chunks": overlapping_chunks(raw, start, end, spans)})

    textio.write_json(project.artifact(cfg, "volume_map.json"), vols)
    print("卷数：%d ｜ 合计 %d 字" % (len(vols), sum(v["chars"] for v in vols)))
    for v in vols:
        print("%3d  %-10s %-34s %6d  %s  片 %s" % (
            v["i"], (v["h1"] or "")[:10], v["h2"][:34], v["chars"], v["file"],
            ",".join(str(n) for n in v["chunks"]) or "—"))
    empty = [v["i"] for v in vols if not v["chunks"]]
    if empty:
        print("警告：%d 卷没有落进任何分片：%s" % (len(empty), ",".join(map(str, empty))))
    if not a.range:
        hit = {n for v in vols for n in v["chunks"]}
        orphan = [n for n, _, _ in spans if n not in hit]
        if orphan:
            print("提示：%d 片不属于任何卷（第一个 %s 之前的前言等）：%s" % (
                len(orphan), "h2" if heads(2) else "h3", ",".join(map(str, orphan))))
    print("→ work/volume_map.json")
    print("下一步：python scripts/05_run_volumes.py")


if __name__ == "__main__":
    main()
