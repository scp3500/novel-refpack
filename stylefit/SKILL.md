---
name: style-fit
description: 从一部长篇语料（小说 / 剧本 / 任何成篇文本）里拟合出它的文风，然后按这个文风写作并验收。用在「仿写某本书」「写出某某的风格」「稿子有 AI 味要改」「给写作助手加风格约束」这类任务上。核心是：不用人工标注、不用盲测，全部从语料自身拟合。
---

# style-fit · 从语料拟合文风，按它写，再验收

## 三条底层判断

### 1 · 边际统计测不出「像不像」，只能当筛子
句长、对白占比、段长、标点率这些段级聚合量，对「把段落打乱」完全免疫（实测 AUC 恰好 **0.500**）。只能判尺寸在不在范围内，不能判语感对不对。

### 2 · 唯一有效的验证负样本是「内容保留打散」
把语料里真实的段落原样打乱顺序再拼回去——同词、同句、同长度，只有顺序变了。相邻段实词重合（`jacCt`）在真书上是打乱样本的 **2–3 倍**（AUC **0.79**）。

### 3 · 搭配比词更致命
写手「造词」比「造搭配」少得多，常见错误是每个词都认识但配错了动词或方位：
```
"帽檐下"   → 写成「帽子外面」     （0 次）
"趴下"     → 写成「趴这儿」       （0 次）
"一摸脑袋" → 写成「摸了摸脑袋」   （0 次）
"推开"     → 写成「一把推开」     （0 次）
```
所以最高杠杆的一层工具是「搭配表」，其次才是「词表」。

## 工作流

### 第一步 · 建索引
```bash
python stylefit/build_index.py --corpus work/chunks --out work/cache/mybook \
    [--attrib work/attrib.json] [--names 主角,配角甲,配角乙] [--config config/stylefit]
```

### 第二步 · 写之前查
```bash
python stylefit/query.py --index work/cache/mybook/index.json --colloc        # 全部搭配概念
python stylefit/query.py --index ... --colloc 视线                            # 0 的那项就是雷区
python stylefit/query.py --index ... --who 主角 --func 让步接受               # 这个人在这种处境怎么说话
python stylefit/query.py --index ... --why 沉默                              # 这个意图书里怎么写
python stylefit/query.py --index ... --scene 战斗                            # 同类场景的真实片段
python stylefit/query.py --index ... --dict 战斗                             # 这类场景实际用的词
python stylefit/query.py --index ... --words                                 # 用词表 + 零频黑名单
python stylefit/query.py --index ... --stats                                 # 统计靶
```

### 第三步 · 写作规矩与八种违和形态自查
1. 一句只写一个具体动作，方位克制不堆砌
2. 空间距离写感官后果，不机械列数字
3. 环境只做背景或物理交互，不为情绪强行编排光影
4. 同一个比喻全篇只用一次
5. 物件出场要有来源、消失要有去处
6. **摘抄连主语**：从原文参考句式时必须连施动主语一起对齐（例如原句「某甲一边擦汗，一边将钥匙轻轻放在桌角」，若只抄后半截写成「那串钥匙轻轻放在桌角」，物件就会失去施动者自己动起来）
7. 不用总结性连接词（「接着…然后…」「总而言之」）封口
8. 写完跑一遍 `verify.py`，0 频探针倍数 > 1.3 就回去改

### 第四步 · 四层验收
```bash
python stylefit/verify.py --text 稿.txt --corpus work/chunks --out work/cache/mybook \
    --ref-pattern '(战斗|挥剑|格挡)'
```
- **门槛层**：段级边际统计落在同类参考段区间内
- **结构层**：自打乱比值接近同类书段中位
- **逐句层**：字符 4-gram 条件归一化 `z` 均值落在 `±0.3` 附近
- **0 频探针**：新造 4-gram 倍数 `≤ 1.05`
