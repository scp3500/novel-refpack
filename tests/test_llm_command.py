# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import time
import unittest

from lib import llm, textio


class TestRenderCommand(unittest.TestCase):
    def test_does_not_use_str_format(self):
        tpl = "awk '{print}' {prompt_file} > {out_file}"
        out = llm.render_command(tpl, {"prompt_file": "/tmp/p", "out_file": "/tmp/o"})
        self.assertIn("{print}", out)
        self.assertIn("/tmp/p", out)
        self.assertIn("/tmp/o", out)

    def test_quotes_spaces(self):
        tpl = "cp {prompt_file} {out_file}"
        out = llm.render_command(tpl, {
            "prompt_file": "/tmp/a b/p.txt",
            "out_file": "/tmp/c d/o.txt",
        })
        self.assertIn("a b", out)
        self.assertIn("'", out)

    def test_respects_existing_double_quotes(self):
        tpl = 'cat "{prompt_file}" > "{out_file}"'
        out = llm.render_command(tpl, {"prompt_file": "/tmp/p", "out_file": "/tmp/o"})
        self.assertIn('"/tmp/p"', out)
        self.assertNotIn("'\"/tmp/p\"'", out)


class TestCommandBackend(unittest.TestCase):
    def _backend(self, command, **kw):
        cfg = dict(llm.DEFAULTS)
        cfg.update(backend="command", command=command, timeout=kw.pop("timeout", 15),
                   retries=1)
        cfg.update(kw)
        return llm.CommandBackend(cfg)

    def test_copies_prompt_to_out_file(self):
        td = tempfile.mkdtemp()
        dest = os.path.join(td, "nested", "missing", "out.md")
        b = self._backend("%s -c 'import shutil,sys; shutil.copy(sys.argv[1], sys.argv[2])' {prompt_file} {out_file}"
                          % sys.executable)
        got = b("你好世界", out_file=dest)
        self.assertEqual(got, "你好世界")
        # 目标文件由调用方再写；后端不得把半截结果留在 dest
        self.assertFalse(os.path.isfile(dest) and os.path.getsize(dest) > 0)

    def test_nonzero_exit_is_failure(self):
        td = tempfile.mkdtemp()
        dest = os.path.join(td, "out.md")
        textio.write_text(dest, "旧结果应保留\n")
        b = self._backend("echo hi > {out_file}; exit 1")
        with self.assertRaises(RuntimeError) as ctx:
            b("x", out_file=dest)
        self.assertIn("exit 1", str(ctx.exception))
        with open(dest, encoding="utf-8") as f:
            self.assertEqual(f.read(), "旧结果应保留\n")

    def test_empty_output_fails(self):
        b = self._backend("true")
        with self.assertRaises(RuntimeError):
            b("x")

    def test_timeout_kills_process_group(self):
        td = tempfile.mkdtemp()
        pidf = os.path.join(td, "pid")
        sleeper = (
            "import os,sys,time;"
            "open(sys.argv[1],'w').write(str(os.getpid()));"
            "time.sleep(60)"
        )
        cmd = "%s -c %s %s" % (sys.executable, repr(sleeper), pidf)
        b = self._backend(cmd, timeout=1)
        t0 = time.time()
        with self.assertRaises(TimeoutError):
            b("x")
        self.assertLess(time.time() - t0, 10)
        self.assertTrue(os.path.isfile(pidf))
        pid = int(open(pidf).read().strip())
        dead = False
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                dead = True
                break
        self.assertTrue(dead, "超时后子进程还活着 pid=%s" % pid)


if __name__ == "__main__":
    unittest.main()
