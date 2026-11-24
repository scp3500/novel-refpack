#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 9 · 生成例子集（文风语料）。

  python scripts/09_build_examples.py
  python scripts/09_build_examples.py --out out/例子.txt
  python scripts/09_build_examples.py --preset compact
  python scripts/09_build_examples.py --style-only --anonymize --kb 60

内容全部来自语料与索引，不自由发挥：叙述腔样本、内心独白、细粒度笔法与镜头细节、
对白回合、台词分角色/语体、亲密写法、名场面、描写套路、语音分期、搭配表·雷区、用词表。

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
from lib import project, textio, corpus as C, budget      # noqa: E402


def _head4(s):
    return re.sub(r"\s", "", s)[:4]


def _head8(s):
    return re.sub(r"[^\u4e00-\u9fff]", "", s)[:8]


def stride_pick(items, k):
    """按全书均匀采样 k 条（避免只取开头）。"""
    if k <= 0:
        return []
    n = len(items)
    if n <= k:
        return list(items)
    return [items[int(i * n / k)] for i in range(k)]


def dedup_stride_pick(items, k, head_n=4):
    """全书均匀步长采样，并过滤句首前 head_n 字重复项。"""
    if k <= 0 or not items:
        return []
    seen_full, seen_head, uniq = set(), set(), []
    for it in items:
        s = it.strip()
        if not s:
            continue
        h = re.sub(r"\s", "", s)[:head_n]
        if s in seen_full or (h and h in seen_head):
            continue
        seen_full.add(s)
        if h:
            seen_head.add(h)
        uniq.append(s)
    return stride_pick(uniq, k)


def quantile_len(items, k=8):
    v = sorted(items, key=len)
    if not v or k <= 0:
        return []
    n = len(v)
    picked = [v[min(n - 1, int(n * i / k))] for i in range(1, k + 1)]
    out, seen_full, seen_head = [], set(), set()
    for s in picked:
        h = _head4(s)
        if s in seen_full or (h and h in seen_head):
            continue
        seen_full.add(s)
        if h:
            seen_head.add(h)
        out.append(s)
    return out


def pick_narr_tier(items, k):
    """长度分级 + 全书均匀步长 + 句首去重，拒绝重复句式。"""
    if k <= 0 or not items:
        return []
    v = sorted(items, key=len)
    # 先按长度均衡取候选，再在原序里均匀步长采样并去重，兼顾长度跨度与全书覆盖
    if len(v) > k * 4:
        # 从原文序列中均匀取 4k 个，再按句首去重后 stride_pick k 个
        pool = stride_pick(items, k * 4)
        res = dedup_stride_pick(pool, k, head_n=4)
        if len(res) >= k:
            return res[:k]
    return dedup_stride_pick(items, k, head_n=4)


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


def voice_profiles(pairs, top=24, self_words=None):
    by = defaultdict(list)
    for w, t in pairs:
        by[w].append(t)
    sw = self_words or SELF_WORDS
    out = {}
    for who, ls in sorted(by.items(), key=lambda kv: -len(kv[1]))[:top]:
        base = len(ls)
        self_cnt = {w: sum(t.count(w) for t in ls) for w in sw}
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
    """语音分期：同一角色的台词按出现顺序均分成 N 期，看条数与均长怎么变。"""
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


TOPICS = [
    ("A · 系统 / 机制与规则",
     r"(系统提示|物品栏|装备栏|菜单|商城|称号|属性|经验值|等级|副本|结算|评分|通关|队伍|队长)"),
    ("B · 战斗、技能与受伤",
     r"(技能|伤害|秒杀|闪避|格挡|斩|拳|开火|爆炸|伤口|鲜血|倒地|挥剑|突刺)"),
    ("C · 推理、赌局与算计",
     r"(推理|线索|证据|嫌疑|凶手|赌局|概率|筹码|下注|赔率|算计|条件|交易)"),
    ("D · 恐惧惊悚与氛围",
     r"(恐怖|诡异|阴森|血腥|尖叫|黑暗|阴冷|毛骨悚然|惨白|尸体|死寂)"),
    ("E · 搞笑吐槽与日常",
     r"(吐槽|坑爹|无语|白眼|干笑|什么鬼|开什么玩笑|吃了|喝了)"),
]

STYLE_ONLY_TOPICS = [
    ("A · 动作推进与肢体细节",
     r"(转身|低头|抬起|伸手|握紧|推开|站起|停下|走过去|后退|加快脚步|拉住|放开|靠在)"),
    ("B · 环境氛围与光影五感",
     r"(阳光|夕阳|月光|灯光|阴影|夜色|寂静|微风|雨声|脚步声|空气|寒意|窗外|街灯)"),
    ("C · 交涉对峙与试探",
     r"(沉默片刻|反问|试探|条件|理由|解释|妥协|拒绝|打断|停顿|平静地|冷静)"),
    ("D · 日常互动与轻快交流",
     r"(苦笑|干笑|叹了口气|顺口|开玩笑|笑出声|咖啡|晚饭|茶|回家|路上|周末)"),
    ("E · 情绪起伏与内心转折",
     r"(犹豫|迟疑|心想|觉得|心里|心跳|发紧|沉默|苦涩|自嘲|不安|松了口气|忍不住)"),
]


