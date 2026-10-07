#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性假模型：读提示词，按模板写摘要 / 卷纪要 / 元章节。

不调任何网络接口，输出只取决于提示词内容。给 command 后端做冒烟：

  python tests/fake_llm.py --prompt {prompt_file} --out {out_file}
"""
import argparse
import os
import re
import sys

TAG = re.compile(r"【尾记[^】]{1,40}】")
CHUNK = re.compile(r"<<<CHUNK\n(.*)\nCHUNK", re.S)
NOTES = re.compile(r"<<<NOTES\n(.*)\nNOTES", re.S)
MATERIAL = re.compile(r"<<<MATERIAL\n(.*)\nMATERIAL", re.S)
RANGE = re.compile(r"范围：(.+)")
LABEL = re.compile(r"合并成【(.+?)】")

PAD = (
    "补充说明：以上条目均从本任务材料里抽出，人名地名不改写。"
    "北境的风、客栈的灯、泥路上的车辙只作场景锚点，不另造设定。"
    "文风样本保持原文用词，不润色，不扩写。"
)


def _read(path):
    if not path:
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    text = text.strip() + "\n"
    if path:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    sys.stdout.write(text)


def _tags(s):
    return list(dict.fromkeys(TAG.findall(s or "")))


def _tail_words(s, n=12):
    lines = [ln.strip() for ln in (s or "").split("\n") if len(ln.strip()) > 8]
    words = []
    for ln in lines[-8:]:
        words += re.findall(r"[\u4e00-\u9fff]{2,4}", ln)
    return list(dict.fromkeys(words))[:n]


def stage1(prompt):
    body = (CHUNK.search(prompt) or type("M", (), {"group": lambda *_: ""})()).group(1)
    rng = (RANGE.search(prompt) or type("M", (), {"group": lambda *_: "未知"})()).group(1).strip()
    tags = _tags(body) or _tags(prompt)
    keys = _tail_words(body)
    samples = [ln.strip() for ln in body.split("\n") if "“" in ln or "「" in ln][:4]
    if not samples:
        samples = [ln.strip() for ln in body.split("\n") if len(ln.strip()) > 10][:3]
    plot = keys[:8] or ["林舟", "苏晚", "北境"]
    lines = [
        "- 章节范围：%s" % rng,
        "- 叙述人称与视角：第三人称，视点跟林舟",
        "- 时间线锚点：按材料顺序，标记 %s" % ("、".join(tags) or "无"),
        "- 主要剧情：",
    ]
    for i, w in enumerate(plot, 1):
        lines.append("  %d. %s相关事件发生，现场留下线索。" % (i, w))
    if tags:
        lines.append("  %d. 本片读到片尾标记 %s。" % (len(plot) + 1, tags[-1]))
    lines += [
        "- 出场角色与关系变化：林舟、苏晚、陈衡同行，关系无突变",
        "- 设定 / 术语 / 地理 / 组织：北境、客栈、泥路；片尾词：%s" % "、".join(keys[:8]),
        "- 类型桥段：日常为主，穿插行路",
        "- 伏笔与线索：%s" % ("、".join(tags) or "无"),
        "- 原文文风样本：",
    ]
    for s in samples:
        lines.append("  - （对白/叙述）%s" % s[:80])
    lines += ["- 基调一句话：赶路、停住、再出发。", "", PAD]
    return "\n".join(lines)


def stage2(prompt):
    notes = (NOTES.search(prompt) or type("M", (), {"group": lambda *_: ""})()).group(1)
    label = (LABEL.search(prompt) or type("M", (), {"group": lambda *_: "本卷"})()).group(1)
    tags = _tags(notes) or _tags(prompt)
    keys = _tail_words(notes)
    quote = ""
    m = re.search(r"[“「]([^”」]{4,40})[”」]", notes)
    if m:
        quote = m.group(1)
    tag_s = "、".join(tags) if tags else "（无尾记）"
    lines = [
        "# %s" % label,
        "",
        "## 一、范围与时间锚",
        "材料范围：%s。尾记：%s。" % (label, tag_s),
        "",
        "## 二、剧情纪要",
        "1. 林舟离开村子。",
        "2. 苏晚跟上队伍，陈衡在后面喊人。",
        "3. 一行人在北境停住脚步，推开门坐下。",
        "第一回合林舟就倒下了，众人把他扶起来继续走。",
        "4. 本卷关键线索：%s。" % "、".join(keys[:6] or ["赶路"]),
    ]
    if tags:
        lines.append("5. 读到卷末标记 %s。" % tags[-1])
    lines += [
        "第三话 过河",  # 话名行，成品清洗应删掉；编号剧情短句必须保留
        "",
        "## 三、本篇末角色状态快照",
        "- 林舟：在路上 / 仍持刀 / 心态稳住。截至 %s。" % tag_s,
        "- 苏晚：同行 / 负责打水与问话。",
        "- 陈衡：殿后喊人。",
        "",
        "## 四、登场人物（新登场请标注）",
        "- 林舟、苏晚、陈衡",
        "",
        "## 五、设定 / 地点 / 组织 / 术语",
        "- 北境：主舞台。客栈、泥路、巷口灯火。",
        "- 术语：尾记标记 %s 用于核对覆盖。" % tag_s,
        "",
        "## 六、名场面与关键台词",
        "- “%s”（本卷）" % (quote or "我们走吧"),
        "",
        "## 七、伏笔与回收",
        "- 未回收：%s 之后的路还没走完。" % (tags[-1] if tags else "本卷"),
        "",
        "## 八、基调一句话",
        "赶路比说话多。",
        "",
        PAD,
    ]
    return "\n".join(lines)


def meta(prompt):
    mat = (MATERIAL.search(prompt) or type("M", (), {"group": lambda *_: ""})()).group(1)
    tags = _tags(mat) or _tags(prompt)
    title = "元章节"
    if "结局" in prompt:
        title = "结局现状"
    elif "世界" in prompt:
        title = "世界观与核心设定"
    elif "角色" in prompt:
        title = "主要角色档案"
    elif "势力" in prompt:
        title = "势力阵营"
    elif "伏笔" in prompt:
        title = "伏笔与回收"
    elif "定位" in prompt:
        title = "作品定位与核心看点"
    lines = [
        "## %s" % title,
        "- 材料字数：%d。尾记数：%d。" % (len(mat), len(tags)),
        "- 尾记清单：%s" % ("、".join(tags[-8:]) if tags else "无"),
        "- 林舟、苏晚、陈衡仍在北境赶路，客栈灯火未灭。",
        "- 设定：北境没有系统面板；术语词典：尾记、客栈、泥路。",
        "- 伏笔：最后的标记必须能在材料里找到，不能写丢结局。",
        "- 分歧：苏晚是否跟上北上的队伍。",
        "- 角色线：三人同行。",
        "",
        PAD, PAD,
    ]
    if tags:
        lines.append("此刻锚点：%s。" % tags[-1])
    return "\n".join(lines)


def render(prompt):
    if "<<<CHUNK" in prompt:
        return stage1(prompt)
    if "<<<NOTES" in prompt:
        return stage2(prompt)
    if "<<<MATERIAL" in prompt:
        return meta(prompt)
    return "未能识别任务类型。\n" + PAD + "\n" + PAD


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    prompt = _read(a.prompt)
    _write(a.out, render(prompt))


if __name__ == "__main__":
    main()
