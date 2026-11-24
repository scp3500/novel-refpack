# 完整工作流水线

本项目流水线将长篇语料（小说 / 剧本 / 字幕）逐级提炼为《整书总结.md》《例子.txt》及合并单文件《参考包.md》（或纯文风脱敏《纯文风包.md》）。

> **启动前先确认输出规模（KB / Token 档位）**
>
> - **AI Agent / 助手调用**：在执行流水线前，**必须先主动询问用户期望的输出大小**：`compact (~60 KB / ~1.6 万 tokens)`、`standard (~150 KB / ~4 万 tokens，默认)`、`rich (~300 KB / ~8 万 tokens)`、`full (全量不裁剪)` 或自定义 `--kb <数字>`。
> - **命令行交互调用**：若运行 `12_run_all.py` 或 `13_build_pack.py` 时处于交互式终端且未显式传入 `--preset` / `--kb` / `--max-tokens`，脚本会自动询问目标档位或 KB 大小；批处理/非交互脚本可加 `--yes` 或显式传参跳过提问。

---

## 流水线全貌

- **完整同人/IF 模式（默认）**：`00 → 01 → 02(LLM) → 03 → 04 → 05(LLM) → 06 → 07 → 09 → 10 → 13`，最终产出 `整书总结.md`、`例子.txt` 与合并后的 `参考包.md`（默认 `standard` 150KB，例子 70% : 摘要 30%）。
- **纯文风快速模式（`--style-only --anonymize`）**：`00 → 01 → (06b 候选扫描 / 06 归属，可选) → 07 → 09 → 13`，跳过全部 LLM 摘要与卷映射，纯离线几秒生成脱敏 `纯文风包.md`（内置目标书高频特征词表）。
- **辅助发现 / 混搭 / 可选 Agent Wiki / 验收工具**：`06b_suggest_entities.py`（自动找人名专名）、`07b_discover_style.py`（零配置风格探索）、`08_stylefit_query.py`（写前查高频词/搭配/导提示卡）、`13b_blend_style.py`（多书混搭）、`13c_build_wiki.py`（**可选**，仅面向本地 Coding Agent 按需阅读的 `work/wiki/` 目录与 `--check-stale` 陈旧检测）、`11_verify.py`（第 0–4 层验收、改稿指南、版本 diff 与 HTML 报告）。

```
原始语料 ──00_extract──► work/raw/_all.txt ──01_split──► work/chunks/ + manifest.json
(EPUB/DOCX/TXT/SRT/ASS/Gal)                              │
        ┌────────────────────────────────────────────────┴────────────────────┐
        ▼ (同人/IF 完整模式)                                                  ▼ (纯文风快速模式 --style-only)
  02_run_notes → 03_merge → 04_volume_map → 05_run_volumes(--meta)      (06b_suggest_entities / 07b_discover_style)
        │                                                                     │
        ├──► 10_build_summary (按预算分级保序裁剪) ──► 整书总结.md              │
        │                                                                     ▼
        └──► 06_build_attrib → 07_stylefit_index ──► 09_build_examples ──► 例子.txt
                                  │                        │                  │
                                  ▼                        └─────► 13_build_pack ──► 参考包.md / 纯文风包.md
                           08_stylefit_query                         │
                        (--top-words/--export-card)                  ├──► 13b_blend_style (多书混搭)
                                                                     └──► 11_verify (--guide/--diff/--html/--cross-domain)
```

一键执行：
- 跨平台 Python：`python -X utf8 scripts/12_run_all.py [--style-only --anonymize] [--preset standard | --kb N] [--ratio 0.7] [--wiki] [--prewarm-verify] [--yes]`
- Bash 环境：`bash scripts/12_run_all.sh [--style-only] [--no-llm]`

---

## 各阶段核心说明

### Stage 0 · 文本抽取（`scripts/00_extract.py`）
- 支持 `.epub` / `.docx` / `.txt`，并扩展支持 **`.srt` / `.ass` 字幕**与常见 **Galgame 脚本文本**（自动剥离时间轴与控制标签）；
- 保留 `# / ## / ###` 标题层级并生成 `work/raw/_all.txt` 与精确字符偏移 `sections.json`（含叶子 `div`/`li` 提取、嵌套去重，以及 **EPUB TOC 目录回退补全标题**）；
- 支持 `drop_builtin_meta`（默认自动剔除版权/奥付/问卷/目次/后记页）与 `drop_headings` / `drop_file_patterns` / `drop_text_patterns` / `drop_line_patterns` 多维净水清洗。

### Stage 1 · 语义分片（`scripts/01_split.py`）
- 按 `chunk_chars`（默认 60,000 字）吸附 `h2/h3` 边界切片，严禁跨 `h1`，清理陈旧 `chunk_*.txt` 并写入带字符区间 `start/end` 的 `work/manifest.json`。

