# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import unittest

from lib import project, textio
from tests.helpers import ROOT, TempProject, load_script, write_extracted

S04 = load_script("04_build_volume_map.py")
S05 = load_script("05_run_volumes.py")


def run_py(script, cfg):
    r = subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script),
         "--config", cfg],
        cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("%s failed:\n%s\n%s" % (script, r.stdout, r.stderr))
    return r


class TestVolumeMapOffsets(unittest.TestCase):
    def test_same_title_different_h1_do_not_mix(self):
        # 正篇 / 外传都有「第一卷 北境」，旧逻辑按标题字符串会串卷。
        ch = "甲" * 40 + "\n林舟在正篇走了一段。标记甲。\n"
        ch_b = "乙" * 40 + "\n苏晚在外传走了一段。标记乙。\n"
        text = "\n".join([
            "# 正篇",
            "## 第一卷 北境",
            "### 第一章 开端",
            ch, ch, ch,
            "### 第二章 过河",
            ch, ch, ch,
            "### 第三章 落脚",
            ch, ch,
            "# 外传",
            "## 第一卷 北境",
            "### 第一章 开端",
            ch_b, ch_b,
        ])
        with TempProject(chunk_chars=250) as tp:
            write_extracted(tp.raw_dir(), text)
            run_py("01_split.py", tp.cfg_path)
            run_py("04_build_volume_map.py", tp.cfg_path)
            vmap = textio.read_json(os.path.join(tp.work, "volume_map.json"))
            self.assertEqual(len(vmap), 2)
            self.assertEqual(vmap[0]["h1"], "正篇")
            self.assertEqual(vmap[1]["h1"], "外传")
            self.assertTrue(vmap[0]["chunks"])
            self.assertTrue(vmap[1]["chunks"])
            self.assertNotEqual(vmap[0]["chunks"], vmap[1]["chunks"])
            # 正篇跨多片：标题只在第一片，后面几片也必须算进这卷
            self.assertGreaterEqual(len(vmap[0]["chunks"]), 2)
            raw = textio.read_text(os.path.join(tp.raw_dir(), "_all.txt"))
            v0 = raw[vmap[0]["start"]:vmap[0]["end"]]
            v1 = raw[vmap[1]["start"]:vmap[1]["end"]]
            self.assertIn("标记甲", v0)
            self.assertNotIn("标记乙", v0)
            self.assertIn("标记乙", v1)
            self.assertNotIn("标记甲", v1)

    def test_chunk_spans_replays_old_manifest(self):
        text = "# 正篇\n## 卷一\n### 一\nAAA\n### 二\nBBB\n"
        units = [u for u in textio.parse_units(text) if "\n".join(u["lines"]).strip()]
        man = [{
            "chunk": 1, "units": len(units), "first": units[0]["title"],
            "last": units[-1]["title"],
        }]
        spans = S04.chunk_spans(text, man)
        self.assertIsNotNone(spans)
        self.assertEqual(spans[0][0], 1)
        self.assertEqual(spans[0][1], units[0]["start"])
        self.assertEqual(spans[0][2], units[-1]["end"])


