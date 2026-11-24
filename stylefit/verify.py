#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style-fit · 五层验收 + Layer 0 基础排雷/反AI探针 + 照抄检测 + 跨领域适配。

用法：
  python stylefit/verify.py --text 稿子.txt --corpus chunks --out cache/mybook [选项]
  python stylefit/verify.py --prewarm --corpus chunks --out cache/mybook
  python stylefit/verify.py --diff v1.txt v2.txt --corpus chunks --out cache/mybook

验收分层（全部从语料自身拟合，不需要人工标注、不需要另一个模型盲判）：
  Layer 0  —— 异常脚本/乱码、零频黑名单、低频搭配(+高频替代)、标点密度、语料拟合 AI 腔与结构探针
  照抄检测 —— 对照 例子.txt 与全书语料 Bfull 查 ≥10 汉字高重合片段
  门槛层   —— 段级边际统计（长稿 >800 字自动切换尺度不变指标 + ~550 字滑窗评估；支持 POV 分桶）
  结构层   —— 自打乱比值 jacCt(原文)/jacCt(自打乱)，参照值现场从语料算
  逐句层   —— 字符 4-gram，按 (类型 × 句长档) 条件归一化成 z；支持专名窗口掩码与 Top-N 0 频高亮
  0 频探针 —— 稿子 4-gram 查新造率（留出法基准），支持专名/领域词窗口掩码（绝不重复首字污染）
  跨领域层 —— 40 个领域无关虚词/转折词分布（Cosine & Jensen-Shannon 相似度）+ 标点轮廓相似度