def _clip_around_match(text, rx, max_chars=0):
    if not max_chars or len(text) <= max_chars:
        return text
    m = rx.search(text) if rx else None
    center = m.start() if m else len(text) // 2
    half = max_chars // 2
    lo = max(0, center - half)
    hi = min(len(text), lo + max_chars)
    if hi - lo < max_chars:
        lo = max(0, hi - max_chars)
    if lo > 0:
        b = text.find("。", lo)
        if b != -1 and b < center:
            lo = b + 1
    if hi < len(text):
        b = text.rfind("。", lo, hi)
        if b != -1 and b > center:
            hi = b + 1
    return ("……" if lo > 0 else "") + text[lo:hi].strip() + ("……" if hi < len(text) else "")


def topic_digests(paras, topics=None, per=12, win=3, max_chars=0):
    """按主题从原文抽大段片段，均匀铺到全书。"""
    out = []
    for title, pat in (topics or TOPICS):
        rx = re.compile(pat)
        hits = [i for i, p in enumerate(paras) if len(p) >= 30 and rx.search(p)]
        picked, seen = [], set()
        for i in stride_pick(hits, per):
            seg = "\n".join(paras[max(0, i - 1):i + win]).strip()
            seg = _clip_around_match(seg, rx, max_chars=max_chars)
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


def load_craft_rules(cfg):
    sf_dir = project.resolve_stylefit_dir(cfg)
    p = os.path.join(sf_dir, "craft_rules.json")
    if os.path.isfile(p):
        return textio.read_json(p, {}) or {}
    return {}


def load_topics(cfg, style_only=False):
    sf_dir = project.resolve_stylefit_dir(cfg)
    p = os.path.join(sf_dir, "topics.json")
    if os.path.isfile(p):
        d = textio.read_json(p, {}) or {}
        items = [(k, v) for k, v in d.items() if not k.startswith("_") and isinstance(v, str)]
        if items:
            return items
    if style_only:
        return STYLE_ONLY_TOPICS
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


def extract_craft_details(paras, raw_text, per_cat=12):
    """当旧 index.json 没有「笔法细节」字段时，在内存里从 paras 实时提取 5 类细节。"""
    has_quote_re = re.compile("[" + "".join(re.escape(c) for c in C.QUOTE_OPEN + C.QUOTE_CLOSE) + "]")
    action_words_re = re.compile(
        r"(?:伸手|伸出|拿|拉|推|走|看|转身|低头|抬起|放下|握|按|推开|坐下|起身|站起|迈步|扣|抓|递|接过|抬眼|抬手|点头|摇头)"
    )
    sensory_re = re.compile(
        r"(?:阳光|月光|灯光|阴影|夜色|光线|昏暗|微风|风声|雨声|脚步声|敲门声|响起|传来|冰凉|滚烫|温热|粗糙|刺骨|窗外|街上|角落|空气|气味|寂静|回荡)"
    )
    transition_re = re.compile(
        r"^(?:片刻之后|没过多久|很快|过了许久|半晌|第二天|次日|夜幕降临|天色渐暗|黄昏|清晨|傍晚|半小时后|等到|回到|离开|走进|来到)"
        r"|(?:片刻之后|没过多久|第二天|夜幕降临|半小时后|等到.{2,10}的时候)"
    )

    chapter_first_paras = set()
    expect_first = False
    for ln in (raw_text or "").split("\n"):
        st = ln.strip()
        if not st:
            continue
        if st.startswith("#") or C.CHAP.match(st):
            expect_first = True
            continue
        if re.fullmatch(r"[-—=*~·\s　]{3,}", st):
            continue
        if expect_first:
            chapter_first_paras.add(st)
            expect_first = False

    craft_action, craft_sensory, craft_trans, craft_dlg_act, craft_short = [], [], [], [], []
    for p in paras:
        plen = len(p)
        has_q = bool(has_quote_re.search(p))
        if not has_q:
            comma_cnt = p.count("，")
            if 35 <= plen <= 140 and 2 <= comma_cnt <= 4 and len(action_words_re.findall(p)) >= 2:
                craft_action.append(p)
            if 30 <= plen <= 140 and sensory_re.search(p):
                craft_sensory.append(p)
            if 20 <= plen <= 110 and (transition_re.search(p) or p in chapter_first_paras):
                craft_trans.append(p)
            if 8 <= plen <= 28:
                craft_short.append(p)
        else:
            if 40 <= plen <= 160 and C.QUOTE.search(p):
                narr_rest = re.sub(r"\s", "", C.QUOTE.sub("", p))
                if len(narr_rest) >= 14:
                    craft_dlg_act.append(p)

    return {
        "连续动作白描": dedup_stride_pick(craft_action, per_cat, head_n=8),
        "环境与五感描写": dedup_stride_pick(craft_sensory, per_cat, head_n=8),
        "开篇与转场句": dedup_stride_pick(craft_trans, per_cat, head_n=8),
        "对话穿插动作（神态锚点）": dedup_stride_pick(craft_dlg_act, per_cat, head_n=8),
        "克制收尾与留白短段": dedup_stride_pick(craft_short, per_cat, head_n=8),
    }


