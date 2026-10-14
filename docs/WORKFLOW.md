# 完整工作流水线

本项目流水线将长篇语料逐级提炼为两份核心参考物：
1. **《整书总结.md》**：包含世界观、势力阵营、分卷全剧情脉络、伏笔与角色状态快照，用于约束剧情事实。
2. **《例子.txt》**：包含原文叙述腔、分角色对白风格、动作搭配表与描写词典，用于贴近原文笔触。

---

## 流水线全貌

> **核心任务目标**：
> 本流水线**主要做且默认只做两件事：原作总结（整书总结.md）与例子总结（例子.txt）**。
> 后续的字符 4-gram 频率拟合、逐句 z 值检验与 0 频探针等量化验收计算，**默认不做**（属于深度质检的可选工具，绝大多数续写与同人创作无需执行）。

> **核心调度原则（首选 vs 备选）**：
> - **首选方式（当前 Agent 直接执行）**：若在 Coding Agent（如 Pi / Claude Code 等）环境中，流程中的 Stage 2（一层摘要）、Stage 5（卷纪要）与 Meta 元章节，**强烈推荐直接由当前 Agent 调度自带的多子代理并行完成**。无需配置外部 API 凭据，直接复用当前环境已有的模型能力。
> - **备选方式（脚本自动化批处理）**：脱离 Agent 批量刷书时，才配置 `config/project.json` 运行 `12_run_all.py` 脚本驱动外部模型 API。

```
原始语料 ──00_extract──► work/raw/_all.txt ──01_split──► work/chunks/ + work/manifest.json
                                                        │
                          02_run_notes（并发处理，单片一任务）
                                                        ▼
                                                work/notes/chunk_NN.md
                                                        │ 03_merge_notes
                                                        ▼
                                                   work/all_notes.md
                                                        │ 04_build_volume_map
                                                        ▼
                                      work/volumes/vol_NN.txt + work/volume_map.json
                                                        │ 05_run_volumes（多路并发）
                                                        ▼
                                                work/notes/vol/vol_NN.md ──┐
                      05_run_volumes --meta ──► work/notes/meta/*.md ─────┤
                                                                     ├──10_build_summary──► work/out/整书总结.md
work/chunks/ ──06_build_attrib──► work/attrib.json ──┐                       │
                                             ├──07_stylefit_index──► work/cache/<name>/index.json
                                                                     ├──09_build_examples──► work/out/例子.txt
生成稿件 ────────────────────────────────────────┴──11_verify──► 四层验收指标
```

一键执行脚本：
- **跨平台（推荐，支持 Windows / macOS / Linux）**：`python scripts/12_run_all.py`（附加 `--no-llm` 可仅运行本地离线计算步骤）。
- **Bash 环境**：`bash scripts/12_run_all.sh`。

---

## 阶段执行细节

### Stage 0 · 文本抽取（`scripts/00_extract.py`）

解析输入文件，提取正文并保留章节标题层级，输出统一纯文本。

- **执行命令**：`python scripts/00_extract.py`
- **输入**：`config/project.json` 中指定的 `source` 文件（`.epub` / `.docx` / `.txt`）
- **输出**：
  - `work/raw/_all.txt`（标准化正文，标题标记为 `#`, `##`, `###`）
  - `work/raw/sections.json`（各级标题对应的字符偏移量字典）
- **核心逻辑**：
  - EPUB 格式按 `container.xml` 与 `content.opf` 的 `spine` 物理阅读顺序线性提取。
  - 自动过滤 `config/project.json` 中 `drop_headings` 定义的无关版面（如版权声明、插图页、封面简介）。
- **验收标准**：提取完成后输出的各级标题数量与实际阅读器目录一致，无章节倒序或正文丢失。

---

### Stage 1 · 语义分片（`scripts/01_split.py`）

将抽取后的全书正文切分为适合单次上下文处理的标准分片。

- **执行命令**：`python scripts/01_split.py`
- **输入**：`work/raw/_all.txt`
- **输出**：
  - `work/chunks/chunk_NN.txt`（切片文本，默认目标单片 60,000 字）
  - `work/manifest.json`（分片元数据映射表，记录每片的字数、起止标题及所属顶级版块）
- **核心逻辑**：
  - 切割点优先吸附于二级/三级标题（章/话边界），避免在段落中间截断。
  - 强制禁止跨一级标题（如正文卷与独立外传、附录）切分，保障分片语境纯粹。
- **验收标准**：
  - 生成分片数符合预期（$\approx \text{总字数} / \text{chunk\_chars}$）。
  - `work/manifest.json` 中相邻分片的首尾标题平滑衔接，无遗漏章节。

