# -*- coding: utf-8 -*-
"""单元测试：EPUB TOC 回退/层级推断/非正文过滤、Ruby 注音剔除、SRT/ASS/Galgame 抽取、繁简检测与 corpus 引号/脱敏。"""
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

from lib import corpus, textio
from tests.helpers import ROOT, TempProject, load_script

S00 = load_script("00_extract.py")


def _make_epub(path, opf_body, files_map, opf_path="OEBPS/content.opf"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="%s" media-type="application/oebps-package+xml"/>'
            '</rootfiles></container>' % opf_path,
        )
        z.writestr(opf_path, opf_body)
        for rel, content in files_map.items():
            z.writestr(rel, content)


class TestRubyAndHtmlParsing(unittest.TestCase):
    def test_ruby_rt_rp_skipped_in_block_parser_and_lxml(self):
        hs = (
            "<html><head><title>忽略标题</title></head><body>"
            "<h1><ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby>标题</h1>"
            "<p>前面<ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby>后面</p>"
            "<div><ruby>漢<rt>かん</rt>字<rt>じ</rt></ruby>混排<span>正常文字</span></div>"
            "<p>嵌套<ruby><rb>東京</rb><rp>（</rp><rt>とうきょう</rt><rp>）</rp></ruby>出发</p>"
            "</body></html>"
        )
        for use_lxml in (False, True):
            blocks = S00.blocks_from_html(hs, use_lxml=use_lxml)
            texts = [t for _, t in blocks]
            joined = "\n".join(texts)
            self.assertIn("漢字标题", joined, f"use_lxml={use_lxml}")
            self.assertIn("前面漢字后面", joined, f"use_lxml={use_lxml}")
            self.assertIn("漢字混排正常文字", joined, f"use_lxml={use_lxml}")
            self.assertIn("嵌套東京出发", joined, f"use_lxml={use_lxml}")
            for ruby_noise in ("かんじ", "かん", "じ", "とうきょう", "(", ")", "（", "）", "忽略标题"):
                self.assertNotIn(ruby_noise, joined, f"use_lxml={use_lxml}, noise={ruby_noise}")


