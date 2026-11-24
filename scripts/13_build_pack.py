#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 13 · 一键合并《整书总结》+《例子集》，生成单文件参考包并输出统计看板。

  python scripts/13_build_pack.py
  python scripts/13_build_pack.py --preset compact
  python scripts/13_build_pack.py --style-only --anonymize
  python scripts/13_build_pack.py --style-only --emit-both
  python scripts/13_build_pack.py --no-rebuild
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import budget, project, textio      # noqa: E402


BAN_SEC_RE = re.compile(
    r"(^##\s+0\.5\s+禁区[^\n]*\n)(.*?)(?=\n(?:---|# |\## )|\Z)",
    re.MULTILINE | re.DOTALL,
)

ANTI_PASTE_GUARDRAIL = (
    "> **防照抄护栏**：严禁直接复用、拼接或仅替换主语地照抄本包例句；"
    "仅学习句长分布、标点节奏、实词搭配、本书高频特征词与心理转折方式。"
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


def _style_cli_args(style_only, anonymize, anonymize_style=None):
    args = []
    if style_only:
        args.append("--style-only")
    if anonymize:
        args.append("--anonymize")
    else:
        args.append("--no-anonymize")
    if anonymize and anonymize_style:
        args += ["--anonymize-style", anonymize_style]
    return args


def _run_py(script_name, extra_args):
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script_name)] + list(extra_args)
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit("%s 执行失败（exit %s）" % (script_name, proc.returncode))