DIALOGUE_FUNC_BUCKETS = [
    ("命令禁止", r"^(别|不要|不许|给我|把.{0,6}(放下|拿来|还)|少|快滚|闭嘴|住手)"),
    ("让步接受", r"^(嗯|好|行|那好|好吧|那就|可以|知道了|随便|算了)"),
    ("否认辩解", r"(不是你想|才不|没有|我那是|不是[^，。]{0,6}是|听我解释|误会)"),
    ("反问逼问", r"[？?]\s*$|难道|不是.{0,8}吗|凭什么|为什么"),
    ("请求商量", r"(让我|能不能|可不可以|好吗|好不好|帮我|借我|陪我)"),
    ("抱怨吐槽", r"(烦|真是|又来了|搞什么|凭什么|可恶|偏偏|未免)"),
    ("慌乱结巴", r"(、|……).{0,3}(我|你)|我我|你你|不、|别、"),
    ("陈述说明", r"."),
]


def _load_dialogue_buckets(cfg=None):
    if cfg:
        sf_dir = project.resolve_stylefit_dir(cfg)
        p = os.path.join(sf_dir, "funcs.json")
        if os.path.isfile(p):
            d = textio.read_json(p, {}) or {}
            items = [(k, v) for k, v in d.items() if not k.startswith("_") and isinstance(v, str)]
            if items:
                return items
    return DIALOGUE_FUNC_BUCKETS


def _classify_dialogue_func(line, buckets=None):
    for name, pat in (buckets or DIALOGUE_FUNC_BUCKETS):
        if re.search(pat, line):
            return name
    return "陈述说明"


