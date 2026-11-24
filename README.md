# novel-refpack

把一本长篇小说、剧本/字幕（十万到几百万字）加工成轻量参考包，直接喂给大模型用于续写、IF 线或原创文风仿写：
- `work/out/整书总结.md`（原作总结）：世界观、全卷分剧情、角色现状、伏笔、设定禁区 —— **锁住事实，防止吃书**。
- `work/out/例子.txt`（例子总结）：叙述节奏、连续动作链、五感细节、对白呼吸感、**目标书高频特征词表**、搭配表、零频黑名单 —— **锁住文风与用词底色，避免描写重复**。
- `work/out/参考包.md`（**一键合并单文件**）：按设定预算将《整书总结》与《例子集》合二为一（默认例子占 70% : 摘要占 30%），头部带容量/Token/占比看板，直接整份发给大模型（加 `--emit-both` 可同时保留独立例子集）。
- `work/out/纯文风包.md`（`--style-only --anonymize`）：免跑 LLM 章节摘要，纯本地秒级剥离原书剧情与人物绑定，支持 `neutral`（某甲/某乙）或 `names`（自然假名）脱敏、专名/单字名安全替换，并内嵌目标书高频词表，专供全新原创仿写。

---

## 核心亮点

- **题材预设开箱即用**：内置 `general`（通用文学，零奇幻偏置）、`modern`（现代都市校园恋爱）、`fantasy`（奇幻异世界系统）、`tieba`（贴吧群聊）四套 `stylefit_dir` 规则预设，支持 `.epub` / `.docx` / `.txt` / `.srt` / `.ass` / Galgame 脚本抽取（含 EPUB TOC 回退与自动过滤版权/奥付页）。
- **目标书高频词表直接对齐**：`07_stylefit_index.py` 与 `09_build_examples.py` 自动从原书提取并嵌入 **高频特征词表**（`index.json["高频词"]`，直接写入 `例子.txt` / `纯文风包.md`），并支持 `08_stylefit_query.py --top-words` 与 `07b_discover_style.py` 零配置发现，让写作模型直接贴齐原书高频词而非凭空猜词。
- **第 0–4 层量化验收与 Agent 改稿闭环**：`11_verify.py` 区分**同题材续写**与**跨题材纯文风仿写**（`--cross-domain --domain-terms`），内置第 0 层卫生拦截（乱码、零频词、低频搭配平替、语料拟合 AI 探针、照抄例句粘贴检测）、视点分桶（`--pov`）、Top-N 异常句定位（`--top-z`）、改稿指南（`--guide`）、版本对比（`--diff`）与 HTML 可视化报告（`--html`）。

---

## 五种创作模式

| 创作模式 | 怎么用 / 命令 | 适合场景 |
|---|---|---|
| **1. 同人与 IF 线（默认合并包）** | `python scripts/13_build_pack.py --preset standard`（可加 `--emit-both`） | 续写、IF 分歧线、支线补完，兼顾事实锁、高频词表与高密度文风细节 |
| **2. 纯文风原创仿写（去剧情脱敏）** | `python scripts/12_run_all.py --style-only --anonymize`（可选 `--anonymize-style names`） | 写全新原创世界观与主角，只借用某位作家的笔法、高频词底色与对白节奏 |
| **3. 多文风混搭** | `python scripts/13b_blend_style.py --narr A.md --dialogue B.md --out out.md` | 自动融合两家所长（如冷硬动作白描 + 幽默轻松吐槽） |
| **4. 反 AI 腔与验收改稿闭环** | 结合 `config/bans.md` 六大结构禁区 + `11_verify.py --guide / --diff / --html` | 洗掉机械套话、结构型 AI 腔与语域串台，量化核验改稿收敛 |
| **5. 群聊 / 贴吧人设蒸馏** | `python scripts/chat_run.py --tieba 弱智吧 --no-llm` 或 `--config config/chat.json` | 打造拟真人类闲聊/贴吧老哥/群友 System Prompt |

*(各模式详细 Prompt 拼接模板与 Agent 改稿闭环见 [docs/MODES.md](docs/MODES.md))*

---

## 容量预算与规模确认（KB / Tokens / 占比）

> **主动确认目标体积**：AI 助手使用本仓库工具启动蒸馏或打包前，应**先主动询问用户期望的输出大小（KB / 档位）**；在交互终端直接运行 `12_run_all.py` 或 `13_build_pack.py` 且未显式指定预算参数时，脚本也会主动提问（批处理脚本可加 `--yes` 或显式传 `--preset` / `--kb` 跳过）。

