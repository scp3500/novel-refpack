#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 6B · 实体、别名变体与专名候选发现（纯标准库，零 LLM 成本）。

  python scripts/06b_suggest_entities.py
  python scripts/06b_suggest_entities.py --corpus work/raw/_all.txt --top 40
  python scripts/06b_suggest_entities.py --config config/project.json --json work/entities_suggest.json

从语料中用启发式规则挖掘：
  1. 候选人物名（说话动词前 2–4 字汉字串 + 敬称/身份后缀前称谓词干）
  2. 候选别名 / 机翻变体簇（子串、共享双字根、同首尾字且上下文相近，如 香里/香里奈/香菜）
  3. 候选非人名专有设定（学校/地名/车站/机构/社团/反复出现的英文标题等，供 anonymize_terms）
输出可读表格与可直接复制进 config/project.json 的配置片段。
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus as C, project, textio  # noqa: E402


# ── 说话动词误报词（含说/道/问/答但并非在说话）──
NOT_SPEECH_WORDS = (
    "知道", "难道", "味道", "道路", "道理", "道歉", "街道", "轨道", "频道", "通道",
    "地道", "霸道", "公道", "报道", "一道", "道具", "说明", "小说", "听说", "据说",
    "传说", "虽说", "问题", "学问", "疑问", "访问", "叫做", "答案", "问答", "答复",
    "回答说", "说道理", "步道", "过道", "走廊道", "人行道", "说道的",
)
NOT_SPEECH_RE = re.compile("|".join(re.escape(w) for w in sorted(NOT_SPEECH_WORDS, key=len, reverse=True)))

# ── 敬称 / 职业 / 身份后缀 ──
HONORIFIC_SUFFIXES = (
    "小姐", "同学", "学长", "学姐", "老师", "先生", "阿姨", "大叔", "前辈",
    "部长", "社长", "会长", "医生", "警官", "队长", "殿下", "大人", "姑娘",
    "公子", "嫂子", "师兄", "师姐",
)
HONORIFIC_RE = re.compile(
    r"([\u4e00-\u9fff]{1,6})(" + "|".join(re.escape(s) for s in HONORIFIC_SUFFIXES) + r")"
)

# ── 非人名专有设定后缀及建议脱敏词 ──
PLACE_ORG_SUFFIX_MAP = [
    ("编辑部", "某编辑部", "机构"),
    ("出版社", "某出版社", "机构"),
    ("咖啡馆", "某咖啡馆", "场所"),
    ("咖啡厅", "某咖啡馆", "场所"),
    ("事务所", "某事务所", "机构"),
    ("俱乐部", "某俱乐部", "组织"),
    ("轻音部", "某社团", "组织"),
    ("音乐厅", "某音乐厅", "场所"),
    ("商店街", "某商业街", "地点"),
    ("高中", "某高中", "学校"),
    ("大学", "某大学", "学校"),
    ("学园", "某学院", "学校"),
    ("学院", "某学院", "学校"),
    ("中学", "某中学", "学校"),
    ("小学", "某小学", "学校"),
    ("车站", "某车站", "地点"),
    ("餐厅", "某餐厅", "场所"),
    ("医院", "某医院", "场所"),
    ("公司", "某公司", "机构"),
    ("集团", "某集团", "机构"),
    ("协会", "某协会", "组织"),
    ("商会", "某商会", "组织"),
    ("社团", "某社团", "组织"),
    ("剧场", "某剧场", "场所"),
    ("公园", "某公园", "地点"),
    ("大街", "某大街", "地点"),
    ("公寓", "某公寓", "地点"),
    ("大厦", "某大厦", "地点"),
    ("站", "某车站", "地点"),
]
_PLACE_SUFFIX_ALT = "|".join(re.escape(s) for s, _, _ in PLACE_ORG_SUFFIX_MAP)
_PLACE_SUFFIX_INFO = {s: (rep, cat) for s, rep, cat in PLACE_ORG_SUFFIX_MAP}
# 对单字「站」排除动词用法（站在/站着/站起/站立/站稳/站住/站定/站成/站好/站了/站到）
_PLACE_SUFFIX_NON_STATION = "|".join(re.escape(s) for s, _, _ in PLACE_ORG_SUFFIX_MAP if s != "站")
PLACE_ORG_RE = re.compile(
    r"([\u4e00-\u9fff]{1,8})((?:" + _PLACE_SUFFIX_NON_STATION + r")|站(?![在着起立稳住定成好了到出进过来去开回]))"
)

