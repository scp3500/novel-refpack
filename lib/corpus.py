# -*- coding: utf-8 -*-
"""语料加载与切分。

引号体系可以配：中文直角引号「」/ 弯引号“” / 单直角『』 全支持，
默认同时认三种（`set_quotes` 可改成只认你书里用的那一种，避免误切）。
"""
import os
import re
import json
import glob

from .textio import natural_key

CHAP = re.compile(r"^\s*第[0-9零一二三四五六七八九十百千两]+[章回节话卷]\s")

QUOTE_OPEN = ["“", "「", "『"]
QUOTE_CLOSE = ["”", "」", "』"]


def set_quotes(opens=None, closes=None):
    """按书的实际引号体系重设（只认这几种，能少切错）。"""
    global QUOTE_OPEN, QUOTE_CLOSE, QUOTE, QUOTE_STRICT
    if opens:
        QUOTE_OPEN = list(opens)
    if closes:
        QUOTE_CLOSE = list(closes)
    o = "".join(re.escape(c) for c in QUOTE_OPEN)
    c = "".join(re.escape(c) for c in QUOTE_CLOSE)
    QUOTE = re.compile("[" + o + "]([^" + c + "]{0,600})[" + c + "]")
    QUOTE_STRICT = QUOTE


QUOTE = re.compile("[" + "".join(re.escape(c) for c in QUOTE_OPEN) + "]"
                   "([^" + "".join(re.escape(c) for c in QUOTE_CLOSE) + "]{0,600})"
                   "[" + "".join(re.escape(c) for c in QUOTE_CLOSE) + "]")
QUOTE_STRICT = QUOTE


def load_corpus(path):
    """path 可以是单文件、目录（递归 .txt/.md）、或逗号分隔的多个。"""
    files = []
    for p in str(path).split(","):
        p = p.strip()
        if not p:
            continue
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "**", "*.txt"), recursive=True),
                            key=natural_key)
            files += sorted(glob.glob(os.path.join(p, "**", "*.md"), recursive=True),
                            key=natural_key)
        elif os.path.isfile(p):
            files.append(p)
    texts = []
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fp:
                texts.append(fp.read())
        except Exception:
            pass
    return "\n".join(texts), files


def paragraphs(raw):
    """去章节标题、空行、分隔线。"""
    out = []
    for l in raw.split("\n"):
        s = l.strip()
        if not s or CHAP.match(s):
            continue
        if re.fullmatch(r"[-—=*~·\s　]{3,}", s):
            continue
        out.append(s)
    return out


SENT_END = re.compile(r"[^。！？…\n]*[。！？…]+|[^。！？…\n]+")


def narr_sentences(paras, min_len=5):
    """叙述句：挖掉引号后按句切，丢掉悬空分句。"""
    out = []
    for p in paras:
        rest = QUOTE.sub("", p)
        for s in SENT_END.findall(rest):
            s = re.sub(r"^[，,、：:——\s]+", "", s).strip()
            if re.search(r"[：:，,、——]$", s):
                continue
            if len(re.sub(r"\s", "", s)) >= min_len:
                out.append(s)
    return out


def load_attribution(path):
    """归属文件：`[{who,text}]` 或 `{"who": ["台词", ...]}`"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    pairs = []
    if isinstance(d, list):
        for x in d:
            if isinstance(x, dict) and x.get("who") and x.get("text"):
                pairs.append((x["who"], x["text"]))
    elif isinstance(d, dict):
        for w, v in d.items():
            if isinstance(v, list):
                for t in v:
                    if isinstance(t, str):
                        pairs.append((w, t))
    return pairs or None


VERB = (r"(?:说|道|问|答|喊|叫|吼|嘟囔|嘟哝|低语|自言自语|补充|回答|解释|抱怨|提醒|警告|"
        r"宣布|嘀咕|开口|回应|呢喃|喃喃|说道|问道|答道|笑道|叹了口气)")
VERB_RE = re.compile(VERB)


def derive_speakers(raw, names):
    """没有归属文件时的兜底：用「名字 + 说话动词 + 引号」这个高精度信号抓。

    准确率低于人工/模型校对过的归属文件，够台词类分析用。
    """
    names = sorted(set(n for n in names if n), key=len, reverse=True)
    if not names:
        return []
    alt = "|".join(re.escape(n) for n in names)
    pat = re.compile(r"(" + alt + r")[^。！？\n]{0,8}" + VERB +
                     r"[^。！？\n]{0,6}?[：:,，]?\s*"
                     r"[" + "".join(re.escape(c) for c in QUOTE_OPEN) + r"]"
                     r"([^" + "".join(re.escape(c) for c in QUOTE_CLOSE) + r"]{0,600})"
                     r"[" + "".join(re.escape(c) for c in QUOTE_CLOSE) + r"]")
    return [(m.group(1), m.group(2)) for m in pat.finditer(raw)]
