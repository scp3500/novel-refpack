# 高阶创作模式与提示词指南

本项目支持五种工作模式：同人/IF 合并参考包、纯文风脱敏原创、多文风混搭、反 AI 腔与验收改稿闭环，以及群聊/贴吧人设蒸馏。

> **生成前先定规模（Agent 与交互终端通用约定）**
>
> 在执行蒸馏或打包前，AI 助手应**主动询问用户目标产出体积与档位**：
> - `compact`（`~60 KB` / `~1.6 万 tokens`）
> - `standard`（`~150 KB` / `~4 万 tokens`，默认）
> - `rich`（`~300 KB` / `~8 万 tokens`）
> - `full`（全量不裁剪）
> - 或自定义 `--kb <数字>`
>
> 直接在交互终端运行 `12_run_all.py` 或 `13_build_pack.py` 且未显式指定 `--preset` / `--kb` / `--max-tokens` 时，脚本也会主动弹窗/提问确认预算（批量自动化可加 `--yes` 跳过）。

---

## 模式 1 · 同人与 IF 线完整参考包（默认）

### 一键命令
```bash
python scripts/13_build_pack.py --preset standard --ratio 0.70
# 需要同时保留合并参考包 + 独立例子集时，加 --emit-both（可配合 --examples-out）
python scripts/13_build_pack.py --preset standard --ratio 0.70 --emit-both --examples-out work/out/例子.txt
```

产出 `work/out/参考包.md`（默认总计 ~150 KB / ~4 万 tokens，**70% 文风例子 + 30% 整书总结**）：
- **上半部（锁事实）**：`〇 续写/IF 速查区`（硬设定、结局现状、卷末状态卡、分歧点）+ `上篇 总览` + `下篇 分卷脉络`（超预算时优先保全开篇与最后 2 卷状态快照）；
- **下半部（锁文风与高频词）**：紧贴用户写作指令，放置高密度叙述腔、连续动作白描、五感细节、对白呼吸感、角色语音档案、**目标书高频特征词表**、搭配雷区与零频黑名单。

---

## 模式 2 · 纯文风抽取与原创写作（`--style-only --anonymize`）

### 适用场景
写一个全新的原创世界观与新主角，只想借用某位成熟作家的叙述腔调、动作节奏、高频用词底色、环境细节与对白张力，**绝不想带入原书剧情、副本设定或角色名**。

### 一键命令（免 API、秒级出稿）
```bash
# 先按题材选好 config/project.json 的 stylefit_dir（general / modern / fantasy / tieba）
python scripts/12_run_all.py --style-only --anonymize --preset standard --yes
# 或自定义大小，如 80KB（约 2.1 万 tokens），并切换自然假名脱敏
python scripts/13_build_pack.py --style-only --anonymize --anonymize-style names --kb 80
```

### 做了哪些隔离与对齐处理
1. 跳过分片摘要、卷纪要与整书总结；
2. 剔除分剧本语料、名场面台词、原书章节标题与角色关系卡；
3. 台词改按**话语功能桶**（命令禁止、让步接受、反问逼问、抱怨吐槽、慌乱结巴等）展示句法与句尾口癖；
4. **精细脱敏**：支持 `anonymize_style=neutral`（`某甲/某乙/某丙`）或 `names`（自然假名如 `林远/苏晴/陈默`），配合 `anonymize_terms`（地名/组织/专名替换）与 `single_char_names`（单字人名安全脱敏），`【条目框】` 自动替换为「某技能/条目」；
5. **内嵌目标书高频特征词表**：`07_stylefit_index.py` 与 `09_build_examples.py` 自动从原书提取并嵌入高频特征实词、动词与连接/副词（`index.json["高频词"]`），写前也可用 `08_stylefit_query.py --top-words` 或 `07b_discover_style.py` 直接检视，让写作模型直接对齐原书高频词汇而非凭空脑补；
6. 篇幅集中分配给**细粒度笔法与镜头细节**（连续动作白描、五感与光影切镜、对话穿插神态锚点、转场留白）、叙述句长阶梯与搭配雷区，减少 AI 复读同一类描写。

---

## 模式 3 · 多文风混搭（跨书融合）

支持用 **`scripts/13b_blend_style.py`** 自动按维度合成两部或多部作品的纯文风包，也可手工截取拼接：

```bash
# 1. 先分别对作品 A、B 生成脱敏纯文风包
python scripts/12_run_all.py --config config/bookA.json --style-only --anonymize --kb 80 --yes
python scripts/12_run_all.py --config config/bookB.json --style-only --anonymize --kb 80 --yes

# 2. 按维度自动混搭（例如：叙述与动作取 A，对白与口癖取 B）
python scripts/13b_blend_style.py --narr workA/out/纯文风包.md --dialogue workB/out/纯文风包.md --out work/out/混搭纯文风包.md
```

