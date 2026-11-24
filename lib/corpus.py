# -*- coding: utf-8 -*-
"""语料加载、成对引号解析、脱敏与基础文本分析。

引号体系可以配：中文直角引号「」/ 弯引号“” / 单直角『』 全支持，
默认同时认三种（`set_quotes` 可改成只认你书里用的那一种，避免误切）。
"""
import os
import re
import json
import glob
from collections import Counter, namedtuple

from .textio import natural_key

CHAP = re.compile(
    r"^\s*(?:第[0-9０-９零〇一二三四五六七八九十百千两]+[章回节话卷部]|序(?:章|言|曲)|楔子|引子|尾声|终章|番外)\b"
)

DIVIDER_RE = re.compile(
    r"^(?:[-—=*~·\s　]{3,}|[◇◇◆○●□■☆★＊*・•\s　\-—_=~]+)$"
)

QUOTE_OPEN = ["“", "「", "『"]
QUOTE_CLOSE = ["”", "」", "』"]

QuoteMatch = namedtuple("QuoteMatch", ["start", "end", "inner", "open_char", "close_char"])


def _build_quote_pair_map():
    pairs = {}
    for i, o in enumerate(QUOTE_OPEN):
        c = QUOTE_CLOSE[i] if i < len(QUOTE_CLOSE) else (QUOTE_CLOSE[-1] if QUOTE_CLOSE else "")
        if o and c:
            pairs[o] = c
    return pairs


def set_quotes(opens=None, closes=None):
    """按书的实际引号体系重设（只认这几种，能少切错）。"""
    global QUOTE_OPEN, QUOTE_CLOSE, QUOTE, QUOTE_STRICT
    if opens:
        QUOTE_OPEN = list(opens)
    if closes:
        QUOTE_CLOSE = list(closes)
    o = "".join(re.escape(c) for c in QUOTE_OPEN)
    c = "".join(re.escape(c) for c in QUOTE_CLOSE)
    QUOTE = re.compile("[" + o + "]([^" + c + "]{0,600})[" + c + "]")
    QUOTE_STRICT = QUOTE


QUOTE = re.compile(
    "[" + "".join(re.escape(c) for c in QUOTE_OPEN) + "]"
    "([^" + "".join(re.escape(c) for c in QUOTE_CLOSE) + "]{0,600})"
    "[" + "".join(re.escape(c) for c in QUOTE_CLOSE) + "]"
)
QUOTE_STRICT = QUOTE


def is_divider(line):
    """判断是否为装饰性分隔线（含单字 ◇ / ＊ 等日轻常见场景分隔符）。"""
    s = (line or "").strip()
    if not s:
        return False
    if DIVIDER_RE.fullmatch(s):
        # 避免把纯中文句号/普通字母误判；至少含一个装饰符号
        return bool(re.search(r"[-—=*~·◇◇◆○●□■☆★＊*・•_=]", s))
    return False


# 轻量繁简代表高频对字（纯标准库，用于检出繁体输入静默失效）
_TRAD_SIMP_PAIRS = (
    ("說", "说"), ("這", "这"), ("們", "们"), ("個", "个"), ("來", "来"),
    ("時", "时"), ("為", "为"), ("會", "会"), ("對", "对"), ("與", "与"),
    ("沒", "没"), ("麼", "么"), ("過", "过"), ("還", "还"), ("經", "经"),
    ("發", "发"), ("開", "开"), ("見", "见"), ("問", "问"), ("話", "话"),
    ("樣", "样"), ("當", "当"), ("點", "点"), ("聽", "听"), ("學", "学"),
    ("關", "关"), ("從", "从"), ("給", "给"), ("頭", "头"), ("邊", "边"),
    ("裡", "里"), ("現", "现"), ("實", "实"), ("聲", "声"), ("動", "动"),
    ("無", "无"), ("應", "应"), ("讓", "让"), ("該", "该"), ("覺", "觉"),
)


def detect_script_variant(text, sample_chars=120000):
    """轻量繁简采样检测：统计高频繁简对字占比，用于提醒繁体语料与简体词典失配。"""
    sample = (text or "")[:sample_chars]
    trad = 0
    simp = 0
    for tc, sc in _TRAD_SIMP_PAIRS:
        trad += sample.count(tc)
        simp += sample.count(sc)
    tot = trad + simp
    if tot < 30:
        return {"variant": "unknown", "trad": trad, "simp": simp, "trad_ratio": 0.0}
    ratio = trad / tot
    if ratio >= 0.65:
        variant = "traditional"
    elif ratio <= 0.35:
        variant = "simplified"
    else:
        variant = "mixed"
    return {
        "variant": variant,
        "trad": trad,
        "simp": simp,
        "trad_ratio": round(ratio, 3),
    }


