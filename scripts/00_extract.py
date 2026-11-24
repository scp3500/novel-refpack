#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 0 · 抽文本：epub / docx / txt / srt / ass → 带结构标记的全文。

  python scripts/00_extract.py                       # 用 config 里的 source
  python scripts/00_extract.py --source book.epub
  python scripts/00_extract.py --drop "简介,制作信息,封面及彩页"
  python scripts/00_extract.py --no-builtin-meta

产出：
  raw/_all.txt       全文，`# h1 / ## h2 / ### h3` 标记 + 段落行
  raw/sections.json  各级标题清单（含字符偏移，供分片与卷映射定位）

为什么要保留层级：分片要按卷/章边界切，索引要按版块定位，丢了层级后面全靠猜。
"""
import os
import re
import sys
import html
import zipfile
import argparse
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import corpus, project, textio      # noqa: E402

BLOCK = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIP_TAGS = {"head", "script", "style", "rt", "rp"}

LEAF_CONTAINERS = {"div", "li", "blockquote"}
SUB_BLOCKS = set(BLOCK) | {"p"} | LEAF_CONTAINERS


class BlockParser(HTMLParser):
    """把 HTML 拆成 (tag, text) 的块序列。h1-h6、p、li 作为块，div/blockquote 仅作叶子块。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._cur = None
        self._buf = []
        self._skip = 0

    def _flush(self, tag=None):
        t = " ".join("".join(self._buf).split())
        if t and (tag or self._cur):
            self.blocks.append((tag or self._cur, t))
        self._buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in BLOCK:
            self._flush(self._cur or "p")
            self._cur = tag
        elif tag in ("p", "li"):
            self._flush(self._cur or "p")
            self._cur = "p"
        elif tag in ("div", "blockquote"):
            self._flush(self._cur or "p")
        elif tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in BLOCK:
            if self._cur == tag or self._cur in BLOCK:
                self._flush(tag)
                self._cur = None
        elif tag in ("p", "li"):
            if self._cur in ("p", None):
                self._flush("p")
                self._cur = None
        elif tag in ("div", "blockquote") and self._cur is None:
            self._flush("p")

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)


def _lxml_text(node):
    """递归收集 lxml 节点文本，跳过 head/script/style/rt/rp 并保留 child.tail。"""
    parts = []

    def _collect(el):
        if not isinstance(el.tag, str):
            return
        tag = el.tag.lower()
        if tag in SKIP_TAGS:
            return
        if el.text:
            parts.append(el.text)
        for child in el:
            if isinstance(child.tag, str):
                ctag = child.tag.lower()
                if ctag == "br":
                    parts.append("\n")
                elif ctag not in SKIP_TAGS:
                    _collect(child)
            if child.tail:
                parts.append(child.tail)

    _collect(node)
    return parts


def _lxml_walk(el, out):
    def clean_txt(chunks):
        return " ".join("".join(chunks).split())

    def has_sub_block(node):
        return any(
            isinstance(d.tag, str) and d.tag.lower() in SUB_BLOCKS
            for d in node.iterdescendants()
        )

    def walk(node):
        if not isinstance(node.tag, str):
            return
        tag = node.tag.lower()
        if tag in SKIP_TAGS:
            return
        if tag in BLOCK:
            t = clean_txt(_lxml_text(node))
            if t:
                out.append((tag, t))
            return
        if tag == "p" and not has_sub_block(node):
            t = clean_txt(_lxml_text(node))
            if t:
                out.append(("p", t))
            return
        if tag in LEAF_CONTAINERS and not has_sub_block(node):
            t = clean_txt(_lxml_text(node))
            if t:
                out.append(("p", t))
            return

        buf = []
        if node.text:
            buf.append(node.text)

        def flush_buf():
            t = clean_txt(buf)
            if t:
                out.append(("p", t))
            buf.clear()

        for child in node:
            ctag = child.tag.lower() if isinstance(child.tag, str) else ""
            if ctag in SKIP_TAGS:
                if child.tail:
                    buf.append(child.tail)
                continue
            if ctag in SUB_BLOCKS or (ctag and has_sub_block(child)):
                flush_buf()
                walk(child)
            elif ctag == "br":
                buf.append("\n")
            elif ctag:
                buf.extend(_lxml_text(child))
            if child.tail:
                buf.append(child.tail)
        flush_buf()

    walk(el)


def blocks_from_html(hs, use_lxml=False):
    if use_lxml:
        try:
            from lxml import html as LH
            hs_clean = re.sub(r"^\s*<\?xml[^>]*\?>", "", hs)
            doc = LH.fromstring(hs_clean)
            root = getattr(doc, "body", None)
            if root is None:
                root = doc
            out = []
            _lxml_walk(root, out)
            if out:
                return out
        except Exception:
            pass
    p = BlockParser()
    p.feed(hs)
    p._flush(p._cur or "p")
    return p.blocks


# ── EPUB OPF / TOC 解析与非正文页过滤 ──

def _norm_epub_path(base_dir, href):
    raw = urllib.parse.unquote((href or "").split("#", 1)[0].split("?", 1)[0]).strip()
    if not raw:
        return ""
    joined = os.path.normpath(os.path.join(base_dir, raw)).replace("\\", "/")
    while joined.startswith("./"):
        joined = joined[2:]
    return joined.lstrip("/")


