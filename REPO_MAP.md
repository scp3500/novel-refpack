# `REPO_MAP.md` · `novel-refpack` 自包含全仓路径与契约地图

> **设计原则（单文件自包含内聚）**：把「任务直达路由 + 数据流与契约 + 全仓路径索引与隐性约束 + 演进日志」全部收口到这一份文件。AI 接手仓库只需通读本文件，即可零盲搜精准定位并避开跨文件隐性雷区。

---

## 一、按任务意图直达路径（先看这张表）

| 任务意图 | 首选主文件 | 必同步联动文件 | 对应单测 |
|---|---|---|---|
| **抽文本**（EPUB/DOCX/TXT/SRT/ASS/剧本、TOC 回退、`<rt>`、非正文过滤、繁简告警） | `scripts/00_extract.py` | `lib/corpus.py`、`lib/project.py` | `tests/test_extract_and_quotes.py`、`tests/test_fixes_and_coverage.py` |
| **引号解析 / 叙述句防病句 / 脱敏 / 高频词 / POV 判定** | `lib/corpus.py` | `scripts/06_build_attrib.py`、`stylefit/build_index.py`、`scripts/09_build_examples.py`、`stylefit/verify.py` | `tests/test_extract_and_quotes.py`、`tests/test_stylefit_and_pack_v2.py` |
| **分片、卷映射、LLM 并发摘要与整书总结** | `scripts/01_split.py`、`02_run_notes.py`、`03_merge_notes.py`、`04_build_volume_map.py`、`05_run_volumes.py`、`10_build_summary.py` | `lib/llm.py`、`lib/textio.py`、`config/prompts/*.txt` | `tests/test_e2e_smoke.py`、`tests/test_volume_and_meta.py`、`tests/test_llm_command.py` |
| **角色名/专名发现与台词归属** | `scripts/06_build_attrib.py`、`scripts/06b_suggest_entities.py` | `lib/corpus.py` | `tests/test_attrib.py`、`tests/test_roadmap_tools.py` |
| **文风索引、高频词、POV 统计靶与多题材预设** | `stylefit/build_index.py`、`scripts/07_stylefit_index.py` | `config/stylefit_{general,modern,fantasy,tieba}/*.json`、`lib/project.py` | `tests/test_stylefit_and_pack_v2.py`、`tests/test_fixes_and_coverage.py` |
| **LLR 语料指纹挖掘（自动生成 `colloc.json`/`words.json`）** | `scripts/07b_discover_style.py` | `lib/corpus.py`、`stylefit/build_index.py` | `tests/test_roadmap_tools.py` |
| **查搭配 / 查高频词 / 导出单角色语音卡** | `stylefit/query.py`、`scripts/08_stylefit_query.py` | `stylefit/build_index.py` | `tests/test_stylefit_and_pack_v2.py` |
| **例子集、容量预算、交互询问 KB、单文件打包与混搭** | `lib/budget.py`、`scripts/09_build_examples.py`、`scripts/13_build_pack.py`、`scripts/13b_blend_style.py` | `scripts/12_run_all.py`、`config/bans.md` | `tests/test_pack_and_style.py`、`tests/test_stylefit_and_pack_v2.py`、`tests/test_roadmap_tools.py` |
| **独立可选 Agent 写作 Wiki 目录模式（`--wiki`）** | `scripts/13c_build_wiki.py` | `scripts/12_run_all.py`、`stylefit/query.py`、`lib/corpus.py` | `tests/test_wiki_mode.py` |
| **写后验稿、第 0 层基础排雷、防粘贴、跨题材、`--guide`/`--diff`/`--html`** | `stylefit/verify.py`、`scripts/11_verify.py` | `lib/corpus.py`、`stylefit/build_index.py` | `tests/test_verify_v2.py`、`tests/test_fixes_and_coverage.py` |
| **一键流水线编排与跨平台 CLI** | `scripts/12_run_all.py`、`scripts/12_run_all.sh` | `lib/budget.py`、`lib/project.py` | `tests/test_run_all_and_config.py`、`tests/test_e2e_smoke.py` |
| **群聊 / 贴吧人设逆向蒸馏（Chat Mode）** | `scripts/chat_run.py`、`chat_00_clean.py`、`chat_01_metrics.py`、`chat_02_distill.py`、`chat_03_build_prompt.py`、`chat_fetch_tieba.py` | `config/chat.example.json`、`lib/project.py` | `tests/test_fixes_and_coverage.py`、`tests/test_pack_and_style.py` |
| **新增 `project.json` 配置字段** | `lib/project.py` (`DEFAULTS`) | `config/project.example.json`、`docs/CONFIG.md`、`REPO_MAP.md` | `tests/test_run_all_and_config.py` |
| **仓库路径索引校验与纯标准库门禁** | `scripts/repo_check.py` | `AGENTS.md`、`REPO_MAP.md` | `tests/test_repo_map.py` |