"""
import os
import re
import sys
import html
import json
import math
import pickle
import random
import hashlib
import argparse
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus as C          # noqa: E402
from lib import textio               # noqa: E402

SPLIT = re.compile(r"[。！？…，、；：]")
LB = [(1, 5), (6, 10), (11, 20), (21, 40), (41, 999)]
STOP = set(
    "的了是在和就都而但也没什么有他她它我你我们不这那一个人上下来去说着到为以与被把给对能会要可以只还又已经于而且所以但是然后于是接着"
)

PUNCT_KEYS = ["！", "？", "…", "——", "，", "。"]
KW = ["chars", "paras", "dlg", "lineLen", "le19", "b2024", "segLen", "ell", "qm", "excl"]
SCALE_INVARIANT_KW = ["dlg", "lineLen", "le19", "b2024", "segLen", "ell", "qm", "excl"]

# ── 异常脚本检测正则（全部从语料拟合：仅当语料该脚本总数 < 5 时报警）──
SCRIPT_RES = {
    "hangul": ("韩文", re.compile(r"[\uac00-\ud7af\u1100-\u11ff]+")),
    "kana": ("日文假名", re.compile(r"[\u3040-\u30ff]+")),
    "cyrillic": ("西里尔字母", re.compile(r"[\u0400-\u04ff]+")),
}

# ── 候选 AI 腔套话（严格语料拟合：仅当语料 0 次或 <=1 次且 <0.2/10万字 才报警）──
AI_CLICHE_CANDIDATES = [
    "漏了一拍", "停了一拍", "浑身一僵", "背脊一僵", "背脊僵了一下",
    "声音干涩", "嗓音干涩", "眼眸", "无机质", "冰冷刺骨",
    "声音平平", "没有半点起伏", "近乎残酷", "冷汗贴在", "空气仿佛凝固",
    "倒吸一口凉气", "指节发白", "嘴角勾起一抹", "微微发凉", "呼吸拂过",
    "浪漫关系", "像婴儿一样哭", "沉重又平静", "冷静得近乎",
    "跳出来的名字", "报道砸了下来", "震得耳朵发麻",
]

# ── 结构探针正则 ──
NEG_CLAUSE_RE = re.compile(r"(?:没有|不是|不再|不会|也没|也不|没再)")
NEG_CONTRAST_RE = re.compile(
    r"(?:脸上没有[^。！？\n]{1,8}[，,]\s*只有|没有[^。！？\n]{1,12}[，,]\s*(?:反而|只有|只是|而是))"
)
MOOD_TAG_RE = re.compile(
    r"(?:声音|语气|嗓音)[^。！？\n]{0,6}(?:平平|干涩|低沉|沙哑|平静|冷淡|轻描淡写|没有半点起伏|没有起伏|沉重)"
)

# ── 相邻句重复 2 字实词排除表（常见虚词/代词/补语）──
REPEAT_2CHAR_STOP = set("""
我们 你们 他们 她们 自己 什么 怎么 这样 那样 这个 那个 这里 那里 这些 那些
没有 不是 可以 已经 因为 所以 但是 不过 还是 就是 只是 如果 虽然 然后 接着
于是 时候 时间 东西 地方 事情 问题 一下 一起 一样 一直 一定 一个 一种 一边
一面 这么 那么 知道 觉得 感觉 好像 似乎 应该 可能 必须 现在 刚才 以前 以后
大家 有人 没人 不会 不能 不要 不想 不敢 出来 起来 下来 回去 过去 过来 进去
出去 上去 回来 看着 说着 笑着 听着 想着 望着 走着 站着 坐着 问道 说道 回答
开口 转身 点头 摇头 其实 反正 大概 或许 居然 竟然 果然 终于 依然 仍然
""".split())

# ── 跨领域虚词/转折词骨架（40 个领域无关功能词）──
FUNC_WORDS = [
    "所以", "不过", "可是", "明明", "竟然", "居然", "果然", "稍微", "实在", "其实",
    "反正", "到底", "究竟", "反而", "简直", "似乎", "好像", "大概", "或许", "毕竟",
    "虽然", "但是", "然而", "却", "还是", "只是", "而且", "甚至", "总觉得", "原本",
    "本来", "既然", "无论", "就算", "哪怕", "只要", "只有", "依然", "仍然", "终于",
]


def lbk(n):
    for i, (a, b) in enumerate(LB):
        if a <= n <= b:
            return i
    return len(LB) - 1


def _snippet(line, start=0, end=None, radius=18):
    s = line.strip()
    if len(s) <= 44:
        return s
    if end is None:
        return s[:44] + "…"
    lo = max(0, start - radius)
    hi = min(len(line), end + radius)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(line) else ""
    return prefix + line[lo:hi].strip() + suffix


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
    return {
        "n": n, "d": d, "sufD": sufD, "sufT": sufT, "N": N,
        "uni": {c: (v + A) / (tot + A * V) for c, v in n[1].items()},
        "floor": (A / 2) / (tot + A * V),
    }


LAM = {2: .45, 3: .30, 4: .30}


def build_char_mask(s, masked_terms):
    """返回与 s 等长的布尔列表，标记命中任意 masked_terms 的字符位置。"""
    if not s or not masked_terms:
        return None
    L = len(s)
    mask = [False] * L
    hit_any = False
    for term in masked_terms:
        if not term:
            continue
        start = 0
        tlen = len(term)
        while True:
            idx = s.find(term, start)
            if idx == -1:
                break
            for j in range(idx, idx + tlen):
                mask[j] = True
            hit_any = True
            start = idx + 1
    return mask if hit_any else None


def bits(M, s, mask=None):
    """计算字符串 s 的平均字符交叉熵（bits/char）。

    当提供 mask（与 s 等长的布尔序列）时，跳过所有 4-gram 窗口接触到
    被掩码字符的位置，避免专名/领域词污染句级 z；若全部位置都被掩码则返回 None。
    """
    n, d, sufD, sufT, uni, floor = (
        M["n"], M["d"], M["sufD"], M["sufT"], M["uni"], M["floor"]
    )
    N = M["N"]
    t = 0.0
    counted = 0
    for i in range(len(s)):
        if mask is not None:
            w_lo = max(0, i - N + 1)
            if any(mask[w_lo:i + 1]):
                continue
        acc = uni.get(s[i], floor)
        for k in range(2, N + 1):
            if i - k + 1 < 0:
                break
            g = s[i - k + 1:i + 1]
            h = g[:-1]
            c = s[i]
            dh = d[k].get(h, 0)
            p = (n[k][g] / dh) if (dh and g in n[k]) else (
                sufD[k].get(c, 0) / sufT[k] if sufT[k] else 0.0
            )
            acc = LAM.get(k, .3) * p + (1 - LAM.get(k, .3)) * acc
        t += min(-math.log2(max(acc, 2 ** -20)), 14.0)
        counted += 1
    if mask is not None:
        if counted == 0:
            return None
        return t / counted
    return t / max(1, len(s))


# ── 内容保留打散（结构层用）──
def cset(p):
    t = re.sub(r"[^\u4e00-\u9fff]", "", p)
    return {
        t[i:i + 2] for i in range(len(t) - 1)
        if t[i] not in STOP and t[i + 1] not in STOP
    }


def jacCt_sets(sets):
    s = n = 0
    for i in range(1, len(sets)):
        a, b = sets[i - 1], sets[i]
        u = len(a | b)
        s += len(a & b) / u if u else 0
        n += 1
    return s / n if n else 0.0


def jacCt(ps):
    return jacCt_sets([cset(p) for p in ps])


def ratio(ps, K=400, seed=31337):
    R = random.Random(seed)
    sets = [cset(p) for p in ps]
    n = len(sets)
    obs = jacCt_sets(sets)
    if n < 2:
        return 1.0
    idx = list(range(n))
    acc = 0.0
    for _ in range(K):
        for i in range(n - 1, 0, -1):
            j = R.randrange(i + 1)
            idx[i], idx[j] = idx[j], idx[i]
        acc += jacCt_sets([sets[k] for k in idx])
    return (obs + 1e-4) / (acc / K + 1e-4)


def feats(text, paras):
    q = C.QUOTE.findall(text)
    L = [len(re.sub(r"\s", "", x)) for x in q]
    cc = len(re.sub(r"\s", "", text))
    return {
        "chars": cc,
        "paras": len(paras),
        "dlg": sum(x + 2 for x in L) / max(1, cc),
        "lineLen": sum(L) / max(1, len(L)),
        "le19": sum(1 for x in L if x <= 19) / max(1, len(L)),
        "b2024": sum(1 for x in L if 20 <= x <= 24) / max(1, len(L)),
        "segLen": cc / max(1, len(paras)),
        "ell": sum(1 for x in q if "…" in x) / max(1, len(L)),
        "qm": sum(1 for x in q if "？" in x) / max(1, len(L)),
        "excl": sum(1 for x in q if "！" in x) / max(1, len(L)),
    }


# ── 向量相似度辅助 ──
def cosine_sim(u, v):
    num = sum(a * b for a, b in zip(u, v))
    du = math.sqrt(sum(a * a for a in u))
    dv = math.sqrt(sum(b * b for b in v))
    if du <= 0.0 or dv <= 0.0:
        return 0.0
    return num / (du * dv)


def js_similarity(u, v):
    su = sum(u)
    sv = sum(v)
    if su <= 0.0 or sv <= 0.0:
        return 0.0
    p = [x / su for x in u]
    q = [x / sv for x in v]
    m = [0.5 * (pi + qi) for pi, qi in zip(p, q)]
    kl_pm = sum(pi * math.log2(pi / mi) for pi, mi in zip(p, m) if pi > 0.0 and mi > 0.0)
    kl_qm = sum(qi * math.log2(qi / mi) for qi, mi in zip(q, m) if qi > 0.0 and mi > 0.0)
    jsd = 0.5 * (kl_pm + kl_qm)
    return max(0.0, min(1.0, 1.0 - jsd))


def compute_punct_rates(text):
    no_ws = re.sub(r"\s", "", text)
    cjk_len = len(re.sub(r"[^\u4e00-\u9fff]", "", text))
    denom = max(1, cjk_len)
    counts = {p: no_ws.count(p) for p in PUNCT_KEYS}
    rates = {p: round(counts[p] / denom * 1000.0, 3) for p in PUNCT_KEYS}
    return counts, rates, cjk_len


def compute_script_counts(text):
    out = {}
    for key, (_label, rx) in SCRIPT_RES.items():
        out[key] = sum(len(m.group(0)) for m in rx.finditer(text))
    return out


def compute_func_profile(text, cjk_len=None):
    if cjk_len is None:
        cjk_len = len(re.sub(r"[^\u4e00-\u9fff]", "", text))
    denom = max(1, cjk_len)
    counts = {w: text.count(w) for w in FUNC_WORDS}
    rates = {w: round(counts[w] / denom * 10000.0, 3) for w in FUNC_WORDS}
    return counts, rates


def compute_mood_tag_stats(paras):
    hits = 0
    dlg_cnt = 0
    for p in paras:
        for qm in C.iter_quotes(p):
            if len(re.sub(r"\s", "", qm.inner)) >= 2:
                dlg_cnt += 1
        narr = C.strip_dialogue_quotes(p, keep_inline_text=True)
        hits += len(MOOD_TAG_RE.findall(narr))
    rate = hits / max(1, dlg_cnt)
    return hits, dlg_cnt, rate


# ── 语料加载 + v3 缓存 ──
def load_index_data(out_dir):
    idxp = os.path.join(out_dir, "index.json")
    if os.path.isfile(idxp):
        try:
            with open(idxp, encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def load_domain_terms(spec):
    if not spec:
        return []
    spec = spec.strip()
    terms = []
    if os.path.isfile(spec):
        txt = textio.read_text(spec)
        for ln in txt.split("\n"):
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            terms.append(s)
    else:
        for part in re.split(r"[,，;；\n]+", spec):
            s = part.strip()
            if s:
                terms.append(s)
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load_examples_blob(path):
    """从例子集（例子.txt）抽取正文/例句/引用/代码块，返回以换行分隔的纯汉字串。"""
    if not path or not os.path.isfile(path):
        return None
    raw = textio.read_text(path)
    cjk_lines = []
    in_code = False
    for ln in raw.split("\n"):
        s = ln.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if not s:
            continue
        if not in_code:
            if s.startswith("#") or s.startswith("|") or C.is_divider(s):
                continue
            s = re.sub(r"^(?:>\s*|[-*•]\s*|\d+[.、)）]\s*)", "", s)
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", s)
        if len(cjk) >= 8:
            cjk_lines.append(cjk)
    return "\n".join(cjk_lines) if cjk_lines else ""


def load_or_build_model(corpus_path, out_dir, no_cache=False):
    os.makedirs(out_dir, exist_ok=True)
    raw, files = C.load_corpus(corpus_path)
    if not raw.strip():
        raise ValueError("语料为空：%s" % corpus_path)
    paras_all = C.paragraphs(raw)

    sig_parts = []
    for fp in files:
        try:
            st = os.stat(fp)
            sig_parts.append((fp, st.st_size, int(st.st_mtime_ns)))
        except OSError:
            sig_parts.append((fp, 0, 0))
    sig_parts.append(("quotes", tuple(C.QUOTE_OPEN), tuple(C.QUOTE_CLOSE)))
    sig_parts.append(("ver", 3))
    corpus_sig = hashlib.sha256(repr(sig_parts).encode("utf-8")).hexdigest()[:16]
    cache_path = os.path.join(out_dir, "verify_cache.pkl")

    cached = None
    if not no_cache and os.path.isfile(cache_path):
        try:
            with open(cache_path, "rb") as fp:
                obj = pickle.load(fp)
            if isinstance(obj, dict) and obj.get("sig") == corpus_sig:
                cached = obj
        except Exception:
            cached = None

    if cached is not None:
        model = dict(cached)
        model["paras_all"] = paras_all
        model["files"] = files
        model["cache_hit"] = True
        model["cache_path"] = cache_path
        return model

    # ── 0 频探针：表用 90% 的段，基准量剩下 10% ──
    pool = paras_all[:]
    random.Random(7).shuffle(pool)
    cut = max(200, len(pool) // 10)
    if cut >= len(pool):
        cut = max(1, len(pool) // 5)
    hold, trainp = pool[:cut], pool[cut:]
    if not trainp:
        trainp = pool[:]
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
    Bfull = re.sub(r"[^\u4e00-\u9fff]", "", raw)

    # ── 逐句层：训练与校准分开 ──
    nlines = C.narr_sentences(paras_all)
    dlines = []
    for m in C.QUOTE.finditer(raw):
        x = m.group(1).strip()
        if len(re.sub(r"\s", "", x)) >= 2:
            dlines.append(x)
    random.Random(9).shuffle(nlines)
    random.Random(11).shuffle(dlines)
    if len(nlines) >= 5000:
        n_cal, n_tr = nlines[:2500], nlines[2500:80000]
    else:
        cut_n = max(1, len(nlines) // 5)
        n_cal, n_tr = nlines[:cut_n], nlines[cut_n:]
    if len(dlines) >= 8000:
        d_cal, d_tr = dlines[:4000], dlines[4000:80000]
    else:
        cut_d = max(1, len(dlines) // 5)
        d_cal, d_tr = dlines[:cut_d], dlines[cut_d:]

    MN, MD = train_ngram(n_tr), train_ngram(d_tr)
    CAL = {}
    for tag, M, lines in (("n", MN, n_cal), ("d", MD, d_cal)):
        min_bk = 20 if len(lines) >= 200 else 3
        for i in range(len(LB)):
            v = [bits(M, x) for x in lines if lbk(len(re.sub(r"\s", "", x))) == i]
            if len(v) < min_bk:
                continue
            mu = sum(v) / len(v)
            CAL[(tag, i)] = (mu, max((sum((x - mu) ** 2 for x in v) / len(v)) ** .5, 1e-6))

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

    # ── v3 语料拟合统计（脚本、标点、虚词、AI套话基线、对话情绪标签率）──
    corpus_scripts = compute_script_counts(raw)
    _pc, corpus_punct, corpus_chars = compute_punct_rates(raw)
    corpus_func_counts, corpus_func_rates = compute_func_profile(raw, corpus_chars)
    corpus_ai_counts = {term: raw.count(term) for term in AI_CLICHE_CANDIDATES}
    mood_hits, mood_dlgs, mood_rate = compute_mood_tag_stats(paras_all)

    payload = {
        "sig": corpus_sig,
        "bg": bg,
        "base": base,
        "Bfull": Bfull,
        "MN": MN,
        "MD": MD,
        "CAL": CAL,
        "rd": rd,
        "rn": rn,
        "corpus_chars": corpus_chars,
        "corpus_scripts": corpus_scripts,
        "corpus_punct": corpus_punct,
        "corpus_func_counts": corpus_func_counts,
        "corpus_func_rates": corpus_func_rates,
        "corpus_ai_counts": corpus_ai_counts,
        "corpus_mood_tag_hits": mood_hits,
        "corpus_dialogue_count": mood_dlgs,
        "corpus_mood_tag_rate": mood_rate,
    }
    try:
        tmp_p = cache_path + ".tmp"
        with open(tmp_p, "wb") as fp:
            pickle.dump(payload, fp, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_p, cache_path)
    except Exception:
        pass

    model = dict(payload)
    model["paras_all"] = paras_all
    model["files"] = files
    model["cache_hit"] = False
    model["cache_path"] = cache_path
    return model


# ── Layer 0 检测函数 ──
def _extract_lines_with_no(text):
    return [(i, ln) for i, ln in enumerate(text.split("\n"), 1)]


def detect_garbled_scripts(numbered_lines, corpus_scripts):
    hits = []
    for lineno, line in numbered_lines:
        if not line.strip():
            continue
        for key, (label, rx) in SCRIPT_RES.items():
            cc = int(corpus_scripts.get(key, 0))
            if cc >= 5:
                continue
            for m in rx.finditer(line):
                hits.append({
                    "line": lineno,
                    "script": key,
                    "script_label": label,
                    "chars": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                    "corpus_count": cc,
                    "snippet": _snippet(line, m.start(), m.end()),
                })
    return hits


def detect_zero_freq_hits(numbered_lines, index_data):
    blacklist = [w for w in (index_data.get("零频词") or []) if isinstance(w, str) and w.strip()]
    if not blacklist:
        return []
    blacklist = sorted(set(blacklist), key=len, reverse=True)
    hits = []
    for lineno, line in numbered_lines:
        if not line.strip():
            continue
        occupied = []
        for term in blacklist:
            start = 0
            while True:
                idx = line.find(term, start)
                if idx == -1:
                    break
                end = idx + len(term)
                if not any(idx >= a and end <= b for a, b in occupied):
                    occupied.append((idx, end))
                    hits.append({
                        "line": lineno,
                        "term": term,
                        "start": idx,
                        "end": end,
                        "snippet": _snippet(line, idx, end),
                    })
                start = idx + 1
    hits.sort(key=lambda x: (x["line"], x["start"]))
    return hits


def detect_low_freq_collocs(numbered_lines, index_data):
    collocs = index_data.get("搭配") or {}
    if not isinstance(collocs, dict) or not collocs:
        return []
    low_items = []
    for concept, mapping in collocs.items():
        if not isinstance(mapping, dict):
            continue
        # 构造 Top-3 高频替代（优先 freq >= 5，其次最高可用）
        high5 = sorted(
            [(w, int(c)) for w, c in mapping.items() if int(c) >= 5],
            key=lambda kv: (-kv[1], kv[0]),
        )
        all_pos = sorted(
            [(w, int(c)) for w, c in mapping.items() if int(c) > 0],
            key=lambda kv: (-kv[1], kv[0]),
        )
        for w, freq in mapping.items():
            f_int = int(freq)
            if 1 <= f_int <= 3 and w:
                alts = [x for x in high5 if x[0] != w][:3]
                if len(alts) < 3:
                    for x in all_pos:
                        if x[0] != w and x[1] > f_int and x not in alts:
                            alts.append(x)
                        if len(alts) >= 3:
                            break
                low_items.append((w, f_int, concept, alts))
    if not low_items:
        return []
    low_items.sort(key=lambda x: (-len(x[0]), x[0]))

    hits = []
    for lineno, line in numbered_lines:
        if not line.strip():
            continue
        seen_span_concept = set()
        for w, f_int, concept, alts in low_items:
            start = 0
            while True:
                idx = line.find(w, start)
                if idx == -1:
                    break
                key = (idx, idx + len(w), concept)
                if key not in seen_span_concept:
                    seen_span_concept.add(key)
                    hits.append({
                        "line": lineno,
                        "term": w,
                        "corpus_freq": f_int,
                        "concept": concept,
                        "alternatives": [[aw, af] for aw, af in alts],
                        "start": idx,
                        "end": idx + len(w),
                        "snippet": _snippet(line, idx, idx + len(w)),
                    })
                start = idx + 1
    hits.sort(key=lambda x: (x["line"], x["start"]))
    return hits


def evaluate_punct_density(draft_text, corpus_punct):
    draft_counts, draft_rates, draft_cjk = compute_punct_rates(draft_text)
    alerts = []
    for p in PUNCT_KEYS:
        dr = draft_rates[p]
        cr = float(corpus_punct.get(p, 0.0))
        dc = draft_counts[p]
        ratio_val = round(dr / cr, 2) if cr > 0 else (999.0 if dr > 0 else 1.0)
        if p == "——":
            if cr == 0 and dc > 0:
                alerts.append({
                    "punct": p, "draft_rate": dr, "corpus_rate": cr, "ratio": ratio_val,
                    "direction": "high",
                    "reason": "原书破折号为 0/千字，稿子出现 %d 次（%.2f/千字）" % (dc, dr),
                })
            elif cr > 0 and dr >= 2.0 * cr and dr >= 2.0:
                alerts.append({
                    "punct": p, "draft_rate": dr, "corpus_rate": cr, "ratio": ratio_val,
                    "direction": "high",
                    "reason": "破折号密度 %.2f/千字 ≥ 原书 %.2f/千字的 %.1f 倍" % (dr, cr, ratio_val),
                })
        else:
            if cr == 0 and dr >= 2.0:
                alerts.append({
                    "punct": p, "draft_rate": dr, "corpus_rate": cr, "ratio": ratio_val,
                    "direction": "high",
                    "reason": "原书「%s」为 0/千字，稿子达 %.2f/千字" % (p, dr),
                })
            elif cr > 0 and dr >= 2.5 * cr and dr >= 5.0:
                alerts.append({
                    "punct": p, "draft_rate": dr, "corpus_rate": cr, "ratio": ratio_val,
                    "direction": "high",
                    "reason": "「%s」密度 %.2f/千字 显著高于原书 %.2f/千字（%.1f 倍）" % (p, dr, cr, ratio_val),
                })
            elif draft_cjk >= 100 and cr >= 10.0 and dr <= 0.35 * cr:
                alerts.append({
                    "punct": p, "draft_rate": dr, "corpus_rate": cr, "ratio": ratio_val,
                    "direction": "low",
                    "reason": "「%s」密度 %.2f/千字 显著低于原书 %.2f/千字（%.2f 倍）" % (p, dr, cr, ratio_val),
                })
    return {"draft": draft_rates, "corpus": corpus_punct, "alerts": alerts}


def detect_ai_cliches(numbered_lines, corpus_ai_counts, corpus_chars):
    """严格语料拟合：仅当 corpus_count == 0 或 (corpus_count <= 1 且 < 0.2/10万字) 时报警。"""
    active = []
    denom = max(1, int(corpus_chars))
    for term in AI_CLICHE_CANDIDATES:
        cc = int(corpus_ai_counts.get(term, 0))
        per_100k = cc / denom * 100000.0
        if cc == 0 or (cc <= 1 and per_100k < 0.2):
            active.append((term, cc, round(per_100k, 3)))
    active.sort(key=lambda x: -len(x[0]))

    hits = []
    for lineno, line in numbered_lines:
        if not line.strip():
            continue
        occupied = []
        for term, cc, per_100k in active:
            start = 0
            while True:
                idx = line.find(term, start)
                if idx == -1:
                    break
                end = idx + len(term)
                if not any(idx >= a and end <= b for a, b in occupied):
                    occupied.append((idx, end))
                    hits.append({
                        "line": lineno,
                        "term": term,
                        "corpus_count": cc,
                        "corpus_per_100k": per_100k,
                        "start": idx,
                        "end": end,
                        "snippet": _snippet(line, idx, end),
                    })
                start = idx + 1
    hits.sort(key=lambda x: (x["line"], x["start"]))
    return hits


def detect_structural_probes(numbered_lines, corpus_mood_rate, exclude_names):
    # 1. 连续否定排比（同段 >=3 个连续否定分句，或连续 >=3 个以否定起头的短段）
    neg_par = []
    single_line_hit_lines = set()
    for lineno, line in numbered_lines:
        s = line.strip()
        if not s:
            continue
        clauses = [c.strip() for c in re.split(r"[。！？；，,、…]+", s) if c.strip()]
        run = 0
        best_run = 0
        for cl in clauses:
            if NEG_CLAUSE_RE.search(cl):
                run += 1
                if run > best_run:
                    best_run = run
            else:
                run = 0
        if best_run >= 3:
            single_line_hit_lines.add(lineno)
            neg_par.append({
                "line": lineno,
                "end_line": lineno,
                "count": best_run,
                "snippet": _snippet(s),
            })

    # 跨连续短段否定排比
    non_empty = [(ln, tx.strip()) for ln, tx in numbered_lines if tx.strip()]
    run_items = []
    for ln, tx in non_empty:
        head = tx[:10]
        if NEG_CLAUSE_RE.search(head) and len(tx) <= 60:
            run_items.append((ln, tx))
        else:
            if len(run_items) >= 3 and not all(x[0] in single_line_hit_lines for x in run_items):
                neg_par.append({
                    "line": run_items[0][0],
                    "end_line": run_items[-1][0],
                    "count": len(run_items),
                    "snippet": _snippet(" / ".join(x[1][:16] for x in run_items[:3])),
                })
            run_items = []
    if len(run_items) >= 3 and not all(x[0] in single_line_hit_lines for x in run_items):
        neg_par.append({
            "line": run_items[0][0],
            "end_line": run_items[-1][0],
            "count": len(run_items),
            "snippet": _snippet(" / ".join(x[1][:16] for x in run_items[:3])),
        })

    # 2. 否定转折套话
    neg_contrast = []
    for lineno, line in numbered_lines:
        if not line.strip():
            continue
        for m in NEG_CONTRAST_RE.finditer(line):
            neg_contrast.append({
                "line": lineno,
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _snippet(line, m.start(), m.end()),
            })

    # 3. 对白语气/情绪标签密度
    mood_hits = []
    draft_dlg_cnt = 0
    for lineno, line in numbered_lines:
        if not line.strip():
            continue
        for qm in C.iter_quotes(line):
            if len(re.sub(r"\s", "", qm.inner)) >= 2:
                draft_dlg_cnt += 1
        # 在原始行中定位对白引号区间，只扫描非对白区域以便精确定位起止偏移
        q_spans = [(qm.start, qm.end) for qm in C.iter_quotes(line) if not C.is_inline_quote(line, qm)]
        for m in MOOD_TAG_RE.finditer(line):
            if any(a <= m.start() < b for a, b in q_spans):
                continue
            mood_hits.append({
                "line": lineno,
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _snippet(line, m.start(), m.end()),
            })
    draft_mood_rate = len(mood_hits) / max(1, draft_dlg_cnt)
    elevated = bool(
        mood_hits and (
            (corpus_mood_rate <= 0.0)
            or (draft_mood_rate >= 2.0 * corpus_mood_rate and draft_mood_rate >= 0.05)
        )
    )

    # 4. 相邻句 2 字实词近距重复（排除人名与停用词）
    name_set = {nm for nm in (exclude_names or []) if len(nm) >= 2}
    sents = []
    for lineno, line in numbered_lines:
        s = line.strip()
        if not s:
            continue
        for seg in C.SENT_END.findall(s):
            seg = seg.strip()
            if len(re.sub(r"[^\u4e00-\u9fff]", "", seg)) >= 4:
                sents.append((lineno, seg))

    def _content_2grams(sent_txt):
        words = []
        seen = set()
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", sent_txt):
            for i in range(len(chunk) - 1):
                w = chunk[i:i + 2]
                if w in seen or w in REPEAT_2CHAR_STOP:
                    continue
                if w[0] in STOP or w[1] in STOP:
                    continue
                if w[0] == w[1]:
                    continue
                if any(w in nm or nm in w for nm in name_set):
                    continue
                seen.add(w)
                words.append(w)
        return words

    adj_repeats = []
    sent_words = [_content_2grams(seg) for _, seg in sents]
    for i in range(len(sents) - 1):
        ln1, seg1 = sents[i]
        ln2, seg2 = sents[i + 1]
        if ln2 - ln1 > 2:
            continue
        w2_set = set(sent_words[i + 1])
        shared = [w for w in sent_words[i] if w in w2_set]
        if not shared:
            continue
        # 若相邻 2-gram 重叠于同一词（如「会议」「议室」），只报首个避免刷屏
        reported_pos = []
        for w in shared:
            pos1 = seg1.find(w)
            if any(abs(pos1 - rp) <= 1 for rp in reported_pos):
                continue
            reported_pos.append(pos1)
            adj_repeats.append({
                "line": ln1,
                "next_line": ln2,
                "word": w,
                "snippet": _snippet(seg1[:24] + " / " + seg2[:24]),
            })

    return {
        "negation_parallelism": neg_par,
        "negation_contrast": neg_contrast,
        "dialogue_mood_tags": {
            "draft_hits": len(mood_hits),
            "draft_dialogues": draft_dlg_cnt,
            "draft_rate": round(draft_mood_rate, 4),
            "corpus_rate": round(float(corpus_mood_rate), 4),
            "elevated": elevated,
            "hits": mood_hits,
        },
        "adjacent_word_repeats": adj_repeats,
    }


# ── C1: 照抄 / 高重合检测 ──
def _find_maximal_cjk_matches(cjk_str, blob, min_len=10):
    """在 cjk_str 中找出所有在 blob 内精确出现且长度 >= min_len 的极大重合区间 [(s, e), ...]。"""
    if not blob or len(cjk_str) < min_len:
        return []
    L = len(cjk_str)
    intervals = []
    prev_end = -1
    for i in range(0, L - min_len + 1):
        probe_end = max(i + min_len, prev_end + 1)
        if probe_end > L:
            break
        if cjk_str[i:probe_end] not in blob:
            continue
        end = probe_end
        while end < L and cjk_str[i:end + 1] in blob:
            end += 1
        span = cjk_str[i:end]
        # 过滤纯叠字/模板噪声
        if len(set(span)) <= 2:
            prev_end = max(prev_end, end)
            continue
        if intervals and i <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((i, end))
        prev_end = max(prev_end, end)
    return intervals


def _cjk_span_to_raw_span(raw_line, cjk_start, cjk_end):
    """将纯汉字下标区间 [cjk_start, cjk_end) 映射回原始行字符区间 [raw_start, raw_end)。"""
    idx = 0
    raw_start = None
    raw_end = None
    for pos, ch in enumerate(raw_line):
        if "\u4e00" <= ch <= "\u9fff":
            if idx == cjk_start:
                raw_start = pos
            idx += 1
            if idx == cjk_end:
                raw_end = pos + 1
                break
    if raw_start is None:
        return 0, len(raw_line)
    if raw_end is None:
        raw_end = len(raw_line)
    return raw_start, raw_end


def detect_copy_paste(numbered_lines, examples_blob, bfull, min_len=10):
    hits = []
    for lineno, line in numbered_lines:
        s = line.strip()
        if not s:
            continue
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", line)
        if len(cjk) < min_len:
            continue
        covered = []
        if examples_blob:
            for cs, ce in _find_maximal_cjk_matches(cjk, examples_blob, min_len=min_len):
                rs, re_ = _cjk_span_to_raw_span(line, cs, ce)
                covered.append((cs, ce))
                hits.append({
                    "line": lineno,
                    "source": "例句",
                    "span": cjk[cs:ce],
                    "length": ce - cs,
                    "start": rs,
                    "end": re_,
                    "snippet": _snippet(line, rs, re_),
                })
        if bfull:
            for cs, ce in _find_maximal_cjk_matches(cjk, bfull, min_len=min_len):
                # 已被「例句」完全覆盖的不再重复报「原书」
                if any(cs >= a and ce <= b for a, b in covered):
                    continue
                rs, re_ = _cjk_span_to_raw_span(line, cs, ce)
                hits.append({
                    "line": lineno,
                    "source": "原书",
                    "span": cjk[cs:ce],
                    "length": ce - cs,
                    "start": rs,
                    "end": re_,
                    "snippet": _snippet(line, rs, re_),
                })
    hits.sort(key=lambda x: (x["line"], x["start"]))
    return hits


# ── C3 / D5: 0 频 n-gram 片段提取与合并 ──
def extract_zero_freq_spans(sent, bg, bfull):
    """提取句子中不在 bg 内的 4-gram（短句补查 3-gram），合并相邻/重叠窗口为可读中文子串。"""
    c = re.sub(r"[^\u4e00-\u9fff]", "", sent)
    L = len(c)
    if L < 3:
        return []
    intervals = []
    if L >= 4:
        for i in range(L - 3):
            if c[i:i + 4] not in bg:
                intervals.append((i, i + 4))
    else:
        if c not in bfull:
            intervals.append((0, L))
    # 若 4-5 字短句 4-gram 全在 bg 里，但内部 3-gram 仍可作为兜底不需额外报；
    # 若 L in (4, 5) 且没有 4-gram 命中，已说明全句在 bg 中。
    if not intervals:
        return []
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return [c[s:e] for s, e in merged]


# ── D2: 专名检测 + 窗口掩码 mrate ──
def detect_auto_proper_nouns(tparas, bfull):
    cand_cnt = {}
    for p in tparas:
        c0 = re.sub(r"[^\u4e00-\u9fff]", "", p)
        for n in (4, 3, 2):
            for i in range(len(c0) - n + 1):
                s = c0[i:i + n]
                cand_cnt[s] = cand_cnt.get(s, 0) + 1
    cand = [s for s, k in cand_cnt.items() if k >= 4 and s not in bfull]
    picked = []
    for s in sorted(set(cand), key=lambda x: (-len(x), x)):
        if not any(s in p or p in s for p in picked):
            picked.append(s)
    return picked


def mrate_masked(ps, bg, masked_terms=None):
    """计算 0 频 4-gram 探针率。当提供 masked_terms 时跳过任何与掩码位置重叠的 4-gram。"""
    cjk_terms = []
    if masked_terms:
        cjk_terms = sorted(
            {re.sub(r"[^\u4e00-\u9fff]", "", t) for t in masked_terms if len(re.sub(r"[^\u4e00-\u9fff]", "", t)) >= 2},
            key=len, reverse=True,
        )
    t_ = n_ = cl = skipped = 0
    for p in ps:
        c = re.sub(r"[^\u4e00-\u9fff]", "", p)
        mask = build_char_mask(c, cjk_terms) if cjk_terms else None
        bad = 0
        for i in range(len(c) - 3):
            if mask is not None and any(mask[i:i + 4]):
                skipped += 1
                continue
            t_ += 1
            if c[i:i + 4] not in bg:
                n_ += 1
                bad += 1
        if bad == 0:
            cl += 1
    return n_ / max(1, t_), cl, skipped


# ── POV 检测与参考段构建 ──
def infer_draft_pov(tparas):
    counts = {"first": 0, "third": 0, "neutral": 0}
    for p in tparas:
        counts[C.detect_para_pov(p)] += 1
    f_cnt, t_cnt = counts["first"], counts["third"]
    if (f_cnt >= 2 and f_cnt >= t_cnt * 1.5) or (f_cnt > 0 and t_cnt == 0):
        inferred = "first"
    elif (t_cnt >= 2 and t_cnt >= f_cnt * 1.5) or (t_cnt > 0 and f_cnt == 0):
        inferred = "third"
    else:
        inferred = "all"
    return inferred, counts


def _collect_segments(paras_src, ref_pattern=None, ref_req=None):
    segs, buf, cnt = [], [], 0
    if ref_pattern:
        for i, p in enumerate(paras_src):
            near = paras_src[max(0, i - 4):i + 5]
            if not (re.search(ref_pattern, p) or any(re.search(ref_pattern, q) for q in near)):
                buf = []
                cnt = 0
                continue
            if ref_req and ref_req not in "".join(near):
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
        for p in paras_src:
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
    return segs


def _build_draft_windows(tparas, target_lo=480, target_hi=620):
    """对长稿（>800 字）构建 ~550 字滑动窗口列表。"""
    n = len(tparas)
    if n == 0:
        return []
    wins = []
    i = 0
    while i < n:
        buf = []
        cnt = 0
        j = i
        while j < n:
            plen = len(re.sub(r"\s", "", tparas[j]))
            if buf and cnt >= target_lo and cnt + plen > target_hi + 80:
                break
            buf.append(tparas[j])
            cnt += plen
            j += 1
            if cnt >= target_lo:
                break
        if buf:
            wins.append(buf)
        if j >= n:
            break
        step = max(1, (j - i) // 2)
        i += step
    return wins


# ── 核心分析管线 ──
def analyze_draft(
    text,
    draft_name,
    model,
    index_data=None,
    *,
    ref_pattern=None,
    ref_req=None,
    pov="all",
    domain_terms=None,
    examples_blob=None,
    paste_min_len=10,
    top_z=10,
    quiet=False,
    cross_domain=False,
):
    index_data = index_data or {}
    text = text.lstrip("\ufeff")
    numbered_lines = _extract_lines_with_no(text)
    tparas = [ln.strip() for _, ln in numbered_lines if ln.strip()]

    paras_all = model["paras_all"]
    bg = model["bg"]
    base = model["base"]
    Bfull = model["Bfull"]
    MN, MD = model["MN"], model["MD"]
    CAL = model["CAL"]
    rd, rn = model["rd"], model["rn"]

    # ── 专名自动检测 + 用户领域词（严格窗口掩码，绝不重复首字替换）──
    picked = detect_auto_proper_nouns(tparas, Bfull)
    user_terms = list(domain_terms or [])
    masked_terms = sorted(set(picked) | set(user_terms), key=lambda x: (-len(x), x))
    booknames = list((index_data.get("台词") or {}).keys())

    # ── Layer 0: 基础排雷、黑名单、低频搭配、标点密度、语料拟合 AI 探针 ──
    garbled = detect_garbled_scripts(numbered_lines, model.get("corpus_scripts") or {})
    zero_hits = detect_zero_freq_hits(numbered_lines, index_data)
    low_collocs = detect_low_freq_collocs(numbered_lines, index_data)
    punct_eval = evaluate_punct_density(text, model.get("corpus_punct") or {})
    ai_cliches = detect_ai_cliches(
        numbered_lines,
        model.get("corpus_ai_counts") or {},
        model.get("corpus_chars") or len(Bfull),
    )
    struct_probes = detect_structural_probes(
        numbered_lines,
        model.get("corpus_mood_tag_rate", 0.0),
        exclude_names=set(booknames) | set(masked_terms),
    )
    mood_elevated_cnt = (
        struct_probes["dialogue_mood_tags"]["draft_hits"]
        if struct_probes["dialogue_mood_tags"]["elevated"] else 0
    )
    layer0_total = (
        len(garbled)
        + len(zero_hits)
        + len(low_collocs)
        + len(punct_eval["alerts"])
        + len(ai_cliches)
        + len(struct_probes["negation_parallelism"])
        + len(struct_probes["negation_contrast"])
        + mood_elevated_cnt
        + len(struct_probes["adjacent_word_repeats"])
    )

    # ── C1: 照抄 / 高重合检测 ──
    paste_hits = detect_copy_paste(numbered_lines, examples_blob, Bfull, min_len=paste_min_len)

    # ── 0 频探针（原始 & 窗口掩码）──
    mine, clean, _ = mrate_masked(tparas, bg, masked_terms=None)
    if masked_terms:
        mine_m, clean_m, skipped_4g = mrate_masked(tparas, bg, masked_terms=masked_terms)
    else:
        mine_m, clean_m, skipped_4g = mine, clean, 0

    # ── POV 分桶 + 门槛层参考段 ──
    inferred_pov, pov_counts = infer_draft_pov(tparas)
    effective_pov = inferred_pov if pov == "auto" else pov
    pov_fallback = False
    if effective_pov in ("first", "third"):
        pov_paras = [p for p in paras_all if C.detect_para_pov(p) == effective_pov]
        segs = _collect_segments(pov_paras, ref_pattern=ref_pattern, ref_req=ref_req)
        if len(segs) < 20:
            pov_fallback = True
            segs = _collect_segments(paras_all, ref_pattern=ref_pattern, ref_req=ref_req)
    else:
        segs = _collect_segments(paras_all, ref_pattern=ref_pattern, ref_req=ref_req)

    if not segs:
        segs = [paras_all[:]] if paras_all else [[""]]

    ref = [feats("\n\n".join(s), s) for s in segs]
    REF = {}
    for k in KW:
        v = sorted(r[k] for r in ref)
        REF[k] = (v[int(len(v) * .05)], v[int(len(v) * .95)])

    f = feats(text, tparas)
    is_long_draft = f["chars"] > 800
    checked_keys = SCALE_INVARIANT_KW if is_long_draft else KW
    outk = [k for k in checked_keys if not (REF[k][0] <= f[k] <= REF[k][1])]
    out_of_range = [
        {"key": k, "value": round(f[k], 4), "lo": round(REF[k][0], 4), "hi": round(REF[k][1], 4)}
        for k in outk
    ]

    # 长稿 ~550 字滑动窗口评估
    win_summary = None
    if is_long_draft:
        wins = _build_draft_windows(tparas)
        in_range_cnt = 0
        win_details = []
        for idx_w, wparas in enumerate(wins, 1):
            wf = feats("\n\n".join(wparas), wparas)
            w_out = [k for k in SCALE_INVARIANT_KW if not (REF[k][0] <= wf[k] <= REF[k][1])]
            ok = len(w_out) == 0
            if ok:
                in_range_cnt += 1
            win_details.append({
                "index": idx_w,
                "chars": wf["chars"],
                "paras": wf["paras"],
                "in_range": ok,
                "out_keys": w_out,
            })
        win_summary = {
            "total": len(wins),
            "in_range": in_range_cnt,
            "ratio": round(in_range_cnt / max(1, len(wins)), 3),
            "details": win_details,
        }

    # ── 结构层 ──
    struct_layer = None
    if not quiet:
        r_val = ratio(tparas)
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
        struct_layer = {
            "ratio": round(r_val, 4),
            "ref_median": round(ref_r[len(ref_r) // 2], 4) if ref_r else 1.0,
            "scrambled_median": round(scr_r[len(scr_r) // 2], 4) if scr_r else 1.0,
        }

    # ── 逐句层（追踪精确 1-based 行号 + 专名窗口掩码 + 0 频高亮）──
    dial_items = []
    narr_items = []
    for lineno, raw_line in numbered_lines:
        p = raw_line.strip()
        if not p:
            continue
        for qm in C.iter_quotes(raw_line):
            inner = qm.inner.strip()
            if len(re.sub(r"\s", "", inner)) >= 2:
                dial_items.append({"line": lineno, "kind": "dial", "text": inner})
        for ns in C.narr_sentences([p]):
            narr_items.append({"line": lineno, "kind": "narr", "text": ns})

    def score_items(items, M, tag):
        scored = []
        zs_raw = []
        zs_masked = []
        for it in items:
            s = it["text"]
            L = len(re.sub(r"\s", "", s))
            c = CAL.get((tag, lbk(L)))
            if not c:
                continue
            b_raw = bits(M, s)
            z_raw = (b_raw - c[0]) / c[1]
            zs_raw.append(z_raw)

            if masked_terms:
                cmask = build_char_mask(s, masked_terms)
                if cmask is not None:
                    b_m = bits(M, s, mask=cmask)
                    z_m = ((b_m - c[0]) / c[1]) if b_m is not None else None
                else:
                    z_m = z_raw
            else:
                z_m = z_raw
            if z_m is not None:
                zs_masked.append(z_m)

            scored.append({
                "line": it["line"],
                "kind": it["kind"],
                "text": s,
                "z": round(z_raw, 4),
                "z_masked": round(z_m, 4) if z_m is not None else None,
            })
        return scored, zs_raw, zs_masked

    pd_scored, zs_d, zs_dm = score_items(dial_items, MD, "d")
    pn_scored, zs_n, zs_nm = score_items(narr_items, MN, "n")

    all_scored = pd_scored + pn_scored
    all_scored.sort(key=lambda x: -x["z"])
    top_n_list = []
    for item in all_scored[:max(0, int(top_z))]:
        spans = extract_zero_freq_spans(item["text"], bg, Bfull)
        rec = dict(item)
        rec["zero_freq_spans"] = spans
        top_n_list.append(rec)

    # ── D3: 跨领域虚词骨架 & 标点轮廓相似度（每次运行都计算）──
    draft_cjk_len = len(re.sub(r"[^\u4e00-\u9fff]", "", text))
    d_fc, d_fr = compute_func_profile(text, draft_cjk_len)
    c_fc = model.get("corpus_func_counts") or {}
    c_fr = model.get("corpus_func_rates") or {}
    u_func = [float(d_fr.get(w, 0.0)) for w in FUNC_WORDS]
    v_func = [float(c_fr.get(w, 0.0)) for w in FUNC_WORDS]
    func_cos = cosine_sim(u_func, v_func)
    func_js = js_similarity(u_func, v_func)

    u_punct = [float(punct_eval["draft"].get(p, 0.0)) for p in PUNCT_KEYS]
    v_punct = [float(punct_eval["corpus"].get(p, 0.0)) for p in PUNCT_KEYS]
    punct_cos = cosine_sim(u_punct, v_punct)

    func_diffs = []
    for w in FUNC_WORDS:
        dr_w = float(d_fr.get(w, 0.0))
        cr_w = float(c_fr.get(w, 0.0))
        func_diffs.append((w, round(dr_w, 2), round(cr_w, 2), dr_w - cr_w))
    top_overused = [
        [w, dr_w, cr_w] for w, dr_w, cr_w, diff in sorted(func_diffs, key=lambda x: -x[3])[:5]
        if diff > 0.5
    ]
    top_underused = [
        [w, dr_w, cr_w] for w, dr_w, cr_w, diff in sorted(func_diffs, key=lambda x: x[3])[:5]
        if diff < -0.5
    ]

    z_dial = sum(zs_d) / max(1, len(zs_d))
    z_narr = sum(zs_n) / max(1, len(zs_n))
    z_dial_m = sum(zs_dm) / max(1, len(zs_dm)) if zs_dm else z_dial
    z_narr_m = sum(zs_nm) / max(1, len(zs_nm)) if zs_nm else z_narr

    report = {
        "file": draft_name,
        "basic": {k: round(v, 4) if isinstance(v, float) else v for k, v in f.items()},
        "pov": {
            "requested": pov,
            "effective": effective_pov,
            "draft_counts": pov_counts,
            "fallback": pov_fallback,
        },
        "threshold": {
            "ref_count": len(ref),
            "ref_pattern": ref_pattern,
            "is_long_draft": is_long_draft,
            "checked_keys": checked_keys,
            "ref_ranges": {k: [round(REF[k][0], 4), round(REF[k][1], 4)] for k in KW},
            "out_of_range": out_of_range,
            "windows": win_summary,
        },
        "structure": struct_layer,
        "layer0": {
            "garbled_scripts": garbled,
            "zero_freq_hits": zero_hits,
            "low_freq_collocs": low_collocs,
            "punct_density": punct_eval,
            "ai_cliches": ai_cliches,
            "structural_probes": struct_probes,
            "total_issues": layer0_total,
        },
        "paste": {
            "min_len": paste_min_len,
            "examples_checked": examples_blob is not None,
            "hits": paste_hits,
        },
        "proper_nouns": {
            "auto_picked": picked,
            "domain_terms": user_terms,
            "masked_terms": masked_terms,
        },
        "sentence_z": {
            "dial_count": len(zs_d),
            "dial_mean": round(z_dial, 4),
            "dial_book_mean": round(sum(rd) / max(1, len(rd)), 4),
            "narr_count": len(zs_n),
            "narr_mean": round(z_narr, 4),
            "narr_book_mean": round(sum(rn) / max(1, len(rn)), 4),
            "dial_masked_mean": round(z_dial_m, 4),
            "narr_masked_mean": round(z_narr_m, 4),
            "top_z_sentences": top_n_list,
        },
        "probe": {
            "novel_rate": round(mine, 6),
            "base_rate": round(base, 6),
            "ratio": round(mine / max(1e-9, base), 4),
            "clean_paras": clean,
            "total_paras": len(tparas),
            "masked_novel_rate": round(mine_m, 6),
            "masked_ratio": round(mine_m / max(1e-9, base), 4),
            "masked_clean_paras": clean_m,
            "masked_skipped_4grams": skipped_4g,
        },
        "cross_domain": {
            "enabled": bool(cross_domain),
            "func_cosine": round(func_cos, 4),
            "func_js_sim": round(func_js, 4),
            "punct_cosine": round(punct_cos, 4),
            "draft_func_total": sum(d_fc.values()),
            "corpus_func_total": sum(c_fc.values()),
            "top_overused_func": top_overused,
            "top_underused_func": top_underused,
        },
        "_all_scored": all_scored,
    }
    return report


def to_json_report(report):
    return {k: v for k, v in report.items() if not k.startswith("_")}


# ── 文本报告格式化 ──
def format_text_report(report, quiet=False):
    lines = []
    b = report["basic"]
    th = report["threshold"]
    pov = report["pov"]
    l0 = report["layer0"]
    paste = report["paste"]
    pn_info = report["proper_nouns"]
    sz = report["sentence_z"]
    pr = report["probe"]
    cd = report["cross_domain"]

    lines.append("=" * 74)
    lines.append(os.path.basename(report["file"]))
    lines.append(
        "字数 %d ｜ 段 %d ｜ 段长 %.1f ｜ 对白 %.1f%% ｜ 台词均长 %.1f ｜ ≤19 %.0f%% ｜ 20-24 %.0f%%" % (
            b["chars"], b["paras"], b["segLen"], b["dlg"] * 100, b["lineLen"],
            b["le19"] * 100, b["b2024"] * 100,
        )
    )
    pov_tag = ""
    if pov["requested"] != "all":
        fb = "（不足20段回退全书）" if pov["fallback"] else ""
        pov_tag = " ｜ 视角 %s→%s%s" % (pov["requested"], pov["effective"], fb)
    lines.append(
        "参考段 %d 个%s%s" % (
            th["ref_count"],
            ("（筛选 %s）" % th["ref_pattern"]) if th["ref_pattern"] else "（全书）",
            pov_tag,
        )
    )

    if th["out_of_range"]:
        out_str = " ".join(
            "%s=%.2f(应%.2f~%.2f)" % (x["key"], x["value"], x["lo"], x["hi"])
            for x in th["out_of_range"]
        )
        mode_hint = "（长稿>800字仅查尺度不变项）" if th["is_long_draft"] else ""
        lines.append("门槛%s：越界 %s" % (mode_hint, out_str))
    else:
        mode_hint = "（长稿>800字仅查尺度不变项）" if th["is_long_draft"] else ""
        lines.append("门槛%s：全部在范围内" % mode_hint)

    if th["windows"]:
        ws = th["windows"]
        lines.append(
            "长稿滑窗评估（~550 字）：%d/%d 个窗口全项落入参考区间（%.0f%%）" % (
                ws["in_range"], ws["total"], ws["ratio"] * 100,
            )
        )

    # Layer 0 摘要
    lines.append("── Layer 0 · 基础排雷、黑名单与语料拟合反 AI 探针（共 %d 项）──" % l0["total_issues"])
    if l0["garbled_scripts"]:
        lines.append("  [异常脚本/乱码] %d 处（原书该脚本 <5 字）：" % len(l0["garbled_scripts"]))
        for h in l0["garbled_scripts"][:10]:
            lines.append("    L%d  %s「%s」（原书 %d 字）  %s" % (
                h["line"], h["script_label"], h["chars"], h["corpus_count"], h["snippet"]
            ))
    if l0["zero_freq_hits"]:
        lines.append("  [零频词黑名单] %d 处：" % len(l0["zero_freq_hits"]))
        for h in l0["zero_freq_hits"][:10]:
            lines.append("    L%d  「%s」  %s" % (h["line"], h["term"], h["snippet"]))
    if l0["low_freq_collocs"]:
        lines.append("  [低频搭配 1~3 次] %d 处：" % len(l0["low_freq_collocs"]))
        for h in l0["low_freq_collocs"][:10]:
            alts = "、".join("%s(%d)" % (aw, af) for aw, af in h["alternatives"]) or "无更高频替代"
            lines.append("    L%d  「%s」(原书 %d 次，概念:%s) → 高频替代：%s" % (
                h["line"], h["term"], h["corpus_freq"], h["concept"], alts
            ))
    if l0["punct_density"]["alerts"]:
        lines.append("  [标点密度偏差] %d 项：" % len(l0["punct_density"]["alerts"]))
        for al in l0["punct_density"]["alerts"]:
            lines.append("    %s" % al["reason"])
    if l0["ai_cliches"]:
        lines.append("  [语料拟合 AI 套话] %d 处：" % len(l0["ai_cliches"]))
        for h in l0["ai_cliches"][:10]:
            lines.append("    L%d  「%s」（原书 %d 次，%.2f/10万字）  %s" % (
                h["line"], h["term"], h["corpus_count"], h["corpus_per_100k"], h["snippet"]
            ))
    sp = l0["structural_probes"]
    if sp["negation_parallelism"]:
        lines.append("  [连续否定排比] %d 处：" % len(sp["negation_parallelism"]))
        for h in sp["negation_parallelism"][:6]:
            ltag = "L%d" % h["line"] if h["line"] == h["end_line"] else "L%d-L%d" % (h["line"], h["end_line"])
            lines.append("    %s  连续 %d 句否定  %s" % (ltag, h["count"], h["snippet"]))
    if sp["negation_contrast"]:
        lines.append("  [否定转折套话] %d 处：" % len(sp["negation_contrast"]))
        for h in sp["negation_contrast"][:6]:
            lines.append("    L%d  「%s」  %s" % (h["line"], h["match"], h["snippet"]))
    mt = sp["dialogue_mood_tags"]
    if mt["elevated"]:
        lines.append(
            "  [对白语气标签偏密] %d 处（稿 %.3f/句 vs 原书 %.3f/句）：" % (
                mt["draft_hits"], mt["draft_rate"], mt["corpus_rate"]
            )
        )
        for h in mt["hits"][:6]:
            lines.append("    L%d  「%s」  %s" % (h["line"], h["match"], h["snippet"]))
    if sp["adjacent_word_repeats"]:
        lines.append("  [相邻句实词重复] %d 处：" % len(sp["adjacent_word_repeats"]))
        for h in sp["adjacent_word_repeats"][:8]:
            lines.append("    L%d→L%d  重复「%s」  %s" % (h["line"], h["next_line"], h["word"], h["snippet"]))
    if l0["total_issues"] == 0:
        lines.append("  全部通过（0 项告警）")

    # 照抄检测
    if paste["hits"]:
        lines.append("── 照抄 / 高重合检测（≥%d 汉字，共 %d 处）──" % (paste["min_len"], len(paste["hits"])))
        for h in paste["hits"][:12]:
            lines.append("  L%d  [%s %d字] 「%s」  %s" % (
                h["line"], h["source"], h["length"], h["span"], h["snippet"]
            ))

    # 结构层
    if report["structure"] is not None:
        st = report["structure"]
        lines.append(
            "结构比值(K=400)：%.2f   （同类书段中位 %.2f ｜ 打乱样本中位 %.2f）" % (
                st["ratio"], st["ref_median"], st["scrambled_median"]
            )
        )

    # 逐句层 & 0 频探针
    lines.append(
        "逐句 z：台词 %d 句 %+.2f（书自身 %+.2f）｜ 叙述 %d 句 %+.2f（书自身 %+.2f）" % (
            sz["dial_count"], sz["dial_mean"], sz["dial_book_mean"],
            sz["narr_count"], sz["narr_mean"], sz["narr_book_mean"],
        )
    )
    lines.append(
        "0 频探针：新造 4-gram %.1f%%（书留出基准 %.1f%%，%.2f 倍）｜ 0 新造句 %d/%d" % (
            pr["novel_rate"] * 100, pr["base_rate"] * 100, pr["ratio"],
            pr["clean_paras"], pr["total_paras"],
        )
    )

    if pn_info["masked_terms"] and not quiet:
        lines.append("疑似新专名/领域词（窗口掩码隔离）：%s" % "、".join(pn_info["masked_terms"]))
        lines.append(
            "窗口掩码隔离后：逐句 z 台词 %+.2f ｜ 叙述 %+.2f   0 频探针 %.1f%%（%.2f 倍，跳过 %d 个专名 4-gram）" % (
                sz["dial_masked_mean"], sz["narr_masked_mean"],
                pr["masked_novel_rate"] * 100, pr["masked_ratio"], pr["masked_skipped_4grams"],
            )
        )

    # 跨领域适配层
    if cd["enabled"]:
        lines.append("── 跨领域适配诊断（优先看虚词骨架、标点轮廓、Layer 0 与掩码 z）──")
        lines.append(
            "  虚词骨架相似度：Cosine %.3f ｜ JS相似度 %.3f   标点轮廓 Cosine %.3f" % (
                cd["func_cosine"], cd["func_js_sim"], cd["punct_cosine"]
            )
        )
        lines.append(
            "  掩码逐句 z：台词 %+.2f ｜ 叙述 %+.2f   Layer 0 告警：%d 项" % (
                sz["dial_masked_mean"], sz["narr_masked_mean"], l0["total_issues"]
            )
        )
        if cd["top_overused_func"]:
            lines.append("  偏多虚词(每万字 稿/书)：%s" % "、".join(
                "%s(%.1f/%.1f)" % (w, d, c) for w, d, c in cd["top_overused_func"]
            ))
        if cd["top_underused_func"]:
            lines.append("  偏少虚词(每万字 稿/书)：%s" % "、".join(
                "%s(%.1f/%.1f)" % (w, d, c) for w, d, c in cd["top_underused_func"]
            ))
    elif not quiet:
        lines.append(
            "虚词骨架相似度：Cosine %.3f ｜ JS %.3f ｜ 标点 Cosine %.3f" % (
                cd["func_cosine"], cd["func_js_sim"], cd["punct_cosine"]
            )
        )

    # Top-N 高 z 句 + 0 频高亮
    top_s = sz["top_z_sentences"]
    if top_s:
        lines.append("最贵 %d 句（按 z 降序，附 0 频片段）：" % len(top_s))
        for item in top_s:
            k_lbl = "台词" if item["kind"] == "dial" else "叙述"
            txt_show = item["text"][:120] + ("…" if len(item["text"]) > 120 else "")
            zf = item.get("zero_freq_spans") or []
            zf_str = ("  [0频: %s]" % " / ".join(zf)) if zf else ""
            lines.append("  L%-4d [%s] z=%+.2f  「%s」%s" % (
                item["line"], k_lbl, item["z"], txt_show, zf_str
            ))

    return "\n".join(lines)


# ── Markdown 《逐行精修清单》 ──
def format_revision_guide(report):
    b = report["basic"]
    l0 = report["layer0"]
    paste = report["paste"]
    sz = report["sentence_z"]
    pr = report["probe"]
    cd = report["cross_domain"]
    th = report["threshold"]

    by_line = {}

    def add(ln, item):
        by_line.setdefault(int(ln), []).append(item)

    for h in l0["garbled_scripts"]:
        add(h["line"], "**[异常脚本/%s]** `%s`（原书 %d 字）→ 删除或改写为正常中文。片段：`%s`" % (
            h["script_label"], h["chars"], h["corpus_count"], h["snippet"]
        ))
    for h in l0["zero_freq_hits"]:
        add(h["line"], "**[零频词黑名单]** `%s`（原书 0 次）→ 必须替换。片段：`%s`" % (
            h["term"], h["snippet"]
        ))
    for h in l0["low_freq_collocs"]:
        alts = " / ".join("`%s`(%d次)" % (aw, af) for aw, af in h["alternatives"]) or "参考原书常用说法"
        add(h["line"], "**[低频搭配·%s]** `%s`（原书仅 %d 次）→ 建议改用：%s。片段：`%s`" % (
            h["concept"], h["term"], h["corpus_freq"], alts, h["snippet"]
        ))
    for h in paste["hits"]:
        add(h["line"], "**[照抄预警·%s %d字]** `%s` → 必须重写句式与措辞，避免贴片。" % (
            h["source"], h["length"], h["span"]
        ))
    for h in l0["ai_cliches"]:
        add(h["line"], "**[AI 套话]** `%s`（原书 %d 次）→ 改用白描动作或具体细节。片段：`%s`" % (
            h["term"], h["corpus_count"], h["snippet"]
        ))
    sp = l0["structural_probes"]
    for h in sp["negation_parallelism"]:
        add(h["line"], "**[连续否定排比]** 连续 %d 句否定 → 拆散或改用正面动作推进。片段：`%s`" % (
            h["count"], h["snippet"]
        ))
    for h in sp["negation_contrast"]:
        add(h["line"], "**[否定转折套话]** `%s` → 直接写当下反应，去掉「没有X，只有/反而Y」模板。" % h["match"])
    if sp["dialogue_mood_tags"]["elevated"]:
        for h in sp["dialogue_mood_tags"]["hits"]:
            add(h["line"], "**[语气标签偏密]** `%s` → 删去声音形容，改用台词本身或动作表现情绪。" % h["match"])
    for h in sp["adjacent_word_repeats"]:
        add(h["line"], "**[相邻句重复词]** 与 L%d 重复 `%s` → 替换其中一处。片段：`%s`" % (
            h["next_line"], h["word"], h["snippet"]
        ))
    for item in sz["top_z_sentences"]:
        if item["z"] >= 0.8 or item.get("zero_freq_spans"):
            k_lbl = "台词" if item["kind"] == "dial" else "叙述"
            zf = "、".join("`%s`" % s for s in (item.get("zero_freq_spans") or [])) or "无明显 0 频段"
            add(item["line"], "**[高 z %s z=%+.2f]** 「%s」｜ 0 频片段：%s → 压平生造词与腔调。" % (
                k_lbl, item["z"], item["text"][:100], zf
            ))

    md = []
    md.append("# 《逐行精修清单》—— %s" % os.path.basename(report["file"]))
    md.append("")
    md.append("## 1. 体检总览")
    md.append("- 字数：**%d**（%d 段，对白占比 %.1f%%）" % (b["chars"], b["paras"], b["dlg"] * 100))
    md.append("- 逐句 z：台词 **%+.2f**（掩码 %+.2f）｜ 叙述 **%+.2f**（掩码 %+.2f）" % (
        sz["dial_mean"], sz["dial_masked_mean"], sz["narr_mean"], sz["narr_masked_mean"]
    ))
    md.append("- 0 频探针：**%.2f 倍**（掩码 %.2f 倍）｜ 虚词相似度：Cos %.3f / JS %.3f" % (
        pr["ratio"], pr["masked_ratio"], cd["func_cosine"], cd["func_js_sim"]
    ))
    md.append("- Layer 0 告警：**%d 项** ｜ 照抄/高重合：**%d 处**" % (l0["total_issues"], len(paste["hits"])))
    md.append("")

    md.append("## 2. 逐行待修项（按行号升序）")
    if not by_line:
        md.append("- 未检出逐行硬伤，可直接微调局部节奏。")
    else:
        for ln in sorted(by_line.keys()):
            md.append("### L%d" % ln)
            for desc in by_line[ln]:
                md.append("- %s" % desc)
    md.append("")

    md.append("## 3. 全局节奏与标点提醒")
    any_glob = False
    if th["out_of_range"]:
        any_glob = True
        md.append("- **门槛越界**：" + "；".join(
            "`%s`=%.2f（参考 %.2f~%.2f）" % (x["key"], x["value"], x["lo"], x["hi"])
            for x in th["out_of_range"]
        ))
    for al in l0["punct_density"]["alerts"]:
        any_glob = True
        md.append("- **标点偏差**：%s" % al["reason"])
    if sp["dialogue_mood_tags"]["elevated"]:
        any_glob = True
        md.append("- **语气标签密度过高**：稿 %.3f/句 vs 原书 %.3f/句" % (
            sp["dialogue_mood_tags"]["draft_rate"], sp["dialogue_mood_tags"]["corpus_rate"]
        ))
    if not any_glob:
        md.append("- 全局节奏、标点密度与对白结构均在参考区间内。")
    md.append("")

    # 短精修提示词骨架
    md.append("## 4. 精修提示词骨架（可直接复制给写作模型）")
    md.append("```markdown")
    md.append("请按以下逐行清单精修草稿，只改动列出的问题点，保持剧情、人物与段落顺序不变：")
    if l0["garbled_scripts"]:
        md.append("1. 清除异常外语/乱码字符：" + "、".join("L%d(%s)" % (h["line"], h["chars"]) for h in l0["garbled_scripts"][:6]))
    if l0["zero_freq_hits"]:
        md.append("2. 替换零频禁用词：" + "、".join(sorted({h["term"] for h in l0["zero_freq_hits"]})[:10]))
    if l0["low_freq_collocs"]:
        repl = []
        for h in l0["low_freq_collocs"][:6]:
            if h["alternatives"]:
                repl.append("%s→%s" % (h["term"], "/".join(aw for aw, _ in h["alternatives"][:2])))
        if repl:
            md.append("3. 低频搭配替换：" + "；".join(repl))
    if paste["hits"]:
        md.append("4. 重写以下与原书/例句高重合的片段（严禁照搬）：" + "、".join("L%d「%s」" % (h["line"], h["span"][:16]) for h in paste["hits"][:6]))
    if l0["ai_cliches"]:
        md.append("5. 去掉 AI 套话改写白描：" + "、".join(sorted({h["term"] for h in l0["ai_cliches"]})[:10]))
    if sz["top_z_sentences"]:
        top_lines = ["L%d(%s)" % (x["line"], "/".join(x["zero_freq_spans"][:2]) or ("z=%+.2f" % x["z"])) for x in sz["top_z_sentences"][:5]]
        md.append("6. 压平高 z 句生造表达：" + "；".join(top_lines))
    md.append("```")
    return "\n".join(md) + "\n"


# ── 多版本对比 (--diff) ──
def _issue_signature_set(report):
    sigs = set()
    l0 = report["layer0"]
    for h in l0["garbled_scripts"]:
        sigs.add(("乱码", h["chars"]))
    for h in l0["zero_freq_hits"]:
        sigs.add(("零频词", h["term"]))
    for h in l0["low_freq_collocs"]:
        sigs.add(("低频搭配", h["term"]))
    for h in l0["ai_cliches"]:
        sigs.add(("AI套话", h["term"]))
    for h in l0["structural_probes"]["negation_contrast"]:
        sigs.add(("否定转折", h["match"]))
    for h in l0["structural_probes"]["adjacent_word_repeats"]:
        sigs.add(("邻句重复", h["word"]))
    for al in l0["punct_density"]["alerts"]:
        sigs.add(("标点偏差", al["punct"]))
    for h in report["paste"]["hits"]:
        sigs.add(("照抄", h["span"][:14]))
    return sigs


def format_diff_report(reports):
    names = [os.path.basename(r["file"]) for r in reports]
    lines = ["# 多版本验收对比", ""]
    header = "| 指标 | " + " | ".join(names) + " | 变化 (末-首) |"
    sep = "| --- | " + " | ".join(["---:"] * len(reports)) + " | ---: |"
    lines.extend([header, sep])

    def _row(label, getter, fmt="%.2f", delta_fmt="%+.2f"):
        vals = [getter(r) for r in reports]
        dv = vals[-1] - vals[0]
        cells = [fmt % v for v in vals]
        lines.append("| %s | %s | %s |" % (label, " | ".join(cells), delta_fmt % dv))

    _row("字数", lambda r: r["basic"]["chars"], "%d", "%+d")
    _row("台词 z", lambda r: r["sentence_z"]["dial_mean"], "%+.2f", "%+.2f")
    _row("叙述 z", lambda r: r["sentence_z"]["narr_mean"], "%+.2f", "%+.2f")
    _row("掩码台词 z", lambda r: r["sentence_z"]["dial_masked_mean"], "%+.2f", "%+.2f")
    _row("掩码叙述 z", lambda r: r["sentence_z"]["narr_masked_mean"], "%+.2f", "%+.2f")
    _row("0 频探针倍数", lambda r: r["probe"]["ratio"], "%.2f", "%+.2f")
    _row("掩码探针倍数", lambda r: r["probe"]["masked_ratio"], "%.2f", "%+.2f")
    _row("虚词 Cosine", lambda r: r["cross_domain"]["func_cosine"], "%.3f", "%+.3f")
    _row("虚词 JS 相似度", lambda r: r["cross_domain"]["func_js_sim"], "%.3f", "%+.3f")
    _row("标点 Cosine", lambda r: r["cross_domain"]["punct_cosine"], "%.3f", "%+.3f")
    _row("Layer 0 告警", lambda r: r["layer0"]["total_issues"], "%d", "%+d")
    _row("照抄命中", lambda r: len(r["paste"]["hits"]), "%d", "%+d")

    first, last = reports[0], reports[-1]
    s0, s1 = _issue_signature_set(first), _issue_signature_set(last)
    fixed = sorted(s0 - s1)
    added = sorted(s1 - s0)
    lines.append("")
    lines.append("## Layer 0 / 照抄问题变化（%s → %s）" % (names[0], names[-1]))
    lines.append("- 已消除（%d 项）：%s" % (
        len(fixed),
        "、".join("%s:%s" % (k, v) for k, v in fixed[:15]) if fixed else "无",
    ))
    lines.append("- 新引入（%d 项）：%s" % (
        len(added),
        "、".join("%s:%s" % (k, v) for k, v in added[:15]) if added else "无",
    ))

    # 句级变化：首版高 z 句已移除/改写 vs 末版新出现的高 z 句
    first_sents = {x["text"]: x["z"] for x in first.get("_all_scored", [])}
    last_sents = {x["text"]: x["z"] for x in last.get("_all_scored", [])}
    improved = sorted(
        [(z, txt) for txt, z in first_sents.items() if txt not in last_sents],
        key=lambda x: -x[0],
    )[:5]
    worsened = sorted(
        [(z, txt) for txt, z in last_sents.items() if txt not in first_sents],
        key=lambda x: -x[0],
    )[:5]
    lines.append("")
    lines.append("## 句级显著变化")
    if improved:
        lines.append("- 已改写/移除的原高 z 句 Top %d：" % len(improved))
        for z, txt in improved:
            lines.append("  - z=%+.2f 「%s」" % (z, txt[:70]))
    if worsened:
        lines.append("- 末版新增高 z 句 Top %d：" % len(worsened))
        for z, txt in worsened:
            lines.append("  - z=%+.2f 「%s」" % (z, txt[:70]))
    return "\n".join(lines) + "\n"


# ── JSONL 历史记录 (--log-history) ──
def append_history_jsonl(path, report):
    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": report["file"],
        "chars": report["basic"]["chars"],
        "z_dial": report["sentence_z"]["dial_mean"],
        "z_narr": report["sentence_z"]["narr_mean"],
        "z_dial_masked": report["sentence_z"]["dial_masked_mean"],
        "z_narr_masked": report["sentence_z"]["narr_masked_mean"],
        "probe_ratio": report["probe"]["ratio"],
        "probe_ratio_masked": report["probe"]["masked_ratio"],
        "func_sim": report["cross_domain"]["func_js_sim"],
        "layer0_issues": report["layer0"]["total_issues"],
        "paste_hits": len(report["paste"]["hits"]),
    }
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


# ── 单文件自包含 HTML 热力图报告 (--html) ──
def _svg_grouped_bars(title, labels, draft_vals, corpus_vals, width=540, height=220):
    max_v = max([1.0] + list(draft_vals) + list(corpus_vals))
    pad_l, pad_r, pad_t, pad_b = 42, 20, 34, 38
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = max(1, len(labels))
    grp_w = plot_w / n
    bar_w = min(22, grp_w * 0.34)

    parts = [
        '<svg viewBox="0 0 %d %d" width="100%%" height="%d" xmlns="http://www.w3.org/2000/svg">' % (width, height, height),
        '<rect x="0" y="0" width="%d" height="%d" rx="8" fill="#fafbfc" stroke="#e2e8f0"/>' % (width, height),
        '<text x="16" y="22" font-size="13" font-weight="600" fill="#1e293b">%s</text>' % html.escape(title),
        '<rect x="%d" y="11" width="10" height="10" fill="#3b82f6" rx="2"/>' % (width - 135),
        '<text x="%d" y="20" font-size="11" fill="#475569">稿子</text>' % (width - 120),
        '<rect x="%d" y="11" width="10" height="10" fill="#94a3b8" rx="2"/>' % (width - 75),
        '<text x="%d" y="20" font-size="11" fill="#475569">原书</text>' % (width - 60),
    ]
    # 基线
    y0 = pad_t + plot_h
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#cbd5e1"/>' % (pad_l, y0, width - pad_r, y0))
    for i, lbl in enumerate(labels):
        cx = pad_l + (i + 0.5) * grp_w
        dv, cv = draft_vals[i], corpus_vals[i]
        dh = (dv / max_v) * plot_h
        ch = (cv / max_v) * plot_h
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#3b82f6" rx="2"><title>%s 稿子: %.2f</title></rect>' % (
            cx - bar_w - 2, y0 - dh, bar_w, max(1.0, dh), html.escape(lbl), dv
        ))
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#94a3b8" rx="2"><title>%s 原书: %.2f</title></rect>' % (
            cx + 2, y0 - ch, bar_w, max(1.0, ch), html.escape(lbl), cv
        ))
        parts.append('<text x="%.1f" y="%d" font-size="11" text-anchor="middle" fill="#334155">%s</text>' % (
            cx, y0 + 18, html.escape(lbl)
        ))
    parts.append("</svg>")
    return "".join(parts)


def render_html_report(report, raw_text):
    b = report["basic"]
    l0 = report["layer0"]
    paste = report["paste"]
    sz = report["sentence_z"]
    pr = report["probe"]
    cd = report["cross_domain"]

    # 按行收集所有高亮区间 (priority, start, end, css_class, tip)
    # priority 越大覆盖等级越高：1=highz, 2=layer0(purple), 3=paste(yellow), 4=garbled(darkred)
    line_anns = {}

    def add_ann(ln, prio, s, e, cls, tip):
        if e <= s:
            return
        line_anns.setdefault(int(ln), []).append((prio, s, e, cls, tip))

    raw_lines = raw_text.lstrip("\ufeff").split("\n")

    # 高 z 句标注（Top-N 且 z >= 0.5 或前 5 句）
    for idx_t, item in enumerate(sz["top_z_sentences"]):
        if item["z"] < 0.5 and idx_t >= 5:
            continue
        ln = item["line"]
        if 1 <= ln <= len(raw_lines):
            src_line = raw_lines[ln - 1]
            pos = src_line.find(item["text"])
            if pos != -1:
                zf = "、".join(item.get("zero_freq_spans") or []) or "无"
                tip = "高z句 (z=%+.2f) | 0频片段: %s" % (item["z"], zf)
                add_ann(ln, 1, pos, pos + len(item["text"]), "hl-highz", tip)

    # Layer 0 紫标：零频词、低频搭配、AI 套话、结构探针
    for h in l0["zero_freq_hits"]:
        add_ann(h["line"], 2, h["start"], h["end"], "hl-l0",
                "零频黑名单: 「%s」（原书 0 次）" % h["term"])
    for h in l0["low_freq_collocs"]:
        alts = " / ".join("%s(%d)" % (aw, af) for aw, af in h["alternatives"]) or "无"
        add_ann(h["line"], 2, h["start"], h["end"], "hl-l0",
                "低频搭配「%s」(原书%d次, %s) | 高频替代: %s" % (h["term"], h["corpus_freq"], h["concept"], alts))
    for h in l0["ai_cliches"]:
        add_ann(h["line"], 2, h["start"], h["end"], "hl-l0",
                "AI套话「%s」(原书%d次)" % (h["term"], h["corpus_count"]))
    for h in l0["structural_probes"]["negation_contrast"]:
        add_ann(h["line"], 2, h["start"], h["end"], "hl-l0",
                "否定转折套话: 「%s」" % h["match"])
    if l0["structural_probes"]["dialogue_mood_tags"]["elevated"]:
        for h in l0["structural_probes"]["dialogue_mood_tags"]["hits"]:
            add_ann(h["line"], 2, h["start"], h["end"], "hl-l0",
                    "对白语气标签偏密: 「%s」" % h["match"])

    # 照抄黄标
    for h in paste["hits"]:
        add_ann(h["line"], 3, h["start"], h["end"], "hl-paste",
                "照抄/高重合 [%s %d字]: 「%s」" % (h["source"], h["length"], h["span"]))

    # 异常脚本深红标
    for h in l0["garbled_scripts"]:
        add_ann(h["line"], 4, h["start"], h["end"], "hl-garbled",
                "异常脚本(%s): 「%s」(原书%d字)" % (h["script_label"], h["chars"], h["corpus_count"]))

    # 逐行渲染无交叉 HTML
    rendered_paras = []
    for lineno, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        anns = line_anns.get(lineno)
        if not anns:
            body_html = html.escape(line)
        else:
            L = len(line)
            best_prio = [0] * L
            best_cls = [""] * L
            tips_per_ch = [[] for _ in range(L)]
            for prio, s, e, cls, tip in anns:
                s = max(0, min(L, s))
                e = max(0, min(L, e))
                for i in range(s, e):
                    if tip not in tips_per_ch[i]:
                        tips_per_ch[i].append(tip)
                    if prio >= best_prio[i]:
                        best_prio[i] = prio
                        best_cls[i] = cls
            # 合并相同 (cls, tuple(tips)) 的连续字符
            segs_html = []
            i = 0
            while i < L:
                cls = best_cls[i]
                tp = tuple(tips_per_ch[i])
                j = i + 1
                while j < L and best_cls[j] == cls and tuple(tips_per_ch[j]) == tp:
                    j += 1
                chunk = html.escape(line[i:j])
                if cls:
                    tip_attr = html.escape(" ; ".join(tp), quote=True)
                    segs_html.append('<span class="%s" title="%s">%s</span>' % (cls, tip_attr, chunk))
                else:
                    segs_html.append(chunk)
                i = j
            body_html = "".join(segs_html)
        rendered_paras.append(
            '<div class="pline"><span class="lno">L%d</span><span class="ltxt">%s</span></div>' % (lineno, body_html)
        )

    # SVG 图表
    svg_punct = _svg_grouped_bars(
        "每千字标点密度对比（稿子 vs 原书）",
        PUNCT_KEYS,
        [float(l0["punct_density"]["draft"].get(p, 0.0)) for p in PUNCT_KEYS],
        [float(l0["punct_density"]["corpus"].get(p, 0.0)) for p in PUNCT_KEYS],
    )
    ref_r = report["threshold"]["ref_ranges"]
    mid = lambda k: 0.5 * (ref_r[k][0] + ref_r[k][1])
    svg_style = _svg_grouped_bars(
        "核心节奏与跨领域相似度（百分比 %）",
        ["对白占比", "≤19短句", "虚词Cos", "虚词JS", "标点Cos"],
        [
            b["dlg"] * 100.0,
            b["le19"] * 100.0,
            cd["func_cosine"] * 100.0,
            cd["func_js_sim"] * 100.0,
            cd["punct_cosine"] * 100.0,
        ],
        [
            mid("dlg") * 100.0,
            mid("le19") * 100.0,
            100.0,
            100.0,
            100.0,
        ],
    )

    cards = [
        ("字数 / 段落", "%d 字" % b["chars"], "%d 段 ｜ 对白 %.1f%%" % (b["paras"], b["dlg"] * 100)),
        ("逐句 z（台词 / 叙述）", "%+.2f / %+.2f" % (sz["dial_mean"], sz["narr_mean"]),
         "掩码后 %+.2f / %+.2f" % (sz["dial_masked_mean"], sz["narr_masked_mean"])),
        ("0 频探针倍数", "%.2f×" % pr["ratio"],
         "掩码 %.2f× ｜ 新造 %.1f%%" % (pr["masked_ratio"], pr["novel_rate"] * 100)),
        ("虚词骨架相似度", "JS %.3f" % cd["func_js_sim"],
         "Cos %.3f ｜ 标点 %.3f" % (cd["func_cosine"], cd["punct_cosine"])),
        ("Layer 0 告警", "%d 项" % l0["total_issues"],
         "乱码 %d ｜ 零频 %d ｜ 搭配 %d ｜ AI %d" % (
             len(l0["garbled_scripts"]), len(l0["zero_freq_hits"]),
             len(l0["low_freq_collocs"]), len(l0["ai_cliches"]),
         )),
        ("照抄 / 高重合", "%d 处" % len(paste["hits"]),
         "阈值 ≥%d 汉字" % paste["min_len"]),
    ]
    cards_html = "".join(
        '<div class="card"><div class="ck">%s</div><div class="cv">%s</div><div class="cs">%s</div></div>' % (
            html.escape(k), html.escape(v), html.escape(sub)
        )
        for k, v, sub in cards
    )

    title_str = "Style-Fit 验收热力图 — %s" % os.path.basename(report["file"])
    doc = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f8fafc; color: #0f172a; line-height: 1.7; }}
  .wrap {{ max-width: 1120px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  h2 {{ font-size: 16px; margin: 24px 0 10px; color: #1e293b; border-left: 4px solid #3b82f6; padding-left: 10px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 18px; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }}
  .ck {{ font-size: 12px; color: #64748b; }}
  .cv {{ font-size: 20px; font-weight: 700; margin: 4px 0; color: #0f172a; }}
  .cs {{ font-size: 12px; color: #475569; }}
  .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 14px; margin-bottom: 18px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; font-size: 13px; }}
  .lg-item {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ display: inline-block; width: 14px; height: 14px; border-radius: 3px; }}
  .draft-box {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; }}
  .pline {{ display: flex; gap: 12px; padding: 4px 0; border-bottom: 1px dashed #f1f5f9; }}
  .lno {{ min-width: 44px; color: #94a3b8; font-family: ui-monospace, Consolas, monospace; font-size: 12px; text-align: right; user-select: none; padding-top: 2px; }}
  .ltxt {{ flex: 1; white-space: pre-wrap; word-break: break-word; font-size: 15px; }}
  .hl-highz {{ background: #ffe0e0; border-bottom: 2px solid #e06060; border-radius: 2px; padding: 0 1px; cursor: help; }}
  .hl-paste {{ background: #fff5cc; border-bottom: 2px solid #d4a017; border-radius: 2px; padding: 0 1px; cursor: help; }}
  .hl-l0 {{ background: #efe0ff; border-bottom: 2px solid #8e44ad; border-radius: 2px; padding: 0 1px; cursor: help; }}
  .hl-garbled {{ background: #8b0000; color: #ffffff; border-radius: 2px; padding: 0 3px; font-weight: 600; cursor: help; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <div class="cards">{cards}</div>
  <div class="charts">
    <div>{svg_punct}</div>
    <div>{svg_style}</div>
  </div>
  <h2>全文热力图（悬停高亮片段查看详情与高频替代）</h2>
  <div class="legend">
    <span class="lg-item"><span class="swatch" style="background:#ffe0e0;border:1px solid #e06060;"></span>高 z 句</span>
    <span class="lg-item"><span class="swatch" style="background:#fff5cc;border:1px solid #d4a017;"></span>照抄/高重合片段</span>
    <span class="lg-item"><span class="swatch" style="background:#efe0ff;border:1px solid #8e44ad;"></span>零频词 / 低频搭配 / AI 探针</span>
    <span class="lg-item"><span class="swatch" style="background:#8b0000;"></span>异常脚本/乱码</span>
  </div>
  <div class="draft-box">
    {paras}
  </div>
</div>
</body>
</html>
""".format(
        title=html.escape(title_str),
        cards=cards_html,
        svg_punct=svg_punct,
        svg_style=svg_style,
        paras="\n    ".join(rendered_paras),
    )
    return doc


