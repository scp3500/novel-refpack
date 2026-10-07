#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6 · 台词归属：从原文抽出「谁说了哪句」，产出 attrib.json。

  python scripts/06_build_attrib.py
  python scripts/06_build_attrib.py --sample 50      # 抽 50 条给人/模型复核

策略是「宁可少收，不要错收」——三条规则都要求句中只有一个候选主语：
  A 台词同行后置叙述（「…」他说。）/ 下一行紧贴的叙述
  B 上一非空行以「：」结尾且只有一个名字
  C 上一非空行含说话动词且只有一个名字

命中多义（一句里两个名字）一律丢弃。归属准确率直接决定语音档案的可信度，
所以自动抓完最好再抽 5% 用模型核一遍。
"""
import os
import re
import sys
import glob
import json
import random
import argparse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio, corpus as C      # noqa: E402

VERBS = ("说", "道", "问", "答", "喊", "叫", "吼", "嘟囔", "低语", "回答", "解释",
         "询问", "回应", "开口", "补充", "叮咛", "提醒", "警告", "宣布", "喃喃", "呢喃",
         "说道", "问道", "答道", "笑道", "叹气", "点头", "摇头", "皱眉", "嘀咕")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--names", default=None, help="覆盖 config 里的角色名，逗号分隔")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sample", type=int, default=0, help="抽 N 条供人工/模型复核")
    a = ap.parse_args()

    cfg = project.load(a.config)
    names = [x.strip() for x in (a.names or ",".join(cfg.get("names") or [])).split(",") if x.strip()]
    if not names:
        raise SystemExit("config 里没有 names（角色名列表），自动抓归属需要它")
    names = sorted(set(names), key=len, reverse=True)
    NAME_RE = re.compile("|".join(re.escape(n) for n in names))
    VERB_RE = re.compile("|".join(VERBS))
    SUBJ_RE = re.compile("(" + "|".join(re.escape(n) for n in names) +
                         r")[^，。！？、：:\n]{0,6}?(?:" + "|".join(VERBS) + ")")

    def names_in(s):
        return list(dict.fromkeys(NAME_RE.findall(s)))

    def subject_of(s):
        got = list(dict.fromkeys(SUBJ_RE.findall(s)))
        return got[0] if len(got) == 1 else None

    pairs = []
    files = sorted(glob.glob(os.path.join(cfg["paths"]["chunks"], "chunk_*.txt")),
                   key=textio.natural_key)
    if not files:
        files = [os.path.join(cfg["paths"]["raw"], "_all.txt")]
    for f in files:
        lines = textio.read_text(f).split("\n")
        n = len(lines)
        for i, ln in enumerate(lines):
            qs = C.QUOTE.findall(ln)
            if not qs:
                continue
            who = None
            tail = ln[ln.rfind("」") + 1:] if "」" in ln else ""
            if tail.strip():
                who = subject_of(tail)
            if who is None and i + 1 < n:
                who = subject_of(lines[i + 1].strip())
            if who is None:
                j = i - 1
                while j >= 0 and not lines[j].strip():
                    j -= 1
                if j >= 0:
                    pv = lines[j].strip()
                    if pv.endswith(("：", ":")) or VERB_RE.search(pv):
                        who = subject_of(pv)
                        if who is None:
                            nm = names_in(pv)
                            if len(nm) == 1 and pv.endswith(("：", ":")):
                                who = nm[0]
            if not who:
                continue
            for q in qs:
                q = q.strip()
                if len(q) >= 2:
                    pairs.append({"who": who, "text": q})

    out = a.out or project.artifact(cfg, "attrib.json")
    textio.write_json(out, pairs)
    c = Counter(p["who"] for p in pairs)
    print("归属：%d 条 ｜ 说话人 %d 个" % (len(pairs), len(c)))
    print(" | ".join("%s:%d" % k for k in c.most_common(25)))
    print("→ %s" % out)

    if a.sample:
        random.Random(7).shuffle(pairs)
        sp = pairs[:a.sample]
        spf = os.path.join(cfg["paths"]["notes"], "attrib_sample.md")
        textio.write_text(spf, "\n".join("- [%s] %s" % (p["who"], p["text"]) for p in sp) + "\n")
        print("抽 %d 条复核稿 → %s（改错的直接改 who）" % (len(sp), spf))

    print("下一步：python scripts/07_stylefit_index.py")


if __name__ == "__main__":
    main()
