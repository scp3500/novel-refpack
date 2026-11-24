# 配置说明

项目通过 `config/` 目录管理小说流水线参数（`project.json`）、群聊/贴吧蒸馏参数（`chat.json`）、分题材文风统计预设（`stylefit_general/`、`stylefit_modern/`、`stylefit_fantasy/`、`stylefit_tieba/`、`stylefit/`）与提示词模板（`prompts/*.txt`）。

---

## 1. 小说项目配置：`config/project.json`

从模板初始化：
```bash
cp config/project.example.json config/project.json
```

该文件已列入 `.gitignore`，包含本地文件路径与模型访问参数。

### 核心字段

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | string | 必填 | 书名或项目代号，用作缓存目录与产物主标题 |
| `source` | string | 必填 | 语料文件路径，支持 `.epub`、`.docx`、`.txt`、`.srt`、`.ass` 及常见 Galgame 脚本文本 |
| `chunk_chars` | int | `60000` | 单分片目标字数 |
| `quote_open` | list | `["“", "「", "『"]` | 台词前引号（建议仅保留书内实际使用的符号） |
| `quote_close` | list | `["”", "」", "』"]` | 台词后引号（需与 `quote_open` 配对） |
| `person` | string | `"third"` | 叙述人称（`"first"` / `"third"`），注入提示词并用于 `11_verify.py` 视点分桶参考 |
| `protagonist` | string | `""` | 主角名称 |
| `vol_unit_word` | string | `"卷"` | 二层归纳单位（如：卷、章、篇、ARC） |
| `names` | list | `[]` | 角色名列表，用于台词归属统计、人物档案与纯文风脱敏（可用 `06b_suggest_entities.py` 自动扫描候选） |
| `aliases` | object | `{}` | 角色别名映射 `{"主名": ["别名1", "昵称2"]}`，归属统计自动合并到主名 |
| `stylefit_dir` | string | `"config/stylefit"` | 文风规则目录或内置预设简称：`general` / `modern` / `fantasy` / `tieba`（模板默认推荐 `"general"`），也支持自定义相对/绝对目录 |
| `bans_file` | string | `"config/bans.md"` | 负向禁区规则文件路径（相对仓库根或绝对路径），每本书建议指向私有文件避免污染仓库 |
| `drop_headings` | list | `["简介", "制作信息", "封面及彩页"]` | 抽取阶段直接丢弃的无正文标题 |
| `drop_builtin_meta` | bool | `true` | EPUB 抽取时自动剔除版权页、奥付、问卷、目次、后记、访谈等内置非正文页 |
| `drop_file_patterns` | list | `[]` | 额外按 EPUB 内部文件路径正则丢弃的文件列表 |
| `drop_text_patterns` | list | `[]` | 额外按页首正文正则丢弃的非正文页列表 |
| `drop_lines` | list | `[]` | 精确匹配的孤立噪声行列表 |
| `drop_line_patterns` | list | `[]` | 按正则剔除的噪声行列表（如 `"^Piece\\s+of\\s*[:：]"`、水印/页眉行） |
| `strip_before_first_heading` | bool | `false` | 为 `true` 时丢弃首个标题之前的扉页/序言杂项 |
| `strip_footnotes` | bool | `false` | 为 `true` 时清理正文内的尾注/脚注标记与注释行 |
| `style_only` | bool | `false` | 为 `true` 时默认走纯文风蒸馏模式，剥离原书剧情绑定 |
| `anonymize` | bool | `false` | 为 `true` 时对角色名、专名与设定框执行脱敏替换 |
| `anonymize_style` | string | `"neutral"` | 脱敏命名风格：`neutral`（`某甲/某乙/某丙`）或 `names`（自然假名如 `林远/苏晴/陈默`，减少代称违和感） |
| `anonymize_terms` | object | `{}` | 专名脱敏映射 `{"原书地名/学校/组织": "某地"}`，防止原创写作带出原书世界观专名 |
| `single_char_names` | list/object | `[]` | 单字人名安全脱敏配置（如 `["朋", "梓"]` 或带上下文规则的字典），避免误伤普通汉字词语 |
| `budget` | object | 见下文 | 容量预算、估算 Token 与例子/摘要占比控制 |
| `hard_settings` | list | `[]` | 注入《整书总结》开头的硬设定条目（建议 5-10 条） |
| `if_points` | list | `[]` | 注入《整书总结》开头的 IF 分歧点条目 |
| `meta_material_chars` | int | `60000` | `05_run_volumes.py --meta` 喂给元章节的最大材料字数 |
| `volume_note_char_limit` | int | `9000` | `05_run_volumes.py` 读入单份分片摘要时的最大字数上限 |
| `llm` | object | 见下文 | 大模型调用后端配置 |
| `paths` | object | 可选 | 产物目录映射，默认指向 `work/` 下各子目录 |

### `budget` 容量与配比配置

```jsonc
"budget": {
  "preset": "standard",     // compact(60KB) / standard(150KB) / rich(300KB) / full(不限)
  "target_kb": null,        // 显式指定目标总 KB（优先级高于 preset）
  "max_tokens": null,       // 显式指定估算总 Token 上限（优先级高于 preset）
  "example_ratio": 0.70     // 例子占总预算比例，默认 0.70（70% 例子 : 30% 摘要）
}
```

