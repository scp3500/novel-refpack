#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_02_distill.py
抽取代表性对话片段，调用模型（或离线模板）蒸馏发言者的行为心理学与接话模式：
- 怎么接话（嘲讽、反问、抓字眼、复读、打岔）
- 情绪与态度基调（松弛、懒散、毒舌、拒绝客服化）
- 绝对禁区与负向特征
输出至 work/chat_behavior.json。
"""
import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import textio, llm, project


PROMPT_TEMPLATE = """你是一名敏锐的社交网络语言学与群体行为分析专家。
下面是一批从真实网络讨论（贴吧/群聊）中提取的高质量交互切片。

请深入分析这些真实人类在聊天时的「接话心理机制」和「语言交互模式」，提炼出 4 个维度的核心特征，直接输出简洁精练的分析总结（不要套大话空话，每条列出具体模式）：

1. 【接话与反问逻辑】：面对别人的提问、抱怨或长篇大论，他们通常如何反应？（如：抓字眼反问、一句话归因、直接嘲讽、答非所问、发问号等）
2. 【情绪与态度基调】：他们的整体心理状态是怎样的？（如：懒散摸鱼、不主动承担解释责任、下断言不端水、排斥说教等）
3. 【高频口语模式与口癖】：他们习惯使用哪些精练的表达句式？（如：“玩XX玩的”、“典”、“急了”、“有没有一种可能”等）
4. 【绝对禁忌（AI味反向特征）】：这群人在交流中绝对不会出现的表达方式是什么？（如：书面辩证法“不仅更是”、假客套“希望对你有帮助”、分点说明等）

【对话样本切片】：
{samples}
"""

OFFLINE_FALLBACK = {
    "接话与反问逻辑": [
        "极简归因：面对别人的长篇抱怨或提问，习惯用极短的一句话把原因归结到对方头上（例如：玩XX玩的、买XX买的）。",
        "抓字眼反问与反驳：不回答核心问题，直接挑出对方原话里最脆弱的一个词进行攻击或反问。",
        "敷衍与冷处理：面对不感兴趣或低级问题，只发单字、问号或直接丢一句‘不知道’、‘建议直接搜’。",
        "拒绝端水：有结论就直接下断言，从不搞‘客观来说/一方面另一方面’的辩证废话。"
    ],
    "情绪与态度基调": [
        "拒绝客服化：绝不为任何人服务，绝不迎合提问者，带有天然的防备心与距离感。",
        "松弛甚至带攻击性：情绪不亢奋、不热情，习惯以‘看乐子’、‘吐槽’或‘嘲弄’作为交流驱动力。",
        "零废话：坚决不打长篇大论，超过三句话没有爆点就会被视为废话。"
    ],
    "高频口语模式与口癖": [
        "定性类：典、急了、孝、串子、逆天。",
        "归因类：玩XX玩的、被XX洗脑了、纯属活该。",
        "反诘类：有没有一种可能、你是懂XX的、谁问你了。"
    ],
    "绝对禁忌（负向特征）": [
        "严禁使用公文过渡词：不仅……更是……、综上所述、总的来说、由此可见。",
        "严禁结尾假客套：希望这个回答对你有帮助、如果有其他疑问随时问我。",
        "严禁无实物的神态与长复合句。"
    ]
}


def pick_representative_samples(threads, max_k=15):
    samples = []
    # 优先挑有主楼 + 多个回复的线程
    good_threads = [t for t in threads if len(t.get("replies", [])) >= 2]
    good_threads.sort(key=lambda t: len(t.get("replies", [])), reverse=True)

    for t in good_threads[:max_k]:
        buf = ["[话题/主贴]: %s" % (t.get("topic") or t.get("title"))]
        for r in t.get("replies", [])[:4]:
            buf.append("  [回复]: %s" % r["text"])
        for sr in t.get("sub_replies", [])[:2]:
            buf.append("    [楼中楼对线]: %s" % sr["text"])
        samples.append("\n".join(buf))
    return samples


def main():
    parser = argparse.ArgumentParser(description="蒸馏接话行为与心理学特征")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--no-llm", action="store_true", help="纯离线运行，使用内置贴吧/群聊行为规则模板")
    args = parser.parse_args()

    cfg = project.load_chat_config(args.config)
    work_dir = project.chat_work_dir(cfg)
    threads_path = os.path.join(work_dir, "chat_threads.json")
    if not os.path.isfile(threads_path):
        sys.stderr.write("未找到 %s，请先运行 chat_00_clean.py\n" % threads_path)
        sys.exit(1)

    threads = textio.read_json(threads_path, [])
    samples = pick_representative_samples(threads, max_k=15)
    sample_text = "\n\n".join(samples)

    behavior_data = {}

    if args.no_llm:
        print("模式：--no-llm 离线模式，加载内置高拟真人格心理行为学模板")
        behavior_data = dict(OFFLINE_FALLBACK)
        behavior_data["_source"] = "offline_template"
    else:
        llm_cfg = cfg.get("llm") or {}

        try:
            print("调用模型蒸馏交互心理学特征（后台：%s，模型：%s）..." % (
                llm_cfg.get("backend", "openai"), llm_cfg.get("model", "default")))
            caller = llm.build(llm_cfg)
            prompt = PROMPT_TEMPLATE.format(samples=sample_text[:4000])
            res = caller(prompt, system="你是一名严谨的群体社交行为与语言学专家。")
            behavior_data = {
                "llm_analysis_raw": res,
                "_source": "llm_distilled"
            }
        except Exception as e:
            sys.stderr.write("调用模型失败（%s），自动降级为离线高质量模板。\n" % e)
            behavior_data = dict(OFFLINE_FALLBACK)
            behavior_data["_source"] = "offline_fallback"

    behavior_data["extracted_samples"] = samples[:8]

    out_path = os.path.join(work_dir, "chat_behavior.json")
    textio.write_json(out_path, behavior_data)
    print("行为心理学特征提炼完成，输出至：%s" % out_path)


if __name__ == "__main__":
    main()