def iter_quotes(text, max_len=600):
    """成对引号栈解析器：正确识别嵌套异种引号（如「平常你会说『活该！』，现在呢？」），
    返回顶层完整引号的 QuoteMatch(start, end, inner, open_char, close_char) 列表。
    """
    if not text:
        return []
    pair_map = _build_quote_pair_map()
    if not pair_map:
        return []
    open_set = set(pair_map.keys())
    close_to_open = {}
    for o, c in pair_map.items():
        close_to_open.setdefault(c, set()).add(o)

    out = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch not in open_set:
            i += 1
            continue
        start = i
        first_open = ch
        expected_close = pair_map[first_open]
        stack = [expected_close]
        j = i + 1
        found_end = -1
        limit = min(n, start + max_len + 2)
        while j < limit:
            cj = text[j]
            if cj == "\n":
                # 跨行未闭合通常意味着原书缺右引号，避免吞掉整段
                break
            if cj == stack[-1]:
                stack.pop()
                if not stack:
                    found_end = j + 1
                    break
            elif cj in open_set and cj != stack[-1]:
                # 内层异种引号（如「里嵌『或“）
                stack.append(pair_map[cj])
            elif cj == expected_close and len(stack) > 1:
                # 内层引号漏闭合但外层已闭合：优雅收回外层
                found_end = j + 1
                break
            j += 1
        if found_end != -1:
            inner = text[start + 1:found_end - 1]
            out.append(QuoteMatch(start, found_end, inner, first_open, text[found_end - 1]))
            i = found_end
        else:
            i += 1
    return out


def extract_quotes(text, min_len=1, max_len=600):
    """抽取全部顶层成对引号内容列表。"""
    out = []
    for m in iter_quotes(text, max_len=max_len):
        s = m.inner.strip()
        if len(re.sub(r"\s", "", s)) >= min_len:
            out.append(s)
    return out


_INLINE_BEFORE_RE = re.compile(
    r"(?:的|地|得|着|为|成|叫做|称为|所谓|名为|题为|这个|那个|这种|那种|写着|印着|标着|念着|看着|听着|望着|像是|宛如|仿佛|把|将|被|用|以|对|向|从|在|和|与|及)\s*$"
)
_INLINE_AFTER_RE = re.compile(
    r"^\s*(?:的|地|得|着|了|过|之|和|与|及|等|般|似的|一样|一般|那样|这样|这种|那种|这个|那个|以外|之外|之中|之内|当中|里面|上面|下面)"
)
_SPEECH_BEFORE_RE = re.compile(
    r"(?:说|道|问|答|喊|叫|吼|嘟囔|嘟哝|低语|补充|回答|解释|抱怨|提醒|警告|宣布|嘀咕|开口|回应|呢喃|喃喃|笑道|叹道|自言自语)\s*[：:，,]?\s*$"
)
_SPEECH_COLON_RE = re.compile(r"[：:]\s*$")
_CJK_OR_ALNUM = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def is_inline_quote(para, qm):
    """判断一个成对引号是「嵌入句子成分的行内强调/书名/引语引号」还是「独立对白引号」。"""
    before = para[:qm.start]
    after = para[qm.end:]
    inner = qm.inner.strip()
    compact = re.sub(r"\s", "", inner)

    # 独立成段（引号外无实质汉字）→ 必为对白
    outside_cjk = bool(re.search(r"[\u4e00-\u9fff]", before + after))
    if not outside_cjk:
        return False

    # 明确由说话动词或冒号引出 → 对白
    if _SPEECH_BEFORE_RE.search(before) or _SPEECH_COLON_RE.search(before):
        return False

    # 紧贴语法成分（如「只看着『XX』以外」「『XX』的状况」）→ 行内引号
    if _INLINE_AFTER_RE.search(after):
        return True
    if _INLINE_BEFORE_RE.search(before) and len(compact) <= 24:
        return True

    # 短引号（≤12 字）且内部无句末标点且夹在叙述句中 → 强调词/专名/心声短语
    if len(compact) <= 12 and not re.search(r"[。！？]", inner):
        return True

    return False


