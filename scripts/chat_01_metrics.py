#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_01_metrics.py
纯 Python 离线统计群聊/贴吧发言的硬指标指纹：
- 单条字数分布（中位数、P80、P95）
- 标点习惯（句号率、空格断句率、问号/感叹号）
- 句首发语词 Top 30
- 贴吧用词表匹配与零频词（结合 config/stylefit_tieba/words.json）
输出至 work/chat_metrics.json。
"""
import os
import re
import sys
import json
import argparse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import textio


def percentile(arr, p):
    if not arr:
        return 0
    k = (len(arr) - 1) * p
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    d = k - f
    return arr[f] + (arr[c] - arr[f]) * d


def main():
    parser = argparse.ArgumentParser(description="统计群聊/贴吧语言硬指标指纹")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args()

    threads_path = os.path.join(ROOT, "work", "chat_threads.json")
    if not os.path.isfile(threads_path):
        sys.stderr.write("未找到 %s，请先运行 chat_00_clean.py\n" % threads_path)
        sys.exit(1)

    threads = textio.read_json(threads_path, [])
    if not threads:
        sys.stderr.write("无有效会话数据\n")
        sys.exit(1)

    all_texts = []
    for t in threads:
        for r in t.get("replies", []):
            if r.get("text"):
                all_texts.append(r["text"].strip())
        for r in t.get("sub_replies", []):
            if r.get("text"):
                all_texts.append(r["text"].strip())

    total_msgs = len(all_texts)
    total_chars = sum(len(t) for t in all_texts)
    lengths = sorted(len(t) for t in all_texts)

    p50 = percentile(lengths, 0.50)
    p80 = percentile(lengths, 0.80)
    p95 = percentile(lengths, 0.95)
    avg_len = total_chars / total_msgs if total_msgs else 0

    # 标点符号统计（每千字发生频次）
    scale = (total_chars / 1000.0) if total_chars else 1.0
    punc_counts = {
        "句号。": sum(t.count("。") for t in all_texts),
        "逗号，": sum(t.count("，") + t.count(",") for t in all_texts),
        "空格（代替逗号）": sum(t.count(" ") for t in all_texts),
        "问号？": sum(t.count("？") + t.count("?") for t in all_texts),
        "感叹号！": sum(t.count("！") + t.count("!") for t in all_texts),
        "波浪号~": sum(t.count("~") + t.count("～") for t in all_texts),
    }
    punc_per_k = {k: round(v / scale, 2) for k, v in punc_counts.items()}

    # 句首发语词统计（取前 2~4 个字符作为特征）
    starter_counter = Counter()
    for t in all_texts:
        m = re.match(r"^([^\w\s]{1,3}|[\u4e00-\u9fa5]{1,4}|[a-zA-Z]{1,5})", t)
        if m:
            starter = m.group(1).strip()
            if starter:
                starter_counter[starter] += 1
    top_starters = [
        {"word": w, "count": c}
        for w, c in starter_counter.most_common(30)
        if c >= 2
    ]

    # 贴吧特定用词表统计
    words_cfg_path = os.path.join(ROOT, "config", "stylefit_tieba", "words.json")
    word_stats = {}
    dead_words = []
    if os.path.isfile(words_cfg_path):
        words_def = textio.read_json(words_cfg_path, {})
        full_blob = "\n".join(all_texts)
        for cat, wlist in words_def.items():
            if cat.startswith("_"):
                continue
            cat_stat = {}
            for w in wlist:
                cnt = full_blob.count(w)
                cat_stat[w] = cnt
                if cnt == 0 and cat in ("书面词（贴吧少用）", "AI 腔（贴吧少用）"):
                    dead_words.append(w)
            word_stats[cat] = cat_stat

    metrics = {
        "语料规模": {
            "总消息数": total_msgs,
            "总字符数": total_chars,
            "话题数": len(threads)
        },
        "字数指纹": {
            "均长": round(avg_len, 1),
            "P50中位数": int(p50),
            "P80短句阈值": int(p80),
            "P95长句阈值": int(p95)
        },
        "每千字标点频率": punc_per_k,
        "高频句首发语词": top_starters[:20],
        "用词表命中": word_stats,
        "零频黑名单_书面与AI词": dead_words
    }

    out_path = os.path.join(ROOT, "work", "chat_metrics.json")
    textio.write_json(out_path, metrics)

    print("硬指标统计完成：")
    print("  - 消息均长：%s 字 ｜ P50：%d 字 ｜ P80：%d 字" % (
        round(avg_len, 1), int(p50), int(p80)))
    print("  - 每千字句号：%.1f ｜ 空格断句：%.1f ｜ 问号：%.1f" % (
        punc_per_k["句号。"], punc_per_k["空格（代替逗号）"], punc_per_k["问号？"]))
    print("  - 高频发语词 Top 5：%s" % "、".join(s["word"] for s in top_starters[:5]))
    print("→ 输出至：%s" % out_path)


if __name__ == "__main__":
    main()
