# -*- coding: utf-8 -*-
"""stylefit/verify.py & scripts/11_verify.py v2 全量单元测试。"""
import json
import os
import subprocess
import sys
import unittest

from lib import textio
from stylefit import verify as V
from tests.helpers import ROOT, TempProject


def _make_rich_corpus():
    """构造足够触发 4-gram 校准、参考段分桶（第一/三人称）、虚词与标点统计的合成语料。"""
    third_paras = [
        "林舟推开门走进院子，桌上放着半凉的茶。所以他也没多问，只是坐下来慢慢等。苏晚问道：「今晚住哪儿？」",
        "他低头看了一眼窗外的雨，不过风势已经小了不少。林舟摆了摆手，笑道：「算了，明天再说吧。」",
        "其实苏晚原本打算早点离开，可是街上的灯刚亮起来。她站在廊下停了片刻，轻声说：「你先歇着，我去买点干粮。」",
        "陈衡把账本合上，顺手推到桌角。果然不出所料，这批货的数目还是差了一截。他叹道：「反正还得重算一遍。」",
        "虽然天色已经暗下来，但是铺子里依然人来人往。林舟靠在椅背上，总觉得今天安静得有些反常，问道：「你看见老周了吗？」",
        "苏晚把包袱放在椅子上，微微偏过头看着他。林舟忍不住笑了笑，说：「别站着了，过来喝口热茶。」",
        "夜风从门缝里钻进来，灯芯晃了两下。他伸手拨了拨灯花，却没有立刻开口，似乎还在盘算明早的路程。",
        "林舟拿起茶杯抿了一口，觉得水温正好。陈衡在旁边补充道：「既然决定北上，明早天一亮就得动身。」",
    ]
    first_paras = [
        "我推开门走进小院，石阶上还带着湿气。所以我放慢了脚步，只是听着屋里的动静。我说：「人都在里头吗？」",
        "我低头看了看手里的信封，不过字迹早就模糊不清了。我心里想着明天的安排，说道：「先别急，慢慢来。」",
        "其实我原本不想掺和这件事，可是话都说到这个份上了。我站在门口停了一会儿，叹道：「好吧，我跟你们走一趟。」",
        "虽然外面下着细雨，但是我依然决定去街口转一圈。我总觉得漏掉了什么线索，问他：「你确定刚才没人来过？」",
        "我把外套挂在门后，倒了半杯温水。果然屋里比外面暖和得多，我靠在桌边说：「反正今天也不打算出门了。」",
        "我翻开笔记本记下几行字，抬头望向窗外。街角的小店已经关门了，我轻轻合上本子，心想终于能睡个安稳觉。",
    ]
    # 重复扩充到足够生成 >= 25 个 480-620 字参考段（第一/三人称各 >= 25 段），并让句长校准桶饱满
    lines = []
    for _ in range(45):
        lines.extend(third_paras)
    for _ in range(45):
        lines.extend(first_paras)
    return "\n".join(lines), third_paras


