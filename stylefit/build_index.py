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
from lib import corpus as C, textio          # noqa: E402

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


def _head8(s):
    return re.sub(r"[^\u4e00-\u9fff]", "", s)[:8]


def _head4(s):
    return re.sub(r"\s", "", s)[:4]


def quantile_pick(v, k=16):
    v = sorted(v, key=len)
    n = len(v)
    if n == 0:
        return []
    picked = [v[min(n - 1, int(n * i / k))] for i in range(1, k)]
    out, seen_full, seen_head = [], set(), set()
    for item in picked:
        h = _head4(item)
        if item in seen_full or (h and h in seen_head):
            continue
        seen_full.add(item)
        if h:
            seen_head.add(h)
        out.append(item)
    return out


def scene_of(txt, rules=None):
    if rules:
        for name, pat in rules:
            if re.search(pat, txt):
                return name
        return "日常"
    if re.search(r"(打|砍|劈|箭|魔法阵|轰|伤口|血|闪避|斩|枪|攻击|剑|刀|杀)", txt):
        return "战斗"
    if re.search(r"(金币|铜币|银两|价钱|买卖|委托|报酬|账|赊|买|卖|交易)", txt):
        return "交易"
    if re.search(r"(脸红|害羞|亲|吻|抱|嘴唇|羞耻|搂|贴|喘|心跳)", txt):
        return "亲密"
    if re.search(r"(道歉|拜托|商量|会议|协会|委托人|谈判|请求|交涉|条件)", txt):
        return "交涉"
    return "日常"


def stride_pick(items, k):
    n = len(items)
    if n <= k:
        return list(items)
    return [items[int(i * n / k)] for i in range(k)]


