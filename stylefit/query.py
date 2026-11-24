#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style-fit · 查询接口与单角色语音卡导出。写之前先查，别靠语感。

  python stylefit/query.py --index cache/mybook/index.json --list
  python stylefit/query.py --index ... --who 主角 [--func 让步接受]
  python stylefit/query.py --index ... --who 主角 --export-card [card.md]
  python stylefit/query.py --index ... --colloc [概念]
  python stylefit/query.py --index ... --dict [场景]      # 场景词典
  python stylefit/query.py --index ... --why <描写意图>
  python stylefit/query.py --index ... --craft [笔法类别]
  python stylefit/query.py --index ... --scene <场景>
  python stylefit/query.py --index ... --words
  python stylefit/query.py --index ... --top-words [40]   # 本书高频特征词
  python stylefit/query.py --index ... --stats
  python stylefit/query.py --index ... --zero
"""
import os
import re
import sys
import json
import argparse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus as C, textio, budget          # noqa: E402

SELF_WORDS = ["我", "咱", "俺", "老子", "本大爷", "本人", "人家",
              "妾身", "本机", "老夫", "小女子", "在下"]


def head(t):
    print("\n" + "─" * 76 + "\n" + t + "\n" + "─" * 76)


def build_voice_card(X, who, attrib_path=None, target_kb=8.0):
    """生成 5–10 KB 单角色语音卡（Markdown）：台词靶、自称、称呼表、句尾口癖、各功能桶精选例句与分期变化。"""
    bs = (X.get("台词") or {}).get(who)
    if not bs:
        return None

    all_samples = []
    for func, b in bs.items():
        all_samples.extend(b.get("样本") or [])

    # 若提供 attrib.json，用全量台词计算精准指标与早/中/后分期变化
    pairs = C.load_attribution(attrib_path) if attrib_path else None
    who_lines = [t.strip() for w, t in (pairs or []) if w == who and len(re.sub(r"\s", "", t)) >= 2]
    lines_for_stat = who_lines if who_lines else all_samples
    n_total = len(who_lines) if who_lines else sum(b.get("n", 0) for b in bs.values())

    lens = sorted(len(x) for x in lines_for_stat)
    avg_len = sum(lens) / max(1, len(lens))
    med_len = lens[len(lens) // 2] if lens else 0
    le19 = sum(1 for x in lens if x <= 19) / max(1, len(lens))
    qm_r = sum(1 for t in lines_for_stat if "？" in t or "?" in t) / max(1, len(lines_for_stat))
    ex_r = sum(1 for t in lines_for_stat if "！" in t or "!" in t) / max(1, len(lines_for_stat))
    el_r = sum(1 for t in lines_for_stat if "…" in t) / max(1, len(lines_for_stat))

    self_cnt = Counter()
    for w in SELF_WORDS:
        c = sum(t.count(w) for t in lines_for_stat)
        if c:
            self_cnt[w] = c

    tail = Counter()
    for t in lines_for_stat:
        s = re.sub(r"[。！？…~\s]+$", "", t)
        if s:
            for ch in (s[-1:], s[-2:]):
                if re.search(r"[\u4e00-\u9fff]", ch):
                    tail[ch] += 1
    top_tails = [(w, c) for w, c in tail.most_common(12) if c >= 2][:8]

    # 称呼表：看此角色提到哪些其他已知角色，以及谁常提此角色
    known_chars = list((X.get("台词") or {}).keys())
    mentions_other = Counter()
    mentioned_by = Counter()
    if pairs:
        for w, t in pairs:
            if w == who:
                for other in known_chars:
                    if other != who and other in t:
                        mentions_other[other] += 1
            elif who in t:
                mentioned_by[w] += 1

    out = [
        "# 角色语音卡 · %s" % who,
        "",
        "> 定位：单角色高浓缩台词参考卡（目标 5–10 KB），适合同人、角色扮演与群像对话对齐。",
        "> 护栏：请学习句长、句尾口癖与回应节奏，严禁直接照抄例句。",
        "",
        "## 一 · 语音统计靶",
        "- 总台词量：%d 条（统计样本 %d 条）" % (n_total, len(lines_for_stat)),
        "- 句长特征：均长 `%.1f` 字 ｜ 中位 `%d` 字 ｜ ≤19 字占比 `%.0f%%`" % (avg_len, med_len, le19 * 100),
        "- 标点偏好：问号率 `%.0f%%` ｜ 感叹率 `%.0f%%` ｜ 省略号率 `%.0f%%`" % (qm_r * 100, ex_r * 100, el_r * 100),
    ]
    if self_cnt:
        out.append("- 自称偏好：%s" % " ｜ ".join("%s %d" % x for x in self_cnt.most_common(6)))
    if top_tails:
        out.append("- 高频句尾口癖：%s" % " ｜ ".join("%s %d" % x for x in top_tails))
    if mentions_other:
        out.append("- 常提起谁：%s" % " ｜ ".join("%s %d" % x for x in mentions_other.most_common(6)))
    if mentioned_by:
        out.append("- 谁常提他：%s" % " ｜ ".join("%s %d" % x for x in mentioned_by.most_common(6)))
    out.append("")

    # 分期变化（早/中/后三段）
    if len(who_lines) >= 30:
        out.append("## 二 · 全书分期语音变化（早 / 中 / 后）")
        n = len(who_lines)
        for label, lo, hi in (("早期", 0, n // 3), ("中期", n // 3, 2 * n // 3), ("后期", 2 * n // 3, n)):
            seg = who_lines[lo:hi]
            if not seg:
                continue
            avg_s = sum(len(x) for x in seg) / len(seg)
            q_s = sum(1 for t in seg if "？" in t) / len(seg) * 100
            e_s = sum(1 for t in seg if "！" in t) / len(seg) * 100
            el_s = sum(1 for t in seg if "…" in t) / len(seg) * 100
            out.append("- **%s**（%d 条）：均长 %.1f 字 ｜ 问 %.0f%% ｜ 叹 %.0f%% ｜ 省 %.0f%%" % (
                label, len(seg), avg_s, q_s, e_s, el_s))
        out.append("")

    out.append("## 三 · 各话语功能桶精选例句")
    for func, b in bs.items():
        out.append("### %s（%d 条 ｜ 中位 %d 字）" % (func, b["n"], b["中位长度"]))
        for s in (b.get("样本") or [])[:8]:
            out.append("- %s" % s)
        out.append("")

    card = "\n".join(out).strip() + "\n"
    if target_kb and budget.utf8_kb(card) > target_kb * 1.15:
        card = budget.trim_to_utf8_bytes(card, target_kb)
    return card


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--attrib", default=None, help="可选 attrib.json，用于 --export-card 分期与称呼表统计")
    ap.add_argument("--who")
    ap.add_argument("--func")
    ap.add_argument("--export-card", nargs="?", const="-", default=None,
                    help="导出单角色语音卡（配合 --who，传路径写文件，不传路径打印到终端）")
    ap.add_argument("--card-kb", type=float, default=9.0, help="单角色语音卡目标体积 KB（默认 9.0）")
    ap.add_argument("--colloc", nargs="?", const="__all__")
    ap.add_argument("--dict", nargs="?", const="__all__", dest="dict_",
                    help="场景词典：某类场景在书里用什么词")
    ap.add_argument("--why")
    ap.add_argument("--craft", nargs="?", const="__all__")
    ap.add_argument("--scene")
    ap.add_argument("--words", action="store_true")
    ap.add_argument("--top-words", nargs="?", const=50, type=int, default=None,
                    help="查看本书高频特征词 Top-N（默认 50）")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--zero", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    X = json.load(open(a.index, encoding="utf-8"))

    if a.list:
        head("可用项")
        print("人物：", "、".join(X["台词"].keys()))
        print("意图：", "、".join(X["描写"].keys()))
        print("笔法细节：", "、".join(X.get("笔法细节", {}).keys()))
        print("搭配：", "、".join(X["搭配"].keys()))
        print("场景：", "、".join(X["场景"].keys()))
        print("高频词数量：", len(X.get("高频词") or []))
        return

    if a.top_words is not None:
        tw = X.get("高频词") or []
        head("本书高频特征词 Top-%d（供模型写作参考）" % min(a.top_words, len(tw)))
        if not tw:
            print("  索引中暂无高频词，请重新运行 scripts/07_stylefit_index.py")
            return
        rows = tw[:a.top_words]
        for i in range(0, len(rows), 5):
            chunk = rows[i:i + 5]
            print("  " + "　".join("%s(%d)" % (x["词"], x["次数"]) for x in chunk))
        return

    if a.zero:
        head("零频黑名单（全书 0 次，禁用）")
        z = X["零频词"]
        for i in range(0, len(z), 6):
            print("  " + "　".join(z[i:i + 6]))
        return

    if a.export_card is not None:
        if not a.who:
            print("使用 --export-card 需要同时指定 --who <角色名>")
            return
        card = build_voice_card(X, a.who, attrib_path=a.attrib, target_kb=a.card_kb)
        if card is None:
            print("没有这个人：%s（可用：%s）" % (a.who, "、".join(X["台词"].keys())))
            return
        if a.export_card == "-":
            print(card)
        else:
            textio.write_text(a.export_card, card)
            print("角色语音卡已写入：%s（%.1f KB）" % (a.export_card, budget.utf8_kb(card)))
        return

    if a.who:
        bs = X["台词"].get(a.who)
        if not bs:
            print("没有这个人：%s（可用：%s）" % (a.who, "、".join(X["台词"].keys())))
            return
        keys = [a.func] if a.func else list(bs.keys())
        for k in keys:
            b = bs.get(k)
            if not b:
                print("没有这个桶：%s（可用：%s）" % (k, "、".join(bs.keys())))
                continue
            head("%s · %s（%d 条，中位 %d 字）" % (a.who, k, b["n"], b["中位长度"]))
            for s in b["样本"]:
                print("  " + s)
        return

    if a.dict_:
        D = X.get("场景词典", {})
        keys = list(D.keys()) if a.dict_ == "__all__" else [k for k in D if a.dict_ in k]
        if not keys:
            print("没有这个场景：%s（可用：%s）" % (a.dict_, "、".join(D.keys())))
            return
        for c in keys:
            head("场景词典 · %s" % c)
            d = D[c]
            hot = [(w, n) for w, n in d.items() if n >= 6]
            cold = [(w, n) for w, n in d.items() if 0 < n < 6]
            dead = [w for w, n in d.items() if n == 0]
            if hot:
                print("  常用： " + "　".join("%s %d" % x for x in sorted(hot, key=lambda x: -x[1])))
            if cold:
                print("  少用： " + "　".join("%s %d" % x for x in sorted(cold, key=lambda x: -x[1])))
            if dead:
                print("  禁用： " + "　".join(dead))
        return

    if a.colloc:
        coll = X["搭配"]
        keys = list(coll.keys()) if a.colloc == "__all__" else [a.colloc]
        for c in keys:
            d = coll.get(c)
            if not d:
                print("没有这个概念：%s（可用：%s）" % (c, "、".join(coll.keys())))
                continue
            head("搭配 · %s" % c)
            for w, n in sorted(d.items(), key=lambda kv: -kv[1]):
                mark = "  ← 全书 0 次，禁用" if n == 0 else ("  （仅 %d 次，慎用）" % n if n <= 3 else "")
                print("    %-14s %4d%s" % (w, n, mark))
        return

    if a.why:
        d = X["描写"].get(a.why)
        if not d:
            print("没有这个意图：%s（可用：%s）" % (a.why, "、".join(X["描写"].keys())))
            return
        head("描写意图 · %s（原书 %d 处）" % (a.why, d["n"]))
        for s in d["样本"]:
            print("  " + s)
        return

    if a.craft:
        C_ = X.get("笔法细节", {})
        if not C_:
            print("索引中没有笔法细节，请用新版 build_index.py 重建索引")
            return
        keys = list(C_.keys()) if a.craft == "__all__" else [a.craft]
        for k in keys:
            items = C_.get(k)
            if items is None:
                print("没有这个笔法类别：%s（可用：%s）" % (k, "、".join(C_.keys())))
                continue
            head("笔法细节 · %s（采样 %d 条）" % (k, len(items)))
            for s in items:
                print("  " + s)
        return

    if a.scene:
        d = X["场景"].get(a.scene)
        if not d:
            print("没有这个场景：%s（可用：%s）" % (a.scene, "、".join(X["场景"].keys())))
            return
        head("场景 · %s（%d 段）" % (a.scene, d["n"]))
        for s in d["样本"]:
            print("  " + s.replace("\n", "\n  ") + "\n")
        return

    if a.words:
        head("用词表（概念 → 书里的说法 / 次数）")
        for c, d in X["用词"].items():
            print("  %-12s %s" % (c, " ｜ ".join(
                "%s %d%s" % (w, n, " ❌" if n == 0 else "") for w, n in d.items())))
        if X.get("高频词"):
            head("本书高频特征词（Top 30）")
            print("  " + "　".join("%s(%d)" % (x["词"], x["次数"]) for x in X["高频词"][:30]))
        head("零频黑名单")
        print("  " + "、".join(X["零频词"]))
        return

    if a.stats:
        head("统计靶")
        for k, v in X["统计"].items():
            print("  %s: %s" % (k, v))
        return

    head("style-fit 查询")
    print(__doc__)


if __name__ == "__main__":
    main()