def _zip_read_text(z, path, name_map=None):
    if not path:
        return None
    try:
        return z.read(path).decode("utf-8", errors="ignore")
    except KeyError:
        if name_map is None:
            name_map = {n.lstrip("/").lower(): n for n in z.namelist()}
        alt = name_map.get(path.lstrip("/").lower())
        if alt:
            try:
                return z.read(alt).decode("utf-8", errors="ignore")
            except KeyError:
                return None
        return None


def _parse_attrs(attr_str):
    attrs = {}
    for m in re.finditer(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', attr_str):
        attrs[m.group(1).lower()] = html.unescape(m.group(2) if m.group(2) is not None else m.group(3))
    return attrs


def _epub_opf_info(z):
    opf_path = None
    try:
        cont = z.read("META-INF/container.xml").decode("utf-8", errors="ignore")
        m = re.search(r'full-path\s*=\s*["\']([^"\']+\.opf)["\']', cont)
        if m:
            opf_path = m.group(1)
    except KeyError:
        pass
    if not opf_path:
        cands = [n for n in z.namelist() if n.lower().endswith(".opf")]
        opf_path = cands[0] if cands else None
    if not opf_path:
        raise SystemExit("这个 epub 里找不到 .opf")
    opf = z.read(opf_path).decode("utf-8", errors="ignore")
    base = os.path.dirname(opf_path)

    items = {}
    nav_path = None
    ncx_path = None
    for m in re.finditer(r"<item\b([^>]+)>", opf, re.I):
        a = _parse_attrs(m.group(1))
        iid = a.get("id")
        href = a.get("href")
        if iid and href:
            items[iid] = href
        props = set((a.get("properties") or "").lower().split())
        mtype = (a.get("media-type") or "").lower()
        if "nav" in props and href and not nav_path:
            nav_path = _norm_epub_path(base, href)
        if mtype == "application/x-dtbncx+xml" and href and not ncx_path:
            ncx_path = _norm_epub_path(base, href)

    spine_m = re.search(r"<spine\b([^>]*)>", opf, re.I)
    if spine_m and not ncx_path:
        toc_id = _parse_attrs(spine_m.group(1)).get("toc")
        if toc_id and toc_id in items:
            ncx_path = _norm_epub_path(base, items[toc_id])

    if not ncx_path:
        ncx_cands = [n for n in z.namelist() if n.lower().endswith(".ncx")]
        if ncx_cands:
            ncx_path = ncx_cands[0].replace("\\", "/").lstrip("/")

    spine = re.findall(r'<itemref\b[^>]*idref\s*=\s*["\']([^"\']+)["\']', opf, re.I)
    files = []
    for s in spine:
        h = _norm_epub_path(base, items.get(s, ""))
        if h.lower().endswith((".html", ".xhtml", ".htm")):
            files.append(h)
    return {
        "opf_path": opf_path,
        "base": base,
        "items": items,
        "spine": files,
        "nav_path": nav_path,
        "ncx_path": ncx_path,
    }


def epub_spine(z):
    return _epub_opf_info(z)["spine"]


def _local_tag(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _parse_ncx_toc(xml_text, ncx_path):
    base_dir = os.path.dirname(ncx_path)
    entries = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # 容错：畸形 XML 退回正则抽取扁平 navPoint
        for m in re.finditer(
            r"<navPoint\b[^>]*>.*?<text[^>]*>(.*?)</text>.*?<content\b[^>]*src\s*=\s*[\"']([^\"']+)[\"']",
            xml_text,
            re.S | re.I,
        ):
            title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).split())
            href = _norm_epub_path(base_dir, html.unescape(m.group(2)))
            if title and href:
                entries.append((1, title, href))
        return entries

    nav_map = None
    for el in root.iter():
        if _local_tag(el.tag) == "navmap":
            nav_map = el
            break
    if nav_map is None:
        return entries

    def walk(parent, depth):
        for child in parent:
            if _local_tag(child.tag) != "navpoint":
                continue
            title = ""
            src = ""
            for sub in child:
                st = _local_tag(sub.tag)
                if st == "navlabel" and not title:
                    for t_el in sub.iter():
                        if _local_tag(t_el.tag) == "text":
                            title = " ".join("".join(t_el.itertext()).split())
                            break
                elif st == "content" and not src:
                    src = sub.attrib.get("src", "")
            href = _norm_epub_path(base_dir, src)
            if title and href:
                entries.append((depth, title, href))
            walk(child, depth + 1)

    walk(nav_map, 1)
    return entries


