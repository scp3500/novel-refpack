---
name: style-fit
description: 从一部长篇语料（小说 / 剧本 / 字幕 / 任何成篇文本）里拟合出它的文风、高频特征词表、搭配与零频雷区，然后按这个文风写作并跑第 0–4 层量化验收闭环。用在「仿写某本书」「写出某某的风格」「稿子有 AI 味要改」「给写作助手加风格约束」这类任务上。核心是：不用人工标注、不用盲测，全部从语料自身拟合。
---

# style-fit · 从语料拟合文风，按它写，再验收

## 四条底层判断

### 1 · 边际统计测不出「像不像」，只能当筛子
句长、对白占比、段长、标点率这些段级聚合量，对「把段落打乱」完全免疫（实测 AUC 恰好 **0.500**）。只能判尺寸在不在范围内，不能判语感对不对。

### 2 · 唯一有效的验证负样本是「内容保留打散」
把语料里真实的段落原样打乱顺序再拼回去——同词、同句、同长度，只有顺序变了。相邻段实词重合（`jacCt`）在真书上是打乱样本的 **2–3 倍**（AUC **0.79**）。

### 3 · 搭配比词更致命，但高频特征词决定底色
写手「造词」比「造搭配」少得多，常见错误是每个词都认识但配错了动词或方位：
```
"帽檐下"   → 写成「帽子外面」     （0 次）
"趴下"     → 写成「趴这儿」       （0 次）
"一摸脑袋" → 写成「摸了摸脑袋」   （0 次）
"推开"     → 写成「一把推开」     （0 次）
```
同时，每本书有自己稳定的**高频特征词表**（`index.json["高频词"]`，含高区分度实词、动词、连接/副词、虚词骨架）。建索引时会自动抽取并嵌入 `例子.txt` / `纯文风包.md`，写作模型应直接对齐这些真实高频词，配合搭配表避开 0 次雷区。

### 4 · 同题材续写与跨题材仿写适用不同验收判据
- **同题材续写 / IF 线**：词表与原作重合，要求字符 4-gram `z ∈ ±0.3`、0 频探针倍数 `≤ 1.05`。
- **跨题材纯文风仿写**（如用古典/名著笔法写现代都市）：新题材专词会天然拉高生造 4-gram，必须启用 `--cross-domain --domain-terms`，重点看**第 0 层清零 + 虚词骨架相似度 + 标点密度 + 照抄粘贴 == 0 + 掩码后 `z`**。

---

## 工作流

### 第一步 · 选预设并建索引（+ 零配置发现）
支持按题材指定 `--config`（或 `project.json` 的 `stylefit_dir`）：`general`（通用文学，零奇幻偏置）、`modern`（现代都市校园恋爱）、`fantasy`（奇幻异世界系统）、`tieba`（贴吧群聊）。

```bash
# 零配置快速探测目标书高频词、特征动词与句式画像
python scripts/07b_discover_style.py

# 建立完整文风索引（自动写入 index.json["高频词"]、搭配、零频词、场景与笔法细节）
python stylefit/build_index.py --corpus work/chunks --out work/cache/mybook \
    [--attrib work/attrib.json] [--names 主角,配角甲,配角乙] [--config config/stylefit_general]
# 或走项目封装脚本
python scripts/07_stylefit_index.py
```

### 第二步 · 写之前查（高频词 + 搭配 + 场景卡）
```bash
python scripts/08_stylefit_query.py --top-words           # 目标书高频特征词表（写作对齐首选）
python scripts/08_stylefit_query.py --colloc              # 全部搭配概念与频次
python scripts/08_stylefit_query.py --colloc 视线          # 0 的那项就是雷区
python scripts/08_stylefit_query.py --who 主角 --func 让步接受  # 这个人在这种处境怎么说话
python scripts/08_stylefit_query.py --why 沉默             # 这个意图书里怎么写
python scripts/08_stylefit_query.py --scene 冲突争执       # 同类场景的真实片段
python scripts/08_stylefit_query.py --dict 冲突争执        # 这类场景实际用的词（常用/少用/禁用）
python scripts/08_stylefit_query.py --words               # 用词表 + 零频黑名单
python scripts/08_stylefit_query.py --stats               # 统计靶（句长/标点率）
python scripts/08_stylefit_query.py --export-card card.md # 导出紧凑提示卡直接喂写作模型
```

### 第三步 · 写作规矩与反 AI 腔自查
1. 一句只写一个具体动作，方位克制不堆砌
2. 空间距离写感官后果，不机械列数字
3. 环境只做背景或物理交互，不为情绪强行编排光影
4. 同一个比喻全篇只用一次
5. 物件出场要有来源、消失要有去处
6. **摘抄连主语**：化用句式时必须连施动主语一起对齐，禁止器官/物件脱离人物自行动作
7. **避开六大结构型 AI 腔**（详见 [`config/bans.md`](../config/bans.md)）：连续否定排比、否定式反差、对白情绪标签与停顿套路、慢镜头生理微动作过载、破折号滥用与分行摆拍、英文机翻腔
8. **严禁照抄例句粘贴**：例句只学句法节奏与高频词选词，绝不原样复制

### 第四步 · Agent 迭代改稿与第 0–4 层验收闭环

可先预热 4-gram 缓存（加速多次改稿复检）：
```bash
python scripts/11_verify.py --prewarm
```

**1. 跑诊断与改稿指引（`--guide` / `--json` / `--top-z`）**
```bash
# 同题材续写
python scripts/11_verify.py --text v1.md --ref-pattern '(关键词正则)' \
    --pov third --guide --top-z 15 --json work/out/v1.json

# 跨题材纯文风仿写
python scripts/11_verify.py --text v1.md --cross-domain \
    --domain-terms '咖啡,地铁,手机,项目组' --pov third --guide --top-z 15 --json work/out/v1.json
```

**2. 按优先级逐层修复**
- **第 0 层（基础排雷硬门槛，必须全部清零）**：
  - 乱码与非目标文字字符；
  - 命中的**零频词**与**低频搭配**（按 `--guide` 建议改用目标书高频替代搭配）；
  - 语料拟合出的高发 AI 探针词；
  - **照抄例句粘贴检测**（命中数必须为 `0`）。
- **结构/修辞层**：对照 `config/bans.md` 清理六大句式型 AI 腔，核对标点密度与虚词骨架。
- **Top-N 高 `z` 句精修**：逐句检查 `--top-z` 列出的句内 0 频片段——合理的新题材专名放进 `--domain-terms`，语域串台的俗词/翻译腔/生造搭配就地改写，优先向 `index.json["高频词"]` 靠拢。

**3. 迭代前后对比与 HTML 报告**
```bash
python scripts/11_verify.py --diff v1.md v2.md --html work/out/verify_report.html
```

**验收判据速览**：
- **第 0 层（基础排雷）**：乱码 `0`、照抄例句 `0`、零频词与低频错配搭配清零
- **第 1 层（门槛层）**：段级边际统计（含按 `--pov` 分桶）与标点密度落在同类参考区间内
- **第 2 层（结构层）**：自打乱比值接近同类书段中位；跨题材重点看虚词骨架相似度
- **第 3 层（逐句层）**：同题材 `z ∈ ±0.3`；跨题材关注 `--domain-terms` 掩码后的 `z` 与 Top-N 异常句收敛
- **第 4 层（0 频探针）**：同题材倍数 `≤ 1.05`（超过 `1.3` 必须返工）
