# -*- coding: utf-8 -*-
"""REPO_MAP.md 路径索引、公开 JSON/正则与纯标准库门禁的单元测试。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import textio  # noqa: E402
from tests.helpers import load_script  # noqa: E402


class TestRepoMapAndCheck(unittest.TestCase):
    def setUp(self):
        self.mod = load_script("repo_check.py")

    def test_live_repo_passes_all_checks(self):
        missing, orphan = self.mod.check_coverage(ROOT)
        self.assertEqual(missing, [], "有未登记到 REPO_MAP.md 的文件: %s" % missing)
        self.assertEqual(orphan, [], "REPO_MAP.md 有已删除的悬空路径: %s" % orphan)
        self.assertEqual(self.mod.check_jsons_and_regex(ROOT), [])
        self.assertEqual(self.mod.check_stdlib_only(ROOT), [])

    def test_skeleton_extracts_functions_and_cli_flags(self):
        sk = self.mod.extract_skeleton("scripts/repo_check.py", ROOT)
        self.assertIn("scripts/repo_check.py", sk)
        self.assertIn("--skeleton", sk)
        self.assertIn("check_coverage", sk)

    def test_detects_unregistered_file_and_third_party_import(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "scripts"), exist_ok=True)
            textio.write_text(os.path.join(td, "REPO_MAP.md"), "- `scripts/a.py`：ok\n")
            textio.write_text(os.path.join(td, "scripts", "a.py"), "import os\n")
            textio.write_text(os.path.join(td, "scripts", "b.py"), "import requests\n")

            missing, orphan = self.mod.check_coverage(td)
            self.assertEqual(missing, ["scripts/b.py"])
            self.assertEqual(orphan, [])

            viols = self.mod.check_stdlib_only(td)
            self.assertTrue(any("requests" in v for v in viols), viols)


if __name__ == "__main__":
    unittest.main()