class _NavTocParser(HTMLParser):
    """解析 EPUB3 nav.xhtml 中的 <nav epub:type="toc"> 或含 <ol><li><a href> 的 <nav>。"""

    def __init__(self, base_dir):
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.navs = []
        self._in_nav = False
        self._nav_depth = 0
        self._is_toc_nav = False
        self._cur_entries = []
        self._ol_depth = 0
        self._in_a = False
        self._a_href = ""
        self._a_buf = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "nav":
            if not self._in_nav:
                self._in_nav = True
                self._nav_depth = 1
                self._cur_entries = []
                self._ol_depth = 0
                etype = ""
                for k, v in attr_map.items():
                    if k == "type" or k.endswith(":type"):
                        etype += " " + v.lower()
                role = attr_map.get("role", "").lower()
                nid = attr_map.get("id", "").lower()
                self._is_toc_nav = (
                    "toc" in etype.split()
                    or role == "doc-toc"
                    or nid == "toc"
                )
            else:
                self._nav_depth += 1
            return
        if not self._in_nav:
            return
        if tag == "ol":
            self._ol_depth += 1
        elif tag == "a" and self._ol_depth >= 1:
            href = attr_map.get("href", "")
            if href:
                self._in_a = True
                self._a_href = href
                self._a_buf = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "nav" and self._in_nav:
            self._nav_depth -= 1
            if self._nav_depth <= 0:
                self.navs.append((self._is_toc_nav, self._cur_entries))
                self._in_nav = False
                self._cur_entries = []
                self._ol_depth = 0
                self._in_a = False
            return
        if not self._in_nav:
            return
        if tag == "a" and self._in_a:
            title = " ".join("".join(self._a_buf).split())
            href = _norm_epub_path(self.base_dir, self._a_href)
            if title and href:
                self._cur_entries.append((max(1, self._ol_depth), title, href))
            self._in_a = False
            self._a_href = ""
            self._a_buf = []
        elif tag == "ol" and self._ol_depth > 0:
            self._ol_depth -= 1

    def handle_data(self, data):
        if self._in_a and not self._skip:
            self._a_buf.append(data)


def _parse_nav_xhtml(html_text, nav_path):
    p = _NavTocParser(os.path.dirname(nav_path))
    p.feed(html_text)
    for is_toc, entries in p.navs:
        if is_toc and entries:
            return entries
    for _, entries in p.navs:
        if entries:
            return entries
    return []


def epub_toc(z, opf_info=None):
    """解析 EPUB 的 nav.xhtml (EPUB3) 与 toc.ncx (EPUB2)，返回 [(depth, title, norm_href), ...]。"""
    info = opf_info or _epub_opf_info(z)
    name_map = {n.lstrip("/").lower(): n for n in z.namelist()}

    nav_entries = []
    if info.get("nav_path"):
        nav_txt = _zip_read_text(z, info["nav_path"], name_map)
        if nav_txt:
            nav_entries = _parse_nav_xhtml(nav_txt, info["nav_path"])

    ncx_entries = []
    if info.get("ncx_path"):
        ncx_txt = _zip_read_text(z, info["ncx_path"], name_map)
        if ncx_txt:
            ncx_entries = _parse_ncx_toc(ncx_txt, info["ncx_path"])

    if nav_entries and ncx_entries:
        return nav_entries if len(nav_entries) >= len(ncx_entries) else ncx_entries
    return nav_entries or ncx_entries


# ── 内置非正文 TOC / 单页过滤器（保守，绝不误删正常章节）──

_TOC_MARKER_RE = re.compile(
    r"^(?:toc|contents|table\s+of\s+contents|目次|目录|目錄)$",
    re.I,
)

_BUILTIN_META_TOC_EXACT_RE = re.compile(
    r"^[【\[（(]?\s*(?:"
    r"cover|title\s*page|frontispiece|illustrations?|toc|contents|table\s+of\s+contents|"
    r"colophon|copyright|credits?|afterword|postscript|commentary|interview|special|"
    r"表紙|表纸|封面(?:及彩页|彩页)?|彩页|彩頁|口絵|口绘|扉页|扉頁|书名页|書名頁|"
    r"目次|目录|目錄|奥付|奥附|版权(?:页|信息|声明)?|版權(?:頁|信息|聲明)?|制作信息|製作信息|"
    r"后\s*记|後\s*記|あとがき|译\s*后\s*记|譯\s*後\s*記|编\s*后\s*记|編\s*後\s*記|"
    r"解\s*说|解\s*說|解説|问卷|問卷|问卷调查|問卷調查|アンケート|"
    r"巻末特別企画|卷末特别企划|特别企划|特別企画|質問コーナー|インタビュー|访谈|訪談|采访|采訪"
    r")\s*[】\]）)]?$",
    re.I,
)

_BUILTIN_META_TOC_PARTIAL_RE = re.compile(
    r"(?:"
    r"巻末特別企画|卷末特别企划|特別企画|特别企划|質問コーナー|インタビュー|"
    r"问卷调查|問卷調查|アンケート|制作信息|製作信息|版权信息|版權信息|版权页|版權頁|"
    r"あとがき|奥付|访谈|訪談|"
    r"^(?:后\s*记|後\s*記|译后记|譯後記|编后记|編後記|解\s*说|解\s*說|解説|封面(?:及彩页)?|目次|目录|目錄)(?:[\s　:：·・\-—（(【\[]|$)"
    r")",
    re.I,
)

_VOL_PAT = re.compile(
    r"(?:第[0-9０-９零〇一二三四五六七八九十百千两]+[卷部]|Vol\.?\s*[0-9０-９]+|Volume\s*[0-9０-９]+)",
    re.I,
)

