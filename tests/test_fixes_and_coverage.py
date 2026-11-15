# -*- coding: utf-8 -*-
"""补齐 00_extract / stylefit / chat_* / llm / attrib aliases 的单测。"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

from lib import corpus, llm, project, textio
from tests.helpers import ROOT, TempProject, load_script, write_extracted

S00 = load_script("00_extract.py")
S06 = load_script("06_build_attrib.py")
S09 = load_script("09_build_examples.py")
C00 = load_script("chat_00_clean.py")
C01 = load_script("chat_01_metrics.py")
C02 = load_script("chat_02_distill.py")
C03 = load_script("chat_03_build_prompt.py")


class TestExtract(unittest.TestCase):
    def test_epub_unquotes_href_strips_fragment_and_drops(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "book.epub")
        with zipfile.ZipFile(epub, "w") as z:
            z.writestr("META-INF/container.xml",
                       '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
            z.writestr("OEBPS/content.opf", """<package>
              <manifest>
                <item id="c1" href="Text/ch%2001.xhtml#top"/>
                <item id="c2" href="Text/ch02.html"/>
              </manifest>
              <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
            </package>""")
            z.writestr("OEBPS/Text/ch 01.xhtml",
                       "<html><body><h1>卷一</h1><h2>简介</h2><p>丢弃内容</p><h2>第一章</h2><p>保留正文</p></body></html>")
            z.writestr("OEBPS/Text/ch02.html",
                       "<html><body><h3>第二章</h3><p>后续正文</p></body></html>")

        out, heads, n = S00.extract_epub(epub, {"简介"})
        joined = "\n".join(out)
        self.assertEqual(n, 2)
        self.assertIn("保留正文", joined)
        self.assertIn("后续正文", joined)
        self.assertNotIn("丢弃内容", joined)
        self.assertEqual([h["title"] for h in heads], ["卷一", "第一章", "第二章"])

    def test_txt_supports_prologue_and_drop(self):
        td = tempfile.mkdtemp()
        txt = os.path.join(td, "book.txt")
        textio.write_text(txt, "\n".join([
            "简介",
            "废话一段",
            "序章 风起",
            "序章正文在这里。",
            "第一卷 北境",
            "第十二章 归途",
            "正文章节内容。",
        ]))
        out, heads, _ = S00.extract_txt(txt, {"简介"})
        joined = "\n".join(out)
        self.assertNotIn("废话一段", joined)
        self.assertIn("序章正文在这里", joined)
        self.assertIn("正文章节内容", joined)
        self.assertEqual([h["title"] for h in heads], ["序章 风起", "第一卷 北境", "第十二章 归途"])


class TestSplitCleanupAndArcs(unittest.TestCase):
    def test_resplit_removes_stale_chunks(self):
        text = "# 正篇\n## 第一章\n" + ("甲" * 40 + "\n") * 2
        with TempProject(chunk_chars=1000) as tp:
            write_extracted(tp.raw_dir(), text)
            chunks_dir = os.path.join(tp.work, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            stale = os.path.join(chunks_dir, "chunk_99.txt")
            textio.write_text(stale, "旧书残留内容")
            r = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "01_split.py"),
                 "--config", tp.cfg_path],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.isfile(stale))
            self.assertTrue(os.path.isfile(os.path.join(chunks_dir, "chunk_01.txt")))

    def test_arc_digests_does_not_leak_interleaved_main_story(self):
        with TempProject() as tp:
            cfg = tp.load()
            parts = [
                "# 正篇",
                "## 第1章 迷雾镇（一）", "迷雾镇第一段很长很长的正文描写，足足超过了三十个字在这里占位。",
                "## 第2章 迷雾镇（二）", "迷雾镇第二段很长很长的正文描写，足足超过了三十个字在这里占位。",
                "## 第3章 迷雾镇（三）", "迷雾镇第三段很长很长的正文描写，足足超过了三十个字在这里占位。",
                "## 第4章 主线插曲", "不该泄露的主线插曲专属密钥LEAK_MAINLINE_SECRET，超过了三十个字。",
                "## 第5章 迷雾镇（四）", "迷雾镇第四段很长很长的正文描写，足足超过了三十个字在这里占位。",
            ]
            write_extracted(tp.raw_dir(), "\n".join(parts))
            arcs = S09.arc_digests(cfg, min_ch=3)
            # 只有前 3 章满足连续 >=3，不跨第4章主线抓到LEAK
            self.assertTrue(arcs)
            blob = "\n".join(arcs[0]["samples"])
            self.assertNotIn("LEAK_MAINLINE_SECRET", blob)


class TestAttribAliasesAndLLM(unittest.TestCase):
    def test_aliases_merge_to_canonical_name(self):
        corpus.set_quotes(["“"], ["”"])
        attr = S06.make_attributor(["林舟"], aliases={"林舟": ["老林"]})
        got = attr(["老林说：“今晚早点睡。”", "林舟道：“明天赶路。”"])
        self.assertEqual([g["who"] for g in got], ["林舟", "林舟"])

    def test_openai_4xx_non_retryable_and_strip_think(self):
        b = llm.OpenAIBackend({
            "base_url": "http://127.0.0.1:9/v1",
            "api_key_env": "",
            "model": "m",
            "temperature": None,
            "max_tokens": 128,
            "timeout": 5,
            "extra_body": {},
            "strip_think": True,
        })
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "<think>内部推理</think>\n最终正文"}}]
        }).encode("utf-8")
        resp.__enter__.return_value = resp
        with mock.patch("urllib.request.urlopen", return_value=resp) as m_open:
            txt = b("hi")
            self.assertEqual(txt, "最终正文")
            sent = json.loads(m_open.call_args[0][0].data.decode("utf-8"))
            self.assertNotIn("temperature", sent)

        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, io.BytesIO(b"bad key"))
        try:
            with mock.patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(llm.NonRetryableError):
                    b("hi")
        finally:
            err.close()


class TestStylefitAndChatPipeline(unittest.TestCase):
    def test_stylefit_index_query_verify_roundtrip(self):
        with TempProject() as tp:
            chunks = os.path.join(tp.work, "chunks")
            cache = os.path.join(tp.work, "cache", "测试书")
            os.makedirs(chunks, exist_ok=True)
            para = "林舟推开门坐下，笑了笑。苏晚问道：「今晚住哪儿？」"
            textio.write_text(os.path.join(chunks, "chunk_01.txt"), "\n".join([para] * 60))
            draft = os.path.join(tp.td, "draft.txt")
            textio.write_text(draft, "\n".join([para] * 6))

            r1 = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "build_index.py"),
                 "--corpus", chunks, "--out", cache, "--names", "林舟,苏晚"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertTrue(os.path.isfile(os.path.join(cache, "index.json")))

            r2 = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "verify.py"),
                 "--text", draft, "--corpus", chunks, "--out", cache, "--quiet"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertTrue(os.path.isfile(os.path.join(cache, "verify_cache.pkl")))
            # 第二次走缓存也应正常通过
            r3 = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "stylefit", "verify.py"),
                 "--text", draft, "--corpus", chunks, "--out", cache, "--quiet"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r3.returncode, 0, r3.stderr)

    def test_chat_pipeline_online_mock_and_qq_clean(self):
        td = tempfile.mkdtemp()
        work = os.path.join(td, "work")
        cfg_path = os.path.join(td, "chat.json")
        src_json = os.path.join(td, "tieba.json")
        textio.write_json(src_json, [
            {"tid": 1, "title": "这波怎么说", "comments": [
                {"floor": 1, "author": "楼主", "text": "刚买的新卡直接黑屏"},
                {"floor": 2, "author": "路人甲", "text": "玩杂牌玩的"},
                {"floor": 3, "author": "路人乙", "text": "典 建议退货"},
            ]},
        ])
        textio.write_json(cfg_path, {
            "name": "test_chat",
            "source": src_json,
            "format": "tieba_json",
            "work_dir": work,
            "min_chars": 2,
            "max_chars": 200,
            "llm": {"backend": "openai", "base_url": "http://127.0.0.1:9/v1", "model": "m"},
        })

        for script, extra in (
            ("chat_00_clean.py", ["--config", cfg_path]),
            ("chat_01_metrics.py", ["--config", cfg_path]),
        ):
            r = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", script)] + extra,
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

        # 验证 chat_02_distill 在线分支调用 llm.build() 不会出现 build_caller 属性错误
        with mock.patch("sys.argv", ["chat_02_distill.py", "--config", cfg_path]), \
             mock.patch.object(llm, "build", return_value=lambda p, system=None: "在线蒸馏特征输出") as m_build:
            C02.main()
            self.assertTrue(m_build.called)
        beh = textio.read_json(os.path.join(work, "chat_behavior.json"))
        self.assertEqual(beh["_source"], "llm_distilled")
        self.assertEqual(beh["llm_analysis_raw"], "在线蒸馏特征输出")

        out_md = os.path.join(work, "out", "prompt.md")
        r4 = subprocess.run(
            [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "chat_03_build_prompt.py"),
             "--config", cfg_path, "--name", "测试老哥", "--out", out_md],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r4.returncode, 0, r4.stderr)
        self.assertIn("在线蒸馏特征输出", textio.read_text(out_md))

        # 验证 QQ 导出按 target_user 过滤与统一 author 字段
        qq_threads, _, _ = C00.clean_qq_txt(
            "2024-01-01 12:00:00 甲\n你好啊\n2024-01-01 12:00:05 乙\n别急\n",
            {"target_user": "乙", "min_chars": 1, "max_chars": 100})
        self.assertEqual(len(qq_threads), 1)
        self.assertEqual(qq_threads[0]["topic"], "别急")


if __name__ == "__main__":
    unittest.main()
