# novel-refpack

把一本长篇小说（十万到几百万字）加工成轻量参考包，直接喂给大模型用于续写、IF 线或原创文风仿写：
- `work/out/整书总结.md`（原作总结）：世界观、全卷分剧情、角色现状、伏笔、设定禁区 —— **锁住事实，防止吃书**。
- `work/out/例子.txt`（例子总结）：叙述节奏、连续动作链、五感细节、对白呼吸感、搭配表、零频黑名单 —— **锁住文风，避免描写重复**。
- `work/out/参考包.md`（**一键合并单文件**）：按设定预算将《整书总结》与《例子集》合二为一（默认例子占 70% : 摘要占 30%），头部带容量/Token/占比看板，直接整份发给大模型。
- `work/out/纯文风包.md`（`--style-only --anonymize`）：免跑 LLM 章节摘要，纯本地秒级剥离原书剧情与人物绑定，人名脱敏为「某甲/某乙」，专供全新原创仿写。

---

## 五种创作模式

| 创作模式 | 怎么用 / 命令 | 适合场景 |
|---|---|---|
| **1. 同人与 IF 线（默认合并包）** | `python scripts/13_build_pack.py --preset standard`（直接粘 `参考包.md`） | 续写、IF 分歧线、支线补完，兼顾事实锁与高密度文风细节 |
| **2. 纯文风原创仿写（去剧情脱敏）** | `python scripts/12_run_all.py --style-only --anonymize`（直接粘 `纯文风包.md`） | 写全新原创世界观与主角，只借用某位作家的笔法、动作链与对白节奏 |
| **3. 多文风混搭** | 分别对 A/B 两本书跑 `--style-only --anonymize`，按叙述骨架/对白维度拼接 | 融合两家所长（如冷硬动作白描 + 幽默轻松吐槽） |
| **4. 反 AI 腔（特征排除）** | 把《例子.txt》或《纯文风包.md》底部的搭配雷区、零频黑名单与 `config/bans.md` 当负面约束 | 洗掉大模型的机械套话、悬空神态与公文过渡词 |
| **5. 群聊 / 贴吧人设蒸馏** | `python scripts/chat_run.py --tieba 弱智吧 --no-llm` 或 `--config config/chat.json` | 打造拟真人类闲聊/贴吧老哥/群友 System Prompt |

*(各模式详细 Prompt 拼接模板见 [docs/MODES.md](docs/MODES.md))*

---

## 容量预算与比例控制（KB / Tokens / 占比）

针对不同模型上下文窗口，可通过 `--preset`、`--kb`、`--max-tokens`、`--ratio` 自由控制输出体积与文风/摘要占比（默认 `standard` 150KB、例子占 `70%` : 摘要占 `30%`）：

| 预设档位 | 总体积 | 估算总 Tokens | 默认配比（例子 70% : 摘要 30%） | 适用场景 |
|---|---|---|---|---|
| `compact` | ~60 KB | ~1.6 万 tokens | 例子 ~42 KB / 摘要 ~18 KB | 32k 窗口 / 网页免费聊天框 |
| `standard` *(默认)* | ~150 KB | ~4.0 万 tokens | 例子 ~105 KB / 摘要 ~45 KB | 64k ~ 128k 主力写作窗口 |
| `rich` | ~300 KB | ~8.0 万 tokens | 例子 ~210 KB / 摘要 ~90 KB | 200k 长窗口丰富细节写作 |
| `full` | 不裁剪 | 全量无损 | 保留全部卷纪要与全量样本 | 1M 窗口（如 Gemini）或本地检索 |

```bash
# 按档位或自定义大小重新打包（秒级完成，无需重跑模型）
python scripts/13_build_pack.py --preset compact
python scripts/13_build_pack.py --kb 120 --ratio 0.75
python scripts/13_build_pack.py --max-tokens 60000 --ratio 0.80

# 纯文风脱敏蒸馏（零 API 消耗，几秒跑完任何一本长篇）
python scripts/12_run_all.py --style-only --anonymize --kb 80
```

> 超预算裁剪时，摘要优先保全「〇 续写速查区（硬设定/结局状态卡）」与首尾卷快照，例子优先保全「细粒度笔法与镜头细节」「对白回合」「描写套路」「搭配雷区与零频黑名单」。

---

## 怎么跑出参考包

### 方式 A · 当前 Coding Agent 调度（推荐，零 API Key 配置）
如果你正在使用 Pi / Claude Code / Cursor 等 Coding Agent：
- 仅做纯文风仿写：直接跑 `python scripts/12_run_all.py --style-only --anonymize`；
- 做全书事实 + 文风包：先跑 `00_extract.py` 与 `01_split.py` 本地切片，再派子代理并行跑分片纪要与卷纪要，最后跑 `06`~`13` 总装输出。

### 方式 B · 独立脚本 + 外部 API（脱离 Agent 批处理）
```bash
cp config/project.example.json config/project.json   # 填入书名、路径、API 端点
python -X utf8 scripts/12_run_all.py                 # 全流程（含参考包.md合并输出）
python -X utf8 scripts/12_run_all.py --no-llm        # 仅离线步骤（抽文本/建索引/出包）
```

---

## 详细文档

- 高阶创作模式与纯文风用法：[`docs/MODES.md`](docs/MODES.md)
- 完整流水线细节：[`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- 配置文件说明（含预算、脱敏与 Chat 模式）：[`docs/CONFIG.md`](docs/CONFIG.md)
- 产物骨架与 Prompt 模板：[`docs/TEMPLATES.md`](docs/TEMPLATES.md)
- 并行调度与子代理原理：[`docs/PARALLEL.md`](docs/PARALLEL.md)
- 常见问题与指标边界：[`docs/PITFALLS.md`](docs/PITFALLS.md)

## License

MIT
