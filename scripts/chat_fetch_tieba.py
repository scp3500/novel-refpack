#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_fetch_tieba.py
通过 aiotieba 直接拉取指定贴吧的热门帖子及楼中楼回复，
输出标准格式的贴吧评论 JSON 文件供 chat_run 流水线使用。

使用方式：
  python scripts/chat_fetch_tieba.py --tieba 弱智吧 --count 20
"""
import os
import sys
import json
import time
import asyncio
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import textio


async def fetch_forum_data(forum_name, thread_count=20, max_floors=10):
    try:
        import aiotieba
    except ImportError:
        sys.stderr.write("未安装 aiotieba，请先执行 pip install aiotieba\n")
        sys.exit(1)

    print(f"正在连接百度贴吧，拉取【{forum_name}】的前排热门贴...")
    comments_data = []

    async with aiotieba.Client() as c:
        # 获取贴吧前排帖子（按默认/回复排序）
        threads = await c.get_threads(forum_name, pn=1, rn=max(30, thread_count))
        if not threads:
            print(f"未获取到【{forum_name}】的帖子，请检查吧名是否正确。")
            return []

        # 按回复数排序，优先提取讨论最热烈的帖子
        hot_threads = sorted(threads, key=lambda t: t.reply_num, reverse=True)[:thread_count]
        print(f"成功获取 {len(hot_threads)} 个热门主题帖，开始拉取各楼层与楼中楼...")

        for idx, h in enumerate(hot_threads, 1):
            try:
                post_comments = []
                posts_result = await c.get_posts(h.tid, rn=max_floors)

                for p in posts_result:
                    text = (p.text or "").strip()
                    if text:
                        author = p.user.user_name if p.user else ""
                        post_comments.append({
                            "floor": p.floor,
                            "author": author,
                            "text": text[:300]
                        })

                    # 楼中楼拉取
                    if getattr(p, "reply_num", 0) > 0:
                        try:
                            subs = await c.get_comments(h.tid, p.pid)
                            for cm in subs[:3]:
                                cm_text = (cm.text or "").strip()
                                if cm_text:
                                    post_comments.append({
                                        "floor": f"{p.floor}L",
                                        "author": cm.user.user_name if cm.user else "",
                                        "text": cm_text[:200]
                                    })
                        except Exception:
                            pass

                comments_data.append({
                    "tid": h.tid,
                    "title": h.title,
                    "reply_num": h.reply_num,
                    "comments": post_comments
                })
                print(f"[{idx}/{len(hot_threads)}] 抓取成功：{h.title[:30]} ({len(post_comments)}条回复)")
            except Exception as e:
                print(f"[{idx}/{len(hot_threads)}] 抓取跳过：{h.title[:20]} ({e})")

            await asyncio.sleep(0.2)

    return comments_data


def main():
    parser = argparse.ArgumentParser(description="拉取指定贴吧的帖子与回复语料")
    parser.add_argument("--tieba", required=True, help="贴吧名称（如：弱智吧、孙笑川吧）")
    parser.add_argument("--count", type=int, default=25, help="拉取热门主题帖数量 (默认 25)")
    parser.add_argument("--out", default=None, help="输出文件路径")
    args = parser.parse_args()

    forum = args.tieba.replace("吧", "")
    data = asyncio.run(fetch_forum_data(forum, thread_count=args.count))
    if not data:
        sys.exit(1)

    work_dir = os.path.join(ROOT, "work")
    os.makedirs(work_dir, exist_ok=True)
    out_file = args.out or os.path.join(work_dir, f"tieba_{forum}.json")

    textio.write_json(out_file, data)
    print(f"\n抓取完成！共抓取 {len(data)} 个主题帖数据。")
    print(f"→ 保存至：{out_file}")


if __name__ == "__main__":
    main()
