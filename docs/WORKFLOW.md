# 工作流详解

一句话：**先把书拆成能机械处理的片，再把片压成摘要，最后用摘要和语料统计拼出两份文件。**
全程不靠记忆、不靠印象，任何结论都能回原文核对。

```
源文件 ──00_extract──► work/raw/_all.txt ──01_split──► work/chunks/ + work/manifest.json
                                                      │
                        02_run_notes（并发 N 路，一片一任务）
                                                      ▼
                                              work/notes/chunk_NN.md
                                                      │ 03_merge_notes
                                                      ▼
                                                 work/all_notes.md
                                                      │ 04_build_volume_map
                                                      ▼
                                    work/volumes/vol_NN.txt + work/volume_map.json
                                                      │ 05_run_volumes（并发）
                                                      ▼
                                              work/notes/vol/vol_NN.md ──┐
                    05_run_volumes --meta ──► work/notes/meta/*.md ─────┤
                                                                   ├──10_build_summary──► work/out/整书总结.md
work/chunks/ ──06_build_attrib──► work/attrib.json ──┐                       │
                                           ├──07_stylefit_index──► work/cache/<name>/index.json
                                                                   ├──09_build_examples──► work/out/例子.txt
稿子 ──────────────────────────────────────┴──11_verify──► 四层指标
```

---

## Stage 0 · 抽文本（`scripts/00_extract.py`）

**输入** `.epub` / `.docx` / `.txt` ｜ **输出** `work/raw/_all.txt` + `work/raw/sections.json`

- epub：按 `META-INF/container.xml` → `.opf` 的 **spine 顺序**读内页，不是按文件名。
- `h1-h4` 转成 `# / ## / ### / ####` 标记，`p` 转段落 —— **层级必须保留**，
  分片靠它切、索引靠它定位、卷映射靠它算偏移。
- 每卷重复的页眉（简介 / 制作信息 / 封面彩页）整段丢弃，配置项 `drop_headings`。
- `sections.json` 记每个标题的**字符偏移**，后面切卷靠它。

**验收**：跑完看标题统计（h1/h2/h3 各几个），和你在阅读器里数出来的对得上。
对不上就说明标签体系不是预期的，去 `extract_epub` 里加分支。

**依赖**：装了 `lxml` 走 lxml（400 万字级快很多），没装走标准库 `html.parser`，结果一样。

---

## Stage 1 · 分片（`scripts/01_split.py`）

**输入** `work/raw/_all.txt` ｜ **输出** `work/chunks/chunk_NN.txt` + `work/manifest.json`

- 最小切点是 h2/h3（章 / 话），**满 `chunk_chars` 就切**，默认 60000 字。
- **不跨 h1 版块**：外传、附录这类独立板块不能和主线混在一片里，
  否则一层摘要会把两种视点揉成一份，后面没法分区。
- `work/manifest.json` 记每片的起止标题、字数、所属 h1 —— 后面每个脚本都靠它。

**为什么是 6 万字**：够大到不丢上下文，够小到单次调用不爆窗口。
实测一片 5.2 万字 ≈ 31k–60k token 输入，输出摘要 1.5–3k 字。

**验收**：片数 ≈ 总字数 / 6 万；每片的 first/last 标题连着读下来是通的，
中间不跳章（跳了说明标题正则没覆盖到）。

---

## Stage 2 · 一层摘要（`scripts/02_run_notes.py`）

**输入** `work/chunks/chunk_NN.txt` ｜ **输出** `work/notes/chunk_NN.md`

**一片 = 一个独立任务。** 这是整个流程能扩到几百万字的关键，也是**能开几十路子代理**的原因：

- 每个任务的输入是一整片，输出是一份摘要，**上下文互不影响**，谁也不看谁。
- 所以可以放心并行：实测 114 万字 → 26 片 → 25 路；444 万字 → 78 片 → 76 路（`PAR=50` 排队）。
- 用子代理跑就是 `backend: command`，一个子代理一片、只给 `read,write`、禁止联网。
- 失败只影响那一片，`--only 07,23` 补跑，已经完成的自动跳过。