| 预设档位 | 总体积 | 估算总 Tokens | 默认配比（例子 70% : 摘要 30%） | 适用场景 |
|---|---|---|---|---|
| `compact` | ~60 KB | ~1.6 万 tokens | 例子 ~42 KB / 摘要 ~18 KB | 32k 窗口 / 网页免费聊天框 |
| `standard` *(默认)* | ~150 KB | ~4.0 万 tokens | 例子 ~105 KB / 摘要 ~45 KB | 64k ~ 128k 主力写作窗口 |
| `rich` | ~300 KB | ~8.0 万 tokens | 例子 ~210 KB / 摘要 ~90 KB | 200k 长窗口丰富细节写作 |
| `full` | 不裁剪 | 全量无损 | 保留全部卷纪要与全量样本 | 1M 窗口（如 Gemini）或本地检索 |

```bash
# 按档位或自定义大小重新打包（秒级完成，无需重跑模型）
python scripts/13_build_pack.py --preset compact
python scripts/13_build_pack.py --kb 120 --ratio 0.75 --emit-both --examples-out work/out/例子.txt
python scripts/13_build_pack.py --max-tokens 60000 --ratio 0.80

# 纯文风脱敏蒸馏（零 API 消耗，几秒跑完任何一本长篇；可顺手预热验收缓存）
python scripts/12_run_all.py --style-only --anonymize --kb 80 --prewarm-verify --yes
```

> 超预算裁剪时，摘要优先保全「〇 续写速查区（硬设定/结局状态卡）」与首尾卷快照，例子优先保全「目标书高频特征词表」「细粒度笔法与镜头细节」「对白回合」「描写套路」「搭配雷区与零频黑名单」。

---

## 怎么跑出参考包与闭环验稿

### 方式 A · 当前 Coding Agent 调度（推荐，零 API Key 配置）
如果你正在使用 Pi / Claude Code / Cursor 等 Coding Agent（详见 [`SKILL.md`](SKILL.md)）：
1. **先确认目标产出规模**（`compact` / `standard` / `rich` / `full` 或 `--kb N`）；
2. **仅做纯文风仿写**：选好 `stylefit_dir`（`general` / `modern` / `fantasy`），可选跑 `06b_suggest_entities.py` 补全专名脱敏，直接跑 `python scripts/12_run_all.py --style-only --anonymize --preset standard --yes`；
3. **做全书事实 + 文风包**：先跑 `00_extract.py` 与 `01_split.py` 本地切片，再派子代理并行跑分片纪要与卷纪要，最后跑 `06`~`13` 总装输出；
4. **写前查词 & 写后验稿**：
   ```bash
   python scripts/07b_discover_style.py                           # 零配置探索原书高频特征词
   python scripts/08_stylefit_query.py --top-words                # 查目标书高频特征词表
   python scripts/08_stylefit_query.py --export-card card.md      # 导出场景/文风提示卡
   python scripts/11_verify.py --text v1.md --guide --top-z 15    # 跑第 0-4 层验收与改稿指南
   python scripts/11_verify.py --diff v1.md v2.md --html report.html
   ```

### 方式 B · 独立脚本 + 外部 API（脱离 Agent 批处理）
```bash
cp config/project.example.json config/project.json   # 填入书名、路径、stylefit_dir、API 端点
python -X utf8 scripts/12_run_all.py                 # 全流程（交互确认体积并输出参考包.md）
python -X utf8 scripts/12_run_all.py --no-llm --yes  # 仅离线步骤（抽文本/建索引/出包）
```

---

## 详细文档

- Agent 技能与闭环入口：[`SKILL.md`](SKILL.md) / [`stylefit/SKILL.md`](stylefit/SKILL.md)
- 高阶创作模式与纯文风用法：[`docs/MODES.md`](docs/MODES.md)
- 完整流水线细节与全部新脚本参数：[`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- 配置文件与分题材预设说明：[`docs/CONFIG.md`](docs/CONFIG.md)
- 产物骨架与 Prompt 模板：[`docs/TEMPLATES.md`](docs/TEMPLATES.md)
- 并行调度与子代理原理：[`docs/PARALLEL.md`](docs/PARALLEL.md)
- 双轨验收指标、第 0 层卫生与排查：[`docs/PITFALLS.md`](docs/PITFALLS.md)

## License

MIT
