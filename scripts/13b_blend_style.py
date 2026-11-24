#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 13B · 多书混搭文风包一键合成器（纯标准库，零 LLM 成本）。

  python scripts/13b_blend_style.py --narr packA.md --dialogue packB.md --out work/out/混搭文风包.md
  python scripts/13b_blend_style.py --narr config/project_a.json --dialogue config/project_b.json --preset compact --out work/out/blend.md
  python scripts/13b_blend_style.py --narr work/out/纯文风包.md --dialogue work_b/out/例子.txt --kb 80 --out blend_80k.md

从【叙述源 A】抽取叙述腔、内心独白、细粒度笔法与镜头细节、描写套路、高频/搭配/用词/零频黑名单与使用禁令；
从【对白源 B】抽取对白回合、语体与台词功能范例及对白统计靶；
自动注入【冲突仲裁规则】与【反照抄红线】，并按 lib/budget.py 精确裁剪容量。
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import budget, project, textio  # noqa: E402


H2_RE = re.compile(r"^##\s+(.+?)\s*$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")


def resolve_pack_source(path, explicit_name=None):
    """解析输入源：支持直接 .md/.txt 文风包，或 project.json 配置路径。

    返回 (pack_file_path, display_name, text)。
    """
    if not path:
        raise SystemExit("缺少输入路径")
    p = os.path.normpath(path if os.path.isabs(path) else os.path.abspath(path))
    if not os.path.exists(p):
        # 也尝试相对仓库根解析
        alt = os.path.normpath(os.path.join(ROOT, path))
        if os.path.exists(alt):
            p = alt
        else:
            raise SystemExit("找不到输入文件：%s" % path)

    inferred_name = None
    pack_path = p

    if os.path.isdir(p):
        for cand in ("纯文风包.md", "例子.txt", "参考包.md"):
            fp = os.path.join(p, cand)
            if os.path.isfile(fp):
                pack_path = fp
                break
        else:
            raise SystemExit("目录中未找到 纯文风包.md 或 例子.txt：%s" % p)
    elif p.lower().endswith(".json"):
        cfg = project.load(p)
        inferred_name = cfg.get("name") or None
        out_dir = cfg["paths"]["out"]
        found = None
        for cand in ("纯文风包.md", "例子.txt", "参考包.md"):
            fp = os.path.join(out_dir, cand)
            if os.path.isfile(fp):
                found = fp
                break
        if not found:
            raise SystemExit(
                "配置 %s 对应的输出目录 %s 下未找到 纯文风包.md 或 例子.txt（请先跑 09_build_examples.py 或 13_build_pack.py）"
                % (p, out_dir)
            )
        pack_path = found

    text = textio.read_text(pack_path)
    if not text.strip():
        raise SystemExit("输入文风包为空：%s" % pack_path)

    if not inferred_name:
        inferred_name = infer_pack_name(text, pack_path)

    return pack_path, (explicit_name or inferred_name), text


def infer_pack_name(text, fallback_path=""):
    """从文风包首行 # 标题推导书名，退回文件名。"""
    for ln in (text or "").splitlines()[:20]:
        m = H1_RE.match(ln.strip())
        if not m:
            continue
        title = m.group(1).strip()
        m_book = re.search(r"《([^》]+)》", title)
        if m_book:
            return m_book.group(1).strip()
        # 如「金瓶梅_崇祯本 · 典型例子集」
        head = re.split(r"[·・|｜]", title)[0].strip()
        if head and head not in ("通用文风样本",):
            return head
    stem = os.path.splitext(os.path.basename(fallback_path))[0]
    return stem or "未命名文风源"


def parse_h2_sections(text):
    """按顶级 `## ` 标题切分 Markdown 小节（忽略代码块内的 `## `）。

    返回 [(title, body_text), ...]，顺序与原文一致。
    """
    sections = []
    cur_title = None
    cur_lines = []
    in_fence = False

    for ln in (text or "").splitlines():
        st = ln.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            if cur_title is not None:
                cur_lines.append(ln)
            continue
        if not in_fence:
            m = H2_RE.match(ln)
            if m:
                if cur_title is not None:
                    sections.append((cur_title, "\n".join(cur_lines).strip()))
                cur_title = m.group(1).strip()
                cur_lines = []
                continue
        if cur_title is not None:
            cur_lines.append(ln)

    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_lines).strip()))
    return sections


