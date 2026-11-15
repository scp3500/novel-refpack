#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_run.py
群聊 / 贴吧语料提示词逆向蒸馏流水线一键运行入口。

使用方式：
  python scripts/chat_run.py --tieba 弱智吧 --no-llm     # 指定吧名，一键从贴吧在线拉取并蒸馏人设
  python scripts/chat_run.py                            # 读取默认配置（本地文件）
  python scripts/chat_run.py --no-llm                   # 离线运行
  python scripts/chat_run.py --config config/chat.json  # 指定配置文件
"""
import os
import sys
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project      # noqa: E402


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

    parser = argparse.ArgumentParser(description="一键运行群聊/贴吧提示词逆向蒸馏流水线")
    parser.add_argument("--tieba", default=None, help="在线拉取指定贴吧（如：弱智吧、孙笑川吧）")
    parser.add_argument("--count", type=int, default=25, help="拉取主题帖数量 (默认 25)")
    parser.add_argument("--no-llm", action="store_true", help="纯离线运行，不调用外部模型 API")
    parser.add_argument("--config", default=None, help="指定配置文件路径")
    args = parser.parse_args()

    env = dict(os.environ)
    cfg_arg = ["--config", args.config] if args.config else []
    cfg = project.load_chat_config(args.config)
    work_dir = project.chat_work_dir(cfg)

    source_arg = []
    role_name = "贴吧老哥/群友"
    out_file = os.path.join(work_dir, "out", "群聊人设提示词.md")

    # 0. 如果指定了贴吧，先在线抓取
    if args.tieba:
        forum = args.tieba.replace("吧", "")
        role_name = f"{forum}吧老哥"
        raw_json = os.path.join(work_dir, f"tieba_{forum}.json")
        out_file = os.path.join(work_dir, "out", f"{forum}吧人设提示词.md")

        fetch_args = ["--tieba", forum, "--count", str(args.count), "--out", raw_json] + cfg_arg
        run_step(f"0 在线拉取【{forum}吧】语料", "chat_fetch_tieba.py", *fetch_args, env=env)
        source_arg = ["--source", raw_json]

    # 1. 清洗与会话重组
    run_step("1 清洗与会话重组", "chat_00_clean.py", *(cfg_arg + source_arg), env=env)

    # 2. 统计排版与节奏硬指标
    run_step("2 统计语言节奏与标点指纹", "chat_01_metrics.py", *cfg_arg, env=env)

    # 3. 行为与心理模式蒸馏
    distill_args = list(cfg_arg)
    if args.no_llm:
        distill_args.append("--no-llm")
    run_step("3 蒸馏交互心理与行为逻辑", "chat_02_distill.py", *distill_args, env=env)

    # 4. 组装生成提示词文件
    build_args = list(cfg_arg) + ["--name", role_name, "--out", out_file]
    run_step("4 自动总装生成人设提示词", "chat_03_build_prompt.py", *build_args, env=env)

    print("\n" + "=" * 50)
    print("流水线全部执行完毕！")
    print("交付产物已生成：%s" % out_file)
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