class TestEpubTocAndFiltering(unittest.TestCase):
    def test_flat_calibre_ncx_recovers_h1_h2_and_drops_meta_pages(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "flat_calibre.epub")
        opf = """<package>
          <manifest>
            <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            <item id="v1" href="Text/v1_cover.xhtml"/>
            <item id="bio" href="Text/bio.xhtml"/>
            <item id="toc1" href="Text/toc1.xhtml"/>
            <item id="c1" href="Text/ch01.xhtml"/>
            <item id="c2" href="Text/ch02.xhtml"/>
            <item id="end1" href="Text/end1.xhtml"/>
            <item id="aw1" href="Text/afterword1.xhtml"/>
            <item id="aw2" href="Text/afterword2.xhtml"/>
            <item id="v2" href="Text/v2_cover.xhtml"/>
            <item id="toc2" href="Text/toc2.xhtml"/>
            <item id="c3" href="Text/ch03.xhtml"/>
            <item id="col" href="Text/colophon.xhtml"/>
          </manifest>
          <spine toc="ncx">
            <itemref idref="v1"/><itemref idref="bio"/><itemref idref="toc1"/>
            <itemref idref="c1"/><itemref idref="c2"/><itemref idref="end1"/>
            <itemref idref="aw1"/><itemref idref="aw2"/>
            <itemref idref="v2"/><itemref idref="toc2"/><itemref idref="c3"/>
            <itemref idref="col"/>
          </spine>
        </package>"""
        ncx = """<?xml version="1.0" encoding="utf-8"?>
        <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
          <navMap>
            <navPoint id="p1"><navLabel><text>冬日旋律 1</text></navLabel><content src="Text/v1_cover.xhtml"/></navPoint>
            <navPoint id="p2"><navLabel><text>目次</text></navLabel><content src="Text/toc1.xhtml"/></navPoint>
            <navPoint id="p3"><navLabel><text>第一章 初雪</text></navLabel><content src="Text/ch01.xhtml#top"/></navPoint>
            <navPoint id="p4"><navLabel><text>第二章 弦音</text></navLabel><content src="Text/ch02.xhtml"/></navPoint>
            <navPoint id="p5"><navLabel><text>后记</text></navLabel><content src="Text/afterword1.xhtml"/></navPoint>
            <navPoint id="p6"><navLabel><text>冬日旋律 2</text></navLabel><content src="Text/v2_cover.xhtml"/></navPoint>
            <navPoint id="p7"><navLabel><text>目次</text></navLabel><content src="Text/toc2.xhtml"/></navPoint>
            <navPoint id="p8"><navLabel><text>第三章 离别</text></navLabel><content src="Text/ch03.xhtml"/></navPoint>
            <navPoint id="p9"><navLabel><text>奥付</text></navLabel><content src="Text/colophon.xhtml"/></navPoint>
          </navMap>
        </ncx>"""
        files = {
            "OEBPS/toc.ncx": ncx,
            "OEBPS/Text/v1_cover.xhtml": "<html><body><div><img src='cover1.jpg'/></div></body></html>",
            "OEBPS/Text/bio.xhtml": "<html><body><p>作者 某小说家</p><p>插画 某画师，出生于东京。</p></body></html>",
            "OEBPS/Text/toc1.xhtml": "<html><body><p>目次</p><p>第一章 初雪</p><p>第二章 弦音</p></body></html>",
            "OEBPS/Text/ch01.xhtml": "<html><body><p>第一章 初雪</p><p>雪花静静地落在窗台上，教室里只剩下钢琴声。</p></body></html>",
            "OEBPS/Text/ch02.xhtml": "<html><body><p>走廊尽头的灯闪烁了一下，她停住了脚步。</p></body></html>",
            "OEBPS/Text/end1.xhtml": "<html><body><p>（终）</p></body></html>",
            "OEBPS/Text/afterword1.xhtml": "<html><body><p>后记</p><p>各位读者好久不见，这里是执笔后记第一页。</p></body></html>",
            "OEBPS/Text/afterword2.xhtml": "<html><body><p>后记第二页续写感谢名单，不应混入正文。</p></body></html>",
            "OEBPS/Text/v2_cover.xhtml": "<html><body><p>冬日旋律 2</p></body></html>",
            "OEBPS/Text/toc2.xhtml": "<html><body><p>目次</p><p>第三章 离别</p></body></html>",
            "OEBPS/Text/ch03.xhtml": "<html><body><p>月台上的风很冷，列车缓缓驶离站台。</p></body></html>",
            "OEBPS/Text/colophon.xhtml": "<html><body><p>版权所有 翻印必究 ISBN 978-4-0000-0000-0 发行所 某文库</p></body></html>",
        }
        _make_epub(epub, opf, files)

        out, heads, n = S00.extract_epub(epub, set())
        self.assertEqual(n, 12)
        text = "\n".join(out).strip() + "\n"

        self.assertEqual(
            [(h["level"], h["title"]) for h in heads],
            [
                (1, "冬日旋律 1"),
                (2, "第一章 初雪"),
                (2, "第二章 弦音"),
                (1, "冬日旋律 2"),
                (2, "第三章 离别"),
            ],
        )
        # 校验精确偏移
        for h in heads:
            self.assertTrue(text[h["offset"]:].startswith("#" * h["level"] + " " + h["title"]))

        self.assertIn("雪花静静地落在窗台上", text)
        self.assertIn("走廊尽头的灯闪烁了一下", text)
        self.assertIn("月台上的风很冷", text)
        # 首行与注入标题重复不应双写
        self.assertEqual(text.count("第一章 初雪"), 1)
        # 各类非正文页全部剔除
        for noise in ("某小说家", "某画师", "（终）", "执笔后记第一页", "后记第二页续写", "版权所有", "ISBN"):
            self.assertNotIn(noise, text)

        # 关闭 drop_builtin_meta 时保留版权/作者/后记等页
        out_raw, heads_raw, _ = S00.extract_epub(epub, set(), cfg={"drop_builtin_meta": False})
        raw_joined = "\n".join(out_raw)
        self.assertIn("某小说家", raw_joined)
        self.assertIn("执笔后记第一页", raw_joined)
        self.assertIn("版权所有", raw_joined)
        self.assertGreater(len(heads_raw), len(heads))

    def test_nested_ncx_preserves_hierarchy(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "nested_ncx.epub")
        opf = """<package>
          <manifest>
            <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            <item id="c1" href="ch1.xhtml"/>
            <item id="c2" href="ch2.xhtml"/>
          </manifest>
          <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine>
        </package>"""
        ncx = """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
          <navMap>
            <navPoint id="v1">
              <navLabel><text>第一部 晨雾</text></navLabel>
              <content src="ch1.xhtml"/>
              <navPoint id="c1">
                <navLabel><text>序幕</text></navLabel>
                <content src="ch1.xhtml#s1"/>
              </navPoint>
              <navPoint id="c2">
                <navLabel><text>第一节 渡口</text></navLabel>
                <content src="ch2.xhtml"/>
              </navPoint>
            </navPoint>
          </navMap>
        </ncx>"""
        files = {
            "OEBPS/toc.ncx": ncx,
            "OEBPS/ch1.xhtml": "<html><body><p>清晨的雾气笼罩着河面。</p></body></html>",
            "OEBPS/ch2.xhtml": "<html><body><p>渡船缓缓靠岸，木桨拍打出水花。</p></body></html>",
        }
        _make_epub(epub, opf, files)
        out, heads, _ = S00.extract_epub(epub, set())
        self.assertEqual(
            [(h["level"], h["title"]) for h in heads],
            [(1, "第一部 晨雾"), (2, "序幕"), (2, "第一节 渡口")],
        )
        self.assertEqual(heads[2].get("h1"), "第一部 晨雾")
        joined = "\n".join(out)
        self.assertIn("清晨的雾气", joined)
        self.assertIn("渡船缓缓靠岸", joined)

    def test_epub3_nav_xhtml_recovers_headings(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "epub3_nav.epub")
        opf = """<package version="3.0">
          <manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="c1" href="Text/p1.xhtml" media-type="application/xhtml+xml"/>
            <item id="c2" href="Text/p2.xhtml" media-type="application/xhtml+xml"/>
            <item id="iv" href="Text/interview.xhtml" media-type="application/xhtml+xml"/>
          </manifest>
          <spine>
            <itemref idref="c1"/><itemref idref="c2"/><itemref idref="iv"/>
          </spine>
        </package>"""
        nav = """<!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
        <body>
          <nav epub:type="toc" id="toc">
            <ol>
              <li><a href="Text/p1.xhtml">Vol.1 雪夜</a>
                <ol>
                  <li><a href="Text/p1.xhtml#ch1">第一话 相遇</a></li>
                  <li><a href="Text/p2.xhtml">第二话 琴声</a></li>
                  <li><a href="Text/interview.xhtml">巻末特別企画 インタビュー</a></li>
                </ol>
              </li>
            </ol>
          </nav>
        </body></html>"""
        files = {
            "OEBPS/nav.xhtml": nav,
            "OEBPS/Text/p1.xhtml": "<html><body><p>冬夜里路灯投下淡黄色的光晕。</p></body></html>",
            "OEBPS/Text/p2.xhtml": "<html><body><p>旧音乐室里传来熟悉的旋律。</p></body></html>",
            "OEBPS/Text/interview.xhtml": "<html><body><p>问：请问本作创作初衷是什么？</p></body></html>",
        }
        _make_epub(epub, opf, files)
        out, heads, _ = S00.extract_epub(epub, set())
        self.assertEqual(
            [(h["level"], h["title"]) for h in heads],
            [(1, "Vol.1 雪夜"), (2, "第一话 相遇"), (2, "第二话 琴声")],
        )
        joined = "\n".join(out)
        self.assertIn("路灯投下淡黄色的光晕", joined)
        self.assertIn("旧音乐室里传来熟悉的旋律", joined)
        self.assertNotIn("创作初衷", joined)

    def test_drop_file_text_and_line_patterns(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "patterns.epub")
        opf = """<package>
          <manifest>
            <item id="c1" href="Text/ch01.xhtml"/>
            <item id="ad" href="Text/promo_ad.xhtml"/>
            <item id="c2" href="Text/ch02.xhtml"/>
            <item id="tx" href="Text/extra_notice.xhtml"/>
          </manifest>
          <spine>
            <itemref idref="c1"/><itemref idref="ad"/>
            <itemref idref="c2"/><itemref idref="tx"/>
          </spine>
        </package>"""
        files = {
            "OEBPS/Text/ch01.xhtml": (
                "<html><body><h1>第一卷</h1><h2>第一章</h2>"
                "<p>Piece of: 雪菜</p><p>她把围巾绕紧了一圈。</p></body></html>"
            ),
            "OEBPS/Text/promo_ad.xhtml": (
                "<html><body><h2>新书广告</h2><p>绝赞发售中，欢迎购买下一卷。</p></body></html>"
            ),
            "OEBPS/Text/ch02.xhtml": (
                "<html><body><h2>第二章</h2>"
                "<p>Piece of：冬马</p><p>钢琴盖缓缓合上，回声渐弱。</p></body></html>"
            ),
            "OEBPS/Text/extra_notice.xhtml": (
                "<html><body><p>电子书限定特别赠品说明，扫码领取。</p></body></html>"
            ),
        }
        _make_epub(epub, opf, files)

        cfg = {
            "drop_file_patterns": [r"promo_ad\.xhtml$"],
            "drop_text_patterns": [r"电子书限定特别赠品"],
            "drop_line_patterns": [r"^Piece\s+of\s*[:：]"],
        }
        out, heads, _ = S00.extract_epub(epub, set(), cfg=cfg)
        raw_text = "\n".join(out).strip() + "\n"
        cleaned_text, cleaned_heads = S00._clean_extracted(raw_text, heads, cfg)

        self.assertIn("她把围巾绕紧了一圈。", cleaned_text)
        self.assertIn("钢琴盖缓缓合上，回声渐弱。", cleaned_text)
        self.assertNotIn("绝赞发售中", cleaned_text)
        self.assertNotIn("电子书限定特别赠品", cleaned_text)
        self.assertNotIn("Piece of", cleaned_text)

        self.assertEqual([h["title"] for h in cleaned_heads], ["第一卷", "第一章", "第二章"])
        for h in cleaned_heads:
            self.assertTrue(
                cleaned_text[h["offset"]:].startswith("#" * h["level"] + " " + h["title"]),
                (h, cleaned_text[h["offset"]:h["offset"] + 20]),
            )

    def test_flat_ncx_vol_pattern_scarce_html_and_cli_flags(self):
        td = tempfile.mkdtemp()
        epub = os.path.join(td, "vol_pat.epub")
        opf = """<package>
          <manifest>
            <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            <item id="v1" href="v1.xhtml"/>
            <item id="c1" href="c1.xhtml"/>
            <item id="c2" href="c2.xhtml"/>
            <item id="aw" href="aw.xhtml"/>
            <item id="q" href="q.xhtml"/>
          </manifest>
          <spine toc="ncx">
            <itemref idref="v1"/><itemref idref="c1"/><itemref idref="c2"/>
            <itemref idref="aw"/><itemref idref="q"/>
          </spine>
        </package>"""
        # 仅 1 个 HTML h1，但 TOC 有多条，触发稀疏回退；扁平 TOC 靠 第一卷/Vol.2 模式推断层级
        ncx = """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
          <navMap>
            <navPoint id="n1"><navLabel><text>第一卷 序幕</text></navLabel><content src="v1.xhtml"/></navPoint>
            <navPoint id="n2"><navLabel><text>初遇</text></navLabel><content src="c1.xhtml"/></navPoint>
            <navPoint id="n3"><navLabel><text>雨夜</text></navLabel><content src="c2.xhtml"/></navPoint>
          </navMap>
        </ncx>"""
        files = {
            "OEBPS/toc.ncx": ncx,
            "OEBPS/v1.xhtml": "<html><body><h1>第一卷 序幕</h1></body></html>",
            "OEBPS/c1.xhtml": "<html><body><p>Piece of: 角色A</p><p>街角咖啡馆响起门铃。</p></body></html>",
            "OEBPS/c2.xhtml": "<html><body><p>雨点敲打在伞面上。</p></body></html>",
            "OEBPS/aw.xhtml": "<html><body><p>各位读者幸会，感谢支持本书执笔完成。</p></body></html>",
            "OEBPS/q.xhtml": "<html><body><p>读者问卷调查请访问 emob.jp 参与反馈。</p></body></html>",
        }
        _make_epub(epub, opf, files)

        with TempProject() as tp:
            raw_default = os.path.join(tp.td, "raw_default")
            r1 = subprocess.run(
                [
                    sys.executable, "-X", "utf8",
                    os.path.join(ROOT, "scripts", "00_extract.py"),
                    "--config", tp.cfg_path,
                    "--source", epub,
                    "--out", raw_default,
                    "--drop-line-pattern", r"^Piece\s+of\s*[:：]",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r1.returncode, 0, r1.stderr)
            txt1 = textio.read_text(os.path.join(raw_default, "_all.txt"))
            secs1 = textio.read_json(os.path.join(raw_default, "sections.json"), [])
            self.assertEqual([(h["level"], h["title"]) for h in secs1], [(1, "第一卷 序幕"), (2, "初遇"), (2, "雨夜")])
            self.assertNotIn("Piece of", txt1)
            self.assertNotIn("各位读者幸会", txt1)
            self.assertNotIn("emob.jp", txt1)
            self.assertIn("街角咖啡馆响起门铃", txt1)

            raw_keep = os.path.join(tp.td, "raw_keep")
            r2 = subprocess.run(
                [
                    sys.executable, "-X", "utf8",
                    os.path.join(ROOT, "scripts", "00_extract.py"),
                    "--config", tp.cfg_path,
                    "--source", epub,
                    "--out", raw_keep,
                    "--no-builtin-meta",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r2.returncode, 0, r2.stderr)
            txt2 = textio.read_text(os.path.join(raw_keep, "_all.txt"))
            self.assertIn("各位读者幸会", txt2)
            self.assertIn("emob.jp", txt2)


class TestSubtitlesGalgameAndScriptVariant(unittest.TestCase):
    def test_extract_srt_and_ass(self):
        td = tempfile.mkdtemp()
        srt_p = os.path.join(td, "ep01.srt")
        textio.write_text(
            srt_p,
            "1\n00:00:01,000 --> 00:00:03,500\n<i>雪菜：</i>早安，春希君！\n\n"
            "2\n00:00:04,000 --> 00:00:06,200\n{\\an8}今天天气真冷啊。\n\n"
            "3\n00:00:07,000 --> 00:00:09,000\n「已经带了围巾吗？」\n",
        )
        out_srt, heads_srt, n_srt = S00.extract_srt(srt_p, set())
        self.assertEqual(heads_srt, [])
        self.assertEqual(n_srt, 3)
        self.assertEqual(out_srt[0], "雪菜：「早安，春希君！」")
        self.assertEqual(out_srt[1], "「今天天气真冷啊。」")
        self.assertEqual(out_srt[2], "「已经带了围巾吗？」")

        ass_p = os.path.join(td, "ep01.ass")
        textio.write_text(
            ass_p,
            "[Script Info]\nTitle: Demo\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:03.00,Default,冬马,0,0,0,,{\\pos(100,200)}别吵，\\N我在练琴。\n"
            "Dialogue: 0,0:00:04.00,0:00:06.00,Default,Default,0,0,0,,{\\i1}门外传来脚步声{\\i0}\n"
            "Dialogue: 0,0:00:07.00,0:00:09.00,Default,Comment,0,0,0,,下雪了, 真冷\n",
        )
        out_ass, heads_ass, n_ass = S00.extract_ass(ass_p, set())
        self.assertEqual(heads_ass, [])
        self.assertEqual(n_ass, 3)
        self.assertEqual(out_ass[0], "冬马：「别吵， 我在练琴。」")
        self.assertEqual(out_ass[1], "「门外传来脚步声」")
        self.assertEqual(out_ass[2], "「下雪了, 真冷」")

        # 验证 main() 自动按扩展名分发 .srt 与 .ass
        with TempProject() as tp:
            for src_p, expect in ((srt_p, "雪菜：「早安，春希君！」"), (ass_p, "冬马：「别吵， 我在练琴。」")):
                out_d = os.path.join(tp.td, "out_" + os.path.splitext(src_p)[1].lstrip("."))
                r = subprocess.run(
                    [
                        sys.executable, "-X", "utf8",
                        os.path.join(ROOT, "scripts", "00_extract.py"),
                        "--config", tp.cfg_path,
                        "--source", src_p,
                        "--out", out_d,
                    ],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(expect, textio.read_text(os.path.join(out_d, "_all.txt")))

    def test_extract_galgame_txt_and_keep_normal_txt_compatible(self):
        td = tempfile.mkdtemp()
        gal_p = os.path.join(td, "gal.txt")
        textio.write_text(
            gal_p,
            "序章 冬日\n"
            "【雪菜】今天放学后一起去练习吧。\n"
            "【春希】「好，我先去拿吉他。」\n"
            "【冬马】随便你们。\n"
            "窗外的雪越下越大。\n",
        )
        out_gal, heads_gal, _ = S00.extract_txt(gal_p, set())
        joined = "\n".join(out_gal)
        self.assertEqual([h["title"] for h in heads_gal], ["序章 冬日"])
        self.assertIn("雪菜：「今天放学后一起去练习吧。」", joined)
        self.assertIn("春希：「好，我先去拿吉他。」", joined)
        self.assertIn("冬马：「随便你们。」", joined)
        self.assertIn("窗外的雪越下越大。", joined)

        # 普通小说偶发【技能】不应误判为 Galgame 剧本
        novel_p = os.path.join(td, "novel.txt")
        textio.write_text(
            novel_p,
            "第一章 试炼\n"
            "少年推开石门，四周漆黑一片。\n"
            "他深吸一口气，缓缓抽出长剑。\n"
            "【系统提示】恭喜获得基础剑术。\n"
            "微风拂过面颊，远处传来钟声。\n"
            "他收起剑刃，沿着石阶继续向下走去。\n",
        )
        out_nov, _, _ = S00.extract_txt(novel_p, set())
        self.assertIn("【系统提示】恭喜获得基础剑术。", "\n".join(out_nov))

    def test_traditional_chinese_warning_in_extract_cli(self):
        trad_para = "他說這個時候我們應該過去看看，這件事沒有那麼簡單，聽見聲音後大家還是開門走了進去，覺得現在確實無法讓問題繼續發展下去。"
        sv = corpus.detect_script_variant(trad_para * 3)
        self.assertEqual(sv["variant"], "traditional")
        self.assertGreaterEqual(sv["trad_ratio"], 0.65)

        with TempProject() as tp:
            src = os.path.join(tp.td, "trad.txt")
            textio.write_text(src, "第一章 測試\n" + (trad_para + "\n") * 5)
            r = subprocess.run(
                [
                    sys.executable, "-X", "utf8",
                    os.path.join(ROOT, "scripts", "00_extract.py"),
                    "--config", tp.cfg_path,
                    "--source", src,
                    "--out", tp.raw_dir(),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            combined = r.stdout + "\n" + r.stderr
            self.assertIn("繁体中文", combined)
            self.assertIn("config/stylefit", combined)


class TestCorpusQuotesDividersAndAnonymizer(unittest.TestCase):
    def setUp(self):
        corpus.set_quotes(["“", "「", "『"], ["”", "」", "』"])

    def test_nested_quotes_and_extract(self):
        s = "她冷笑着开口：「平常你会说『活该！』，现在怎么不说话了？」说完转过身去。"
        qms = corpus.iter_quotes(s)
        self.assertEqual(len(qms), 1)
        self.assertEqual(qms[0].open_char, "「")
        self.assertEqual(qms[0].close_char, "」")
        self.assertEqual(qms[0].inner, "平常你会说『活该！』，现在怎么不说话了？")
        self.assertEqual(corpus.extract_quotes(s), ["平常你会说『活该！』，现在怎么不说话了？"])

    def test_inline_quotes_preserved_and_broken_fragments_filtered(self):
        paras = [
            "我只看着「他」以外的世界，却始终不敢抬头。",
            "这种「温柔」的状况，让她彻底失去了反抗的力气。",
            "林舟低声说道：「今晚别出门了。」说完拉上了窗帘。",
            "的残缺开头不应该被收录进叙述句里。",
            "这句带着未闭合括号（不应该收录。",
        ]
        sents = corpus.narr_sentences(paras)
        self.assertIn("我只看着他以外的世界，却始终不敢抬头。", sents)
        self.assertIn("这种温柔的状况，让她彻底失去了反抗的力气。", sents)
        self.assertIn("说完拉上了窗帘。", sents)
        for s in sents:
            self.assertNotIn("只看着以外", s)
            self.assertFalse(s.startswith("的残缺"))
            self.assertNotIn("未闭合括号", s)

    def test_is_divider(self):
        for d in ("◇", "＊", "◇◆◇", "＊　＊　＊", "---", "———", "***"):
            self.assertTrue(corpus.is_divider(d), d)
        for non_d in ("", "   ", "第一章", "他点点头。", "◇第一章"):
            self.assertFalse(corpus.is_divider(non_d), non_d)

    def test_build_anonymizer_terms_single_char_collapse_and_names_style(self):
        clean, rmap = corpus.build_anonymizer(
            names=["北原春希", "小木曾雪菜"],
            aliases={"北原春希": ["春希", "北原"]},
            anonymize_terms={"峰城大学": "某大学", "轻音乐同好会": "某社团"},
            single_char_names=["朋"],
            style="neutral",
            collapse_adjacent=True,
        )
        sample = (
            "北原春希在峰城大学的轻音乐同好会见到了朋，而朋也是他最好的朋友。"
            "春希北原走过去拍了拍小木曾雪菜的肩膀，使出【秘技回旋】。"
        )
        got = clean(sample)
        self.assertNotIn("北原春希", got)
        self.assertNotIn("小木曾雪菜", got)
        self.assertNotIn("峰城大学", got)
        self.assertNotIn("轻音乐同好会", got)
        self.assertNotIn("【秘技回旋】", got)
        self.assertIn("某大学", got)
        self.assertIn("某社团", got)
        # 单字名「朋」安全替换，同时完整保留「朋友」
        self.assertIn("朋友", got)
        self.assertNotIn("见到了朋", got)
        self.assertNotIn("而朋也是", got)
        # 连续重复代称合并：春希北原 -> 某甲某甲 -> 某甲
        self.assertNotIn("某甲某甲", got)
        self.assertIn("某甲走过去", got)

        # style="names" 使用自然中性人名
        clean_nat, rmap_nat = corpus.build_anonymizer(
            names=["北原春希", "小木曾雪菜"],
            style="names",
        )
        got_nat = clean_nat("北原春希看着小木曾雪菜。")
        self.assertEqual(rmap_nat["北原春希"], corpus.NATURAL_ROLES[0])
        self.assertEqual(rmap_nat["小木曾雪菜"], corpus.NATURAL_ROLES[1])
        self.assertIn(corpus.NATURAL_ROLES[0], got_nat)
        self.assertIn(corpus.NATURAL_ROLES[1], got_nat)


if __name__ == "__main__":
    unittest.main()
