# -*- coding: utf-8 -*-
"""单元测试：06b_suggest_entities.py / 07b_discover_style.py / 13b_blend_style.py。

全部只用标准库，可通过：
  python -X utf8 -m unittest tests.test_roadmap_tools -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import budget, textio  # noqa: E402
from tests import helpers as H  # noqa: E402


def _run_py(rel_script, args):
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, rel_script)] + list(args)
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _build_entity_corpus():
    """构造含角色名、敬称、机翻变体（香里/香里奈/香菜）、地点机构与英文标题的合成语料。"""
    lines = ["# 第一章 冬季排练", ""]
    for i in range(6):
        lines.extend([
            "林远说道：「今天放学后我们去白夜咖啡馆排练 WHITE ALBUM 吧。」",
            "苏晴笑了笑，对林远说：「好啊，刚出新宿车站就能看到白夜咖啡馆的招牌。」",
            "星野同学低声问道：「樱花高中轻音部的器材借到了吗？」",
            "北原学长回答：「樱花高中那边已经批准了，顺便去青山音乐厅看一眼。」",
            "我们自己都没有想到，突然心里声音响起，那个男人和少女只是站在原地。",
        ])
    # 机翻变体群：香里 / 香里奈 / 香菜 在相似语境中反复出现
    for i in range(4):
        lines.extend([
            "香里奈轻轻说道：「这首 WHITE ALBUM 的副歌节奏还要再放慢一点。」",
            "香里轻轻说道：「这首 WHITE ALBUM 的副歌节奏已经很稳了。」",
            "香菜轻轻说道：「这首 WHITE ALBUM 的副歌节奏听起来真温柔。」",
            "香里奈学姐点头微笑，转身走进樱花高中旁边的白夜咖啡馆。",
            "香里学姐点头微笑，转身走进新宿车站对面的青山音乐厅。",
        ])
    return "\n".join(lines) + "\n"


def _build_style_corpus():
    """构造带明显正向超配词、明确零频词、以及高频实词特征的合成语料。"""
    places = ("青石巷", "旧木桥", "渡口栈道", "城北茶肆", "石阶拐角")
    objs = ("宣纸折扇", "青瓷茶盏", "黄铜油灯", "牛皮账本", "竹编提篮")
    lefts = ("薄薄", "深秋", "河畔", "黎明", "林间", "山谷", "夜色", "巷尾", "桥头", "檐下")
    rights = ("漫过屋檐", "压低河面", "缠绕灯柱", "沾湿衣袖", "笼住桥洞", "拂过窗棂", "透进院墙", "散入石阶", "浮在江心", "绕着木柱")
    paras = ["# 第一章 寒夜", ""]
    for i in range(45):
        pl = places[i % len(places)]
        ob = objs[(i * 2) % len(objs)]
        lf = lefts[i % len(lefts)]
        rt = rights[(i * 3) % len(rights)]
        lf2 = lefts[(i * 7 + 1) % len(lefts)]
        rt2 = rights[(i * 5 + 2) % len(rights)]
        paras.append(
            "林舟皱了皱眉，叹了口气，转身推开%s的木门。%s的寒雾，%s，几盏灯笼在风里微晃，"
            "案上的%s带着潮气。苏晚笑了笑，摇了摇头，低声道："
            "「趁着寒雾还没%s，早点动身。」" % (pl, lf, rt, ob, rt2)
        )
        paras.append(
            "他背在身后握紧铜钥，穿过%s缓步前行。远处钟声落定，林舟在寒雾里又叹了口气，"
            "皱了皱眉，顺手收起%s的%s。" % (pl, lf2, ob)
        )
    return "\n".join(paras) + "\n"


def _build_pack_a(repeat=1):
    """合成叙述源风格包 A（含独特叙述腔/独白/笔法/描写/高频/搭配/零频/禁令，以及易区分的 A 对白）。"""
    narr_items = "\n".join(
        "- 叙述源A专属白描句%d：青石街巷笼在寒雾里，屋檐滴水敲击青砖，发出细碎脆响。" % i
        for i in range(1, 20 * repeat + 1)
    )
    craft_items = "\n".join(
        "- 叙述源A专属动作链%d：某甲抬手拭去袖口水汽，反手合拢木窗，铜栓落锁时轻响一声。" % i
        for i in range(1, 18 * repeat + 1)
    )
    intent_items = "\n".join(
        "- 叙述源A专属描写套路%d：寒风卷起阶前枯叶，灯火在湿润石面上拉出颤抖细影。" % i
        for i in range(1, 16 * repeat + 1)
    )
    return f"""# 《寒雾录》纯文风参考包

> **模式**：纯文风脱敏包

---
## 一 · 文风速览（统计靶）