# ── 常见人名停用词与泛指词 ──
PERSON_STOP = set("""
自己 我们 你们 他们 她们 它们 大家 众人 旁人 别人 他人 有人 没人 无人 某人
什么 怎么 怎样 为什么 怎么会 没有 不是 可以 已经 因为 所以 但是 不过 还是 就是
只是 如果 虽然 然后 接着 于是 这个 那个 这些 那些 这里 那里 这样 那样 突然 忽然
心里 心中 内心 心头 脑海 声音 嗓音 语气 话语 目光 视线 眼光 脸上 脸颊 眼睛 眼神
眼眶 嘴角 唇角 嘴唇 眉头 眉心 手里 手上 双手 手指 脚步 脚下 背影 身影 身形 身体
时候 时间 时刻 片刻 半晌 许久 良久 对方 男人 女人 男子 女子 少年 少女 老人 老头
老者 孩子 小孩 男孩 女孩 青年 中年 妇人 众人 大家 朋友 同学 老师 先生 小姐 前辈
学长 学姐 阿姨 大叔 部长 社长 会长 医生 警官 队长 殿下 大人 姑娘 公子 嫂子 师兄 师姐
东西 地方 事情 问题 情况 状态 感觉 心情 情绪 表情 神情 神色 动作 反应 态度 样子
结果 理由 原因 办法 主意 意思 机会 可能 应该 必须 需要 想要 打算 准备 开始 结束
继续 停止 离开 回到 来到 进入 走出 走进 起来 下来 出来 过去 过来 回去 回来 看着 望着
盯着 听着 说着 笑着 哭着 走着 站着 坐着 低头 抬头 转身 回头 点头 摇头 皱眉 微笑
轻笑 冷笑 苦笑 干笑 大笑 叹气 沉默 开口 回答 回应 解释 补充 提醒 抱怨 声音 一声
一下 一眼 一刻 一瞬 一边 一面 一起 一样 一直 一定 一切 一般 所有 全部 整个 其中
其他 其余 另外 此外 而且 并且 或者 甚至 反而 原来 本来 其实 果然 竟然 居然 差点
几乎 大概 也许 不知 知道 明白 觉得 好像 似乎 仿佛 正在 刚才 以前 以后 今天 明天
昨天 晚上 白天 中午 下午 早上 清晨 傍晚 夜里 半夜 此刻 此时 这时 那时 同时 随即
随后 立刻 马上 连忙 急忙 赶紧 赶忙 缓缓 慢慢 轻轻 微微 悄悄 默默 暗暗 低声 轻声
大声 沉声 冷声 柔声 厉声 笑着 怒道 笑道 问道 说道 答道 喊道 叫道 听见 听到 看见
看到 发现 想起 记得 忘记 告诉 认为 相信 希望 担心 害怕 紧张 惊讶 疑惑 好奇 愤怒
高兴 开心 难过 伤心 失望 无奈 尴尬 害羞 冷静 认真 仔细 随便 故意 实在 确实 真的
的确 仿佛 宛如 犹如 不禁 不由 不由得 忍不住 下意识 自言自语 脱口而出 异口同声
""".split())

# 候选人物名前缀需要剥离的常见虚词/介词/动词/副词
_LEAD_STRIP_WORDS = sorted(set("""
于是 然后 接着 突然 忽然 随后 随即 立刻 马上 连忙 急忙 赶紧 赶忙 此刻 此时 这时 那时
同时 其实 不过 但是 只是 可是 所以 因为 虽然 如果 还是 或者 并且 甚至 居然 竟然 仿佛
似乎 好像 已经 正在 曾经 从未 一直 总是 仍然 依然 慢慢 缓缓 轻轻 微微 悄悄 默默 暗暗
低声 轻声 大声 沉声 冷声 柔声 抬头 低头 转身 回头 点头 摇头 看着 望着 盯着 听着 笑着
说着 想着 问着 走过 走进 走出 来到 回到 离开 站在 坐在 躺在 靠在 望着 对着 朝着 向着
跟着 替他 替她 帮他 帮她 让他 让她 叫他 叫她 见他 见她 听见 看见 发现 感到 觉得 听着
这个 那个 这位 那位 这名 那名 一个 一名 一位 两个 两人 二人 众人 大家 只有 唯有 除了
连同 以及 还有 而是 就是 不是 却是 也是 又是 才是 倒是 真是 确实 实在 真的 终于 果然
""".split()), key=len, reverse=True)

_LEAD_FUNC_CHARS = set(
    "的了着过把被对向跟给和与在从让叫使却也都就才又还再只很真挺太最一这那"
    "个位名来去说问笑看听想望盯见找等朝冲往替帮陪而但可若如既虽自他她它我你您咱"
    "没不别莫未无非将连同及或并且即便既虽"
)
_TAIL_FUNC_CHARS = set(
    "的了着过吗呢吧啊呀哦嗯哼嘛罢把被对向跟给和与在从让却也都就才又还再只地得之"
    "一这那他她它我你您没不别"
)

