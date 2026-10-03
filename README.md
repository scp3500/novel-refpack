# novel-refpack

把一本长篇（小说 / 剧本 / 系列文，十万到几百万字）加工成两份文件，用来喂给大模型做续写、写 IF 线、写同人、做仿写：

| 产物 | 定位 | 内容 |
|---|---|---|
| `work/out/整书总结.md` | **事实圣经** | 世界观、剧情走向、角色状态、伏笔、IF 分歧点、禁区 |
| `work/out/例子.txt` | **文风语料** | 逐字原文摘录：叙述腔、台词分角色、描写套路、名场面、搭配表、零频黑名单 |

整书总结防止模型把剧情写飞，例子集防止模型写出来有 AI 味。两份配套使用。

不绑定任何 agent 框架：摘要任务走**任意 OpenAI 兼容接口**，也可以换成**一条 shell 命令**（把你自己的 CLI / agent 接进来）。

---

## 快速开始

```bash
git clone <this-repo> && cd novel-refpack
pip install -r requirements.txt          # 只用标准库也能跑，见 requirements.txt 说明

cp config/project.example.json config/project.json
#  编辑 config/project.json：填 source（书的位置）、names（角色名）、引号体系

# 不花钱、不调模型的部分（先跑这个确认抽取质量）
python scripts/00_extract.py        # 抽文本   → work/raw/_all.txt + sections.json
python scripts/01_split.py          # 分片     → work/chunks/ + work/manifest.json

# 摘要两条流水线（并发，可中断可重跑）
python scripts/02_run_notes.py      # 一层摘要 → work/notes/chunk_NN.md
python scripts/03_merge_notes.py    # 汇总     → work/all_notes.md（带片尾覆盖率校验）
python scripts/04_build_volume_map.py   # 卷映射 → work/volumes/ + work/volume_map.json
python scripts/05_run_volumes.py    # 二层     → work/notes/vol/vol_NN.md
python scripts/05_run_volumes.py --meta # 元章节 → work/notes/meta/*.md

# 文风索引与两份成品
python scripts/06_build_attrib.py   # 台词归属 → work/attrib.json
python scripts/07_stylefit_index.py # 文风索引 → work/cache/<name>/index.json
python scripts/08_stylefit_query.py --stats   # 查索引（写作前必查）
python scripts/09_build_examples.py # 例子集   → work/out/例子.txt
python scripts/10_build_summary.py  # 整书总结 → work/out/整书总结.md

# 验收
python scripts/11_verify.py --text <你的稿子>
```

一把跑完：`bash scripts/12_run_all.sh`（`--no-llm` 只跑不调模型的那几段）。
中途失败直接重跑同一条命令：已完成的片会跳过，缺的补上（`--only 3,7` 指定编号）。

---

## 目录结构

```
novel-refpack/                        ← 工具目录：只放代码、配置、文档
├─ scripts/          流水线，编号即执行顺序（00 → 12）
│  ├─ 00_extract      抽文本          │ 06_build_attrib   台词归属
│  ├─ 01_split        分片            │ 07_stylefit_index 文风索引
│  ├─ 02_run_notes    一层摘要（并发）│ 08_stylefit_query 查索引
│  ├─ 03_merge_notes  汇总 + 校验     │ 09_build_examples 例子集
│  ├─ 04_build_volume_map 卷映射      │ 10_build_summary  整书总结
│  ├─ 05_run_volumes  二层 / --meta   │ 11_verify         验收
│  └─ 12_run_all.sh   一把跑完
├─ stylefit/         文风工具包（纯语料驱动，可单独用）
│  ├─ SKILL.md       方法说明 + 写作规矩
│  ├─ build_index.py 建索引 · query.py 查 · verify.py 验收
├─ lib/              公共库：textio（读写）· llm（模型后端）· corpus（语料）· project（配置）
├─ config/           全部可改，不含代码
│  ├─ project.example.json   项目配置模板 → 复制成 project.json
│  ├─ bans.md                禁区（模型最容易犯的错，嵌进两份成品）
│  ├─ prompts/               stage1_* / stage2_* / meta_*（新加 meta_xxx 会被自动发现）
│  └─ stylefit/              colloc 搭配 · words 用词 · intents 意图 · scenes 场景
├─ docs/
│  ├─ WORKFLOW.md    流程详解：每步的输入输出、验收判据、上下文预算
│  ├─ PARALLEL.md    并行：开多少路子代理、并发怎么定、防跑歪的规则
│  ├─ TEMPLATES.md   模板与两份成品的骨架 + 喂给模型的提示词骨架
│  ├─ PITFALLS.md    坑与指标目标值
│  └─ CONFIG.md      配置字段速查
└─ work/             跑出来的数据（已 gitignore，删了可重建）
   └─ raw/ chunks/ volumes/ notes/{,vol,meta}/ cache/ out/ logs/
      manifest.json  volume_map.json  attrib.json  all_notes.md
```

