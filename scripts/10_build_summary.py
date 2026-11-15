#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 10 · 生成整书总结（事实圣经）。

  python scripts/10_build_summary.py
  python scripts/10_build_summary.py --out out/整书总结.md

结构（照 docs/TEMPLATES.md）：

  〇 续写 / IF 速查       ← 硬设定 + 结局现状 + 角色状态卡 + 分歧点 + 禁区（放最前面）
  上篇 总览               ← notes/meta/*.md（定位 / 世界观 / 势力 / 角色 / 文风规则）
  下篇 分篇详细剧情       ← notes/vol/*.md 全量拼接（事件不删）
  附录                    ← 角色线 / 术语 / 伏笔

事实来源只有两个：分片摘要和卷纪要。不靠记忆，不靠印象。
"""
import os
import re
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import budget, project, textio      # noqa: E402


def read_meta(cfg, name):
    p = os.path.join(cfg["paths"]["notes"], "meta", name + ".md")
    return textio.read_text(p).strip() if os.path.isfile(p) else ""


def vol_label(v, f):
    if v:
        return ("%s %s" % (v.get("h1") or "", v.get("h2") or "")).strip() or os.path.basename(f)
    return os.path.basename(f)


def section_of(text, keys):
    """抽某小节：标题含 keys 之一就开始收，直到下一个同级或更高级的标题。

    二级标题下面常常还有三级小节（例：「五、设定」里的「### 术语词典」），
    所以遇到更深的标题不改 grab 状态。
    """
    out, grab = [], False
    for ln in text.split("\n"):
        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            hit = any(k in ln for k in keys)
            grab = hit if lvl <= 2 else (grab or hit)
            if grab:
                out.append(ln)
            continue
        if grab:
            out.append(ln)
    return "\n".join(out).strip()


def _build_section(title, body, hint="", miss=None):
    lines = [title, ""]
    if body:
        lines.append(body.strip())
    else:
        if miss is not None:
            miss.append(title)
        lines.append("<!-- 缺内容：%s -->" % (hint or "见 docs/TEMPLATES.md"))
    lines.append("")
    return "\n".join(lines)


def _assemble_summary(name, header_block, p1_sec0_header, p1_blocks, p2_upper_header,
                      p2_upper_blocks, p3_vols_header, p3_vol_texts, p3_tail_note,
                      p2_app_header, p2_app_blocks, stats_line=""):
    parts = [header_block]
    if stats_line:
        parts.append(stats_line + "\n")
    parts.append("> 续写 / IF 前只读「〇」；设定与走向见「上篇」；逐卷剧情见「下篇」。\n\n---\n")
    parts.append(p1_sec0_header)
    parts.extend(p1_blocks)
    parts.append("---\n")
    parts.append(p2_upper_header)
    parts.extend(p2_upper_blocks)
    parts.append("---\n")
    parts.append(p3_vols_header)
    parts.extend(p3_vol_texts)
    if p3_tail_note:
        parts.append(p3_tail_note)
    parts.append("---\n")
    parts.append(p2_app_header)
    parts.extend(p2_app_blocks)
    return "\n".join(p.strip() for p in parts if p and p.strip()).strip() + "\n"


def _vol_weights(n):
    if n <= 0:
        return []
    w = []
    for idx in range(n):
        if idx >= n - 2:
            w.append(4.0)
        elif idx == 0:
            w.append(2.5)
        else:
            w.append(1.0)
    return w


def _compress_blocks(blocks, total_budget):
    if not blocks or total_budget is None:
        return list(blocks)
    sizes = [len(b) for b in blocks]
    if sum(sizes) <= total_budget:
        return list(blocks)
    alloc = budget.allot_weights(sizes, [1.0] * len(blocks), total_budget)
    return [
        budget.trim_markdown_block(b, q, keep_tail=False) if len(b) > q else b
        for b, q in zip(blocks, alloc)
    ]


def _compress_volumes(vol_texts, total_budget):
    if not vol_texts or total_budget is None:
        return list(vol_texts)
    sizes = [len(v) for v in vol_texts]
    if sum(sizes) <= total_budget:
        return list(vol_texts)
    weights = _vol_weights(len(vol_texts))
    alloc = budget.allot_weights(sizes, weights, total_budget)
    return [
        budget.trim_markdown_block(v, q, keep_tail=True) if len(v) > q else v
        for v, q in zip(vol_texts, alloc)
    ]


def _render_with_budget(binfo, header_block, p1_sec0_header, p1_blocks, p2_upper_header,
                        p2_upper_blocks, p3_vols_header, p3_vol_texts, p3_tail_note,
                        p2_app_header, p2_app_blocks):
    raw_body = _assemble_summary(
        "", header_block, p1_sec0_header, p1_blocks, p2_upper_header,
        p2_upper_blocks, p3_vols_header, p3_vol_texts, p3_tail_note,
        p2_app_header, p2_app_blocks, stats_line=""
    )
    sum_chars = binfo.get("summary_chars")
    sum_kb = binfo.get("summary_kb")

    if binfo.get("unlimited") or not sum_chars or len(raw_body) <= sum_chars:
        prelim = raw_body
        stats_line = "> 容量统计：%s" % budget.format_stats_banner(prelim, budget_info=binfo)
        return _assemble_summary(
            "", header_block, p1_sec0_header, p1_blocks, p2_upper_header,
            p2_upper_blocks, p3_vols_header, p3_vol_texts, p3_tail_note,
            p2_app_header, p2_app_blocks, stats_line=stats_line
        )

    def build_for_chars(target_chars):
        fixed_overhead = (
            len(header_block) + len(p1_sec0_header) + len(p2_upper_header)
            + len(p3_vols_header) + len(p3_tail_note or "") + len(p2_app_header) + 260
        )
        avail = max(600, target_chars - fixed_overhead)

        # 第一优先级：# 〇、续写 / IF 速查（最多 38%，尽量完整保留）
        p1_raw_len = sum(len(b) for b in p1_blocks)
        p1_cap = int(avail * 0.38)
        if p1_raw_len <= p1_cap:
            c_p1 = list(p1_blocks)
            p1_used = p1_raw_len
        else:
            c_p1 = _compress_blocks(p1_blocks, p1_cap)
            p1_used = sum(len(b) for b in c_p1)

        rem_after_p1 = max(200, avail - p1_used)
        # 第三优先级至少保底总可用预算的 30%
        p3_floor = int(avail * 0.30)
        p2_raw_len = sum(len(b) for b in p2_upper_blocks) + sum(len(b) for b in p2_app_blocks)
        p2_cap = min(int(avail * 0.32), max(100, rem_after_p1 - p3_floor))
        if p2_raw_len <= p2_cap:
            c_p2_upper = list(p2_upper_blocks)
            c_p2_app = list(p2_app_blocks)
            p2_used = p2_raw_len
        else:
            all_p2 = p2_upper_blocks + p2_app_blocks
            c_all_p2 = _compress_blocks(all_p2, p2_cap)
            nu = len(p2_upper_blocks)
            c_p2_upper = c_all_p2[:nu]
            c_p2_app = c_all_p2[nu:]
            p2_used = sum(len(b) for b in c_all_p2)

        p3_cap = max(p3_floor, avail - p1_used - p2_used)
        c_p3_vols = _compress_volumes(p3_vol_texts, p3_cap)

        prelim = _assemble_summary(
            "", header_block, p1_sec0_header, c_p1, p2_upper_header,
            c_p2_upper, p3_vols_header, c_p3_vols, p3_tail_note,
            p2_app_header, c_p2_app, stats_line=""
        )
        return prelim, c_p1, c_p2_upper, c_p3_vols, c_p2_app

    prelim, c_p1, c_p2_upper, c_p3_vols, c_p2_app = build_for_chars(sum_chars)
    if sum_kb and sum_kb > 0:
        cur_kb = budget.utf8_kb(prelim)
        if cur_kb > sum_kb * 1.08:
            adj_chars = max(500, int(sum_chars * (sum_kb / cur_kb) * 0.97))
            prelim, c_p1, c_p2_upper, c_p3_vols, c_p2_app = build_for_chars(adj_chars)

    stats_line = "> 容量统计：%s" % budget.format_stats_banner(prelim, budget_info=binfo)
    return _assemble_summary(
        "", header_block, p1_sec0_header, c_p1, p2_upper_header,
        c_p2_upper, p3_vols_header, c_p3_vols, p3_tail_note,
        p2_app_header, c_p2_app, stats_line=stats_line
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    budget.add_budget_args(ap)
    a = ap.parse_args()

    cfg = project.load(a.config)
    binfo = budget.resolve_budget(
        cfg, preset=a.preset, kb=a.kb, max_tokens=a.max_tokens, ratio=a.ratio
    )
    name = cfg.get("name") or ""
    all_vols = project.vol_notes(cfg, with_missing=True)
    vols = [f for _, f in all_vols if os.path.isfile(f)]
    miss = []

    header_block = "# 《%s》整书总结（事实圣经）\n" % name

    # ── 〇 速查 ──
    p1_sec0_header = "# 〇、续写 / IF 速查\n"
    p1_blocks = []

    hard = cfg.get("hard_settings") or []
    if hard:
        hard_body = "\n".join("- %s" % x for x in hard)
    else:
        w = read_meta(cfg, "meta_world")
        hard_body = w[:1200] if w else ""
    p1_blocks.append(_build_section(
        "## 0.1 硬设定速查（不可改）",
        hard_body,
        "在 config/project.json 的 hard_settings 里列 5-10 条不可改的设定底线",
        miss=miss,
    ))

    p1_blocks.append(_build_section(
        "## 0.2 结局现状（截到哪一卷、此刻各人在哪在干什么）",
        read_meta(cfg, "meta_ending"),
        "跑 python scripts/05_run_volumes.py --meta，产出 notes/meta/meta_ending.md",
        miss=miss,
    ))

    # 状态卡只认卷映射里的最后一卷：它的纪要缺了就留空报缺，
    # 拿前一卷顶替会把时间锚悄悄挪早
    state = ""
    hint = "卷纪要模板里要有「本篇末角色状态快照」一节（见 config/prompts/stage2_volume.txt）"
    if all_vols:
        lv, lf = all_vols[-1]
        if os.path.isfile(lf):
            state = section_of(textio.read_text(lf), ("状态快照", "角色状态"))
            if state:
                state = "> 截至：%s\n\n%s" % (vol_label(lv, lf), state)
        else:
            hint = "最后一卷 %s（%s）的纪要缺失：python scripts/05_run_volumes.py --only %s" % (
                os.path.basename(lf), vol_label(lv, lf), lv["i"] if lv else "")
            print("警告：" + hint)
    p1_blocks.append(_build_section("## 0.3 角色状态卡（截至结局）", state, hint, miss=miss))

    fore = read_meta(cfg, "meta_foreshadow")
    if_points = cfg.get("if_points") or []
    body_if = ""
    if if_points:
        body_if = "\n".join("- %s" % x for x in if_points)
    elif fore:
        body_if = section_of(fore, ("分歧", "IF")) or fore[:1500]
    p1_blocks.append(_build_section(
        "## 0.4 IF / 续写分歧点", body_if, "在 config 里配 if_points，或靠 meta_foreshadow", miss=miss
    ))

    bp = project.resolve_bans_file(cfg)
    p1_blocks.append(_build_section(
        "## 0.5 禁区（不能写什么）",
        textio.read_text(bp).strip() if bp else "",
        "写 config/bans.md 或配置 bans_file",
        miss=miss,
    ))

    # ── 上篇 ──
    p2_upper_header = "# 上篇 · 总览\n"
    p2_upper_blocks = [
        _build_section("## 一、作品定位与核心看点", read_meta(cfg, "meta_positioning"), miss=miss),
        _build_section("## 二、世界观与核心设定", read_meta(cfg, "meta_world"), miss=miss),
        _build_section("## 三、势力阵营", read_meta(cfg, "meta_factions"), miss=miss),
        _build_section("## 四、主要角色档案", read_meta(cfg, "meta_characters"), miss=miss),
    ]

    idx_p = os.path.join(cfg["paths"]["cache"], name or "book", "index.json")
    X = textio.read_json(idx_p, {}) or {}
    style_body = ""
    if X:
        st = X.get("统计", {})
        z = X.get("零频词") or []
        lines = [
            "- 台词均长 %s ｜ 中位 %s ｜ ≤19 字占比 %s" % (
                st.get("台词均长"), st.get("台词中位长度"), st.get("台词≤19字占比")),
            "- 每千字标点：%s" % st.get("每千字标点"),
            "- 零频黑名单（全书 0 次，禁用）：%s" % ("、".join(z) if z else "—"),
            "- 搭配表见 `例子.txt` 第十节；写作规矩见 docs/PITFALLS.md。",
        ]
        style_body = "\n".join(lines)
    p2_upper_blocks.append(_build_section(
        "## 五、文风与写作规则（实测硬指标）", style_body, "先跑 scripts/07_stylefit_index.py", miss=miss
    ))

    # ── 下篇 ──
    p3_vols_header = (
        "# 下篇 · 分篇详细剧情\n\n"
        "> 逐卷保留全部事件，跨卷重复保留、同卷内完全相同的字符串才去重。\n"
        "> 每卷篇末附该时间点的角色状态快照——写 IF 线时用它定时间锚。\n"
    )
    p3_vol_texts = []
    p3_tail_note = ""
    if vols:
        for f in vols:
            t = textio.clean_note_text(textio.read_text(f)).strip()
            if t:
                p3_vol_texts.append(t)
        lack = [v["i"] for v, f in all_vols if v and not os.path.isfile(f)]
        if lack:
            miss.append("下篇缺 %d 卷（%s）" % (len(lack), ",".join(map(str, lack))))
    else:
        miss.append("下篇 分篇详细剧情")
        p3_tail_note = "<!-- 缺 notes/vol/*.md：跑 python scripts/05_run_volumes.py -->\n"

    # ── 附录 ──
    p2_app_header = "# 附录\n"
    ch = read_meta(cfg, "meta_characters")
    w = read_meta(cfg, "meta_world")
    p2_app_blocks = [
        _build_section(
            "## A 角色线 / 关系线 / 群像",
            section_of(ch, ("角色线", "关系线", "群像", "成长线")) or ch[:2000],
            "meta 模板里加「角色线 / 关系线」小节",
            miss=miss,
        ),
        _build_section(
            "## B 设定术语词典",
            section_of(w, ("术语", "词典", "设定表")) or "",
            "meta 模板里加「术语」小节",
            miss=miss,
        ),
        _build_section(
            "## C 伏笔与回收",
            section_of(fore, ("伏笔",)) or fore[:1500] if fore else "",
            "靠 meta_foreshadow",
            miss=miss,
        ),
    ]

    out = a.out or os.path.join(cfg["paths"]["out"], "整书总结.md")
    body = _render_with_budget(
        binfo, header_block, p1_sec0_header, p1_blocks, p2_upper_header,
        p2_upper_blocks, p3_vols_header, p3_vol_texts, p3_tail_note,
        p2_app_header, p2_app_blocks
    )
    textio.write_text(out, body)
    kb = budget.utf8_kb(body)
    toks = budget.estimate_tokens(body)
    print("整书总结：%.1f KB ｜ %d 字 ｜ ~%s tokens ｜ 卷纪要 %d 份" % (
        kb, len(body), format(toks, ","), len(vols)))
    if miss:
        print("待补章节 %d 个：%s" % (len(miss), "；".join(miss)))
    print("→ %s" % out)
    print("下一步：python scripts/11_verify.py --text <你的稿子>")


if __name__ == "__main__":
    main()
