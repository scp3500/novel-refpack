#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 13 · 一键合并《整书总结》+《例子集》，生成单文件参考包并输出统计看板。

  python scripts/13_build_pack.py
  python scripts/13_build_pack.py --preset compact
  python scripts/13_build_pack.py --style-only --anonymize
  python scripts/13_build_pack.py --no-rebuild
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import budget, project, textio      # noqa: E402


BAN_SEC_RE = re.compile(
    r"(^##\s+0\.5\s+禁区[^\n]*\n)(.*?)(?=\n(?:---|# |\## )|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _compact_ban_section(summary_text):
    """若 整书总结 的 0.5 禁区 与 例子集 末尾「使用禁令」重复，精简为单行指引以省 Token。"""
    def _repl(m):
        head = m.group(1)
        body = m.group(2).strip()
        if not body or "<!-- 缺内容" in body or "文末自检清单" in body:
            return m.group(0)
        return head + "\n> 禁区细则已与文末「使用禁令 / 常见误区」自检清单合并，请直阅文末对应小节。\n"

    return BAN_SEC_RE.sub(_repl, summary_text, count=1)


def _budget_cli_args(a):
    args = []
    if a.preset:
        args += ["--preset", a.preset]
    if a.kb is not None:
        args += ["--kb", str(a.kb)]
    if a.max_tokens is not None:
        args += ["--max-tokens", str(a.max_tokens)]
    if a.ratio is not None:
        args += ["--ratio", str(a.ratio)]
    return args


def _style_cli_args(a):
    args = []
    if a.style_only:
        args.append("--style-only")
    if a.anonymize:
        args.append("--anonymize")
    elif a.no_anonymize:
        args.append("--no-anonymize")
    return args


def _run_py(script_name, extra_args):
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script_name)] + list(extra_args)
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit("%s 执行失败（exit %s）" % (script_name, proc.returncode))