# 非人名专名前缀剥离词
_PLACE_LEAD_WORDS = sorted(set("""
来到 回到 走进 走出 离开 前往 经过 路过 位于 站在 坐在 住在 就在 还在 已在 正在
去了 到了 进了 出了 回了 离开 靠近 附近 对面 旁边 里面 外面 门口 门前 门外 校门
一家 这家 那家 某家 一所 这所 那所 某所 一座 这座 那座 某座 一间 这间 那间 一个
这个 那个 整个 整座 整条 附近 周边 隔壁 市区 城里 城外 街角 街头 街尾 每天 昨天
今天 明天 晚上 白天 上午 下午 中午 放学 毕业 考上 考进 考入 就读 任职 工作
""".split()), key=len, reverse=True)

_PLACE_LEAD_CHARS = set("的了着过在去到从往回进出这那某一家所座间条个栋幢")

# 明显泛指而非专名的地名/机构词
_GENERIC_PLACE_TERMS = set("""
普通高中 重点高中 私立高中 公立高中 女子高中 男子高中 市立高中 县立高中
普通大学 重点大学 私立大学 国立大学 医科大学 师范大学 音乐学院 美术学院
火车站 地铁站 公交站 汽车站 下一站 上一站 终点站 始发站 换乘站 加油站 便利站
小车站 大车站 车站 咖啡馆 咖啡厅 西餐厅 中餐厅 家庭餐厅 快餐厅 食堂餐厅 餐厅
大医院 小医院 市医院 中心医院 医院 大公司 小公司 总公司 分公司 跨国公司 公司
律师事务所 侦探事务所 事务所 学生会 理事会 委员会 董事会 运动社团 社团
电影剧场 大剧场 音乐厅 小公园 大公园 市民公园 中心公园 公园 商业大街 大街 商店街
单身公寓 高级公寓 学生公寓 破旧公寓 公寓 办公大厦 写字大厦 大厦
""".split())

# 英文专名噪声词
_EN_STOP = set("""
THE AND FOR NOT BUT WITH FROM THAT THIS HAVE BEEN WERE WILL WOULD COULD SHOULD
ABOUT AFTER BEFORE UNDER OVER INTO ONTO UPON THEN THAN WHEN WHERE WHAT WHICH
WHOSE WHILE THERE HERE YOUR THEIR OURS MINE HERS SOME MANY MUCH MORE MOST VERY
JUST ONLY ALSO EVEN STILL BACK DOWN AWAY HERE THERE OKAY YEAH NOPE SURE WELL
CHAPTER PART VOLUME PROLOGUE EPILOGUE INTERLUDE SECTION BOOK PAGE LINE NOTE
END FIN NEXT PREV MENU INFO DATA FILE TEXT HTML HTTP HTTPS UTF EPUB TXT PDF
VIP APP URL API ID OK NO YES PM AM TV CD DVD PC DJ MC VS MR MS MRS DR
""".split())

EN_TITLE_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9'&-]{1,20}(?:\s+(?:[A-Z][A-Za-z0-9'&-]{0,20}|of|the|in|on|at|to|for|and|or|a|an|de|no|wa|ga)){0,4})(?![A-Za-z0-9])"
)


# 说话动词与敬称尾部剥离（用于从「名字 + 副词/敬称 + 说话动词」中剥离动作/副词）
_SPEECH_VERBS_LIST = sorted(
    set(re.findall(r"[\u4e00-\u9fff]+", C.VERB)),
    key=len,
    reverse=True,
)
SPEECH_VERB_LONGEST_RE = re.compile("|".join(re.escape(v) for v in _SPEECH_VERBS_LIST))

_TRAIL_BEFORE_VERB_WORDS = sorted(set("""
轻轻 微微 缓缓 慢慢 低声 轻声 大声 沉声 冷声 柔声 厉声 小声 悄悄 默默 暗暗
笑着 轻笑着 冷笑着 苦笑着 干笑着 微笑着 笑眯眯地 笑着说 点头 摇头 点了点头 摇了摇头
转身 回头 转过身 回过头 抬头 低头 抬起头 低下头 皱眉 皱了皱眉 皱起眉头 叹气 叹了口气
连忙 急忙 赶紧 赶忙 突然 忽然 立刻 马上 随即 随后 再次 继续 接着 开口 顺口 脱口
不禁 不由 不由得 忍不住 下意识 认真 仔细 冷静 淡淡 淡然 平静 温柔 焦急 紧张 犹豫
迟疑 疑惑 惊讶 愤怒 兴奋 高兴 开心 无奈 尴尬 害羞 随意 随口 故意 似乎 仿佛 好像
看着 望着 盯着 听着 想着 一边 一面 同时 终于 还是 只是 倒是 却是 也是 又是 才是
实在 确实 真的 的确 竟然 居然 偏偏 果然 甚至 反而 原来 本来 其实 不过 但是 只是
""".split()) | set(HONORIFIC_SUFFIXES), key=len, reverse=True)

_TRAIL_BEFORE_VERB_CHARS = set("地得的了着过又也都就才却还再只一正在正要欲将便即乃遂")


