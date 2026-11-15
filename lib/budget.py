# -*- coding: utf-8 -*-
"""容量预算、UTF-8 KB / 字符数 / Token 估算与章节按权重裁剪工具。

全部只用标准库。中文散文与 Markdown 混合文本经验换算：
- 1 个汉字 UTF-8 占 3 字节，加上换行/ASCII 标点/Markdown 标记，平均 ~2.75 字节/字符（1 KB ≈ 372 字符）
- 主流分词器（DeepSeek / Qwen / GPT-4o / Claude）在现代中文小说上：
  1 个中文字符 ≈ 0.68 tokens，ASCII 字符 ≈ 0.28 tokens。
"""
import re

CJK_RE = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")

# 预设总体积档位（单位 KB，None 表示不设上限）
PRESET_KB = {
    "compact": 60.0,     # ~2.2 万字 / ~1.6 万 tokens（适合 32k 窗口或免费网页端）
    "standard": 150.0,   # ~5.5 万字 / ~4.0 万 tokens（默认甜点，适合 64k~128k 窗口）
    "rich": 300.0,       # ~11 万字  / ~8.0 万 tokens（适合 200k 长窗口深度创作）
    "full": None,        # 全量无损输出
}

BYTES_PER_CHAR = 2.75
TOKENS_PER_CHAR = 0.68


def utf8_kb(text):
    """返回文本的精确 UTF-8 大小（KB，1 KB = 1024 bytes）。"""
    if not text:
        return 0.0
    return len(text.encode("utf-8")) / 1024.0


def estimate_tokens(text):
    """估算中文+Markdown混合文本的 Token 数（零外部依赖）。"""
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(round(cjk * 0.68 + other * 0.28)))


def kb_to_chars(kb):
    if kb is None or kb <= 0:
        return None
    return max(500, int(round(kb * 1024.0 / BYTES_PER_CHAR)))


def tokens_to_kb(tokens):
    if tokens is None or tokens <= 0:
        return None
    chars = tokens / TOKENS_PER_CHAR
    return round(chars * BYTES_PER_CHAR / 1024.0, 2)


def add_budget_args(ap, default_preset=None):
    """给 argparse 注入统一的容量预算参数。"""
    ap.add_argument("--preset", choices=["compact", "standard", "rich", "full"],
                    default=default_preset,
                    help="容量预设档位：compact(60KB) / standard(150KB) / rich(300KB) / full(不限)")
    ap.add_argument("--kb", type=float, default=None,
                    help="目标总大小（KB，覆盖 --preset；0 表示不限）")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="目标最大估算 Token 数（覆盖 --preset；0 表示不限）")
    ap.add_argument("--ratio", type=float, default=None,
                    help="例子集占总预算比例（0.1~1.0，默认 0.70 即 70%% 例子 : 30%% 摘要）")


def resolve_budget(cfg=None, preset=None, kb=None, max_tokens=None, ratio=None, style_only=False):
    """综合命令行参数与 config['budget']，算出总预算与例子/摘要各自配额。

    返回 dict:
      {
        "preset": str,
        "total_kb": float | None,
        "total_chars": int | None,
        "target_tokens": int | None,
        "example_ratio": float,
        "summary_ratio": float,
        "example_kb": float | None,
        "summary_kb": float | None,
        "example_chars": int | None,
        "summary_chars": int | None,
        "unlimited": bool,
      }
    """
    bcfg = dict((cfg or {}).get("budget") or {})
    eff_preset = preset or bcfg.get("preset") or "standard"
    if eff_preset not in PRESET_KB:
        eff_preset = "standard"

    eff_ratio = ratio if ratio is not None else bcfg.get("example_ratio", 0.70)
    try:
        eff_ratio = float(eff_ratio)
    except (TypeError, ValueError):
        eff_ratio = 0.70
    eff_ratio = min(1.0, max(0.1, eff_ratio))
    if style_only:
        eff_ratio = 1.0

    eff_kb = kb if kb is not None else bcfg.get("target_kb")
    eff_tok = max_tokens if max_tokens is not None else bcfg.get("max_tokens")

    total_kb = None
    if eff_kb is not None:
        total_kb = None if eff_kb <= 0 else float(eff_kb)
        eff_preset = "custom" if total_kb is not None else "full"
    elif eff_tok is not None:
        total_kb = None if eff_tok <= 0 else tokens_to_kb(eff_tok)
        eff_preset = "custom" if total_kb is not None else "full"
    else:
        total_kb = PRESET_KB.get(eff_preset)

    unlimited = total_kb is None
    if unlimited:
        return {
            "preset": "full",
            "total_kb": None,
            "total_chars": None,
            "target_tokens": None,
            "example_ratio": eff_ratio,
            "summary_ratio": round(1.0 - eff_ratio, 4),
            "example_kb": None,
            "summary_kb": None,
            "example_chars": None,
            "summary_chars": None,
            "unlimited": True,
        }

    ex_kb = round(total_kb * eff_ratio, 2)
    sum_kb = round(max(0.0, total_kb * (1.0 - eff_ratio)), 2)
    total_chars = kb_to_chars(total_kb)
    ex_chars = kb_to_chars(ex_kb) if ex_kb > 0 else 0
    sum_chars = kb_to_chars(sum_kb) if sum_kb > 0 else 0
    return {
        "preset": eff_preset,
        "total_kb": round(total_kb, 2),
        "total_chars": total_chars,
        "target_tokens": int(round(total_chars * TOKENS_PER_CHAR)),
        "example_ratio": round(eff_ratio, 4),
        "summary_ratio": round(1.0 - eff_ratio, 4),
        "example_kb": ex_kb,
        "summary_kb": sum_kb,
        "example_chars": ex_chars,
        "summary_chars": sum_chars,
        "unlimited": False,
    }