---

## 二、流水线数据流与核心契约（谁生产 / 谁消费）

```text
source (.epub/.docx/.txt/.srt/.ass)
   ▼ 00_extract.py
work/raw/_all.txt + work/raw/sections.json
   ▼ 01_split.py
work/chunks/chunk_NN.txt + work/manifest.json
   ├──► (完整模式) 02_run_notes → 03_merge_notes → 04_build_volume_map → 05_run_volumes → 10_build_summary → work/out/整书总结.md
   ├──► (辅助)     06b_suggest_entities.py / 07b_discover_style.py
   ├──► 06_build_attrib.py ──► work/attrib.json
   ▼
07_stylefit_index.py (stylefit/build_index.py) + config/stylefit_<preset>/*.json
   ▼
work/cache/<name>/index.json ──┬──► 08_stylefit_query.py (查搭配/高频词/单角色语音卡)
                               ├──► 09_build_examples.py ──► work/out/例子.txt
                               ├──► 13_build_pack.py ──────► work/out/{参考包.md | 纯文风包.md}   [默认单文件产物]
                               │        └──► 13b_blend_style.py (多文风混搭)
                               ├──► 13c_build_wiki.py ─────► work/wiki/{AGENTS,route,index,...}  [可选 --wiki 模式]
                               └──► 11_verify.py (stylefit/verify.py) ──► verify_cache.pkl / --json / --guide / --diff / --html
```

| 契约文件 | Producer | Consumer | 核心约束（改字段必读） |
|---|---|---|---|
| `config/project.json` | 模板 `project.example.json` | `lib/project.py` → 全部脚本 | 新字段必须在 `DEFAULTS` 提供向后兼容默认值 |
| `config/stylefit_*/*.json` | 仓库预设 / `07b_discover_style.py` | `stylefit/build_index.py`、`09_build_examples.py` | `_` 开头键为注释必须忽略；`intents/topics/scene_rules/funcs` 的值必须可 `re.compile` |
| `work/raw/sections.json` | `00_extract.py` | `01_split.py`、`04_build_volume_map.py`、`09_build_examples.py` | `offset` 必须精确指向 `_all.txt` 中 `#` 行起始字符位置 |
| `work/manifest.json` | `01_split.py` | `02`、`03`、`04_build_volume_map.py` | `start/end` 左闭右开对齐 `_all.txt` |
| `work/volume_map.json` | `04_build_volume_map.py` | `lib/project.py:vol_notes`、`05`、`10_build_summary.py` | `i` 决定卷序与 `vol_NN.md` 文件名 |
| `work/attrib.json` | `06_build_attrib.py` | `build_index.py`、`query.py`、`09`、`13c_build_wiki.py` | `[{who, text}]`，`who` 已按 `aliases` 归并为主名 |
| `work/cache/<name>/index.json` | `stylefit/build_index.py` | `query.py`、`verify.py`、`09`、`13c_build_wiki.py` | 顶层键 `meta/台词/描写/笔法细节/搭配/用词/高频词/零频词/场景/场景词典/统计` 只增不改名 |
| `work/cache/<name>/verify_cache.pkl` | `stylefit/verify.py` | `stylefit/verify.py` | 改缓存结构**必须递增** `("ver", N)` 版本号触发自动重建 |
| `work/wiki/`（可选） | `13c_build_wiki.py` | 本地 Coding Agent | 仅 `--wiki` 生成；重建时保留 `meta/contradictions.md` 人工条目 |

---

## 三、全仓库代码路径索引（职责｜联动｜接口｜隐性约束）

