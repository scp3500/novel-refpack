#!/usr/bin/env bash
# 一把跑完。摘要阶段很耗时，建议先分段跑；中途断掉直接重跑本脚本，已完成的会跳过。
#
#   bash scripts/12_run_all.sh              # 全跑
#   bash scripts/12_run_all.sh --no-llm     # 只跑不花钱的部分（抽文本→分片→建索引→两份成品）
#   PAR=32 bash scripts/12_run_all.sh       # 覆盖并发数
#
# 环境变量：PY（python 命令，默认 python）、PAR（并发数，默认用 config 里的值）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY="${PY:-python}"
SKIP_LLM=0
for arg in "$@"; do
  [ "$arg" = "--no-llm" ] && SKIP_LLM=1
done

run() { echo "=== $1 ==="; shift; "$PY" -X utf8 "$@"; }

run "0 抽文本"            scripts/00_extract.py
run "1 分片"              scripts/01_split.py
if [ "$SKIP_LLM" = 0 ]; then
  run "2 一层摘要（并发，一片一个任务）" scripts/02_run_notes.py ${PAR:+--par "$PAR"}
fi
run "3 汇总 + 片尾覆盖率校验" scripts/03_merge_notes.py
run "4 卷映射"            scripts/04_build_volume_map.py
if [ "$SKIP_LLM" = 0 ]; then
  run "5 二层卷纪要（并发）" scripts/05_run_volumes.py ${PAR:+--par "$PAR"}
  run "5b 元章节（世界观/角色/势力/结局/伏笔）" scripts/05_run_volumes.py --meta
fi
run "6 台词归属"          scripts/06_build_attrib.py
run "7 文风索引"          scripts/07_stylefit_index.py
run "8 生成例子集"        scripts/09_build_examples.py
run "9 生成整书总结"      scripts/10_build_summary.py

echo
echo "产物："
ls -la work/out/ 2>/dev/null || true
echo
echo "验收你自己的稿子：python scripts/11_verify.py --text <稿子>"
