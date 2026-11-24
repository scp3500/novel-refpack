#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键运行完整流水线（跨平台纯 Python 版本，兼容 Windows / macOS / Linux）。

使用方式：
  python scripts/12_run_all.py                  # 全跑
  python scripts/12_run_all.py --no-llm         # 只跑离线计算（抽文本→分片→建索引→两份成品）
  python scripts/12_run_all.py --style-only --anonymize --kb 120
  python scripts/12_run_all.py --par 32         # 覆盖并发数
  python scripts/12_run_all.py --config my.json # 指定配置文件

环境变量：
  PAR              并发数（默认用 config 里的 llm.concurrency）
  REFPACK_CONFIG   配置文件路径（默认 config/project.json）
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import budget, project, textio      # noqa: E402


def run_step(desc, script_name, *args, env=None):
    print("\n=== %s ===" % desc, flush=True)
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script_name)] + list(args)
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    if proc.returncode != 0:
        sys.stderr.write("\n[失败] 步骤「%s」异常退出（exit %s）\n" % (desc, proc.returncode))
        sys.exit(proc.returncode)


def main():
    textio.ensure_utf8_stdio()
    if sys.version_info < (3, 9):
        sys.stderr.write("需要 Python 3.9+，当前版本：%s\n" % sys.version)
        sys.exit(2)

    parser = argparse.ArgumentParser(description="一键运行 novel-refpack 流水线")
    parser.add_argument("--no-llm", action="store_true", help="只跑不调模型的步骤")
    parser.add_argument("--par", type=int, default=None, help="并发任务数")
    parser.add_argument("--config", default=None, help="指定 project.json 路径")
    budget.add_budget_args(parser)
    parser.add_argument("--style-only", action="store_true", help="纯文风模式：跳过 LLM 摘要与卷映射，直接提取脱敏文风包")
    parser.add_argument("--anonymize", action="store_true", help="人名脱敏为中性代称")
    parser.add_argument("--no-anonymize", action="store_true", help="禁用人名脱敏")
    parser.add_argument("--anonymize-style", choices=["neutral", "names"], default=None,
                        help="脱敏代称风格：neutral（某甲/某乙）或 names（林远/苏晴/陈默）")
    parser.add_argument("--emit-both", action="store_true",
                        help="纯文风模式同时输出脱敏版与原名对照版（互不串台）")
    parser.add_argument("--prewarm-verify", action="store_true",
                        help="流水线结束前自动预热 verify_cache.pkl，避免首次验稿等待")
    parser.add_argument("--wiki", action="store_true",
                        help="额外在 work/wiki/ 生成面向本地 Coding Agent 按需阅读的互联 Wiki 目录（默认单文件打包不受影响）")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互式规模确认提示")
    parser.add_argument("--ask-size", action="store_true", help="主动交互询问目标产物大小（KB / 档位）")
    args = parser.parse_args()

    env = dict(os.environ)
    if args.config:
        env["REFPACK_CONFIG"] = os.path.abspath(args.config)
    par_arg = []
    if args.par is not None:
        par_arg = ["--par", str(args.par)]
    elif "PAR" in env and env["PAR"].strip():
        par_arg = ["--par", env["PAR"].strip()]

    cfg_arg = ["--config", env["REFPACK_CONFIG"]] if "REFPACK_CONFIG" in env else []

    cfg = {}
    try:
        cfg = project.load(env.get("REFPACK_CONFIG"))
    except SystemExit:
        pass

    # 交互终端未显式指定文件大小时，主动询问目标规模（KB / 档位）
    budget.prompt_budget_interactive(args, cfg, force=args.ask_size)

    style_only = bool(args.style_only or cfg.get("style_only"))

    budget_args = []
    if args.preset:
        budget_args += ["--preset", args.preset]
    if args.kb is not None:
        budget_args += ["--kb", str(args.kb)]
    if args.max_tokens is not None:
        budget_args += ["--max-tokens", str(args.max_tokens)]
    if args.ratio is not None:
        budget_args += ["--ratio", str(args.ratio)]

    style_args = []
    if style_only:
        style_args.append("--style-only")
    if args.anonymize:
        style_args.append("--anonymize")
    elif args.no_anonymize:
        style_args.append("--no-anonymize")
    if args.anonymize_style:
        style_args += ["--anonymize-style", args.anonymize_style]

    pack_extra = ["--yes"]
    if args.emit_both:
        pack_extra.append("--emit-both")

    # 0 抽文本
    run_step("0 抽文本", "00_extract.py", *cfg_arg, env=env)

    # 1 分片
    run_step("1 分片", "01_split.py", *cfg_arg, env=env)

    if style_only:
        # 纯文风快速链路：全程不跑 LLM 摘要与卷映射
        has_names = bool(cfg.get("names") or cfg.get("aliases"))
        if has_names:
            run_step("6 台词归属", "06_build_attrib.py", *cfg_arg, env=env)
        else:
            print("\n=== 6 台词归属（已跳过：未配置 names/aliases，交由 07 自动识别说话人） ===", flush=True)

        run_step("7 文风索引", "07_stylefit_index.py", *cfg_arg, env=env)
        if args.emit_both:
            run_step("8 生成双版本纯文风单文件包", "13_build_pack.py", *(cfg_arg + budget_args + style_args + pack_extra), env=env)
        else:
            run_step("8 生成纯文风例子集", "09_build_examples.py", *(cfg_arg + budget_args + style_args), env=env)
            run_step("9 生成纯文风单文件包", "13_build_pack.py", *(["--no-rebuild"] + cfg_arg + budget_args + style_args + pack_extra), env=env)
    else:
        # 2 一层摘要
        if not args.no_llm:
            run_step("2 一层摘要（并发，一片一个任务）", "02_run_notes.py", *(cfg_arg + par_arg), env=env)

        # 3 汇总 + 校验
        run_step("3 汇总 + 片尾覆盖率校验", "03_merge_notes.py", *cfg_arg, env=env)

        # 4 卷映射
        run_step("4 卷映射", "04_build_volume_map.py", *cfg_arg, env=env)

        # 5 二层卷纪要与元章节
        if not args.no_llm:
            run_step("5 二层卷纪要（并发）", "05_run_volumes.py", *(cfg_arg + par_arg), env=env)
            run_step("5b 元章节（世界观/角色/势力/结局/伏笔）", "05_run_volumes.py", *(["--meta"] + cfg_arg + par_arg), env=env)

        # 6 台词归属
        run_step("6 台词归属", "06_build_attrib.py", *cfg_arg, env=env)

        # 7 文风索引
        run_step("7 文风索引", "07_stylefit_index.py", *cfg_arg, env=env)

        # 8 生成例子集
        run_step("8 生成例子集", "09_build_examples.py", *(cfg_arg + budget_args + style_args), env=env)

        # 9 生成整书总结
        run_step("9 生成整书总结", "10_build_summary.py", *(cfg_arg + budget_args), env=env)

        # 10 合并生成参考包
        run_step("10 合并生成参考包", "13_build_pack.py", *(["--no-rebuild"] + cfg_arg + budget_args + style_args + pack_extra), env=env)

    if args.wiki:
        run_step("额外生成 Agent Wiki 目录", "13c_build_wiki.py", *(cfg_arg + style_args), env=env)

    if args.prewarm_verify:
        run_step("预热验稿缓存（verify_cache.pkl）", "11_verify.py", *(["--prewarm"] + cfg_arg), env=env)

    # 产物概览
    out_dir = os.path.normpath(cfg.get("paths", {}).get("out") or os.path.join(ROOT, "work", "out"))
    print("\n产物目录：%s" % out_dir)
    if os.path.isdir(out_dir):
        for f in sorted(os.listdir(out_dir)):
            fp = os.path.join(out_dir, f)
            if not os.path.isfile(fp):
                continue
            if f.endswith((".md", ".txt")):
                txt = textio.read_text(fp)
                print("  - %s (%.1f KB | ~%s tokens)" % (
                    f, budget.utf8_kb(txt), format(budget.estimate_tokens(txt), ",")
                ))
            else:
                size = os.path.getsize(fp)
                print("  - %s (%d bytes)" % (f, size))
    print("\n验收你自己的稿子：python scripts/11_verify.py --text <你的稿子.txt>")


if __name__ == "__main__":
    main()
