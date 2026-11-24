#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 13c · 可选 Agent Wiki 输出模式（面向本地 Coding Agent 按需阅读）。

默认流水线仍输出单文件参考包（参考包.md / 纯文风包.md）；本脚本为纯 opt-in 扩展，
将文风语料、角色语音卡与设定/分卷拆分为互联 Markdown 页面，便于 Claude Code /
Codex / Pi / Cursor / Antigravity 每章按需读取 2–4 页，避免每次对话塞入 150 KB 全量包。

使用方式：
  python scripts/13c_build_wiki.py
  python scripts/13c_build_wiki.py --style-only --anonymize
  python scripts/13c_build_wiki.py --style-only --anonymize --anonymize-style names
  python scripts/13c_build_wiki.py --out-dir work/wiki
  python scripts/13c_build_wiki.py --check-stale
"""
import argparse
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import budget, corpus as C, project, textio          # noqa: E402
from stylefit import query as sf_query                        # noqa: E402


ANTI_PASTE_GUARDRAIL = (
    "> **防照抄护栏**：严禁直接复用、拼接或仅替换主语地照抄本页例句；"
    "仅学习句长分布、标点节奏、实词搭配、本书高频特征词与心理转折方式。"
)

_SCRIPT_CACHE = {}


def _load_script(fname):
    """按路径加载同目录已有脚本，复用核心函数避免代码重复。"""
    if fname in _SCRIPT_CACHE:
        return _SCRIPT_CACHE[fname]
    path = os.path.join(ROOT, "scripts", fname)
    key = "_refpack_wiki_reuse_" + fname.replace(".", "_")
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    _SCRIPT_CACHE[fname] = mod
    return mod


def _yaml_scalar(val):
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return json.dumps(str(val), ensure_ascii=False)


def _yaml_list(items):
    return "[" + ", ".join(_yaml_scalar(x) for x in items) + "]"


def _frontmatter(pairs):
    lines = ["---"]
    for k, v in pairs:
        if isinstance(v, (list, tuple)):
            lines.append("%s: %s" % (k, _yaml_list(v)))
        else:
            lines.append("%s: %s" % (k, _yaml_scalar(v)))
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n"


def _safe_filename(name):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (name or "").strip()).strip(". ")
    return s or "unnamed"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(65536)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _collect_sources(cfg, style_only=False):
    """采集当前构建依赖的源文件及其 SHA-256，用于增量陈旧检测。"""
    sources = {}

    def add_file(key, fpath, kind):
        if fpath and os.path.isfile(fpath):
            sources[key] = {
                "sha256": _sha256_file(fpath),
                "bytes": os.path.getsize(fpath),
                "kind": kind,
            }

    add_file("raw/_all.txt", os.path.join(cfg["paths"]["raw"], "_all.txt"), "raw")

    chunks_dir = cfg["paths"]["chunks"]
    if os.path.isdir(chunks_dir):
        chunk_files = sorted(
            glob.glob(os.path.join(chunks_dir, "chunk_*.txt")),
            key=textio.natural_key,
        )
        for cf in chunk_files:
            add_file("chunks/" + os.path.basename(cf), cf, "chunk")

    idx_path = os.path.join(cfg["paths"]["cache"], cfg.get("name") or "book", "index.json")
    add_file("index.json", idx_path, "index")
    add_file("attrib.json", project.artifact(cfg, "attrib.json"), "attrib")

    if not style_only:
        meta_dir = os.path.join(cfg["paths"]["notes"], "meta")
        if os.path.isdir(meta_dir):
            for mf in sorted(glob.glob(os.path.join(meta_dir, "*.md")), key=textio.natural_key):
                add_file("notes/meta/" + os.path.basename(mf), mf, "note")
        vol_dir = os.path.join(cfg["paths"]["notes"], "vol")
        if os.path.isdir(vol_dir):
            for vf in sorted(glob.glob(os.path.join(vol_dir, "vol_*.md")), key=textio.natural_key):
                add_file("notes/vol/" + os.path.basename(vf), vf, "note")

    return sources


def check_stale(cfg, out_dir, style_only=None):
    """比对当前源文件哈希与现有 _sources.json，报告新增/变更/移除/未变，绝不改写任何文件。"""
    src_path = os.path.join(out_dir, "_sources.json")
    if not os.path.isfile(src_path):
        print("状态：MISSING（未找到 %s，请先生成 Wiki）" % os.path.normpath(src_path))
        return 2

    saved = textio.read_json(src_path, {}) or {}
    prev = saved.get("sources") or {}
    eff_style_only = (saved.get("mode") == "style_only") if style_only is None else bool(style_only)
    curr = _collect_sources(cfg, style_only=eff_style_only)

    added = sorted(k for k in curr if k not in prev)
    removed = sorted(k for k in prev if k not in curr)
    modified = sorted(k for k in curr if k in prev and curr[k]["sha256"] != prev[k].get("sha256"))
    unchanged = sorted(k for k in curr if k in prev and curr[k]["sha256"] == prev[k].get("sha256"))

    print("Wiki 源文件陈旧检测：%s" % os.path.normpath(out_dir))
    print("  新增 (%d)%s" % (len(added), ("：" + "、".join(added)) if added else ""))
    print("  变更 (%d)%s" % (len(modified), ("：" + "、".join(modified)) if modified else ""))
    print("  移除 (%d)%s" % (len(removed), ("：" + "、".join(removed)) if removed else ""))
    print("  未变 (%d)" % len(unchanged))

    if added or removed or modified:
        print("状态：STALE（检测到源文件变动，建议重跑 scripts/13c_build_wiki.py）")
        return 1
    print("状态：FRESH（所有源文件均未变动）")
    return 0


def _read_meta_any(cfg, stem):
    """兼容 notes/meta/meta_<stem>.md 与 notes/meta/<stem>.md 两种命名。"""
    meta_dir = os.path.join(cfg["paths"]["notes"], "meta")
    for fname in ("meta_" + stem + ".md", stem + ".md"):
        p = os.path.join(meta_dir, fname)
        if os.path.isfile(p):
            txt = textio.read_text(p).strip()
            if txt:
                return txt
    return ""


def _extract_char_notes(char_doc, who, aliases=None):
    """从角色元档案中抽取匹配该角色的小节或要点行。"""
    if not char_doc or not who:
        return ""
    keys = [who] + [a for a in (aliases or ()) if a and a != who]
    out, grab, grab_lvl = [], False, 0
    for ln in char_doc.split("\n"):
        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            if any(k in ln for k in keys):
                grab, grab_lvl = True, lvl
                out.append(ln)
                continue
            if grab and lvl <= grab_lvl:
                grab = False
        if grab:
            out.append(ln)
    if out:
        return textio.clean_note_text("\n".join(out)).strip()

    # 兜底：无独立小节时，捞取包含该角色名的要点行
    hits = []
    for ln in char_doc.split("\n"):
        s = ln.strip()
        if s and not s.startswith("#") and any(k in s for k in keys):
            hits.append(s)
            if len(hits) >= 12:
                break
    return "\n".join(hits).strip()


_PROTECTED_MD_RE = re.compile(r"(\[\[[^\]]+\]\]|\[[^\]]+\]\([^)]+\)|`[^`]+`)")


def _add_wikilinks(text, char_names, exclude=None):
    """为正文中的已知角色名添加 [[角色]] 双向链接，跳过标题、代码块与已有链接。"""
    excl = set(exclude or ())
    targets = sorted({n for n in (char_names or ()) if n and n not in excl}, key=len, reverse=True)
    if not targets or not text:
        return text
    pat = re.compile("|".join(re.escape(n) for n in targets))

    out_lines = []
    in_fence = False
    for ln in text.split("\n"):
        st = ln.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            out_lines.append(ln)
            continue
        if in_fence or st.startswith("#"):
            out_lines.append(ln)
            continue
        parts = _PROTECTED_MD_RE.split(ln)
        rebuilt = []
        for idx, seg in enumerate(parts):
            if idx % 2 == 1:
                rebuilt.append(seg)
            else:
                rebuilt.append(pat.sub(lambda m: "[[%s]]" % m.group(0), seg))
        out_lines.append("".join(rebuilt))
    return "\n".join(out_lines)


def _mentioned_characters(text, char_names, exclude=None):
    excl = set(exclude or ())
    return [n for n in (char_names or ()) if n and n not in excl and n in (text or "")]


def _build_style_overview(cfg, X, style_only, anonymize, anon_style, role_map, craft_rules, today):
    st = X.get("统计", {})
    lines = [
        "# 文风速览与统计靶",
        "",
        ANTI_PASTE_GUARDRAIL,
        "",
        "## 一 · 核心硬指标",
        "- 语料规模：%s" % (X.get("meta", {}).get("chars", "?")),
        "- 台词均长：%s ｜ 中位：%s ｜ ≤19 字占比：%s（统计来源：%s）" % (
            st.get("台词均长"), st.get("台词中位长度"), st.get("台词≤19字占比"),
            st.get("台词统计来源") or "归属台词",
        ),
        "- 每千字标点：%s" % st.get("每千字标点"),
        "- 叙述句数：%s" % st.get("叙述句数"),
    ]
    if st.get("POV分桶"):
        pov_parts = []
        for pk, pv in st["POV分桶"].items():
            pov_parts.append("%s %d段(%.0f%%，均长%.1f，对白%.0f%%)" % (
                pk, pv.get("段数", 0), pv.get("占比", 0) * 100,
                pv.get("均段长", 0), pv.get("对白占比", 0) * 100,
            ))
        if pov_parts:
            lines.append("- POV 视角分桶：%s" % " ｜ ".join(pov_parts))
    if not style_only and not anonymize and st.get("说话人台词量"):
        lines.append("- 台词量前 12 人：%s" % st.get("说话人台词量"))
    if anonymize and role_map:
        style_desc = "自然中性人名（林远/苏晴……）" if anon_style == "names" else "中性代称（某甲/某乙……）"
        lines.append("- 脱敏说明：摘录中的原书人名已统一映射为%s，【条目框】已替换为「某技能/条目」。" % style_desc)
    lines.extend([
        "",
        "## 二 · 对标说明",
        craft_rules.get("benchmark_note") or "> 对标时必须按同类场景切区间，不能拿全书硬套（详见 docs/PITFALLS.md）。",
        "",
    ])
    fm = _frontmatter([
        ("type", "style"),
        ("topic", "overview"),
        ("mode", "style_only" if style_only else "full"),
        ("anonymized", anonymize),
        ("updated", today),
    ])
    return fm + "\n".join(lines).strip() + "\n"


def _build_style_narration(cfg, paras, narr, clean_fn, craft_rules, ex_mod, anonymize, today):
    person_label = "第一人称" if cfg.get("person") == "first" else "第三人称"
    lines = [
        "# 叙述腔与内心独白（%s）" % person_label,
        "",
        ANTI_PASTE_GUARDRAIL,
        "",
        "## 一 · 叙述句长阶梯",
        "",
    ]
    tiers = [
        ("超短句(≤12字)", [s for s in narr if len(s) <= 12]),
        ("短句(13-25字)", [s for s in narr if 12 < len(s) <= 25]),
        ("中句(26-50字)", [s for s in narr if 25 < len(s) <= 50]),
        ("长复合句(>50字)", [s for s in narr if len(s) > 50]),
    ]
    for tag, pool in tiers:
        lines.append("### %s" % tag)
        picked = ex_mod.pick_narr_tier(pool, 20)
        if picked:
            for s in picked:
                lines.append("- %s" % clean_fn(s))
        else:
            lines.append("- （当前语料无此区间样本）")
        lines.append("")

    inner_pat = craft_rules.get("inner_words") or r"(心想|心里想|觉得|暗自|不禁|寻思|盘算|默念|吐槽)"
    inner = [s for s in narr if re.search(inner_pat, s)]
    one = [p.strip() for p in paras if 4 <= len(p.strip()) <= 26 and not C.iter_quotes(p)]

    lines.append("## 二 · 内心独白（混在叙述里，不带引号）")
    lines.append("")
    for s in ex_mod.dedup_stride_pick(inner, 24, head_n=4):
        lines.append("- %s" % clean_fn(s))
    lines.append("")

    lines.append("## 三 · 单句成段短句（独立成行，留白/吐槽）")
    lines.append("")
    for s in ex_mod.dedup_stride_pick(one, 36, head_n=4):
        lines.append("- %s" % clean_fn(s))
    lines.append("")

    fm = _frontmatter([
        ("type", "style"),
        ("topic", "narration"),
        ("anonymized", anonymize),
        ("updated", today),
    ])
    return fm + "\n".join(lines).strip() + "\n"


def _build_style_craft(X, paras, raw, clean_fn, ex_mod, style_only, anonymize, today):
    craft_data = X.get("笔法细节") or ex_mod.extract_craft_details(paras, raw, per_cat=12)
    craft_order = [
        "连续动作白描",
        "环境与五感描写",
        "对话穿插动作（神态锚点）",
        "开篇与转场句",
        "克制收尾与留白短段",
    ]
    lines = [
        "# 细粒度笔法与描写意图",
        "",
        ANTI_PASTE_GUARDRAIL,
        "",
        "## 一 · 五类笔法与镜头细节",
        "",
    ]
    for cat in craft_order:
        items = craft_data.get(cat) or []
        lines.append("### %s" % cat)
        picked = ex_mod.dedup_stride_pick(items, 12, head_n=8)
        if picked:
            for item in picked:
                lines.append("- %s" % clean_fn(item))
        else:
            lines.append("- （当前语料无此类别样本）")
        lines.append("")

    lines.append("## 二 · 描写意图（这个意图书里怎么写）")
    lines.append("")
    for intent_name, d in (X.get("描写") or {}).items():
        if style_only and intent_name in ("看面板",):
            continue
        lines.append("### %s（原书 %d 处）" % (intent_name, d.get("n", 0)))
        for s in ex_mod.dedup_stride_pick(d.get("样本", []), 10, head_n=6):
            lines.append("- %s" % clean_fn(s))
        lines.append("")

    fm = _frontmatter([
        ("type", "style"),
        ("topic", "craft"),
        ("anonymized", anonymize),
        ("updated", today),
    ])
    return fm + "\n".join(lines).strip() + "\n"


def _build_style_dialogue(cfg, X, pairs, paras, clean_fn, ex_mod, style_only, anonymize, today):
    lines = [
        "# 对白回合与话语功能桶",
        "",
        ANTI_PASTE_GUARDRAIL,
        "",
        "## 一 · 分场景对白回合（引号与叙述的呼吸节奏）",
        "",
    ]
    for sc, d in (X.get("场景") or {}).items():
        if style_only and sc in ("游戏面板", "死亡复活"):
            continue
        lines.append("### 场景：%s" % sc)
        for s in ex_mod.stride_pick(d.get("样本", []), 6):
            lines.append("```")
            lines.append(clean_fn(s.strip()))
            lines.append("```")
        lines.append("")

    all_dialogues = C.extract_dialogue_quotes(paras, min_len=2)
    buckets = ex_mod.build_dialogue_style_buckets(
        X, pairs, per_bucket=10, cfg=cfg, all_dialogues=all_dialogues
    )
    lines.append("## 二 · 全书对白功能桶（句长、节奏与高频句尾）")
    lines.append("")
    for row in buckets:
        tail_str = " ｜ ".join(row["tails"]) if row["tails"] else "—"
        lines.append("### %s（%d 条 ｜ 均长 %.1f 字 ｜ 中位 %d 字 ｜ 高频句尾：%s）" % (
            row["func"], row["n"], row["avg_len"], row["med_len"], tail_str
        ))
        for s in row["samples"]:
            lines.append("- %s" % clean_fn(s))
        lines.append("")

    fm = _frontmatter([
        ("type", "style"),
        ("topic", "dialogue"),
        ("anonymized", anonymize),
        ("updated", today),
    ])
    return fm + "\n".join(lines).strip() + "\n"


def _build_style_vocab(cfg, X, paras, clean_fn, role_map, style_only, anonymize, today):
    lines = [
        "# 词汇表、高频特征词与雷区",
        "",
        "> 选词优先靠拢「本书高频特征词」与高频搭配；标 `【禁用】` 或在零频黑名单中的词严禁出现。",
        "",
        "## 一 · 本书高频特征词（写作模型词汇对齐参考）",
        "",
    ]
    raw_top_words = X.get("高频词") or []
    if not raw_top_words and paras:
        exclude_tw = set(cfg.get("names") or []) | set((X.get("台词") or {}).keys())
        for alts in (cfg.get("aliases") or {}).values():
            exclude_tw.update(alts or ())
        exclude_tw.update((cfg.get("anonymize_terms") or {}).keys())
        raw_top_words = [
            {"词": w, "次数": c}
            for w, c in C.extract_top_words(paras, top_k=60, exclude_terms=exclude_tw)
        ]

    ex_leak = set(role_map.keys()) if anonymize else set()
    shown_tw = []
    for item in raw_top_words:
        w = item.get("词", "")
        c_cnt = item.get("次数", 0)
        if not w or (anonymize and (w in ex_leak or clean_fn(w) != w)):
            continue
        shown_tw.append("%s %d" % (w, c_cnt))
        if len(shown_tw) >= 60:
            break
    if shown_tw:
        for i in range(0, len(shown_tw), 10):
            lines.append("- " + " ｜ ".join(shown_tw[i:i + 10]))
    else:
        lines.append("- （语料较短，暂未提取到高频特征词）")
    lines.append("")

    lines.append("## 二 · 搭配表（典型 vs 雷区）")
    lines.append("")
    for concept, dd in (X.get("搭配") or {}).items():
        lines.append("### %s" % concept)
        for w, n in sorted(dd.items(), key=lambda kv: -kv[1]):
            mark = "  【禁用】" if n == 0 else ("  【慎用】" if n <= 3 else "")
            lines.append("- %s  %d%s" % (w, n, mark))
        lines.append("")

    lines.append("## 三 · 用词表（概念 → 书里说法）")
    lines.append("")
    for concept, dd in (X.get("用词") or {}).items():
        lines.append("- **%s**：%s" % (concept, " ｜ ".join(
            "%s %d%s" % (w, n, "【禁用】" if n == 0 else "") for w, n in dd.items()
        )))
    lines.append("")

    lines.append("## 四 · 零频黑名单（全书 0 次，禁用）")
    lines.append("")
    z = X.get("零频词") or []
    lines.append("、".join(z) if z else "（空）")
    lines.append("")

    lines.append("## 五 · 场景词典")
    lines.append("")
    for sc, dd in (X.get("场景词典") or {}).items():
        if style_only and sc in ("游戏面板", "死亡复活"):
            continue
        hot = sorted([(w, n) for w, n in dd.items() if n > 0], key=lambda x: -x[1])[:12]
        dead = [w for w, n in dd.items() if n == 0]
        lines.append("- **%s**：%s" % (sc, " ｜ ".join("%s %d" % x for x in hot) if hot else "—"))
        if dead:
            lines.append("  - 禁用：%s" % "、".join(dead))
    lines.append("")

    fm = _frontmatter([
        ("type", "style"),
        ("topic", "vocab"),
        ("anonymized", anonymize),
        ("updated", today),
    ])
    return fm + "\n".join(lines).strip() + "\n"


def _build_style_bans(cfg, today):
    bp = project.resolve_bans_file(cfg)
    bans_body = textio.read_text(bp).strip() if bp else "<!-- 在 config/bans.md 里写本书的硬禁区。 -->"
    fm = _frontmatter([
        ("type", "style"),
        ("topic", "bans"),
        ("source", os.path.basename(bp) if bp else "none"),
        ("updated", today),
    ])
    return fm + "# 写作禁区与反 AI 腔自检\n\n" + bans_body + "\n"


def _build_world_page(cfg, book_label, char_pages_map, today):
    sections = []
    hard = cfg.get("hard_settings") or []
    if hard:
        sections.append(("## 硬设定（不可改）", "\n".join("- %s" % x for x in hard)))
    if_points = cfg.get("if_points") or []
    if if_points:
        sections.append(("## IF / 续写分歧点", "\n".join("- %s" % x for x in if_points)))

    meta_specs = [
        ("positioning", "## 作品定位与核心看点"),
        ("world", "## 世界观与核心设定"),
        ("factions", "## 势力阵营"),
        ("ending", "## 结局现状"),
        ("foreshadow", "## 伏笔与回收"),
    ]
    for stem, title in meta_specs:
        body = _read_meta_any(cfg, stem)
        if body:
            sections.append((title, textio.clean_note_text(body).strip()))

    if not sections and not char_pages_map:
        return None

    lines = ["# 《%s》世界观与设定总览" % book_label, ""]
    for title, body in sections:
        lines.append(title)
        lines.append("")
        lines.append(body)
        lines.append("")

    if char_pages_map:
        lines.append("## 角色档案索引")
        lines.append("")
        for who, rel_path in char_pages_map.items():
            lines.append("- [%s](%s)" % (who, rel_path))
        lines.append("")

    body_text = "\n".join(lines).strip() + "\n"
    if char_pages_map:
        body_text = _add_wikilinks(body_text, list(char_pages_map.keys()))

    fm = _frontmatter([
        ("type", "world"),
        ("book", book_label),
        ("status", "compiled"),
        ("updated", today),
    ])
    return fm + body_text


def _build_initial_contradictions(today):
    fm = _frontmatter([
        ("type", "meta"),
        ("topic", "contradictions"),
        ("status", "living"),
        ("updated", today),
    ])
    return fm + "\n".join([
        "# 矛盾与人工复核队列",
        "",
        "> 本页为持久复核笔记本：重新运行 `13c_build_wiki.py` 时会完整保留你手写的记录，绝不覆盖。",
        "",
        "## 待核对的剧情与设定矛盾",
        "- （示例）时间线 / 地点 / 道具状态前后冲突请记在这里，并注明对应卷页。",
        "",
        "## 角色语音分期与性格转折备忘",
        "- （示例）若角色在某卷发生口吻突变（结巴→流利、幼年→成年），在此标明分界点。",
        "",
        "## 人工复核清单",
        "- [ ] 核对 `world.md` 硬设定与最新章节无冲突",
        "- [ ] 核对主要角色 `characters/*.md` 的 `status: draft` 是否已人工确认",
        "",
    ])


def _build_route_md(has_chars, has_world, has_vols, style_only):
    lines = [
        "# 写作任务路由表（route.md）",
        "",
        "> 每次动笔只按当前任务加载 **2–4 个最相关页面**，不要一次性把整个 Wiki 全部塞进上下文。",
        "",
        "| 写作任务 / 场景 | 优先阅读页面 | 说明 |",
        "|---|---|---|",
        "| 定基调、句长与标点密度 | `style/overview.md` | 核对台词均长、每千字标点、POV 分桶与防照抄护栏 |",
        "| 写叙述节奏、心理独白、动作与五感 | `style/narration.md` + `style/craft.md` | 按句长阶梯、五类笔法细节与描写意图落地 |",
        "| 写对白回合与口吻呼吸感 | `style/dialogue.md` | 看场景对白切片与全书话语功能桶 |",
        "| 选词对齐与反 AI 腔避雷 | `style/vocab.md` + `style/bans.md` | 对齐本书高频特征词，排查零频词、低频搭配与结构雷区 |",
    ]
    if has_chars:
        lines.append("| 写特定角色戏份与台词 | `characters/<角色>.md` | 查看单角色语音靶、口癖、分期变化与人物设定 |")
    else:
        lines.append("| 写角色台词（当前为脱敏/纯文风模式） | `style/dialogue.md` | 本次未生成角色专页，统一按功能桶控对白 |")
    if has_world or has_vols:
        lines.append("| 查主线剧情、硬设定、结局与伏笔 | `world.md` + `volumes/vol_NN.md` | 按需只翻对应卷页，避免剧透或吃书 |")
    else:
        lines.append("| 查设定与剧情（当前未生成剧情页） | `style/overview.md` | 当前为纯文风模式或缺少卷纪要 |")
    lines.append("| 发现设定冲突 / 角色分期异常 | `meta/contradictions.md` | 追加记录，重建 Wiki 时自动保留 |")
    lines.extend([
        "",
        "## 写后验稿与改稿闭环",
        "",
        "```bash",
        "# 1. 首轮第 0–4 层体检 + 分优先级改稿指南",
    ])
    if style_only:
        lines.append("python scripts/11_verify.py --text <稿子.md> --cross-domain --domain-terms '新题材专词1,新题材专词2' --guide --top-z 15")
    else:
        lines.append("python scripts/11_verify.py --text <稿子.md> --guide --top-z 15")
    lines.extend([
        "# 2. 改稿前后量化对比与 HTML 可视化报告",
        "python scripts/11_verify.py --diff v1.md v2.md --html work/out/verify_report.html",
        "# 3. 检查源语料分片是否变更（不改写 Wiki）",
        "python scripts/13c_build_wiki.py --check-stale",
        "```",
        "",
    ])
    return "\n".join(lines)


def _build_agents_md(book_label, style_only):
    mode_tag = "纯文风脱敏模式" if style_only else "完整设定 + 文风模式"
    return "\n".join([
        "# Agent 写作工作指引 · %s（%s）" % (book_label, mode_tag),
        "",
        "1. **先读路由再读目录**：动笔前先读 `route.md` → `index.md`，明确本次需要哪些页面。",
        "2. **按需加载 2–4 页**：每章只打开与当前场景直接相关的 2–4 个页面，不要整目录全量灌入上下文。",
        "3. **严禁照抄例句**：禁止直接复制、拼接或仅换主语照抄 `style/*.md` 与 `characters/*.md` 中的原句；只学句长阶梯、标点节奏、实词搭配与高频特征词。",
        "4. **避雷优先**：行文避开 `style/vocab.md` 零频黑名单与 `【禁用】` 搭配，收尾前对照 `style/bans.md` 去 AI 腔。",
        "5. **冲突落账**：发现设定矛盾、时间线冲突或角色分期疑问，追加写入 `meta/contradictions.md`（重建 Wiki 会保留你的笔记）。",
        "6. **写完必须体检**：每章定稿前跑 `python scripts/11_verify.py --text <稿子.md> --guide`（跨题材仿写加 `--cross-domain`），确认第 0 层清零后再交付。",
        "7. **增量检测**：源语料或索引更新后，可运行 `python scripts/13c_build_wiki.py --check-stale` 核查陈旧分片。",
        "",
    ])


def _build_index_md(book_label, X, page_records, style_only, anonymize, today):
    st = X.get("统计", {})
    total_kb = sum(r["kb"] for r in page_records)
    lines = [
        "# 《%s》Agent Wiki 总目录" % book_label,
        "",
        "> 模式：`%s` ｜ 脱敏：`%s` ｜ 更新：`%s` ｜ 共 `%d` 页（合计 `%.1f KB`）" % (
            "style_only" if style_only else "full",
            "是" if anonymize else "否",
            today,
            len(page_records),
            total_kb,
        ),
        "",
        "## 本书统计靶速览",
        "- 语料规模：%s" % (X.get("meta", {}).get("chars", "?")),
        "- 台词均长：%s ｜ 中位：%s ｜ ≤19 字占比：%s" % (
            st.get("台词均长"), st.get("台词中位长度"), st.get("台词≤19字占比"),
        ),
        "- 每千字标点：%s" % st.get("每千字标点"),
        "- 叙述句数：%s" % st.get("叙述句数"),
        "",
    ]

    groups = [
        ("导航与元信息", lambda p: p["group"] == "root"),
        ("文风与词表（style/）", lambda p: p["group"] == "style"),
        ("角色语音卡（characters/）", lambda p: p["group"] == "characters"),
        ("世界观与分卷剧情", lambda p: p["group"] == "story"),
        ("复核与日志", lambda p: p["group"] == "meta"),
    ]
    for gtitle, pred in groups:
        sub = [r for r in page_records if pred(r)]
        if not sub:
            continue
        lines.append("## %s" % gtitle)
        lines.append("")
        lines.append("| 页面 | 简介 | 体积 |")
        lines.append("|---|---|---|")
        for r in sub:
            lines.append("| [%s](%s) | %s | %.1f KB |" % (
                r["title"], r["rel"], r["summary"], r["kb"]
            ))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_wiki(cfg, out_dir, style_only=False, anonymize=False, anon_style="neutral"):
    ex_mod = _load_script("09_build_examples.py")
    sum_mod = _load_script("10_build_summary.py")

    today = datetime.date.today().isoformat()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    X = ex_mod.load_index(cfg)
    pairs = ex_mod.read_pairs(cfg)
    names = cfg.get("names") or []
    raw, _ = C.load_corpus(cfg["paths"]["chunks"])
    paras = C.paragraphs(raw)
    narr = C.narr_sentences(paras)
    craft_rules = ex_mod.load_craft_rules(cfg)

    if anonymize:
        extra_speakers = list((X.get("台词") or {}).keys())
        clean_fn, role_map = C.build_anonymizer(
            names=names,
            aliases=cfg.get("aliases"),
            extra_terms=extra_speakers,
            strip_brackets=True,
            anonymize_terms=cfg.get("anonymize_terms"),
            single_char_names=cfg.get("single_char_names"),
            style=anon_style,
            collapse_adjacent=True,
        )
    else:
        clean_fn, role_map = (lambda s: s), {}

    book_label = "通用文风样本" if (style_only and anonymize) else (cfg.get("name") or "book")

    os.makedirs(out_dir, exist_ok=True)
    page_records = []

    def write_page(rel, title, summary, content, group):
        rel_posix = rel.replace("\\", "/")
        abs_p = os.path.join(out_dir, *rel_posix.split("/"))
        textio.write_text(abs_p, content)
        page_records.append({
            "rel": rel_posix,
            "title": title,
            "summary": summary,
            "kb": budget.utf8_kb(content),
            "group": group,
        })

    # 1. style/*.md (always generated)
    write_page(
        "style/overview.md",
        "文风速览与统计靶",
        "台词长度、标点密度、POV 分桶与防照抄护栏",
        _build_style_overview(cfg, X, style_only, anonymize, anon_style, role_map, craft_rules, today),
        "style",
    )
    write_page(
        "style/narration.md",
        "叙述腔与内心独白",
        "超短/短/中/长句阶梯、内心独白与单句成段短句",
        _build_style_narration(cfg, paras, narr, clean_fn, craft_rules, ex_mod, anonymize, today),
        "style",
    )
    write_page(
        "style/craft.md",
        "细粒度笔法与描写意图",
        "五类动作/五感/转场笔法细节 + 描写意图句群",
        _build_style_craft(X, paras, raw, clean_fn, ex_mod, style_only, anonymize, today),
        "style",
    )
    write_page(
        "style/dialogue.md",
        "对白回合与话语功能桶",
        "分场景对白切片 + 全书对白功能桶与高频句尾",
        _build_style_dialogue(cfg, X, pairs, paras, clean_fn, ex_mod, style_only, anonymize, today),
        "style",
    )
    write_page(
        "style/vocab.md",
        "词汇表、高频特征词与雷区",
        "本书高频特征词、搭配表、用词表、零频黑名单与场景词典",
        _build_style_vocab(cfg, X, paras, clean_fn, role_map, style_only, anonymize, today),
        "style",
    )
    write_page(
        "style/bans.md",
        "写作禁区与反 AI 腔自检",
        "反 AI 腔结构禁区与定稿自检清单",
        _build_style_bans(cfg, today),
        "style",
    )

    # 2. characters/<角色>.md (when NOT anonymized)
    char_pages_map = {}
    if not anonymize:
        speakers = list((X.get("台词") or {}).keys())
        attrib_path = project.artifact(cfg, "attrib.json")
        if not os.path.isfile(attrib_path):
            attrib_path = None
        char_meta_doc = _read_meta_any(cfg, "characters")
        aliases_cfg = cfg.get("aliases") or {}

        # Precompute safe filenames so cross-links stay accurate
        for who in speakers:
            char_pages_map[who] = "characters/%s.md" % _safe_filename(who)

        for idx, who in enumerate(speakers, start=1):
            card = sf_query.build_voice_card(X, who, attrib_path=attrib_path, target_kb=10.0)
            if not card:
                continue
            who_aliases = list(aliases_cfg.get(who) or [])
            extra_notes = _extract_char_notes(char_meta_doc, who, aliases=who_aliases)
            parts = [card.rstrip()]
            if extra_notes:
                parts.extend([
                    "",
                    "## 四 · 人物档案与设定摘录",
                    "",
                    _add_wikilinks(extra_notes, speakers, exclude={who}),
                ])

            mentioned_others = _mentioned_characters(
                card + "\n" + extra_notes, speakers, exclude={who}
            )
            rel_links = ["[对白节奏](../style/dialogue.md)"]
            if not style_only:
                rel_links.insert(0, "[世界观总览](../world.md)")
            for other in mentioned_others[:10]:
                rel_links.append("[%s](%s.md)" % (other, _safe_filename(other)))
            parts.extend(["", "## 关联页面", "- " + " ｜ ".join(rel_links), ""])

            fm = _frontmatter([
                ("entity_id", "char_%02d" % idx),
                ("name", who),
                ("aliases", who_aliases),
                ("type", "character"),
                ("status", "draft"),
                ("updated", today),
            ])
            rel = char_pages_map[who]
            write_page(
                rel,
                "角色 · %s" % who,
                "语音统计靶、句尾口癖、功能桶例句与人物档案",
                fm + "\n".join(parts).strip() + "\n",
                "characters",
            )

    # 3. world.md & volumes/vol_NN.md (when NOT style_only)
    has_world = False
    vol_count = 0
    if not style_only:
        world_content = _build_world_page(cfg, book_label, char_pages_map, today)
        if world_content:
            has_world = True
            write_page(
                "world.md",
                "世界观与设定总览",
                "硬设定、IF 分歧点、势力、结局与伏笔总览",
                world_content,
                "story",
            )

        char_names = list(char_pages_map.keys())
        for vinfo, fpath in project.vol_notes(cfg):
            raw_vol = textio.read_text(fpath)
            cleaned = textio.clean_note_text(raw_vol).strip()
            if not cleaned:
                continue
            stem = os.path.splitext(os.path.basename(fpath))[0]
            vlabel = sum_mod.vol_label(vinfo, fpath)
            mentioned = _mentioned_characters(cleaned, char_names)
            linked = _add_wikilinks(cleaned, char_names) if char_names else cleaned

            body_parts = [linked]
            if mentioned:
                body_parts.extend([
                    "",
                    "## 本卷关联角色页",
                    "- " + " ｜ ".join(
                        "[%s](../characters/%s.md)" % (nm, _safe_filename(nm))
                        for nm in mentioned
                    ),
                ])

            fm = _frontmatter([
                ("type", "volume"),
                ("volume", stem),
                ("title", vlabel),
                ("characters", mentioned),
                ("status", "compiled"),
                ("updated", today),
            ])
            write_page(
                "volumes/%s.md" % stem,
                "分卷 · %s" % vlabel,
                "分卷剧情纪要与卷末状态快照",
                fm + "\n".join(body_parts).strip() + "\n",
                "story",
            )
            vol_count += 1

    # 4. meta/contradictions.md (preserve user edits if already exists!)
    contradictions_path = os.path.join(out_dir, "meta", "contradictions.md")
    if os.path.isfile(contradictions_path):
        c_text = textio.read_text(contradictions_path)
    else:
        c_text = _build_initial_contradictions(today)
        textio.write_text(contradictions_path, c_text)
    page_records.append({
        "rel": "meta/contradictions.md",
        "title": "矛盾与人工复核队列",
        "summary": "剧情/设定冲突、角色分期备忘（重建自动保留）",
        "kb": budget.utf8_kb(c_text),
        "group": "meta",
    })

    # 5. route.md & AGENTS.md
    write_page(
        "route.md",
        "写作任务路由表",
        "按写作场景路由到最相关的 2–4 个页面与验稿命令",
        _build_route_md(bool(char_pages_map), has_world, vol_count > 0, style_only),
        "root",
    )
    write_page(
        "AGENTS.md",
        "Agent 写作指引",
        "本地 Coding Agent 入口规约（~25 行精简版）",
        _build_agents_md(book_label, style_only),
        "root",
    )

    # 6. log.md (append-only greppable build log)
    sources = _collect_sources(cfg, style_only=style_only)
    log_path = os.path.join(out_dir, "log.md")
    prev_log = textio.read_text(log_path) if os.path.isfile(log_path) else "# Wiki 构建日志\n\n"
    total_kb_est = sum(r["kb"] for r in page_records)
    log_entry = (
        "## [%s] build-wiki | %s | mode=%s | anon=%s | pages=%d | total=%.1f KB\n"
        "- style=6 ｜ characters=%d ｜ volumes=%d ｜ world=%s ｜ sources=%d\n\n"
    ) % (
        now_str,
        book_label,
        "style_only" if style_only else "full",
        "yes" if anonymize else "no",
        len(page_records) + 2,  # + index.md + log.md
        total_kb_est,
        len(char_pages_map),
        vol_count,
        "yes" if has_world else "no",
        len(sources),
    )
    new_log = prev_log.rstrip() + "\n\n" + log_entry if prev_log.strip() else "# Wiki 构建日志\n\n" + log_entry
    textio.write_text(log_path, new_log)
    page_records.append({
        "rel": "log.md",
        "title": "Wiki 构建日志",
        "summary": "追加式构建流水记录（可 grep 检索历史）",
        "kb": budget.utf8_kb(new_log),
        "group": "meta",
    })

    # 7. index.md (master catalog)
    index_content = _build_index_md(book_label, X, page_records, style_only, anonymize, today)
    textio.write_text(os.path.join(out_dir, "index.md"), index_content)

    # 8. _sources.json
    all_pages = sorted([r["rel"] for r in page_records] + ["index.md"])
    sources_meta = {
        "book": book_label,
        "mode": "style_only" if style_only else "full",
        "anonymized": bool(anonymize),
        "updated_at": now_iso,
        "pages": all_pages,
        "sources": sources,
    }
    textio.write_json(os.path.join(out_dir, "_sources.json"), sources_meta)

    print("Agent Wiki 构建完成：%s" % os.path.normpath(out_dir))
    print("  模式：%s ｜ 脱敏：%s ｜ 页面：%d 页 ｜ 源哈希：%d 项" % (
        "纯文风" if style_only else "完整设定+文风",
        "是" if anonymize else "否",
        len(all_pages),
        len(sources),
    ))
    print("  入口：%s" % os.path.normpath(os.path.join(out_dir, "AGENTS.md")))
    print("  目录：%s" % os.path.normpath(os.path.join(out_dir, "index.md")))
    return sources_meta


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(
        description="可选 Agent Wiki 输出模式：生成面向本地 Coding Agent 按需阅读的互联 Markdown 目录"
    )
    ap.add_argument("--config", default=None, help="指定 project.json 路径")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 <work>/wiki）")
    ap.add_argument("--style-only", action="store_true", default=None,
                    help="纯文风模式：只生成 style/ 目录，不生成 world.md / volumes/")
    ap.add_argument("--anonymize", action="store_true", help="对摘录人名与【条目框】做中性代称脱敏")
    ap.add_argument("--no-anonymize", action="store_true", help="禁用人名脱敏")
    ap.add_argument("--anonymize-style", choices=["neutral", "names"], default=None,
                    help="脱敏代称风格：neutral（某甲/某乙）或 names（林远/苏晴/陈默）")
    ap.add_argument("--check-stale", action="store_true",
                    help="仅比对当前分片/源文件 SHA-256 与现有 _sources.json，报告新增/变更/未变而不改写文件")
    a = ap.parse_args()

    cfg = project.load(a.config)
    out_dir = os.path.normpath(a.out_dir or os.path.join(cfg["paths"]["work"], "wiki"))

    if a.check_stale:
        rc = check_stale(cfg, out_dir, style_only=a.style_only)
        sys.exit(rc)

    style_only = bool(cfg.get("style_only")) if a.style_only is None else bool(a.style_only)
    if a.no_anonymize:
        anonymize = False
    elif a.anonymize or cfg.get("anonymize") or style_only:
        anonymize = True
    else:
        anonymize = False
    anon_style = a.anonymize_style or cfg.get("anonymize_style") or "neutral"

    build_wiki(
        cfg,
        out_dir=out_dir,
        style_only=style_only,
        anonymize=anonymize,
        anon_style=anon_style,
    )


if __name__ == "__main__":
    main()
