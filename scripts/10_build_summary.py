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
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio      # noqa: E402


def read_meta(cfg, name):
    p = os.path.join(cfg["paths"]["notes"], "meta", name + ".md")
    return textio.read_text(p).strip() if os.path.isfile(p) else ""


def vol_notes(cfg):
    return sorted(glob.glob(os.path.join(cfg["paths"]["notes"], "vol", "*.md")))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    cfg = project.load(a.config)
    name = cfg.get("name") or ""
    vols = vol_notes(cfg)
    L = []
    P = L.append
    miss = []

    def block(cond, title, body, hint=""):
        P(title)
        P("")
        if body:
            P(body.strip())
        else:
            miss.append(title)
            P("<!-- 缺内容：%s -->" % (hint or "见 docs/TEMPLATES.md"))
        P("")

    P("# 《%s》整书总结（事实圣经）" % name)
    P("")
    P("> 用途：作为 AI 续写 / 写 IF 线 / 仿写的背景设定与剧情纲领。")
    P("> 与 `例子.txt` 配套：本文给**设定与走向**，例子给**文风与语感**。")
    P("> 事实来源：分片摘要（all_notes.md）＋ 卷纪要（notes/vol/）。")
    P("")
    P("---")
    P("")

    # ── 〇 速查 ──
    P("# 〇、续写 / IF 速查")
    P("")
    P("**写前先卡三道**：① 时间线锚在哪一卷（见下「结局现状」）；"
      "② 角色当前状态（见「状态卡」）；③ 禁区（见「0.5」）。")
    P("")

    hard = cfg.get("hard_settings") or []
    P("## 0.1 硬设定速查（不可改）")
    P("")
    if hard:
        for x in hard:
            P("- %s" % x)
    else:
        w = read_meta(cfg, "meta_world")
        P(w[:1200] if w else "")
        if not w:
            miss.append("0.1 硬设定速查")
            P("<!-- 在 config/project.json 的 hard_settings 里列 5-10 条不可改的设定底线 -->")
    P("")

    block(True, "## 0.2 结局现状（截到哪一卷、此刻各人在哪在干什么）",
          read_meta(cfg, "meta_ending"),
          "跑 python scripts/05_run_volumes.py --meta，产出 notes/meta/meta_ending.md")

    state = ""
    if vols:
        state = section_of(textio.read_text(vols[-1]), ("状态快照", "角色状态"))
    block(True, "## 0.3 角色状态卡（截至结局）", state,
          "卷纪要模板里要有「本篇末角色状态快照」一节（见 config/prompts/stage2_volume.txt）")

    fore = read_meta(cfg, "meta_foreshadow")
    if_points = cfg.get("if_points") or []
    body = ""
    if if_points:
        body = "\n".join("- %s" % x for x in if_points)
    elif fore:
        body = section_of(fore, ("分歧", "IF")) or fore[:1500]
    block(True, "## 0.4 IF / 续写分歧点", body, "在 config 里配 if_points，或靠 meta_foreshadow")

    bp = os.path.join(ROOT, "config", "bans.md")
    block(True, "## 0.5 禁区（不能写什么）",
          textio.read_text(bp).strip() if os.path.isfile(bp) else "",
          "写 config/bans.md")

    P("---")
    P("")

    # ── 上篇 ──
    P("# 上篇 · 总览")
    P("")
    block(True, "## 一、作品定位与核心看点", read_meta(cfg, "meta_positioning"))
    block(True, "## 二、世界观与核心设定", read_meta(cfg, "meta_world"))
    block(True, "## 三、势力阵营", read_meta(cfg, "meta_factions"))
    block(True, "## 四、主要角色档案", read_meta(cfg, "meta_characters"))

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
            "- 搭配表见 `例子.txt` 第十一节；写作规矩见 docs/PITFALLS.md。",
        ]
        style_body = "\n".join(lines)
    block(True, "## 五、文风与写作规则（实测硬指标）", style_body,
          "先跑 scripts/07_stylefit_index.py")

    P("---")
    P("")

    # ── 下篇 ──
    P("# 下篇 · 分篇详细剧情")
    P("")
    P("> 逐卷保留全部事件，跨卷重复保留、同卷内完全相同的字符串才去重。")
    P("> 每卷篇末附该时间点的角色状态快照——写 IF 线时用它定时间锚。")
    P("")
    if vols:
        for f in vols:
            t = textio.clean_note_text(textio.read_text(f))
            P(t.strip())
            P("")
    else:
        miss.append("下篇 分篇详细剧情")
        P("<!-- 缺 notes/vol/*.md：跑 python scripts/05_run_volumes.py -->")
        P("")

    P("---")
    P("")

    # ── 附录 ──
    P("# 附录")
    P("")
    ch = read_meta(cfg, "meta_characters")
    block(True, "## A 角色线 / 关系线 / 群像",
          section_of(ch, ("角色线", "关系线", "群像", "成长线")) or ch[:2000],
          "meta 模板里加「角色线 / 关系线」小节")
    w = read_meta(cfg, "meta_world")
    block(True, "## B 设定术语词典",
          section_of(w, ("术语", "词典", "设定表")) or "",
          "meta 模板里加「术语」小节")
    block(True, "## C 伏笔与回收",
          section_of(fore, ("伏笔",)) or fore[:1500] if fore else "",
          "靠 meta_foreshadow")

    out = a.out or os.path.join(cfg["paths"]["out"], "整书总结.md")
    body = "\n".join(L).strip() + "\n"
    textio.write_text(out, body)
    print("整书总结：%d 字 ｜ 卷纪要 %d 份" % (len(body), len(vols)))
    if miss:
        print("待补章节 %d 个：%s" % (len(miss), "；".join(miss)))
    print("→ %s" % out)
    print("下一步：python scripts/11_verify.py --text <你的稿子>")


if __name__ == "__main__":
    main()