class TestMetaMaterial(unittest.TestCase):
    def _vol_note(self, i, extra_setting, extra_fore, ending_mark=""):
        return "\n".join([
            "# 第%d卷" % i,
            "## 一、范围与时间锚",
            "第%d卷范围。" % i,
            "## 二、剧情纪要",
            "1. 第%d卷的事件发生了。" % i,
            ending_mark,
            "## 三、本篇末角色状态快照",
            "- 林舟在第%d卷末。" % i,
            "## 四、登场人物（新登场请标注）",
            "- 林舟",
            "## 五、设定 / 地点 / 组织 / 术语",
            extra_setting,
            "## 六、名场面与关键台词",
            "- “走吧”",
            "## 七、伏笔与回收",
            extra_fore,
            "## 八、基调一句话",
            "赶路。",
            "",
        ])

    def test_world_gets_setting_foreshadow_gets_hooks(self):
        with TempProject() as tp:
            cfg = tp.load()
            vdir = os.path.join(cfg["paths"]["notes"], "vol")
            os.makedirs(vdir, exist_ok=True)
            vmap = []
            for i in range(1, 4):
                textio.write_text(
                    os.path.join(vdir, "vol_%02d.md" % i),
                    self._vol_note(i, "设定UNIQUE_SET_%d" % i, "伏笔UNIQUE_FORE_%d" % i))
                vmap.append({"i": i, "h1": "", "h2": "第%d卷" % i})
            textio.write_json(os.path.join(cfg["paths"]["work"], "volume_map.json"), vmap)
            world = S05.meta_material(cfg, "meta_world")
            fore = S05.meta_material(cfg, "meta_foreshadow")
            pos = S05.meta_material(cfg, "meta_positioning")
            self.assertIn("UNIQUE_SET_1", world)
            self.assertIn("UNIQUE_SET_3", world)
            self.assertNotIn("UNIQUE_FORE_1", world)
            self.assertIn("UNIQUE_FORE_2", fore)
            self.assertIn("UNIQUE_SET_2", fore)  # 伏笔元章节也要设定
            self.assertNotIn("UNIQUE_SET_1", pos)
            self.assertNotIn("UNIQUE_FORE_1", pos)
            self.assertIn("第1卷范围", pos)

    def test_ending_keeps_tail_volumes_when_compressed(self):
        with TempProject() as tp:
            cfg = tp.load()
            vdir = os.path.join(cfg["paths"]["notes"], "vol")
            os.makedirs(vdir, exist_ok=True)
            vmap = []
            blob = "详" * 4000
            for i in range(1, 9):
                mark = "结局标记END_%d" % i
                body = self._vol_note(i, blob, blob, ending_mark=mark)
                textio.write_text(os.path.join(vdir, "vol_%02d.md" % i), body)
                vmap.append({"i": i, "h1": "", "h2": "第%d卷" % i})
            textio.write_json(os.path.join(cfg["paths"]["work"], "volume_map.json"), vmap)
            ending = S05.meta_material(cfg, "meta_ending", limit=8000)
            self.assertIn("结局标记END_8", ending)
            self.assertIn("结局标记END_7", ending)
            # 早期卷可以被压缩掉中间，但不得把最后一卷整段丢掉
            self.assertLess(len(ending), 12000)

    def test_clip_keeps_head_and_tail(self):
        body = ["头%d" % i for i in range(20)] + ["尾锚点XYZ"] 
        # 让中间很长
        body = ["开头行"] + ["中" * 80 for _ in range(10)] + ["结尾行TAIL"]
        got = S05.clip("## 二、剧情纪要", body, 80)
        self.assertIn("开头行", got)
        self.assertIn("TAIL", got)
        self.assertIn(S05.GAP, got)


class TestVolNotesOrder(unittest.TestCase):
    def test_last_item_is_map_last_volume_not_string_sort(self):
        with TempProject() as tp:
            cfg = tp.load()
            vdir = os.path.join(cfg["paths"]["notes"], "vol")
            os.makedirs(vdir, exist_ok=True)
            # 残留旧文件 + 三位数卷号：字符串排序会把 vol_100 排到 vol_11 前面
            for i in (11, 99, 100):
                textio.write_text(os.path.join(vdir, "vol_%02d.md" % i), "# 卷%d\n%s\n" % (i, "状" * 40))
            textio.write_text(os.path.join(vdir, "vol_03.md"), "# 残留不该出现\n")
            vmap = [{"i": i, "h1": "", "h2": "第%d卷" % i} for i in (11, 99, 100)]
            textio.write_json(os.path.join(cfg["paths"]["work"], "volume_map.json"), vmap)
            notes = project.vol_notes(cfg, with_missing=True)
            self.assertEqual([v["i"] for v, _ in notes], [11, 99, 100])
            self.assertEqual(notes[-1][0]["i"], 100)
            self.assertTrue(notes[-1][1].endswith("vol_100.md"))
            names = [os.path.basename(p) for _, p in project.vol_notes(cfg)]
            self.assertNotIn("vol_03.md", names)


class TestAllot(unittest.TestCase):
    def test_fits_get_full_size(self):
        sizes = [10, 10, 100]
        alloc = S05.allot(sizes, [1, 1, 4], 80)
        self.assertEqual(alloc[0], 10)
        self.assertEqual(alloc[1], 10)
        self.assertEqual(alloc[2], 60)


if __name__ == "__main__":
    unittest.main()
