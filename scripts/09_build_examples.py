#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 9 · 生成例子集（文风语料）。

  python scripts/09_build_examples.py
  python scripts/09_build_examples.py --out out/例子.txt

内容全部来自语料与索引，不自由发挥：叙述腔样本、内心独白、对白回合、
台词分角色 + 语音档案、亲密写法、名场面、描写套路、语音分期、搭配表·雷区、用词表。

「使用禁令」一节从 config/bans.md 读（没有就留占位符），
它专门拦模型最容易犯的错：照抄开篇特殊写法、写本书没有的设定、把分期角色写死。
"""
import os
import re
import sys
import glob
import argparse
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio, corpus as C      # noqa: E402


def quantile_len(items, k=8):
    v = sorted(items, key=len)
    if not v:
        return []
    n = len(v)
    return list(dict.fromkeys(v[min(n - 1, int(n * i / k))] for i in range(1, k)))


def load_index(cfg):
    p = os.path.join(cfg["paths"]["cache"], cfg.get("name") or "book", "index.json")
    if not os.path.isfile(p):
        raise SystemExit("没有索引：%s\n先跑 scripts/07_stylefit_index.py" % p)
    return textio.read_json(p, {})


def read_pairs(cfg):
    d = textio.read_json(os.path.join(ROOT, "attrib.json"), [])
    return [(x["who"], x["text"]) for x in (d or []) if isinstance(x, dict)
            and x.get("who") and x.get("text")]


SELF_WORDS = ["我", "咱", "俺", "老子", "本大爷", "本人", "人家", "在下", "鄙人",
              "妾身", "本机", "老夫", "小女子"]


def voice_profiles(pairs, top=24):
    by = defaultdict(list)
    for w, t in pairs:
        by[w].append(t)
    out = {}
    for who, ls in sorted(by.items(), key=lambda kv: -len(kv[1]))[:top]:
        base = len(ls)
        self_cnt = {w: sum(t.count(w) for t in ls) for w in SELF_WORDS}
        self_cnt = {w: n for w, n in self_cnt.items() if n > 0}
        tail = Counter()
        for t in ls:
            s = re.sub(r"[。！？…~\s]+$", "", t)
            if 0 < len(s) <= 8:
                tail[s[-2:]] += 1
        out[who] = {
            "n": base,
            "均长": round(sum(len(t) for t in ls) / base, 1),
            "自称": sorted(self_cnt.items(), key=lambda kv: -kv[1])[:4],
            "口癖": [x for x in tail.most_common(5) if x[1] >= 3],
            "问号率": round(sum(1 for t in ls if "？" in t) / base, 3),
            "感叹率": round(sum(1 for t in ls if "！" in t) / base, 3),
            "省略率": round(sum(1 for t in ls if "…" in t) / base, 3),
        }
    return out


def address_table(pairs, names, top=16):
    """谁怎么称呼谁：目标名在各说话人台词里的出现次数。"""
    out = {}
    for nm in names:
        callers = Counter()
        for w, t in pairs:
            if w != nm and nm in t:
                callers[w] += t.count(nm)
        if callers:
            out[nm] = callers.most_common(5)
    return out


def stage_table(pairs, periods=3, top=8):
    """语音分期：同一角色的台词按出现顺序均分成 N 期，看条数与均长怎么变。

    出现顺序 ≈ 剧情顺序（归属是从头到尾扫原文抓的）。
    """
    bywho = defaultdict(list)
    for w, t in pairs:
        bywho[w].append(t)
    res = {}
    for who, ls in sorted(bywho.items(), key=lambda kv: -len(kv[1]))[:top]:
        if len(ls) < periods * 20:
            continue
        n = len(ls)
        parts = []
        for i in range(periods):
            seg = ls[int(n * i / periods):int(n * (i + 1) / periods)]
            if not seg:
                parts.append("—")
                continue
            parts.append("%d条/均%.0f字" % (len(seg), sum(len(x) for x in seg) / len(seg)))
        res[who] = parts
    return res


def scene_cards(cfg, k=3):
    """名场面：从每卷纪要里抽「名场面与关键台词」小节的逐字引文。"""
    out, seen = [], set()
    for f in sorted(glob.glob(os.path.join(cfg["paths"]["notes"], "vol", "*.md"))):
        t = textio.read_text(f)
        grab, buf = False, []
        for ln in t.split("\n"):
            if ln.startswith("## "):
                grab = any(x in ln for x in ("名场面", "关键台词"))
                continue
            if not grab:
                continue
            for q in C.QUOTE.findall(ln):
                q = q.strip()
                if 6 <= len(q) <= 120 and q not in seen:
                    seen.add(q)
                    buf.append(q)
        if buf:
            out.append((os.path.basename(f), buf[:8]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    cfg = project.load(a.config)
    X = load_index(cfg)
    pairs = read_pairs(cfg)
    names = cfg.get("names") or []
    raw, _ = C.load_corpus(cfg["paths"]["chunks"])
    paras = C.paragraphs(raw)
    narr = C.narr_sentences(paras)

    L = []
    P = L.append
    P("# %s · 典型例子集" % (cfg.get("name") or ""))
    P("（文风语料 ｜ 全部摘自原文 ｜ 供仿写与提示词取用）")
    P("")
    P("配套：`整书总结.md`（设定/剧情/状态/IF）。本文只负责文风与语感。")
    P("阅读顺序建议：先看【一 使用禁令】避免踩雷，再扫【二 文风速览】定口径，")
    P("然后按需查【四 台词分角色】【六 名场面】【九 搭配表·雷区】。")
    P("")
    P("=" * 60)

    # ── 一 使用禁令 ──
    bans = ""
    bp = os.path.join(ROOT, "config", "bans.md")
    if os.path.isfile(bp):
        bans = textio.read_text(bp).strip()
    P("## 一 · 使用禁令 / 常见误区（写之前必读）")
    P("")
    if bans:
        P(bans)
    else:
        P("<!-- 在 config/bans.md 里写本书的硬禁区。典型三条： -->")
        P("1. 别默认照抄开篇的特殊写法（书信体/序章独白），那是一次性的，不是全书常规叙述。")
        P("2. 别写本书没有的设定（例：本书没有系统面板，禁止出现【检测到…】这类提示）。")
        P("3. 说话方式分期的角色，不能一路写成同一种腔调（见【八 语音分期】）。")
    P("")

    # ── 二 文风速览 ──
    st = X.get("统计", {})
    P("## 二 · 文风速览（统计靶）")
    P("")
    P("- 语料规模：%s" % (X.get("meta", {}).get("chars", "?")))
    P("- 台词均长：%s ｜ 中位：%s ｜ ≤19 字占比：%s" % (
        st.get("台词均长"), st.get("台词中位长度"), st.get("台词≤19字占比")))
    P("- 每千字标点：%s" % st.get("每千字标点"))
    P("- 台词量前 12 人：%s" % st.get("说话人台词量"))
    P("- 叙述句数：%s" % st.get("叙述句数"))
    P("")
    P("> 对标时必须按同类场景切区间，不能拿全书硬套（详见 docs/PITFALLS.md）。")
    P("")

    # ── 三 叙述腔 ──
    P("## 三 · 叙述腔（%s）" % ("第一人称" if cfg.get("person") == "first" else "第三人称"))
    P("")
    short = [s for s in narr if len(s) <= 22]
    mid = [s for s in narr if 22 < len(s) <= 50]
    long = [s for s in narr if len(s) > 50]
    for tag, pool in (("短句", short), ("中句", mid), ("长句", long)):
        P("**%s**" % tag)
        for s in quantile_len(pool, 5):
            P("- %s" % s)
        P("")

    # ── 四 内心独白 ──
    P("## 四 · 内心独白 / 吐槽（混在叙述里，不带引号的那种）")
    P("")
    inner = [s for s in narr if re.search(r"(心想|心里想|觉得|暗自|不禁|寻思|盘算|默念|吐槽)", s)]
    for s in quantile_len(inner, 8):
        P("- %s" % s)
    P("")

    # ── 五 对白回合 ──
    P("## 五 · 对白回合片段（引号与叙述的呼吸节奏）")
    P("")
    for sc, d in (X.get("场景") or {}).items():
        P("### 场景：%s" % sc)
        for s in d.get("样本", [])[:3]:
            P("```")
            P(s.strip())
            P("```")
        P("")

    # ── 六 台词分角色 + 语音档案 ──
    P("## 六 · 台词分角色 + 语音档案")
    P("")
    masks = voice_profiles(pairs)
    addrs = address_table(pairs, names)
    for who, d in masks.items():
        P("### %s" % who)
        P("- 台词 %d 条 ｜ 均长 %.1f ｜ 问号率 %.0f%% ｜ 感叹率 %.0f%% ｜ 省略率 %.0f%%" % (
            d["n"], d["均长"], d["问号率"] * 100, d["感叹率"] * 100, d["省略率"] * 100))
        if d["自称"]:
            P("- 自称：%s" % " ｜ ".join("%s %d" % x for x in d["自称"]))
        if addrs.get(who):
            P("- 谁常提他：%s" % " ｜ ".join("%s %d" % x for x in addrs[who]))
        if d["口癖"]:
            P("- 句尾口癖：%s" % " ｜ ".join("%s %d" % x for x in d["口癖"]))
        bs = (X.get("台词") or {}).get(who) or {}
        for func, b in list(bs.items())[:4]:
            P("- **%s**（%d 条，中位 %d 字）" % (func, b["n"], b["中位长度"]))
            for s in b["样本"][:4]:
                P("  - %s" % s)
        P("")

    # ── 七 亲密 / 感情场景写法 ──
    P("## 七 · 亲密与感情场景写法")
    P("")
    d = (X.get("场景") or {}).get("亲密")
    if d:
        P("原文片段（%d 段）：" % d["n"])
        for s in d.get("样本", [])[:3]:
            P("```")
            P(s.strip())
            P("```")
    P("")
    P("场景词典（这类场景书里实际用的词 · 次数）：")
    for k, dd in (X.get("场景词典") or {}).items():
        hot = sorted([(w, n) for w, n in dd.items() if n > 0], key=lambda x: -x[1])[:12]
        dead = [w for w, n in dd.items() if n == 0]
        P("- **%s**：%s" % (k, " ｜ ".join("%s %d" % x for x in hot)))
        if dead:
            P("  - 禁用：%s" % "、".join(dead))
    P("")

    # ── 八 名场面 ──
    P("## 八 · 名场面原文摘录")
    P("")
    for fn, qs in scene_cards(cfg):
        P("### %s" % fn)
        for q in qs:
            P("- “%s”" % q)
        P("")
    if not scene_cards(cfg):
        P("<!-- notes/vol/*.md 里没有「名场面与关键台词」小节，检查二层模板 -->")
        P("")

    # ── 九 描写套路 ──
    P("## 九 · 描写套路（这个意图书里怎么写）")
    P("")
    for name, d in (X.get("描写") or {}).items():
        P("### %s（原书 %d 处）" % (name, d["n"]))
        for s in d.get("样本", []):
            P("- %s" % s)
        P("")

    # ── 十 语音分期 ──
    P("## 十 · 语音分期（角色说话随时间/年龄变化）")
    P("")
    tab = stage_table(pairs)
    if tab:
        P("| 角色 | 前期 | 中期 | 后期 |")
        P("|---|---|---|---|")
        for who, parts in tab.items():
            P("| %s | %s |" % (who, " | ".join(parts)))
    else:
        P("<!-- 没算出分期数据。若本书有角色说话方式随剧情变化（结巴→流利、幼年→成年），"
          "在这里手工列出来，并标明分界章节。 -->")
    P("")

    # ── 十一 搭配表 · 雷区 ──
    P("## 十一 · 搭配表 · 典型 vs 雷区")
    P("")
    P("> 写手很少造词，但经常配错。下表左列是概念，右列是书里实际的配法及次数，")
    P("> 标「禁用」的是全书 0 次——出现就是 AI 味。")
    P("")
    for c, dd in (X.get("搭配") or {}).items():
        P("### %s" % c)
        for w, n in sorted(dd.items(), key=lambda kv: -kv[1]):
            mark = "  ❌ 禁用" if n == 0 else ("  ⚠ 慎用" if n <= 3 else "")
            P("- %s  %d%s" % (w, n, mark))
        P("")
    z = X.get("零频词") or []
    P("### 零频黑名单（全书 0 次）")
    P("")
    P("、".join(z) if z else "（空）")
    P("")

    # ── 十二 用词表 ──
    P("## 十二 · 用词表与场景高频词")
    P("")
    for c, dd in (X.get("用词") or {}).items():
        P("- **%s**：%s" % (c, " ｜ ".join(
            "%s %d%s" % (w, n, "❌" if n == 0 else "") for w, n in dd.items())))
    P("")

    out = a.out or os.path.join(cfg["paths"]["out"], "例子.txt")
    textio.write_text(out, "\n".join(L).strip() + "\n")
    n = len("\n".join(L))
    print("例子集：%d 字 ｜ 角色档案 %d 个 ｜ 搭配概念 %d ｜ 零频词 %d" % (
        n, len(masks), len(X.get("搭配") or {}), len(X.get("零频词") or [])))
    print("→ %s" % out)
    print("下一步：python scripts/10_build_summary.py")


if __name__ == "__main__":
    main()
