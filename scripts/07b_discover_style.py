#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 7B · 基于对数似然比（LLR / G²）的语料文风指纹自动挖掘（纯标准库，零 LLM 成本）。

  python scripts/07b_discover_style.py
  python scripts/07b_discover_style.py --corpus work/chunks --top 30
  python scripts/07b_discover_style.py --config config/project.json --export-dir work/stylefit_auto
  python scripts/07b_discover_style.py --corpus work/raw/_all.txt --json work/style_fingerprint.json

核心能力：
  1. 内置现代中文 / 网文先验词频表（~210 条常见动宾搭配、反应短语、连接副词、感官动作与高频 AI 套话，按语义概念分组）。
  2. 计算每个词项相对先验期望的精确对数似然比（Log-Likelihood Ratio / G²）：
     - 正向指纹词（本书显著超配，obs > exp 且高 G²）；
     - 负向零频雷区（通用先验高频、但本书 0 次出现，极易暴露 AI 味）；
     - 本书高频特征词（调用 corpus.extract_top_words，剔除配置中的人名/别名，直示目标书真实实词质感）。
  3. --export-dir 可一键导出可直接接进 stylefit_dir / build_index.py 的 colloc.json 与 words.json。
"""
import argparse
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus as C, project, textio  # noqa: E402


# 参考语料虚拟规模（1000 万汉字通用现代汉语/网文参考库）
REF_CORPUS_CHARS = 10_000_000

# ── 内置先验词频表（单位：每 10 万汉字期望出现次数）──
# 结构：{"概念名": {"kind": "colloc"|"words", "terms": [(词项, 每10万字先验频次), ...]}}
PRIOR_CONCEPTS = {
    # ── 搭配类（动宾搭配 / 肢体反应 / 表情 / 感官动作）──
    "眼神与视线": {
        "kind": "colloc",
        "terms": [
            ("看了一眼", 14.0), ("抬起头", 12.0), ("抬眼", 7.0), ("移开视线", 4.5),
            ("别过脸", 3.5), ("垂下眼", 4.0), ("垂着眼", 3.5), ("扫了一眼", 8.0),
            ("盯了一眼", 3.0), ("四目相对", 3.5), ("眼神深邃", 4.0), ("瞳孔骤缩", 4.0),
            ("眼神一凛", 4.0), ("眼中闪过一丝", 5.5), ("目光如炬", 3.0), ("凝视着", 5.0),
            ("注视着", 6.0), ("打量着", 5.5),
        ],
    },
    "笑与神情": {
        "kind": "colloc",
        "terms": [
            ("笑了笑", 15.0), ("微笑着", 6.5), ("笑出声", 6.0), ("忍不住笑", 4.0),
            ("干笑", 5.0), ("苦笑", 10.0), ("冷笑", 9.0), ("轻笑", 9.0),
            ("咧嘴笑", 3.5), ("嘴角勾起", 7.0), ("嘴角上扬", 6.5), ("似笑非笑", 4.5),
            ("嗤笑", 4.5), ("面无表情", 8.0), ("神色一凛", 4.5), ("脸色一沉", 6.0),
            ("脸色苍白", 5.0), ("淡淡一笑", 5.0), ("露出一抹", 6.0),
        ],
    },
    "皱眉与微表情": {
        "kind": "colloc",
        "terms": [
            ("皱了皱眉", 12.0), ("皱起眉头", 7.0), ("眉头紧锁", 5.0), ("挑了挑眉", 6.0),
            ("咬了咬唇", 4.5), ("咬紧牙关", 4.5), ("脸红了", 5.5), ("耳根发烫", 3.5),
            ("脸颊发烫", 3.0), ("抿了抿唇", 5.5), ("嘴唇微动", 3.0), ("咽了口唾沫", 4.0),
            ("微微一愣", 6.5), ("微微皱眉", 6.0),
        ],
    },
    "点头摇头与停顿": {
        "kind": "colloc",
        "terms": [
            ("点了点头", 16.0), ("微微颔首", 4.5), ("摇了摇头", 14.0), ("轻轻摇头", 4.5),
            ("顿了顿", 9.5), ("沉默片刻", 6.0), ("陷入沉默", 5.0), ("一时语塞", 3.5),
            ("欲言又止", 4.5), ("半晌没说话", 3.0), ("沉默了一会儿", 4.0),
        ],
    },
    "呼吸与叹气": {
        "kind": "colloc",
        "terms": [
            ("叹了口气", 16.0), ("长叹一声", 4.5), ("轻叹", 5.5), ("深吸一口气", 9.5),
            ("松了口气", 10.0), ("屏住呼吸", 4.5), ("倒吸一口凉气", 4.5), ("喘了口气", 5.0),
            ("呼吸一滞", 4.0), ("心跳加速", 4.5),
        ],
    },
    "手部与动作链": {
        "kind": "colloc",
        "terms": [
            ("伸出手", 12.0), ("握紧拳头", 6.0), ("攥紧", 6.5), ("捏住衣角", 3.0),
            ("背在身后", 4.5), ("摆了摆手", 9.5), ("挥了挥手", 7.0), ("揉了揉", 7.5),
            ("拍了拍", 10.0), ("摸了摸", 9.5), ("推开", 16.0), ("推了推", 6.0),
            ("一把推开", 3.5), ("撞开", 4.0), ("拉开", 12.0), ("抓起", 7.0),
            ("拿起来", 8.0), ("掏出", 11.0), ("放在桌上", 5.0),
        ],
    },
    "起身走动与转身": {
        "kind": "colloc",
        "terms": [
            ("站起身", 11.0), ("站起来", 13.0), ("猛地起身", 3.5), ("坐下来", 9.5),
            ("呆坐", 2.5), ("转身", 20.0), ("转过身", 12.0), ("退后一步", 5.0),
            ("后退一步", 5.0), ("拔腿就跑", 3.0), ("小跑", 5.5), ("冲过去", 6.5),
            ("停下脚步", 7.5), ("快步走", 5.0), ("踉跄", 5.0), ("迈步", 6.0),
        ],
    },
    "说话与声音": {
        "kind": "colloc",
        "terms": [
            ("小声说", 6.0), ("压低声音", 6.5), ("脱口而出", 5.5), ("嘀咕", 6.5),
            ("嘟囔", 6.0), ("呢喃", 6.0), ("喃喃自语", 4.5), ("自言自语", 6.0),
            ("沉声道", 10.0), ("冷声道", 8.0), ("轻声道", 9.0), ("开口道", 8.5),
            ("淡淡地道", 5.5), ("笑着说", 8.0), ("喊道", 11.0), ("叫道", 12.0),
            ("答道", 10.0), ("问道", 14.0), ("低声说", 6.0),
        ],
    },
    "眼泪与情绪震动": {
        "kind": "colloc",
        "terms": [
            ("眼眶发红", 4.0), ("眼眶发热", 3.5), ("泪水滑落", 3.0), ("吸了吸鼻子", 3.5),
            ("抹了把脸", 3.5), ("浑身一震", 6.0), ("身体一僵", 5.5), ("心里一沉", 6.0),
            ("心头一震", 5.0), ("脑海一片空白", 3.5), ("打了个寒颤", 3.5), ("热泪盈眶", 3.0),
        ],
    },
    "环境与感官": {
        "kind": "colloc",
        "terms": [
            ("微风拂过", 3.0), ("阳光洒落", 3.0), ("灯光昏暗", 3.0), ("空气仿佛凝固", 3.5),
            ("寂静无声", 3.5), ("鸦雀无声", 4.0), ("脚步声响起", 3.5), ("空气中弥漫", 3.5),
            ("冰凉", 8.5), ("滚烫", 6.0), ("温热", 7.0), ("刺骨", 5.0),
            ("昏暗", 7.5), ("寂静", 8.0), ("阴影", 9.5), ("余晖", 3.5),
        ],
    },
    # ── 用词类（程度副词 / 连接词 / 心理动词 / 高频 AI 套话与网文惯用语）──
    "程度副词": {
        "kind": "words",
        "terms": [
            ("非常", 24.0), ("十分", 22.0), ("极其", 12.0), ("格外", 9.5),
            ("相当", 14.0), ("颇为", 6.5), ("略微", 7.5), ("稍微", 11.0),
            ("丝毫", 12.0), ("无比", 11.0), ("异常", 9.0), ("隐隐", 8.5),
            ("微微", 18.0), ("彻底", 14.0), ("简直", 12.0), ("实在", 16.0),
            ("的确", 14.0), ("确实", 16.0), ("显然", 12.0),
        ],
    },
    "连接与推进词": {
        "kind": "words",
        "terms": [
            ("然后", 34.0), ("接着", 22.0), ("于是", 20.0), ("随后", 17.0),
            ("紧接着", 8.5), ("片刻之后", 6.0), ("没过多久", 6.5), ("下一秒", 6.0),
            ("下一刻", 7.0), ("与此同时", 6.5), ("然而", 22.0), ("不过", 38.0),
            ("毕竟", 22.0), ("居然", 16.0), ("竟然", 18.0), ("偏偏", 11.0),
            ("果然", 18.0), ("终究", 8.5), ("顿时", 16.0), ("登时", 6.0),
        ],
    },
    "心理与感知动词": {
        "kind": "words",
        "terms": [
            ("心想", 12.0), ("暗自", 8.0), ("暗道", 8.0), ("不禁", 16.0),
            ("不由得", 11.0), ("忍不住", 18.0), ("下意识", 13.0), ("默默", 13.0),
            ("恍然", 6.0), ("察觉", 10.0), ("意识到", 12.0), ("感觉到", 13.0),
            ("寻思", 5.5), ("盘算", 5.0), ("思忖", 4.0),
        ],
    },
    "高频AI与网文套话": {
        "kind": "words",
        "terms": [
            ("瞬间", 24.0), ("仿佛", 22.0), ("似乎", 30.0), ("宛如", 7.5),
            ("犹如", 7.5), ("骤然", 7.5), ("蓦然", 5.0), ("赫然", 6.0),
            ("霎时间", 4.5), ("刹那间", 5.5), ("一时间", 8.5), ("不知为何", 8.0),
            ("莫名其妙", 7.0), ("不可思议", 6.5), ("难以置信", 6.5), ("哭笑不得", 5.5),
            ("意味深长", 5.5), ("若有所思", 6.0), ("毫不在意", 5.0), ("不动声色", 5.5),
            ("猝不及防", 4.5), ("泛起一丝", 4.0), ("一抹", 8.0), ("一丝", 16.0),
            ("嘴角微微上扬", 4.0), ("倒吸一口气", 4.0),
        ],
    },
}


def compute_llr(obs, n_target, prior_per_100k, n_ref=REF_CORPUS_CHARS):
    """计算精确 2x2 对数似然比 G²（Log-Likelihood Ratio / Dunning 1993）。

    参数：
      obs: 目标语料中观测到的出现次数 O1
      n_target: 目标语料汉字规模 N1
      prior_per_100k: 参考语料每 10 万字期望频次
      n_ref: 参考语料规模 N2
    返回 (g2, exp_target, direction)：
      direction: +1 表示 obs > exp（正向超配），-1 表示 obs < exp（负向欠配），0 表示持平。
    """
    n1 = max(1.0, float(n_target))
    n2 = max(1.0, float(n_ref))
    o1 = max(0.0, min(float(obs), n1))
    o2 = max(0.0, min(float(prior_per_100k) * (n2 / 100_000.0), n2))

    exp_prior = n1 * (float(prior_per_100k) / 100_000.0)
    tot_n = n1 + n2
    tot_o = o1 + o2
    if tot_o <= 0.0:
        return 0.0, 0.0, 0

    e1 = n1 * tot_o / tot_n
    e2 = n2 * tot_o / tot_n
    o1_not = max(0.0, n1 - o1)
    o2_not = max(0.0, n2 - o2)
    e1_not = max(1e-12, n1 - e1)
    e2_not = max(1e-12, n2 - e2)

    def _term(o, e):
        if o <= 0.0 or e <= 0.0:
            return 0.0
        return o * math.log(o / e)

    g2 = 2.0 * (
        _term(o1, e1)
        + _term(o2, e2)
        + _term(o1_not, e1_not)
        + _term(o2_not, e2_not)
    )
    if g2 < 0.0:
        g2 = 0.0

    if abs(o1 - e1) < 1e-12:
        direction = 0
    elif o1 > e1:
        direction = 1
    else:
        direction = -1
    return round(g2, 3), round(exp_prior, 3), direction


def discover_style(raw, top=30, exclude_terms=None, min_sig_count=None):
    """对语料运行 LLR 文风指纹挖掘 + 高频特征词提取。"""
    paras = C.paragraphs(raw)
    cjk_only = re.sub(r"[^\u4e00-\u9fff]", "", raw)
    no_ws = re.sub(r"\s", "", raw)
    n_cjk = max(1, len(cjk_only))

    all_rows = []
    by_concept = {}
    seen_terms = set()

    for concept, spec in PRIOR_CONCEPTS.items():
        kind = spec["kind"]
        rows_c = []
        for term, prior_rate in spec["terms"]:
            if term in seen_terms:
                continue
            seen_terms.add(term)
            obs = no_ws.count(term)
            g2, exp_cnt, direction = compute_llr(obs, n_cjk, prior_rate)
            obs_rate = round(obs / n_cjk * 100_000.0, 2)
            fold = round(obs_rate / prior_rate, 2) if prior_rate > 0 else 0.0
            rec = {
                "term": term,
                "concept": concept,
                "kind": kind,
                "obs": obs,
                "exp": exp_cnt,
                "obs_per_100k": obs_rate,
                "prior_per_100k": prior_rate,
                "fold": fold,
                "g2": g2,
                "direction": direction,
            }
            all_rows.append(rec)
            rows_c.append(rec)
        by_concept[concept] = {"kind": kind, "items": rows_c}

    # 1. 正向指纹词（obs > exp，按 G² 降序）
    positives = [r for r in all_rows if r["obs"] > 0 and r["direction"] > 0]
    positives.sort(key=lambda r: (-r["g2"], -r["obs"], r["term"]))

    # 2. 负向零频雷区（obs == 0，按 G² 降序，即先验越高越靠前）
    zero_mines = [r for r in all_rows if r["obs"] == 0 and r["prior_per_100k"] > 0]
    zero_mines.sort(key=lambda r: (-r["g2"], -r["prior_per_100k"], r["term"]))

    # 3. 显著欠配词（obs > 0 但显著低于先验，供参考）
    under_rep = [r for r in all_rows if r["obs"] > 0 and r["direction"] < 0]
    under_rep.sort(key=lambda r: (-r["g2"], r["obs"], r["term"]))

    # 4. 本书高频特征词（调用 corpus.extract_top_words，剔除人名与别名）
    eff_min = min_sig_count if min_sig_count is not None else (3 if n_cjk < 40_000 else 5)
    sig_pairs = C.extract_top_words(
        paras,
        top_k=max(top, 40),
        exclude_terms=exclude_terms or (),
        min_count=eff_min,
    )
    signature_words = [
        {"word": w, "count": c, "per_100k": round(c / n_cjk * 100_000.0, 2)}
        for w, c in sig_pairs
    ]

    return {
        "meta": {
            "chars_cjk": n_cjk,
            "paragraphs": len(paras),
            "prior_terms_checked": len(all_rows),
            "top": top,
        },
        "positive_fingerprints": positives[:top],
        "zero_freq_mines": zero_mines[:top],
        "under_represented": under_rep[:min(top, 20)],
        "signature_words": signature_words[:top],
        "all_positive_count": len(positives),
        "all_zero_count": len(zero_mines),
        "_by_concept": by_concept,
        "_all_zero": zero_mines,
        "_all_signature": signature_words,
    }


def build_stylefit_exports(result, top_zero=40, top_sig=40):
    """从挖掘结果构造可直接用于 stylefit/build_index.py 的 colloc.json 与 words.json。"""
    by_concept = result["_by_concept"]

    colloc_out = {
        "_说明": "由 scripts/07b_discover_style.py 基于对数似然比（LLR / G²）自动挖掘生成，可直接用于 stylefit_dir。",
    }
    words_out = {
        "_说明": "由 scripts/07b_discover_style.py 自动挖掘生成：含语义词组、本书高频特征词与先验零频雷区。",
    }

    for concept, spec in by_concept.items():
        kind = spec["kind"]
        items = spec["items"]
        # 同概念内：保留所有本书实际出现的高频/超配词 + 先验最高的前若干个零频对照项（形成典型 vs 雷区）
        observed = sorted([r for r in items if r["obs"] > 0], key=lambda r: (-r["obs"], -r["g2"]))
        zeros = sorted([r for r in items if r["obs"] == 0], key=lambda r: (-r["prior_per_100k"], r["term"]))
        picked = [r["term"] for r in observed] + [r["term"] for r in zeros[:5]]
        # 去重保持顺序
        uniq = list(dict.fromkeys(picked))
        if not uniq:
            continue
        if kind == "colloc":
            colloc_out[concept] = uniq
        else:
            words_out[concept] = uniq

    # 本书高频特征词
    sig_list = [r["word"] for r in result.get("_all_signature", [])[:top_sig] if r.get("word")]
    if sig_list:
        words_out["本书高频特征词"] = sig_list

    # 先验高频但本书零频（雷区）
    zero_list = [r["term"] for r in result.get("_all_zero", [])[:top_zero] if r.get("term")]
    if zero_list:
        words_out["先验高频但本书零频（雷区）"] = zero_list

    return colloc_out, words_out


def export_stylefit_dir(result, export_dir):
    os.makedirs(export_dir, exist_ok=True)
    colloc_out, words_out = build_stylefit_exports(result)
    colloc_path = os.path.join(export_dir, "colloc.json")
    words_path = os.path.join(export_dir, "words.json")
    textio.write_json(colloc_path, colloc_out)
    textio.write_json(words_path, words_out)
    return colloc_path, words_path


def _resolve_corpus_and_cfg(config_path, corpus_path):
    cfg = {}
    if config_path:
        cfg = project.load(config_path)
    elif not corpus_path:
        cfg = project.load(None)
    elif os.path.isfile(project.CONFIG):
        try:
            cfg = project.load(project.CONFIG)
        except SystemExit:
            cfg = {}

    target = corpus_path
    if not target:
        chunks_dir = cfg["paths"]["chunks"]
        raw_all = os.path.join(cfg["paths"]["raw"], "_all.txt")
        if os.path.isfile(raw_all):
            target = raw_all
        elif os.path.isdir(chunks_dir):
            target = chunks_dir
        else:
            fallback_raw = os.path.join(ROOT, "work", "raw", "_all.txt")
            fallback_chunks = os.path.join(ROOT, "work", "chunks")
            target = fallback_raw if os.path.isfile(fallback_raw) else fallback_chunks
    return cfg, target


def format_report(result, corpus_path, file_count):
    meta = result["meta"]
    lines = [
        "=== 语料文风指纹挖掘报告（LLR / G²） ===",
        "语料：%s（%d 个文件 ｜ %s 汉字 ｜ %s 段 ｜ 扫描先验词项 %d 条）" % (
            corpus_path, file_count, format(meta["chars_cjk"], ","),
            format(meta["paragraphs"], ","), meta["prior_terms_checked"],
        ),
        "",
        "## 1. 正向文风指纹词（本书显著超配，obs > exp，Top %d / 共 %d）" % (
            len(result["positive_fingerprints"]), result["all_positive_count"]),
    ]
    if result["positive_fingerprints"]:
        lines.append("| # | 词项 | 语义概念 | 实际次数 | 期望次数 | 本书/10万字 | 先验/10万字 | 倍数 | G² |")
        lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|")
        for idx, r in enumerate(result["positive_fingerprints"], 1):
            lines.append("| %d | %s | %s | %d | %.1f | %.1f | %.1f | %.2fx | %.2f |" % (
                idx, r["term"], r["concept"], r["obs"], r["exp"],
                r["obs_per_100k"], r["prior_per_100k"], r["fold"], r["g2"]))
    else:
        lines.append("（未检测到正向超配词）")
    lines.append("")

    lines.append("## 2. 负向零频雷区（先验高频但本书 0 次，Top %d / 共 %d）" % (
        len(result["zero_freq_mines"]), result["all_zero_count"]))
    if result["zero_freq_mines"]:
        lines.append("| # | 零频雷区词 | 语义概念 | 期望次数 | 先验/10万字 | G² |")
        lines.append("|---:|---|---|---:|---:|---:|")
        for idx, r in enumerate(result["zero_freq_mines"], 1):
            lines.append("| %d | %s | %s | %.1f | %.1f | %.2f |" % (
                idx, r["term"], r["concept"], r["exp"], r["prior_per_100k"], r["g2"]))
    else:
        lines.append("（先验词项在本书均有出现）")
    lines.append("")

    lines.append("## 3. 本书高频特征词（纯本地实词统计，已排除配置人名/别名，Top %d）" % len(result["signature_words"]))
    if result["signature_words"]:
        lines.append(" ｜ ".join("%s(%d)" % (r["word"], r["count"]) for r in result["signature_words"]))
    else:
        lines.append("（语料偏短，未达到高频词阈值）")
    lines.append("")
    return "\n".join(lines)


def _public_json(result):
    return {k: v for k, v in result.items() if not k.startswith("_")}


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="基于对数似然比（LLR / G²）自动挖掘语料文风指纹与零频雷区")
    ap.add_argument("--config", default=None, help="project.json 路径（可选，用于读取人名/别名与默认语料）")
    ap.add_argument("--corpus", default=None, help="语料文件或目录（默认回退 work/raw/_all.txt 或 work/chunks）")
    ap.add_argument("--top", type=int, default=30, help="每类展示前 N 项（默认 30）")
    ap.add_argument("--export-dir", default=None, help="导出可直接用于 stylefit_dir 的 colloc.json 与 words.json")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="OUT.JSON",
                    help="输出结构化 JSON（不填路径则打印到标准输出，填路径则写入文件）")
    a = ap.parse_args()

    cfg, corpus_path = _resolve_corpus_and_cfg(a.config, a.corpus)
    raw, files = C.load_corpus(corpus_path)
    if not raw.strip():
        raise SystemExit("语料为空或不存在：%s" % corpus_path)

    exclude_terms = list(cfg.get("names") or [])
    for canon, alts in (cfg.get("aliases") or {}).items():
        if canon:
            exclude_terms.append(canon)
        for al in (alts or ()):
            if al:
                exclude_terms.append(al)
    for k in (cfg.get("anonymize_terms") or {}).keys():
        if k:
            exclude_terms.append(k)

    result = discover_style(raw, top=max(1, a.top), exclude_terms=exclude_terms)
    result["meta"]["corpus"] = corpus_path
    result["meta"]["files"] = len(files)

    exported = None
    if a.export_dir:
        cpath, wpath = export_stylefit_dir(result, a.export_dir)
        exported = {"colloc": cpath, "words": wpath}
        result["meta"]["exported"] = exported

    pub = _public_json(result)
    if a.json == "-":
        print(json.dumps(pub, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, corpus_path, len(files)))
        if exported:
            print("已导出 stylefit 词表：")
            print("  - %s" % exported["colloc"])
            print("  - %s" % exported["words"])
        if a.json:
            textio.write_json(a.json, pub)
            print("JSON 已写入：%s" % a.json)


if __name__ == "__main__":
    main()