def build_dialogue_style_buckets(X, pairs, per_bucket=10, cfg=None, all_dialogues=None):
    """纯文风模式：去角色绑定，按台词功能桶汇总全书代表句式、句长与句尾语气词。

    优先使用 all_dialogues（全书全部对白引号，彻底解决裸对白归属覆盖率低的问题），
    其次使用 pairs，最后回退 X["台词"]。
    """
    func_buckets = _load_dialogue_buckets(cfg)
    buckets = defaultdict(list)
    if all_dialogues:
        for txt in all_dialogues:
            t = (txt or "").strip()
            if len(re.sub(r"\s", "", t)) >= 2:
                buckets[_classify_dialogue_func(t, func_buckets)].append(t)
    elif pairs:
        for _, txt in pairs:
            t = (txt or "").strip()
            if len(re.sub(r"\s", "", t)) >= 2:
                buckets[_classify_dialogue_func(t, func_buckets)].append(t)
    else:
        known = {k for k, _ in func_buckets}
        for who_map in (X.get("台词") or {}).values():
            for func, info in (who_map or {}).items():
                target = func if func in known else "陈述说明"
                for s in (info.get("样本") or []):
                    buckets[target].append(s)

    out = []
    for func, _ in func_buckets:
        ls = buckets.get(func) or []
        if not ls:
            continue
        lens = sorted(len(x) for x in ls)
        avg_len = round(sum(lens) / len(lens), 1)
        med_len = lens[len(lens) // 2]
        tail = Counter()
        for t in ls:
            s = re.sub(r"[。！？…~\s]+$", "", t)
            if s:
                for ch in (s[-1:], s[-2:]):
                    if re.search(r"[\u4e00-\u9fff]", ch):
                        tail[ch] += 1
        top_tails = [w for w, c in tail.most_common(12) if c >= 2][:6]
        samples = pick_narr_tier(ls, per_bucket)
        out.append({
            "func": func,
            "n": len(ls),
            "avg_len": avg_len,
            "med_len": med_len,
            "tails": top_tails,
            "samples": samples,
        })
    return out


def _compose_document(header_lines, sections):
    parts = list(header_lines)
    for hdr, body, _w, _kt in sections:
        parts.append(hdr)
        parts.append("")
        if body:
            parts.append(body.rstrip())
            parts.append("")
    return "\n".join(parts).strip() + "\n"


def _budget_trim_sections(header_lines, sections, binfo):
    """按权重分配字符配额并优雅裁剪；若 UTF-8 KB 仍超出目标 8% 以上则等比下调再裁一次。"""
    if binfo.get("unlimited") or not binfo.get("example_chars"):
        return _compose_document(header_lines, sections)

    header_len = sum(len(x) + 1 for x in header_lines)
    sec_raw_texts = []
    weights = []
    keep_tails = []
    for hdr, body, w, kt in sections:
        block = (hdr + "\n\n" + (body.rstrip() if body else "")).strip() + "\n"
        sec_raw_texts.append(block)
        weights.append(w)
        keep_tails.append(kt)

    total_chars = header_len + sum(len(t) for t in sec_raw_texts)
    ex_chars = binfo["example_chars"]
    if total_chars <= ex_chars:
        doc = _compose_document(header_lines, sections)
        ex_kb = binfo.get("example_kb")
        if not ex_kb or budget.utf8_kb(doc) <= ex_kb * 1.08:
            return doc

    def _run_allot(char_limit):
        avail = max(400, char_limit - header_len - len(sections) * 2)
        sizes = [len(t) for t in sec_raw_texts]
        alloc = budget.allot_weights(sizes, weights, avail)
        trimmed_secs = []
        for idx, (hdr, body, w, kt) in enumerate(sections):
            block = sec_raw_texts[idx]
            lim = alloc[idx]
            if len(block) > lim:
                tblock = budget.trim_markdown_block(block, lim, keep_tail=kt)
                # 拆回 hdr 与 body
                lines = tblock.split("\n", 1)
                nhdr = lines[0] if lines else hdr
                nbody = lines[1].lstrip("\n") if len(lines) > 1 else ""
                trimmed_secs.append((nhdr, nbody, w, kt))
            else:
                trimmed_secs.append((hdr, body, w, kt))
        return _compose_document(header_lines, trimmed_secs)

    doc = _run_allot(ex_chars)
    ex_kb = binfo.get("example_kb")
    if ex_kb and budget.utf8_kb(doc) > ex_kb * 1.08:
        actual_kb = budget.utf8_kb(doc)
        scale_down = (ex_kb / actual_kb) * 0.96
        doc = _run_allot(max(600, int(ex_chars * scale_down)))
    if ex_kb and budget.utf8_kb(doc) > ex_kb * 1.12:
        doc = budget.trim_to_utf8_bytes(doc, ex_kb)
    return doc


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--style-only", action="store_true", default=None,
                    help="纯文风蒸馏模式：剥离原书剧情、名场面、分期与人物绑定")
    ap.add_argument("--anonymize", action="store_true",
                    help="对摘录中的人名与【条目框】做中性代称脱敏")
    ap.add_argument("--no-anonymize", action="store_true",
                    help="强制关闭脱敏（即使在 --style-only 下）")
    ap.add_argument("--anonymize-style", choices=["neutral", "names"], default=None,
                    help="脱敏代称风格：neutral（某甲/某乙）或 names（林远/苏晴/陈默）")
    budget.add_budget_args(ap)
    a = ap.parse_args()

    cfg = project.load(a.config)
    style_only = bool(cfg.get("style_only")) if a.style_only is None else bool(a.style_only)
    if a.no_anonymize:
        anonymize = False
    elif a.anonymize or cfg.get("anonymize") or style_only:
        anonymize = True
    else:
        anonymize = False
    anon_style = a.anonymize_style or cfg.get("anonymize_style") or "neutral"

    binfo = budget.resolve_budget(
        cfg,
        preset=a.preset,
        kb=a.kb,
        max_tokens=a.max_tokens,
        ratio=a.ratio,
        style_only=style_only,
    )
    if binfo["unlimited"]:
        scale = 2.5
    else:
        scale = max(0.45, min(2.6, (binfo["example_kb"] or 105.0) / 105.0))

    X = load_index(cfg)
    pairs = read_pairs(cfg)
    names = cfg.get("names") or []
    raw, _ = C.load_corpus(cfg["paths"]["chunks"])
    paras = C.paragraphs(raw)
    narr = C.narr_sentences(paras)
    all_dialogues = C.extract_dialogue_quotes(paras, min_len=2) if style_only else None

    if anonymize:
        extra_speakers = list((X.get("台词") or {}).keys())
        clean_fn, role_map = C.build_anonymizer(
            names=names,
            aliases=cfg.get("aliases"),
            extra_terms=extra_speakers,
            strip_brackets=True,
            anonymize_terms=cfg.get("anonymize_terms"),
            single_char_names=cfg.get("single_char_names"),
            style=anon_style,
            collapse_adjacent=True,
        )
    else:
        clean_fn, role_map = (lambda s: s), {}

    # ── 组装各节 (header, body, weight, keep_tail) ──
    sections = []

    def add_sec(header, lines_list, weight, keep_tail=False):
        body = "\n".join(lines_list).strip()
        sections.append((header, body, weight, keep_tail))

    craft_rules = load_craft_rules(cfg)
    self_words = craft_rules.get("self_words") or SELF_WORDS

    # ── 一 文风速览 ──
    st = X.get("统计", {})
    s1 = [
        "- 语料规模：%s" % (X.get("meta", {}).get("chars", "?")),
        "- 台词均长：%s ｜ 中位：%s ｜ ≤19 字占比：%s（统计来源：%s）" % (
            st.get("台词均长"), st.get("台词中位长度"), st.get("台词≤19字占比"),
            st.get("台词统计来源") or "归属台词"),
        "- 每千字标点：%s" % st.get("每千字标点"),
        "- 叙述句数：%s" % st.get("叙述句数"),
    ]
    if st.get("POV分桶"):
        pov_parts = []
        for pk, pv in st["POV分桶"].items():
            pov_parts.append("%s %d段(%.0f%%，均长%.1f，对白%.0f%%)" % (
                pk, pv.get("段数", 0), pv.get("占比", 0) * 100, pv.get("均段长", 0), pv.get("对白占比", 0) * 100))
        if pov_parts:
            s1.append("- POV 视角分桶：%s" % " ｜ ".join(pov_parts))
    if not style_only:
        s1.append("- 台词量前 12 人：%s" % st.get("说话人台词量"))
    if anonymize and role_map:
        style_desc = "自然中性人名（林远/苏晴……）" if anon_style == "names" else "中性代称（某甲/某乙……）"
        s1.append("- 脱敏说明：摘录中的原书人名已统一映射为%s，【条目框】已替换为「某技能/条目」。" % style_desc)
    s1.append("")
    s1.append(craft_rules.get("benchmark_note") or "> 对标时必须按同类场景切区间，不能拿全书硬套（详见 docs/PITFALLS.md）。")
    add_sec("## 一 · 文风速览（统计靶）", s1, 3.0)

    # ── 二 叙述腔 ──
    narr_k = max(8, min(50, int(round(20 * scale))))
    s2 = []
    tiers = [
        ("超短句(≤12字)", [s for s in narr if len(s) <= 12]),
        ("短句(13-25字)", [s for s in narr if 12 < len(s) <= 25]),
        ("中句(26-50字)", [s for s in narr if 25 < len(s) <= 50]),
        ("长复合句(>50字)", [s for s in narr if len(s) > 50]),
    ]
    for tag, pool in tiers:
        s2.append("**%s**" % tag)
        for s in pick_narr_tier(pool, narr_k):
            s2.append("- %s" % clean_fn(s))
        s2.append("")
    add_sec("## 二 · 叙述腔（%s）" % ("第一人称" if cfg.get("person") == "first" else "第三人称"), s2, 3.0)

    # ── 三 内心独白 ──
    inner_k = max(8, int(round(24 * scale)))
    one_k = max(12, int(round(36 * scale)))
    inner_pat = craft_rules.get("inner_words") or r"(心想|心里想|觉得|暗自|不禁|寻思|盘算|默念|吐槽)"
    inner = [s for s in narr if re.search(inner_pat, s)]
    one = [p.strip() for p in paras if 4 <= len(p.strip()) <= 26 and not C.iter_quotes(p)]
    s3 = []
    for s in dedup_stride_pick(inner, inner_k, head_n=4):
        s3.append("- %s" % clean_fn(s))
    s3.append("")
    s3.append(craft_rules.get("one_line_label") or "**单句成段短句（原文里独立一行，带吐槽 / 自嘲味）：**")
    s3.append("")
    for s in dedup_stride_pick(one, one_k, head_n=4):
        s3.append("- %s" % clean_fn(s))
    add_sec(craft_rules.get("inner_heading") or "## 三 · 内心独白 / 吐槽（混在叙述里，不带引号的那种）", s3, 2.2)

    # ── 三B 细粒度笔法与镜头细节 ──
    craft_k = max(5, int(round(12 * scale)))
    craft_data = X.get("笔法细节") or extract_craft_details(paras, raw, per_cat=craft_k)
    craft_order = [
        "连续动作白描",
        "环境与五感描写",
        "对话穿插动作（神态锚点）",
        "开篇与转场句",
        "克制收尾与留白短段",
    ]
    s_craft = [
        "> 写动作戏、环境氛围与转场衔接前先读这一节：全部来自原文真实句段，展示句子如何落地。",
        "",
    ]
    for cat in craft_order:
        items = craft_data.get(cat) or []
        if not items:
            continue
        s_craft.append("### %s" % cat)
        for item in dedup_stride_pick(items, craft_k, head_n=8):
            s_craft.append("- %s" % clean_fn(item))
        s_craft.append("")
    add_sec("## 四 · 细粒度笔法与镜头细节（连续动作 / 五感环境 / 神态锚点 / 转场留白）", s_craft, 4.0)

    # ── 四 对白回合 ──
    dlg_per = max(2, int(round(int(craft_rules.get("dlg_samples_base") or 6) * scale)))
    s4 = []
    for sc, d in (X.get("场景") or {}).items():
        if style_only and sc in ("游戏面板", "死亡复活"):
            continue
        s4.append("### 场景：%s" % sc)
        for s in stride_pick(d.get("样本", []), dlg_per):
            s4.append("```")
            s4.append(clean_fn(s.strip()))
            s4.append("```")
        s4.append("")
    add_sec("## 五 · 对白回合片段（引号与叙述的呼吸节奏）", s4, 3.5)

    # ── 五 台词档案 / 语体 ──
    masks = {}
    if style_only:
        bucket_per = max(5, int(round(10 * scale)))
        s5 = [
            "> 已开启纯文风模式：基于全书全部对白引号按话语功能汇总句式、节奏与高频句尾语气词（不再受限于归属覆盖率）。",
            "",
        ]
        for binfo_row in build_dialogue_style_buckets(
            X, pairs, per_bucket=bucket_per, cfg=cfg, all_dialogues=all_dialogues
        ):
            tail_str = " ｜ ".join(binfo_row["tails"]) if binfo_row["tails"] else "—"
            s5.append("### %s（%d 条 ｜ 均长 %.1f 字 ｜ 中位 %d 字 ｜ 高频句尾：%s）" % (
                binfo_row["func"], binfo_row["n"], binfo_row["avg_len"], binfo_row["med_len"], tail_str))
            for s in binfo_row["samples"]:
                s5.append("- %s" % clean_fn(s))
            s5.append("")
        add_sec("## 六 · 语体与台词功能范例", s5, 3.0)

        if not anonymize and pairs:
            masks = voice_profiles(pairs, top=12, self_words=self_words)
            addrs = address_table(pairs, names)
            s5b = [
                "> 保留原书人名对照：展示主要说话人的句长、自称、句尾口癖与典型台词。",
                "",
            ]
            sp_samples = max(2, min(4, int(round(3 * scale))))
            for who, d in masks.items():
                s5b.append("### %s" % who)
                s5b.append("- 台词 %d 条 ｜ 均长 %.1f ｜ 问号率 %.0f%% ｜ 感叹率 %.0f%%" % (
                    d["n"], d["均长"], d["问号率"] * 100, d["感叹率"] * 100))
                if d["自称"]:
                    s5b.append("- 自称：%s" % " ｜ ".join("%s %d" % x for x in d["自称"]))
                if addrs.get(who):
                    s5b.append("- 谁常提他：%s" % " ｜ ".join("%s %d" % x for x in addrs[who]))
                if d["口癖"]:
                    s5b.append("- 句尾口癖：%s" % " ｜ ".join("%s %d" % x for x in d["口癖"]))
                bs = (X.get("台词") or {}).get(who) or {}
                for func, b in list(bs.items())[:3]:
                    s5b.append("- **%s**（%d 条，中位 %d 字）" % (func, b["n"], b["中位长度"]))
                    for s in b["样本"][:sp_samples]:
                        s5b.append("  - %s" % s)
                s5b.append("")
            add_sec("## 六B · 主要人物语音档案（保留原名对照）", s5b, 2.4)
    else:
        masks = voice_profiles(pairs, self_words=self_words)
        addrs = address_table(pairs, names)
        sample_per_func = max(4, int(round(8 * scale)))
        s5 = []
        for who, d in masks.items():
            s5.append("### %s" % clean_fn(who))
            s5.append("- 台词 %d 条 ｜ 均长 %.1f ｜ 问号率 %.0f%% ｜ 感叹率 %.0f%% ｜ 省略率 %.0f%%" % (
                d["n"], d["均长"], d["问号率"] * 100, d["感叹率"] * 100, d["省略率"] * 100))
            if d["自称"]:
                s5.append("- 自称：%s" % " ｜ ".join("%s %d" % x for x in d["自称"]))
            if addrs.get(who):
                s5.append("- 谁常提他：%s" % " ｜ ".join("%s %d" % (clean_fn(k), v) for k, v in addrs[who]))
            if d["口癖"]:
                s5.append("- 句尾口癖：%s" % " ｜ ".join("%s %d" % x for x in d["口癖"]))
            bs = (X.get("台词") or {}).get(who) or {}
            for func, b in list(bs.items())[:8]:
                s5.append("- **%s**（%d 条，中位 %d 字）" % (func, b["n"], b["中位长度"]))
                for s in b["样本"][:sample_per_func]:
                    s5.append("  - %s" % clean_fn(s))
            s5.append("")
        add_sec("## 六 · 台词分角色 + 语音档案", s5, 3.0)

    # ── 六 亲密 / 感情场景写法 ──
    s6 = []
    d = (X.get("场景") or {}).get("亲密")
    intimate_base = int(craft_rules.get("intimate_samples_base") or 4)
    if d:
        s6.append("原文片段（%d 段）：" % d["n"])
        for s in stride_pick(d.get("样本", []), max(2, int(round(intimate_base * scale)))):
            s6.append("```")
            s6.append(clean_fn(s.strip()))
            s6.append("```")
        s6.append("")
    s6.append("场景词典（这类场景书里实际用的词 · 次数）：")
    for k, dd in (X.get("场景词典") or {}).items():
        if style_only and k in ("游戏面板", "死亡复活"):
            continue
        hot = sorted([(w, n) for w, n in dd.items() if n > 0], key=lambda x: -x[1])[:12]
        dead = [w for w, n in dd.items() if n == 0]
        s6.append("- **%s**：%s" % (k, " ｜ ".join("%s %d" % x for x in hot)))
        if dead:
            s6.append("  - 禁用：%s" % "、".join(dead))
    add_sec("## 七 · 亲密与感情场景写法", s6, float(craft_rules.get("intimate_weight") or 1.8))

    # ── 七 名场面（仅同人/IF 模式）──
    if not style_only:
        cards = scene_cards(cfg)
        s7 = []
        for fn, qs in cards:
            s7.append("### %s" % fn)
            for q in qs:
                s7.append("- “%s”" % clean_fn(q))
            s7.append("")
        if not cards:
            s7.append("<!-- notes/vol/*.md 里没有「名场面与关键台词」小节，检查二层模板 -->")
        add_sec("## 八 · 名场面原文摘录", s7, 1.0)

    # ── 八 描写套路 ──
    intent_k = max(5, int(round(10 * scale)))
    s8 = []
    for name, d in (X.get("描写") or {}).items():
        if style_only and name in ("看面板",):
            continue
        s8.append("### %s（原书 %d 处）" % (name, d["n"]))
        for s in dedup_stride_pick(d.get("样本", []), intent_k, head_n=6):
            s8.append("- %s" % clean_fn(s))
        s8.append("")
    add_sec("## 九 · 描写套路（这个意图书里怎么写）", s8, 3.5)

    # ── 九 语音分期（仅同人/IF 模式）──
    if not style_only:
        s9 = []
        tab = stage_table(pairs)
        if tab:
            s9.append("| 角色 | 前期 | 中期 | 后期 |")
            s9.append("|---|---|---|---|")
            for who, parts in tab.items():
                s9.append("| %s | %s |" % (clean_fn(who), " | ".join(parts)))
        else:
            s9.append("<!-- 没算出分期数据。若本书有角色说话方式随剧情变化（结巴→流利、幼年→成年），"
                      "在这里手工列出来，并标明分界章节。 -->")
        add_sec("## 十 · 语音分期（角色说话随时间/年龄变化）", s9, 1.2)

    # ── 十 搭配表 · 雷区（保持原词不脱敏）──
    s10 = [
        "> 写手很少造词，但经常配错。下表左列是概念，右列是书里实际的配法及次数，",
        "> 标「禁用」的是全书 0 次——出现就是 AI 味。",
        "",
    ]
    for c, dd in (X.get("搭配") or {}).items():
        s10.append("### %s" % c)
        for w, n in sorted(dd.items(), key=lambda kv: -kv[1]):
            mark = "  【禁用】" if n == 0 else ("  【慎用】" if n <= 3 else "")
            s10.append("- %s  %d%s" % (w, n, mark))
        s10.append("")
    z = X.get("零频词") or []
    s10.append("### 零频黑名单（全书 0 次）")
    s10.append("")
    s10.append("、".join(z) if z else "（空）")
    add_sec("## 十一 · 搭配表 · 典型 vs 雷区", s10, 2.8, keep_tail=True)

    # ── 十一 用词表与本书高频特征词（供写作模型参考目标书真实高频词）──
    s11 = []
    for c, dd in (X.get("用词") or {}).items():
        s11.append("- **%s**：%s" % (c, " ｜ ".join(
            "%s %d%s" % (w, n, "【禁用】" if n == 0 else "") for w, n in dd.items())))
    raw_top_words = X.get("高频词") or []
    if not raw_top_words and paras:
        exclude_tw = set(names) | set((X.get("台词") or {}).keys())
        for alts in (cfg.get("aliases") or {}).values():
            exclude_tw.update(alts or ())
        exclude_tw.update((cfg.get("anonymize_terms") or {}).keys())
        raw_top_words = [{"词": w, "次数": c} for w, c in C.extract_top_words(paras, top_k=60, exclude_terms=exclude_tw)]
    if raw_top_words:
        ex_leak = set(role_map.keys()) if anonymize else set()
        shown_tw = []
        for item in raw_top_words:
            w = item.get("词", "")
            c_cnt = item.get("次数", 0)
            if not w or (anonymize and (w in ex_leak or clean_fn(w) != w)):
                continue
            shown_tw.append("%s %d" % (w, c_cnt))
            if len(shown_tw) >= 50:
                break
        if shown_tw:
            s11.append("")
            s11.append("### 本书高频特征词（写作模型词汇对齐参考）")
            s11.append("> 以下为原书语料自动统计的高频实词与习语（已过滤停用词与角色专名），行文选词优先靠拢这套语域：")
            for idx_tw in range(0, len(shown_tw), 10):
                s11.append("- " + " ｜ ".join(shown_tw[idx_tw:idx_tw + 10]))
    add_sec("## 十二 · 用词表与本书高频特征词", s11, 2.2)

    # ── 十二 章节标题样例（仅同人/IF 模式）──
    if not style_only:
        secs = textio.read_json(os.path.join(cfg["paths"]["raw"], "sections.json"), []) or []
        all_t = [s.get("title") for s in secs if s.get("title")]
        named = [t for t in all_t if re.match(r"^第[0-9０-９零〇一二三四五六七八九十百千两]+[章节回话卷]\s+\S", t)]
        s12 = [
            "（全书 %d 章，其中 %d 章原文就没给标题、只写「第 N 章」，此处只列有标题的 %d 个；"
            "写番外时不要给这些无名章补造标题。）" % (len(all_t), len(all_t) - len(named), len(named)),
            "",
        ]
        for t in stride_pick(named, max(15, min(60, int(round(36 * scale))))):
            s12.append("- %s" % clean_fn(t))
        add_sec("## 十三 · 章节标题样例（写番外 / IF 时沿用这套句式）", s12, 0.5)

    # ── 十三 专项摘录 ──
    topic_per = max(2, int(round(int(craft_rules.get("topic_samples_base") or 8) * scale)))
    topic_win = int(craft_rules.get("topic_win") or 3)
    topic_max_chars = int(craft_rules.get("topic_max_excerpt_chars") or 0)
    s13 = []
    for title, segs in topic_digests(paras, topics=load_topics(cfg, style_only=style_only), per=topic_per, win=topic_win, max_chars=topic_max_chars):
        s13.append("### %s" % title)
        s13.append("")
        for s in segs:
            s13.append("```")
            s13.append(clean_fn(s))
            s13.append("```")
        s13.append("")
    add_sec("## 十四 · 专项摘录（按主题的大段原文，写同类场景前先扫一遍）", s13, float(craft_rules.get("topics_weight") or 1.8))

    # ── 十四 分剧本语料（仅同人/IF 模式）──
    arcs = []
    if not style_only:
        arcs = arc_digests(cfg)
        max_arcs = max(4, int(round(10 * scale)))
        arcs_show = arcs[:max_arcs]
        s14 = [
            "> 每个剧本／副本是一个独立世界，腔调与用词不同。写哪个本的同人，先翻对应那一节。",
            "",
        ]
        for arc in arcs_show:
            s14.append("### 剧本：%s（%s → %s，%d 章 ≈ %d 字）" % (
                arc["name"], arc["first"], arc["last"], arc["chapters"], arc["chars"]))
            s14.append("")
            for s in arc["samples"][:3]:
                s14.append("```")
                s14.append(clean_fn(s))
                s14.append("```")
            s14.append("")
        add_sec("## 十五 · 分剧本语料（同一作者写不同世界时的腔调差异）", s14, 1.0)

    # ── 十五 使用禁令（放最后，当自检清单用）──
    bans = ""
    bp = project.resolve_bans_file(cfg)
    if bp:
        bans = textio.read_text(bp).strip()
    s15 = [
        craft_rules.get("bans_note") or "> 定稿前扫一遍。这一节拦的是模型最容易犯的错：照抄开篇特殊写法、写本书没有的设定、把分期角色写死。",
        "",
        bans if bans else "<!-- 在 config/bans.md 里写本书的硬禁区。 -->",
    ]
    add_sec("## 十六 · 使用禁令 / 常见误区（写完自检用）", s15, 2.5, keep_tail=True)

    # ── 组装文档头 + 预算裁剪 + 统计看板 ──
    mode_tags = []
    mode_tags.append("纯文风蒸馏" if style_only else "同人/IF全套")
    mode_tags.append("已脱敏" if anonymize else "原名保留")
    mode_str = " · ".join(mode_tags)

    book_label = "通用文风样本" if (style_only and anonymize) else (cfg.get("name") or "")
    header_placeholder = [
        "# %s · 典型例子集" % book_label,
        "> 容量统计：__STATS_BANNER__",
        "> **防照抄护栏**：严禁直接复用、拼接或仅替换主语地照抄本包例句；仅学习句长分布、标点节奏、实词搭配、本书高频特征词与心理转折方式。",
        "（文风语料 ｜ 全部摘自原文 ｜ 供仿写与提示词取用）",
        "",
        "配套：`整书总结.md`（设定/剧情/状态/IF）。本文只负责文风与语感。"
        if not style_only else
        "本文件已剥离原书剧情与角色绑定，专供仿写语感、句式节奏与动作细节参考。",
        "阅读顺序建议：先看【一 文风速览】定口径，写动作翻【四 细粒度笔法与镜头细节】【九 描写套路】，",
        "写对白查【五 对白回合】【六 %s】，收尾前用【%s】自检。" % (
            "语体与台词功能范例" if style_only else "台词分角色",
            "十六 使用禁令",
        ),
        "",
        "=" * 60,
        "",
    ]

    doc = _budget_trim_sections(header_placeholder, sections, binfo)
    banner_line = budget.format_stats_banner(doc.replace("__STATS_BANNER__", ""), budget_info=binfo) + " ｜ 模式 " + mode_str
    doc = doc.replace("__STATS_BANNER__", banner_line, 1)
    # 替换真实看板长度可能略微变动（~20字），确保最终统计精确一致
    final_banner = budget.format_stats_banner(doc, budget_info=binfo) + " ｜ 模式 " + mode_str
    doc = re.sub(r"^> 容量统计：.*$", "> 容量统计：" + final_banner, doc, count=1, flags=re.MULTILINE)

    out = a.out or os.path.join(cfg["paths"]["out"], "例子.txt")
    textio.write_text(out, doc)
    print("容量统计：%s" % final_banner)
    print("例子集：%d 字 ｜ 角色档案 %d 个 ｜ 搭配概念 %d ｜ 剧本 %d ｜ 零频词 %d" % (
        len(doc), len(masks), len(X.get("搭配") or {}), len(arcs), len(X.get("零频词") or [])))
    print("→ %s" % out)
    print("下一步：python scripts/10_build_summary.py")


if __name__ == "__main__":
    main()
