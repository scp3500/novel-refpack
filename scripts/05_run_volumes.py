#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 · 二层归纳：把分片摘要合并成「每卷纪要」。可选跑元章节。

  python scripts/05_run_volumes.py            # 每卷一个任务 → notes/vol/vol_NN.md
  python scripts/05_run_volumes.py --only 3,5
  python scripts/05_run_volumes.py --meta     # 世界观 / 角色 / 势力 / 结局 / 伏笔 / 定位
  python scripts/05_run_volumes.py --meta --only characters

每个任务只读这一卷的几份分片摘要（4-6k token），不读原文——
单卷原文 7-13 万字，输入 45k-132k token，既贵又没必要。
"""
import os
import sys
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio, llm      # noqa: E402
from lib.llm import DEFAULTS              # noqa: E402


def build_volume_jobs(cfg):
    vmap = textio.read_json(os.path.join(ROOT, "volume_map.json"), None)
    if not vmap:
        raise SystemExit("先跑 scripts/04_build_volume_map.py（缺 volume_map.json）")
    notes = cfg["paths"]["notes"]
    outdir = os.path.join(notes, "vol")
    jobs = []
    for v in vmap:
        of = os.path.join(outdir, "vol_%02d.md" % v["i"])
        # 该卷命中的分片摘要；命中为空就取区间内的分片
        nums = v.get("chunks") or []
        if not nums:
            nums = list(range(max(1, v["i"] * 3 - 2), v["i"] * 3 + 1))
        files = [os.path.join(notes, "chunk_%02d.md" % n) for n in nums]
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            print("跳过 vol_%02d（没有对应摘要）" % v["i"])
            continue
        label = ("%s %s" % (v.get("h1") or "", v["h2"])).strip()
        jobs.append((v["i"], {"out": of, "files": files, "label": label,
                              "chars": sum(os.path.getsize(f) for f in files)}))
    return jobs


def build_meta_jobs(cfg):
    adir = os.path.join(ROOT, "config", "prompts")
    names = [os.path.basename(f)[:-4] for f in sorted(glob.glob(os.path.join(adir, "meta_*.txt")))]
    outdir = os.path.join(cfg["paths"]["notes"], "meta")
    jobs = []
    for n in names:
        jobs.append((n, {"out": os.path.join(outdir, n + ".md"),
                         "prompt": n, "label": n.replace("meta_", "")}))
    return jobs


def digest(cfg, limit=60000):
    """给元章节任务用的压缩材料：优先用每卷纪要的剧情/状态两节，其次用总摘要。"""
    vol = sorted(glob.glob(os.path.join(cfg["paths"]["notes"], "vol", "*.md")))
    src = []
    if vol:
        for f in vol:
            t = textio.read_text(f)
            keep = []
            grab = False
            for ln in t.split("\n"):
                if ln.startswith("## "):
                    grab = any(k in ln for k in ("剧情纪要", "状态快照", "登场人物", "名场面"))
                if grab:
                    keep.append(ln)
            src.append("### %s\n%s" % (os.path.basename(f), "\n".join(keep[:80])))
    else:
        src = [textio.read_text(os.path.join(ROOT, "all_notes.md"))]
    text = "\n\n".join(src)
    if len(text) > limit:
        text = text[:limit] + "\n\n…（后略）"
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--par", type=int, default=None)
    ap.add_argument("--backend", default=None, choices=["openai", "command"])
    ap.add_argument("--meta", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = project.load(a.config)
    lcfg = dict(DEFAULTS)
    lcfg.update(cfg.get("llm") or {})
    if a.backend:
        lcfg["backend"] = a.backend
    par = a.par or lcfg["concurrency"]
    backend = llm.build(lcfg)

    only = set(a.only.split(",")) if a.only else None
    jobs = build_meta_jobs(cfg) if a.meta else build_volume_jobs(cfg)
    if only:
        jobs = [j for j in jobs if str(j[0]) in only]
    if not a.force:
        jobs = [j for j in jobs if not (os.path.isfile(j[1]["out"])
                                        and os.path.getsize(j[1]["out"]) > 300)]
    print("待办 %d ｜ 模式 %s ｜ 并发 %d" % (len(jobs), "meta" if a.meta else "volumes", par))
    if a.dry_run:
        for k, j in jobs:
            print("   %s  %s" % (k, j["out"]))
        return

    unit = cfg.get("vol_unit_word") or "卷"
    dg = digest(cfg) if a.meta else None

    def work(k, j):
        if a.meta:
            prompt = project.prompt(cfg, j["prompt"], name=cfg.get("name", ""),
                                    material=dg)
        else:
            body = "\n\n".join(
                "--- %s ---\n%s" % (os.path.basename(f), textio.read_text(f)[:9000])
                for f in j["files"])
            prompt = project.prompt(cfg, "stage2_volume", name=cfg.get("name", ""),
                                    unit=unit, label=j["label"], notes=body)
        out = backend(prompt, out_file=j["out"]) if lcfg["backend"] == "command" \
            else backend(prompt)
        if not out or len(out) < 300:
            raise RuntimeError("纪要过短（%d 字）" % len(out or ""))
        textio.write_text(j["out"], out.strip() + "\n")

    llm.run_batch(jobs, work, concurrency=par, label="meta" if a.meta else "vol",
                  logdir=os.path.join(cfg["paths"]["logs"], "vol"),
                  retries=lcfg["retries"])
    print("下一步：%s" % ("python scripts/10_build_summary.py" if a.meta
                        else "python scripts/06_build_attrib.py"))


if __name__ == "__main__":
    main()