- 语料规模：320000
- 台词均长：42.5 ｜ 中位：36 ｜ ≤19 字占比：0.210
- 每千字标点：{{'！': 1.2, '？': 2.5, '…': 0.8, '——': 0.3, '，': 72.0, '。': 38.0}}
- 叙述句数：9800

## 二 · 叙述腔（第三人称）

**短句(13-25字)**
{narr_items}

## 三 · 内心独白 / 吐槽（混在叙述里，不带引号的那种）

- 叙述源A专属独白：某甲暗自思忖，这笔旧账迟早要算清。
- 叙述源A专属短段：天色沉了下来。

## 四 · 细粒度笔法与镜头细节（连续动作 / 五感环境 / 神态锚点 / 转场留白）

### 连续动作白描
{craft_items}

## 五 · 对白回合片段（引号与叙述的呼吸节奏）

### 场景：日常
```
「这是A源的冗长书面台词，绝不该出现在混搭包里。」某甲缓缓说道。
```

## 六 · 语体与台词功能范例

### 陈述说明（100 条 ｜ 均长 42.5 字）
- 这是A源的台词范例，不应混入B源对白。

## 九 · 描写套路（这个意图书里怎么写）

### 寒夜氛围（原书 80 处）
{intent_items}

## 十一 · 搭配表 · 典型 vs 雷区

### 呼吸与叹气
- 叹了口气  88
- 倒吸一口凉气  0  【禁用】

### 零频黑名单（全书 0 次）

嘴角微微上扬、眼神深邃、瞳孔骤缩、倒吸一口凉气

## 十二 · 用词表与场景高频词

- **本书高频特征词**：寒雾 120 ｜ 青石 95 ｜ 铜钥 64
- **程度副词**：十分 40 ｜ 极其 0【禁用】

## 十六 · 使用禁令 / 常见误区（写完自检用）

- 叙述源A铁律：严禁使用现代网文套话「瞳孔骤缩」「嘴角微微上扬」。
"""


def _build_pack_b(repeat=1):
    """合成对白源风格包 B（含独特快节奏对白回合与语体功能，以及易区分的 B 叙述）。"""
    rounds = "\n".join(
        "```\n「对白源B专属回合%d：喂，你到底走不走啊？」\n「走走走，催什么催！」\n「那还不快点！」\n```" % i
        for i in range(1, 14 * repeat + 1)
    )
    funcs = "\n".join(
        "- 对白源B专属反问台词%d：哈？你在开什么玩笑，这也能信？" % i
        for i in range(1, 20 * repeat + 1)
    )
    return f"""# 《疾风对话集》纯文风参考包

> **模式**：纯文风脱敏包

---
## 一 · 文风速览（统计靶）

- 语料规模：180000
- 台词均长：11.2 ｜ 中位：9 ｜ ≤19 字占比：0.865
- 每千字标点：{{'！': 12.4, '？': 14.8, '…': 4.2, '——': 1.5, '，': 45.0, '。': 30.0}}
- 叙述句数：4200

## 二 · 叙述腔（第一人称）

- 这是B源的叙述句，绝不该出现在混搭包的叙述腔中。

## 三 · 内心独白 / 吐槽

- 这是B源的独白句，绝不该出现在混搭包中。

## 五 · 对白回合片段（引号与叙述的呼吸节奏）

### 场景：日常交锋
{rounds}

## 六 · 语体与台词功能范例

### 反问逼问（320 条 ｜ 均长 10.4 字 ｜ 中位 9 字 ｜ 高频句尾：吗？ ｜ 啊？）
{funcs}

## 十一 · 搭配表 · 典型 vs 雷区

### 零频黑名单（全书 0 次）
这是B源的零频词，不该覆盖A源

## 十六 · 使用禁令 / 常见误区（写完自检用）

