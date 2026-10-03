#!/usr/bin/env bash
# 一把跑完（摘要阶段很耗时，建议先分段跑，中途断掉直接重跑本脚本，已完成的会跳过）
#
#   bash scripts/12_run_all.sh              # 全跑
#   bash scripts/12_run_all.sh --no-llm     # 只跑不花钱的部分（抽文本→分片→建索引→验收）
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY="${PY:-python}"

echo "=== 0 抽文本 ===";        $PY -X utf8 scripts/00_extract.py "$@"
echo "=== 1 分片 ===";          $PY -X utf8 scripts/01_split.py
if [ "${1:-}" != "--no-llm" ]; then
  echo "=== 2 一层摘要（并发）==="; $PY -X utf8 scripts/02_run_notes.py
fi
echo "=== 3 汇总 + 覆盖率校验 ==="; $PY -X utf8 scripts/03_merge_notes.py
echo "=== 4 卷映射 ===";        $PY -X utf8 scripts/04_build_volume_map.py
if [ "${1:-}" != "--no-llm" ]; then
  echo "=== 5 二层归纳 ===";    $PY -X utf8 scripts/05_run_volumes.py
  echo "=== 5b 元章节 ===";     $PY -X utf8 scripts/05_run_volumes.py --meta
fi
echo "=== 6 台词归属 ===";      $PY -X utf8 scripts/06_build_attrib.py
echo "=== 7 文风索引 ===";      $PY -X utf8 scripts/07_stylefit_index.py
echo "=== 8 例子集 ===";        $PY -X utf8 scripts/09_build_examples.py
echo "=== 9 整书总结 ===";      $PY -X utf8 scripts/10_build_summary.py
echo
echo "产物："
ls -la out/ 2>/dev/null || true
echo "验收你自己的稿子：python scripts/11_verify.py --text <稿子>"
