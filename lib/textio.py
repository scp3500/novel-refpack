# -*- coding: utf-8 -*-
"""文本读写与结构解析。全部标准库，无依赖。"""
import os
import re
import json

ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1")

HEAD = re.compile(r"^(#{1,6})\s+(.*)$")


def read_text(path):
    """按常见编码依次尝试，最后兜底 utf-8 + ignore。"""
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def write_text(path, s):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def parse_units(text):
    """把带 `# / ## / ###` 标记的全文切成「叶级单元」列表。

    一个单元 = 一个 h2 或 h3 标题 + 它后面的正文行，直到下一个 h2/h3 或 h1。
    返回 [{level, h1, h2, title, lines}]，顺序与原文一致。
    """
    units = []
    cur_h1, cur_h2 = "", ""
    cur = None
    for ln in text.split("\n"):
        m = HEAD.match(ln)
        if m:
            lvl, title = len(m.group(1)), m.group(2).strip()
            if lvl == 1:
                cur_h1, cur_h2 = title, ""
                if cur is not None:
                    units.append(cur)
                    cur = None
                continue
            if lvl == 2:
                cur_h2 = title
            if lvl in (2, 3):
                if cur is not None:
                    units.append(cur)
                cur = {"level": lvl, "h1": cur_h1, "h2": cur_h2,
                       "title": title, "lines": [ln]}
                continue
            # 更深层级：并入当前单元
            if cur is not None:
                cur["lines"].append(ln)
            continue
        if cur is None:
            cur = {"level": 3, "h1": cur_h1, "h2": cur_h2,
                   "title": "(前言)", "lines": []}
        cur["lines"].append(ln)
    if cur is not None:
        units.append(cur)
    return units


# 纯话名罗列行：「第三话 标题」「第12章：归乡」「3. 第三话 标题」。
# 话名后面必须是分隔符或行尾（「第一回合林舟就倒下了」不算），
# 标题部分不能带句读（带「，。；！？」的是剧情句，不是话名）。
TITLE_LINE = re.compile(
    r"\s*(?:\d{1,3}[.、)）]\s*)?"
    r"第[0-9０-９零〇一二三四五六七八九十百千两]+[话章节卷回]"
    r"(?:[\s　:：·・\-—]+[^，,。；;！!？?…\n]{0,30})?\s*")


def clean_note_text(s):
    """清洗摘要里的取材口吻与内部编号（生成成品前跑一遍）。

    只删「确定是话名」的行。「1. 林舟打败了狼王」这种编号剧情短句一律保留：
    卷纪要的剧情纪要就是这种格式，删了等于把下篇的剧情删光。
    """
    out = []
    for ln in s.split("\n"):
        t = ln.rstrip()
        # 形如 "(chunk_12)" / "(分片 12)" / "见 chunk_12" 的内部编号
        t = re.sub(r"[（(]\s*(chunk|分片|片)\s*_?\s*\d+[^）)]*[）)]", "", t)
        t = re.sub(r"(见|来自|出自)\s*(chunk|分片)_?\s*\d+", "", t)
        if TITLE_LINE.fullmatch(t):
            continue
        out.append(t)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
