# AGENTS.md · `novel-refpack` AI 协作入口

> 本文件保持极薄。开始读代码或改代码前，**只需先通读一份自包含全局地图：[REPO_MAP.md](REPO_MAP.md)**（内含任务路由、数据流契约、全仓路径索引与隐性约束），不要盲目全仓扫描。

## 硬红线（不可破坏）
1. **纯标准库零新增依赖**：全部核心代码仅用 Python 3.9+ 标准库（仅 `scripts/00_extract.py` 的 `lxml` 与 `scripts/chat_fetch_tieba.py` 的 `aiotieba` 允许局部可选导入）。
2. **语料拟合原则**：反 AI 腔词级检测、搭配雷区、异常脚本告警与零频黑名单必须先查目标语料频次拟合，禁止拍脑袋一刀切主观清单。
3. **向后兼容与默认产物**：保持现有 `config/project.json`、`config/stylefit/` 与 `scripts/NN_*.py` 兼容；默认输出继续为单文件打包（`参考包.md` / `纯文风包.md`），`--wiki` 仅为面向本地 Coding Agent 写作的独立可选模式。
4. **主动询问产出规模**：给用户蒸馏/打包前，主动询问目标文件大小（`compact ~60KB` / `standard ~150KB` / `rich ~300KB` / `full` / 自定义 `--kb N`）；CLI 交互提示必须在非 TTY 与 `--yes` 下静默跳过。
5. **不提交私有资产**：严禁提交私有书单配置（`config/project.json`、`config/bans_*.md`、`config/stylefit_<私书>/`、`work*`）。

## 改动后唯一自检门禁
```bash
# 快速校验（路径索引覆盖 + 公开 JSON/正则 + 纯标准库合规）
python -X utf8 scripts/repo_check.py --check

# 全检门禁（以上全部 + 全套单元测试）
python -X utf8 scripts/repo_check.py --full

# 抽单文件符号与 CLI 骨架，方便同步更新 REPO_MAP.md
python -X utf8 scripts/repo_check.py --skeleton <相对路径.py>
```