# ── CLI 入口 ──
def build_arg_parser():
    ap = argparse.ArgumentParser(description="style-fit 验收工具（含 Layer 0、照抄检测、掩码隔离与热力图）")
    ap.add_argument("--text", default=None, help="待验收草稿路径（--prewarm 或 --diff 时可省略）")
    ap.add_argument("--corpus", required=True, help="语料文件/目录路径")
    ap.add_argument("--out", required=True, help="缓存与 index.json 目录")
    ap.add_argument("--ref-pattern", default=None, help="参考区间按场景切，例 '(猫|尾巴|摸头)'；不填用全书")
    ap.add_argument("--ref-req", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-cache", action="store_true", help="忽略并重建 verify 模型缓存")
    ap.add_argument("--examples", default=None, help="例子集路径（如 work/out/例子.txt），用于照抄检测")
    ap.add_argument("--paste-min-len", type=int, default=10, help="照抄/高重合最小连续汉字数（默认 10）")
    ap.add_argument("--domain-terms", default=None, help="领域专名：逗号分隔词表或换行分隔 txt 文件路径")
    ap.add_argument("--cross-domain", action="store_true", help="跨领域适配诊断模式")
    ap.add_argument("--pov", choices=["auto", "first", "third", "all"], default="all",
                    help="参考段视角分桶：auto/first/third/all（默认 all）")
    ap.add_argument("--top-z", type=int, default=10, help="展示最贵 Top-N 句（默认 10）")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="输出机器可读 JSON；不带路径或传 - 输出到 stdout，传路径则写入文件")
    ap.add_argument("--prewarm", action="store_true", help="仅预热构建 verify_cache.pkl 后退出")
    ap.add_argument("--guide", nargs="?", const="-", default=None,
                    help="生成 Markdown《逐行精修清单》；传路径写入文件，否则打印到 stdout")
    ap.add_argument("--diff", nargs="+", default=None,
                    help="多版本对比：传入 2 个及以上草稿路径，同进程复用缓存模型输出对比表")
    ap.add_argument("--log-history", nargs="?", const="AUTO", default=None,
                    help="追加一行 JSONL 验收历史；不填路径默认写到 <out>/verify_history.jsonl")
    ap.add_argument("--html", default=None, help="生成单文件自包含 HTML 热力图报告路径")
    return ap