### `llm` 后端配置

#### A. OpenAI 兼容接口（API / 本地引擎）
```jsonc
"llm": {
  "backend": "openai",
  "base_url": "https://api.example.com/v1",
  "api_key_env": "OPENAI_API_KEY",
  "model": "gpt-4o-mini",
  "temperature": 0.3,       // 设为 null 则不发送 temperature 字段（兼容部分推理模型）
  "max_tokens": 4096,
  "timeout": 600,
  "retries": 3,
  "concurrency": 16,
  "strip_think": true,      // 自动剥离输出中的 <think>...</think> 推理块
  "extra_body": {}
}
```

#### B. 外部 CLI 命令（子代理 / 本地 Agent）
```jsonc
"llm": {
  "backend": "command",
  "command": "my-agent -p --no-session --tools read,write < {prompt_file} > {out_file}",
  "concurrency": 8,
  "timeout": 1800,
  "retries": 3
}
```

- **命令占位符**：`{prompt_file}`、`{out_file}`、`{chunk_file}`（若未写出 `{out_file}` 则回退捕获 stdout）。
- **Windows 注意**：`cmd.exe` 不支持单引号，命令模板需包路径时请统一使用双引号 `"`。
- **环境变量覆盖**：`REFPACK_CONFIG`、`REFPACK_MODEL`、`REFPACK_BASE_URL`、`REFPACK_BACKEND`、`REFPACK_CONCURRENCY`。

---

## 2. 群聊 / 贴吧配置：`config/chat.json`

从 `config/chat.example.json` 复制修改，可通过 `CHAT_CONFIG` 环境变量或 `--config` 指定：

| 字段 | 说明 |
|---|---|
| `source` | 贴吧导出 JSON 或 QQ 群导出 TXT 路径 |
| `work_dir` | chat 流水线工作目录（默认 `"work"`，输出 `<work_dir>/out/群聊人设提示词.md`） |
| `format` | `"tieba_json"` 或 `"qq_txt"` |
| `target_user` | 可选，仅提取指定用户的发言进行蒸馏 |
| `min_chars` / `max_chars` | 过滤过短或过长刷屏回复的长度边界 |
| `drop_title_patterns` / `drop_text_patterns` | 过滤水楼、签到帖、纯数字与表情占位符的正则列表 |

---

## 3. 分题材文风统计预设：`stylefit_dir`

在 `config/project.json` 中设置 `"stylefit_dir"` 即可一键切换题材预设（无需手动改 JSON），也可复制任意预设目录定制私有词典：

| 预设简称 / 目录 | 对应目录 | 适用题材 |
|---|---|---|
| `general` | `config/stylefit_general/` | **通用文学 / 现实叙事（零奇幻/系统偏置）**：覆盖冲突争执、内心转折、环境光影、动作细节与对话日常 |
| `modern` | `config/stylefit_modern/` | **现代都市 / 校园 / 日常 / 恋爱轻小说**：内置手机/简讯/车站/咖啡/雨/夕阳/视线回避/低语等高频表达 |
| `fantasy` | `config/stylefit_fantasy/` | **奇幻 / 异世界 / 战斗 / 系统面板**：覆盖武器交锋、施法魔力、公会小队、迷宫探索与系统数值 |
| `tieba` | `config/stylefit_tieba/` | **贴吧 / 群聊 / 口语吐槽语料** |
| *(缺省兼容)* | `config/stylefit/` | 保留旧版默认规则目录，向后兼容已有项目 |

### 预设目录内的 7 个 JSON 文件

| 配置文件 | 数据格式 | 用途 |
|---|---|---|
| `colloc.json` | `{"动作概念": ["候选说法", ...]}` | 统计高频动作/神态/方位搭配；0 次出现项标记为搭配雷区 |
| `words.json` | `{"概念分类": ["词汇列表", ...]}` | 统计词汇分布；0 次出现项列入零频黑名单 |
| `intents.json` | `{"意图分类": "匹配正则"}` | 抽取各类描写意图的完整句群样本 |
| `scenes.json` | `{"场景名称": ["特征词", ...]}` | 构建场景词典（含常用 / 少用 / 禁用三档） |
| `topics.json` | `{"主题名": "匹配正则"}` | `09_build_examples.py` 专项摘录主题（默认模式下使用） |
| `scene_rules.json` | `{"场景名": "匹配正则"}` | 指导 `build_index.py` 按题材切分场景片段（未命中归入「日常」） |
| `funcs.json` | `{"功能分类": "匹配正则"}` | 覆盖默认台词功能桶分类规则（按声明顺序首次命中归桶） |

> **说明**：JSON 中以 `_` 开头的键会被忽略，可用作注释。

---

## 4. 提示词模板与负向禁区

- `config/prompts/stage1_note.txt`、`stage2_volume.txt`、`meta_*.txt`：一/二层摘要与元章节提示词（新增 `meta_*.txt` 会被 `05_run_volumes.py --meta` 自动发现）。
- `config/bans.md`：通用反 AI 腔、动作视点纪律与**六大结构/修辞型 AI 腔**正反对比模板。为具体小说定制角色/设定禁区时，建议在 `config/project.json` 中通过 `"bans_file"` 指向私有文件，避免公开提交具体作品设定。