def _strip_before_verb_tail(s):
    """剥离紧贴在说话动词前的副词、伴随动作与敬称后缀（如「香里奈轻轻」->「香里奈」）。"""
    cur = s
    changed = True
    while changed and len(cur) > 2:
        changed = False
        for w in _TRAIL_BEFORE_VERB_WORDS:
            if cur.endswith(w) and len(cur) - len(w) >= 2:
                cur = cur[:-len(w)]
                changed = True
                break
        if not changed and cur[-1] in _TRAIL_BEFORE_VERB_CHARS and len(cur) > 2:
            cur = cur[:-1]
            changed = True
    return cur


def _strip_person_prefix(s):
    """剥离候选人名前导虚词/副词/介词，保留核心 2–4 字人名。"""
    cur = s
    changed = True
    while changed and len(cur) > 2:
        changed = False
        for w in _LEAD_STRIP_WORDS:
            if cur.startswith(w) and len(cur) - len(w) >= 2:
                cur = cur[len(w):]
                changed = True
                break
        if not changed and cur[0] in _LEAD_FUNC_CHARS and len(cur) > 2:
            cur = cur[1:]
            changed = True
    while len(cur) > 2 and cur[-1] in _TAIL_FUNC_CHARS:
        cur = cur[:-1]
    return cur


_PLACE_BOUNDARY_RE = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in _PLACE_LEAD_WORDS) +
    r"|看到|看见|望见|发现|听见|找到|到达|抵达|进入|离开|冲进|跑进|踏进|步入|走出|走进|顺便|刚好|刚才|已经|正在|即将"
    r"|[的了着过在去到从往回进出把被向朝冲跟和与是有这那某])"
)


def _strip_place_prefix(stem):
    """剥离地名/机构前缀里的动词、介词、量词与虚词（含中间出现的动词边界，如「转身走进樱花」->「樱花」）。"""
    cur = stem
    # 从最后一个边界词/介词处切分，前提是切分后仍剩至少 2 字（若原后缀较长也容许 1 字）
    matches = list(_PLACE_BOUNDARY_RE.finditer(cur))
    for m in reversed(matches):
        tail = cur[m.end():]
        if len(tail) >= 2:
            cur = tail
            break
    changed = True
    while changed and cur:
        changed = False
        for w in _PLACE_LEAD_WORDS:
            if cur.startswith(w) and len(cur) > len(w):
                cur = cur[len(w):]
                changed = True
                break
        if not changed and cur and cur[0] in _PLACE_LEAD_CHARS:
            cur = cur[1:]
            changed = True
    return cur


def _valid_person_cand(w):
    if not w or not (2 <= len(w) <= 4):
        return False
    if w in PERSON_STOP:
        return False
    if w[0] in _LEAD_FUNC_CHARS or w[-1] in _TAIL_FUNC_CHARS:
        return False
    if re.search(r"[一二三四五六七八九十百千万两几每各某第]", w):
        return False
    if len(set(w)) == 1 and len(w) >= 2:
        # 保留叠字昵称（如 芳芳/莹莹）仅在非叹词时，排除 哈哈/呵呵/呜呜/啊啊
        if w[0] in "哈呵嘿嘻呜哇唉咳嗯哦啊咦噗嘎砰咚咔啪":
            return False
    return True


_GENERIC_CTX_BIGRAMS = set("""
说道 问道 答道 回答 开口 低声 轻声 大声 笑着 微笑 点头 摇头 转身 回头 看着 望着
先生 小姐 夫人 同学 学长 学姐 老师 前辈 医生 警官 队长 大人 殿下 伯爵 男爵 侯爵
""".split())

# 西方译名高频音译单字（避免仅因同含 尔/阿/德/拉 就把无关角色混为一簇）
_TRANSLIT_COMMON_CHARS = set("阿尔拉德弗贝卡巴维马罗安埃奥诺斯特克格布勒波法圣莫尔加佩里托菲迪")

_ROLE_TAIL_2 = set("夫人 先生 小姐 伯爵 男爵 侯爵 子爵 公爵 医生 警官 队长 同学 老师 学长 学姐 前辈".split())


def _collect_context_profile(raw, term, max_samples=80):
    """为候选名收集去噪后的局部上下文特征（排除泛用说话动词/敬称），用于别名聚类相似度。"""
    feats = Counter()
    start = 0
    hits = 0
    tlen = len(term)
    n = len(raw)
    while hits < max_samples:
        idx = raw.find(term, start)
        if idx == -1:
            break
        start = idx + tlen
        hits += 1
        left = raw[max(0, idx - 8):idx]
        right = raw[idx + tlen:min(n, idx + tlen + 12)]
        for ch in re.findall(r"[\u4e00-\u9fff]{2}", left):
            if ch not in _GENERIC_CTX_BIGRAMS:
                feats["L:" + ch] += 1
        for ch in re.findall(r"[\u4e00-\u9fff]{2}", right):
            if ch not in _GENERIC_CTX_BIGRAMS:
                feats["R:" + ch] += 1
        # 也纳入紧邻引号内的前 4 字语义片段（如共同提及同一首歌/事件）
        for en in re.findall(r"[A-Za-z]{3,}", right[:24]):
            feats["EN:" + en.upper()] += 2
    return feats