def extract_dialogue_quotes(paras_or_text, min_len=2, max_len=600):
    """只抽取真正的对白台词（过滤行内短强调/书名/专名引号），支持全书无归属统计与纯文风功能桶。"""
    if isinstance(paras_or_text, str):
        lines = paragraphs(paras_or_text)
    else:
        lines = paras_or_text
    out = []
    for p in lines:
        for qm in iter_quotes(p, max_len=max_len):
            if is_inline_quote(p, qm):
                continue
            s = qm.inner.strip()
            if len(re.sub(r"\s", "", s)) >= min_len:
                out.append(s)
    return out


def strip_dialogue_quotes(para, keep_inline_text=True):
    """从段落中剔除对白引号；对行内强调/专名引号保留其文字内容（仅去引号符号），
    避免原地挖空造出「只看着以外的时间」「的状况，让……」等病句。
    """
    qms = iter_quotes(para)
    if not qms:
        return para
    parts = []
    last = 0
    for qm in qms:
        parts.append(para[last:qm.start])
        if keep_inline_text and is_inline_quote(para, qm):
            inner = qm.inner.strip()
            if _CJK_OR_ALNUM.search(inner):
                parts.append(inner)
        else:
            # 独立对白位置留换行切隔，防止前后两句粘连成一个长句
            parts.append("\n")
        last = qm.end
    parts.append(para[last:])
    return "".join(parts)


def load_corpus(path):
    """path 可以是单文件、目录（递归 .txt/.md）、或逗号分隔的多个。"""
    files = []
    for p in str(path).split(","):
        p = p.strip()
        if not p:
            continue
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "**", "*.txt"), recursive=True),
                            key=natural_key)
            files += sorted(glob.glob(os.path.join(p, "**", "*.md"), recursive=True),
                            key=natural_key)
        elif os.path.isfile(p):
            files.append(p)
    texts = []
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fp:
                texts.append(fp.read())
        except Exception:
            pass
    return "\n".join(texts), files


def paragraphs(raw):
    """去章节标题、空行、分隔线与 Markdown # 标题行。"""
    out = []
    for l in raw.split("\n"):
        s = l.strip()
        if not s or s.startswith("#") or CHAP.match(s):
            continue
        if is_divider(s):
            continue
        out.append(s)
    return out


SENT_END = re.compile(r"[^。！？…\n]*[。！？…]+|[^。！？…\n]+")

# 明显残缺伪句开头（原地剔除引号后常残余的悬空助词/介词）
_BROKEN_HEAD_RE = re.compile(
    r"^(?:的|地|得|着|了|过|之(?![前后中外])|般|似的|一样|以外|之外)"
)
_BROKEN_GAP_RE = re.compile(
    r"(?:看着以外|望着以外|听着以外|觉得的|的[。！？…]$)"
)
_BRACKET_PAIRS = (("（", "）"), ("(", ")"), ("【", "】"), ("《", "》"), ("「", "」"), ("『", "』"), ("“", "”"))


def _has_unbalanced_delims(s):
    for o, c in _BRACKET_PAIRS:
        if s.count(o) != s.count(c):
            return True
    return False


def narr_sentences(paras, min_len=5):
    """叙述句：成对剥离对白引号（保留行内强调词，绝不挖空造病句），按句切分并丢弃残缺伪句。"""
    out = []
    quote_chars = set(QUOTE_OPEN) | set(QUOTE_CLOSE)
    for p in paras:
        rest = strip_dialogue_quotes(p, keep_inline_text=True)
        for seg in rest.split("\n"):
            for s in SENT_END.findall(seg):
                s = re.sub(r"^[，,、；;：:——\s]+", "", s).strip()
                if not s:
                    continue
                if re.search(r"[：:，,、——]$", s):
                    continue
                if any(ch in quote_chars for ch in s):
                    continue
                if _has_unbalanced_delims(s):
                    continue
                if _BROKEN_HEAD_RE.match(s) or _BROKEN_GAP_RE.search(s):
                    continue
                if len(re.sub(r"\s", "", s)) >= min_len:
                    out.append(s)
    return out


