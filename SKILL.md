---
name: novel-refpack
description: 把长篇小说、剧本/字幕或群聊语料加工成轻量喂模型参考包（整书总结 + 高密度文风例子集 + 一键合并参考包），支持主动确认容量预算（KB / Tokens / 例子占比）、目标书高频特征词表对齐、纯文风无剧透脱敏蒸馏、多书混搭与第 0–4 层文风验收闭环。
---

# novel-refpack · 长篇参考包与文风蒸馏工具

> **⚠️ Agent 执行前必做（第一步：主动确认产出规模 / KB）**
>
> 在启动任何蒸馏、索引打包或生成参考包任务前，**必须先主动询问用户期望的产出规模与文件大小（KB / Token 档位）**，不要直接默认跑完再让用户重打包。请直接给出以下选项供用户选择：
> - **`compact`**（`~60 KB` / `~1.6 万 tokens`）：32k 窗口或网页聊天框轻量投喂
> - **`standard`**（`~150 KB` / `~4 万 tokens`，**默认**）：64k–128k 主力写作窗口
> - **`rich`**（`~300 KB` / `~8 万 tokens`）：200k 长窗口高细节创作
> - **`full`**（全量不裁剪）：1M 超长窗口或本地检索
> - **自定义大小**：`--kb <数字>`（例如 `--kb 80` 或 `--kb 200`）或 `--max-tokens <数字>`
>
> 说明：`12_run_all.py` 与 `13_build_pack.py` 在交互式终端未指定预算参数时也会主动提问；在自动化/非交互调用时，请根据用户确认的结果显式传入 `--preset` / `--kb`（或加 `--yes` 使用配置默认值）。

---

## 核心能力与模式

1. **同人 / IF 线完整参考包（默认）**：产出 `整书总结.md`（锁事实与角色快照）+ `例子.txt`（锁文风细节、搭配表与目标书高频特征词）+ 合并单文件 `参考包.md`（默认 `standard` 档 150KB ≈ 4 万 tokens，例子占 70% : 摘要占 30%）。支持 `13_build_pack.py --emit-both` 一次同时输出合并包与独立例子集。
2. **纯文风灵活蒸馏（`--style-only --anonymize`）**：无需调大模型跑章节摘要，纯本地秒级提取叙述节奏、连续动作链、五感环境细节、对白呼吸感、**目标书高频特征词表**、搭配雷区与零频黑名单；支持 `anonymize_style=neutral`（某甲/某乙）或 `names`（自然假名）、`anonymize_terms`（地名/专名脱敏）与 `single_char_names`（单字人名安全脱敏），直接用于全新原创小说。
3. **目标书高频词驱动写作（Vocab-Aligned Writing）**：`07_stylefit_index.py` 与 `09_build_examples.py` 自动从目标书统计并内嵌 **高频特征词表**（`index.json["高频词"]`，直接写入 `例子.txt` / `纯文风包.md`），并支持 `08_stylefit_query.py --top-words` 与 `07b_discover_style.py` 零配置探索，让写作模型直接对齐原书真实高频词汇，而非凭空猜测。
4. **多书文风混搭（`scripts/13b_blend_style.py`）**：按维度（叙述骨架 / 动作细节 / 对白节奏）自动合成多部作品的纯文风参考包。
5. **群聊 / 贴吧人设蒸馏（`scripts/chat_run.py`）**：从贴吧或 QQ 群记录逆向蒸馏高拟真 System Prompt。

---

## 常用命令速查

```bash
# 0. 快速准备配置（按题材选 stylefit_dir: general / modern / fantasy / tieba）
python scripts/06b_suggest_entities.py                    # 自动扫描候选人名与专名，辅助填 names / anonymize_terms
python scripts/07b_discover_style.py                      # 零配置自动发现目标书高频词、特征动词、连接词与句式特征

# 1. 纯文风蒸馏（免 API，支持 EPUB / DOCX / TXT / SRT / ASS / Galgame 剧本）
python scripts/12_run_all.py --style-only --anonymize --preset standard --yes
python scripts/12_run_all.py --style-only --anonymize --kb 120 --prewarm-verify --yes

# 2. 完整流水线（含分片纪要、卷纪要、例子集、整书总结与合并参考包）
python scripts/12_run_all.py --preset standard --ratio 0.70 --yes
python scripts/12_run_all.py --kb 200 --ratio 0.75 --yes

# 3. 单独按不同容量 / 脱敏风格重打包（秒级完成，不重跑模型）
python scripts/13_build_pack.py --preset compact
python scripts/13_build_pack.py --kb 150 --ratio 0.75 --emit-both --anonymize-style names
python scripts/13b_blend_style.py --narr packA.md --dialogue packB.md --out work/out/混搭文风包.md

# 4. 写前查高频词、搭配与导出提示卡
python scripts/08_stylefit_query.py --top-words           # 查看目标书高频特征词表
python scripts/08_stylefit_query.py --colloc              # 查搭配表与 0 次雷区
python scripts/08_stylefit_query.py --export-card card.md # 导出精简场景/风格提示卡
```

---

## Agent 迭代改稿标准闭环

当用户要求「按某本书文风写一章」或「把这段稿子改得更像原作 / 去掉 AI 味」时，严格按以下闭环执行：

1. **首轮验收与诊断**：
   ```bash
   # 同题材续写 / IF 线
   python scripts/11_verify.py --text v1.md --ref-pattern '(场景关键词)' --guide --json report_v1.json --top-z 15
   # 跨题材纯文风仿写（如用名著文风写现代题材）
   python scripts/11_verify.py --text v1.md --cross-domain --domain-terms '新题材专词1,新题材专词2' --pov third --guide --json report_v1.json
   ```
2. **清理第 0 层卫生问题（优先级最高，必须归零）**：
   - 清除乱码 / 非目标文字字符；
   - 替换命中的**零频词**与**低频错配搭配**（直接采纳 `--guide` 给出的原书高频平替搭配）；
   - 替换由目标语料拟合出的 AI 高发探针词；
   - **照抄例句粘贴必须归零**（严禁直接复制 `例子.txt` 原句段落）。
3. **清理句式与结构型 AI 腔**：
   - 对照 [`config/bans.md`](config/bans.md) 六大结构型雷区（连续否定排比、否定式反差、对白情绪标签、慢镜头生理微动作过载、破折号滥用与分行摆拍、英文机翻腔）逐段去油；
   - 核对目标书**高频特征词表**（`--top-words`）与标点密度，把漂移的现代/机翻措辞拉回目标书语域。
4. **精准修复 Top-N 高 `z` 句**：
   - 查看 `--top-z` 报告中 `z` 值最异常的句子及其句内 **0 频片段**；
   - **区分两类 0 频片段**：属于新题材必然出现的合理专名/设定词（通过 `--domain-terms` 豁免）保留；属于语域串台的俗词、翻译腔或生造搭配立即改写。
5. **版本对比与可视化复检**：
   ```bash
   python scripts/11_verify.py --diff v1.md v2.md --html work/out/verify_report.html
   ```
   确认第 0 层清零、结构与虚词骨架贴合、`z` 与 0 频探针收敛达标后交付最终稿件。

文风拟合底层原理、八种 AI 违和形态与第 0–4 层验收详解见 [`stylefit/SKILL.md`](stylefit/SKILL.md)，完整模式、流水线与避坑边界见 [`docs/MODES.md`](docs/MODES.md)、[`docs/WORKFLOW.md`](docs/WORKFLOW.md)、[`docs/CONFIG.md`](docs/CONFIG.md) 与 [`docs/PITFALLS.md`](docs/PITFALLS.md)。