def allot_weights(sizes, weights, budget_chars):
    """按权重分配字符配额：本身比配额小的节拿全量，剩余配额再按权重分给超长节。"""
    if budget_chars is None:
        return list(sizes)
    n = len(sizes)
    alloc = [0] * n
    todo = [i for i in range(n) if sizes[i] > 0]
    left = max(0, int(budget_chars))
    while todo:
        wsum = float(sum(max(0.01, weights[i]) for i in todo))
        fit = [i for i in todo if sizes[i] <= left * max(0.01, weights[i]) / wsum]
        if not fit:
            for i in todo:
                alloc[i] = int(left * max(0.01, weights[i]) / wsum)
            break
        for i in fit:
            alloc[i] = sizes[i]
            left -= sizes[i]
        todo = [i for i in todo if i not in fit]
    return alloc


def trim_markdown_block(text, max_chars, keep_tail=False, gap="\n……（受容量预算限制，此处省略部分条目）……\n"):
    """按行/段落边界优雅裁剪 Markdown 文本到 max_chars 字符内，不截断半行或破坏代码块闭合。"""
    if max_chars is None or len(text) <= max_chars:
        return text
    if max_chars <= 0:
        return ""
    lines = text.split("\n")
    head_line = ""
    body = lines
    if lines and lines[0].startswith("#"):
        head_line = lines[0]
        body = lines[1:]

    room = max_chars - (len(head_line) + 1 if head_line else 0) - len(gap)
    if room <= 40:
        return (head_line + "\n" if head_line else "") + text[:max(0, max_chars)].rstrip()

    if not keep_tail:
        kept, used, in_fence = [], 0, False
        for ln in body:
            if used + len(ln) + 1 > room:
                break
            kept.append(ln)
            used += len(ln) + 1
            if ln.strip().startswith("```"):
                in_fence = not in_fence
        if in_fence:
            kept.append("```")
        res = "\n".join(([head_line] if head_line else []) + kept).rstrip() + gap
        return res.strip() + "\n"

    # 首尾兼顾保留（适合分卷纪要与长列表）
    front, back = [], []
    used_f = used_b = 0
    half_f = int(room * 0.55)
    half_b = room - half_f
    i, j = 0, len(body)
    f_fence = False
    while i < j and used_f + len(body[i]) + 1 <= half_f:
        ln = body[i]
        front.append(ln)
        used_f += len(ln) + 1
        if ln.strip().startswith("```"):
            f_fence = not f_fence
        i += 1
    if f_fence:
        front.append("```")

    b_fence = False
    while j > i and used_b + len(body[j - 1]) + 1 <= half_b:
        j -= 1
        ln = body[j]
        back.insert(0, ln)
        used_b += len(ln) + 1
        if ln.strip().startswith("```"):
            b_fence = not b_fence
    if b_fence:
        back.insert(0, "```")

    parts = ([head_line] if head_line else []) + front + [gap.strip()] + back
    return "\n".join(parts).strip() + "\n"


def trim_to_utf8_bytes(text, max_kb):
    """硬兜底：若按字符估算后实际 UTF-8 字节仍超出目标 KB 超过 8%，按行回退修剪到预算附近。"""
    if max_kb is None or max_kb <= 0:
        return text
    limit_bytes = int(max_kb * 1024 * 1.05)
    raw_b = text.encode("utf-8")
    if len(raw_b) <= limit_bytes:
        return text
    target_bytes = int(max_kb * 1024)
    lines = text.split("\n")
    kept, used, in_fence = [], 0, False
    for ln in lines:
        lb = len((ln + "\n").encode("utf-8"))
        if used + lb > target_bytes - 90:
            break
        kept.append(ln)
        used += lb
        if ln.strip().startswith("```"):
            in_fence = not in_fence
    if in_fence:
        kept.append("```")
    kept.append("")
    kept.append("<!-- 已按目标容量 %.1f KB 截断收尾 -->" % max_kb)
    return "\n".join(kept).strip() + "\n"


def format_stats_banner(full_text, example_text="", summary_text="", budget_info=None):
    """生成写入产物头部或打印到控制台的统计摘要行。"""
    kb = utf8_kb(full_text)
    chars = len(full_text)
    toks = estimate_tokens(full_text)
    parts = [
        "大小 %.1f KB" % kb,
        "字符 %s" % format(chars, ","),
        "估算 ~%s tokens" % format(toks, ","),
    ]
    if example_text and summary_text:
        ekb = utf8_kb(example_text)
        skb = utf8_kb(summary_text)
        denom = max(0.01, ekb + skb)
        parts.append("例子 %.1f KB (%.0f%%) : 摘要 %.1f KB (%.0f%%)" % (
            ekb, ekb / denom * 100, skb, skb / denom * 100))
    if budget_info and not budget_info.get("unlimited"):
        parts.append("档位 %s (目标 %.0f KB)" % (
            budget_info.get("preset", "custom"), budget_info.get("total_kb") or 0))
    elif budget_info and budget_info.get("unlimited"):
        parts.append("档位 full (无损全量)")
    return " ｜ ".join(parts)
