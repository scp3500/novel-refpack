#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 · 二层归纳：把分片摘要合并成「每卷纪要」。可选跑元章节。

  python scripts/05_run_volumes.py            # 每卷一个任务 → notes/vol/vol_NN.md
  python scripts/05_run_volumes.py --only 3,5
  python scripts/05_run_volumes.py --meta     # 世界观 / 角色 / 势力 / 结局 / 伏笔 / 定位
  python scripts/05_run_volumes.py --meta --only characters

每个任务只读这一卷的几份分片摘要（4-6k token），不读原文——
单卷原文 7-13 万字，输入 45k-132k token，既贵又没必要。

元章节各自备料（见 VOL_SECTIONS）：世界观要「设定」、伏笔要「伏笔与回收」、
结局现状要最后几卷的全文。材料超长时按卷均摊压缩，每卷每节保留首尾，
不会从头截断把最后几卷丢掉。
"""
import os
import sys
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio, llm      # noqa: E402
from lib.llm import DEFAULTS              # noqa: E402

MATERIAL_CHARS = 60000

# 元章节 → 从每卷纪要里取哪几节（匹配 stage2_volume.txt 的 ## 小节标题关键词）
VOL_SECTIONS = {
    "meta_positioning": ("范围", "剧情", "基调"),
    "meta_world": ("剧情", "设定"),
    "meta_factions": ("剧情", "登场", "设定"),
    "meta_characters": ("剧情", "状态", "登场", "名场面"),
    "meta_ending": ("剧情", "状态", "伏笔"),
    "meta_foreshadow": ("剧情", "设定", "伏笔"),
}
ALL_SECTIONS = ("范围", "剧情", "状态", "登场", "设定", "名场面", "伏笔", "基调")
# 看「此刻」的元章节：压缩时最后 N 卷权重更高，尽量全文保留
TAIL_HEAVY = {"meta_ending": 3}
GAP = "……（中略）……"


def build_volume_jobs(cfg):
    vmap = textio.read_json(project.artifact(cfg, "volume_map.json"), None)
    if not vmap:
        raise SystemExit("先跑 scripts/04_build_volume_map.py（缺 work/volume_map.json）")
    notes = cfg["paths"]["notes"]
    outdir = os.path.join(notes, "vol")
    jobs = []
    for v in vmap:
        of = os.path.join(outdir, "vol_%02d.md" % v["i"])
        nums = v.get("chunks") or []
        if not nums:
            print("跳过 vol_%02d（卷映射里没有对应分片，检查 04_build_volume_map 的输出）" % v["i"])
            continue
        files = [os.path.join(notes, "chunk_%02d.md" % n) for n in nums]
        lack = [n for n, f in zip(nums, files) if not os.path.isfile(f)]
        if lack:
            # 缺一片就开跑会产出一份缺剧情的纪要，之后重跑还会被当成「已完成」跳过
            print("跳过 vol_%02d（缺分片摘要 %s，先补跑 scripts/02_run_notes.py --only %s）" % (
                v["i"], ",".join("%02d" % n for n in lack), ",".join(str(n) for n in lack)))
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


def note_sections(text):
    """卷纪要 → (# 标题, [(## 小节标题行, [正文行])])。### 及更深并入所属小节。"""
    title, secs, cur = "", [], None
    for ln in text.split("\n"):
        if ln.startswith("# ") and not title and cur is None:
            title = ln[2:].strip()
            continue
        if ln.startswith("## "):
            cur = (ln.rstrip(), [])
            secs.append(cur)
            continue
        if cur is not None:
            cur[1].append(ln.rstrip())
    out = []
    for head, body in secs:
        while body and not body[-1].strip():
            body.pop()
        while body and not body[0].strip():
            body.pop(0)
        out.append((head, body))
    return title, out


def allot(sizes, weights, budget):
    """按权重分预算：放得下的块拿全量，剩下的再按权重分给放不下的。"""
    alloc = [0] * len(sizes)
    todo = [i for i, s in enumerate(sizes) if s > 0]
    left = max(0, budget)
    while todo:
        wsum = float(sum(weights[i] for i in todo))
        fit = {i for i in todo if sizes[i] <= left * weights[i] / wsum}
        if not fit:
            for i in todo:
                alloc[i] = int(left * weights[i] / wsum)
            break
        for i in fit:
            alloc[i] = sizes[i]
            left -= sizes[i]
        todo = [i for i in todo if i not in fit]
    return alloc


def clip(head, body, quota):
    """把一节压到 quota 字以内：保留开头和结尾的行，砍中间。"""
    lines = ([head] if head else []) + body
    full = "\n".join(lines)
    if len(full) <= quota:
        return full
    room = max(0, quota - (len(head) + 1 if head else 0) - len(GAP) - 2)
    front, back, used = [], [], 0
    i, j = 0, len(body)
    while i < j and used + len(body[i]) + 1 <= room // 2:
        used += len(body[i]) + 1
        front.append(body[i])
        i += 1
    while j > i and used + len(body[j - 1]) + 1 <= room:
        j -= 1
        used += len(body[j]) + 1
        back.insert(0, body[j])
    if not front and not back and body and room > 0:
        front = [body[0][:room]]
    return "\n".join(([head] if head else []) + front + [GAP] + back)


def material_blocks(cfg, keys):
    """[(卷标题, [(小节标题, [行])])]，按卷序。没有卷纪要时退回 all_notes.md 的分片块。"""
    blocks = []
    vols = project.vol_notes(cfg)
    if vols:
        for v, f in vols:
            title, secs = note_sections(textio.read_text(f))
            label = title or (("%s %s" % (v.get("h1") or "", v.get("h2") or "")).strip()
                              if v else "") or os.path.basename(f)
            pieces = [(h, b) for h, b in secs
                      if not h.startswith("## 附") and any(k in h for k in keys)]
            blocks.append((label, pieces))
        return blocks
    p = project.artifact(cfg, "all_notes.md")
    if not os.path.isfile(p):
        raise SystemExit("没有卷纪要也没有 work/all_notes.md：先跑 05_run_volumes.py（不带 --meta）")
    cur = None
    for ln in textio.read_text(p).split("\n"):
        if ln.startswith("## 分片"):
            cur = (ln[3:].strip(), [("", [])])
            blocks.append(cur)
        elif cur is not None:
            cur[1][0][1].append(ln.rstrip())
    return blocks


def meta_material(cfg, prompt_name, limit=MATERIAL_CHARS):
    """给某个元章节备料：取它需要的小节；超过 limit 时每卷每节按权重压缩、保留首尾。"""
    blocks = material_blocks(cfg, VOL_SECTIONS.get(prompt_name, ALL_SECTIONS))
    n = len(blocks)
    tail = TAIL_HEAVY.get(prompt_name, 0)
    sizes, weights = [], []
    for bi, (_, pieces) in enumerate(blocks):
        for h, body in pieces:
            sizes.append(len("\n".join(([h] if h else []) + body)))
            weights.append(4 if tail and bi >= n - tail else 1)

    def render(alloc, note=""):
        out, k = [], 0
        for label, pieces in blocks:
            parts = ["### %s" % label]
            for h, body in pieces:
                parts.append(clip(h, body, alloc[k]))
                k += 1
            out.append("\n".join(parts))
        return note + "\n\n".join(out)

    text = render(sizes)
    if len(text) <= limit:
        return text
    note = "（材料已按卷压缩：共 %d 卷，每卷各节保留首尾%s。）\n\n" % (
        n, "，最后 %d 卷优先保全" % tail if tail else "")
    overhead = len(render([0] * len(sizes), note)) - len(GAP) * len(sizes)
    return render(allot(sizes, weights, limit - overhead - len(GAP) * len(sizes)), note)


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

    # command 后端的输出先落在目标目录里的临时文件，目录必须先存在
    os.makedirs(os.path.join(cfg["paths"]["notes"], "meta" if a.meta else "vol"), exist_ok=True)

    only = set(a.only.split(",")) if a.only else None
    jobs = build_meta_jobs(cfg) if a.meta else build_volume_jobs(cfg)
    if only:
        jobs = [j for j in jobs if str(j[0]) in only]
    if not a.force:
        jobs = [j for j in jobs if not (os.path.isfile(j[1]["out"])
                                        and os.path.getsize(j[1]["out"]) > 300)]
    mats = {k: meta_material(cfg, j["prompt"]) for k, j in jobs} if a.meta else {}
    print("待办 %d ｜ 模式 %s ｜ 并发 %d" % (len(jobs), "meta" if a.meta else "volumes", par))
    if a.dry_run:
        for k, j in jobs:
            extra = "  材料 %d 字" % len(mats[k]) if a.meta else ""
            print("   %s  %s%s" % (k, j["out"], extra))
        return

    unit = cfg.get("vol_unit_word") or "卷"

    def work(k, j):
        if a.meta:
            prompt = project.prompt(cfg, j["prompt"], name=cfg.get("name", ""),
                                    material=mats[k])
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
