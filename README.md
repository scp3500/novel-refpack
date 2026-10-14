# novel-refpack

把一本长篇小说加工成两份轻量参考文件，喂给大模型解决长篇写作的两大痛点：

| 交付文件 | 定位 | 作用 |
|---|---|---|
| `work/out/整书总结.md` | 原作总结 | 世界观、全卷分剧情、角色现状、伏笔、设定禁区 —— **锁住事实，防止吃书** |
| `work/out/例子.txt` | 例子总结 | 叙述腔调、角色口癖、动作搭配表、零频黑名单 —— **锁住文风，贴近原作** |

主要工作是提炼上述两份总结。字符 4-gram 统计等质检工作默认不做，纯属可选。

---

## 快速上手

### 模式 A · 首选推荐：直接让当前 Agent 执行（零配置、免 API Key）

如果你正在使用 Coding Agent（如 Pi、Claude Code、Cursor 等）：
**无需配置任何 API Key 或模型端点，更不需要手动调参。**

当前模型本身具备子代理编排与读写能力。把书（`.epub` / `.txt`）放入目录后，直接对 Agent 发一句指令：

> **“帮我把《书名》处理成整书总结和例子集。先本地切片，再派子代理跑分片纪要并汇总生成成品。”**

Agent 会自动在后台完成切片、派发子代理并行提取、并总装生成交付文件。

---

### 模式 B · 备选方案：独立脚本 + 外部 API（脱离 Agent 批量挂机）

若脱离了交互式 Agent 窗口，需在服务器后台批量跑任务：

```bash
git clone <this-repo> && cd novel-refpack
cp config/project.example.json config/project.json  # 填入书名、路径、API 或本地模型端点

python scripts/12_run_all.py                        # 全平台一键执行（Windows 推荐 python -X utf8）
python scripts/12_run_all.py --no-llm               # 仅运行本地离线部分（抽文本、分片、建索引）
```

---

## 拿到的结果怎么用

将生成的两份文件拼装为系统提示词与上下文：

```text
[System Prompt]
你是一名专业小说作家。必须严格遵守以下事实与设定禁令：
--- 粘贴《整书总结.md》中的设定、角色状态与禁令 ---

[Few-Shot / Context]
请严格模仿以下原文的叙述腔与对白习惯：
--- 粘贴《例子.txt》中的角色语气样本与描写范例 ---

[User Prompt]
请写一段剧情：[你的具体续写或 IF 线需求]
```

---

## 进阶模式（不止于还原原作）

除还原原作同人与 IF 线外，本项目还支持以下三种拓展创作模式（详见 [docs/MODES.md](docs/MODES.md)）：

1. **模式 1 · 纯文风抽取与原创写作**：剥离原著剧情和人名，仅借用作家的叙事节奏与笔法写全新原创故事；
2. **模式 2 · 双文风正交融合**：按维度切分（如 A 的冷硬动作叙述 + B 的轻小说机智对白），组合出全新文学张力；
3. **模式 3 · 反 AI 腔与特征过滤**：利用语料搭配表和高阶负面提示词，精准洗掉大模型的机械套话与公文腔。

---

## 详细文档

- 高阶创作与反 AI 提示词：[`docs/MODES.md`](docs/MODES.md)
- 完整流水线细节：[`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- 配置文件说明：[`docs/CONFIG.md`](docs/CONFIG.md)
- 并行与子代理原理：[`docs/PARALLEL.md`](docs/PARALLEL.md)
- 常见问题与指标：[`docs/PITFALLS.md`](docs/PITFALLS.md)

## License

MIT
