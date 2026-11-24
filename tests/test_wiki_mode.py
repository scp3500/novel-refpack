# -*- coding: utf-8 -*-
"""Tests for optional Agent Wiki mode (scripts/13c_build_wiki.py & 12_run_all.py --wiki)."""
import os
import subprocess
import sys
import unittest

from lib import textio
from tests.helpers import ROOT, TempProject
from tests.synthetic import generate_novel


def _run_py(script_name, *args):
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script_name)] + list(args)
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _prepare_indexed_project(tp, with_notes=False):
    novel_text, _, _ = generate_novel(n_vol=2, ch_per=18)
    src_path = os.path.join(tp.td, "book.txt")
    textio.write_text(src_path, novel_text)

    cfg = textio.read_json(tp.cfg_path)
    cfg["source"] = src_path
    cfg["aliases"] = {"林舟": ["阿舟"], "苏晚": ["晚晚"]}
    cfg["stylefit_dir"] = "general"
    textio.write_json(tp.cfg_path, cfg)

    for step in ("00_extract.py", "01_split.py", "06_build_attrib.py", "07_stylefit_index.py"):
        r = _run_py(step, "--config", tp.cfg_path)
        if r.returncode != 0:
            raise AssertionError("%s failed:\n%s\n%s" % (step, r.stdout, r.stderr))

    if with_notes:
        meta_dir = os.path.join(tp.work, "notes", "meta")
        vol_dir = os.path.join(tp.work, "notes", "vol")
        os.makedirs(meta_dir, exist_ok=True)
        os.makedirs(vol_dir, exist_ok=True)
        textio.write_text(
            os.path.join(meta_dir, "meta_world.md"),
            "## 世界观\n北境群镇以青石镇与烽火台为界，常年风雪。\n",
        )
        textio.write_text(
            os.path.join(meta_dir, "meta_characters.md"),
            "## 林舟\n沉稳克制的护队领队，与苏晚、陈衡同行北上。\n\n"
            "## 苏晚\n心思缜密，常提醒林舟不要逞强。\n",
        )
        textio.write_text(
            os.path.join(meta_dir, "meta_ending.md"),
            "三人抵达北门客栈，暂避风雪。\n",
        )
        textio.write_text(
            os.path.join(meta_dir, "meta_foreshadow.md"),
            "## 伏笔\n城墙根的鼓声来源尚未揭晓。\n",
        )
        textio.write_text(
            os.path.join(vol_dir, "vol_01.md"),
            "# 第一卷 北境\n\n林舟带着苏晚与陈衡在青石镇落脚，约定明早继续北上。\n",
        )
        textio.write_text(
            os.path.join(vol_dir, "vol_02.md"),
            "# 第二卷 风雪\n\n风雪封路，陈衡去巷口探查，林舟与苏晚守在门后。\n",
        )


