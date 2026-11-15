---
name: novel-refpack
description: 把长篇小说或群聊语料加工成轻量喂模型参考包（整书总结 + 高密度文风例子集 + 一键合并参考包），支持容量预算（KB / Tokens / 例子占比）控制、纯文风无剧透脱敏蒸馏与四层文风验收。
---

# novel-refpack · 长篇参考包与文风蒸馏工具

## 核心能力与模式

1. **同人 / IF 线完整参考包（默认）**：产出 `整书总结.md`（锁事实与角色快照）+ `例子.txt`（锁文风细节与搭配）+ 合并单文件 `参考包.md`（默认 `standard` 档 150KB ≈ 4 万 tokens，例子占 70% : 摘要占 30%）。
2. **纯文风灵活蒸馏（`--style-only --anonymize`）**：无需调大模型跑章节摘要，纯本地秒级提取叙述节奏、连续动作链、五感环境细节、对白呼吸感、搭配表与零频黑名单，自动剥离原书剧情副本并将人名脱敏为「某甲/某乙」，直接用于全新原创小说。
3. **群聊 / 贴吧人设蒸馏（`scripts/chat_run.py`）**：从贴吧或 QQ 群记录逆向蒸馏高拟真 System Prompt。

## 常用命令

```bash
# 1. 纯文风蒸馏（免 API，剥离原书剧情并脱敏人名，自定义体积与档位）
python scripts/12_run_all.py --style-only --anonymize --preset standard
python scripts/12_run_all.py --style-only --anonymize --kb 120

# 2. 完整流水线（含分片纪要、卷纪要、例子集、整书总结与合并参考包）
python scripts/12_run_all.py --preset standard --ratio 0.70
python scripts/12_run_all.py --kb 200 --ratio 0.75

# 3. 单独重新按不同容量/占比打包（无需重跑模型）
python scripts/13_build_pack.py --preset compact
python scripts/13_build_pack.py --max-tokens 60000 --ratio 0.75

# 4. 写前查搭配与写后四层验收（详见 stylefit/SKILL.md）
python scripts/08_stylefit_query.py --colloc
python scripts/11_verify.py --text draft.txt --ref-pattern '(关键词正则)'
```

文风拟合底层原理、八种 AI 违和形态与四层验收判据见 [`stylefit/SKILL.md`](stylefit/SKILL.md)，完整流水线与配置说明见 [`docs/WORKFLOW.md`](docs/WORKFLOW.md) 与 [`docs/CONFIG.md`](docs/CONFIG.md)。
