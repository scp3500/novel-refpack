#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键运行完整流水线（跨平台纯 Python 版本，兼容 Windows / macOS / Linux）。

使用方式：
  python scripts/12_run_all.py                  # 全跑
  python scripts/12_run_all.py --no-llm         # 只跑离线计算（抽文本→分片→建索引→两份成品）
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


def run_step(desc, script_name, *args, env=None):
    print("\n=== %s ===" % desc, flush=True)
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script_name)] + list(args)
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    if proc.returncode != 0:
        sys.stderr.write("\n[失败] 步骤「%s」异常退出（exit %s）\n" % (desc, proc.returncode))
        sys.exit(proc.returncode)


def main():
    if sys.version_info < (3, 9):
        sys.stderr.write("需要 Python 3.9+，当前版本：%s\n" % sys.version)
        sys.exit(2)

    parser = argparse.ArgumentParser(description="一键运行 novel-refpack 流水线")
    parser.add_argument("--no-llm", action="store_true", help="只跑不调模型的步骤")
    parser.add_argument("--par", type=int, default=None, help="并发任务数")
    parser.add_argument("--config", default=None, help="指定 project.json 路径")
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

    # 0 抽文本
    run_step("0 抽文本", "00_extract.py", *cfg_arg, env=env)

    # 1 分片
    run_step("1 分片", "01_split.py", *cfg_arg, env=env)

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
        run_step("5b 元章节（世界观/角色/势力/结局/伏笔）", "05_run_volumes.py", "--meta", *cfg_arg, env=env)

    # 6 台词归属
    run_step("6 台词归属", "06_build_attrib.py", *cfg_arg, env=env)

    # 7 文风索引
    run_step("7 文风索引", "07_stylefit_index.py", *cfg_arg, env=env)

    # 8 生成例子集
    run_step("8 生成例子集", "09_build_examples.py", *cfg_arg, env=env)

    # 9 生成整书总结
    run_step("9 生成整书总结", "10_build_summary.py", *cfg_arg, env=env)

    # 产物概览
    out_dir = os.path.join(ROOT, "work", "out")
    print("\n产物目录：%s" % out_dir)
    if os.path.isdir(out_dir):
        for f in sorted(os.listdir(out_dir)):
            fp = os.path.join(out_dir, f)
            size = os.path.getsize(fp)
            print("  - %s (%d bytes)" % (f, size))
    print("\n验收你自己的稿子：python scripts/11_verify.py --text <你的稿子.txt>")


if __name__ == "__main__":
    main()