一句话分界：**仓库根以外的东西都可提交，`work/` 里的东西都可删。**

## 两套脚本

**流水线**（`scripts/`）：抽文本 → 分片 → 并发摘要 → 汇总 → 卷纪要 → 归属 → 索引 → 生成两份成品 → 验收。

**stylefit**（`stylefit/`）：从语料本身拟合文风，不需要人工标注。

```bash
python stylefit/build_index.py --corpus work/chunks --out work/cache/mybook --names 甲,乙,丙
python stylefit/query.py --index work/cache/mybook/index.json --colloc 耳朵的动作
python stylefit/query.py --index work/cache/mybook/index.json --who 主角 --func 让步接受
python stylefit/verify.py --text 稿子.txt --corpus work/chunks --out work/cache/mybook --ref-pattern '(猫|尾巴)'
```

用 `scripts/07` ~ `scripts/11` 调时路径已配好，不用手写这些参数。

`verify.py` 出四层结果：门槛（在不在范围内）、结构（自打乱比值）、逐句（字符 4-gram 的 z 值）、0 频探针（新造 4-gram 倍数）。

## 并行：开几十路子代理

摘要阶段是 **一片 = 一个独立任务**，彼此不看对方的输入，所以可以放心开到几十路：

| 阶段 | 任务数 | 实测并发 |
|---|---|---|
| 一层摘要（每片一个） | = 片数（26 / 78 / 上百） | **25–78 路** |
| 二层卷纪要（每卷一个） | = 卷数 | 30–35 路 |
| 元章节（世界观/角色/势力…） | 6 个 | 6 路 |

实测：114 万字 → 26 片 → 25 路并发；444 万字 → 78 片 → 76 路并发（`PAR=50` 排队）。

```bash
python scripts/02_run_notes.py --par 50       # 并发数直接传
python scripts/02_run_notes.py --only 7,23    # 补跑指定片，已完成的自动跳过
```

用**子代理**跑（每个子代理一个独立上下文，上下文天然不被污染）：

```jsonc
"llm": {
  "backend": "command",
  "command": "my-agent -p --no-session --tools read,write < {prompt_file} > {out_file}",
  "concurrency": 50, "timeout": 1800, "retries": 3
}
```

细节、并发数怎么定、防止几十路跑歪的规则：见 [`docs/PARALLEL.md`](docs/PARALLEL.md)。

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
- 并行与子代理：开多少路、怎么接、怎么防跑歪：[`docs/PARALLEL.md`](docs/PARALLEL.md)
- 摘要模板和成品骨架：[`docs/TEMPLATES.md`](docs/TEMPLATES.md)
- 常见坑与指标目标：[`docs/PITFALLS.md`](docs/PITFALLS.md)
- 配置字段：[`docs/CONFIG.md`](docs/CONFIG.md)

## License

MIT
