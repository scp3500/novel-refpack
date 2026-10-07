# -*- coding: utf-8 -*-
"""用确定性假模型跑一遍真实流水线（约 105 章）。"""
import json
import os
import shlex
import subprocess
import sys
import unittest

from lib import textio
from tests.helpers import ROOT, EnvRestore, TempProject
from tests.synthetic import CH_PER_VOL, VOLS, generate_novel


FAKE = os.path.join(ROOT, "tests", "fake_llm.py")
N_CH = VOLS * CH_PER_VOL


class TestE2ESmoke(EnvRestore):
    def test_run_all_on_105_chapters(self):
        novel, n_ch, last_tag = generate_novel()
        self.assertEqual(n_ch, N_CH)
        self.assertGreaterEqual(n_ch, 100)
        cmd = "%s %s --prompt {prompt_file} --out {out_file}" % (
            shlex.quote(sys.executable), shlex.quote(FAKE))
        with TempProject(
            name="北境夜话",
            chunk_chars=400,
            llm={
                "backend": "command",
                "command": cmd,
                "concurrency": 8,
                "timeout": 30,
                "retries": 1,
            },
        ) as tp:
            src = os.path.join(tp.td, "novel.txt")
            textio.write_text(src, novel)
            # 把 source 写回配置
            with open(tp.cfg_path, encoding="utf-8") as f:
                cfgj = json.load(f)
            cfgj["source"] = src
            with open(tp.cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfgj, f, ensure_ascii=False, indent=1)

            env = dict(os.environ)
            env.pop("PY", None)
            env["REFPACK_CONFIG"] = tp.cfg_path
            env["PAR"] = "8"
            r = subprocess.run(
                ["bash", os.path.join(ROOT, "scripts", "12_run_all.sh")],
                cwd=ROOT, env=env, capture_output=True, text=True)
            if r.returncode != 0:
                self.fail("12_run_all.sh 失败（exit %s）\nSTDOUT:\n%s\nSTDERR:\n%s" % (
                    r.returncode, r.stdout[-4000:], r.stderr[-4000:]))

            secs = textio.read_json(os.path.join(tp.work, "raw", "sections.json"), [])
            h1 = [s for s in secs if s.get("level") == 1]
            h2 = [s for s in secs if s.get("level") == 2]
            self.assertEqual(len(h1), VOLS, r.stdout[-1500:])
            self.assertEqual(len(h2), N_CH)

            man = textio.read_json(os.path.join(tp.work, "manifest.json"), [])
            self.assertGreaterEqual(len(man), 100)
            self.assertTrue(all(isinstance(m.get("start"), int) for m in man))
            chunk_105 = os.path.join(tp.work, "chunks", "chunk_105.txt")
            self.assertTrue(os.path.isfile(chunk_105), "应有 chunk_105.txt 以覆盖三位数排序")

            vmap = textio.read_json(os.path.join(tp.work, "volume_map.json"), [])
            self.assertEqual(len(vmap), N_CH)
            self.assertTrue(os.path.isfile(os.path.join(tp.work, "volumes", "vol_100.txt")))
            # 各卷「第一章」标题相同，必须靠偏移分到不同片
            vol1 = vmap[0]
            vol22 = vmap[CH_PER_VOL]  # 第二卷第一章
            self.assertEqual(vol1["h2"].split()[0], vol22["h2"].split()[0])
            self.assertNotEqual(vol1["chunks"], vol22["chunks"])
            self.assertNotEqual(vol1["start"], vol22["start"])
            self.assertEqual(vmap[-1]["i"], N_CH)
            self.assertTrue(vmap[-1]["chunks"])

            notes = os.path.join(tp.work, "notes")
            self.assertTrue(os.path.isfile(os.path.join(notes, "chunk_105.md")))
            self.assertTrue(os.path.isfile(os.path.join(notes, "vol", "vol_105.md")))
            for stem in ("positioning", "world", "factions", "characters", "ending", "foreshadow"):
                self.assertTrue(os.path.isfile(os.path.join(notes, "meta", "meta_%s.md" % stem)))

            ending = textio.read_text(os.path.join(notes, "meta", "meta_ending.md"))
            self.assertIn(last_tag, ending)

            pairs = textio.read_json(os.path.join(tp.work, "attrib.json"), [])
            who = {p["who"] for p in pairs}
            self.assertTrue({"林舟", "苏晚", "陈衡"} <= who, who)
            stolen = [p for p in pairs if p.get("text", "").startswith("我先去打水")]
            self.assertFalse(stolen, "「我先去打水」不应被下一行的苏晚抢走：%s" % stolen)

            summary = textio.read_text(os.path.join(tp.work, "out", "整书总结.md"))
            self.assertIn("1. 林舟离开村子。", summary)
            self.assertIn("第一回合林舟就倒下了", summary)
            self.assertNotIn("\n第三话 过河\n", summary)
            self.assertIn(last_tag, summary)
            self.assertIn("截至：", summary)
            last_h2 = vmap[-1]["h2"]
            self.assertIn(last_h2, summary)

            examples = textio.read_text(os.path.join(tp.work, "out", "例子.txt"))
            self.assertGreater(len(examples), 200)
            self.assertIn("使用禁令", examples)

            # 字符串排序会把 vol_100 排到 vol_11 前面；成品必须按卷号
            vol_files = [os.path.join(notes, "vol", "vol_%02d.md" % i) for i in range(1, N_CH + 1)]
            self.assertTrue(all(os.path.isfile(f) for f in vol_files[-3:]))


if __name__ == "__main__":
    unittest.main()