---

### Stage 2 · 一层分片摘要（`scripts/02_run_notes.py`）

多路并发调用模型，逐片生成结构化事件与文风摘录。

- **执行命令**：`python scripts/02_run_notes.py [--par 并发数] [--only 分片列表]`
- **输入**：`work/chunks/chunk_NN.txt` + `config/prompts/stage1_note.txt`
- **输出**：`work/notes/chunk_NN.md`
- **核心逻辑**：
  - 任务粒度为单分片独立处理，各任务无状态依赖，支持大批量并发（详见 [docs/PARALLEL.md](PARALLEL.md)）。
  - 提示词强制约束模型完整阅读至分片结尾，并逐字摘录原文文风样本（严禁改写或二次润色）。
- **验收标准**：目标分片均生成对应 markdown 文件，产物包含主要剧情、出场角色、伏笔线索与原文摘录。

---

### Stage 3 · 摘要合并与覆盖率校验（`scripts/03_merge_notes.py`）

汇集全部单片摘要，并执行完整性防跳读检测。

- **执行命令**：`python scripts/03_merge_notes.py [--check]`
- **输入**：`work/notes/chunk_*.md`
- **输出**：`work/all_notes.md`
- **核心逻辑**：
  - 顺序拼接全部一层摘要，保持原始结构化标记不丢失。
  - 抽取每个分片末尾最后若干行的实体词，反向检索对应摘要内容。若未命中任何特征词，则标记跳读预警。
- **验收标准**：无缺失分片；覆盖率校验无批量 WARN 警告。

---

### Stage 4 · 卷结构映射（`scripts/04_build_volume_map.py`）

建立物理卷与分片摘要之间的对应关系。

- **执行命令**：`python scripts/04_build_volume_map.py [--range N]`
- **输入**：`work/raw/sections.json` + `work/raw/_all.txt`
- **输出**：
  - `work/volumes/vol_NN.txt`（单卷合并文本）
  - `work/volume_map.json`（记录每卷包含的章节范围及其对应的分片编号区间）
- **核心逻辑**：
  - 依据一级标题（卷/篇）解析字符区间，计算其与 `work/manifest.json` 中各分片的重叠范围。
- **验收标准**：前 50 个标题的偏移量映射通过率达 100%。

---

### Stage 5 · 二层分卷纪要与元章节（`scripts/05_run_volumes.py`）

以卷为单位归纳宏观剧情，并提炼全局世界观、势力与角色卡。

- **执行命令**：
  - 分卷纪要：`python scripts/05_run_volumes.py [--par 并发数]`
  - 全局元章节：`python scripts/05_run_volumes.py --meta`
- **输入**：对应卷所覆盖的分片摘要 + `config/prompts/stage2_volume.txt` 及 `meta_*.txt`
- **输出**：
  - `work/notes/vol/vol_NN.md`（包含剧情主干、登场人物、伏笔回收及**卷末角色状态快照**）
  - `work/notes/meta/*.md`（全书级别定位、世界观、阵营、结局现状等 6 份核心元档案）
- **核心逻辑**：
  - 直接读取一层结构化摘要，无需回溯数十万字原始长文本，降低上下文开销并提高信息密度。
  - 自动扫描 `config/prompts/` 目录下的全部 `meta_*.txt` 模版，并发提炼全书全局档案。
- **验收标准**：
  - 各卷纪要字数在 1,800 - 3,500 字区间，卷末角色状态快照完整。
  - 元章节未出现语料之外的自造设定。

---

### Stage 6 · 台词归属识别（`scripts/06_build_attrib.py`）

从全书语料中提取对话台词及其对应说话人，构建语音特征库。

- **执行命令**：`python scripts/06_build_attrib.py [--sample 50]`
- **输入**：`work/chunks/*.txt` + `config/project.json` 中的 `names` 列表
- **输出**：`work/attrib.json`（结构为 `[{"who": "角色名", "text": "台词原文"}]`）
- **核心逻辑**：
  - 采用严格规则抽取：后置紧随叙述、下一行叙述锚定、冒号引导。
  - 单句内存在多个候选人名时主动丢弃，保证训练样本纯度。
- **验收标准**：使用 `--sample 50` 随机抽样 50 条人工复查，准确率达到可用标准（可手动修正回填）。

---

### Stage 7 · 文风特征索引（`scripts/07_stylefit_index.py`）

统计提取作者的用词习惯、高频搭配、描写套路及基准量化指标。

