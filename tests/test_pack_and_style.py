# -*- coding: utf-8 -*-
"""覆盖：预算控制(KB/Tokens/比例)、参考包合并、纯文风脱敏、细节扩展、抽取偏移与无标题兜底。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

from lib import budget, corpus, project, textio
from tests.helpers import ROOT, TempProject, load_script, write_extracted

S00 = load_script("00_extract.py")
C03 = load_script("chat_03_build_prompt.py")


class TestBudgetAndPrompt(unittest.TestCase):
    def test_budget_presets_and_ratio(self):
        b_std = budget.resolve_budget({}, preset="standard")
        self.assertEqual(b_std["total_kb"], 150.0)
        self.assertAlmostEqual(b_std["example_ratio"], 0.70, places=2)
        self.assertAlmostEqual(b_std["example_kb"], 105.0, places=1)
        self.assertAlmostEqual(b_std["summary_kb"], 45.0, places=1)

        b_style = budget.resolve_budget({}, kb=80, style_only=True)
        self.assertEqual(b_style["example_ratio"], 1.0)
        self.assertEqual(b_style["example_kb"], 80.0)
        self.assertEqual(b_style["summary_kb"], 0.0)

        b_tok = budget.resolve_budget({}, max_tokens=40000, ratio=0.8)
        self.assertGreater(b_tok["total_kb"], 100.0)
        self.assertAlmostEqual(b_tok["example_ratio"], 0.8, places=2)

    def test_prompt_single_pass_no_secondary_expansion(self):
        with TempProject() as tp:
            cfg = tp.load()
            got = project.prompt(
                cfg,
                "stage1_note",
                name="测试{chunk_text}",
                person="第三人称",
                chunk_no="01",
                h1="卷一",
                first="序",
                last="一",
                chunk_text="正文内容",
            )
            self.assertIn("正文内容", got)
            # 书名里的 {chunk_text} 不应再次展开成第二次正文内容
            self.assertEqual(got.count("正文内容"), 1)


class TestExtractAndVolumeFallback(unittest.TestCase):
    def test_first_heading_offset_exact_and_epub_div(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "divbook.epub")
        with zipfile.ZipFile(epub, "w") as z:
            z.writestr(
                "META-INF/container.xml",
                '<container><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>',
            )
            z.writestr(
                "content.opf",
                '<package><manifest><item id="c1" href="c1.xhtml"/></manifest>'
                '<spine><itemref idref="c1"/></spine></package>',
            )
            z.writestr(
                "c1.xhtml",
                "<html><body><h1>第一卷</h1>"
                "<div class='wrap'>外层裸文本<p>内层段落</p></div>"
                "<div><li>列表项正文</li></div>"
                "</body></html>",
            )
        r = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                os.path.join(ROOT, "scripts", "00_extract.py"),
                "--source",
                epub,
                "--out",
                os.path.join(td, "raw"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        raw_txt = textio.read_text(os.path.join(td, "raw", "_all.txt"))
        secs = textio.read_json(os.path.join(td, "raw", "sections.json"), [])
        self.assertGreaterEqual(len(secs), 1)
        for h in secs:
            self.assertTrue(
                raw_txt[h["offset"]:].startswith("#" * h["level"] + " " + h["title"]),
                (h, raw_txt[h["offset"]:h["offset"] + 20]),
            )
        self.assertIn("外层裸文本", raw_txt)
        self.assertEqual(raw_txt.count("内层段落"), 1)
        self.assertIn("列表项正文", raw_txt)

    def test_no_heading_plain_text_volume_map_fallback(self):
        with TempProject(chunk_chars=300) as tp:
            src = os.path.join(tp.td, "plain.txt")
            textio.write_text(
                src,
                "没有任何章节标题的纯白板小说正文，第一段足够长。\n" * 18,
            )
            cfg = textio.read_json(tp.cfg_path)
            cfg["source"] = src
            textio.write_json(tp.cfg_path, cfg)

            for sc in ("00_extract.py", "01_split.py", "04_build_volume_map.py"):
                r = subprocess.run(
                    [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", sc), "--config", tp.cfg_path],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(r.returncode, 0, (sc, r.stderr))

            vmap = textio.read_json(os.path.join(tp.work, "volume_map.json"), [])
            self.assertEqual(len(vmap), 1)
            self.assertTrue(vmap[0]["h2"].startswith("分段"))
            self.assertEqual(vmap[0]["chunks"], [1])


class TestStyleOnlyAndPackBudget(unittest.TestCase):
    def test_style_only_anonymize_and_craft_details(self):
        with TempProject(names=["叶孤城", "西门吹雪"], aliases={"叶孤城": ["城主"]}) as tp:
            chunks_dir = os.path.join(tp.work, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            sample_paras = [
                "叶孤城推开木门，低头看了看掌心，随即把长剑按在桌角上。",
                "窗外夜色沉沉，微风卷着雨水敲打瓦片，院角石阶一片冰凉。",
                "西门吹雪站起身，目光落在对面的茶杯上，半晌没有接话。",
                "“这局棋，你打算怎么下？”城主缓缓放下茶盏，指尖轻轻叩着桌面，神色平静得像一潭深水。",
                "西门吹雪摇头道：“再等半刻钟，天亮之前自然会有答案。”",
                "叶孤城使出【天外飞仙】，剑光一闪，屋檐上的积雪簌簌落下。",
                "片刻之后，风停了。",
            ]
            textio.write_text(os.path.join(chunks_dir, "chunk_01.txt"), "\n".join(sample_paras * 18))

            src = os.path.join(tp.td, "book.txt")
            textio.write_text(src, "# 第一卷\n## 第一章 落雪\n" + "\n".join(sample_paras * 18))
            cfg = textio.read_json(tp.cfg_path)
            cfg["source"] = src
            textio.write_json(tp.cfg_path, cfg)

            r = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    os.path.join(ROOT, "scripts", "12_run_all.py"),
                    "--config",
                    tp.cfg_path,
                    "--style-only",
                    "--anonymize",
                    "--kb",
                    "45",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)

            pack_p = os.path.join(tp.work, "out", "纯文风包.md")
            self.assertTrue(os.path.isfile(pack_p))
            pack = textio.read_text(pack_p)
            self.assertIn("细粒度笔法与镜头细节", pack)
            self.assertIn("语体与台词功能范例", pack)
            self.assertIn("使用禁令", pack)
            self.assertNotIn("分剧本语料", pack)
            self.assertNotIn("名场面原文摘录", pack)
            self.assertNotIn("叶孤城", pack)
            self.assertNotIn("西门吹雪", pack)
            self.assertNotIn("【天外飞仙】", pack)
            self.assertIn("某甲", pack)
            self.assertLessEqual(budget.utf8_kb(pack), 55.0)

    def test_merged_pack_budget_and_ratio(self):
        with TempProject(
            names=["林舟", "苏晚"],
            hard_settings=["硬设定一：不可违背底线"],
            if_points=["分歧点一：如果林舟留在村里"],
        ) as tp:
            raw_dir = tp.raw_dir()
            chunks_dir = os.path.join(tp.work, "chunks")
            vol_dir = os.path.join(tp.work, "notes", "vol")
            meta_dir = os.path.join(tp.work, "notes", "meta")
            cache_dir = os.path.join(tp.work, "cache", "测试书")
            for d in (raw_dir, chunks_dir, vol_dir, meta_dir, cache_dir):
                os.makedirs(d, exist_ok=True)

            para = "林舟伸手推开屋门，顺手把油灯放在桌上，笑了笑。苏晚问道：「今晚还赶路吗？」"
            textio.write_text(os.path.join(chunks_dir, "chunk_01.txt"), "\n".join([para] * 120))
            write_extracted(raw_dir, "# 第一卷\n## 第一章\n" + "\n".join([para] * 40))
            textio.write_json(os.path.join(tp.work, "attrib.json"), [{"who": "林舟", "text": "走吧。"}] * 40)

            vmap = []
            for vi in range(1, 9):
                vmap.append({"i": vi, "h1": "第一部", "h2": "第%d卷" % vi, "chunks": [1]})
                lines = ["# 第%d卷" % vi, "## 二、剧情纪要"]
                lines += ["%d. 林舟在第%d卷推进剧情事件。" % (k, vi) + ("细节补充内容" * 18) for k in range(1, 15)]
                lines += ["## 三、本篇末角色状态快照", "- 林舟：第%d卷末尾状态正常。" % vi]
                textio.write_text(os.path.join(vol_dir, "vol_%02d.md" % vi), "\n".join(lines))
            textio.write_json(os.path.join(tp.work, "volume_map.json"), vmap)
            textio.write_text(os.path.join(meta_dir, "meta_ending.md"), "## 结局现状\n结局停在第8卷末尾。")
            textio.write_text(os.path.join(meta_dir, "meta_world.md"), "## 二、世界观\n常规世界。")

            subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "07_stylefit_index.py"), "--config", tp.cfg_path],
                cwd=ROOT, check=True, capture_output=True,
            )
            r = subprocess.run(
                [
                    sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "13_build_pack.py"),
                    "--config", tp.cfg_path, "--preset", "compact", "--ratio", "0.70",
                ],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)

            pack_p = os.path.join(tp.work, "out", "参考包.md")
            self.assertTrue(os.path.isfile(pack_p))
            pack = textio.read_text(pack_p)
            self.assertIn("构成明细", pack)
            self.assertIn("截至：第一部 第8卷", pack)
            self.assertIn("硬设定一", pack)
            self.assertIn("使用禁令", pack)
            self.assertLessEqual(budget.utf8_kb(pack), 72.0)


class TestChatDynamicPeriodRule(unittest.TestCase):
    def test_high_period_rate_does_not_forbid_period(self):
        td = tempfile.mkdtemp()
        work = os.path.join(td, "work")
        os.makedirs(work, exist_ok=True)
        cfg_p = os.path.join(td, "chat.json")
        textio.write_json(cfg_p, {"work_dir": work})
        textio.write_json(os.path.join(work, "chat_metrics.json"), {
            "字数指纹": {"P50中位数": 20, "P80短句阈值": 40, "P95长句阈值": 80},
            "每千字标点频率": {"句号。": 32.5, "空格（代替逗号）": 1.0},
            "高频句首发语词": [{"word": "其实", "count": 5}],
            "零频黑名单_书面与AI词": [],
        })
        textio.write_json(os.path.join(work, "chat_behavior.json"), {"_source": "offline_template"})
        out_p = os.path.join(td, "prompt.md")
        r = subprocess.run(
            [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "chat_03_build_prompt.py"),
             "--config", cfg_p, "--out", out_p],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        txt = textio.read_text(out_p)
        self.assertIn("自然标点断句", txt)
        self.assertNotIn("彻底禁用句号", txt)


if __name__ == "__main__":
    unittest.main()
