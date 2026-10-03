#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 · 分片：raw/_all.txt → chunks/chunk_NN.txt + manifest.json

  python scripts/01_split.py                # 默认 60000 字/片（读 config）
  python scripts/01_split.py --target 40000

规则：以 h2/h3 为最小切点，满一片就切；不跨 h1 版块。
manifest 记每片的起止标题、字数、所属 h1，后面所有脚本都靠它定位。
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--target", type=int, default=None)
    a = ap.parse_args()

    cfg = project.load(a.config)
    target = a.target or cfg.get("chunk_chars") or 60000
    src = os.path.join(cfg["paths"]["raw"], "_all.txt")
    if not os.path.isfile(src):
        raise SystemExit("先跑 scripts/00_extract.py（缺 %s）" % src)
    outdir = cfg["paths"]["chunks"]
    os.makedirs(outdir, exist_ok=True)

    text = textio.read_text(src)
    units = textio.parse_units(text)

    state = {"buf": [], "h1": None, "first": None, "last": None, "n": 0, "len": 0}
    man = []

    def flush():
        if not state["buf"]:
            return
        body = "\n".join(state["buf"]).strip() + "\n"
        idx = len(man) + 1
        textio.write_text(os.path.join(outdir, "chunk_%02d.txt" % idx), body)
        man.append({"chunk": idx, "chars": len(body), "h1": state["h1"],
                    "first": state["first"], "last": state["last"],
                    "units": state["n"]})
        state.update(buf=[], h1=None, first=None, last=None, n=0, len=0)

    for u in units:
        seg = "\n".join(u["lines"]).strip()
        if not seg:
            continue
        if state["h1"] is not None and u["h1"] != state["h1"]:
            flush()
        if state["len"] and state["len"] + len(seg) > target:
            flush()
        if not state["buf"]:
            state["h1"] = u["h1"]
            state["first"] = u["title"]
        state["buf"].append(seg)
        state["len"] += len(seg) + 1
        state["n"] += 1
        state["last"] = u["title"]
    flush()

    textio.write_json(project.artifact(cfg, "manifest.json"), man)
    print("分片：%d 片 ｜ 合计 %d 字 ｜ 目标 %d 字/片" % (
        len(man), sum(m["chars"] for m in man), target))
    for m in man:
        print("%3d  %6d  %-10s | %-34s | %s" % (
            m["chunk"], m["chars"], (m["h1"] or "")[:10],
            (m["first"] or "")[:34], (m["last"] or "")[:30]))
    print("→ work/manifest.json")
    print("下一步：python scripts/02_run_notes.py")


if __name__ == "__main__":
    main()
