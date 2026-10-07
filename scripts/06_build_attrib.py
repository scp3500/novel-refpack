#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6 · 台词归属：从原文抽出「谁说了哪句」，产出 attrib.json。

  python scripts/06_build_attrib.py
  python scripts/06_build_attrib.py --sample 50      # 抽 50 条给人/模型复核

策略是「宁可少收，不要错收」——每条规则都要求只有一个候选主语（名字 + 说话动词），
按下面的顺序，前一条能下结论就不再往后看：
  A 同行叙述：引号外的文字（“…”他说。/ 张三道：「…」）。
    同行有叙述却认不出唯一主语（两个名字、只有代词）→ 直接丢弃，不去邻行猜。
  B 上一非空行是纯叙述（不含引号），以「：」结尾 → 取它的主语 / 唯一名字
  C 上一非空行是纯叙述且含说话动词 → 取它的唯一主语
  D 下一行紧贴的纯叙述，且以「名字 + 说话动词」开头（“…”\n张三说完就走了。）。
    下一行自己带引号、或以「：」结尾，说明它在引出下一句，不能拿来归属本句。

两种中文引号（“” 和 「」『』）都认，以 config 的 quote_open / quote_close 为准。
「知道」「难道」「问题」「小说」这类词里的「道 / 问 / 说」不算说话动词。
归属准确率直接决定语音档案的可信度，所以自动抓完最好再抽 5% 用模型核一遍。
"""
import os
import re
import sys
import glob
import random
import argparse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio, corpus as C      # noqa: E402

VERBS = ("说", "道", "问", "答", "喊", "叫", "吼", "嘟囔", "低语", "回答", "解释",
         "询问", "回应", "开口", "补充", "叮咛", "提醒", "警告", "宣布", "喃喃", "呢喃",
         "说道", "问道", "答道", "笑道", "叹气", "点头", "摇头", "皱眉", "嘀咕")

# 含说话动词的字、但本身不是在说话的词
NOT_SPEECH = ("知道", "难道", "味道", "道路", "道理", "道歉", "街道", "轨道", "频道", "通道",
              "地道", "霸道", "公道", "报道", "一道", "道具", "说明", "小说", "听说", "据说",
              "传说", "虽说", "问题", "学问", "疑问", "访问", "叫做", "答案")
# 名字前紧挨着介词时，名字是宾语（她对张三说）
OBJ_BEFORE = "对向跟朝冲给被把让"
# 动词前紧挨着否定 / 情态词时不是在说话（没说、想问、不知该说）
NEG_BEFORE = "不没别想要该能会敢"
PRONOUNS = ("他", "她", "它", "我", "你", "您", "咱", "俺")
COLON = ("：", ":")
CJK = re.compile(r"[\u4e00-\u9fff]")


def make_attributor(names, verbs=VERBS):
    """返回 attribute(lines) -> [{who, text}]。lines 是按段落切好的行。"""
    names = sorted(set(n for n in names if n), key=len, reverse=True)
    if not names:
        raise ValueError("names 为空")
    alt = "|".join(re.escape(n) for n in names)
    name_re = re.compile(alt)
    name_split = re.compile("(" + alt + ")")
    verb_alt = "|".join(re.escape(v) for v in sorted(verbs, key=len, reverse=True))
    verb_re = re.compile(verb_alt)
    subj_re = re.compile("(?<![" + OBJ_BEFORE + "])(" + alt + r")[^，。！？、：:\n]{0,6}?"
                         "(?<![" + NEG_BEFORE + "])(?:" + verb_alt + ")")
    not_speech = re.compile("|".join(re.escape(w) for w in NOT_SPEECH))

    def mask(s):
        """把「知道」这类词换成占位符；名字本身不动（名字里可能恰好有这些字）。"""
        parts = name_split.split(s)
        return "".join(p if k % 2 else not_speech.sub(lambda m: "＿" * len(m.group()), p)
                       for k, p in enumerate(parts))

    def names_in(s):
        return list(dict.fromkeys(name_re.findall(s)))

    def subject_of(s):
        got = list(dict.fromkeys(subj_re.findall(mask(s))))
        return got[0] if len(got) == 1 else None

    def has_verb(s):
        return bool(verb_re.search(mask(s)))

    def lone_name(s):
        """以「：」结尾、只有一个名字且没有代词的引语句：张三看着窗外：「…」"""
        nm = names_in(s)
        if len(nm) == 1 and not any(p in s for p in PRONOUNS):
            return nm[0]
        return None

    def same_line(ln):
        """(有没有同行叙述, 主语)"""
        ms = list(C.QUOTE.finditer(ln))
        outside = C.QUOTE.sub("｜", ln)
        if not CJK.search(outside):
            return False, None
        who = subject_of(outside)
        if who is None:
            lead = ln[:ms[0].start()].rstrip()
            if lead.endswith(COLON) and len(names_in(outside)) == 1:
                who = lone_name(lead)
        return True, who

    def prev_line(lines, i):
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            return False, None
        pv = lines[j].strip()
        if pv.startswith("#") or C.QUOTE.search(pv):
            return False, None
        if pv.endswith(COLON):
            return True, subject_of(pv) or lone_name(pv)
        if has_verb(pv):
            return True, subject_of(pv)
        return False, None

    def next_line(lines, i):
        if i + 1 >= len(lines):
            return None
        nx = lines[i + 1].strip()
        if not nx or nx.startswith("#") or nx.endswith(COLON) or C.QUOTE.search(nx):
            return None
        m = subj_re.match(mask(nx))
        if m and subject_of(nx) == m.group(1):
            return m.group(1)
        return None

    def speaker(lines, i):
        decided, who = same_line(lines[i])
        if decided:
            return who
        decided, who = prev_line(lines, i)
        if decided:
            return who
        return next_line(lines, i)

    def attribute(lines):
        pairs = []
        for i, ln in enumerate(lines):
            qs = C.QUOTE.findall(ln)
            if not qs:
                continue
            who = speaker(lines, i)
            if not who:
                continue
            for q in qs:
                q = q.strip()
                if len(q) >= 2:
                    pairs.append({"who": who, "text": q})
        return pairs

    return attribute


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
    attribute = make_attributor(names)

    pairs = []
    files = sorted(glob.glob(os.path.join(cfg["paths"]["chunks"], "chunk_*.txt")),
                   key=textio.natural_key)
    if not files:
        files = [os.path.join(cfg["paths"]["raw"], "_all.txt")]
    for f in files:
        pairs += attribute(textio.read_text(f).split("\n"))

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