### `lib/`（核心公共库）
- `lib/__init__.py`：包标记，无副作用。
- `lib/textio.py`：跨编码原子读写（同目录隐藏 `.tmp` + `os.replace`）、`natural_key`、`parse_units`、`clean_note_text`（只删话名行，不误删编号剧情句）、`ensure_utf8_stdio`（Windows UTF-8 兜底）。
- `lib/project.py`：配置合并（`DEFAULTS` + 环境变量覆盖）、路径 `normpath` 规整、`resolve_bans_file`、`resolve_stylefit_dir`（支持 `general/modern/fantasy/tieba` 预设简称）、`vol_notes`、`prompt`（单遍正则替换防书名 `{...}` 二次展开）；`load()` 自动调 `ensure_utf8_stdio` 和 `corpus.set_quotes`。
- `lib/corpus.py`：`is_divider`（含 `◇/＊`）、`detect_script_variant`（繁简告警）、成对栈式引号 `iter_quotes`/`extract_quotes`/`extract_dialogue_quotes`、`strip_dialogue_quotes` + `narr_sentences`（保留行内强调引号内容防挖空病句，过滤残缺伪句）、`detect_para_pov`、`extract_top_words`（目标书高频特征词）、`build_anonymizer`（支持 `anonymize_terms`/`single_char_names` 安全边界/相邻重名合并/`style="neutral"|"names"`）。联动：`00`、`06`、`07b`、`09`、`13c`、`build_index`、`verify`。
- `lib/budget.py`：UTF-8 KB / Token 估算、`resolve_budget`、`allot_weights`、`trim_markdown_block`（保围栏闭合）、`trim_to_utf8_bytes`、`parse_size_choice` & `prompt_budget_interactive`（交互终端主动问 KB 规模；非 TTY / `--yes` / 显式预算时静默跳过）。
- `lib/llm.py`：OpenAI HTTP + 外部 `command` 子代理双后端并发调度（`call_llm`、`run_parallel`、`render_command`、`strip_think`）；4xx 不重试（429 除外），`render_command` 禁用 `str.format`，超时杀整个进程组。

### `stylefit/`（文风统计与验稿引擎）
- `stylefit/build_index.py`：离线构建 `index.json`（台词功能桶、描写意图、5 类笔法细节、搭配表、场景词典、用词表、`高频词`、零频黑名单、场景片段、全书对白统计靶与 `POV分桶`）。归属覆盖率 `<30%` 时自动切换全书引号对白统计；繁体语料告警。
- `stylefit/query.py`：查询 `index.json`（`--list/--who/--func/--colloc/--dict/--why/--craft/--scene/--words/--top-words/--stats/--zero`）及 `--export-card` 导出 5–10 KB 单角色语音卡（`build_voice_card` 亦被 `13c_build_wiki.py` 复用）。
- `stylefit/verify.py`：全层验稿引擎（Layer 0 基础排雷：语料拟合乱码/零频词/低频搭配+高频平替/标点密度/语料拟合 AI 套话与结构探针；≥10 字照抄例句/原书检测；长稿 `>800` 字滑窗门槛；专名窗口掩码严禁 `s[0]*len(s)` 叠字；4-gram 逐句 `z` 与 0 频高亮；跨题材虚词骨架层；`--pov`；`--prewarm`/`--json`/`--guide`/`--diff`/`--log-history`/`--html`）。