- **执行命令**：`python scripts/07_stylefit_index.py`
- **输入**：`work/chunks/` + `work/attrib.json` + `config/stylefit/*.json`
- **输出**：`work/cache/<name>/index.json`
- **核心逻辑**：
  - 统计台词功能桶分布（不同情境下的发言习惯）。
  - 构建高频搭配表与零频黑名单（哪些动词/方位搭配书内从不使用）。
  - 建立场景词典与典型描写片段库，计算全书段落边际统计基准值（句长、对白比、段长）。
- **验收标准**：索引文件包含各维度统计数据，可使用 `python scripts/08_stylefit_query.py --stats` 正常查询。

---

### Stage 8 · 构建例子集（`scripts/09_build_examples.py`）

组装用于对齐文风的原汁原味语料库。

- **执行命令**：`python scripts/09_build_examples.py`
- **输入**：`index.json` + `work/attrib.json` + `work/notes/vol/*.md` + `config/bans.md`
- **输出**：`work/out/例子.txt`
- **核心逻辑**：
  - 将十二个维度的文风资料组合成册：开篇硬性禁令（来自 `bans.md`）、文风速览靶标、叙述腔、内心独白、按场景对白回合、分角色语音档案、名场面精选、描写套路、搭配雷区与用词黑名单。
- **验收标准**：文本结构完备，各章节包含充足的原句摘录，不含模型二次加工生成的非原文语句。

---

### Stage 9 · 构建整书总结（`scripts/10_build_summary.py`）

组装用于约束宏观剧情事实的核心参考手册。

- **执行命令**：`python scripts/10_build_summary.py`
- **输入**：`work/all_notes.md` + `work/notes/vol/*.md` + `work/notes/meta/*.md` + `index.json`
- **输出**：`work/out/整书总结.md`
- **核心逻辑**：
  - 组装三大板块：【速查区】（硬设定、结局现状、分歧点）、【上篇总览】（世界观、势力、角色档案）、【下篇分卷剧情】（各卷全事件与卷末快照）。
  - 执行产物文本清洗，自动剔除分片编号标识与提示词元文本残留。
- **验收标准**：结构符合 [docs/TEMPLATES.md](TEMPLATES.md) 约定，速查区置于首部，各卷事件保留完整。

---

### Stage 10 · 产出验收评估（默认不做，完全可选，`scripts/11_verify.py`）

说明：**本步骤默认不做**。流水线的主要产物是【原作总结】与【例子总结】，已完全满足大模型续写和 IF 线的全部上下文需求。仅当有学术化或极严苛统计对比需求时，才手动调用 `11_verify.py` 进行字符 4-gram 与 0 频探针计算。以创作者主观阅读体感为准。

- **执行命令**：`python scripts/11_verify.py --text <待验文本.txt> --ref-pattern '<场景关键词正则>'`
- **输入**：待验生成稿件 + 语料索引
- **输出**：四层指标检验报告（门槛层、结构层、逐句层、0 频探针）
- **核心逻辑**：
  - `--ref-pattern` 指定当前场景类型关键词（如战斗、日常），从语料中切取同类参考区间做对照。
- **验收判据**：
  - **门槛层**：句长、对白占比、段长位于语料参考区间内。
  - **逐句层**：字符 4-gram 条件归一化 $z$ 分数台词与叙述均在 $\pm 0.3$ 附近。
  - **0 频探针**：新造 4-gram 比率倍数 $\le 1.05$。

---

## 阶段 11 · 接入大模型写作落地指南

在完成 Stage 0 ~ 9 产出《整书总结.md》和《例子.txt》后，推荐按以下结构组织模型上下文：

1. **设定锁（System Prompt）**：
   - 载入 `work/out/整书总结.md` 的前言、硬设定、世界观、相关势力与主要角色状态；
   - 载入文档末尾提取的「使用禁令」（角色人设绝对红线）。
2. **文风锚（Few-shot / Context）**：
   - 从 `work/out/例子.txt` 中提取目标角色的专属语气条目、名场面及目标场景（例如战斗或谈判）的原文描写范例；
   - 提取《例子.txt》底部的搭配禁区与零频禁用词表。
3. **写作指令（User Prompt）**：
   - 明确要撰写的具体剧情、分歧点（IF 线事件）、涉及的角色与视点；
   - 要求模型严格遵守人设语气，严禁使用禁词列表中的生造词。
4. **质检闭环（Post-generation QC）**：
   - 将模型生成的新稿存为文本文件，运行 `python scripts/11_verify.py --text 稿件.txt`（可选）；
   - 根据 $z$ 分数偏差和 0 频词报警做局部微调，消除生造词与 AI 腔。

关于如何将本产物用于全新原创世界观、多文风融合以及深度反 AI 腔调，请参考专题指南：[docs/MODES.md](MODES.md)。

