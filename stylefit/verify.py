#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style-fit · 四层验收 + 0 频探针。写完稿子跑这个。

  python stylefit/verify.py --text 稿子.txt --corpus chunks --out cache/mybook \
      [--ref-pattern '(猫|尾巴|摸头)'] [--quiet]

四层（全部从语料自身拟合，不需要人工标注、不需要另一个模型盲判）：

  门槛层   —— 段级边际统计在不在同类参考段范围内。
              这类指标对「把段落打乱」完全免疫（AUC 恰好 0.500），
              原理上测不出「像不像」，只能当筛子。
  结构层   —— 自打乱比值 jacCt(原文)/jacCt(自打乱)。参照值现场从语料算，不写死。
              最弱的一层，只作参考。
  逐句层   —— 字符 4-gram，按 (类型 × 句长档) 条件归一化成 z。
              唯一能测「这句话像不像」的层。z 越接近 0 越像；负=比书平淡，正=比书生造。
  0 频探针 —— 稿子的 4-gram 拿去语料查新造率；基准用留出法算。看倍数，不看绝对值。

另附「新专名检测」：稿子里反复出现、语料里 0 次的 2-4 字串，
会被等长替换成书里的名字后再算一遍逐句层和探针，避免新角色名把整层指标抬起来。
"""
import os
import re
import sys
import json
import math
import random
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus as C          # noqa: E402

SPLIT = re.compile(r"[。！？…，、；：]")
LB = [(1, 5), (6, 10), (11, 20), (21, 40), (41, 999)]
STOP = set("的了是在和就都而但也没什么有他她它我你我们不这那一个人上下来去说着到为以与被把给对能会要可以只还又已经于而且所以但是然后于是接着")


def lbk(n):
    for i, (a, b) in enumerate(LB):
        if a <= n <= b:
            return i
    return len(LB) - 1


# ── 字符 4-gram（逐句层用）──
def train_ngram(lines, N=4, A=0.30):
    n = {k: {} for k in range(1, N + 1)}
    d = {k: {} for k in range(2, N + 1)}
    for s in lines:
        for i in range(len(s)):
            for k in range(1, N + 1):
                if i - k + 1 < 0:
                    break
                g = s[i - k + 1:i + 1]
                n[k][g] = n[k].get(g, 0) + 1
                if k >= 2:
                    h = g[:-1]
                    d[k][h] = d[k].get(h, 0) + 1
    sufD = {k: {} for k in range(1, N + 1)}
    for k in range(1, N + 1):
        for g in n[k]:
            sufD[k][g[-1]] = sufD[k].get(g[-1], 0) + 1
    sufT = {k: sum(sufD[k].values()) for k in range(1, N + 1)}
    tot = sum(n[1].values()) or 1
    V = len(n[1]) or 1
    return {"n": n, "d": d, "sufD": sufD, "sufT": sufT, "N": N,
            "uni": {c: (v + A) / (tot + A * V) for c, v in n[1].items()},
            "floor": (A / 2) / (tot + A * V)}


LAM = {2: .45, 3: .30, 4: .30}


def bits(M, s):
    n, d, sufD, sufT, uni, floor = (M["n"], M["d"], M["sufD"], M["sufT"],
                                    M["uni"], M["floor"])
    N = M["N"]
    t = 0.0
    for i in range(len(s)):
        acc = uni.get(s[i], floor)
        for k in range(2, N + 1):
            if i - k + 1 < 0:
                break
            g = s[i - k + 1:i + 1]
            h = g[:-1]
            c = s[i]
            dh = d[k].get(h, 0)
            p = (n[k][g] / dh) if (dh and g in n[k]) else (
                sufD[k].get(c, 0) / sufT[k] if sufT[k] else 0.0)
            acc = LAM.get(k, .3) * p + (1 - LAM.get(k, .3)) * acc
        t += min(-math.log2(max(acc, 2 ** -20)), 14.0)
    return t / max(1, len(s))


# ── 内容保留打散（结构层用）──
def cset(p):
    t = re.sub(r"[^\u4e00-\u9fff]", "", p)
    return {t[i:i + 2] for i in range(len(t) - 1)
            if t[i] not in STOP and t[i + 1] not in STOP}


def jacCt(ps):
    s = n = 0
    for i in range(1, len(ps)):
        a, b = cset(ps[i - 1]), cset(ps[i])
        u = len(a | b)
        s += len(a & b) / u if u else 0
        n += 1
    return s / n if n else 0.0


def ratio(ps, K=400, seed=31337):
    R = random.Random(seed)

    def sh(a):
        a = a[:]
        for i in range(len(a) - 1, 0, -1):
            j = R.randrange(i + 1)
            a[i], a[j] = a[j], a[i]
        return a
    obs = jacCt(ps)
    acc = 0.0
    for _ in range(K):
        acc += jacCt(sh(ps))
    return (obs + 1e-4) / (acc / K + 1e-4)


def feats(text, paras):
    q = C.QUOTE.findall(text)
    L = [len(re.sub(r"\s", "", x)) for x in q]
    cc = len(re.sub(r"\s", "", text))
    return {"chars": cc, "paras": len(paras),
            "dlg": sum(x + 2 for x in L) / max(1, cc),
            "lineLen": sum(L) / max(1, len(L)),
            "le19": sum(1 for x in L if x <= 19) / max(1, len(L)),
            "b2024": sum(1 for x in L if 20 <= x <= 24) / max(1, len(L)),
            "segLen": cc / max(1, len(paras)),
            "ell": sum(1 for x in q if "…" in x) / max(1, len(L)),
            "qm": sum(1 for x in q if "？" in x) / max(1, len(L)),
            "excl": sum(1 for x in q if "！" in x) / max(1, len(L))}


KW = ["chars", "paras", "dlg", "lineLen", "le19", "b2024", "segLen", "ell", "qm", "excl"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref-pattern", default=None,
                    help="参考区间按场景切，例 '(猫|尾巴|摸头)'；不填用全书")
    ap.add_argument("--ref-req", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    raw, _ = C.load_corpus(a.corpus)
    paras_all = C.paragraphs(raw)
    text = open(a.text, encoding="utf-8").read().lstrip("\ufeff")
    tparas = [x.strip() for x in text.split("\n") if x.strip()]

    # ── 0 频探针：表用 90% 的段，基准量剩下 10% ──
    pool = paras_all[:]
    random.Random(7).shuffle(pool)
    cut = max(200, len(pool) // 10)
    hold, trainp = pool[:cut], pool[cut:]
    bg = set()
    for p in trainp:
        c = re.sub(r"[^\u4e00-\u9fff]", "", p)
        for i in range(len(c) - 3):
            bg.add(c[i:i + 4])

    def nrate(seg_list):
        t_ = n_ = 0
        for p in seg_list:
            c = re.sub(r"[^\u4e00-\u9fff]", "", p)
            for i in range(len(c) - 3):
                t_ += 1
                if c[i:i + 4] not in bg:
                    n_ += 1
        return n_ / max(1, t_)
    base = nrate(hold)

    # ── 新专名检测（会把整层指标抬高，先隔离）──
    Bfull = re.sub(r"[^\u4e00-\u9fff]", "", raw)
    cand_cnt = {}
    for p in tparas:
        c0 = re.sub(r"[^\u4e00-\u9fff]", "", p)
        for n in (4, 3, 2):
            for i in range(len(c0) - n + 1):
                s = c0[i:i + n]
                cand_cnt[s] = cand_cnt.get(s, 0) + 1
    cand = [s for s, k in cand_cnt.items() if k >= 4 and s not in Bfull]
    picked = []
    for s in sorted(set(cand), key=lambda x: -len(x)):
        if not any(s in p or p in s for p in picked):
            picked.append(s)
    idxp = os.path.join(a.out, "index.json")
    booknames = []
    if os.path.isfile(idxp):
        try:
            booknames = list(json.load(open(idxp, encoding="utf-8"))["台词"].keys())
        except Exception:
            booknames = []
    name_map, used = {}, set()
    for s in picked:
        rep = next((n for n in booknames if len(n) == len(s) and n not in used), None) \
            or next((n for n in booknames if len(n) == len(s)), None)
        name_map[s] = rep if rep else s[0] * len(s)
        if rep:
            used.add(rep)

    def subst(p):
        for s, r in name_map.items():
            p = p.replace(s, r)
        return p
    tparas_m = [subst(p) for p in tparas]

    def mrate(ps):
        t_ = n_ = cl = 0
        for p in ps:
            c = re.sub(r"[^\u4e00-\u9fff]", "", p)
            bad = 0
            for i in range(len(c) - 3):
                t_ += 1
                if c[i:i + 4] not in bg:
                    n_ += 1
                    bad += 1
            if bad == 0:
                cl += 1
        return n_ / max(1, t_), cl
    mine, clean = mrate(tparas)
    mine_m, clean_m = mrate(tparas_m)

    # ── 门槛层：同类参考段 ──
    segs, buf, cnt = [], [], 0
    if a.ref_pattern:
        for i, p in enumerate(paras_all):
            near = paras_all[max(0, i - 4):i + 5]
            if not (re.search(a.ref_pattern, p)
                    or any(re.search(a.ref_pattern, q) for q in near)):
                buf = []
                cnt = 0
                continue
            if a.ref_req and a.ref_req not in "".join(near):
                buf = []
                cnt = 0
                continue
            buf.append(p)
            cnt += len(re.sub(r"\s", "", p))
            if 480 <= cnt <= 620:
                segs.append(buf[:])
                buf = []
                cnt = 0
            elif cnt > 620:
                buf = []
                cnt = 0
            if len(segs) >= 200:
                break
    if len(segs) < 20:
        segs, buf, cnt = [], [], 0
        for p in paras_all:
            buf.append(p)
            cnt += len(re.sub(r"\s", "", p))
            if 480 <= cnt <= 620:
                segs.append(buf[:])
                buf = []
                cnt = 0
            elif cnt > 620:
                buf = []
                cnt = 0
            if len(segs) >= 200:
                break
    ref = [feats("\n\n".join(s), s) for s in segs]
    REF = {}
    for k in KW:
        v = sorted(r[k] for r in ref)
        REF[k] = (v[int(len(v) * .05)], v[int(len(v) * .95)])
    f = feats(text, tparas)
    outk = [k for k in KW if not (REF[k][0] <= f[k] <= REF[k][1])]

    # ── 逐句层：训练与校准分开 ──
    nlines = C.narr_sentences(paras_all)
    dlines = []
    for m in C.QUOTE.finditer(raw):
        x = m.group(1).strip()
        if len(re.sub(r"\s", "", x)) >= 2:
            dlines.append(x)
    random.Random(9).shuffle(nlines)
    random.Random(11).shuffle(dlines)
    n_cal, n_tr = nlines[:2500], nlines[2500:22000]
    d_cal, d_tr = dlines[:4000], dlines[4000:24000]
    MN, MD = train_ngram(n_tr), train_ngram(d_tr)
    CAL = {}
    for tag, M, lines in (("n", MN, n_cal), ("d", MD, d_cal)):
        for i in range(len(LB)):
            v = [bits(M, x) for x in lines if lbk(len(re.sub(r"\s", "", x))) == i]
            if len(v) < 20:
                continue
            mu = sum(v) / len(v)
            CAL[(tag, i)] = (mu, max((sum((x - mu) ** 2 for x in v) / len(v)) ** .5, 1e-6))

    dial = [x.strip() for p in tparas for x in C.QUOTE.findall(p)
            if len(re.sub(r"\s", "", x.strip())) >= 2]
    narr = C.narr_sentences(tparas)

    def sc(lines, M, tag):
        per = []
        for s in lines:
            L = len(re.sub(r"\s", "", s))
            c = CAL.get((tag, lbk(L)))
            if not c:
                continue
            per.append(((bits(M, s) - c[0]) / c[1], s))
        return per
    pd_, pn = sc(dial, MD, "d"), sc(narr, MN, "n")
    dial_m = [x.strip() for p in tparas_m for x in C.QUOTE.findall(p)
              if len(re.sub(r"\s", "", x.strip())) >= 2]
    narr_m = C.narr_sentences(tparas_m)
    pdm, pnm = sc(dial_m, MD, "d"), sc(narr_m, MN, "n")

    def zbook(M, lines, tag):
        out = []
        for s in lines:
            L = len(re.sub(r"\s", "", s))
            c = CAL.get((tag, lbk(L)))
            if c:
                out.append((bits(M, s) - c[0]) / c[1])
        return out
    rd = zbook(MD, d_cal[:1500], "d")
    rn = zbook(MN, n_cal[:1500], "n")

    print("=" * 74)
    print(os.path.basename(a.text))
    print("字数 %d ｜ 段 %d ｜ 段长 %.1f ｜ 对白 %.1f%% ｜ 台词均长 %.1f ｜ ≤19 %.0f%% ｜ 20-24 %.0f%%" % (
        f["chars"], f["paras"], f["segLen"], f["dlg"] * 100, f["lineLen"],
        f["le19"] * 100, f["b2024"] * 100))
    print("参考段 %d 个%s" % (len(ref), ("（筛选 %s）" % a.ref_pattern) if a.ref_pattern else "（全书）"))
    print("门槛：%s" % ("越界 " + " ".join(
        "%s=%.2f(应%.2f~%.2f)" % (k, f[k], REF[k][0], REF[k][1]) for k in outk)
        if outk else "全部在范围内"))
    if not a.quiet:
        r = ratio(tparas)
        idxs = list(range(min(30, len(segs))))
        ref_r = sorted(ratio(segs[i], K=200, seed=1000 + i) for i in idxs)
        scr_r = []
        for i in idxs[:15]:
            R2 = random.Random(500 + i)
            a2 = segs[i][:]
            for j in range(len(a2) - 1, 0, -1):
                k2 = R2.randrange(j + 1)
                a2[j], a2[k2] = a2[k2], a2[j]
            scr_r.append(ratio(a2, K=200, seed=2000 + i))
        scr_r.sort()
        print("结构比值(K=400)：%.2f   （同类书段中位 %.2f ｜ 打乱样本中位 %.2f）" % (
            r, ref_r[len(ref_r) // 2], scr_r[len(scr_r) // 2]))
    zs = [x[0] for x in pd_]
    zn = [x[0] for x in pn]
    print("逐句 z：台词 %d 句 %+.2f（书自身 %+.2f）｜ 叙述 %d 句 %+.2f（书自身 %+.2f）" % (
        len(zs), sum(zs) / max(1, len(zs)), sum(rd) / max(1, len(rd)),
        len(zn), sum(zn) / max(1, len(zn)), sum(rn) / max(1, len(rn))))
    print("0 频探针：新造 4-gram %.1f%%（书留出基准 %.1f%%，%.2f 倍）｜ 0 新造句 %d/%d" % (
        mine * 100, base * 100, mine / max(1e-9, base), clean, len(tparas)))
    if picked and not a.quiet:
        zs2 = [x[0] for x in pdm]
        zn2 = [x[0] for x in pnm]
        print("疑似新专名：%s  →  等长换成书里的 %s" % (
            "、".join(picked), "、".join(name_map[s] for s in picked)))
        print("扣除新专名后：逐句 z 台词 %+.2f ｜ 叙述 %+.2f   0 频探针 %.1f%%（%.2f 倍）" % (
            sum(zs2) / max(1, len(zs2)), sum(zn2) / max(1, len(zn2)),
            mine_m * 100, mine_m / max(1e-9, base)))
    worst = sorted(pd_ + pn, key=lambda x: -x[0])[:3]
    if worst:
        print("最贵 3 句：")
        for z, s in worst:
            print("   z=%+.2f  「%s」" % (z, s[:40]))


if __name__ == "__main__":
    main()