def _cosine_sim(c1, c2):
    if not c1 or not c2:
        return 0.0
    common = set(c1.keys()) & set(c2.keys())
    if len(common) < 2:
        return 0.0
    dot = sum(c1[k] * c2[k] for k in common)
    n1 = math.sqrt(sum(v * v for v in c1.values()))
    n2 = math.sqrt(sum(v * v for v in c2.values()))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def _pair_alias_reason(a, b, prof_a, prof_b):
    """判断两个候选名是否直接构成潜在别名/机翻变体关系，返回依据标签或 None。"""
    # 排除两词仅共享泛用头衔后缀（如 伯爵夫人 vs 男爵夫人 / 尔福夫人 vs 拉尔夫人）
    if len(a) >= 3 and len(b) >= 3 and a[-2:] == b[-2:] and a[-2:] in _ROLE_TAIL_2:
        # 除非前面字根也高度重合
        if a[:-2] != b[:-2] and not (a[:-2] in b[:-2] or b[:-2] in a[:-2]):
            return None

    # 1. 子串包含（如 香里 vs 香里奈，冬马 vs 冬马和纱，基督山 vs 基督山伯爵）
    if (len(a) >= 2 and a in b) or (len(b) >= 2 and b in a):
        short, long_ = (a, b) if len(a) < len(b) else (b, a)
        # 避免单字头衔或极泛用称谓（如 伯爵 吸附 伯爵夫人）误合并
        if short in _ROLE_TAIL_2 and long_.endswith(("夫人", "小姐", "先生")):
            return None
        return "子串包含"

    # 2. 共享 2 字前缀（如 小木曾雪 / 小木曾，香里奈 / 香里美）
    if len(a) >= 2 and len(b) >= 2 and a[:2] == b[:2] and a[:2] not in _ROLE_TAIL_2:
        return "共享双字前缀"

    # 3. 同首字 + 长度相近（<=1）+ 较高去噪上下文相似（专门捕获 香里 / 香菜 这类机翻变体）
    if abs(len(a) - len(b)) <= 1 and a[0] == b[0] and a[0] not in _TRANSLIT_COMMON_CHARS:
        sim = _cosine_sim(prof_a, prof_b)
        if sim >= 0.30:
            return "同首字+上下文相似"

    return None


def _cluster_aliases(candidates, raw, top_pool=60):
    """将可能指向同一角色或机翻变体的候选名聚类（星形归并防传递链式雪球）。"""
    pool = candidates[:top_pool]
    if len(pool) < 2:
        return []

    # 按综合分降序，强候选优先作为簇中心（canonical seed）
    ordered = sorted(pool, key=lambda r: (-r["score"], -r["total_hits"], -len(r["name"]), r["name"]))
    names = [c["name"] for c in ordered]
    info = {c["name"]: c for c in ordered}
    profiles = {nm: _collect_context_profile(raw, nm) for nm in names}

    assigned = set()
    clusters = []

    for seed in names:
        if seed in assigned:
            continue
        members = [seed]
        reasons = set()
        for other in names:
            if other == seed or other in assigned:
                continue
            # 必须直接与中心词（或已入簇的子串变体）满足直接关系，避免多跳雪球
            r = _pair_alias_reason(seed, other, profiles[seed], profiles[other])
            if not r and len(members) > 1:
                for m in members[1:]:
                    if (m in other or other in m) or (len(m) >= 2 and len(other) >= 2 and m[:2] == other[:2]):
                        r = _pair_alias_reason(m, other, profiles[m], profiles[other])
                        if r:
                            break
            if r:
                members.append(other)
                reasons.add(r)
        if len(members) < 2:
            continue
        for m in members:
            assigned.add(m)
        members.sort(key=lambda nm: (-info[nm]["score"], -info[nm]["total_hits"], -len(nm), nm))
        canonical = members[0]
        variants = members[1:]
        mt_flag = any(
            (abs(len(canonical) - len(v)) <= 1 and (canonical[0] == v[0] or canonical in v or v in canonical))
            for v in variants
        )
        clusters.append({
            "canonical": canonical,
            "variants": variants,
            "reasons": sorted(reasons),
            "suspected_mt_variant": mt_flag,
            "total_score": sum(info[m]["score"] for m in members),
        })

    clusters.sort(key=lambda c: (-c["total_score"], c["canonical"]))
    return clusters