- **叙述骨架与动作推进（取作品 A）**：截取 A 的「叙述腔」「高频特征词」「细粒度笔法与镜头细节（连续动作/五感）」；
- **对白节奏与吐槽口癖（取作品 B）**：截取 B 的「对白回合片段」「语体与台词功能范例」；
- **冲突约束**：明确要求「无论对白多么轻松跳脱，旁白叙述必须保持作品 A 的冷硬克制节奏」。

---

## 模式 4 · 反 AI 腔与 Agent 迭代改稿闭环

### 1. 双层负向约束（结构禁区 + 语料拟合词表）
- **结构/修辞禁区（跨题材通用）**：来自 [`config/bans.md`](../config/bans.md)，涵盖公文过渡、辩证套话、悬空神态，以及实战高发的**六大结构型 AI 腔**（连续否定排比、否定式反差描写、对白情绪标签与停顿套路、慢镜头感官/生理微动作过载、破折号滥用与分行摆拍、英文机翻腔）。
- **词级与搭配雷区（必须按目标书拟合）**：直接取用 `例子.txt` / `纯文风包.md` 底部由 `index.json` 自动统计出的「搭配表 · 典型 vs 雷区」「零频黑名单」与「目标书高频特征词表」，切忌脱离原书盲目写死词表。

### 2. Agent 迭代改稿标准闭环
推荐让写作 Agent 按以下五步循环打磨稿件：

```bash
# 第一步：跑验收与改稿向导（跨题材仿写加 --cross-domain 与 --domain-terms）
python scripts/11_verify.py --text v1.md --guide --json work/out/v1.json --top-z 15
# 跨题材示例：
python scripts/11_verify.py --text v1.md --cross-domain --domain-terms '咖啡,地铁,手机' --pov third --guide --json work/out/v1.json
```

1. **清理第 0 层卫生问题（必须清零）**：修复乱码/非目标文字、替换命中的零频词与低频错配搭配（直接采用 `--guide` 推荐的目标书高频平替）、替换语料拟合出的 AI 高发探针词，并确保**照抄例句粘贴 == 0**。
2. **清理句式型 AI 腔**：按 `config/bans.md` 六大结构套路逐段修剪否定排比、情绪注脚、生理微动作堆砌、滥用破折号与机翻语序。
3. **对齐目标书高频词**：对照 `08_stylefit_query.py --top-words` 替换生硬或串台的动词/连接词。
4. **逐句排查 Top-N 高 `z` 句**：查看 `--top-z` 标出的句内 0 频片段——属于新题材合理专名的加入 `--domain-terms`；属于语域串台俗词、翻译腔或生造搭配的就地重写。
5. **版本对比与可视化复检**：
   ```bash
   python scripts/11_verify.py --diff v1.md v2.md --html work/out/verify_report.html
   ```

### 3. 开箱即用负面约束模板
```markdown
【反 AI 腔负面约束 Negative Constraints】
1. 禁用六大结构型 AI 腔：严禁连续 ≥3 个「没有/不是/不再」排比；严禁「没有提高声音，反而……」「脸上没有愤怒，只有……」式否定反差；严禁「停了一拍」「声音平平的」「语气没有半点起伏」等情绪注脚；严禁密集堆砌「指尖发凉/冷汗贴背/背脊僵硬/心跳漏拍」；非打断语境严禁高频「——」插入与单行摆拍；严禁英文机翻腔。
2. 禁用公文辩证句型：严禁「不仅……更是……」「与其说……不如说……」「不是……而是……」，直接陈述事实与动作。
3. 严禁强行升华：动作或对话结束即收尾，禁止章节末段添加总结性、哲理性抒情旁白。
4. 词表服从目标书统计：优先使用参考包中的「目标书高频特征词表」与高频搭配，严禁踩中零频黑名单或原样粘贴例句。
```

---

## 模式 5 · 群聊与贴吧人设蒸馏（Chat Mode）

```bash
# 在线抓取贴吧热门帖并蒸馏（需 pip install aiotieba）
python scripts/chat_run.py --tieba 弱智吧 --no-llm

# 从本地导出 JSON / QQ 聊天记录蒸馏（支持自定义 work_dir）
python scripts/chat_run.py --config config/chat.json
```

工具会自动统计消息字数分位数（P50/P80/P95）、每千字句号率与空格断句习惯、高频句首发语词与行为交互逻辑，并按实测句号频率动态生成标点规则。
