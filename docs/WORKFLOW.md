# 完整工作流水线

本项目流水线将长篇语料逐级提炼为《整书总结.md》《例子.txt》及合并单文件《参考包.md》（或纯文风脱敏《纯文风包.md》）。

---

## 流水线全貌

- **完整同人/IF 模式（默认）**：`00 → 01 → 02(LLM) → 03 → 04 → 05(LLM) → 06 → 07 → 09 → 10 → 13`，最终产出 `整书总结.md`、`例子.txt` 与合并后的 `参考包.md`（默认 `standard` 150KB，例子 70% : 摘要 30%）。
- **纯文风快速模式（`--style-only --anonymize`）**：`00 → 01 → (06，可选) → 07 → 09 → 13`，跳过全部 LLM 摘要与卷映射，纯离线几秒生成脱敏 `纯文风包.md`。
- **四层验收（`11_verify.py`）**：可选质检工具，默认不跑，需要定量核对生成稿件与原作 4-gram 贴合度时手动执行。

```
原始语料 ──00_extract──► work/raw/_all.txt ──01_split──► work/chunks/ + manifest.json
                                                        │
        ┌───────────────────────────────────────────────┴────────────────────┐
        ▼ (同人/IF 完整模式)                                                 ▼ (纯文风快速模式 --style-only)
  02_run_notes → 03_merge → 04_volume_map → 05_run_volumes(--meta)           │
        │                                                                    │
        ├──► 10_build_summary (按预算分级保序裁剪) ──► 整书总结.md            │
        │                                                                    ▼
        └──► 06_build_attrib → 07_stylefit_index ──► 09_build_examples ──► 例子.txt
                                                            │                │
                                                            └────► 13_build_pack ──► 参考包.md / 纯文风包.md
```

一键执行：
- 跨平台 Python：`python -X utf8 scripts/12_run_all.py [--style-only --anonymize] [--preset standard] [--kb N] [--ratio 0.7]`
- Bash 环境：`bash scripts/12_run_all.sh [--style-only] [--no-llm]`

---

## 各阶段核心说明

### Stage 0 · 文本抽取（`scripts/00_extract.py`）
- 支持 `.epub` / `.docx` / `.txt`，保留 `# / ## / ###` 标题层级并生成 `work/raw/_all.txt` 与精确字符偏移 `sections.json`（含叶子 `div`/`li` 提取与嵌套去重）。

### Stage 1 · 语义分片（`scripts/01_split.py`）
- 按 `chunk_chars`（默认 60,000 字）吸附 `h2/h3` 边界切片，严禁跨 `h1`，清理陈旧 `chunk_*.txt` 并写入带字符区间 `start/end` 的 `work/manifest.json`。

### Stage 2~5 · 分片摘要、合并校验、卷映射与卷纪要
- `02_run_notes.py`：单片一任务并发摘要（支持 `openai` 与 `command` 后端）。
- `03_merge_notes.py`：拼接 `all_notes.md` 并检验片尾特征词覆盖率防跳读。
- `04_build_volume_map.py`：按偏移精确映射卷与分片；遇到无 `h2/h3/h1` 的纯白板 TXT 时自动按 `manifest.json` 分片生成虚拟卷兜底。
- `05_run_volumes.py`：分卷归纳（`notes/vol/vol_NN.md`）与 `--meta` 六大元档案提炼（超限材料按卷均摊保首尾）。

### Stage 6~7 · 台词归属与文风索引
- `06_build_attrib.py`：严格单主语规则提取说话人，支持 `aliases` 别名归并（`--style-only` 时若未配 `names` 则自动跳过交由 Stage 7 兜底）。
- `07_stylefit_index.py` / `stylefit/build_index.py`：统计 18 类搭配、18 类描写意图完整句群（最多 24 条/类）、去重叠场景片段（最多 18 段/类）、5 类「笔法细节」（连续动作白描/五感环境/对话穿插动作/开篇转场/克制留白短段，最多 25 条/类）与零频黑名单。

### Stage 9 · 生成例子集（`scripts/09_build_examples.py`）
- 根据 `--preset` / `--kb` / `--max-tokens` / `--ratio` 自动伸缩各节采样深度与预算权重裁剪；
- 支持 `--style-only`（剥离名场面、分期、标题、分剧本语料，台词改为去角色化的功能桶范例）与 `--anonymize`（人名脱敏为 `某甲/某乙……`，`【条目框】` 替换为「某技能/条目」）。

### Stage 10 · 生成整书总结（`scripts/10_build_summary.py`）
- 预算未超限或 `full` 档位时无损全保；超限时按三级优先级保序压缩（优先保 `〇 续写速查` 结局锚点，其次 `上篇/附录`，最后对 `下篇` 按第 1 卷和末 2 卷高权重分配并保留卷末状态快照）。

### Stage 13 · 合并参考包（`scripts/13_build_pack.py`）
- 将《整书总结》前置、《例子集》后置（去除重复禁区段落），输出 `work/out/参考包.md`（或 `--style-only` 下的 `纯文风包.md`），顶部与控制台展示精确 **KB、字符数、估算 Tokens 及例子/摘要占比**。