class TestVerifyV2Core(unittest.TestCase):
    def setUp(self):
        self.tp = TempProject()
        self.tp.__enter__()
        self.chunks = os.path.join(self.tp.work, "chunks")
        self.cache = os.path.join(self.tp.work, "cache", "测试书")
        os.makedirs(self.chunks, exist_ok=True)
        os.makedirs(self.cache, exist_ok=True)

        self.corpus_text, self.third_paras = _make_rich_corpus()
        # 在语料中放 3 次「眼眸」，测试 AI 探针严格语料拟合不误报
        self.corpus_text += "\n" + "林舟看着她清亮的眼眸，微微一笑。\n" * 3
        textio.write_text(os.path.join(self.chunks, "chunk_01.txt"), self.corpus_text)

        # 构造 index.json（含零频词、搭配、台词人物）
        self.index_data = {
            "台词": {"林舟": {}, "苏晚": {}, "陈衡": {}},
            "零频词": ["勾起嘴角", "无机质眼神"],
            "搭配": {
                "笑": {"冷笑": 2, "笑了笑": 45, "微笑": 20, "轻笑": 12, "干笑": 1},
                "看": {"凝眸": 1, "看了看": 30, "望向": 15, "瞥了一眼": 8},
            },
        }
        textio.write_json(os.path.join(self.cache, "index.json"), self.index_data)
        self.model = V.load_or_build_model(self.chunks, self.cache, no_cache=True)

    def tearDown(self):
        self.tp.__exit__(None, None, None)

    def test_layer0_garbled_scripts_corpus_fitted(self):
        draft = (
            "林舟推开门走进院子。\n"
            "桌上写着奇怪的韩文안녕和假名ありがとう。\n"
            "墙角还有西里尔字母Привет留下的痕迹。\n"
        )
        rep = V.analyze_draft(draft, "draft.txt", self.model, self.index_data, quiet=True)
        scripts = {h["script"] for h in rep["layer0"]["garbled_scripts"]}
        self.assertEqual(scripts, {"hangul", "kana", "cyrillic"})
        for h in rep["layer0"]["garbled_scripts"]:
            self.assertEqual(h["corpus_count"], 0)
            self.assertIn(h["line"], (2, 3))

        # 若语料本身含 >=5 个日文假名，则不应再对假名报警，但仍应对韩文报警
        model_with_kana = dict(self.model)
        model_with_kana["corpus_scripts"] = {"hangul": 0, "kana": 12, "cyrillic": 0}
        rep2 = V.analyze_draft(draft, "draft.txt", model_with_kana, self.index_data, quiet=True)
        scripts2 = {h["script"] for h in rep2["layer0"]["garbled_scripts"]}
        self.assertNotIn("kana", scripts2)
        self.assertIn("hangul", scripts2)
        self.assertIn("cyrillic", scripts2)

    def test_layer0_zero_freq_and_low_freq_collocations(self):
        draft = (
            "林舟勾起嘴角，用无机质眼神盯着对面。\n"
            "他发出一声冷笑，又凝眸望向远方。\n"
        )
        rep = V.analyze_draft(draft, "draft.txt", self.model, self.index_data, quiet=True)
        zf_terms = [h["term"] for h in rep["layer0"]["zero_freq_hits"]]
        self.assertIn("勾起嘴角", zf_terms)
        self.assertIn("无机质眼神", zf_terms)

        lows = {h["term"]: h for h in rep["layer0"]["low_freq_collocs"]}
        self.assertIn("冷笑", lows)
        self.assertEqual(lows["冷笑"]["corpus_freq"], 2)
        self.assertEqual(lows["冷笑"]["concept"], "笑")
        alts = [aw for aw, _ in lows["冷笑"]["alternatives"]]
        self.assertEqual(alts, ["笑了笑", "微笑", "轻笑"])
        self.assertIn("凝眸", lows)
        self.assertEqual(lows["凝眸"]["line"], 2)

    def test_layer0_punct_ai_cliches_and_structural_probes(self):
        draft = (
            "林舟推开门——走进院子——又看了看——窗外——雨还在下。\n"
            "他浑身一僵，看着她清亮的眼眸。\n"
            "她没有骂我。没有提昨天的事，也没有问我去哪了。\n"
            "他脸上没有怒意，只有疲惫。她没有回答，反而转身离开。\n"
            "苏晚的声音干涩，说：「算了，别提了。」\n"
            "屋子里的气氛格外沉闷。他坐下来依然觉得沉闷。\n"
            "林舟走过长廊。林舟推开木门。\n"
        )
        rep = V.analyze_draft(draft, "draft.txt", self.model, self.index_data, quiet=True)
        l0 = rep["layer0"]

        # 破折号在语料中为 0，草稿有多个 —— 必报警
        punct_alerts = [a["punct"] for a in l0["punct_density"]["alerts"]]
        self.assertIn("——", punct_alerts)

        # AI 套话：浑身一僵(语料 0 次)应报警；眼眸(语料 3 次)不应报警！
        ai_terms = [h["term"] for h in l0["ai_cliches"]]
        self.assertIn("浑身一僵", ai_terms)
        self.assertNotIn("眼眸", ai_terms)

        sp = l0["structural_probes"]
        # 连续否定排比
        self.assertTrue(any(h["line"] == 3 and h["count"] >= 3 for h in sp["negation_parallelism"]))
        # 否定转折套话
        self.assertGreaterEqual(len(sp["negation_contrast"]), 2)
        # 对白语气标签密度高于语料(0)
        self.assertTrue(sp["dialogue_mood_tags"]["elevated"])
        self.assertEqual(sp["dialogue_mood_tags"]["draft_hits"], 1)
        # 相邻句 2 字实词重复：捕获「沉闷」，排除角色名「林舟」
        rep_words = [h["word"] for h in sp["adjacent_word_repeats"]]
        self.assertIn("沉闷", rep_words)
        self.assertNotIn("林舟", rep_words)

    def test_copy_paste_detection_examples_and_corpus(self):
        ex_path = os.path.join(self.tp.td, "例子.txt")
        textio.write_text(
            ex_path,
            "# 示例\n> 他把旧怀表放在柜台上发出清脆声响\n- 窗外的梧桐树叶被秋风吹得沙沙作响\n",
        )
        ex_blob = V.load_examples_blob(ex_path)
        draft = (
            "这一段完全是新写的内容，讲的是早晨买菜的日常。\n"
            "他把旧怀表放在柜台上发出清脆声响，然后转身走了。\n"
            "林舟推开门走进院子，桌上放着半凉的茶，随后坐下。\n"
        )
        rep = V.analyze_draft(
            draft, "draft.txt", self.model, self.index_data,
            examples_blob=ex_blob, paste_min_len=10, quiet=True,
        )
        hits = rep["paste"]["hits"]
        sources = {(h["line"], h["source"]) for h in hits}
        self.assertIn((2, "例句"), sources)
        self.assertIn((3, "原书"), sources)
        for h in hits:
            self.assertGreaterEqual(h["length"], 10)

    def test_long_draft_threshold_and_sliding_windows(self):
        # 构造 > 1000 字长稿（复用语料真实多段分布，保证尺度不变项全落在区间内）
        long_draft = "\n".join(self.third_paras * 4)
        rep = V.analyze_draft(long_draft, "long.txt", self.model, self.index_data, quiet=True)
        th = rep["threshold"]
        self.assertTrue(th["is_long_draft"])
        self.assertNotIn("chars", th["checked_keys"])
        self.assertNotIn("paras", th["checked_keys"])
        out_keys = [x["key"] for x in th["out_of_range"]]
        self.assertNotIn("chars", out_keys)
        self.assertNotIn("paras", out_keys)
        self.assertIsNotNone(th["windows"])
        self.assertGreater(th["windows"]["total"], 1)
        self.assertGreater(th["windows"]["in_range"], 0)

    def test_proper_noun_window_masking_and_domain_terms(self):
        # 原书同款句式，只替换/插入新专名「星际港湾」(重复5次自动检出) 与领域词「跃迁引擎」
        paras = [
            "星际港湾推开门走进院子，桌上放着半凉的茶。所以他也没多问，只是坐下来慢慢等。苏晚问道：「今晚住哪儿？」",
            "星际港湾低头看了一眼窗外的雨，不过风势已经小了不少。他摆了摆手，笑道：「算了，明天再说吧。」",
            "星际港湾把账本合上，顺手推到桌角。果然不出所料，跃迁引擎的数目还是差了一截。",
            "星际港湾靠在椅背上，总觉得今天安静得有些反常，问道：「你看见老周了吗？」",
            "星际港湾拿起茶杯抿了一口，觉得水温正好。陈衡补充道：「既然决定北上，明早天一亮就得动身。」",
        ]
        draft = "\n".join(paras)
        # 测试从文件加载 domain_terms
        dt_file = os.path.join(self.tp.td, "terms.txt")
        textio.write_text(dt_file, "# 领域词表\n跃迁引擎\n")
        dterms = V.load_domain_terms(dt_file)
        self.assertEqual(dterms, ["跃迁引擎"])

        rep = V.analyze_draft(
            draft, "scifi.txt", self.model, self.index_data,
            domain_terms=dterms, quiet=False,
        )
        self.assertIn("星际港湾", rep["proper_nouns"]["auto_picked"])
        self.assertIn("跃迁引擎", rep["proper_nouns"]["masked_terms"])
        # 掩码后 0 频探针必须显著低于未掩码，且跳过了专名 4-gram
        self.assertGreater(rep["probe"]["masked_skipped_4grams"], 0)
        self.assertLess(rep["probe"]["masked_novel_rate"], rep["probe"]["novel_rate"])
        # 掩码后叙述 z 应低于未掩码（不被生造专名污染）
        self.assertLess(rep["sentence_z"]["narr_masked_mean"], rep["sentence_z"]["narr_mean"])
        # 绝不出现重复首字替换污染（如「星星星星」）
        txt_rep = V.format_text_report(rep)
        self.assertNotIn("星星星星", txt_rep)

        # 直接单测 bits(M, s, mask=...) 跳过含掩码字符的 4-gram 窗口
        s = "星际港湾推开门走进院子，桌上放着半凉的茶。"
        m = V.build_char_mask(s, ["星际港湾"])
        b_raw = V.bits(self.model["MN"], s)
        b_mask = V.bits(self.model["MN"], s, mask=m)
        self.assertIsNotNone(b_mask)
        self.assertLess(b_mask, b_raw)
        # 全句被掩码时返回 None
        self.assertIsNone(V.bits(self.model["MN"], "星际港湾", mask=[True] * 4))

    def test_cross_domain_similarity_and_pov_bucketing(self):
        first_draft = "\n".join([
            "我推开门走进小院，石阶上还带着湿气。所以我放慢了脚步，只是听着屋里的动静。我说：「人都在里头吗？」",
            "其实我原本不想掺和这件事，可是话都说到这个份上了。不过我还是站住了，叹道：「好吧，我跟你们走一趟。」",
            "虽然外面下着细雨，但是我依然决定去街口转一圈。我总觉得漏掉了什么线索，反正今天也不急。",
        ])
        rep = V.analyze_draft(
            first_draft, "first.txt", self.model, self.index_data,
            pov="auto", cross_domain=True, quiet=True,
        )
        self.assertEqual(rep["pov"]["effective"], "first")
        self.assertFalse(rep["pov"]["fallback"])
        cd = rep["cross_domain"]
        self.assertTrue(cd["enabled"])
        self.assertGreater(cd["func_cosine"], 0.6)
        self.assertGreater(cd["func_js_sim"], 0.5)
        self.assertGreater(cd["punct_cosine"], 0.7)
        txt = V.format_text_report(rep)
        self.assertIn("跨领域适配诊断", txt)

    def test_top_z_with_line_numbers_and_zero_freq_spans(self):
        draft = (
            "林舟推开门走进院子，桌上放着半凉的茶。\n"
            "他们当场握手拍板决定启动量子反应堆，全场瞬间炸了锅。\n"
            "苏晚问道：「今晚住哪儿？」\n"
        )
        rep = V.analyze_draft(draft, "topz.txt", self.model, self.index_data, top_z=5, quiet=True)
        top_list = rep["sentence_z"]["top_z_sentences"]
        self.assertTrue(top_list)
        # 最贵的一句应是第 2 行，且含合并后的 0 频子串
        top0 = top_list[0]
        self.assertEqual(top0["line"], 2)
        self.assertIn("握手拍板", top0["text"])
        self.assertTrue(top0["zero_freq_spans"])
        joined_spans = "".join(top0["zero_freq_spans"])
        self.assertIn("握手拍板", joined_spans)

    def test_guide_diff_history_and_html_outputs(self):
        v1 = os.path.join(self.tp.td, "v1.txt")
        v2 = os.path.join(self.tp.td, "v2.txt")
        textio.write_text(
            v1,
            "林舟勾起嘴角，浑身一僵，发出一声冷笑。\n"
            "他看着奇怪的韩文안녕，握手拍板砸了桌子。\n",
        )
        textio.write_text(
            v2,
            "林舟推开门走进院子，桌上放着半凉的茶。所以他也没多问，只是坐下来慢慢等。\n"
            "苏晚问道：「今晚住哪儿？」\n",
        )
        rep1 = V.analyze_draft(textio.read_text(v1), v1, self.model, self.index_data, quiet=True)
        rep2 = V.analyze_draft(textio.read_text(v2), v2, self.model, self.index_data, quiet=True)

        # Revision guide
        guide = V.format_revision_guide(rep1)
        self.assertIn("《逐行精修清单》", guide)
        self.assertIn("### L1", guide)
        self.assertIn("### L2", guide)
        self.assertIn("笑了笑", guide)
        self.assertIn("精修提示词骨架", guide)

        # Multi-version diff
        diff_md = V.format_diff_report([rep1, rep2])
        self.assertIn("多版本验收对比", diff_md)
        self.assertIn("已消除", diff_md)
        self.assertIn("勾起嘴角", diff_md)

        # JSONL history
        hist_p = os.path.join(self.tp.td, "hist.jsonl")
        V.append_history_jsonl(hist_p, rep1)
        V.append_history_jsonl(hist_p, rep2)
        rows = [json.loads(ln) for ln in textio.read_text(hist_p).strip().split("\n")]
        self.assertEqual(len(rows), 2)
        for req_k in (
            "ts", "file", "chars", "z_dial", "z_narr", "z_dial_masked",
            "z_narr_masked", "probe_ratio", "probe_ratio_masked",
            "func_sim", "layer0_issues", "paste_hits",
        ):
            self.assertIn(req_k, rows[0])
        self.assertLess(rows[1]["layer0_issues"], rows[0]["layer0_issues"])

        # Self-contained HTML heatmap（零外部 CSS/JS/CDN 资源；SVG xmlns 除外）
        html_doc = V.render_html_report(rep1, textio.read_text(v1))
        self.assertIn("<!DOCTYPE html>", html_doc)
        self.assertIn("<svg", html_doc)
        self.assertIn("hl-garbled", html_doc)
        self.assertIn("hl-l0", html_doc)
        self.assertNotIn("<link", html_doc)
        self.assertNotIn("<script", html_doc)
        self.assertNotIn("https://", html_doc)
        self.assertNotIn('href="http', html_doc)
        self.assertNotIn('src="http', html_doc)