并行粒度、并发数怎么定、防止几十路跑歪的四条规则：见 `docs/PARALLEL.md`。

提示词模板：`config/prompts/stage1_note.txt`。**模板先定死再开跑**，
格式不统一后面就没法机械合并。

模板里的两条硬要求：

1. **必须读完整片**（读到片尾），否则剧情开天窗。
2. **「原文文风样本」必须逐字摘抄**，不许改写 —— 这些样本后来会进例子集，
   一旦被模型改写，例子集里就掺进了模型的句子。

**验收**：`scripts/03_merge_notes.py` 的覆盖率检查——
它会取每片**最后几行**的特征词回查摘要，一个字都没提到就标 WARN（跳读的信号）。

**上下文预算**

| 层 | 每个任务的输入 | 输出 |
|---|---|---|
| 一层（读原文） | 1 片 ≈5.2 万字 ≈31k–60k token | 1.5–3k 字 |
| 二层（读摘要） | 几份摘要 6–9k 字 ≈4–6k token | 3–5k 字 |

---

## Stage 3 · 汇总（`scripts/03_merge_notes.py`）

**输入** `work/notes/*.md` ｜ **输出** `work/all_notes.md`

合并 + 校验。摘要本身**不要清洗**（保真），清洗留给生成成品时做。

---

## Stage 4 · 卷映射（`scripts/04_build_volume_map.py`）

**输入** `work/raw/sections.json` + `_all.txt` ｜ **输出** `work/volumes/vol_NN.txt` + `work/volume_map.json`

一层按 6 万字切，二层的单位是「卷 / 章」，两者**不对齐**。
这里用 sections.json 的字符偏移精确切卷，并回查每卷落在哪些分片里，
二层任务才知道该读哪几份摘要。

**验收**：脚本开头打印偏移校验通过率（前 50 个标题对得上的比例），应当是 50/50。

---

## Stage 5 · 二层归纳（`scripts/05_run_volumes.py`）

**输入** 该卷对应的几份分片摘要 ｜ **输出** `work/notes/vol/vol_NN.md`

- **不要读原文。** 单卷原文 7–13 万字 = 45k–132k token，既贵又没必要；
  读摘要 4–6k token 就够。
- 模板：`config/prompts/stage2_volume.txt`，其中
  **「三、本篇末角色状态快照」一节不可删** —— 写 IF 线时要靠它定时间锚。
- 去重规则写进提示词：相邻分片会重复交代同一段，合并去重，不要写两遍。

`--meta` 模式跑**元章节**（`config/prompts/meta_*.txt`），
从卷纪要的压缩材料里归纳全书级的：定位 / 世界观 / 势力 / 角色 / 结局现状 / 伏笔。
这些是整书总结上篇和附录的来源。

**验收**：每卷纪要 1800–3500 字；`# 标题` 与 `work/volume_map.json` 对得上；
材料里没有的设定没有出现（抽查几个自造名词）。

---

## Stage 6 · 台词归属（`scripts/06_build_attrib.py`）

**输入** `work/chunks/*.txt` + 角色名表 ｜ **输出** `work/attrib.json`

产出 `[{who, text}]`：谁说了哪句。三种高精度规则（同行后置叙述 / 下一行紧贴叙述 / 上一行以「：」结尾），
**一句里出现两个名字就丢弃** —— 宁可少收，不要错收。

归属准确率直接决定后面「语音档案」的可信度。自动抓完用 `--sample 50`
抽一批出来复核，改完的条目直接回填 `work/attrib.json`。

**没有属归属文件怎么办**：`stylefit/build_index.py --names 甲,乙,丙` 会退化成
「名字+说话动词+引号」自动抓，台词类够用，准确率低一档。

---

## Stage 7 · 文风索引（`scripts/07_stylefit_index.py`）

**输入** `work/chunks/` + `work/attrib.json` + `config/stylefit/*.json` ｜ **输出** `work/cache/<name>/index.json`

这一步是全部「像不像」结论的数据源。统计出：