def suggest_entities(raw, top=40, existing_names=None, min_place_hits=2, min_en_hits=2):
    """纯本地启发式抽取人物候选、别名/变体簇与非人名专有设定。"""
    paras = C.paragraphs(raw)
    total_cjk = len(re.sub(r"[^\u4e00-\u9fff]", "", raw))
    existing = set(n.strip() for n in (existing_names or []) if n and n.strip())

    speech_hits = Counter()
    honorific_hits = Counter()
    honorific_examples = defaultdict(Counter)

    # ── 1. 说话动词前 2–4 字 CJK 序列（按最长说话动词优先切分，避免「林远说道」吞成「林远说」）──
    clause_split_re = re.compile(r"[，,。！？!?\n；;：:（）()「」『』“”《》—…\s]+")

    def _extract_cand_from_clause(clause_text):
        cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", clause_text)
        if not cjk_chunks:
            return None
        raw_run = cjk_chunks[-1]
        trimmed = _strip_before_verb_tail(raw_run)
        cleaned = _strip_person_prefix(trimmed)
        cleaned = _strip_before_verb_tail(cleaned)
        if 2 <= len(cleaned) <= 4 and _valid_person_cand(cleaned):
            return cleaned
        for L in (4, 3, 2):
            if len(cleaned) >= L:
                tail = _strip_person_prefix(cleaned[-L:])
                if _valid_person_cand(tail):
                    return tail
        return None

    for p in paras:
        narr = C.strip_dialogue_quotes(p, keep_inline_text=True)
        masked = NOT_SPEECH_RE.sub(lambda m: "＿" * len(m.group(0)), narr)
        for seg in masked.split("\n"):
            for m in SPEECH_VERB_LONGEST_RE.finditer(seg):
                before = seg[:m.start()]
                if not before:
                    continue
                # 动词前紧挨否定/情态词（如「没说」「不想说」）时跳过
                if before[-1] in "不没别想要该能会敢难":
                    continue
                clauses = [c for c in clause_split_re.split(before) if c]
                if not clauses:
                    continue
                last_clause = clauses[-1]
                cand = _extract_cand_from_clause(last_clause)
                if cand:
                    speech_hits[cand] += 1
                # 若紧邻分句以「对/向/跟/朝/冲」开头（如「苏晴笑了笑，对林远说」），前一分句主语也是人物候选
                if len(clauses) >= 2 and last_clause and last_clause[0] in "对向跟朝冲替帮":
                    prev_clause = clauses[-2]
                    cjk_prev = re.findall(r"[\u4e00-\u9fff]{2,}", prev_clause)
                    if cjk_prev:
                        p_head = _strip_person_prefix(cjk_prev[0])
                        p_head = _strip_before_verb_tail(p_head)
                        # 也剥离常见简短伴随动作后缀（如「笑了笑」「叹了口气」）
                        p_head = re.sub(r"(?:笑了笑|笑着|笑|点点头|摇摇头|叹气|抬头|低头|转身|回头|微笑|轻笑|冷笑|苦笑)$", "", p_head)
                        if _valid_person_cand(p_head):
                            speech_hits[p_head] += 1

    # ── 2. 敬称 / 身份后缀前称谓词干 ──
    for p in paras:
        for m in HONORIFIC_RE.finditer(p):
            stem_raw, suf = m.group(1), m.group(2)
            stem = _strip_person_prefix(stem_raw)
            if len(stem) > 4:
                stem = stem[-3:] if _valid_person_cand(stem[-3:]) else stem[-2:]
                stem = _strip_person_prefix(stem)
            if _valid_person_cand(stem):
                honorific_hits[stem] += 1
                honorific_examples[stem][stem + suf] += 1
            elif len(stem) == 1 and stem not in _LEAD_FUNC_CHARS and stem not in _TAIL_FUNC_CHARS:
                # 单字姓 + 敬称（如 林小姐 / 王先生），作为整体候选保留
                full_form = stem + suf
                if _valid_person_cand(full_form):
                    honorific_hits[full_form] += 1
                    honorific_examples[full_form][full_form] += 1

    # ── 3. 合并评分并剔除纯子串残留（如 香里奈 -> 里奈，若 里奈 几乎不独立出现）──
    all_cands = set(speech_hits.keys()) | set(honorific_hits.keys())
    raw_counts = {w: raw.count(w) for w in all_cands}

    # 先按频次筛选基础合格项（总频次 >= 2 或有 >= 2 次强信号）
    prelim = {}
    for w in all_cands:
        sh = speech_hits[w]
        hh = honorific_hits[w]
        th = raw_counts[w]
        if (sh + hh) < 2 and th < 3:
            continue
        score = sh * 3 + hh * 2
        prelim[w] = {
            "name": w,
            "score": score,
            "speech_hits": sh,
            "honorific_hits": hh,
            "total_hits": th,
            "honorifics": [k for k, _ in honorific_examples[w].most_common(3)],
            "configured": w in existing,
        }

    # 过滤纯后缀/前缀碎片：仅当短串 >= 90% 的出现完全被更长候选覆盖且无独立敬称信号时剔除
    # （注意：若 香里 独立出现次数较多，如 香里 12 次、香里奈 6 次，会保留两者以便聚类为别名/变体）
    kept = []
    long_cands = [v for v in prelim.values() if len(v["name"]) >= 3]
    for w, rec in prelim.items():
        drop = False
        for lv in long_cands:
            lw = lv["name"]
            if len(lw) <= len(w) or w not in lw:
                continue
            standalone = rec["total_hits"] - lv["total_hits"]
            # 若短串绝大部分嵌套在长串内部，且无独立敬称，判定为正则截断碎片
            if standalone <= max(1, int(rec["total_hits"] * 0.12)) and rec["honorific_hits"] <= lv["honorific_hits"]:
                drop = True
                break
        if not drop:
            kept.append(rec)

    kept.sort(key=lambda r: (-r["score"], -r["total_hits"], -len(r["name"]), r["name"]))
    characters = kept[:top]

    # ── 4. 候选别名 / 变体聚类 ──
    alias_clusters = _cluster_aliases(kept, raw, top_pool=max(top * 2, 60))

    # ── 5. 候选非人名专有设定（地点/学校/机构/社团 + 英文专名）──
    place_counts = Counter()
    place_meta = {}
    for p in paras:
        for m in PLACE_ORG_RE.finditer(p):
            stem_raw, suf = m.group(1), m.group(2)
            stem = _strip_place_prefix(stem_raw)
            if not stem:
                continue
            # 「站」单字后缀容易误吸普通词（如 下一站 / 站在），要求前面至少 2 字且不以常见虚词收尾
            if suf == "站" and (len(stem) < 2 or stem[-1] in "一二三四五六七八九十上下前后左右这那每某"):
                continue
            term = stem + suf
            if not (2 <= len(term) <= 8):
                continue
            if term in _GENERIC_PLACE_TERMS or term in PERSON_STOP:
                continue
            if term in prelim:
                continue
            place_counts[term] += 1
            if term not in place_meta:
                rep, cat = _PLACE_SUFFIX_INFO[suf]
                place_meta[term] = (rep, cat)

    # 去除被更长专名完全包含的短片段（如 新宿车站 包含 宿车站）
    place_filtered = []
    place_items = [(t, c) for t, c in place_counts.items() if c >= min_place_hits]
    for t, c in place_items:
        subsumed = any(
            len(ot) > len(t) and t in ot and (c - oc) <= max(1, int(c * 0.15))
            for ot, oc in place_items
        )
        if subsumed:
            continue
        rep, cat = place_meta[t]
        place_filtered.append({
            "term": t,
            "category": cat,
            "count": c,
            "suggested_replacement": rep,
        })

    # 英文 / 拉丁标题短语（如 WHITE ALBUM）
    en_counts = Counter()
    for m in EN_TITLE_RE.finditer(raw):
        phrase = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(phrase) < 4:
            continue
        words = phrase.split()
        if all(w.upper() in _EN_STOP for w in words):
            continue
        if len(words) == 1 and words[0].upper() in _EN_STOP:
            continue
        en_counts[phrase] += 1

    en_items = [(t, c) for t, c in en_counts.items() if c >= min_en_hits]
    for t, c in en_items:
        subsumed = any(
            len(ot) > len(t) and t in ot and (c - oc) <= max(1, int(c * 0.15))
            for ot, oc in en_items
        )
        if subsumed:
            continue
        place_filtered.append({
            "term": t,
            "category": "英文专名/作品",
            "count": c,
            "suggested_replacement": "某作品/专名",
        })

    place_filtered.sort(key=lambda r: (-r["count"], -len(r["term"]), r["term"]))
    non_person_terms = place_filtered[:top]

    # ── 6. 构造可直接复制到 project.json 的配置片段 ──
    variant_set = set()
    aliases_snippet = {}
    for cl in alias_clusters:
        aliases_snippet[cl["canonical"]] = cl["variants"]
        variant_set.update(cl["variants"])

    names_snippet = [c["name"] for c in characters if c["name"] not in variant_set][:min(top, 30)]
    anon_snippet = {r["term"]: r["suggested_replacement"] for r in non_person_terms[:min(top, 30)]}

    snippet = {
        "names": names_snippet,
        "aliases": aliases_snippet,
        "anonymize_terms": anon_snippet,
    }

    return {
        "meta": {
            "chars_cjk": total_cjk,
            "paragraphs": len(paras),
            "top": top,
        },
        "characters": characters,
        "alias_clusters": alias_clusters,
        "non_person_terms": non_person_terms,
        "project_snippet": snippet,
    }