def main():
    ap = argparse.ArgumentParser(description="合并生成单文件参考包（整书总结 + 典型例子集）")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    budget.add_budget_args(ap)
    ap.add_argument("--style-only", action="store_true", help="只输出纯文风脱敏包（跳过整书总结）")
    ap.add_argument("--anonymize", action="store_true", help="将人名脱敏为中性代称")
    ap.add_argument("--no-anonymize", action="store_true", help="禁用人名脱敏")
    ap.add_argument("--no-rebuild", action="store_true", help="不重跑 09/10，直接读取现有产物按预算合并")
    a = ap.parse_args()

    cfg = project.load(a.config)
    style_only = bool(a.style_only or cfg.get("style_only"))
    binfo = budget.resolve_budget(
        cfg,
        preset=a.preset,
        kb=a.kb,
        max_tokens=a.max_tokens,
        ratio=a.ratio if a.ratio is not None else None,
        style_only=style_only,
    )

    cfg_args = ["--config", a.config] if a.config else []
    b_args = _budget_cli_args(a)
    s_args = _style_cli_args(a)

    if not a.no_rebuild:
        _run_py("09_build_examples.py", cfg_args + b_args + s_args)
        if not style_only:
            _run_py("10_build_summary.py", cfg_args + b_args)

    out_dir = cfg["paths"]["out"]
    ex_path = os.path.join(out_dir, "例子.txt")
    sum_path = os.path.join(out_dir, "整书总结.md")

    if not os.path.isfile(ex_path):
        raise SystemExit("缺少例子集文件：%s（去掉 --no-rebuild 或先跑 scripts/09_build_examples.py）" % ex_path)
    ex_text = textio.read_text(ex_path).strip()

    sum_text = ""
    if not style_only:
        if not os.path.isfile(sum_path):
            raise SystemExit("缺少整书总结文件：%s（去掉 --no-rebuild 或先跑 scripts/10_build_summary.py）" % sum_path)
        sum_text = textio.read_text(sum_path).strip()

    if a.no_rebuild and not binfo.get("unlimited"):
        ex_chars = binfo.get("example_chars")
        if ex_chars and len(ex_text) > ex_chars:
            ex_text = budget.trim_markdown_block(ex_text, ex_chars, keep_tail=True).strip()
        if not style_only:
            sum_chars = binfo.get("summary_chars")
            if sum_chars and len(sum_text) > sum_chars:
                sum_text = budget.trim_markdown_block(sum_text, sum_chars, keep_tail=True).strip()

    name = cfg.get("name") or "book"
    if style_only:
        mode_desc = "纯文风脱敏包（仅文风语料与句法习惯，剥离原书剧情设定与人物关系）"
        body = ex_text + "\n"
        default_out = os.path.join(out_dir, "纯文风包.md")
    else:
        mode_desc = "同人 / IF 完整合并包（上半部：事实与设定锁｜下半部：文风与对话例子，紧贴创作 Prompt）"
        compact_sum = _compact_ban_section(sum_text)
        body = (
            compact_sum.strip()
            + "\n\n"
            + "=" * 60
            + "\n\n"
            + ex_text.strip()
            + "\n"
        )
        default_out = os.path.join(out_dir, "参考包.md")

    def make_header(full_body):
        total_kb = budget.utf8_kb(full_body)
        total_chars = len(full_body)
        total_toks = budget.estimate_tokens(full_body)
        lines = [
            "# 《%s》%s" % (name, "纯文风参考包" if style_only else "写作参考包（设定 + 文风）"),
            "",
            "> **模式**：%s" % mode_desc,
            "> **总容量**：`%.1f KB` ｜ **总字符**：`%s` ｜ **估算总 Tokens**：`~%s tokens`" % (
                total_kb, format(total_chars, ","), format(total_toks, ",")
            ),
        ]
        if not style_only:
            ekb = budget.utf8_kb(ex_text)
            etoks = budget.estimate_tokens(ex_text)
            skb = budget.utf8_kb(sum_text)
            stoks = budget.estimate_tokens(sum_text)
            denom = max(0.01, ekb + skb)
            lines.append(
                "> **构成明细**：文风例子部分 `%.1f KB`（`~%s tokens`，占 `%.1f%%`） + 整书总结部分 `%.1f KB`（`~%s tokens`，占 `%.1f%%`）" % (
                    ekb, format(etoks, ","), ekb / denom * 100.0,
                    skb, format(stoks, ","), skb / denom * 100.0,
                )
            )
        if not binfo.get("unlimited"):
            lines.append(
                "> **预算档位**：`%s`（目标总计 `%.0f KB`，比例 `%.0f%% : %.0f%%`）" % (
                    binfo.get("preset", "custom"),
                    binfo.get("total_kb") or 0,
                    binfo.get("example_ratio", 0.7) * 100.0,
                    binfo.get("summary_ratio", 0.3) * 100.0,
                )
            )
        else:
            lines.append("> **预算档位**：`full`（全量无损）")
        lines.extend(["", "---", ""])
        return "\n".join(lines)

    # 两遍渲染使头部看板里的总体积与最终写入文件完全一致
    draft = make_header(body) + body
    final_text = make_header(draft) + body

    out_path = a.out or default_out
    textio.write_text(out_path, final_text)

    total_kb = budget.utf8_kb(final_text)
    total_chars = len(final_text)
    total_toks = budget.estimate_tokens(final_text)
    print("合并参考包完成：%s" % ("纯文风包" if style_only else "完整参考包"))
    print("  总计：%.1f KB ｜ %s 字 ｜ ~%s tokens" % (
        total_kb, format(total_chars, ","), format(total_toks, ",")
    ))
    if not style_only:
        ekb = budget.utf8_kb(ex_text)
        etoks = budget.estimate_tokens(ex_text)
        skb = budget.utf8_kb(sum_text)
        stoks = budget.estimate_tokens(sum_text)
        denom = max(0.01, ekb + skb)
        print("  例子：%.1f KB ｜ ~%s tokens ｜ 占 %.1f%%" % (ekb, format(etoks, ","), ekb / denom * 100.0))
        print("  摘要：%.1f KB ｜ ~%s tokens ｜ 占 %.1f%%" % (skb, format(stoks, ","), skb / denom * 100.0))
    print("→ %s" % out_path)


if __name__ == "__main__":
    main()