| 产出 | 回答什么问题 |
|---|---|
| 台词 × 功能桶 | 这个人在这种处境说什么话 |
| 描写意图样本 | 这个意图书里怎么写 |
| **搭配表** | 这个动作该配哪个动词、哪个方位 |
| 用词表 / 零频黑名单 | 哪些词书里根本不用 |
| 场景词典 | 这类场景实际用哪些词 |
| 场景片段 | 同类场景的真实段落 |
| 统计靶 | 台词均长 / 中位 / 对白占比 / 标点率 |

**换书必须改的四处**：引号体系（`config` 的 `quote_open/close`）、叙述人称、
角色名表、`config/stylefit/*.json` 里的词表。

---

## Stage 8 · 生成例子集（`scripts/09_build_examples.py`）

**输入** `index.json` + `work/attrib.json` + `work/notes/vol/*.md` ｜ **输出** `work/out/例子.txt`

十二节：使用禁令 → 文风速览 → 叙述腔 → 内心独白 → 对白回合 →
台词分角色+语音档案 → 亲密写法 → 名场面 → 描写套路 → 语音分期 →
搭配表·雷区 → 用词表。

**使用禁令一节从 `config/bans.md` 读**，它拦的是模型最容易犯的错：
照抄开篇特殊写法、写本书没有的设定、把分期角色写死、人称称呼错。

**宁厚勿薄**：例子给少了模型一定写飘。实做里一份从 3.8 万字扩到 13.7 万字，
模型输出质量肉眼可见变好。

---

## Stage 9 · 生成整书总结（`scripts/10_build_summary.py`）

**输入** `work/all_notes.md` + `work/notes/vol/*.md` + `work/notes/meta/*.md` + `index.json`
｜ **输出** `work/out/整书总结.md`

结构见 `docs/TEMPLATES.md`。三条纪律：

1. **〇 速查区放最前面**：模型不会从头读到尾，速查区放开头才生效。
2. **每卷篇末的角色状态快照必须保留**（写 IF 线定时间锚用）。
3. **事件全覆盖**：分片摘要的事件要逐卷进下篇，跨卷重复保留，
   只去重同卷内完全相同的字符串 —— 去多了就是丢剧情。

生成时会跑 `lib/textio.py: clean_note_text()` 清掉三类残留：
话名罗列、内部编号（`chunk_76` 这种）、元文本说明。

---

## Stage 10 · 验收（`scripts/11_verify.py`）

**输入** 你的稿子 ｜ **输出** 四层指标

| 层 | 测什么 | 判据 |
|---|---|---|
| 门槛 | 段级边际统计是否落在同类参考段区间内 | 全部在范围内 |
| 结构 | 自打乱比值 | 接近同类书段中位（最弱的一层） |
| 逐句 | 字符 4-gram 条件归一化 z | 台词与叙述都 ≈ ±0.3 |
| 0 频探针 | 新造 4-gram 率 | 倍数 ≤ 1.05 |

**`--ref-pattern` 必须按场景切**（写撸猫戏就用 `(猫|尾巴|摸头)`），
拿全书硬套等于用错靶子——同类场景的台词均长能差一倍。

---

## 并发、成本与中断

| 阶段 | 任务数 | 并发 |
|---|---|---|
| Stage 2 一层摘要 | = 片数（几十到上百） | 16–50 路，实测最高 76 路 |
| Stage 5 二层卷纪要 | = 卷数 | 30–35 路 |
| Stage 5 --meta | 6 个 | 6 路 |
| 其余阶段 | 单进程 | — |

- 全部任务都是「读文件 → 写文件」，**可以随时中断随时重跑**，`--only` 指定编号补。
- 排空时间 ≈ `任务数 ÷ 并发 × 单任务耗时`（一片约 30–120 秒）。
- 先小批量试：`02_run_notes.py --only 1,2,3 --par 8`，跑通再加并发。
- 想先跑通再全量：`04_build_volume_map.py --range 3` 只建前 3 卷。
- 只有 Stage 2 / 5 / meta 花钱，其余是纯本地文本处理。

展开见 `docs/PARALLEL.md`。