def _resolve_corpus_and_cfg(config_path, corpus_path):
    cfg = {}
    if config_path:
        cfg = project.load(config_path)
    elif not corpus_path:
        cfg = project.load(None)
    elif os.path.isfile(project.CONFIG):
        try:
            cfg = project.load(project.CONFIG)
        except SystemExit:
            cfg = {}

    target = corpus_path
    if not target:
        raw_all = os.path.join(cfg["paths"]["raw"], "_all.txt")
        chunks_dir = cfg["paths"]["chunks"]
        if os.path.isfile(raw_all):
            target = raw_all
        elif os.path.isdir(chunks_dir):
            target = chunks_dir
        else:
            fallback_raw = os.path.join(ROOT, "work", "raw", "_all.txt")
            fallback_chunks = os.path.join(ROOT, "work", "chunks")
            target = fallback_raw if os.path.isfile(fallback_raw) else fallback_chunks
    return cfg, target


def format_report(result, corpus_path, file_count):
    lines = []
    meta = result["meta"]
    lines.append("=== 实体与专名候选发现报告 ===")
    lines.append("语料：%s（%d 个文件 ｜ %s 汉字 ｜ %s 段）" % (
        corpus_path, file_count, format(meta["chars_cjk"], ","), format(meta["paragraphs"], ",")))
    lines.append("")

    # 表 1：候选人物名
    lines.append("## 1. 候选人物名（Top %d）" % len(result["characters"]))
    if result["characters"]:
        lines.append("| # | 候选名 | 综合分 | 说话动词前 | 敬称前 | 全文频次 | 敬称样例 | 已配置 |")
        lines.append("|---:|---|---:|---:|---:|---:|---|---|")
        for idx, c in enumerate(result["characters"], 1):
            hon = " / ".join(c["honorifics"]) if c["honorifics"] else "—"
            mark = "是" if c["configured"] else ""
            lines.append("| %d | %s | %d | %d | %d | %d | %s | %s |" % (
                idx, c["name"], c["score"], c["speech_hits"], c["honorific_hits"],
                c["total_hits"], hon, mark))
    else:
        lines.append("（未发现达到阈值的人物候选）")
    lines.append("")

    # 表 2：别名 / 变体簇
    lines.append("## 2. 候选别名 / 译名变体簇（%d 组）" % len(result["alias_clusters"]))
    if result["alias_clusters"]:
        lines.append("| 建议主名 | 候选别名 / 变体 | 疑似机翻变体 | 聚类依据 |")
        lines.append("|---|---|---|---|")
        for cl in result["alias_clusters"]:
            lines.append("| %s | %s | %s | %s |" % (
                cl["canonical"],
                "、".join(cl["variants"]),
                "是" if cl["suspected_mt_variant"] else "待核",
                "；".join(cl["reasons"]) or "—",
            ))
    else:
        lines.append("（未检测到明显的别名或译名变体簇）")
    lines.append("")

    # 表 3：非人名专有设定
    lines.append("## 3. 候选非人名专有设定（地点 / 机构 / 作品，供 anonymize_terms）")
    if result["non_person_terms"]:
        lines.append("| # | 候选专名 | 类别 | 频次 | 建议脱敏映射 |")
        lines.append("|---:|---|---|---:|---|")
        for idx, r in enumerate(result["non_person_terms"], 1):
            lines.append("| %d | %s | %s | %d | %s |" % (
                idx, r["term"], r["category"], r["count"], r["suggested_replacement"]))
    else:
        lines.append("（未发现达到阈值的非人名专有设定）")
    lines.append("")

    # 可复制 project.json 片段
    lines.append("## 4. 可直接复制到 config/project.json 的片段")
    lines.append("```json")
    lines.append(json.dumps(result["project_snippet"], ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="纯本地实体、别名变体与专名候选发现（供填写 project.json）")
    ap.add_argument("--config", default=None, help="project.json 路径（可选）")
    ap.add_argument("--corpus", default=None, help="语料文件或目录（默认回退 work/raw/_all.txt 或 work/chunks）")
    ap.add_argument("--top", type=int, default=40, help="每类最多展示前 N 项（默认 40）")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="OUT.JSON",
                    help="输出结构化 JSON（不填路径则打印到标准输出，填路径则写入文件）")
    a = ap.parse_args()

    cfg, corpus_path = _resolve_corpus_and_cfg(a.config, a.corpus)
    raw, files = C.load_corpus(corpus_path)
    if not raw.strip():
        raise SystemExit("语料为空或不存在：%s" % corpus_path)

    existing_names = list(cfg.get("names") or [])
    for canon, alts in (cfg.get("aliases") or {}).items():
        if canon:
            existing_names.append(canon)
        for al in (alts or ()):
            if al:
                existing_names.append(al)

    result = suggest_entities(raw, top=max(1, a.top), existing_names=existing_names)
    result["meta"]["corpus"] = corpus_path
    result["meta"]["files"] = len(files)

    if a.json == "-":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, corpus_path, len(files)))
        if a.json:
            textio.write_json(a.json, result)
            print("JSON 已写入：%s" % a.json)


if __name__ == "__main__":
    main()
