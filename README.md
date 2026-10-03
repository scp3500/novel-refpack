# novel-refpack

把一本长篇（小说 / 剧本 / 系列文，十万到几百万字）加工成两份文件，用来喂给大模型做续写、写 IF 线、写同人、做仿写：

| 产物 | 定位 | 内容 |
|---|---|---|
| `out/整书总结.md` | **事实圣经** | 世界观、剧情走向、角色状态、伏笔、IF 分歧点、禁区 |
| `out/例子.txt` | **文风语料** | 逐字原文摘录：叙述腔、台词分角色、描写套路、名场面、搭配表、零频黑名单 |

整书总结防止模型把剧情写飞，例子集防止模型写出来有 AI 味。两份配套使用。

不绑定任何 agent 框架：摘要任务走**任意 OpenAI 兼容接口**，也可以换成**一条 shell 命令**（把你自己的 CLI / agent 接进来）。

---

## 快速开始

```bash
git clone <this-repo> && cd novel-refpack
pip install -r requirements.txt          # 只用标准库也能跑，见 requirements.txt 说明

cp config/project.example.json config/project.json
#  编辑 config/project.json：填 source（书的位置）、names（角色名）、引号体系

python scripts/00_extract.py             # 0 抽文本   → raw/_all.txt + raw/sections.json
python scripts/01_split.py               # 1 分片     → chunks/ + manifest.json
python scripts/02_run_notes.py           # 2 一层摘要 → notes/chunk_NN.md（并发）
python scripts/03_merge_notes.py         # 3 汇总     → all_notes.md
python scripts/04_build_volume_map.py    # 4 建卷映射 → volumes/ + volume_map.json
python scripts/05_run_volumes.py         # 5 二层归纳 → notes/vol/vol_NN.md
python scripts/05_run_volumes.py --meta  #   （可选）设定/角色/势力/伏笔等元章节

python scripts/06_build_attrib.py        # 6 台词归属 → attrib.json
python scripts/07_stylefit_index.py      # 7 文风索引 → cache/<name>/index.json
python scripts/08_stylefit_query.py --stats   # 查索引（写作前必查）

python scripts/09_build_examples.py      # 8 生成例子集 → out/例子.txt
python scripts/10_build_summary.py       # 9 生成整书总结 → out/整书总结.md
python scripts/11_verify.py --text <稿子> # 10 验收（对生成的示范段 / 你的稿子）
```

中途失败直接重跑同一条命令：已完成的片会跳过，缺的补上（`--only 3,7` 可指定编号）。

---

## 目录结构

```
novel-refpack/
├─ scripts/          流水线（按编号顺序跑）
├─ stylefit/         文风拟合工具包（建索引 / 查询 / 验收）
├─ lib/              公共库：文本 IO、模型调用、语料解析
├─ config/
│  ├─ project.example.json   项目配置模板
│  ├─ prompts/               各阶段提示词模板（可直接改）
│  └─ stylefit/              文风索引的词表：搭配 / 意图 / 场景 / 用词
├─ docs/
│  ├─ WORKFLOW.md    七阶段详解：输入输出、验收标准、上下文预算
│  ├─ TEMPLATES.md   摘要模板 + 两份成品的结构骨架
│  ├─ PITFALLS.md    踩过的坑 + 指标目标值
│  └─ CONFIG.md      配置字段说明
└─ work/             跑出来的数据（已 gitignore）
   ├─ raw/ chunks/ notes/ notes/vol/ volumes/ cache/ logs/ out/
```

## 两套脚本

**流水线**（`scripts/`）：抽文本 → 分片 → 并发摘要 → 汇总 → 卷纪要 → 归属 → 索引 → 生成两份成品 → 验收。

**stylefit**（`stylefit/`）：从语料本身拟合文风，不需要人工标注。

```bash
python stylefit/build_index.py --corpus chunks --out cache/mybook --names 甲,乙,丙
python stylefit/query.py --index cache/mybook/index.json --colloc 耳朵的动作
python stylefit/query.py --index cache/mybook/index.json --who 主角 --func 让步接受
python stylefit/verify.py --text 稿子.txt --corpus chunks --out cache/mybook --ref-pattern '(猫|尾巴)'
```

`verify.py` 出四层结果：门槛（在不在范围内）、结构（自打乱比值）、逐句（字符 4-gram 的 z 值）、0 频探针（新造 4-gram 倍数）。

## 摘要任务用什么跑

`config/project.json` 的 `llm` 段二选一：

```jsonc
// A. OpenAI 兼容接口（本地 vLLM / Ollama / 各家 API 都行）
"llm": { "backend": "openai", "base_url": "http://127.0.0.1:8000/v1",
         "api_key_env": "OPENAI_API_KEY", "model": "your-model",
         "concurrency": 16 }

// B. 任意 CLI：{prompt_file} / {out_file} 会被替换成实际路径
"llm": { "backend": "command",
         "command": "my-agent -p --no-session < {prompt_file} > {out_file}",
         "concurrency": 8 }
```

B 模式就是给「不用某个特定 agent 的人」留的口子：只要你的工具能读一个提示词文件、写一个输出文件，就能接进来。

## 详细文档

- 方法怎么设计、每一步为什么这么做：[`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- 摘要模板和成品骨架：[`docs/TEMPLATES.md`](docs/TEMPLATES.md)
- 常见坑与指标目标：[`docs/PITFALLS.md`](docs/PITFALLS.md)
- 配置字段：[`docs/CONFIG.md`](docs/CONFIG.md)

## License

MIT