def _render_and_write_pack(cfg, binfo, style_only, anonymize, ex_text, sum_text, out_path):
    name = cfg.get("name") or "book"
    if style_only:
        mode_desc = (
            "纯文风脱敏包（仅文风语料与句法习惯，剥离原书剧情设定与人物关系）"
            if anonymize else
            "纯文风参考包（保留原名对照，仅蒸馏文风语料与句法习惯，剥离原书剧情设定）"
        )
        body = ex_text + "\n"
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

    def make_header(full_body):
        total_kb = budget.utf8_kb(full_body)
        total_chars = len(full_body)
        total_toks = budget.estimate_tokens(full_body)
        lines = [
            "# 《%s》%s" % (name, "纯文风参考包" if style_only else "写作参考包（设定 + 文风）"),
            "",
            "> **模式**：%s" % mode_desc,
            ANTI_PASTE_GUARDRAIL,
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
    print("→ %s" % os.path.normpath(out_path))


def _build_one_examples(cfg_args, b_args, style_only, anonymize, anon_style, target_ex_path):
    s_args = _style_cli_args(style_only, anonymize, anon_style)
    _run_py("09_build_examples.py", cfg_args + b_args + s_args + ["--out", target_ex_path])
    return textio.read_text(target_ex_path).strip()


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="合并生成单文件参考包（整书总结 + 典型例子集）")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--examples-out", default=None,
                    help="显式指定中间例子集输出路径（打包自定义 --out 时默认用临时文件，不覆写 work/out/例子.txt）")
    budget.add_budget_args(ap)
    ap.add_argument("--style-only", action="store_true", help="只输出纯文风脱敏包（跳过整书总结）")
    ap.add_argument("--anonymize", action="store_true", help="将人名脱敏为中性代称")
    ap.add_argument("--no-anonymize", action="store_true", help="禁用人名脱敏")
    ap.add_argument("--anonymize-style", choices=["neutral", "names"], default=None,
                    help="脱敏代称风格：neutral（某甲/某乙）或 names（林远/苏晴/陈默）")
    ap.add_argument("--emit-both", action="store_true",
                    help="纯文风模式一键同时产出脱敏版（纯文风包.md）与原名对照版（纯文风包_原名版.md），互不串台")
    ap.add_argument("--no-rebuild", action="store_true", help="不重跑 09/10，直接读取现有产物按预算合并")
    ap.add_argument("--yes", "-y", action="store_true", help="跳过交互式规模确认提示")
    ap.add_argument("--ask-size", action="store_true", help="主动交互询问目标产物大小（KB / 档位）")
    a = ap.parse_args()

    cfg = project.load(a.config)
    budget.prompt_budget_interactive(a, cfg, force=a.ask_size)

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
    anon_style = a.anonymize_style or cfg.get("anonymize_style") or "neutral"
    out_dir = cfg["paths"]["out"]
    os.makedirs(out_dir, exist_ok=True)
    default_ex_path = os.path.join(out_dir, "例子.txt")
    sum_path = os.path.join(out_dir, "整书总结.md")

    # --emit-both：一键同时产出脱敏版与原名对照版，互不串台
    if a.emit_both:
        if not style_only:
            style_only = True
            binfo = budget.resolve_budget(
                cfg, preset=a.preset, kb=a.kb, max_tokens=a.max_tokens,
                ratio=a.ratio if a.ratio is not None else None, style_only=True,
            )
        base_out = a.out or os.path.join(out_dir, "纯文风包.md")
        stem, ext = os.path.splitext(base_out)
        orig_out = stem + "_原名版" + (ext or ".md")

        # 脱敏版可同步更新默认例子集（若未自定义 --out），原名版始终走隔离临时路径避免覆写
        ex_anon_path = a.examples_out or (default_ex_path if not a.out else None)
        tmp_files = []
        try:
            if not ex_anon_path:
                fd, ex_anon_path = tempfile.mkstemp(prefix=".ex_anon_", suffix=".txt", dir=out_dir)
                os.close(fd)
                tmp_files.append(ex_anon_path)
            ex_anon = _build_one_examples(cfg_args, b_args, True, True, anon_style, ex_anon_path)
            _render_and_write_pack(cfg, binfo, True, True, ex_anon, "", base_out)

            fd2, ex_orig_path = tempfile.mkstemp(prefix=".ex_orig_", suffix=".txt", dir=out_dir)
            os.close(fd2)
            tmp_files.append(ex_orig_path)
            ex_orig = _build_one_examples(cfg_args, b_args, True, False, anon_style, ex_orig_path)
            _render_and_write_pack(cfg, binfo, True, False, ex_orig, "", orig_out)
        finally:
            for tf in tmp_files:
                try:
                    if os.path.isfile(tf):
                        os.unlink(tf)
                except OSError:
                    pass
        return

    if a.no_anonymize:
        anonymize = False
    elif a.anonymize or cfg.get("anonymize") or style_only:
        anonymize = True
    else:
        anonymize = False

    default_out = os.path.join(out_dir, "纯文风包.md" if style_only else "参考包.md")
    out_path = os.path.normpath(a.out or default_out)
    is_custom_out = bool(a.out) and (os.path.normpath(a.out) != os.path.normpath(default_out))

    tmp_ex = None
    try:
        if not a.no_rebuild:
            if a.examples_out:
                ex_path = a.examples_out
            elif is_custom_out:
                # 打包自定义 --out 时将中间例子写入临时路径，绝不覆写已有的 work/out/例子.txt
                fd, tmp_ex = tempfile.mkstemp(prefix=".ex_tmp_", suffix=".txt", dir=out_dir)
                os.close(fd)
                ex_path = tmp_ex
            else:
                ex_path = default_ex_path
            ex_text = _build_one_examples(cfg_args, b_args, style_only, anonymize, anon_style, ex_path)
            if not style_only:
                _run_py("10_build_summary.py", cfg_args + b_args)
        else:
            ex_path = a.examples_out or default_ex_path
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

        _render_and_write_pack(cfg, binfo, style_only, anonymize, ex_text, sum_text, out_path)
    finally:
        if tmp_ex and os.path.isfile(tmp_ex):
            try:
                os.unlink(tmp_ex)
            except OSError:
                pass


if __name__ == "__main__":
    main()
