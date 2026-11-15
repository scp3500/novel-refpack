#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_00_clean.py
解析贴吧 JSON 或群聊导出 TXT，清洗无意义刷屏与纯水楼，
输出标准化的会话与对线线程结构到 work/chat_threads.json。
"""
import os
import re
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import textio, project


def load_chat_config(path=None):
    p = path or os.environ.get("CHAT_CONFIG")
    if not p:
        cand = os.path.join(ROOT, "config", "chat.json")
        if os.path.isfile(cand):
            p = cand
        else:
            p = os.path.join(ROOT, "config", "chat.example.json")
    if not os.path.isfile(p):
        sys.stderr.write("未找到配置文件：%s\n" % p)
        sys.exit(2)
    cfg = textio.read_json(p, {}) or {}
    cfg["_path"] = p
    return cfg


def is_dropped_text(text, patterns, min_c, max_c):
    t = text.strip()
    if not t or len(t) < min_c or len(t) > max_c:
        return True
    for pat in patterns:
        if re.search(pat, t):
            return True
    return False


def clean_tieba(data, cfg):
    title_drops = [re.compile(p) for p in cfg.get("drop_title_patterns", [])]
    text_drops = cfg.get("drop_text_patterns", [])
    min_c = cfg.get("min_chars", 2)
    max_c = cfg.get("max_chars", 300)
    target_user = cfg.get("target_user", "").strip()

    threads = []
    dropped_posts = 0
    dropped_comments = 0

    for item in data:
        title = (item.get("title") or "").strip()
        if any(p.search(title) for p in title_drops):
            dropped_posts += 1
            continue

        raw_comments = item.get("comments") or []
        if not raw_comments:
            continue

        # 找到 1 楼作为主贴背景
        floor_1_text = ""
        other_comments = []
        for c in raw_comments:
            f = str(c.get("floor", ""))
            txt = (c.get("text") or "").strip()
            author = (c.get("author") or "").strip()

            if f == "1":
                floor_1_text = txt
                continue

            if is_dropped_text(txt, text_drops, min_c, max_c):
                dropped_comments += 1
                continue

            if target_user and author != target_user:
                continue

            other_comments.append({
                "floor": f,
                "author": author,
                "text": txt
            })

        if not other_comments and not floor_1_text:
            continue

        # 区分主楼回复与楼中楼交火
        main_replies = [c for c in other_comments if not str(c["floor"]).endswith("L")]
        sub_replies = [c for c in other_comments if str(c["floor"]).endswith("L")]

        threads.append({
            "tid": item.get("tid"),
            "title": title,
            "topic": floor_1_text or title,
            "replies": main_replies,
            "sub_replies": sub_replies,
            "total_valid_replies": len(other_comments)
        })

    return threads, dropped_posts, dropped_comments


def clean_qq_txt(raw_text, cfg):
    # 标准 QQ 格式：2024-01-01 12:00:00 昵称 或 昵称 12:00:00
    head_re = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2})\s+([^\(\n]+)")
    lines = raw_text.splitlines()

    msgs = []
    cur_who = ""
    cur_text = []

    for line in lines:
        m = head_re.match(line)
        if m:
            if cur_who and cur_text:
                msgs.append({"author": cur_who, "text": "\n".join(cur_text).strip()})
            cur_who = m.group(2).strip()
            cur_text = []
        else:
            if line.strip():
                cur_text.append(line.strip())

    if cur_who and cur_text:
        msgs.append({"author": cur_who, "text": "\n".join(cur_text).strip()})

    text_drops = cfg.get("drop_text_patterns", [])
    min_c = cfg.get("min_chars", 2)
    max_c = cfg.get("max_chars", 300)
    target_user = (cfg.get("target_user") or "").strip()

    # 简单切 Session：每 15 条切一段
    sessions = []
    chunk = []
    for m in msgs:
        if target_user and m["author"] != target_user:
            continue
        if is_dropped_text(m["text"], text_drops, min_c, max_c):
            continue
        chunk.append(m)
        if len(chunk) >= 15:
            sessions.append({
                "tid": len(sessions) + 1,
                "title": chunk[0]["text"][:20],
                "topic": chunk[0]["text"],
                "replies": chunk[1:],
                "sub_replies": [],
                "total_valid_replies": len(chunk) - 1
            })
            chunk = []
    if chunk:
        sessions.append({
            "tid": len(sessions) + 1,
            "title": chunk[0]["text"][:20],
            "topic": chunk[0]["text"],
            "replies": chunk[1:],
            "sub_replies": [],
            "total_valid_replies": len(chunk) - 1
        })
    return sessions, 0, 0


def main():
    parser = argparse.ArgumentParser(description="清洗贴吧/群聊语料并提取结构化对话")
    parser.add_argument("--config", default=None, help="指定配置文件路径")
    parser.add_argument("--source", default=None, help="覆盖源文件路径")
    args = parser.parse_args()

    cfg = project.load_chat_config(args.config)
    source = args.source or cfg.get("source", "")
    if not os.path.isabs(source):
        source = os.path.join(ROOT, source)

    if not os.path.isfile(source):
        sys.stderr.write("输入文件不存在：%s\n" % source)
        sys.exit(1)

    fmt = cfg.get("format", "tieba_json")
    print("读取源数据：%s（格式：%s）" % (source, fmt))

    if fmt == "tieba_json":
        data = textio.read_json(source, [])
        threads, d_posts, d_comments = clean_tieba(data, cfg)
    else:
        text = textio.read_text(source)
        threads, d_posts, d_comments = clean_qq_txt(text, cfg)

    work_dir = project.chat_work_dir(cfg)
    os.makedirs(work_dir, exist_ok=True)
    out_path = os.path.join(work_dir, "chat_threads.json")

    textio.write_json(out_path, threads)
    total_replies = sum(t["total_valid_replies"] for t in threads)
    print("清洗完成：保留 %d 个有效会话/话题，共 %d 条发言。" % (len(threads), total_replies))
    if d_posts or d_comments:
        print("  - 过滤纯水帖/无效帖：%d 个" % d_posts)
        print("  - 过滤纯数字/刷屏回复：%d 条" % d_comments)
    print("→ 输出至：%s" % out_path)


if __name__ == "__main__":
    main()
