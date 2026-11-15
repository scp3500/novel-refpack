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
    d = textio.read_json(project.artifact(cfg, "attrib.json"), [])
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


def stage_table(pairs, periods=3, top=30):
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
    for _, f in project.vol_notes(cfg):
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
            out.append((os.path.basename(f), buf[:30]))
    return out


def stride_pick(items, k):
    """按全书均匀采样 k 条（避免只取开头）。"""
    n = len(items)
    if n <= k:
        return list(items)
    return [items[int(i * n / k)] for i in range(k)]


TOPICS = [
    ("A · 登陆空间 / 剧本与游戏机制",
     r"(登陆空间|剧本|副本|结算|评分|通关|队伍|队长|系统提示|物品栏|装备栏|菜单|商城|称号|声望|灵力值|经验值)"),
    ("B · 战斗、技能与受伤",
     r"(技能|灵力|称号|伤害|秒杀|闪避|格挡|斩|拳|开火|爆炸|伤口|鲜血|倒地)"),
    ("C · 推理、赌局与算计",
     r"(推理|线索|证据|嫌疑|凶手|赌局|概率|筹码|下注|赔率|算计|条件|交易)"),
    ("D · 恐惧惊悚与副本氛围",
     r"(恐怖|诡异|阴森|血腥|尖叫|黑暗|阴冷|毛骨悚然|惨白|尸体|死寂)"),
    ("E · 搞笑吐槽与日常",
     r"(吐槽|坑爹|无语|白眼|中二|干笑|什么鬼|开什么玩笑|吃了|喝了)"),
]


def topic_digests(paras, topics=None, per=12, win=3):
    """按主题从原文抽大段片段，均匀铺到全书。"""
    out = []
    for title, pat in (topics or TOPICS):
        rx = re.compile(pat)
        hits = [i for i, p in enumerate(paras) if len(p) >= 30 and rx.search(p)]
        picked, seen = [], set()
        for i in stride_pick(hits, per):
            seg = "\n".join(paras[max(0, i - 1):i + win]).strip()
            key = seg[:60]
            if key in seen:
                continue
            seen.add(key)
            picked.append(seg)
        out.append((title, picked))
    return out


def arc_base(t):
    t = re.sub(r"^第[0-9０-９零〇一二三四五六七八九十百千两]+章\s*", "", t or "")
    return re.split(r"[（(【]", t)[0].strip()


def load_topics(cfg):
    p = os.path.join(ROOT, "config", "stylefit", "topics.json")
    if os.path.isfile(p):
        d = textio.read_json(p, {}) or {}
        items = [(k, v) for k, v in d.items() if not k.startswith("_") and isinstance(v, str)]
        if items:
            return items
    return TOPICS