def load_attribution(path):
    """归属文件：`[{who,text}]` 或 `{"who": ["台词", ...]}`"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    pairs = []
    if isinstance(d, list):
        for x in d:
            if isinstance(x, dict) and x.get("who") and x.get("text"):
                pairs.append((x["who"], x["text"]))
    elif isinstance(d, dict):
        for w, v in d.items():
            if isinstance(v, list):
                for t in v:
                    if isinstance(t, str):
                        pairs.append((w, t))
    return pairs or None


VERB = (r"(?:说|道|问|答|喊|叫|吼|嘟囔|嘟哝|低语|自言自语|补充|回答|解释|抱怨|提醒|警告|"
        r"宣布|嘀咕|开口|回应|呢喃|喃喃|说道|问道|答道|笑道|叹了口气)")
VERB_RE = re.compile(VERB)


def derive_speakers(raw, names):
    """没有归属文件时的兜底：用「名字 + 说话动词 + 引号」或剧本格式「名字：「台词」」抓。"""
    names = sorted(set(n for n in names if n), key=len, reverse=True)
    if not names:
        return []
    alt = "|".join(re.escape(n) for n in names)
    lead_re = re.compile(r"(" + alt + r")(?:[^。！？\n]{0,8}" + VERB + r"[^。！？\n]{0,6}?[：:,，]?|[：:])\s*$")
    out = []
    for ln in raw.split("\n"):
        for qm in iter_quotes(ln):
            before = ln[:qm.start]
            m = lead_re.search(before)
            if m:
                txt = qm.inner.strip()
                if len(re.sub(r"\s", "", txt)) >= 2:
                    out.append((m.group(1), txt))
    return out


# ── POV 第一/三人称段落判定 ──
_FIRST_POV_RE = re.compile(r"(?:^|[，。！？、；\s])(?:我|我的|自己|心里|心想|我却|我也|我只|我把|我被)")
_THIRD_POV_RE = re.compile(r"(?:^|[，。！？、；\s])(?:他|她|他的|她的|他却|她却|他也|她也|他们|她们)")


def detect_para_pov(para):
    """按叙述部分判定段落视角：first / third / neutral。"""
    narr = strip_dialogue_quotes(para, keep_inline_text=True)
    if len(re.sub(r"\s", "", narr)) < 8:
        return "neutral"
    f_cnt = len(_FIRST_POV_RE.findall(narr)) + narr.count("我")
    t_cnt = len(_THIRD_POV_RE.findall(narr)) + narr.count("他") + narr.count("她")
    if f_cnt >= 2 and f_cnt >= t_cnt * 2:
        return "first"
    if t_cnt >= 2 and t_cnt >= f_cnt * 2:
        return "third"
    if f_cnt > 0 and t_cnt == 0:
        return "first"
    if t_cnt > 0 and f_cnt == 0:
        return "third"
    return "neutral"


# ── 语料高频特征词提取（供模型写作时参考目标书的高频用词）──
_TOP_WORD_STOP = set("""
我们 你们 他们 她们 自己 什么 怎么 这样 那样 这个 那个 这里 那里 这些 那些
没有 不是 可以 已经 因为 所以 但是 不过 还是 就是 只是 如果 虽然 然后 接着
于是 时候 时间 东西 地方 事情 问题 一下 一起 一样 一直 一定 一个 一种 一边
一面 这么 那么 怎么 为什么 怎么会 不知道 知道 觉得 感觉 好像 应该 可能 必须
现在 刚才 以前 以后 今天 明天 昨天 大家 有人 没人 不会 不能 不要 不想 不敢
的话 的人 的事 声音 眼睛 脸上 心里 眼中 手里 嘴角 视线 表情 动作 语气 脚步
一下 一声 一眼 一刻 一瞬 出来 起来 下来 回去 过去 过来 进去 出去 上去 回来
看着 说着 笑着 听着 想着 望着 走着 站着 坐着 问着 问道 说道 回答 开口 转身
""".split())

_FUNC_STOP_CHARS = set("的了是在和就都而但也没不这那有他她它我你个一上下来去着到为以与被把给对能会要只还又于吗呢吧啊呀哦么从向让些其谁哪怎什")
_INNER_BREAK_CHARS = set("的了是在和就都而但也没不这那有他她它我你个着到为以与被把给对能会要只还又于吗呢吧啊呀哦么从向让些其谁哪怎什")


def extract_top_words(paras_or_text, top_k=60, exclude_terms=None, min_count=5):
    """纯本地从语料提取高频 2–4 字实词/习语（排除停用词、功能粘连与指定专名），
    让写作模型直接参考目标书的高频用词与语域质感。
    返回 [(词, 频次), ...]。
    """
    if isinstance(paras_or_text, str):
        paras = paragraphs(paras_or_text)
    else:
        paras = list(paras_or_text or [])
    if not paras:
        return []

    ex_set = set(t.strip() for t in (exclude_terms or []) if t and t.strip())
    cnt = {2: Counter(), 3: Counter(), 4: Counter()}
    left_ctx = {2: {}, 3: {}, 4: {}}
    right_ctx = {2: {}, 3: {}, 4: {}}

    for p in paras:
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", p):
            L = len(chunk)
            for n in (2, 3, 4):
                if L < n:
                    continue
                c_n = cnt[n]
                lc_n = left_ctx[n]
                rc_n = right_ctx[n]
                for i in range(L - n + 1):
                    w = chunk[i:i + n]
                    if w[0] in _FUNC_STOP_CHARS or w[-1] in _FUNC_STOP_CHARS:
                        continue
                    if n >= 3 and any(ch in _INNER_BREAK_CHARS for ch in w[1:-1]):
                        continue
                    c_n[w] += 1
                    lch = chunk[i - 1] if i > 0 else "^"
                    rch = chunk[i + n] if i + n < L else "$"
                    s_l = lc_n.get(w)
                    if s_l is None:
                        lc_n[w] = {lch}
                    elif len(s_l) < 8:
                        s_l.add(lch)
                    s_r = rc_n.get(w)
                    if s_r is None:
                        rc_n[w] = {rch}
                    elif len(s_r) < 8:
                        s_r.add(rch)

    total_chars = sum(len(re.sub(r"[^\u4e00-\u9fff]", "", p)) for p in paras) or 1
    dyn_min = max(min_count, int(total_chars / 60000) * 3)

    cands = {}
    for n in (4, 3, 2):
        for w, c in cnt[n].most_common(1200):
            if c < dyn_min:
                break
            if w in _TOP_WORD_STOP or w in ex_set:
                continue
            if any(ex in w or (len(ex) >= 2 and w in ex) for ex in ex_set if len(ex) >= 2):
                continue
            if len(set(w)) == 1 and len(w) >= 3:
                continue
            if len(w) >= 3 and re.search(r"[一二三四五六七八九十百千万两几每各某]", w):
                continue
            # 3/4 字词要求内部凝聚度，且在足够大语料上要求左右边界有一定自由度
            if n == 3:
                c1, c2 = cnt[2].get(w[:2], 0), cnt[2].get(w[1:], 0)
                if min(c1, c2) > 0 and c / min(c1, c2) < 0.50:
                    continue
            elif n == 4:
                c1, c2 = cnt[2].get(w[:2], 0), cnt[2].get(w[2:], 0)
                if min(c1, c2) > 0 and c / min(c1, c2) < 0.55:
                    continue
            if total_chars >= 20000 and n >= 3:
                ld = len(left_ctx[n].get(w, ()))
                rd = len(right_ctx[n].get(w, ()))
                if ld < 2 and rd < 2:
                    continue
            cands[w] = c

    # 只允许已通过清洗的更长词吸收其子碎片（如「音乐室」吸收「音乐」「乐室」）
    long_words = [(w, c) for w, c in cands.items() if len(w) >= 3]
    final = []
    for w, c in cands.items():
        if len(w) < 4:
            subsumed = sum(lc for lw, lc in long_words if len(lw) > len(w) and w in lw)
            if subsumed >= c * 0.75:
                continue
        # 2 字词若始终被同一个前字或后字锁死（半截词碎片），且该拼接词已在 cands 中，上面已吸收；
        # 若拼接词不在 cands 中（如「乐室」仅出现在「音乐室」但「音」没被吸收），用左右自由度二次把关
        if len(w) == 2 and total_chars >= 20000:
            ld = len(left_ctx[2].get(w, ()))
            rd = len(right_ctx[2].get(w, ()))
            if ld <= 1 and rd <= 1:
                continue
        final.append((w, c))

    final.sort(key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return final[:top_k]


NEUTRAL_ROLES = (
    "某甲", "某乙", "某丙", "某丁", "某戊", "某己", "某庚", "某辛",
    "角色A", "角色B", "角色C", "角色D", "角色E", "角色F", "角色G", "角色H",
)

NATURAL_ROLES = (
    "林远", "苏晴", "陈默", "周扬", "沈念", "陆川", "许安", "顾明",
    "唐宁", "方舟", "叶清", "程野", "梁音", "宋言", "江澄", "何舟",
)

BRACKET_TAG_RE = re.compile(r"【[^】\n]{2,24}】")

# 单字名默认安全边界（避免把 朋友/友情/梓木 等常见词拆坏）
_SINGLE_CHAR_COMMON_COMPOUNDS = {
    "朋": ("朋友", "亲朋", "宾朋", "良朋", "高朋", "朋辈", "朋党"),
    "明": ("明白", "明天", "明亮", "明明", "聪明", "说明", "证明", "明显", "光明", "文明", "黎明", "声明", "透明", "发明"),
    "白": ("明白", "白色", "白天", "苍白", "惨白", "白眼", "坦白", "表白", "独白", "对白", "空白", "洁白", "雪白", "白费"),
    "青": ("青春", "青年", "青色", "青草", "青涩", "青梅", "铁青", "青铜"),
    "雪": ("下雪", "白雪", "雪花", "积雪", "风雪", "暴雪", "雪白", "冰雪", "融雪", "吹雪"),
    "冬": ("冬天", "冬季", "寒冬", "深冬", "初冬", "隆冬", "冬日", "秋冬", "越冬"),
    "春": ("春天", "春季", "青春", "春日", "初春", "新春", "阳春", "春风"),
    "夏": ("夏天", "夏季", "盛夏", "初夏", "夏日", "仲夏", "春夏", "酷夏"),
    "秋": ("秋天", "秋季", "深秋", "初秋", "秋日", "秋风", "春秋", "金秋"),
}


_SINGLE_CTX_BEFORE_1 = set("叫喊找问对向跟给和与被把让帮陪见像比离爱恨骗唤称是")
_SINGLE_CTX_BEFORE_2 = ("看着", "望着", "盯着", "背叛", "告诉", "想起", "提到", "喜欢", "讨厌", "伤害", "离开", "告别", "拥抱", "亲吻")
_SINGLE_CTX_AFTER_1 = set("的也都很又才却把被对向跟给和与说说道问笑哭看走来去在是有没不会能要想点摇站坐转低抬")
_SINGLE_CTX_PUNCT = set(" \t\r\n，。！？、；：（）()「」『』“”《》—…")


def _make_single_char_replacer(ch, rep, rule=None):
    """构造单字名的安全上下文替换器：避开常见双字词，优先匹配独立称呼/受词/主语边界。"""
    esc = re.escape(ch)
    if isinstance(rule, dict):
        ex_before = rule.get("exclude_before") or ""
        ex_after = rule.get("exclude_after") or ""
        lb = ("(?<![" + re.escape(ex_before) + "])") if ex_before else ""
        la = ("(?![" + re.escape(ex_after) + "])") if ex_after else ""
        rx = re.compile(lb + esc + la)
        return lambda s: rx.sub(rep, s)

    compounds = list(_SINGLE_CHAR_COMMON_COMPOUNDS.get(ch, ()))
    before_ban = set()
    after_ban = set()
    for w in compounds:
        idx = w.find(ch)
        if idx > 0:
            before_ban.add(w[idx - 1])
        if 0 <= idx < len(w) - 1:
            after_ban.add(w[idx + 1])

    def _replace(text):
        if ch not in text:
            return text
        out = []
        n = len(text)
        i = 0
        while i < n:
            if text[i] != ch:
                out.append(text[i])
                i += 1
                continue
            prev1 = text[i - 1] if i > 0 else ""
            prev2 = text[i - 2:i] if i >= 2 else ""
            next1 = text[i + 1] if i + 1 < n else ""
            if (prev1 and prev1 in before_ban) or (next1 and next1 in after_ban):
                out.append(ch)
                i += 1
                continue
            ok_before = (not prev1) or (prev1 in _SINGLE_CTX_PUNCT) or (prev1 in _SINGLE_CTX_BEFORE_1) or (prev2 in _SINGLE_CTX_BEFORE_2)
            ok_after = (not next1) or (next1 in _SINGLE_CTX_PUNCT) or (next1 in _SINGLE_CTX_AFTER_1)
            if ok_before or ok_after:
                out.append(rep)
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    return _replace


def build_anonymizer(
    names=None,
    aliases=None,
    extra_terms=None,
    strip_brackets=True,
    anonymize_terms=None,
    single_char_names=None,
    style="neutral",
    collapse_adjacent=True,
):
    """构造专有名词脱敏函数 anonymize(text) -> str，用于纯文风蒸馏模式剥离原书人名与设定词。

    - 同一主名及其全部 aliases 会映射到同一个中性代称（保持对话回合内指代连贯）。
    - style="neutral" 使用 某甲/某乙/...；style="names" 使用自然中性人名（林远/苏晴/陈默...）。
    - anonymize_terms={"原书学校/地名": "某高中"} 支持非人名专有设定脱敏。
    - single_char_names 支持单字名安全边界替换（不破坏 朋友 等常见词）。
    - collapse_adjacent=True 自动合并连续重复代称（某甲某甲 → 某甲）。
    """
    palette = NATURAL_ROLES if style == "names" else NEUTRAL_ROLES
    canon_order = []
    alias_to_canon = {}
    for n in (names or []):
        n = (n or "").strip()
        if n and n not in canon_order:
            canon_order.append(n)
    for canon, alts in (aliases or {}).items():
        canon = (canon or "").strip()
        if not canon:
            continue
        if canon not in canon_order:
            canon_order.append(canon)
        for a in (alts or ()):
            a = (a or "").strip()
            if a and a != canon:
                alias_to_canon[a] = canon

    for t in (extra_terms or []):
        t = (t or "").strip()
        if t and t not in canon_order and t not in alias_to_canon:
            canon_order.append(t)

    role_map = {}
    for idx, c in enumerate(canon_order):
        label = palette[idx] if idx < len(palette) else ("角色%d" % (idx + 1))
        role_map[c] = label
    for a, c in alias_to_canon.items():
        role_map[a] = role_map.get(c, palette[0])

    # 非人名专有设定映射（地名/机构/曲名等），优先按长度替换
    term_map = {}
    for k, v in (anonymize_terms or {}).items():
        k = (k or "").strip()
        v = (v or "").strip()
        if k and v:
            term_map[k] = v

    # 单字人名安全替换规则
    single_rules = []
    if isinstance(single_char_names, dict):
        items_sc = list(single_char_names.items())
    else:
        items_sc = [(x, None) for x in (single_char_names or [])]
    for ch, rule in items_sc:
        ch = (ch or "").strip()
        if len(ch) != 1:
            continue
        if isinstance(rule, str) and rule.strip():
            rep = rule.strip()
            fn = _make_single_char_replacer(ch, rep, None)
        elif isinstance(rule, dict) and rule.get("replace"):
            rep = str(rule["replace"]).strip()
            fn = _make_single_char_replacer(ch, rep, rule)
        else:
            rep = role_map.get(ch)
            if not rep:
                idx = len(canon_order) + len(single_rules)
                rep = palette[idx] if idx < len(palette) else ("角色%d" % (idx + 1))
            fn = _make_single_char_replacer(ch, rep, rule)
        role_map[ch] = rep
        single_rules.append((ch, fn, rep))

    # 普通多字替换表（排除单字名，避免无边界全局误杀）
    single_chars_set = {ch for ch, _, _ in single_rules}
    merged_multi = {}
    for k, v in role_map.items():
        if k not in single_chars_set:
            merged_multi[k] = v
    merged_multi.update(term_map)

    if not merged_multi and not single_rules and not strip_brackets:
        return lambda s: s, {}

    keys = sorted(merged_multi.keys(), key=len, reverse=True)
    name_pat = re.compile("|".join(re.escape(k) for k in keys)) if keys else None

    all_labels = sorted(set(role_map.values()), key=len, reverse=True)
    dup_re = (
        re.compile(r"(" + "|".join(re.escape(lb) for lb in all_labels) + r")\1+")
        if (collapse_adjacent and all_labels) else None
    )

    def _clean(s):
        if not s:
            return s
        out = s
        if name_pat is not None:
            out = name_pat.sub(lambda m: merged_multi[m.group(0)], out)
        for _ch, fn, _rep in single_rules:
            if _ch in out:
                out = fn(out)
        if strip_brackets:
            out = BRACKET_TAG_RE.sub("「某技能/条目」", out)
        if dup_re is not None:
            out = dup_re.sub(r"\1", out)
        return out

    full_map = dict(role_map)
    full_map.update(term_map)
    return _clean, full_map
