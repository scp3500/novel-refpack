#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style-fit · 查询接口。写之前先查，别靠语感。

  python stylefit/query.py --index cache/mybook/index.json --list
  python stylefit/query.py --index ... --who 白夜 [--func 让步接受]
  python stylefit/query.py --index ... --colloc [概念]
  python stylefit/query.py --index ... --dict [场景]      # 场景词典
  python stylefit/query.py --index ... --why <描写意图>
  python stylefit/query.py --index ... --scene <场景>
  python stylefit/query.py --index ... --words
  python stylefit/query.py --index ... --stats
  python stylefit/query.py --index ... --zero
"""
import os
import sys
import json
import argparse
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def head(t):
    print("\n" + "─" * 76 + "\n" + t + "\n" + "─" * 76)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--who")
    ap.add_argument("--func")
    ap.add_argument("--colloc", nargs="?", const="__all__")
    ap.add_argument("--dict", nargs="?", const="__all__", dest="dict_",
                    help="场景词典：某类场景在书里用什么词")
    ap.add_argument("--why")
    ap.add_argument("--scene")
    ap.add_argument("--words", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--zero", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    X = json.load(open(a.index, encoding="utf-8"))

    if a.list:
        head("可用项")
        print("人物：", "、".join(X["台词"].keys()))
        print("意图：", "、".join(X["描写"].keys()))
        print("搭配：", "、".join(X["搭配"].keys()))
        print("场景：", "、".join(X["场景"].keys()))
        return

    if a.zero:
        head("零频黑名单（全书 0 次，禁用）")
        z = X["零频词"]
        for i in range(0, len(z), 6):
            print("  " + "　".join(z[i:i + 6]))
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
