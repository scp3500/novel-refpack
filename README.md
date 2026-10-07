# novel-refpack

把一本长篇（小说 / 剧本 / 系列文，大约十万到几百万字）处理成两份文件，供大模型续写、写 IF 线、写同人或仿写时当参考：

| 产物 | 作用 | 内容 |
|---|---|---|
| `work/out/整书总结.md` | 事实参考 | 世界观、剧情走向、角色状态、伏笔、IF 分歧点、禁区 |
| `work/out/例子.txt` | 文风语料 | 原文摘录：叙述腔、分角色台词、描写套路、名场面、搭配表、零频黑名单 |

整书总结用来约束剧情，例子集用来贴近原文写法。两份一起用。

摘要任务可以用任意 OpenAI 兼容接口，也可以改成一条 shell 命令（接自己的 CLI / agent）。

---

## 快速开始

```bash
git clone <this-repo> && cd novel-refpack
pip install -r requirements.txt          # 只用标准库也能跑，见 requirements.txt

cp config/project.example.json config/project.json
# 编辑 config/project.json：填 source（书的位置）、names（角色名）、引号体系

# 不调模型的部分（可先跑，检查抽取结果）
python scripts/00_extract.py        # 抽文本   → work/raw/_all.txt + sections.json
python scripts/01_split.py          # 分片     → work/chunks/ + work/manifest.json

# 摘要（可并发；失败可重跑）
python scripts/02_run_notes.py      # 一层摘要 → work/notes/chunk_NN.md
python scripts/03_merge_notes.py    # 汇总     → work/all_notes.md（含片尾覆盖率校验）
python scripts/04_build_volume_map.py   # 卷映射 → work/volumes/ + work/volume_map.json
python scripts/05_run_volumes.py    # 二层     → work/notes/vol/vol_NN.md
python scripts/05_run_volumes.py --meta # 元章节 → work/notes/meta/*.md

# 文风索引与成品
python scripts/06_build_attrib.py   # 台词归属 → work/attrib.json
python scripts/07_stylefit_index.py # 文风索引 → work/cache/<name>/index.json
python scripts/08_stylefit_query.py --stats   # 查索引
python scripts/09_build_examples.py # 例子集   → work/out/例子.txt
python scripts/10_build_summary.py  # 整书总结 → work/out/整书总结.md

# 验收
python scripts/11_verify.py --text <你的稿子>
```

全部跑完：`bash scripts/12_run_all.sh`（加 `--no-llm` 则只跑不调模型的步骤）。

中途失败可直接重跑同一条命令：已完成的片会跳过，缺的会补上（`--only 3,7` 可指定编号）。

---

## 目录结构

```
novel-refpack/                        ← 工具目录：代码、配置、文档
├─ scripts/          流水线，编号即执行顺序（00 → 12）
│  ├─ 00_extract      抽文本          │ 06_build_attrib   台词归属
│  ├─ 01_split        分片            │ 07_stylefit_index 文风索引
│  ├─ 02_run_notes    一层摘要（并发）│ 08_stylefit_query 查索引
│  ├─ 03_merge_notes  汇总 + 校验     │ 09_build_examples 例子集
│  ├─ 04_build_volume_map 卷映射      │ 10_build_summary  整书总结
│  ├─ 05_run_volumes  二层 / --meta   │ 11_verify         验收
│  └─ 12_run_all.sh   全部跑完
├─ stylefit/         文风工具（按语料建索引，也可单独用）
│  ├─ SKILL.md       方法说明与写作规则
│  ├─ build_index.py 建索引 · query.py 查询 · verify.py 验收
├─ lib/              公共库：textio（读写）· llm（模型后端）· corpus（语料）· project（配置）
├─ config/           配置（无代码）
│  ├─ project.example.json   项目配置模板 → 复制为 project.json
│  ├─ bans.md                禁区（会写进两份成品）
│  ├─ prompts/               stage1_* / stage2_* / meta_*（新增 meta_xxx 会自动发现）
│  └─ stylefit/              colloc 搭配 · words 用词 · intents 意图 · scenes 场景
├─ docs/
│  ├─ WORKFLOW.md    各步输入输出、验收标准、上下文预算
│  ├─ PARALLEL.md    并发与子代理用法
│  ├─ TEMPLATES.md   模板与成品骨架
│  ├─ PITFALLS.md    常见问题与指标参考
│  └─ CONFIG.md      配置字段说明
└─ work/             运行产物（已 gitignore，删了可重建）
   └─ raw/ chunks/ volumes/ notes/{,vol,meta}/ cache/ out/ logs/
      manifest.json  volume_map.json  attrib.json  all_notes.md
```