def _clean_section_title(title):
    """去掉原序号前缀（如「二 · 」「十一 · 」）以便重排统一编号。"""
    t = re.sub(r"^[一二三四五六七八九十百0-9A-Za-z]+\s*[·・.、：:\-—]\s*", "", title.strip())
    return t.strip() or title.strip()


def _extract_overview_lines(sections, mode):
    """从「文风速览」小节抽取对应维度的统计靶行（mode='narr' 或 'dialogue'）。"""
    overview_body = ""
    for title, body in sections:
        if any(k in title for k in ("文风速览", "统计靶")):
            overview_body = body
            break
    if not overview_body:
        return []

    kept = []
    for ln in overview_body.splitlines():
        s = ln.strip()
        if not s or s.startswith(">"):
            continue
        if mode == "narr":
            if any(k in s for k in ("语料规模", "叙述句数", "每千字标点", "脱敏说明", "视角", "人称")):
                kept.append(s)
        else:
            if any(k in s for k in ("台词均长", "台词中位", "≤19", "台词量", "每千字标点", "语体")):
                kept.append(s)
    return kept


def _pick_matching_sections(sections, specs):
    """按规则列表从源小节中无重复抽取匹配节，返回 [(clean_title, body, weight, keep_tail), ...]。"""
    used_idx = set()
    picked = []
    for keywords, weight, keep_tail in specs:
        for idx, (title, body) in enumerate(sections):
            if idx in used_idx or not body.strip():
                continue
            if any(kw in title for kw in keywords):
                used_idx.add(idx)
                picked.append((_clean_section_title(title), body.strip(), weight, keep_tail))
    return picked


def _cn_index(n):
    nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
            "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十"]
    return nums[n - 1] if 1 <= n <= len(nums) else str(n)


def _compose_document(header_lines, sections):
    out = list(header_lines)
    for hdr, body, _w, _kt in sections:
        out.append(hdr)
        out.append("")
        if body:
            out.append(body.rstrip())
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _budget_trim_sections(header_lines, sections, binfo):
    """按权重分配字符配额并优雅裁剪；必要时二次等比收缩与字节硬兜底。"""
    if binfo.get("unlimited") or not binfo.get("total_chars"):
        return _compose_document(header_lines, sections)

    header_len = sum(len(x) + 1 for x in header_lines)
    sec_raw_texts = []
    weights = []
    keep_tails = []
    for hdr, body, w, kt in sections:
        block = (hdr + "\n\n" + (body.rstrip() if body else "")).strip() + "\n"
        sec_raw_texts.append(block)
        weights.append(w)
        keep_tails.append(kt)

    target_chars = binfo["total_chars"]
    target_kb = binfo.get("total_kb")

    total_chars = header_len + sum(len(t) for t in sec_raw_texts)
    if total_chars <= target_chars:
        doc = _compose_document(header_lines, sections)
        if not target_kb or budget.utf8_kb(doc) <= target_kb * 1.05:
            return doc

    def _run_allot(char_limit):
        avail = max(300, char_limit - header_len - len(sections) * 2)
        sizes = [len(t) for t in sec_raw_texts]
        alloc = budget.allot_weights(sizes, weights, avail)
        trimmed_secs = []
        for idx, (hdr, body, w, kt) in enumerate(sections):
            block = sec_raw_texts[idx]
            lim = alloc[idx]
            if len(block) > lim:
                tblock = budget.trim_markdown_block(block, lim, keep_tail=kt)
                parts = tblock.split("\n", 1)
                nhdr = parts[0] if parts else hdr
                nbody = parts[1].lstrip("\n") if len(parts) > 1 else ""
                trimmed_secs.append((nhdr, nbody, w, kt))
            else:
                trimmed_secs.append((hdr, body, w, kt))
        return _compose_document(header_lines, trimmed_secs)

    doc = _run_allot(target_chars)
    if target_kb and budget.utf8_kb(doc) > target_kb * 1.05:
        actual_kb = budget.utf8_kb(doc)
        scale_down = (target_kb / actual_kb) * 0.94
        doc = _run_allot(max(400, int(target_chars * scale_down)))
    if target_kb and budget.utf8_kb(doc) > target_kb * 1.06:
        doc = budget.trim_to_utf8_bytes(doc, target_kb)
    return doc


