#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 2 · 一层摘要：每片一个独立任务，读完整片 → 写结构化摘要。

  python scripts/02_run_notes.py                     # 全部缺片，并发按 config
  python scripts/02_run_notes.py --only 3,7,12       # 只跑这几片
  python scripts/02_run_notes.py --par 32            # 覆盖并发数
  python scripts/02_run_notes.py --backend command   # 换成命令行后端

一片 = 一个任务，彼此独立：谁失败不影响别人，重跑自动跳过已完成的。
摘要模板在 config/prompts/stage1_note.txt，改那个文件就是改输出格式。
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio, llm      # noqa: E402
from lib.llm import DEFAULTS              # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--only", default=None, help="只跑这些编号，逗号分隔")
    ap.add_argument("--par", type=int, default=None)
    ap.add_argument("--backend", default=None, choices=["openai", "command"])
    ap.add_argument("--force", action="store_true", help="覆盖已有摘要")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = project.load(a.config)
    man = textio.read_json(os.path.join(ROOT, "manifest.json"), None)
    if not man:
        raise SystemExit("先跑 scripts/01_split.py（缺 manifest.json）")

    lcfg = dict(DEFAULTS)
    lcfg.update(cfg.get("llm") or {})
    if a.backend:
        lcfg["backend"] = a.backend
    par = a.par or lcfg["concurrency"]
    backend = llm.build(lcfg)
    notes = cfg["paths"]["notes"]
    os.makedirs(notes, exist_ok=True)

    only = set(int(x) for x in a.only.split(",")) if a.only else None
    jobs = []
    for m in man:
        n = m["chunk"]
        if only and n not in only:
            continue
        cf = os.path.join(cfg["paths"]["chunks"], "chunk_%02d.txt" % n)
        of = os.path.join(notes, "chunk_%02d.md" % n)
        if not os.path.isfile(cf):
            print("跳过 %02d（没有分片文件）" % n)
            continue
        if os.path.isfile(of) and os.path.getsize(of) > 200 and not a.force:
            print("跳过 %02d（已有摘要）" % n)
            continue
        jobs.append((n, {"chunk": cf, "out": of, "meta": m}))

    print("待办 %d 片 ｜ 后端 %s ｜ 并发 %d" % (len(jobs), lcfg["backend"], par))
    if a.dry_run:
        for n, j in jobs:
            print("   %02d  %s" % (n, j["chunk"]))
        return

    def work(n, j):
        body = textio.read_text(j["chunk"])
        m = j["meta"]
        prompt = project.prompt(
            cfg, "stage1_note",
            name=cfg.get("name", ""),
            person="第一人称" if cfg.get("person") == "first" else "第三人称",
            chunk_file=os.path.relpath(j["chunk"], ROOT).replace("\\", "/"),
            chunk_no="%02d" % n,
            h1=m.get("h1") or "", first=m.get("first") or "", last=m.get("last") or "",
            chunk_text=body)
        if lcfg["backend"] == "command":
            out = backend(prompt, chunk_file=j["chunk"], out_file=j["out"])
        else:
            out = backend(prompt)
        if not out or len(out) < 200:
            raise RuntimeError("摘要过短（%d 字）" % len(out or ""))
        textio.write_text(j["out"], out.strip() + "\n")

    llm.run_batch(jobs, work, concurrency=par, label="notes",
                  logdir=os.path.join(cfg["paths"]["logs"], "notes"),
                  retries=lcfg["retries"])
    print("下一步：python scripts/03_merge_notes.py")


if __name__ == "__main__":
    main()