class TestVerifyCLIAndStage11Wrapper(unittest.TestCase):
    def test_prewarm_json_diff_html_guide_and_11_verify_wrapper(self):
        with TempProject() as tp:
            chunks = os.path.join(tp.work, "chunks")
            cache = os.path.join(tp.work, "cache", "测试书")
            out_dir = os.path.join(tp.work, "out")
            os.makedirs(chunks, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            corpus_text, _ = _make_rich_corpus()
            textio.write_text(os.path.join(chunks, "chunk_01.txt"), corpus_text)
            textio.write_text(
                os.path.join(out_dir, "例子.txt"),
                "# 例句\n> 窗外梧桐树叶被秋风吹得沙沙作响\n",
            )
            v1 = os.path.join(tp.td, "v1.txt")
            v2 = os.path.join(tp.td, "v2.txt")
            textio.write_text(
                v1,
                "林舟推开门走进院子。窗外梧桐树叶被秋风吹得沙沙作响。\n"
                "苏晚问道：「今晚住哪儿？」\n",
            )
            textio.write_text(
                v2,
                "林舟推开门走进院子，桌上放着半凉的茶。\n"
                "苏晚问道：「今晚住哪儿？」\n",
            )

            s11 = os.path.join(ROOT, "scripts", "11_verify.py")

            # 1) --prewarm 不需要 --text，构建 v3 缓存
            r_pre = subprocess.run(
                [sys.executable, "-X", "utf8", s11, "--config", tp.cfg_path, "--prewarm"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r_pre.returncode, 0, r_pre.stderr + r_pre.stdout)
            self.assertTrue(os.path.isfile(os.path.join(cache, "verify_cache.pkl")))

            # 2) --json（stdout 纯 JSON）+ 自动探测 work/out/例子.txt + 裸 --log-history 落盘 logs/
            guide_p = os.path.join(tp.td, "guide.md")
            html_p = os.path.join(tp.td, "report.html")
            r_json = subprocess.run(
                [
                    sys.executable, "-X", "utf8", s11,
                    "--config", tp.cfg_path,
                    "--text", v1,
                    "--json",
                    "--guide", guide_p,
                    "--html", html_p,
                    "--log-history",
                    "--quiet",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r_json.returncode, 0, r_json.stderr)
            parsed = json.loads(r_json.stdout)
            self.assertTrue(parsed["paste"]["examples_checked"])
            self.assertTrue(any(h["source"] == "例句" for h in parsed["paste"]["hits"]))
            self.assertTrue(os.path.isfile(guide_p))
            self.assertTrue(os.path.isfile(html_p))
            hist_default = os.path.join(tp.work, "logs", "verify_history.jsonl")
            self.assertTrue(os.path.isfile(hist_default))

            # 3) --diff 不需要 --text
            r_diff = subprocess.run(
                [
                    sys.executable, "-X", "utf8", s11,
                    "--config", tp.cfg_path,
                    "--diff", v1, v2, "--quiet",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r_diff.returncode, 0, r_diff.stderr)
            self.assertIn("多版本验收对比", r_diff.stdout)


if __name__ == "__main__":
    unittest.main()
