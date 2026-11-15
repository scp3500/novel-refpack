#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_03_build_prompt.py
将硬统计指标（chat_metrics.json）与行为心理特征（chat_behavior.json）
自动组装生成可直接复制给任意大模型使用的《群聊人设提示词.md》。
输出至 work/out/群聊人设提示词.md。
"""
import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import textio, project


def main():
    parser = argparse.ArgumentParser(description="组装生成群聊/贴吧人设提示词文件")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--name", default=None, help="人设角色名称（如：弱智吧老哥/群友）")
    parser.add_argument("--out", default=None, help="自定义输出文件路径")
    args = parser.parse_args()

    role_name = args.name or "贴吧老哥/老群友"
    cfg = project.load_chat_config(args.config)
    work_dir = project.chat_work_dir(cfg)

    metrics_p = os.path.join(work_dir, "chat_metrics.json")
    behavior_p = os.path.join(work_dir, "chat_behavior.json")

    if not os.path.isfile(metrics_p):
        sys.stderr.write("缺少 %s，请先运行 chat_01_metrics.py\n" % metrics_p)
        sys.exit(1)

    metrics = textio.read_json(metrics_p, {})
    behavior = textio.read_json(behavior_p, {}) if os.path.isfile(behavior_p) else {}

    z_finger = metrics.get("字数指纹", {})
    punc = metrics.get("每千字标点频率", {})
    starters = metrics.get("高频句首发语词", [])
    dead_words = metrics.get("零频黑名单_书面与AI词", [])

    p50 = z_finger.get("P50中位数", 8)
    p80 = z_finger.get("P80短句阈值", 18)
    p95 = z_finger.get("P95长句阈值", 35)

    L = []
    def P(s=""):
        L.append(s)

    P("# %s拟真人格 System Prompt（文风与规则包）" % role_name)
    P("")
    P("> 本提示词由真实人类社交对话语料通过 `novel-refpack` 逆向蒸馏生成。")
    P("> 复制粘贴下方内容至大模型的【系统提示词 / System Prompt】框中即可生效。")
    P("")
    P("---")
    P("")
    P("```markdown")
    P("【系统定位与身份】")
    P("你是一个真实的【%s】。" % role_name)
    P("你不是 AI 助手，不为任何人服务，严禁输出任何客服式问候、公文套话或多段总结。")
    P("")
    P("【硬性格式与节奏约束（基于语料统计）】")
    P("1. 篇幅极短：单次发言字数中位数严格限制在 %d~%d 字之间，超过 %d 字视为严重失败。绝不写复合长句与大段说明。" % (p50, p80, p95))
    P("2. 彻底禁用句号：人类在即时交流中几乎不打句号（语料出现率极低）。短暂停顿直接用【空格】代替，断句用换行代替。")
    P("3. 情绪符号：表达疑问直接用单问号（“？”）或多问号（“？？？”），不加任何主谓解释；感叹直接用“！”或不带标点。")
    if starters:
        top_words = "、".join(s["word"] for s in starters[:8])
        P("4. 高频发语词：发言时自然承接以下词汇起手：%s。" % top_words)
    P("")
    P("【接话与互动逻辑（行为心理约束）】")

    # 提取行为特征
    if "llm_analysis_raw" in behavior:
        P(behavior["llm_analysis_raw"].strip())
    else:
        logics = behavior.get("接话与反问逻辑", [])
        attitudes = behavior.get("情绪与态度基调", [])
        for item in logics:
            P("- %s" % item)
        for item in attitudes:
            P("- %s" % item)

    P("")
    P("【负向禁令清单（绝对禁用 AI 腔）】")
    P("严禁出现以下任何书面词、辩证连接词及客服套话：")
    bans = ["不仅……更是……", "总的来说", "综上所述", "值得注意的是", "希望对你有所帮助", "如果还有其他问题", "从某种程度上来说"]
    if dead_words:
        bans.extend(dead_words[:10])
    P("- 禁用词表：%s" % "、".join(list(dict.fromkeys(bans))))
    P("- 严禁在结尾进行任何升华、总结或礼貌收尾。")
    P("")
    P("【真实人类对白范例（Few-shot）】")
    samples = behavior.get("extracted_samples", [])
    if samples:
        for idx, s in enumerate(samples[:6], 1):
            P("### 范例 %d" % idx)
            P(s.strip())
            P("")
    else:
        P("[用户]: 这个方案怎么样？")
        P("[回复]: 槽点太多不知道从哪开始喷")
        P("")
        P("[用户]: 为什么天天报错？")
        P("[回复]: 建议重开")
    P("```")
    P("")

    out_dir = os.path.join(work_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    out_file = args.out or os.path.join(out_dir, "群聊人设提示词.md")

    textio.write_text(out_file, "\n".join(L).strip() + "\n")
    print("\n成功生成人设提示词成品！")
    print("→ 输出路径：%s" % out_file)


if __name__ == "__main__":
    main()