def arc_digests(cfg, min_ch=3, win=2):
    """按剧本 / 副本切语料：同一个作者写不同世界时的腔调差异。

    剧本名从章标题「第NNN章 XXXX（一）」的前缀取；
    同一剧本被主线插断时会拆成多段，按各自连续区间切片后再合并，避免把中间主线卷进来。
    """
    secs = textio.read_json(os.path.join(cfg["paths"]["raw"], "sections.json"), []) or []
    raw = textio.read_text(os.path.join(cfg["paths"]["raw"], "_all.txt"))
    offs = [s.get("offset") for s in secs]
    if not secs or any(o is None for o in offs):
        return []
    bases = [arc_base(s.get("title")) for s in secs]
    cnt = Counter(b for b in bases if b)
    runs, i = [], 0
    while i < len(secs):
        b = bases[i]
        if b and cnt[b] >= min_ch:
            j = i
            while j < len(secs) and bases[j] == b:
                j += 1
            if j - i >= min_ch:
                runs.append((b, i, j, j - i))
            i = j
        else:
            i += 1
    merged = {}
    for b, i, j, n in runs:
        if b not in merged:
            merged[b] = {"runs": [], "chapters": 0}
        merged[b]["runs"].append((i, j))
        merged[b]["chapters"] += n
    items = sorted(merged.items(), key=lambda kv: -kv[1]["chapters"])
    out = []
    for name, info in items:
        ch = info["chapters"]
        segs_body = []
        total_chars = 0
        for r_start, r_end in info["runs"]:
            start = offs[r_start]
            end = offs[r_end] if r_end < len(secs) else len(raw)
            total_chars += max(0, end - start)
            segs_body.append([p.strip() for p in C.paragraphs(raw[start:end])])
        per = 5 if ch >= 20 else (4 if ch >= 8 else 3)
        # 在各连续段内部采样，防止跨段滑窗越界到无关章节
        cand_passages = []
        for body in segs_body:
            for n, p in enumerate(body):
                if len(p) >= 30:
                    passage = "\n".join(x for x in body[max(0, n - 1):n + win] if x).strip()
                    if passage:
                        cand_passages.append(passage)
        samples, seen = [], set()
        for passage in stride_pick(cand_passages, per):
            key = passage[:50]
            if key in seen:
                continue
            seen.add(key)
            samples.append(passage)
        first_idx = info["runs"][0][0]
        last_idx = info["runs"][-1][1]
        out.append({"name": name, "first": secs[first_idx].get("title"),
                    "last": secs[last_idx - 1].get("title"), "chapters": ch,
                    "chars": total_chars, "samples": samples})
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
    P("阅读顺序建议：先扇【一 文风速览】定口径，写对白查【五 台词分角色】【四 对白回合】，")
    P("写动作翻【八 描写套路】【十三 专项摘录】，写特定剧本查【十四 分剧本语料】，收尾前用【十五 使用禁令】自检。")
    P("")
    P("=" * 60)

    # ── 一 文风速览 ──
    st = X.get("统计", {})
    P("## 一 · 文风速览（统计靶）")
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

    # ── 二 叙述腔 ──
    P("## 二 · 叙述腔（%s）" % ("第一人称" if cfg.get("person") == "first" else "第三人称"))
    P("")
    short = [s for s in narr if len(s) <= 22]
    mid = [s for s in narr if 22 < len(s) <= 50]
    long = [s for s in narr if len(s) > 50]
    for tag, pool in (("超短句", [s for s in narr if len(s) <= 12]),
                      ("短句", short), ("中句", mid), ("长句", long)):
        P("**%s**" % tag)
        for s in quantile_len(pool, 10):
            P("- %s" % s)
        P("")

    # ── 三 内心独白 ──
    P("## 三 · 内心独白 / 吐槽（混在叙述里，不带引号的那种）")
    P("")
    inner = [s for s in narr if re.search(r"(心想|心里想|觉得|暗自|不禁|寻思|盘算|默念|吐槽)", s)]
    for s in quantile_len(inner, 20):
        P("- %s" % s)
    P("")
    P("**单句成段短句（原文里独立一行，带吐槽 / 自嘲味）：**")
    P("")
    one = [p.strip() for p in paras if 4 <= len(p.strip()) <= 26 and not C.QUOTE.search(p)]
    for s in stride_pick(one, 36):
        P("- %s" % s)
    P("")

    # ── 四 对白回合 ──
    P("## 四 · 对白回合片段（引号与叙述的呼吸节奏）")
    P("")
    for sc, d in (X.get("场景") or {}).items():
        P("### 场景：%s" % sc)
        for s in d.get("样本", [])[:4]:
            P("```")
            P(s.strip())
            P("```")
        P("")

    # ── 五 台词分角色 + 语音档案 ──
    P("## 五 · 台词分角色 + 语音档案")
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
        for func, b in list(bs.items())[:8]:
            P("- **%s**（%d 条，中位 %d 字）" % (func, b["n"], b["中位长度"]))
            for s in b["样本"][:8]:
                P("  - %s" % s)
        P("")

    # ── 六 亲密 / 感情场景写法 ──
    P("## 六 · 亲密与感情场景写法")
    P("")
    d = (X.get("场景") or {}).get("亲密")
    if d:
        P("原文片段（%d 段）：" % d["n"])
        for s in d.get("样本", [])[:4]:
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

    # ── 七 名场面 ──
    P("## 七 · 名场面原文摘录")
    P("")
    for fn, qs in scene_cards(cfg):
        P("### %s" % fn)
        for q in qs:
            P("- “%s”" % q)
        P("")
    if not scene_cards(cfg):
        P("<!-- notes/vol/*.md 里没有「名场面与关键台词」小节，检查二层模板 -->")
        P("")

    # ── 八 描写套路 ──
    P("## 八 · 描写套路（这个意图书里怎么写）")
    P("")
    for name, d in (X.get("描写") or {}).items():
        P("### %s（原书 %d 处）" % (name, d["n"]))
        for s in d.get("样本", []):
            P("- %s" % s)
        P("")

    # ── 九 语音分期 ──
    P("## 九 · 语音分期（角色说话随时间/年龄变化）")
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

    # ── 十 搭配表 · 雷区 ──
    P("## 十 · 搭配表 · 典型 vs 雷区")
    P("")
    P("> 写手很少造词，但经常配错。下表左列是概念，右列是书里实际的配法及次数，")
    P("> 标「禁用」的是全书 0 次——出现就是 AI 味。")
    P("")
    for c, dd in (X.get("搭配") or {}).items():
        P("### %s" % c)
        for w, n in sorted(dd.items(), key=lambda kv: -kv[1]):
            mark = "  【禁用】" if n == 0 else ("  【慎用】" if n <= 3 else "")
            P("- %s  %d%s" % (w, n, mark))
        P("")
    z = X.get("零频词") or []
    P("### 零频黑名单（全书 0 次）")
    P("")
    P("、".join(z) if z else "（空）")
    P("")

    # ── 十一 用词表 ──
    P("## 十一 · 用词表与场景高频词")
    P("")
    for c, dd in (X.get("用词") or {}).items():
        P("- **%s**：%s" % (c, " ｜ ".join(
            "%s %d%s" % (w, n, "【禁用】" if n == 0 else "") for w, n in dd.items())))
    P("")

    # ── 十二 章节标题样例 ──
    P("## 十二 · 章节标题样例（写番外 / IF 时沿用这套句式）")
    P("")
    secs = textio.read_json(os.path.join(cfg["paths"]["raw"], "sections.json"), []) or []
    all_t = [s.get("title") for s in secs if s.get("title")]
    named = [t for t in all_t if re.match(r"^第[0-9０-９零〇一二三四五六七八九十百千两]+[章节回话卷]\s+\S", t)]
    P("（全书 %d 章，其中 %d 章原文就没给标题、只写「第 N 章」，此处只列有标题的 %d 个；"
      "写番外时不要给这些无名章补造标题。）" % (
          len(all_t), len(all_t) - len(named), len(named)))
    P("")
    for t in stride_pick(named, 60):
        P("- %s" % t)
    P("")

    # ── 十三 专项摘录 ──
    P("## 十三 · 专项摘录（按主题的大段原文，写同类场景前先扫一遍）")
    P("")
    for title, segs in topic_digests(paras, topics=load_topics(cfg)):
        P("### %s" % title)
        P("")
        for s in segs:
            P("```")
            P(s)
            P("```")
        P("")

    # ── 十四 分剧本语料 ──
    P("## 十四 · 分剧本语料（同一作者写不同世界时的腔调差异）")
    P("")
    P("> 每个剧本／副本是一个独立世界，腔调与用词不同。写哪个本的同人，先翻对应那一节。")
    P("")
    arcs = arc_digests(cfg)
    for arc in arcs:
        P("### 剧本：%s（%s → %s，%d 章 ≈ %d 字）" % (
            arc["name"], arc["first"], arc["last"], arc["chapters"], arc["chars"]))
        P("")
        for s in arc["samples"]:
            P("```")
            P(s)
            P("```")
        P("")

    # ── 十五 使用禁令（放最后，当自检清单用）──
    bans = ""
    bp = project.resolve_bans_file(cfg)
    if bp:
        bans = textio.read_text(bp).strip()
    P("## 十五 · 使用禁令 / 常见误区（写完自检用）")
    P("")
    P("> 定稿前扫一遍。这一节拦的是模型最容易犯的错：照抄开篇特殊写法、写本书没有的设定、把分期角色写死。")
    P("")
    if bans:
        P(bans)
    else:
        P("<!-- 在 config/bans.md 里写本书的硬禁区。 -->")
    P("")

    out = a.out or os.path.join(cfg["paths"]["out"], "例子.txt")
    textio.write_text(out, "\n".join(L).strip() + "\n")
    n = len("\n".join(L))
    print("例子集：%d 字 ｜ 角色档案 %d 个 ｜ 搭配概念 %d ｜ 剧本 %d ｜ 零频词 %d" % (
        n, len(masks), len(X.get("搭配") or {}), len(arcs), len(X.get("零频词") or [])))
    print("→ %s" % out)
    print("下一步：python scripts/10_build_summary.py")


if __name__ == "__main__":
    main()