_PREFIX_NUM_VOL_RE = re.compile(
    r"^(.{4,}?)[\s　\-—·:：]*(?:Vol\.?\s*|Volume\s*)?(?:第?[0-9０-９零〇一二三四五六七八九十百千两]+[卷部]?)$",
    re.I,
)

_END_ONLY_RE = re.compile(
    r"^[（(\[【]?\s*(?:终|終|完|fin|the\s+end|end)\s*[）)\]】\.。!！]*$",
    re.I,
)

_COLOPHON_TEXT_RE = re.compile(
    r"版权所有|版權所有|著作权|著作權|发行人|發行人|发行所|發行所|"
    r"印刷[・·、]制本|出版发行|出版發行|ISBN|问卷调查|問卷調查|"
    r"emob\.jp|东京都港区|東京都港區|SB\s*Creative|本文イラスト|"
    r"内文插画|內文插畫|封面.{0,20}插画|封面.{0,20}插畫",
    re.I,
)

_AUTHOR_BIO_START_RE = re.compile(r"^\s*作者[\s　:：]+")
_ILLUSTRATOR_RE = re.compile(r"插画|插畫|原画师|原畫師|绘师|繪師|イラスト")

_TOC_HEAD_RE = re.compile(
    r"^(?:目次|目录|目錄|CONTENTS|Table\s+of\s+Contents)(?:$|[\s　:：·・\-—])",
    re.I,
)

_AFTERWORD_HEAD_RE = re.compile(
    r"^[【\[（(]?\s*(?:"
    r"后\s*记|後\s*記|あとがき|译\s*后\s*记|譯\s*後\s*記|编\s*后\s*记|編\s*後\s*記|"
    r"解\s*说|解\s*說|解説|访谈|訪談|采访|采訪|卷末特别企划|巻末特別企画|特别企划|特別企画"
    r")\s*[】\]）)]?(?:$|[\s　:：·・\-—].{0,40}$)",
    re.I,
)

_AFTERWORD_ADDR_RE = re.compile(
    r"原作|书末|書末|后记|後記|幸会|幸會|好久不见|好久不見|执笔|執筆|解说|解說|解説|文库|文庫"
)


def _is_builtin_meta_toc(title):
    s = (title or "").strip()
    if not s:
        return True
    return bool(_BUILTIN_META_TOC_EXACT_RE.fullmatch(s) or _BUILTIN_META_TOC_PARTIAL_RE.search(s))


def _infer_toc_levels(entries, drop, drop_builtin_meta=True):
    """将 TOC (depth, title, href) 规整为层级 1..3；对扁平 Calibre toc.ncx 自动推断 2 级卷/章结构。"""
    if not entries:
        return []
    depths = {d for d, _, _ in entries}
    if len(depths) > 1:
        min_d = min(depths)
        return [(min(3, max(1, d - min_d + 1)), t, h) for d, t, h in entries]

    def is_meta(title):
        return (title in drop) or (drop_builtin_meta and _is_builtin_meta_toc(title))

    story_idxs = [i for i, (_, t, _) in enumerate(entries) if not is_meta(t)]
    story_count = len(story_idxs)
    vol_idxs = set()

    # 1) 共享 >=4 字前缀且以数字/全角数字/中文数字结尾的重复卷标题
    prefix_groups = {}
    for i in story_idxs:
        t = entries[i][1].strip()
        m = _PREFIX_NUM_VOL_RE.match(t)
        if m:
            pref = m.group(1).strip()
            if len(pref) >= 4:
                prefix_groups.setdefault(pref, []).append(i)
    for pref, idxs in prefix_groups.items():
        if len(idxs) >= 2 and len(idxs) < story_count:
            vol_idxs.update(idxs)

    # 2) 被多个 目次/目录 条目分隔的卷标题（紧接在 目次/目录 前的非元信息标题）
    toc_markers = [i for i, (_, t, _) in enumerate(entries) if _TOC_MARKER_RE.fullmatch(t.strip())]
    if len(toc_markers) >= 2:
        prev_marker = -1
        for mi in toc_markers:
            for j in range(mi - 1, max(prev_marker, mi - 3), -1):
                if j >= 0 and not is_meta(entries[j][1]):
                    vol_idxs.add(j)
                    break
            prev_marker = mi

    # 3) 若尚未检出卷标题，检查是否含 第X卷 / 第X部 / Vol.X 模式
    if not vol_idxs:
        pat_idxs = [i for i in story_idxs if _VOL_PAT.search(entries[i][1])]
        if pat_idxs and len(pat_idxs) < story_count:
            vol_idxs.update(pat_idxs)
    else:
        # 已有卷标题时，也兼容夹杂的显式 第X卷 / Vol.X
        for i in story_idxs:
            if _VOL_PAT.search(entries[i][1]):
                vol_idxs.add(i)

    if vol_idxs and len(vol_idxs) < story_count:
        return [
            (1 if i in vol_idxs else 2, t, h)
            for i, (_, t, h) in enumerate(entries)
        ]

    # 纯扁平单层章节 TOC：统一作为 h2，便于下游 parse_units 与卷映射对齐
    return [(2, t, h) for _, t, h in entries]


