# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from lib import textio


class TestNaturalKey(unittest.TestCase):
    def test_vol_100_after_vol_99(self):
        files = ["vol_%02d.md" % i for i in (1, 2, 10, 11, 99, 100, 101, 110)]
        str_sorted = sorted(files)
        nat_sorted = sorted(files, key=textio.natural_key)
        self.assertLess(str_sorted.index("vol_100.md"), str_sorted.index("vol_99.md"))
        self.assertEqual(
            nat_sorted,
            ["vol_01.md", "vol_02.md", "vol_10.md", "vol_11.md",
             "vol_99.md", "vol_100.md", "vol_101.md", "vol_110.md"])

    def test_chunk_three_digits(self):
        files = ["chunk_100.txt", "chunk_11.txt", "chunk_2.txt"]
        self.assertEqual(
            sorted(files, key=textio.natural_key),
            ["chunk_2.txt", "chunk_11.txt", "chunk_100.txt"])


class TestCleanNoteText(unittest.TestCase):
    def test_keeps_numbered_plot_sentence(self):
        s = "1. 林舟离开村子。\n2. 苏晚跟上队伍。\n"
        out = textio.clean_note_text(s)
        self.assertIn("1. 林舟离开村子。", out)
        self.assertIn("2. 苏晚跟上队伍。", out)

    def test_keeps_first_round_plot(self):
        s = "第一回合林舟就倒下了，众人把他扶起来。\n"
        self.assertIn("第一回合林舟就倒下了", textio.clean_note_text(s))

    def test_drops_true_title_lines(self):
        s = "第三话 过河\n第12章：归乡\n3. 第三话 标题\n正文还在。\n"
        out = textio.clean_note_text(s)
        self.assertNotIn("第三话 过河", out)
        self.assertNotIn("第12章：归乡", out)
        self.assertNotIn("3. 第三话 标题", out)
        self.assertIn("正文还在。", out)

    def test_strips_internal_chunk_ids(self):
        s = "见 chunk_12 的事件（分片 3）还在。\n"
        out = textio.clean_note_text(s)
        self.assertNotIn("chunk_12", out)
        self.assertNotIn("分片 3", out)

    def test_title_with_period_is_plot(self):
        # 标题部分带句号 → 剧情句，不是话名
        s = "第十二章：他终于回家了。\n"
        self.assertIn("他终于回家了", textio.clean_note_text(s))


class TestParseUnits(unittest.TestCase):
    def test_offsets_cover_body(self):
        text = "# 正篇\n## 第一卷\n### 第一章\n甲甲甲\n### 第二章\n乙乙乙\n"
        units = textio.parse_units(text)
        self.assertEqual([u["title"] for u in units], ["第一卷", "第一章", "第二章"])
        self.assertTrue(all("start" in u and "end" in u for u in units))
        ch1 = [u for u in units if u["title"] == "第一章"][0]
        self.assertIn("甲甲甲", text[ch1["start"]:ch1["end"]])
        self.assertNotIn("乙乙乙", text[ch1["start"]:ch1["end"]])


class TestAtomicWrite(unittest.TestCase):
    def test_write_text_creates_parent_and_replaces(self):
        td = tempfile.mkdtemp()
        path = os.path.join(td, "nested", "a.md")
        textio.write_text(path, "one\n")
        textio.write_text(path, "two\n")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "two\n")
        leftovers = [n for n in os.listdir(os.path.join(td, "nested")) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_tmp_sibling_hidden_and_same_dir(self):
        path = "/tmp/notes/vol_01.md"
        tmp = textio.tmp_sibling(path)
        self.assertEqual(os.path.dirname(tmp), os.path.dirname(os.path.abspath(path)))
        self.assertTrue(os.path.basename(tmp).startswith("."))
        self.assertTrue(tmp.endswith(".tmp"))


if __name__ == "__main__":
    unittest.main()