def main(argv=None):
    textio.ensure_utf8_stdio()
    ap = build_arg_parser()
    a = ap.parse_args(argv)

    if not a.prewarm and not a.diff and not a.text:
        ap.error("需要提供 --text（除非使用 --prewarm 或 --diff）")

    try:
        model = load_or_build_model(a.corpus, a.out, no_cache=a.no_cache)
    except ValueError as e:
        print(str(e))
        sys.exit(1)

    if a.prewarm:
        status = "命中缓存" if model.get("cache_hit") else "已构建缓存"
        print("预热完成（%s）：%s（%d 汉字，%d 段）" % (
            status, model["cache_path"], model["corpus_chars"], len(model["paras_all"])
        ))
        return

    index_data = load_index_data(a.out)
    domain_terms = load_domain_terms(a.domain_terms)
    examples_blob = load_examples_blob(a.examples) if a.examples else None

    if a.diff:
        if len(a.diff) < 2:
            ap.error("--diff 至少需要 2 个文件")
        reports = []
        for fpath in a.diff:
            raw_txt = textio.read_text(fpath)
            rep = analyze_draft(
                raw_txt, fpath, model, index_data,
                ref_pattern=a.ref_pattern, ref_req=a.ref_req,
                pov=a.pov, domain_terms=domain_terms,
                examples_blob=examples_blob, paste_min_len=a.paste_min_len,
                top_z=a.top_z, quiet=a.quiet, cross_domain=a.cross_domain,
            )
            reports.append(rep)
        diff_md = format_diff_report(reports)
        if a.json == "-":
            print(json.dumps({"diff": [to_json_report(r) for r in reports]}, ensure_ascii=False, indent=2))
        else:
            if a.json:
                textio.write_json(a.json, {"diff": [to_json_report(r) for r in reports]})
            print(diff_md)
        return

    raw_text = textio.read_text(a.text)
    report = analyze_draft(
        raw_text, a.text, model, index_data,
        ref_pattern=a.ref_pattern, ref_req=a.ref_req,
        pov=a.pov, domain_terms=domain_terms,
        examples_blob=examples_blob, paste_min_len=a.paste_min_len,
        top_z=a.top_z, quiet=a.quiet, cross_domain=a.cross_domain,
    )

    if a.log_history is not None:
        hist_path = os.path.join(a.out, "verify_history.jsonl") if a.log_history == "AUTO" else a.log_history
        append_history_jsonl(hist_path, report)

    if a.html:
        html_doc = render_html_report(report, raw_text)
        textio.write_text(a.html, html_doc)

    if a.guide and a.guide != "-":
        textio.write_text(a.guide, format_revision_guide(report))

    if a.json == "-":
        print(json.dumps(to_json_report(report), ensure_ascii=False, indent=2))
        return

    if a.json:
        textio.write_json(a.json, to_json_report(report))

    print(format_text_report(report, quiet=a.quiet))
    if a.guide == "-":
        print("")
        print(format_revision_guide(report))


if __name__ == "__main__":
    main()