def _page_meta_kind(blocks):
    """保守判定单页是否为非正文页，返回 'empty' / 'meta' / None。"""
    texts = [t.strip() for _, t in blocks if t and t.strip()]
    if not texts:
        return "empty"
    has_heading = any(tag in BLOCK for tag, _ in blocks)
    page_text = "\n".join(texts)
    page_len = len(page_text)
    first_block = texts[0]

    # 1) 空页或仅有结束标记/短题名+结束标记（无 h1-h6 时）
    if not has_heading:
        if len(texts) == 1 and _END_ONLY_RE.fullmatch(first_block):
            return "empty"
        if len(texts) <= 2 and _END_ONLY_RE.fullmatch(texts[-1]) and len(first_block) <= 30:
            return "empty"

    # 2) 版权/奥付/问卷页
    head450 = page_text[:450]
    if page_len < 2000 and _COLOPHON_TEXT_RE.search(head450):
        return "meta"

    # 3) 作者/插画简介页
    head250 = page_text[:250]
    if page_len < 1200 and (
        _AUTHOR_BIO_START_RE.match(head250)
        or ("作者" in head250 and _ILLUSTRATOR_RE.search(head250))
    ):
        return "meta"

    # 4) 目录页
    if page_len < 2500 and _TOC_HEAD_RE.match(first_block):
        rest = texts[1:]
        if not rest:
            return "meta"
        short_cnt = sum(1 for x in rest if len(x) <= 55)
        if short_cnt >= len(rest) * 0.7:
            return "meta"

    # 5) 后记/解说/访谈页
    if _AFTERWORD_HEAD_RE.match(first_block):
        return "meta"
    head280 = page_text[:280]
    if ("各位读者" in head280 or "各位讀者" in head280) and _AFTERWORD_ADDR_RE.search(head280):
        return "meta"

    return None


def _compile_regex_list(patterns):
    out = []
    for p in (patterns or []):
        p = (p or "").strip()
        if not p:
            continue
        try:
            out.append(re.compile(p))
        except re.error as e:
            sys.stderr.write("忽略非法正则 %r：%s\n" % (p, e))
    return out


def _resolve_offsets(out, heads):
    if not heads:
        return
    raw_joined = "\n".join(out)
    lead = len(raw_joined) - len(raw_joined.lstrip())
    raw_pos = []
    p = 0
    for s in out:
        raw_pos.append(p)
        p += len(s) + 1
    for h in heads:
        idx = h.pop("_idx")
        # out[idx] 形如 "\n# title" / "\n## title" / "\n### title"
        h["offset"] = raw_pos[idx] + 1 - lead


def _emit_heading(out, heads, cur, level, title):
    if level == 1:
        cur["h1"] = title
        cur["h2"] = ""
        heads.append({"level": 1, "title": title, "_idx": len(out)})
        out.append("\n# " + title)
    elif level == 2:
        cur["h2"] = title
        heads.append({"level": 2, "title": title, "_idx": len(out), "h1": cur["h1"]})
        out.append("\n## " + title)
    else:
        heads.append({"level": 3, "title": title, "_idx": len(out),
                      "h2": cur["h2"], "h1": cur["h1"]})
        out.append("\n### " + title)