- 这是B源的禁令，不应混入。
"""


class TestSuggestEntities(unittest.TestCase):
    def test_discovery_and_alias_clustering(self):
        mod = H.load_script("06b_suggest_entities.py")
        raw = _build_entity_corpus()
        res = mod.suggest_entities(raw, top=30)

        char_names = [c["name"] for c in res["characters"]]
        self.assertIn("林远", char_names)
        self.assertIn("苏晴", char_names)
        self.assertIn("星野", char_names)
        self.assertIn("北原", char_names)
        # 停用词与泛指词必须被过滤
        for bad in ("我们", "自己", "突然", "心里", "声音", "男人", "少女"):
            self.assertNotIn(bad, char_names)

        # 机翻变体聚类：香里 / 香里奈 / 香菜 应聚在同一簇
        clusters = res["alias_clusters"]
        self.assertTrue(clusters, "应当检测到别名/译名变体簇")
        merged_sets = [set([cl["canonical"]] + cl["variants"]) for cl in clusters]
        found_xiang = any({"香里", "香里奈", "香菜"}.issubset(s) for s in merged_sets)
        self.assertTrue(found_xiang, "应将 香里/香里奈/香菜 聚为一簇，实际：%r" % (clusters,))

        # 非人名专有设定：学校/车站/咖啡馆/音乐厅 + 英文标题
        non_person = {r["term"]: r for r in res["non_person_terms"]}
        self.assertIn("樱花高中", non_person)
        self.assertIn("白夜咖啡馆", non_person)
        self.assertIn("新宿车站", non_person)
        self.assertIn("青山音乐厅", non_person)
        self.assertIn("WHITE ALBUM", non_person)
        self.assertEqual(non_person["樱花高中"]["suggested_replacement"], "某高中")

        # project.json 片段完整性
        snip = res["project_snippet"]
        self.assertIn("names", snip)
        self.assertIn("anonymize_terms", snip)
        self.assertIn("WHITE ALBUM", snip["anonymize_terms"])

    def test_cli_json_and_config_fallback(self):
        with H.TempProject(names=["林远"]) as tp:
            H.write_extracted(tp.raw_dir(), _build_entity_corpus())
            out_json = os.path.join(tp.td, "entities.json")
            proc = _run_py(
                "scripts/06b_suggest_entities.py",
                ["--config", tp.cfg_path, "--top", "25", "--json", out_json],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("project.json", proc.stdout)
            self.assertTrue(os.path.isfile(out_json))
            data = textio.read_json(out_json)
            self.assertIn("characters", data)
            self.assertIn("alias_clusters", data)
            self.assertIn("non_person_terms", data)
            self.assertIn("project_snippet", data)
            # 已配置的 林远 应标记 configured=True
            lin = next((c for c in data["characters"] if c["name"] == "林远"), None)
            self.assertIsNotNone(lin)
            self.assertTrue(lin["configured"])


class TestDiscoverStyle(unittest.TestCase):
    def test_llr_math_and_signature_words(self):
        mod = H.load_script("07b_discover_style.py")

        # 精确 LLR 基本性质验证
        g2_pos, exp_pos, dir_pos = mod.compute_llr(obs=80, n_target=50_000, prior_per_100k=20.0)
        self.assertGreater(g2_pos, 50.0)
        self.assertAlmostEqual(exp_pos, 10.0, places=2)
        self.assertEqual(dir_pos, 1)

        g2_zero, exp_zero, dir_zero = mod.compute_llr(obs=0, n_target=100_000, prior_per_100k=60.0)
        self.assertGreater(g2_zero, 50.0)
        self.assertAlmostEqual(exp_zero, 60.0, places=2)
        self.assertEqual(dir_zero, -1)

        # 在合成语料上挖掘
        raw = _build_style_corpus()
        res = mod.discover_style(raw, top=25, exclude_terms=["林舟", "苏晚"])

        pos_terms = [r["term"] for r in res["positive_fingerprints"]]
        self.assertIn("叹了口气", pos_terms)
        self.assertIn("皱了皱眉", pos_terms)
        self.assertTrue(all(r["obs"] > r["exp"] and r["g2"] >= 0 for r in res["positive_fingerprints"]))

        zero_terms = [r["term"] for r in res["zero_freq_mines"]]
        self.assertIn("似乎", zero_terms)
        self.assertIn("瞬间", zero_terms)
        self.assertTrue(all(r["obs"] == 0 and r["g2"] >= 0 for r in res["zero_freq_mines"]))

        # 高频特征词：应抓到语料实词且排除林舟/苏晚
        sig_words = [r["word"] for r in res["signature_words"]]
        self.assertIn("寒雾", sig_words)
        self.assertNotIn("林舟", sig_words)
        self.assertNotIn("苏晚", sig_words)

    def test_cli_export_dir_compatible_with_build_index(self):
        with H.TempProject(names=["林舟", "苏晚"], aliases={"林舟": ["阿舟"]}) as tp:
            H.write_extracted(tp.raw_dir(), _build_style_corpus())
            export_dir = os.path.join(tp.td, "stylefit_auto")
            out_json = os.path.join(tp.td, "discover.json")

            proc = _run_py(
                "scripts/07b_discover_style.py",
                [
                    "--config", tp.cfg_path,
                    "--top", "20",
                    "--export-dir", export_dir,
                    "--json", out_json,
                ],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            colloc_path = os.path.join(export_dir, "colloc.json")
            words_path = os.path.join(export_dir, "words.json")
            self.assertTrue(os.path.isfile(colloc_path))
            self.assertTrue(os.path.isfile(words_path))
            self.assertTrue(os.path.isfile(out_json))

            words_data = textio.read_json(words_path)
            self.assertIn("本书高频特征词", words_data)
            self.assertIn("先验高频但本书零频（雷区）", words_data)
            self.assertNotIn("林舟", words_data["本书高频特征词"])

            # 关键端到端验证：把导出的 export_dir 直接喂给 stylefit/build_index.py
            idx_out = os.path.join(tp.td, "idx_out")
            raw_all = os.path.join(tp.raw_dir(), "_all.txt")
            bproc = _run_py(
                "stylefit/build_index.py",
                [
                    "--corpus", raw_all,
                    "--out", idx_out,
                    "--names", "林舟,苏晚",
                    "--config", export_dir,
                ],
            )
            self.assertEqual(bproc.returncode, 0, bproc.stderr + "\n" + bproc.stdout)
            idx = textio.read_json(os.path.join(idx_out, "index.json"))
            self.assertIsInstance(idx, dict)
            self.assertTrue(idx.get("搭配"))
            self.assertIn("本书高频特征词", idx.get("用词", {}))
            self.assertIn("先验高频但本书零频（雷区）", idx.get("用词", {}))
            self.assertTrue(len(idx.get("零频词", [])) > 0)


class TestBlendStyle(unittest.TestCase):
    def test_blend_direct_packs_with_budget_and_provenance(self):
        with tempfile.TemporaryDirectory(prefix="refpack_blend_") as td:
            pack_a = os.path.join(td, "pack_a.md")
            pack_b = os.path.join(td, "pack_b.md")
            out_md = os.path.join(td, "blended.md")
            textio.write_text(pack_a, _build_pack_a(repeat=3))
            textio.write_text(pack_b, _build_pack_b(repeat=3))

            target_kb = 8.0
            proc = _run_py(
                "scripts/13b_blend_style.py",
                [
                    "--narr", pack_a,
                    "--dialogue", pack_b,
                    "--out", out_md,
                    "--kb", str(target_kb),
                ],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.isfile(out_md))

            blended = textio.read_text(out_md)
            # 1. 容量合规 + 容量看板
            actual_kb = budget.utf8_kb(blended)
            self.assertLessEqual(actual_kb, target_kb * 1.08, "混搭包 %.2f KB 超出目标 %.1f KB" % (actual_kb, target_kb))
            self.assertIn("容量看板", blended)
            self.assertIn("tokens", blended)

            # 2. 冲突仲裁规则 & 反照抄红线
            self.assertIn("冲突仲裁规则", blended)
            self.assertIn("绝不被对白源带偏", blended)
            self.assertIn("严禁直接复用、拼接或仅替换主语地照抄本包例句", blended)

            # 3. 叙述、笔法、描写、零频、禁令来自 A，绝不含 B 的叙述/禁令
            self.assertIn("寒雾录", blended)
            self.assertIn("叙述源A专属白描句", blended)
            self.assertIn("叙述源A专属动作链", blended)
            self.assertIn("叙述源A专属描写套路", blended)
            self.assertIn("叙述源A铁律", blended)
            self.assertNotIn("这是B源的叙述句", blended)
            self.assertNotIn("这是B源的独白句", blended)
            self.assertNotIn("这是B源的禁令", blended)

            # 4. 对白回合、语体台词与对白统计靶来自 B，绝不含 A 的对白
            self.assertIn("疾风对话集", blended)
            self.assertIn("对白源B专属回合", blended)
            self.assertIn("对白源B专属反问台词", blended)
            self.assertIn("台词均长：11.2", blended)
            self.assertNotIn("这是A源的冗长书面台词", blended)
            self.assertNotIn("这是A源的台词范例", blended)

            # 5. 代码块栅栏成对闭合
            fences = [ln for ln in blended.splitlines() if ln.strip().startswith("```")]
            self.assertEqual(len(fences) % 2, 0, "裁剪后存在未闭合的代码块")

    def test_blend_via_project_json_configs(self):
        with H.TempProject(name="源书甲") as tp_a, H.TempProject(name="源书乙") as tp_b:
            out_a = os.path.join(tp_a.work, "out")
            out_b = os.path.join(tp_b.work, "out")
            os.makedirs(out_a, exist_ok=True)
            os.makedirs(out_b, exist_ok=True)
            textio.write_text(os.path.join(out_a, "纯文风包.md"), _build_pack_a(repeat=1))
            textio.write_text(os.path.join(out_b, "例子.txt"), _build_pack_b(repeat=1))

            out_md = os.path.join(tp_a.td, "blend_from_cfg.md")
            proc = _run_py(
                "scripts/13b_blend_style.py",
                [
                    "--narr", tp_a.cfg_path,
                    "--dialogue", tp_b.cfg_path,
                    "--out", out_md,
                    "--preset", "full",
                ],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            blended = textio.read_text(out_md)
            self.assertIn("【叙述】源书甲 × 【对白】源书乙", blended)
            self.assertIn("叙述源A专属白描句1", blended)
            self.assertIn("对白源B专属回合1", blended)
            self.assertIn("嘴角微微上扬", blended)
            self.assertIn("寒雾 120", blended)


if __name__ == "__main__":
    unittest.main()
