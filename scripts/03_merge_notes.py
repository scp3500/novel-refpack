#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3 · 汇总：notes/chunk_NN.md → all_notes.md，并做覆盖率校验。

  python scripts/03_merge_notes.py            # 合并 + 校验
  python scripts/03_merge_notes.py --check    # 只校验，不写文件

覆盖率校验做两件事：
  1. 片数是否齐全（缺片 = 剧情开天窗）；
  2. 每片摘要是否覆盖到片尾 —— 抽样比对分片文件最后几行的特征串，
     摘要里一个字都没提到就标 WARN（模型跳读的信号）。
"""
import os
import re
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio      # noqa: E402


def tail_keys(chunk_text, k=6):
    """取分片最后若干行的特征串（人名/名词），用于覆盖检查。"""
    lines = [l.strip() for l in chunk_text.split("\n") if len(l.strip()) > 12]
    keys = []
    for l in lines[-k:]:
        for w in re.findall(r"[\u4e00-\u9fff]{2,4}", l):
            if w not in ("说道", "什么", "这个", "那个", "就是", "但是", "然后", "自己", "已经"):
                keys.append(w)
    return list(dict.fromkeys(keys))[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    cfg = project.load(a.config)
    notes = cfg["paths"]["notes"]
    chunks = cfg["paths"]["chunks"]
    man = textio.read_json(project.artifact(cfg, "manifest.json"), []) or []

    parts, missing, warns = [], [], []
    for m in man:
        n = m["chunk"]
        nf = os.path.join(notes, "chunk_%02d.md" % n)
        cf = os.path.join(chunks, "chunk_%02d.txt" % n)
        if not os.path.isfile(nf):
            missing.append(n)
            continue
        note = textio.read_text(nf)
        parts.append("## 分片 %02d（%s → %s ｜ %d 字）\n\n%s\n" % (
            n, m.get("first") or "", m.get("last") or "", m.get("chars") or 0, note.strip()))
        if os.path.isfile(cf):
            ct = textio.read_text(cf)
            keys = tail_keys(ct)
            hit = sum(1 for k in keys if k in note)
            if keys and hit < max(1, len(keys) // 4):
                warns.append((n, keys[:6], hit))

    total = sum(len(p) for p in parts)
    print("分片 %d ｜ 已有摘要 %d ｜ 缺失 %d ｜ 合计 %d 字" % (len(man), len(parts), len(missing), total))
    if missing:
        print("缺片：%s" % "、".join("%02d" % n for n in missing))
        print("补跑：python scripts/02_run_notes.py --only %s" % ",".join(str(n) for n in missing))
    if warns:
        print("片尾覆盖可疑（可能没读到底）：")
        for n, keys, hit in warns:
            print("   分片 %02d  命中 %d/%d  片尾关键词：%s" % (n, hit, len(keys), "、".join(keys)))
    else:
        print("片尾覆盖检查：通过")

    if a.check:
        return
    header = ("# %s · 分片总摘要\n\n"
              "> 由 %d 份分片摘要合并，事实来源。生成成品时只取其中的剧情事件，"
              "元文本（编者前言、制作信息、作者设定草案）请勿混入。\n\n" % (
                  cfg.get("name", ""), len(parts)))
    out = a.out or project.artifact(cfg, "all_notes.md")
    textio.write_text(out, header + "\n\n".join(parts) + "\n")
    print("→ %s" % out)
    print("下一步：python scripts/04_build_volume_map.py")


if __name__ == "__main__":
    main()