def extract_epub(path, drop, cfg=None):
    cfg = cfg or {}
    drop_builtin_meta = bool(cfg.get("drop_builtin_meta", True))
    file_drop_res = _compile_regex_list(cfg.get("drop_file_patterns"))
    text_drop_res = _compile_regex_list(cfg.get("drop_text_patterns"))

    with zipfile.ZipFile(path) as z:
        opf_info = _epub_opf_info(z)
        files = opf_info["spine"]
        name_map = {n.lstrip("/").lower(): n for n in z.namelist()}

        lxml_ok = False
        try:
            import lxml  # noqa: F401
            lxml_ok = True
        except ImportError:
            pass

        parsed_pages = []
        html_head_count = 0
        for f in files:
            hs = _zip_read_text(z, f, name_map)
            if hs is None:
                continue
            blocks = blocks_from_html(hs, lxml_ok)
            parsed_pages.append((f, blocks))
            for tag, _ in blocks:
                if tag in BLOCK:
                    html_head_count += 1

        raw_toc = epub_toc(z, opf_info)
        toc_entries = _infer_toc_levels(raw_toc, drop, drop_builtin_meta=drop_builtin_meta)

        # 建立 spine 路径映射（兼容大小写差异）
        spine_exact = set(f for f, _ in parsed_pages)
        spine_lower = {f.lower(): f for f, _ in parsed_pages}
        toc_by_file = {}
        toc_story_count = 0
        for lvl, title, href in toc_entries:
            target = href if href in spine_exact else spine_lower.get(href.lower())
            if not target:
                continue
            toc_by_file.setdefault(target, []).append((lvl, title))
            if title not in drop and not (drop_builtin_meta and _is_builtin_meta_toc(title)):
                toc_story_count += 1

        use_toc = (
            len(toc_entries) >= 2
            and bool(toc_by_file)
            and (html_head_count == 0 or html_head_count < max(2, toc_story_count // 4))
        )

        out, heads = [], []
        cur = {"h1": "", "h2": ""}
        skip = False

        for f, blocks in parsed_pages:
            page_text = "\n".join(t for _, t in blocks if t)
            page_head500 = page_text[:500]
            file_dropped = any(rx.search(f) for rx in file_drop_res)
            text_dropped = bool(text_drop_res and page_head500 and any(rx.search(page_head500) for rx in text_drop_res))

            if use_toc:
                t_entries = toc_by_file.get(f) or []
                pending_heads = []
                if t_entries:
                    for lvl, title in t_entries:
                        if title in drop or (drop_builtin_meta and _is_builtin_meta_toc(title)):
                            skip = True
                            continue
                        skip = False
                        pending_heads.append((lvl, title))

                if file_dropped or text_dropped:
                    continue

                if not t_entries and skip:
                    continue

                meta_kind = _page_meta_kind(blocks) if drop_builtin_meta else None

                if skip:
                    # 本页最后命中的 TOC 条目被丢弃（例如同页含 卷标题 + 目次），
                    # 仅保留非丢弃的 h1 卷标题，跳过本页正文与后续无标题页。
                    for lvl, title in pending_heads:
                        if lvl == 1:
                            _emit_heading(out, heads, cur, lvl, title)
                    continue

                if meta_kind == "meta":
                    # 版权/作者简介/目录/后记页：若同页带 h1 卷标题仍保留 h1，丢弃正文
                    for lvl, title in pending_heads:
                        if lvl == 1:
                            _emit_heading(out, heads, cur, lvl, title)
                    continue

                emitted_norm = set()
                for lvl, title in pending_heads:
                    _emit_heading(out, heads, cur, lvl, title)
                    emitted_norm.add("".join(title.split()))

                if meta_kind == "empty":
                    continue

                first_body = True
                for tag, t in blocks:
                    ts = t.strip()
                    if not ts:
                        continue
                    if first_body and "".join(ts.split()) in emitted_norm:
                        first_body = False
                        continue
                    first_body = False
                    if tag in BLOCK and (ts in drop or (drop_builtin_meta and _is_builtin_meta_toc(ts))):
                        continue
                    out.append(ts)
            else:
                if file_dropped or text_dropped:
                    continue

                meta_kind = _page_meta_kind(blocks) if drop_builtin_meta else None
                if meta_kind == "empty":
                    continue
                if meta_kind == "meta":
                    # 若本页显式以被丢弃的标题开头（如 <h2>后记</h2>），同步置 skip=True 以滤掉后记续页
                    for tag, t in blocks:
                        if tag in BLOCK and (t in drop or _is_builtin_meta_toc(t)):
                            skip = True
                            break
                    continue

                for tag, t in blocks:
                    if tag in BLOCK:
                        if t in drop or (drop_builtin_meta and _is_builtin_meta_toc(t)):
                            skip = True
                            continue
                        skip = False
                        lvl = 1 if tag == "h1" else (2 if tag == "h2" else 3)
                        _emit_heading(out, heads, cur, lvl, t)
                    else:
                        if skip:
                            continue
                        out.append(t)

        _resolve_offsets(out, heads)
        return out, heads, len(files)


def extract_docx(path, drop):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    paras = re.findall(r"<w:p\b.*?</w:p>|<w:p\b[^>]*/>", xml, re.S)
    out, heads = [], []
    cur = {"h1": "", "h2": ""}
    skip = False

    for p in paras:
        t = "".join(html.unescape(x) for x in re.findall(r"<w:t\b[^>]*>(.*?)</w:t>", p, re.S))
        t = " ".join(t.split())
        if not t:
            continue
        st = re.search(r'w:val="([^"]*[Hh]eading[^"]*|[^"]*标题[^"]*)"', p)
        lvl = 0
        if st:
            d = re.search(r"(\d)", st.group(1))
            lvl = int(d.group(1)) if d else 1
        if lvl == 1:
            if t in drop:
                skip = True
                continue
            skip = False
            cur = {"h1": t, "h2": ""}
            heads.append({"level": 1, "title": t, "_idx": len(out)})
            out.append("\n# " + t)
        elif lvl == 2:
            if t in drop:
                skip = True
                continue
            skip = False
            cur["h2"] = t
            heads.append({"level": 2, "title": t, "_idx": len(out), "h1": cur["h1"]})
            out.append("\n## " + t)
        elif lvl >= 3:
            if t in drop:
                skip = True
                continue
            skip = False
            heads.append({"level": 3, "title": t, "_idx": len(out),
                          "h2": cur["h2"], "h1": cur["h1"]})
            out.append("\n### " + t)
        else:
            if skip:
                continue
            out.append(t)
    _resolve_offsets(out, heads)
    return out, heads, len(paras)


# ── 对白格式化（SRT / ASS / Galgame 剧本）──

_ALREADY_QUOTED_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"))


def _is_already_quoted(s):
    if len(s) < 2:
        return False
    for o, c in _ALREADY_QUOTED_PAIRS:
        if s[0] == o and s[-1] == c:
            return True
    return False


def _format_dialogue_line(speaker, text):
    t = (text or "").strip()
    if not t:
        return ""
    quoted = t if _is_already_quoted(t) else ("「%s」" % t)
    sp = (speaker or "").strip()
    if sp:
        return "%s：%s" % (sp, quoted)
    return quoted


_SRT_TIME_RE = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}"
)
_SRT_SPEAKER_RE = re.compile(
    r"^(?:[-—–]\s*)?([^\s:：。！？，,]{1,16})[：:]\s*(.+)$"
)