### Stage 2~5 · 分片摘要、合并校验、卷映射与卷纪要
- `02_run_notes.py`：单片一任务并发摘要（支持 `openai` 与 `command` 后端）。
- `03_merge_notes.py`：拼接 `all_notes.md` 并检验片尾特征词覆盖率防跳读。
- `04_build_volume_map.py`：按偏移精确映射卷与分片；遇到无 `h2/h3/h1` 的纯白板 TXT 时自动按 `manifest.json` 分片生成虚拟卷兜底。
- `05_run_volumes.py`：分卷归纳（`notes/vol/vol_NN.md`）与 `--meta` 六大元档案提炼（超限材料按卷均摊保首尾）。

### Stage 6 & 6b · 实体候选扫描与台词归属
- `06b_suggest_entities.py`：离线扫描语料中的高频人名、单字名候选与地名/组织专名，辅助快速填写 `names`、`aliases`、`anonymize_terms` 与 `single_char_names`。
- `06_build_attrib.py`：严格单主语规则提取说话人，支持 `aliases` 别名归并（`--style-only` 时若未配 `names` 则自动跳过交由 Stage 7 兜底）。

### Stage 7, 7b & 8 · 文风索引、零配置发现与写前查询
- `07_stylefit_index.py` / `stylefit/build_index.py`：读取 `stylefit_dir`（支持 `general` / `modern` / `fantasy` / `tieba` 预设或自定义目录），统计搭配表、描写意图完整句群、去重叠场景片段、5 类「笔法细节」、零频黑名单，并**自动提取目标书高频特征词表写入 `index.json["高频词"]`**。
- `07b_discover_style.py`：无需预先配置词典，自动从语料发现高区分度高频词、特征动词、连接词与句式习惯。
- `08_stylefit_query.py`：写前速查工具，新增 `--top-words`（直接输出目标书高频特征词表）与 `--export-card <out.md>`（一键导出紧凑场景/文风提示卡）。

### Stage 9 · 生成例子集（`scripts/09_build_examples.py`）
- 根据 `--preset` / `--kb` / `--max-tokens` / `--ratio` 自动伸缩各节采样深度与预算权重裁剪；
- **自动内嵌目标书高频特征词表**（源自 `index.json["高频词"]`），让写作模型直接对齐原书高频词汇；
- 支持 `--style-only`（剥离剧情绑定、台词改为去角色化的功能桶范例）与 `--anonymize`（支持 `anonymize_style=neutral|names`、`anonymize_terms` 专名替换与 `single_char_names` 单字名安全脱敏）。

### Stage 10 · 生成整书总结（`scripts/10_build_summary.py`）
- 预算未超限或 `full` 档位时无损全保；超限时按三级优先级保序压缩（优先保 `〇 续写速查` 结局锚点，其次 `上篇/附录`，最后对 `下篇` 按第 1 卷和末 2 卷高权重分配并保留卷末状态快照）。

### Stage 11 · 第 0–4 层文风验收与迭代对比（`scripts/11_verify.py`）
- 支持 `--prewarm` 预热 4-gram 缓存（也可在 `12_run_all.py` 中传 `--prewarm-verify` 顺手完成）；
- 支持 `--guide`（输出分优先级改稿指南）、`--json`（机器可读诊断报告）、`--top-z N`（定位最异常的 N 句及句内 0 频片段）、`--pov first|third`（视点分桶对标）；
- 支持 `--cross-domain` + `--domain-terms`（跨题材纯文风仿写专用验收轨道）；
- 支持 `--diff v1.md v2.md`（迭代前后指标对比）与 `--html report.html`（可视化高亮验收报告）。

### Stage 12, 13, 13b & 13c · 一键编排、合并出包、多书混搭与可选 Agent Wiki
- `12_run_all.py`：跨平台一键调度全流程；交互终端未指定预算参数时主动询问目标规模，支持 `--yes`（跳过交互确认）、`--prewarm-verify`（构建完成后顺手预热验收缓存），以及可选 `--wiki`（在不改变默认单文件打包的前提下，额外调用 `13c_build_wiki.py` 生成 `work/wiki/`）。
- `13_build_pack.py`：将《整书总结》前置、《例子集》后置（去重禁区段落），输出 `参考包.md`（或 `--style-only` 下的 `纯文风包.md`）；支持 `--emit-both`（同时保留独立例子集）、`--examples-out`（自定义例子集输出路径）与 `--anonymize-style neutral|names`。
- `13b_blend_style.py`：按维度（叙述骨架 / 笔法细节 / 对白口癖等）自动合并多份 `纯文风包.md`，生成跨书混搭参考包。
- `13c_build_wiki.py`（**可选，仅本地 Coding Agent 用**）：将文风靶、五类笔法、对白功能桶、高频词表与（完整模式下的）角色卡/世界观/分卷页拆分为互联 `work/wiki/` 目录，保留 `meta/contradictions.md` 手写笔记，并通过 `_sources.json` + `--check-stale` 识别变更分片。

*(仓库代码路径地图与协作约束见根目录 [`AGENTS.md`](../AGENTS.md) 与 [`REPO_MAP.md`](../REPO_MAP.md)，一致性检查可运行 `python scripts/repo_check.py`。)*
