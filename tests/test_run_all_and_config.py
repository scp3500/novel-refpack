# -*- coding: utf-8 -*-
import os
import subprocess
import unittest

from lib import project
from tests.helpers import ROOT, EnvRestore, TempProject, write_extracted


class TestRunAllScript(unittest.TestCase):
    def test_syntax_and_python3_preference(self):
        path = os.path.join(ROOT, "scripts", "12_run_all.sh")
        r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("command -v python3", text)
        py3_at = text.find("command -v python3")
        py_at = text.find("command -v python ")
        self.assertGreater(py3_at, 0)
        self.assertGreater(py_at, py3_at)
        self.assertIn("sys.version_info >= (3, 9)", text)
        self.assertIn("REFPACK_CONFIG", text)

    def test_py_detection_picks_python3(self):
        r = subprocess.run(
            ["bash", "-c", r'''
set -euo pipefail
if [ -z "${PY:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo missing; exit 127
  fi
fi
echo "$PY"
'''],
            capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "PY"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "python3")


class TestRefpackConfig(EnvRestore):
    def test_load_uses_env_path(self):
        with TempProject(name="env书") as tp:
            os.environ["REFPACK_CONFIG"] = tp.cfg_path
            cfg = project.load()
            self.assertEqual(cfg["_path"], tp.cfg_path)
            self.assertEqual(cfg["name"], "env书")
            self.assertTrue(cfg["paths"]["work"].endswith("work") or os.path.isabs(cfg["paths"]["work"]))


class TestSplitWritesOffsets(unittest.TestCase):
    def test_manifest_has_start_end(self):
        import subprocess as sp
        import sys
        text = "# 正篇\n## 卷一\n### 一\n" + ("甲" * 30 + "\n") * 3 + "### 二\n" + ("乙" * 30 + "\n") * 3
        with TempProject(chunk_chars=80) as tp:
            write_extracted(tp.raw_dir(), text)
            r = sp.run([sys.executable, "-X", "utf8",
                        os.path.join(ROOT, "scripts", "01_split.py"),
                        "--config", tp.cfg_path],
                       cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            man = __import__("lib.textio", fromlist=["textio"]).read_json(
                os.path.join(tp.work, "manifest.json"))
            self.assertTrue(man)
            for m in man:
                self.assertIsInstance(m.get("start"), int)
                self.assertIsInstance(m.get("end"), int)
                self.assertGreater(m["end"], m["start"])


if __name__ == "__main__":
    unittest.main()