def extract_srt(path, drop):
    """抽取 .srt 字幕：剥离序号、时间戳与样式标签，输出规整台词行供 stylefit 直接复用。"""
    text = textio.read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    out = []
    cues = 0
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.isdigit():
            continue
        if _SRT_TIME_RE.match(s):
            cues += 1
            continue
        # 去 HTML 标签与 ASS/SRT 花括号样式标签
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\{[^}]*\}", "", s)
        s = " ".join(html.unescape(s).split())
        if not s or s in drop:
            continue
        m = _SRT_SPEAKER_RE.match(s)
        if m and not m.group(1).isdigit() and m.group(1).lower() not in ("http", "https"):
            line = _format_dialogue_line(m.group(1), m.group(2))
        else:
            s = re.sub(r"^[-—–]\s+", "", s).strip()
            line = _format_dialogue_line("", s)
        if line:
            out.append(line)
    return out, [], cues or 1


_ASS_GENERIC_NAMES = {"", "default", "comment", "nt", "none", "n/a", "unknown"}


def extract_ass(path, drop):
    """抽取 .ass/.ssa 字幕：解析 [Events] Dialogue 行，剥离 {...} 覆盖标签与 \\N 换行。"""
    text = textio.read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    out = []
    in_events = False
    cols = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
    name_idx = 4
    text_idx = 9
    dialogs = 0

    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            in_events = (s.lower() == "[events]")
            continue
        if not in_events:
            continue
        low = s.lower()
        if low.startswith("format:"):
            raw_cols = [c.strip().lower() for c in s.split(":", 1)[1].split(",")]
            if raw_cols:
                cols = raw_cols
                name_idx = cols.index("name") if "name" in cols else (cols.index("actor") if "actor" in cols else -1)
                text_idx = cols.index("text") if "text" in cols else (len(cols) - 1)
            continue
        if not low.startswith("dialogue:"):
            continue
        payload = s.split(":", 1)[1].lstrip()
        parts = payload.split(",", len(cols) - 1)
        if text_idx < 0 or text_idx >= len(parts):
            continue
        raw_text = parts[text_idx]
        raw_name = parts[name_idx].strip() if (0 <= name_idx < len(parts)) else ""
        # 剥离 ASS 覆盖标签 {...}，\N / \n / \h 转空格
        cleaned = re.sub(r"\{[^}]*\}", "", raw_text)
        cleaned = re.sub(r"\\[Nnh]", " ", cleaned)
        cleaned = " ".join(cleaned.split())
        if not cleaned or cleaned in drop:
            continue
        dialogs += 1
        sp = raw_name if raw_name.lower() not in _ASS_GENERIC_NAMES else ""
        line = _format_dialogue_line(sp, cleaned)
        if line:
            out.append(line)
    return out, [], dialogs or 1


TXT_HEAD = re.compile(
    r"^\s*(?:第[0-9０-９零〇一二三四五六七八九十百千两]+[卷部章话回节]"
    r"|序(?:章|言|曲)|楔子|引子|尾声|终章|后记|番外(?:\s*[0-9一二三四五六七八九十]+)?)"
    r"(?:$|[\s　:：·・\-—]+(?![课])[^\n]{0,50})$"
)
TXT_H1 = re.compile(r"^\s*(第[0-9０-９零〇一二三四五六七八九十百千两]+[卷部])(?:$|[\s　:：\-—]+[^\n]{0,60})$")
GAL_LINE_RE = re.compile(r"^【([^】\n]{1,16})】\s*(.+)$")


def extract_txt(path, drop):
    text = textio.read_text(path)
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # 检测是否以 Galgame 剧本格式（【角色名】台词）为主，保持普通 TXT 小说 100% 兼容
    gal_cnt = sum(1 for s in raw_lines if GAL_LINE_RE.match(s))
    non_empty = len(raw_lines)
    is_galgame = (
        (gal_cnt >= 3 and gal_cnt / max(1, non_empty) >= 0.30)
        or (gal_cnt >= 2 and gal_cnt / max(1, non_empty) >= 0.50)
    )

    out, heads = [], []
    cur = {"h1": "", "h2": ""}
    skip = False

    for s in raw_lines:
        if s in drop:
            skip = True
            continue
        m = TXT_H1.match(s)
        if m:
            skip = False
            cur = {"h1": s, "h2": ""}
            heads.append({"level": 1, "title": s, "_idx": len(out)})
            out.append("\n# " + s)
            continue
        m = TXT_HEAD.match(s)
        if m and len(s) <= 40:
            skip = False
            cur["h2"] = s
            heads.append({"level": 2, "title": s, "_idx": len(out), "h1": cur["h1"]})
            out.append("\n## " + s)
            continue
        if skip:
            continue
        if is_galgame:
            gm = GAL_LINE_RE.match(s)
            if gm:
                line = _format_dialogue_line(gm.group(1), gm.group(2))
                if line:
                    out.append(line)
                continue
        out.append(s)
    _resolve_offsets(out, heads)
    return out, heads, 1


