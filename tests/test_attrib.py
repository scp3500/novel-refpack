# -*- coding: utf-8 -*-
import unittest

from lib import corpus
from tests.helpers import load_script

A = load_script("06_build_attrib.py")


class TestAttrib(unittest.TestCase):
    def setUp(self):
        corpus.set_quotes(["“", "「", "『"], ["”", "」", "』"])
        self.attr = A.make_attributor(["林舟", "苏晚", "陈衡"])

    def ids(self, lines):
        return [(p["who"], p["text"]) for p in self.attr(lines)]

    def test_curly_quotes(self):
        got = self.ids(["林舟说：“我们走吧。”"])
        self.assertEqual(got, [("林舟", "我们走吧。")])

    def test_corner_quotes(self):
        got = self.ids(["苏晚道：「今晚宿在镇上。」"])
        self.assertEqual(got, [("苏晚", "今晚宿在镇上。")])

    def test_leading_narration(self):
        got = self.ids(["陈衡喊：“后面没人。”"])
        self.assertEqual(got, [("陈衡", "后面没人。")])

    def test_zhidao_is_not_speech(self):
        # 「知道」里的「道」不能当说话动词；这行没有引号，本来也不该出对。
        got = self.ids(["苏晚知道林舟不会回头。", "林舟推开门坐下。"])
        self.assertEqual(got, [])

    def test_next_line_with_own_quote_does_not_steal(self):
        lines = [
            "“我先去打水。”",
            "苏晚问道：“要不要我跟着？”",
        ]
        got = self.ids(lines)
        texts = [t for _, t in got]
        self.assertIn("要不要我跟着？", texts)
        # 上一句不能被下一行的「苏晚」抢走
        stolen = [who for who, t in got if t == "我先去打水。"]
        self.assertEqual(stolen, [])

    def test_prev_line_colon(self):
        lines = [
            "林舟看着窗外：",
            "“不用。你歇着。”",
        ]
        got = self.ids(lines)
        self.assertEqual(got, [("林舟", "不用。你歇着。")])

    def test_two_names_discard(self):
        got = self.ids(["林舟和苏晚都道：“走。”"])
        self.assertEqual(got, [])

    def test_object_preposition_not_subject(self):
        got = self.ids(["她对林舟说：“跟上。”"])
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