仓库里除 `work/` 外的内容都可以提交；`work/` 里的内容都可以删。

## 两套脚本

**流水线**（`scripts/`）：抽文本 → 分片 → 并发摘要 → 汇总 → 卷纪要 → 归属 → 索引 → 生成两份成品 → 验收。

**stylefit**（`stylefit/`）：从语料统计文风特征，不需要人工标注。

```bash
python stylefit/build_index.py --corpus work/chunks --out work/cache/mybook --names 甲,乙,丙
python stylefit/query.py --index work/cache/mybook/index.json --colloc 耳朵的动作
python stylefit/query.py --index work/cache/mybook/index.json --who 主角 --func 让步接受
python stylefit/verify.py --text 稿子.txt --corpus work/chunks --out work/cache/mybook --ref-pattern '(猫|尾巴)'
```

用 `scripts/07`～`scripts/11` 调用时路径已配好，一般不用手写这些参数。

`verify.py` 输出四层结果：门槛（是否在范围内）、结构（自打乱比值）、逐句（字符 4-gram 的 z 值）、0 频探针（新造 4-gram 倍数）。

## 并行

摘要阶段一片对应一个独立任务，任务之间不共享输入，可以开较高并发：

| 阶段 | 任务数 | 参考并发 |
|---|---|---|
| 一层摘要（每片一个） | = 片数（26 / 78 / 更多） | 25–78 路 |
| 二层卷纪要（每卷一个） | = 卷数 | 30–35 路 |
| 元章节（世界观/角色/势力等） | 6 个 | 6 路 |

参考数据：114 万字 → 26 片 → 25 路并发；444 万字 → 78 片 → 76 路并发（`PAR=50` 排队）。

```bash
python scripts/02_run_notes.py --par 50       # 指定并发数
python scripts/02_run_notes.py --only 7,23    # 补跑指定片，已完成的跳过
```

用子代理跑时（每个子代理独立上下文）：

```jsonc
"llm": {
  "backend": "command",
  "command": "my-agent -p --no-session --tools read,write < {prompt_file} > {out_file}",
  "concurrency": 50, "timeout": 1800, "retries": 3
}
```

并发设置与注意事项见 [`docs/PARALLEL.md`](docs/PARALLEL.md)。

## 摘要任务用什么跑

在 `config/project.json` 的 `llm` 段二选一：

```jsonc
// A. OpenAI 兼容接口（本地 vLLM / Ollama / 各家 API）
"llm": { "backend": "openai", "base_url": "http://127.0.0.1:8000/v1",
         "api_key_env": "OPENAI_API_KEY", "model": "your-model",
         "concurrency": 16 }

// B. 任意 CLI：{prompt_file} / {out_file} 会替换成实际路径
"llm": { "backend": "command",
         "command": "my-agent -p --no-session < {prompt_file} > {out_file}",
         "concurrency": 8 }
```

B 模式只要工具能读提示词文件、写输出文件即可接入。

## 详细文档

- 流程说明：[`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- 并行与子代理：[`docs/PARALLEL.md`](docs/PARALLEL.md)
- 模板与成品骨架：[`docs/TEMPLATES.md`](docs/TEMPLATES.md)
- 常见问题与指标：[`docs/PITFALLS.md`](docs/PITFALLS.md)
- 配置字段：[`docs/CONFIG.md`](docs/CONFIG.md)

## License

MIT