def _clean_extracted(text, heads, cfg):
    """按配置可选清洗正文前的目录残余、脚注定义/引用与指定孤立行/正则噪声行，并同步修正标题偏移。"""
    strip_before = bool(cfg.get("strip_before_first_heading"))
    strip_footnotes = bool(cfg.get("strip_footnotes"))
    drop_lines = set(x.strip() for x in (cfg.get("drop_lines") or []) if x and x.strip())
    drop_line_res = _compile_regex_list(cfg.get("drop_line_patterns"))
    if not (strip_before or strip_footnotes or drop_lines or drop_line_res):
        return text, heads

    lines = text.splitlines()
    if strip_before:
        for i, ln in enumerate(lines):
            if re.match(r"^#{1,3}\s+\S", ln):
                lines = lines[i:]
                break

    fn_def_re = re.compile(r"^\[\d+\]")
    fn_ref_re = re.compile(r"\[\d+\]")
    cleaned = []
    for ln in lines:
        s = ln.strip()
        if strip_footnotes and fn_def_re.match(s):
            continue
        if drop_lines and s in drop_lines:
            continue
        if drop_line_res and s and any(rx.search(s) for rx in drop_line_res):
            continue
        if strip_footnotes:
            ln = fn_ref_re.sub("", ln)
        cleaned.append(ln)

    new_text = "\n".join(cleaned).strip() + "\n"
    # 顺序扫描行，精确回填每个标题在清洗后文本中的字符偏移
    pos = 0
    line_offsets = {}
    new_lines = new_text.split("\n")
    for idx, ln in enumerate(new_lines):
        line_offsets[idx] = pos
        pos += len(ln) + 1
    scan_idx = 0
    new_heads = []
    for h in heads:
        title = fn_ref_re.sub("", h["title"]).strip() if strip_footnotes else h["title"]
        marker = "#" * h["level"] + " " + title
        found = None
        for i in range(scan_idx, len(new_lines)):
            if new_lines[i] == marker:
                found = i
                break
        if found is not None:
            nh = dict(h)
            nh["title"] = title
            nh["offset"] = line_offsets[found]
            new_heads.append(nh)
            scan_idx = found + 1
    return new_text, new_heads


def main():
    textio.ensure_utf8_stdio()

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--drop", default=None, help="要整段丢弃的标题，逗号分隔")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-builtin-meta", action="store_true",
                    help="关闭 EPUB 内置非正文页（版权/目次/后记/访谈/作者简介）自动过滤")
    ap.add_argument("--drop-line-pattern", action="append", default=None,
                    help="追加按正则丢弃的噪声行（可重复指定）")
    a = ap.parse_args()

    cfg = project.load(a.config, need_source=not a.source)
    if a.no_builtin_meta:
        cfg["drop_builtin_meta"] = False
    if a.drop_line_pattern:
        cfg["drop_line_patterns"] = list(cfg.get("drop_line_patterns") or []) + list(a.drop_line_pattern)

    src = a.source or cfg["source"]
    drop = set(x.strip() for x in (a.drop or ",".join(cfg.get("drop_headings") or [])).split(",") if x.strip())
    outdir = a.out or cfg["paths"]["raw"]
    os.makedirs(outdir, exist_ok=True)

    ext = os.path.splitext(src)[1].lower()
    if ext == ".epub":
        out, heads, n = extract_epub(src, drop, cfg=cfg)
    elif ext == ".docx":
        out, heads, n = extract_docx(src, drop)
    elif ext == ".srt":
        out, heads, n = extract_srt(src, drop)
    elif ext in (".ass", ".ssa"):
        out, heads, n = extract_ass(src, drop)
    else:
        out, heads, n = extract_txt(src, drop)

    text = "\n".join(out).strip() + "\n"
    text, heads = _clean_extracted(text, heads, cfg)
    textio.write_text(os.path.join(outdir, "_all.txt"), text)
    textio.write_json(os.path.join(outdir, "sections.json"), heads)

    c = Counter(h["level"] for h in heads)
    print("来源：%s" % src)
    print("单元：%s" % n)
    print("字数：%d ｜ 行数：%d" % (len(text), text.count("\n") + 1))
    print("标题：h1 %d ｜ h2 %d ｜ h3 %d" % (c.get(1, 0), c.get(2, 0), c.get(3, 0)))
    print("→ %s" % os.path.join(outdir, "_all.txt"))

    sv = corpus.detect_script_variant(text)
    if sv.get("variant") == "traditional":
        print(
            "警告：检测到繁体中文语料（繁体占比 %.1f%%，繁 %d / 简 %d）。"
            "默认 config/stylefit/*.json 词典为简体中文，建议先转为简体或使用繁体词典目录（stylefit_dir）。"
            % (sv.get("trad_ratio", 0.0) * 100.0, sv.get("trad", 0), sv.get("simp", 0))
        )

    print("检查第一屏：")
    print("\n".join(text.split("\n")[:12]))


if __name__ == "__main__":
    main()