### `scripts/`（小说流水线与工具）
- `scripts/00_extract.py`：抽取 `.epub`/`.docx`/`.txt`/`.srt`/`.ass`/Galgame 剧本 → `raw/_all.txt` + `sections.json`；EPUB 支持 `toc.ncx`/`nav.xhtml` 自动回退与扁平目录双层推断、`BlockParser` 与可选 `lxml` 双路径跳过 `<rt>/<rp>`、`drop_builtin_meta`/`drop_*_patterns` 过滤与繁简警告；`extract_epub(path, drop)` 保持两参兼容。
- `scripts/01_split.py`：按 `h2/h3` 不跨 `h1` 切 `chunks/chunk_NN.txt` 与 `manifest.json`（先清旧片）。
- `scripts/02_run_notes.py`：并发跑一层分片摘要 `notes/chunk_NN.md`（断点续跑）。
- `scripts/03_merge_notes.py`：合并 `all_notes.md` 并查片尾特征词覆盖率（防模型跳读）。
- `scripts/04_build_volume_map.py`：严格按 `sections.json` 字符偏移切卷与映射分片至 `volume_map.json`（无标题纯文本自动兜底）。
- `scripts/05_run_volumes.py`：并发跑卷纪要 `notes/vol/vol_NN.md` 与 `--meta` 元章节（自动发现 `meta_*.txt`，压缩时保首尾卷）。
- `scripts/06_build_attrib.py`：高精度台词归属 `attrib.json`（嵌套引号、多轮白话、`aliases` 归并、剧本 `【角色名】台词`）。
- `scripts/06b_suggest_entities.py`：纯本地实体/译名变体/地名机构候选发现，输出 `project.json` 配置片段。
- `scripts/07_stylefit_index.py`：`stylefit/build_index.py` 装配壳（注入 `stylefit_dir`、`attrib.json` 与 `names+aliases`）。
- `scripts/07b_discover_style.py`：基于内置通用汉语先验算 LLR/G² 挖掘正向指纹词、零频雷区与本书高频词，`--export-dir` 一键导出 `colloc.json`/`words.json`。
- `scripts/08_stylefit_query.py`：`stylefit/query.py` 装配壳（自动补 `--index` 与 `--attrib`）。
- `scripts/09_build_examples.py`：生成《例子.txt》（`--style-only` 尊重 `topics.json` 并用全书裸对白桶、内嵌本书高频特征词表、防照抄护栏、`--anonymize-style`、`anonymize_terms`/`single_char_names`）。
- `scripts/10_build_summary.py`：从摘要组装《整书总结.md》（优先保开篇与最后 2 卷）。
- `scripts/11_verify.py`：`stylefit/verify.py` 装配壳（自动补 `--corpus`/`--out`/`--examples`/`--log-history`，`--json` 到 stdout 时回显走 stderr）。
- `scripts/12_run_all.py`：跨平台一键流水线（`--no-llm`/`--style-only`/`--emit-both`/`--prewarm-verify`/`--wiki`/`--yes`/`--ask-size` + 交互规模询问；默认单文件打包）。
- `scripts/13_build_pack.py`：合并单文件参考包（两遍容量看板、防照抄护栏、自定义 `--out` 临时隔离不覆写 `例子.txt`、`--emit-both` 双版、交互规模询问）。
- `scripts/13b_blend_style.py`：多文风一键混搭合成器（A 叙述/笔法/搭配 + B 对白/功能桶，带冲突仲裁与围栏感知解析）。
- `scripts/13c_build_wiki.py`：独立可选 Agent 写作 Wiki 目录模式生成器（产出 `work/wiki/` 互联文件树与 `--check-stale`；不影响默认打包，重建保留 `meta/contradictions.md`）。
- `scripts/repo_check.py`：零依赖仓库自检门禁（`REPO_MAP.md` 路径覆盖 + 公开 JSON/正则校验 + AST 纯标准库检查 + `--skeleton` + `--full`）。

### `scripts/chat_*.py`（群聊 / 贴吧人设蒸馏模式）
- `scripts/chat_fetch_tieba.py`：抓贴吧热门帖为 `tieba_json`（唯一可选依赖 `aiotieba`，延迟导入）。
- `scripts/chat_00_clean.py`：清洗 `tieba_json` / `qq_txt`。
- `scripts/chat_01_metrics.py`：统计消息长度分位、每千字句号率、空格断句与发语词 → `chat_metrics.json`。
- `scripts/chat_02_distill.py`：LLM 提炼交互心理学特征 → `chat_behavior.json`。
- `scripts/chat_03_build_prompt.py`：合成 `群聊人设提示词.md`（按实测句号率动态生成标点规则）。
- `scripts/chat_run.py`：Chat Mode 一键总控。

### `config/`、`docs/` 与 `tests/`
- `config/stylefit/`（默认兼容，勿改脏）；`config/stylefit_{general,modern,fantasy,tieba}/`（四套内置预设）；`config/bans.md`（通用+6类结构反AI禁区）；`config/prompts/`（摘要/元章节模板）；`config/{project,chat}.example.json`。
- `SKILL.md`、`stylefit/SKILL.md`、`docs/{MODES,CONFIG,PITFALLS,WORKFLOW,TEMPLATES,PARALLEL}.md`、`README.md`（含主动询问 KB 规模、参考目标书高频词、双轨验稿与可选 `--wiki` 说明）。
- `tests/`：全套 `unittest` 测试套件（`python -X utf8 scripts/repo_check.py --full` 一键跑通）。

---

## 四、架构演进日志（追加式）
- `2026-11-24`：完成全链路 5 大 Milestone + 7 项 Roadmap 特性（EPUB TOC/ruby/字幕/剧本、成对引号防病句、增强脱敏、多题材预设、全量对白桶、本书高频词、交互 KB 询问、防串台打包、验稿引擎 v2 与 guide/diff/html、06b/07b/13b）。
- `2026-11-24`：按单文件自包含内聚思想落地 `AGENTS.md` + `REPO_MAP.md` + `scripts/repo_check.py`，并新增独立可选的本地 Agent 写作 `--wiki` 模式（`scripts/13c_build_wiki.py`），统一第 0 层检测命名为「基础排雷」。
