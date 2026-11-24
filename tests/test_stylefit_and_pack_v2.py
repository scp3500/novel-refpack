# -*- coding: utf-8 -*-
"""针对配置解耦、全量对白桶、本书高频词、防串台打包、交互规模选择、语音卡与 POV 分桶的单元测试。"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import budget, corpus as C, project, textio  # noqa: E402
from tests.helpers import load_script  # noqa: E402


class TestStylefitAndPackV2(unittest.TestCase):
    def test_parse_size_choice_and_interactive_prompt(self):
        self.assertEqual(budget.parse_size_choice(""), ("standard", None))
        self.assertEqual(budget.parse_size_choice("1"), ("compact", None))
        self.assertEqual(budget.parse_size_choice("3"), ("rich", None))
        self.assertEqual(budget.parse_size_choice("4"), ("full", None))
        self.assertEqual(budget.parse_size_choice("120"), (None, 120.0))
        self.assertEqual(budget.parse_size_choice("85kb"), (None, 85.0))
        self.assertEqual(budget.parse_size_choice("0"), ("full", None))

        ns = argparse.Namespace(preset=None, kb=None, max_tokens=None, yes=False)
        p, kb = budget.prompt_budget_interactive(ns, cfg={}, force=True, input_fn=lambda _: "110kb")
        self.assertIsNone(p)
        self.assertEqual(kb, 110.0)
        self.assertEqual(ns.kb, 110.0)

        # 指定 --yes 且非 force 时不触发询问
        ns2 = argparse.Namespace(preset=None, kb=None, max_tokens=None, yes=True)
        called = []
        budget.prompt_budget_interactive(ns2, cfg={}, force=False, input_fn=lambda _: called.append(1) or "1")
        self.assertEqual(called, [])

    def test_attrib_nested_quotes_and_galgame_script(self):
        mod = load_script("06_build_attrib.py")
        attr = mod.make_attributor(["春希", "雪菜"])
        lines = [
            "雪菜说道：「平常你马上就会说『活该！』，现在却睡昏头了吗？」",
            "【春希】那只是因为昨天排练太晚了。",
        ]
        pairs = attr(lines)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0]["who"], "雪菜")
        self.assertEqual(pairs[0]["text"], "平常你马上就会说『活该！』，现在却睡昏头了吗？")
        self.assertEqual(pairs[1]["who"], "春希")
        self.assertEqual(pairs[1]["text"], "那只是因为昨天排练太晚了。")

    def test_style_only_full_dialogue_buckets_top_words_pov_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as td:
            sf_dir = os.path.join(td, "sf_custom")
            os.makedirs(sf_dir, exist_ok=True)
            textio.write_json(os.path.join(sf_dir, "topics.json"), {
                "音乐室与排练": "(音乐室|吉他|钢琴|排练|合唱)"
            })
            textio.write_json(os.path.join(sf_dir, "colloc.json"), {
                "视线": ["移开视线", "别开视线", "抬起眼"]
            })
            textio.write_json(os.path.join(sf_dir, "words.json"), {
                "情绪": ["犹豫", "不安", "无语"]
            })
            textio.write_json(os.path.join(sf_dir, "intents.json"), {
                "沉默": "(沉默|移开视线|别开视线)"
            })
            textio.write_json(os.path.join(sf_dir, "scenes.json"), {
                "日常": ["音乐室", "吉他", "咖啡"]
            })

            # 构造混合第一/三人称且 90% 为裸对白的语料
            paras = ["# 第一卷 冬日练习", "## 第一章 音乐室"]
            for i in range(25):
                paras.append("我推开第二音乐室的木门，窗外的夕阳照在钢琴和吉他上，我心里有些犹豫，只好移开视线。")
                paras.append("「今天的排练从副歌开始吧，别再走神了。」")
                paras.append("「嗯，知道了，那就先试一遍旋律。」")
                paras.append("「为什么刚才那一节突然停下来了？」")
            for i in range(15):
                paras.append("她站在峰城大学附属高中门口，看着雪菜的背影轻轻叹了口气，手指握紧乐谱转身走开。")
                paras.append("「真是拿你没办法，每次都在音乐室拖到天黑。」")
            # 仅给 3 条显式归属对白，模拟 5% 归属覆盖率
            paras.append("春希说道：「明天见，记得带吉他。」")
            paras.append("雪菜问道：「你真的不一起去喝咖啡吗？」")
            paras.append("春希答道：「我先把排练清单整理好。」")

            chunks_dir = os.path.join(td, "work", "chunks")
            raw_dir = os.path.join(td, "work", "raw")
            out_dir = os.path.join(td, "work", "out")
            cache_dir = os.path.join(td, "work", "cache")
            os.makedirs(chunks_dir, exist_ok=True)
            os.makedirs(raw_dir, exist_ok=True)
            body = "\n".join(paras) + "\n"
            textio.write_text(os.path.join(raw_dir, "_all.txt"), body)
            textio.write_text(os.path.join(chunks_dir, "chunk_01.txt"), body)

            cfg_path = os.path.join(td, "project.json")
            textio.write_json(cfg_path, {
                "name": "wa2_unit",
                "source": os.path.join(raw_dir, "_all.txt"),
                "names": ["春希", "雪菜"],
                "anonymize_terms": {"峰城大学附属高中": "某高中"},
                "stylefit_dir": sf_dir,
                "paths": {
                    "work": os.path.join(td, "work"),
                    "raw": raw_dir,
                    "chunks": chunks_dir,
                    "notes": os.path.join(td, "work", "notes"),
                    "volumes": os.path.join(td, "work", "volumes"),
                    "cache": cache_dir,
                    "out": out_dir,
                    "logs": os.path.join(td, "work", "logs"),
                },
            })

            for script, extra in [
                ("06_build_attrib.py", []),
                ("07_stylefit_index.py", []),
            ]:
                r = subprocess.run(
                    [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script), "--config", cfg_path] + extra,
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

            idx_path = os.path.join(cache_dir, "wa2_unit", "index.json")
            with open(idx_path, encoding="utf-8") as fp:
                idx = json.load(fp)
            # 确认高频词表、全书台词数与 POV 分桶均生成
            self.assertTrue(idx.get("高频词"))
            top_terms = [x["词"] for x in idx["高频词"]]
            self.assertTrue(any(w in top_terms for w in ("音乐室", "吉他", "排练")), top_terms[:15])
            self.assertEqual(idx["统计"]["台词统计来源"], "全书引号对白")
            self.assertGreater(idx["统计"]["全书台词数"], 80)
            self.assertIn("第一人称", idx["统计"]["POV分桶"])
            self.assertIn("第三人称", idx["统计"]["POV分桶"])

            # 测试 08_stylefit_query.py --top-words 与 --export-card
            q_tw = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "08_stylefit_query.py"),
                 "--config", cfg_path, "--top-words", "10"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(q_tw.returncode, 0, q_tw.stderr)
            self.assertIn("高频特征词", q_tw.stdout)

            # 注入足够台词条目到 index 以测试单角色语音卡导出
            idx["台词"]["春希"] = {"陈述说明": {"n": 35, "中位长度": 12, "样本": ["我先把排练清单整理好。", "明天见，记得带吉他。"]}}
            textio.write_json(idx_path, idx)
            card_path = os.path.join(td, "haruki_card.md")
            q_card = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "08_stylefit_query.py"),
                 "--config", cfg_path, "--who", "春希", "--export-card", card_path],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(q_card.returncode, 0, q_card.stderr)
            card_txt = textio.read_text(card_path)
            self.assertIn("角色语音卡 · 春希", card_txt)
            self.assertIn("语音统计靶", card_txt)

            # 跑 13_build_pack.py 默认产出（写入 work/out/例子.txt）
            r1 = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "13_build_pack.py"),
                 "--config", cfg_path, "--style-only", "--anonymize", "--anonymize-style", "names", "--yes"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r1.returncode, 0, r1.stderr + r1.stdout)
            ex_default = os.path.join(out_dir, "例子.txt")
            pack_default = os.path.join(out_dir, "纯文风包.md")
            ex_txt_orig = textio.read_text(ex_default)
            pack_txt = textio.read_text(pack_default)
            # 确认：防照抄护栏、自定义 topics.json、高频词表、全量裸对白桶、非人名脱敏与中性人名风格
            self.assertIn("防照抄护栏", pack_txt)
            self.assertIn("音乐室与排练", pack_txt)
            self.assertIn("本书高频特征词", pack_txt)
            self.assertIn("某高中", pack_txt)
            self.assertNotIn("峰城大学附属高中", pack_txt)
            self.assertNotIn("雪菜", pack_txt)
            self.assertIn("全书全部对白引号", pack_txt)

            # 再跑自定义 --out 的原名版，确认不会覆写默认 work/out/例子.txt！
            custom_out = os.path.join(td, "custom_orig.md")
            r2 = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "13_build_pack.py"),
                 "--config", cfg_path, "--style-only", "--no-anonymize", "--out", custom_out, "--yes"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r2.returncode, 0, r2.stderr + r2.stdout)
            self.assertEqual(textio.read_text(ex_default), ex_txt_orig)
            self.assertIn("雪菜", textio.read_text(custom_out))

            # 测试 --emit-both 一键产出双版本
            both_out = os.path.join(td, "both", "纯文风包.md")
            r3 = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "13_build_pack.py"),
                 "--config", cfg_path, "--style-only", "--emit-both", "--out", both_out, "--yes"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r3.returncode, 0, r3.stderr + r3.stdout)
            self.assertTrue(os.path.isfile(both_out))
            both_orig = os.path.join(td, "both", "纯文风包_原名版.md")
            self.assertTrue(os.path.isfile(both_orig))
            self.assertNotIn("雪菜", textio.read_text(both_out))
            self.assertIn("雪菜", textio.read_text(both_orig))


if __name__ == "__main__":
    unittest.main()