def blend_style_texts(
    narr_text,
    dialogue_text,
    narr_name="叙述源",
    dialogue_name="对白源",
    binfo=None,
    narr_weight_ratio=None,
):
    """将叙述源 A 与对白源 B 混搭为统一文风包字符串。"""
    if binfo is None:
        binfo = budget.resolve_budget(preset="standard", style_only=True)

    secs_a = parse_h2_sections(narr_text)
    secs_b = parse_h2_sections(dialogue_text)

    # ── 提取双源统计靶 ──
    narr_stats = _extract_overview_lines(secs_a, "narr")
    dlg_stats = _extract_overview_lines(secs_b, "dialogue")

    # ── 从叙述源 A 抽取叙述/描写/笔法/实词搭配/零频/禁令 ──
    narr_specs = [
        (("叙述腔",), 3.0, False),
        (("内心独白", "独白"), 2.2, False),
        (("细粒度笔法与镜头细节", "细粒度笔法", "笔法与镜头", "镜头细节"), 3.8, False),
        (("描写套路",), 3.2, False),
        (("高频",), 2.0, False),
        (("搭配表", "零频"), 2.8, True),
        (("用词表",), 2.0, False),
        (("使用禁令", "禁区", "常见误区"), 2.4, True),
    ]
    narr_picked = _pick_matching_sections(secs_a, narr_specs)

    # ── 从对白源 B 抽取对白回合、语体与台词功能范例 ──
    dlg_specs = [
        (("对白回合",), 3.6, False),
        (("语体与台词功能范例", "台词功能", "台词分角色", "台词"), 3.6, False),
        (("语音档案",), 2.2, False),
    ]
    dlg_picked = _pick_matching_sections(secs_b, dlg_specs)

    # 如用户显式传了 --ratio（0.1~0.9），按比例调节叙述源 vs 对白源权重
    n_mult = 1.0
    d_mult = 1.0
    if narr_weight_ratio is not None:
        r = min(0.9, max(0.1, float(narr_weight_ratio)))
        n_mult = r / 0.5
        d_mult = (1.0 - r) / 0.5

    # ── 组装有序小节 ──
    merged = []
    sec_no = 1

    # 第一节：双源文风速览
    ov_lines = [
        "### 【叙述与描写靶】（来源：%s）" % narr_name,
    ]
    if narr_stats:
        ov_lines.extend(narr_stats)
    else:
        ov_lines.append("- （叙述源未提供独立统计靶，以正文叙述腔与笔法范例为准）")
    ov_lines.append("")
    ov_lines.append("### 【对白与语体靶】（来源：%s）" % dialogue_name)
    if dlg_stats:
        ov_lines.extend(dlg_stats)
    else:
        ov_lines.append("- （对白源未提供独立统计靶，以正文对白回合与语体功能范例为准）")
    merged.append(("## %s · 双源文风速览（统计靶）" % _cn_index(sec_no), "\n".join(ov_lines), 2.4, False))
    sec_no += 1

    # 先放叙述源主体（叙述腔 / 独白 / 笔法 / 描写套路），再放对白源（对白回合 / 语体台词），最后放词表/零频/禁令
    narr_front = []
    narr_tail = []
    for title, body, w, kt in narr_picked:
        if any(k in title for k in ("高频", "搭配", "用词", "零频", "禁令", "禁区", "误区")):
            narr_tail.append((title, body, w * n_mult, kt))
        else:
            narr_front.append((title, body, w * n_mult, kt))

    for title, body, w, kt in narr_front:
        hdr = "## %s · %s【叙述源：%s】" % (_cn_index(sec_no), title, narr_name)
        merged.append((hdr, body, w, kt))
        sec_no += 1

    for title, body, w, kt in dlg_picked:
        hdr = "## %s · %s【对白源：%s】" % (_cn_index(sec_no), title, dialogue_name)
        merged.append((hdr, body, w * d_mult, kt))
        sec_no += 1

    for title, body, w, kt in narr_tail:
        hdr = "## %s · %s【叙述源：%s】" % (_cn_index(sec_no), title, narr_name)
        merged.append((hdr, body, w, kt))
        sec_no += 1

    # ── 头部：容量看板 + 冲突仲裁规则 + 反照抄红线 ──
    header_lines = [
        "# 混搭文风参考包：【叙述】%s × 【对白】%s" % (narr_name, dialogue_name),
        "",
        "> **容量看板**：__STATS_BANNER__",
        "> **叙述与描写源**：`%s`（负责叙述腔、内心独白、细粒度笔法、描写套路、高频实词/搭配/零频黑名单与禁令）" % narr_name,
        "> **对白与语体源**：`%s`（负责对白回合呼吸节奏、语体与台词功能范例、对白句长统计靶）" % dialogue_name,
        "",
        "> **冲突仲裁规则（多源混搭铁律）**：",
        "> 1. 旁白、动作链、五感环境、内心独白与实词搭配严格遵循【叙述源：%s】；" % narr_name,
        "> 2. 对白句长、呼吸感、话语功能、台词交互节奏与句尾口癖严格遵循【对白源：%s】；" % dialogue_name,
        "> 3. 无论对白多么跳脱、尖锐或舒缓，叙述腔、镜头密度与实词选词绝不被对白源带偏；反之，引号内台词也不被叙述源拖慢或书面化；",
        "> 4. 同一段落内的「动作/神态锚点」服从【叙述源】，「引号内对白」服从【对白源】，用换行与标点保持清晰边界；",
        "> 5. 零频黑名单与使用禁令以【叙述源】为底线，对白源特有的口语词仅限引号内出现。",
        "",
        "> **反照抄红线**：严禁直接复用、拼接或仅替换主语地照抄本包例句；所有样本仅用于校准句法节奏、动词选词、镜头密度与对白呼吸感，正文必须围绕新剧情完全原创生成。",
        "",
        "---",
        "",
    ]

    doc = _budget_trim_sections(header_lines, merged, binfo)
    banner1 = budget.format_stats_banner(doc.replace("__STATS_BANNER__", ""), budget_info=binfo)
    doc = doc.replace("__STATS_BANNER__", banner1, 1)
    banner2 = budget.format_stats_banner(doc, budget_info=binfo)
    doc = re.sub(r"^> \*\*容量看板\*\*：.*$", "> **容量看板**：" + banner2, doc, count=1, flags=re.MULTILINE)

    if not binfo.get("unlimited") and binfo.get("total_kb"):
        if budget.utf8_kb(doc) > binfo["total_kb"] * 1.06:
            doc = budget.trim_to_utf8_bytes(doc, binfo["total_kb"])
            banner3 = budget.format_stats_banner(doc, budget_info=binfo)
            doc = re.sub(r"^> \*\*容量看板\*\*：.*$", "> **容量看板**：" + banner3, doc, count=1, flags=re.MULTILINE)

    return doc, {
        "narr_sections": [t for t, _, _, _ in narr_picked],
        "dialogue_sections": [t for t, _, _, _ in dlg_picked],
        "kb": round(budget.utf8_kb(doc), 2),
        "chars": len(doc),
        "tokens": budget.estimate_tokens(doc),
    }


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="多书混搭文风包一键合成器（叙述源 A × 对白源 B）")
    ap.add_argument("--narr", required=True, help="叙述源文风包（.md/.txt）或 project.json 配置路径")
    ap.add_argument("--dialogue", required=True, help="对白源文风包（.md/.txt）或 project.json 配置路径")
    ap.add_argument("--out", default=os.path.join(ROOT, "work", "out", "混搭文风包.md"),
                    help="输出混搭文风包路径（默认 work/out/混搭文风包.md）")
    ap.add_argument("--narr-name", default=None, help="自定义叙述源显示名（可选）")
    ap.add_argument("--dialogue-name", default=None, help="自定义对白源显示名（可选）")
    budget.add_budget_args(ap)
    a = ap.parse_args()

    narr_path, narr_name, narr_text = resolve_pack_source(a.narr, explicit_name=a.narr_name)
    dlg_path, dlg_name, dlg_text = resolve_pack_source(a.dialogue, explicit_name=a.dialogue_name)

    binfo = budget.resolve_budget(
        cfg=None,
        preset=a.preset,
        kb=a.kb,
        max_tokens=a.max_tokens,
        ratio=None,
        style_only=True,
    )

    doc, stats = blend_style_texts(
        narr_text,
        dlg_text,
        narr_name=narr_name,
        dialogue_name=dlg_name,
        binfo=binfo,
        narr_weight_ratio=a.ratio,
    )

    textio.write_text(a.out, doc)
    print("混搭文风包生成完成：%s（叙述）× %s（对白）" % (narr_name, dlg_name))
    print("  叙述源：%s（抽取 %d 节）" % (narr_path, len(stats["narr_sections"])))
    print("  对白源：%s（抽取 %d 节）" % (dlg_path, len(stats["dialogue_sections"])))
    print("  总计：%.1f KB ｜ %s 字 ｜ ~%s tokens" % (
        stats["kb"], format(stats["chars"], ","), format(stats["tokens"], ",")))
    print("→ %s" % a.out)


if __name__ == "__main__":
    main()