def main():
    textio.ensure_utf8_stdio()
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

    sv = C.detect_script_variant(raw)
    if sv["variant"] == "traditional":
        print(
            "[警告] 检测到语料以繁体中文为主（繁体字占比 %.1f%%，繁 %d / 简 %d），"
            "而默认 config/stylefit/*.json 词典为简体，搭配表/用词表/零频黑名单可能出现大量 0 命中！"
            "建议先将语料转为简体，或配置繁体版 stylefit_dir。" % (
                sv["trad_ratio"] * 100.0, sv["trad"], sv["simp"]
            ),
            file=sys.stderr,
        )

    # ── 归属 ──
    known_names = [x.strip() for x in a.names.split(",") if x.strip()]
    pairs = C.load_attribution(a.attrib)
    src = "归属文件"
    if not pairs:
        names = list(known_names)
        if not names:
            names = [n for n, _ in Counter(
                m for m in re.findall(r"([\u4e00-\u9fff]{2,4})(?=[^。！？\n]{0,8}" + C.VERB + r")", raw)
            ).most_common(30)]
        pairs = C.derive_speakers(raw, names)
        src = "自动抓取"
    print("台词配对 %d 条（%s，%d 个说话人）" % (len(pairs), src, len({w for w, _ in pairs})))

    narr = C.narr_sentences(paras)
    IDX = {"meta": {"corpus": a.corpus, "chars": len(B), "paras": len(paras),
                    "files": len(files), "attrib": src, "pairs": len(pairs),
                    "script_variant": sv["variant"]},
           "台词": {}, "描写": {}, "笔法细节": {}, "搭配": {}, "用词": {}, "高频词": [],
           "零频词": [], "场景": {}, "场景词典": {}, "统计": {}}

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

    def _split_sents(para):
        parts = re.findall(r"[^。！？\n]+[。！？]+|[^。！？\n]+", para)
        return [x.strip() for x in parts if x.strip()]

    def _pick_sentence_group(para, pat_re):
        if len(para) <= 140:
            return [para] if pat_re.search(para) else []
        sents = _split_sents(para)
        if not sents:
            return []
        groups = []
        for idx, sent in enumerate(sents):
            if not pat_re.search(sent):
                continue
            grp = sent
            if len(grp) < 35 and idx > 0 and len(sents[idx - 1]) + len(grp) <= 140:
                grp = sents[idx - 1] + grp
            if len(grp) < 35 and idx + 1 < len(sents) and len(grp) + len(sents[idx + 1]) <= 140:
                grp = grp + sents[idx + 1]
            if len(grp) > 140:
                if len(sent) <= 140:
                    grp = sent
                else:
                    sub = [c.strip() for c in re.split(r"(?<=[，；])", sent) if c.strip()]
                    acc = ""
                    for seg in sub:
                        if pat_re.search(seg):
                            acc = seg
                            break
                    if not acc:
                        acc = sub[0] if sub else sent[:140]
                    for seg in sub:
                        if seg == acc:
                            continue
                        if len(acc) >= 35:
                            break
                        if len(acc) + len(seg) <= 140:
                            acc += seg
                    grp = acc[:140]
            if grp:
                groups.append(grp)
        return groups

    for name, pat in intents.items():
        if name.startswith("_"):
            continue
        pat_re = re.compile(pat)
        total_hits = sum(len(pat_re.findall(p)) for p in paras)
        cands = []
        for p in paras:
            if not pat_re.search(p):
                continue
            cands.extend(_pick_sentence_group(p, pat_re))
        seen_h, deduped = set(), []
        for c in cands:
            h8 = _head8(c)
            key = h8 if h8 else c[:12]
            if key in seen_h:
                continue
            seen_h.add(key)
            deduped.append(c)
        IDX["描写"][name] = {"n": total_hits, "样本": stride_pick(deduped, 24)}

    # ── 2b 笔法细节 ──
    craft_rules = {}
    cr_file = os.path.join(a.config, "craft_rules.json")
    if os.path.isfile(cr_file):
        craft_rules = json.load(open(cr_file, encoding="utf-8"))

    has_quote_re = re.compile("[" + "".join(re.escape(c) for c in C.QUOTE_OPEN + C.QUOTE_CLOSE) + "]")
    action_words_re = re.compile(
        craft_rules.get("action_words")
        or r"(?:伸手|伸出|拿|拉|推|走|看|转身|低头|抬起|放下|握|按|推开|坐下|起身|站起|迈步|扣|抓|递|接过|抬眼|抬手|点头|摇头)"
    )
    sensory_re = re.compile(
        craft_rules.get("sensory")
        or r"(?:阳光|月光|灯光|阴影|夜色|光线|昏暗|微风|风声|雨声|脚步声|敲门声|响起|传来|冰凉|滚烫|温热|粗糙|刺骨|窗外|街上|角落|空气|气味|寂静|回荡)"
    )
    transition_re = re.compile(
        craft_rules.get("transition")
        or (r"^(?:片刻之后|没过多久|很快|过了许久|半晌|第二天|次日|夜幕降临|天色渐暗|黄昏|清晨|傍晚|半小时后|等到|回到|离开|走进|来到)"
            r"|(?:片刻之后|没过多久|第二天|夜幕降临|半小时后|等到.{2,10}的时候)")
    )

    craft_k = int(craft_rules.get("craft_max_samples") or 25)

    def _dedup_stride_25(items):
        seen_h, out = set(), []
        for it in items:
            h8 = _head8(it)
            key = h8 if h8 else it[:12]
            if key in seen_h:
                continue
            seen_h.add(key)
            out.append(it)
        return stride_pick(out, craft_k)

    craft_action, craft_sensory, craft_trans, craft_dlg_act, craft_short = [], [], [], [], []
    # 检测章节首段：原始文本中章节标题行后的首个非空正文段
    chapter_first_paras = set()
    lines_raw = raw.split("\n")
    expect_first = False
    for ln in lines_raw:
        st = ln.strip()
        if not st:
            continue
        if st.startswith("#") or C.CHAP.match(st):
            expect_first = True
            continue
        if C.is_divider(st):
            continue
        if expect_first:
            chapter_first_paras.add(st)
            expect_first = False

    for p in paras:
        plen = len(p)
        qms = C.iter_quotes(p)
        has_q = bool(qms) or bool(has_quote_re.search(p))
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
            if 40 <= plen <= 160 and qms:
                narr_rest = re.sub(r"\s", "", C.strip_dialogue_quotes(p, keep_inline_text=False))
                if len(narr_rest) >= 14:
                    craft_dlg_act.append(p)

    IDX["笔法细节"] = {
        "连续动作白描": _dedup_stride_25(craft_action),
        "环境与五感描写": _dedup_stride_25(craft_sensory),
        "开篇与转场句": _dedup_stride_25(craft_trans),
        "对话穿插动作（神态锚点）": _dedup_stride_25(craft_dlg_act),
        "克制收尾与留白短段": _dedup_stride_25(craft_short),
    }

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

    # ── 5 场景片段（全书均匀采样，不偏向前文）──
    scene_rules = None
    sr_file = os.path.join(a.config, "scene_rules.json")
    if os.path.isfile(sr_file):
        sr_raw = json.load(open(sr_file, encoding="utf-8"))
        scene_rules = [(k, v) for k, v in sr_raw.items() if not k.startswith("_")]

    bs = defaultdict(list)
    for i, p in enumerate(paras):
        s = scene_of(p, scene_rules)
        bs[s].append(i)
    scene_max_samples = int(craft_rules.get("scene_max_samples") or 18)
    scene_win_before = int(craft_rules.get("scene_win_before") if craft_rules.get("scene_win_before") is not None else 3)
    scene_win_after = int(craft_rules.get("scene_win_after") if craft_rules.get("scene_win_after") is not None else 5)
    scene_max_chars = int(craft_rules.get("scene_max_excerpt_chars") or 0)
    rule_map = dict(scene_rules or [])

    def _clip_scene(txt, sname):
        if not scene_max_chars or len(txt) <= scene_max_chars:
            return txt
        pat = rule_map.get(sname)
        m = re.search(pat, txt) if pat else None
        center = m.start() if m else len(txt) // 2
        half = scene_max_chars // 2
        lo = max(0, center - half)
        hi = min(len(txt), lo + scene_max_chars)
        if hi - lo < scene_max_chars:
            lo = max(0, hi - scene_max_chars)
        if lo > 0:
            b = txt.find("。", lo)
            if b != -1 and b < center:
                lo = b + 1
        if hi < len(txt):
            b = txt.rfind("。", lo, hi)
            if b != -1 and b > center:
                hi = b + 1
        return ("……" if lo > 0 else "") + txt[lo:hi].strip() + ("……" if hi < len(txt) else "")

    IDX["场景"] = {}
    for s, idxs in bs.items():
        non_overlap = []
        for idx in idxs:
            if not non_overlap or idx - non_overlap[-1] >= 6:
                non_overlap.append(idx)
        picks = stride_pick(non_overlap, scene_max_samples)
        IDX["场景"][s] = {
            "n": len(idxs),
            "样本": [_clip_scene("\n".join(paras[max(0, idx - scene_win_before):idx + scene_win_after]), s) for idx in picks],
        }

    # ── 4b 本书高频特征词（供写作模型直接参考目标书高频用词）──
    exclude_for_top = set(known_names) | set(IDX["台词"].keys())
    IDX["高频词"] = [
        {"词": w, "次数": c}
        for w, c in C.extract_top_words(paras, top_k=80, exclude_terms=exclude_for_top, min_count=4)
    ]

    # ── 6 统计靶（全书对白优先，不再受限于低覆盖率归属）──
    all_dlg = C.extract_dialogue_quotes(paras, min_len=2)
    attrib_L = [t for _, t in pairs if len(re.sub(r"\s", "", t)) >= 2]
    use_all_dlg = bool(all_dlg) and (len(attrib_L) < len(all_dlg) * 0.30 or not attrib_L)
    L = all_dlg if use_all_dlg else attrib_L
    lens = sorted(len(x) for x in L)

    # POV 分桶统计（第一人称 vs 第三人称）
    pov_groups = {"第一人称": [], "第三人称": []}
    for p in paras:
        pv = C.detect_para_pov(p)
        if pv == "first":
            pov_groups["第一人称"].append(p)
        elif pv == "third":
            pov_groups["第三人称"].append(p)
    pov_stats = {}
    for pname, plist in pov_groups.items():
        if len(plist) < 10:
            continue
        p_raw = "\n".join(plist)
        p_cjk = len(re.sub(r"[^\u4e00-\u9fff]", "", p_raw))
        p_compact = re.sub(r"\s", "", p_raw)
        p_dlgs = C.extract_dialogue_quotes(plist, min_len=2)
        dlg_chars = sum(len(re.sub(r"\s", "", x)) + 2 for x in p_dlgs)
        pov_stats[pname] = {
            "段数": len(plist),
            "占比": round(len(plist) / max(1, len(paras)), 3),
            "均段长": round(len(p_compact) / max(1, len(plist)), 1),
            "对白占比": round(dlg_chars / max(1, len(p_compact)), 3),
            "每千字标点": {
                pm: round(p_compact.count(pm) / max(1, p_cjk) * 1000, 2)
                for pm in ["！", "？", "…", "——"]
            },
        }

    IDX["统计"] = {
        "台词均长": round(sum(lens) / max(1, len(lens)), 1),
        "台词中位长度": lens[len(lens) // 2] if lens else 0,
        "台词≤19字占比": round(sum(1 for x in lens if x <= 19) / max(1, len(lens)), 3),
        "全书台词数": len(all_dlg),
        "归属台词数": len(attrib_L),
        "台词统计来源": "全书引号对白" if use_all_dlg else "归属台词",
        "每千字标点": {p: round(BR.count(p) / max(1, len(B)) * 1000, 2)
                   for p in ["！", "？", "…", "——", "，", "。"]},
        "说话人台词量": {w: c for w, c in Counter(w for w, _ in pairs).most_common(12)},
        "叙述句数": len(narr),
        "POV分桶": pov_stats,
    }

    out = os.path.join(a.out, "index.json")
    json.dump(IDX, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("索引写入 %s" % out)
    print("人物 %d ｜ 功能桶 %d ｜ 描写意图 %d ｜ 搭配概念 %d ｜ 高频词 %d ｜ 场景 %d ｜ 场景词典 %d ｜ 零频词 %d" % (
        len(IDX["台词"]), sum(len(v) for v in IDX["台词"].values()), len(IDX["描写"]),
        len(IDX["搭配"]), len(IDX["高频词"]), len(IDX["场景"]), len(IDX["场景词典"]), len(IDX["零频词"])))
    if IDX["零频词"]:
        print("零频词（全书 0 次，禁用）：",
              "、".join(IDX["零频词"][:40]) + ("..." if len(IDX["零频词"]) > 40 else ""))


if __name__ == "__main__":
    main()
