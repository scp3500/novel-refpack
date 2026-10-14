# 配置说明

项目通过 `config/` 目录管理任务参数、模型调用后端、文风统计词典与提示词模板。

---

## 1. 项目基础配置：`config/project.json`

从模板初始化：
```bash
cp config/project.example.json config/project.json
```

该文件已列入 `.gitignore`，包含本地文件路径与模型访问参数。

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | string | 必填 | 书名或项目代号，用作输出目录与文档主标题 |
| `source` | string | 必填 | 语料文件路径，支持 `.epub`、`.docx`、`.txt` |
| `chunk_chars` | int | `60000` | 单分片目标字数 |
| `quote_open` | list | `["“", "「", "『"]` | 台词前引号。建议仅保留书内实际使用的符号 |
| `quote_close` | list | `["”", "」", "』"]` | 台词后引号。需与 `quote_open` 配对 |
| `person` | string | `"third"` | 叙述人称（`"first"` 或 `"third"`），注入提示词供模型对齐视点 |
| `protagonist` | string | `""` | 主角名称 |
| `vol_unit_word` | string | `"卷"` | 二层剧情归纳单位（如：卷、章、篇、ARC） |
| `names` | list | `[]` | 角色名列表，用于台词归属统计与角色档案归纳 |
| `drop_headings` | list | `["简介", "制作信息", "封面及彩页"]` | 文本抽取阶段直接丢弃的无正文标题 |
| `hard_settings` | list | `[]` | 注入《整书总结》开头的硬设定条目（建议 5-10 条） |
| `if_points` | list | `[]` | 注入《整书总结》开头的分歧点条目 |
| `llm` | object | 见下文 | 大模型调用后端配置 |
| `paths` | object | 可选 | 产物目录映射，默认指向 `work/` 下各子目录 |

### llm 后端配置

支持两种调用后端：**OpenAI 兼容接口** 与 **外部 CLI 命令**。

#### A. OpenAI 兼容接口（API / 本地引擎）

适用于云端大模型、vLLM、Ollama、LM Studio 等服务：

```jsonc
"llm": {
  "backend": "openai",
  "base_url": "https://api.example.com/v1",
  "api_key_env": "OPENAI_API_KEY",   // 读取 API Key 的环境变量名
  "model": "gpt-4o-mini",
  "temperature": 0.3,
  "max_tokens": 4096,
  "timeout": 600,
  "retries": 3,
  "concurrency": 16,
  "extra_body": {}                    // 传递给底层的额外请求体参数
}
```

#### B. 外部 CLI 命令（子代理 / 本地 Agent）

适用于调用本地 Agent 命令行工具执行独立会话：

```jsonc
"llm": {
  "backend": "command",
  "command": "my-agent -p --no-session --tools read,write < {prompt_file} > {out_file}",
  "concurrency": 8,
  "timeout": 1800,
  "retries": 3
}
```

- **命令占位符**：
  - `{prompt_file}`：当前任务的提示词临时文件路径。
  - `{out_file}`：期望产物输出文件路径。若命令结束时该文件未生成，系统默认捕获进程的 stdout 作为结果。
  - `{chunk_file}`：当前分片对应的文本文件路径。
- **权限建议**：子代理仅需开放本地文件读写权限，避免赋予网络访问权限以保证执行确定性。

#### 环境变量覆盖

支持通过环境变量临时覆盖 `project.json` 中的参数，无需修改配置文件：

```bash
REFPACK_MODEL=deepseek-chat \
REFPACK_BASE_URL=https://api.deepseek.com/v1 \
REFPACK_CONCURRENCY=32 \
python scripts/02_run_notes.py
```

---

## 2. 文风统计规则：`config/stylefit/*.json`

用于指导 `scripts/07_stylefit_index.py` 从语料中提取搭配习惯与描写特征：

| 配置文件 | 数据格式 | 用途 |
|---|---|---|
| `colloc.json` | `{"动作概念": ["动词/方位候选", ...]}` | 统计高频搭配；频次为 0 的项会被标记为搭配雷区 |
| `words.json` | `{"概念分类": ["词汇列表", ...]}` | 统计词汇分布；语料中未出现的词会列入零频黑名单 |
| `intents.json` | `{"意图分类": "匹配正则"}` | 抽取特定描写样本（如心理活动、神态描写） |
| `scenes.json` | `{"场景名称": ["特征词", ...]}` | 构建特定场景的描写词典与上下文样本 |
| `funcs.json` | `{"功能分类": "匹配正则"}` | 自定义台词功能桶分类（可选，默认使用内置分类） |

> **说明**：JSON 文件中以 `_` 开头的键会被自动忽略，可作为注释字段使用。

---

## 3. 提示词模板：`config/prompts/*.txt`

流水线各阶段使用的 Prompt 模版。运行时由系统自动填充上下文占位符：

| 模板文件名 | 执行阶段 | 可用占位符 |
|---|---|---|
| `stage1_note.txt` | Stage 2（分片一层摘要） | `{name}`, `{person}`, `{chunk_no}`, `{chunk_file}`, `{h1}`, `{first}`, `{last}`, `{chunk_text}` |
| `stage2_volume.txt` | Stage 5（分卷二层纪要） | `{name}`, `{unit}`, `{label}`, `{notes}` |
| `meta_positioning.txt` | Stage 5 `--meta`（作品定位） | `{name}`, `{material}` |
| `meta_world.txt` | Stage 5 `--meta`（世界观设定） | `{name}`, `{material}` |
| `meta_factions.txt` | Stage 5 `--meta`（势力阵营） | `{name}`, `{material}` |
| `meta_characters.txt` | Stage 5 `--meta`（角色档案） | `{name}`, `{material}` |
| `meta_ending.txt` | Stage 5 `--meta`（结局状态卡） | `{name}`, `{material}` |
| `meta_foreshadow.txt` | Stage 5 `--meta`（伏笔与分歧） | `{name}`, `{material}` |

> **扩展**：在 `config/prompts/` 下新增 `meta_*.txt` 文件后，`python scripts/05_run_volumes.py --meta` 会自动扫描并纳入归纳流程。

---

## 4. 负向规则配置：`config/bans.md`

用于收纳生成文本时严禁犯下的错误（如设定冲突、严重 OOC、高频 AI 腔句式）。
该文件内容会在生成阶段完整嵌入到《整书总结》与《例子集》的开篇位置，作为大模型写作时的首要负面清单。