class TestWikiMode(unittest.TestCase):
    def test_style_only_anonymized_wiki(self):
        with TempProject(name="北境测试", chunk_chars=8000) as tp:
            _prepare_indexed_project(tp, with_notes=False)
            wiki_dir = os.path.join(tp.work, "wiki")
            r = _run_py("13c_build_wiki.py", "--config", tp.cfg_path, "--style-only", "--anonymize")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            required = [
                "AGENTS.md",
                "route.md",
                "index.md",
                "style/overview.md",
                "style/narration.md",
                "style/craft.md",
                "style/dialogue.md",
                "style/vocab.md",
                "style/bans.md",
                "meta/contradictions.md",
                "_sources.json",
                "log.md",
            ]
            for rel in required:
                fp = os.path.join(wiki_dir, *rel.split("/"))
                self.assertTrue(os.path.isfile(fp), "Missing expected wiki file: %s" % rel)

            # Should NOT generate character pages, world.md, or volumes/ in --style-only --anonymize mode
            self.assertFalse(os.path.exists(os.path.join(wiki_dir, "characters")))
            self.assertFalse(os.path.exists(os.path.join(wiki_dir, "world.md")))
            self.assertFalse(os.path.exists(os.path.join(wiki_dir, "volumes")))

            # Verify vocab.md includes high-freq signature words section & zero-freq blacklist
            vocab_txt = textio.read_text(os.path.join(wiki_dir, "style", "vocab.md"))
            self.assertIn("高频特征词", vocab_txt)
            self.assertIn("零频黑名单", vocab_txt)
            self.assertIn("搭配表", vocab_txt)

            # Verify overview frontmatter
            overview_txt = textio.read_text(os.path.join(wiki_dir, "style", "overview.md"))
            self.assertTrue(overview_txt.startswith("---\n"))
            self.assertIn('anonymized: true', overview_txt)

            # Verify AGENTS.md is ultra-thin and includes key guidance
            agents_txt = textio.read_text(os.path.join(wiki_dir, "AGENTS.md"))
            self.assertLessEqual(len(agents_txt.splitlines()), 35)
            self.assertIn("route.md", agents_txt)
            self.assertIn("index.md", agents_txt)
            self.assertIn("11_verify.py", agents_txt)

            # Verify index.md links use relative forward slashes
            index_txt = textio.read_text(os.path.join(wiki_dir, "index.md"))
            self.assertIn("(style/overview.md)", index_txt)
            self.assertIn("(style/vocab.md)", index_txt)
            self.assertIn("(route.md)", index_txt)

            # Verify NO original character names leaked in any markdown file
            for root_d, _, files in os.walk(wiki_dir):
                for fn in files:
                    if not fn.endswith(".md"):
                        continue
                    txt = textio.read_text(os.path.join(root_d, fn))
                    for orig_name in ("林舟", "苏晚", "陈衡"):
                        self.assertNotIn(orig_name, txt, "Original name %s leaked in %s" % (orig_name, fn))

            # Verify _sources.json tracks chunk hashes
            src_meta = textio.read_json(os.path.join(wiki_dir, "_sources.json"))
            self.assertTrue(src_meta.get("anonymized"))
            self.assertEqual(src_meta.get("mode"), "style_only")
            self.assertTrue(any(k.startswith("chunks/") for k in (src_meta.get("sources") or {})))

    def test_full_mode_characters_volumes_crosslinks_and_preserve_contradictions(self):
        with TempProject(name="北境测试", chunk_chars=8000) as tp:
            _prepare_indexed_project(tp, with_notes=True)
            wiki_dir = os.path.join(tp.work, "wiki")
            r = _run_py("13c_build_wiki.py", "--config", tp.cfg_path, "--no-anonymize")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            # Character pages generated with YAML frontmatter + meta notes
            lin_path = os.path.join(wiki_dir, "characters", "林舟.md")
            su_path = os.path.join(wiki_dir, "characters", "苏晚.md")
            self.assertTrue(os.path.isfile(lin_path))
            self.assertTrue(os.path.isfile(su_path))

            lin_txt = textio.read_text(lin_path)
            self.assertIn("entity_id:", lin_txt)
            self.assertIn("aliases:", lin_txt)
            self.assertIn("阿舟", lin_txt)
            self.assertIn('status: "draft"', lin_txt)
            self.assertIn("护队领队", lin_txt)
            self.assertIn("[[苏晚]]", lin_txt)

            # World & volume pages with [[character]] cross-links
            world_path = os.path.join(wiki_dir, "world.md")
            vol1_path = os.path.join(wiki_dir, "volumes", "vol_01.md")
            vol2_path = os.path.join(wiki_dir, "volumes", "vol_02.md")
            self.assertTrue(os.path.isfile(world_path))
            self.assertTrue(os.path.isfile(vol1_path))
            self.assertTrue(os.path.isfile(vol2_path))

            world_txt = textio.read_text(world_path)
            self.assertIn("北境没有系统面板", world_txt)
            self.assertIn("[[林舟]]", world_txt)
            self.assertIn("(characters/林舟.md)", world_txt)

            vol1_txt = textio.read_text(vol1_path)
            self.assertTrue(vol1_txt.startswith("---\n"))
            self.assertIn("[[林舟]]", vol1_txt)
            self.assertIn("[[苏晚]]", vol1_txt)
            self.assertIn("../characters/林舟.md", vol1_txt)

            # Preserve user edits in meta/contradictions.md across rebuilds
            contra_path = os.path.join(wiki_dir, "meta", "contradictions.md")
            custom_note = "- [人工记录] 第二卷风雪夜时间锚需与青石镇出发日再核对"
            textio.write_text(contra_path, textio.read_text(contra_path) + "\n" + custom_note + "\n")

            r2 = _run_py("13c_build_wiki.py", "--config", tp.cfg_path, "--no-anonymize")
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

            contra_after = textio.read_text(contra_path)
            self.assertIn(custom_note, contra_after)

            # Append-only log.md has 2 entries
            log_txt = textio.read_text(os.path.join(wiki_dir, "log.md"))
            self.assertEqual(log_txt.count("build-wiki |"), 2)

    def test_check_stale_detects_modified_chunk(self):
        with TempProject(name="北境测试", chunk_chars=8000) as tp:
            _prepare_indexed_project(tp, with_notes=False)
            wiki_dir = os.path.join(tp.work, "wiki")
            r = _run_py("13c_build_wiki.py", "--config", tp.cfg_path, "--style-only", "--anonymize")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            # Fresh immediately after build
            r_fresh = _run_py("13c_build_wiki.py", "--config", tp.cfg_path, "--check-stale")
            self.assertEqual(r_fresh.returncode, 0, r_fresh.stdout + r_fresh.stderr)
            self.assertIn("FRESH", r_fresh.stdout)

            # Modify a chunk file and verify --check-stale detects it without rewriting _sources.json
            src_json_path = os.path.join(wiki_dir, "_sources.json")
            before_sources = textio.read_text(src_json_path)

            chunk_files = sorted(os.listdir(os.path.join(tp.work, "chunks")))
            first_chunk = os.path.join(tp.work, "chunks", chunk_files[0])
            textio.write_text(first_chunk, textio.read_text(first_chunk) + "\n补充的新一段正文内容。\n")

            r_stale = _run_py("13c_build_wiki.py", "--config", tp.cfg_path, "--check-stale")
            self.assertEqual(r_stale.returncode, 1, r_stale.stdout + r_stale.stderr)
            self.assertIn("STALE", r_stale.stdout)
            self.assertIn("chunks/" + chunk_files[0], r_stale.stdout)
            self.assertEqual(textio.read_text(src_json_path), before_sources)

    def test_run_all_wiki_flag_help_and_execution(self):
        r_help = _run_py("12_run_all.py", "--help")
        self.assertEqual(r_help.returncode, 0, r_help.stderr)
        self.assertIn("--wiki", r_help.stdout)

        with TempProject(name="一键Wiki测试", chunk_chars=8000) as tp:
            novel_text, _, _ = generate_novel(n_vol=1, ch_per=5)
            src_path = os.path.join(tp.td, "book.txt")
            textio.write_text(src_path, novel_text)
            cfg = textio.read_json(tp.cfg_path)
            cfg["source"] = src_path
            cfg["stylefit_dir"] = "general"
            textio.write_json(tp.cfg_path, cfg)

            r = _run_py(
                "12_run_all.py",
                "--config", tp.cfg_path,
                "--style-only", "--anonymize",
                "--kb", "60",
                "--yes",
                "--wiki",
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            # Both default single-file pack AND optional wiki exist
            self.assertTrue(os.path.isfile(os.path.join(tp.work, "out", "纯文风包.md")))
            self.assertTrue(os.path.isfile(os.path.join(tp.work, "wiki", "AGENTS.md")))
            self.assertTrue(os.path.isfile(os.path.join(tp.work, "wiki", "index.md")))
            self.assertTrue(os.path.isfile(os.path.join(tp.work, "wiki", "style", "vocab.md")))


if __name__ == "__main__":
    unittest.main()
