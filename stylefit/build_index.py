#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style-fit · 建索引。

从语料里统计出：人物×功能台词、描写意图、搭配表、用词表、零频黑名单、场景片段、统计靶。
全部来自语料本身，不需要人工标注。

用法：
  python stylefit/build_index.py --corpus chunks --out cache/mybook \
      [--attrib attrib.json] [--names 甲,乙,丙] [--config config/stylefit]

归属文件可选。没有就用「名字+说话动词+引号」自动抓（准确率低一些，台词类够用）。
"""
import os
import re
import sys
import json
import argparse
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus as C          # noqa: E402

CFG = os.path.join(ROOT, "config", "stylefit")

# ── 台词功能桶：纯表层规则，可解释、可改（放 config/stylefit/funcs.json 可覆盖）──
FUNCS_DEFAULT = [
    ["命令禁止", r"^(别|不要|不许|给我|把.{0,6}(放下|拿来|还)|少|快滚|闭嘴|住手)"],
    ["让步接受", r"^(嗯|好|行|那好|好吧|那就|可以|知道了|随便|算了)"],
    ["否认辩解", r"(不是你想|才不|没有|我那是|不是[^，。]{0,6}是|听我解释|误会)"],
    ["反问逼问", r"[？?]\s*$|难道|不是.{0,8}吗|凭什么|为什么"],
    ["请求商量", r"(让我|能不能|可不可以|好吗|好不好|帮我|借我|陪我)"],
    ["慌乱结巴", r"(、|……).{0,3}(我|你)|我我|你你|不、|别、"],
    ["关心担忧", r"(没事|小心|别担心|放心吧|伤|疼|休息|我来)"],
    ["抱怨吐槽", r"(烦|真是|又来了|搞什么|凭什么|可恶|偏偏|未免)"],
    ["陈述说明", r"."],
]


def load_funcs(cfg_dir):
    f = os.path.join(cfg_dir, "funcs.json")
    if os.path.isfile(f):
        d = json.load(open(f, encoding="utf-8"))
        return [(k, v) for k, v in d.items() if not k.startswith("_")]
    return [(k, v) for k, v in FUNCS_DEFAULT]


def bucket(t, funcs):
    for name, pat in funcs:
        if re.search(pat, t):
            return name
    return "陈述说明"


def quantile_pick(v, k=6):
    v = sorted(v, key=len)
    n = len(v)
    picked = [v[min(n - 1, int(n * i / k))] for i in range(1, k)]
    return list(dict.fromkeys(picked))


def scene_of(txt):
    if re.search(r"(打|砍|劈|箭|魔法阵|轰|伤口|血|闪避|斩|枪|攻击)", txt):
        return "战斗"
    if re.search(r"(金币|铜币|价钱|买卖|委托|报酬|账|赊|买|卖)", txt):
        return "交易"
    if re.search(r"(脸红|害羞|亲|吻|抱|嘴唇|羞耻|搂|贴|喘)", txt):
        return "亲密"
    if re.search(r"(道歉|拜托|商量|会议|协会|委托人|谈判|请求)", txt):
        return "交涉"
    return "日常"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--attrib", default=None)
    ap.add_argument("--names", default="", help="已知人名，逗号分隔（自动抓说话人用）")
    ap.add_argument("--config", default=CFG)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    raw, files = C.load_corpus(a.corpus)
    if not raw.strip():
        print("语料为空：", a.corpus)
        sys.exit(1)
    paras = C.paragraphs(raw)
    B = re.sub(r"[^\u4e00-\u9fff]", "", raw)    # 只留汉字：词频
    BR = re.sub(r"\s", "", raw)                  # 留标点：带标点的说法、标点率
    funcs = load_funcs(a.config)
    print("语料 %d 个文件 ｜ %d 字 ｜ %d 段" % (len(files), len(B), len(paras)))

    # ── 归属 ──
    pairs = C.load_attribution(a.attrib)
    src = "归属文件"
    if not pairs:
        names = [x.strip() for x in a.names.split(",") if x.strip()]
        if not names:
            names = [n for n, _ in Counter(
                m for m in re.findall(r"([\u4e00-\u9fff]{2,4})(?=[^。！？\n]{0,8}" + C.VERB + r")", raw)
            ).most_common(30)]
        pairs = C.derive_speakers(raw, names)
        src = "自动抓取"
    print("台词配对 %d 条（%s，%d 个说话人）" % (len(pairs), src, len({w for w, _ in pairs})))

    narr = C.narr_sentences(paras)
    IDX = {"meta": {"corpus": a.corpus, "chars": len(B), "paras": len(paras),
                    "files": len(files), "attrib": src, "pairs": len(pairs)},
           "台词": {}, "描写": {}, "搭配": {}, "用词": {}, "零频词": [], "场景": {},
           "场景词典": {}, "统计": {}}

    # ── 1 人物 × 功能 ──
    by = defaultdict(list)
    for w, t in pairs:
        t = t.strip()
        if len(re.sub(r"\s", "", t)) >= 2:
            by[w].append(t)
    for who, ls in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(ls) < 30:
            continue
        bk = defaultdict(list)
        for t in ls:
            bk[bucket(t, funcs)].append(t)
        IDX["台词"][who] = {
            k: {"n": len(v),
                "中位长度": sorted(len(x) for x in v)[len(v) // 2],
                "样本": quantile_pick(v)}
            for k, v in sorted(bk.items(), key=lambda kv: -len(kv[1]))}

    # ── 2 描写意图 ──
    intents = {}
    f = os.path.join(a.config, "intents.json")
    if os.path.isfile(f):
        intents = json.load(open(f, encoding="utf-8"))
    for name, pat in intents.items():
        if name.startswith("_"):
            continue
        hits = [m.group(0).replace("\n", "")
                for m in re.finditer(r".{0,28}(?:" + pat + r").{0,32}", raw)]
        seen, keep = set(), []
        for h in hits:
            if h in seen:
                continue
            seen.add(h)
            if len(keep) < 8:
                keep.append(h)
        IDX["描写"][name] = {"n": len(hits), "样本": keep}

    # ── 3 搭配表（核心）──
    coll = {}
    f = os.path.join(a.config, "colloc.json")
    if os.path.isfile(f):
        coll = json.load(open(f, encoding="utf-8"))
    for k, cands in coll.items():
        if k.startswith("_"):
            continue
        IDX["搭配"][k] = {w: BR.count(w) for w in cands}

    # ── 3b 场景词典 ──
    scnd = {}
    f = os.path.join(a.config, "scenes.json")
    if os.path.isfile(f):
        scnd = json.load(open(f, encoding="utf-8"))
    IDX["场景词典"] = {k: {w: BR.count(w) for w in v}
                   for k, v in scnd.items() if not k.startswith("_")}

    # ── 4 用词表 / 零频黑名单 ──
    words = {}
    f = os.path.join(a.config, "words.json")
    if os.path.isfile(f):
        words = json.load(open(f, encoding="utf-8"))
    IDX["用词"] = {k: {w: BR.count(w) for w in v}
                 for k, v in words.items() if not k.startswith("_")}
    cand = []
    for d in (coll, words, scnd):
        for k, vs in d.items():
            if not k.startswith("_"):
                cand += vs
    IDX["零频词"] = sorted({w for w in cand if BR.count(w) == 0})

    # ── 5 场景片段 ──
    bs = defaultdict(list)
    for i, p in enumerate(paras):
        s = scene_of(p)
        if len(bs[s]) < 400:
            bs[s].append("\n".join(paras[max(0, i - 3):i + 5]))
    IDX["场景"] = {s: {"n": len(v), "样本": v[:4]} for s, v in bs.items()}

    # ── 6 统计靶 ──
    L = [t for _, t in pairs if len(re.sub(r"\s", "", t)) >= 2]
    lens = sorted(len(x) for x in L)
    IDX["统计"] = {
        "台词均长": round(sum(lens) / max(1, len(lens)), 1),
        "台词中位长度": lens[len(lens) // 2] if lens else 0,
        "台词≤19字占比": round(sum(1 for x in lens if x <= 19) / max(1, len(lens)), 3),
        "每千字标点": {p: round(BR.count(p) / max(1, len(B)) * 1000, 2)
                   for p in ["！", "？", "…", "——", "，", "。"]},
        "说话人台词量": {w: c for w, c in Counter(w for w, _ in pairs).most_common(12)},
        "叙述句数": len(narr),
    }

    out = os.path.join(a.out, "index.json")
    json.dump(IDX, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("索引写入 %s" % out)
    print("人物 %d ｜ 功能桶 %d ｜ 描写意图 %d ｜ 搭配概念 %d ｜ 场景 %d ｜ 场景词典 %d ｜ 零频词 %d" % (
        len(IDX["台词"]), sum(len(v) for v in IDX["台词"].values()), len(IDX["描写"]),
        len(IDX["搭配"]), len(IDX["场景"]), len(IDX["场景词典"]), len(IDX["零频词"])))
    if IDX["零频词"]:
        print("零频词（全书 0 次，禁用）：",
              "、".join(IDX["零频词"][:40]) + ("..." if len(IDX["零频词"]) > 40 else ""))


if __name__ == "__main__":
    main()
