# 配置说明

## config/project.json

先从模板复制：`cp config/project.example.json config/project.json`。
这个文件已在 `.gitignore` 里（含本机路径）。

| 字段 | 默认 | 说明 |
|---|---|---|
| `name` | — | 书名，用于输出目录和标题 |
| `source` | — | 源文件路径（`.epub` / `.docx` / `.txt`） |
| `chunk_chars` | `60000` | 每片目标字数 |
| `quote_open` / `quote_close` | `["“","「","『"]` / `["”","」","』"]` | 引号体系。**只填你书里实际用的**，填多了会误切 |
| `person` | `"third"` | `first` / `third`，只写进提示词供模型参考 |
| `protagonist` | `""` | 主角名，部分脚本会用到 |
| `vol_unit_word` | `"卷"` | 二层归纳的单位叫法：卷 / 章 / 篇 / ARC |
| `names` | `[]` | 角色名列表。**自动抓台词归属和语音档案靠它**，越全越好 |
| `drop_headings` | `["简介","制作信息","封面及彩页"]` | 抽文本时整段丢弃的标题 |
| `hard_settings` | `[]` | 整书总结「〇.1 硬设定速查」的条目，5-10 条 |
| `if_points` | `[]` | 整书总结「〇.4 IF 分歧点」的条目 |
| `llm` | 见下 | 模型后端配置（API / 子代理 CLI） |

### llm 段

```jsonc
// A. OpenAI 兼容接口（本地 vLLM / Ollama / LM Studio / 云端 API）
"llm": {
  "backend": "openai",
  "base_url": "http://127.0.0.1:8000/v1",
  "api_key_env": "OPENAI_API_KEY",   // 从这个环境变量读 key
  "model": "your-model",
  "temperature": 0.3,
  "max_tokens": 4096,
  "timeout": 600,
  "retries": 3,
  "concurrency": 16,
  "extra_body": {}                    // 需要额外参数时塞这里
}

// B. 任意 CLI（把你的 agent 接进来）
"llm": {
  "backend": "command",
  "command": "my-agent -p --no-session < {prompt_file} > {out_file}",
  "concurrency": 8,
  "timeout": 1800,
  "retries": 3
}
```

`command` 里可用占位符：`{prompt_file}` `{out_file}` `{chunk_file}`。
命令跑完若 `{out_file}` 不存在，就取命令的 stdout 当结果。

**B 模式就是子代理模式**：一个子代理只干一个任务（一片 / 一卷），各自独立上下文。
示例中的 `--tools read,write` 是刻意的——只给读写，别给它联网，也别让它去翻别的片。
实测并发 25–78 路可用，并发数、排空时间与防跑歪规则见 `docs/PARALLEL.md`。

**环境变量覆盖**（不改文件也能切模型）：

```bash
REFPACK_MODEL=xxx REFPACK_BASE_URL=http://... REFPACK_CONCURRENCY=32 \
  python scripts/02_run_notes.py
```

### paths 段

默认 `raw/ chunks/ notes/ volumes/ cache/ out/ logs/`，相对仓库根。

## config/stylefit/*.json

| 文件 | 结构 | 作用 |
|---|---|---|
| `colloc.json` | `{"概念": ["候选说法", ...]}` | **搭配表**，最高杠杆。0 次的说法进雷区 |
| `words.json` | `{"概念": ["词", ...]}` | 用词表；0 次的进零频黑名单 |
| `intents.json` | `{"意思名": "正则"}` | 描写意图样本，回答「这个意图书里怎么写」 |
| `scenes.json` | `{"场景名": ["词", ...]}` | 场景词典，写同类场景前查 |
| `funcs.json` | `{"功能桶": "正则"}` | 可选，覆盖内置的台词功能桶分类 |

命名以 `_` 开头的键会被跳过，用来写注释。

## config/prompts/*.txt

| 文件 | 阶段 | 占位符 |
|---|---|---|
| `stage1_note.txt` | 一层摘要 | `{name} {person} {chunk_no} {chunk_file} {h1} {first} {last} {chunk_text}` |
| `stage2_volume.txt` | 二层卷纪要 | `{name} {unit} {label} {notes}` |
| `meta_positioning.txt` | 作品定位 | `{name} {material}` |
| `meta_world.txt` | 世界观与设定 | `{name} {material}` |
| `meta_factions.txt` | 势力阵营 | `{name} {material}` |
| `meta_characters.txt` | 角色档案 | `{name} {material}` |
| `meta_ending.txt` | 结局现状卡 | `{name} {material}` |
| `meta_foreshadow.txt` | 伏笔与分叉点 | `{name} {material}` |

新增 `meta_xxx.txt` 会自动被 `05_run_volumes.py --meta` 发现并执行。

## config/bans.md

原样嵌进「例子集」和「整书总结」的开头。写模型每次都会犯的错，
一条一句，出现新的 OOC 就回填。这是整套东西里投入产出比最高的一份文件。
