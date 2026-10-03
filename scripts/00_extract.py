#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 0 · 抽文本：epub / docx / txt → 带结构标记的全文。

  python scripts/00_extract.py                       # 用 config 里的 source
  python scripts/00_extract.py --source book.epub
  python scripts/00_extract.py --drop "简介,制作信息,封面及彩页"

产出：
  raw/_all.txt       全文，`# h1 / ## h2 / ### h3` 标记 + 段落行
  raw/sections.json  各级标题清单（含字符偏移，供分片与卷映射定位）

为什么要保留层级：分片要按卷/章边界切，索引要按版块定位，丢了层级后面全靠猜。
"""
import os
import re
import sys
import json
import html
import zipfile
import argparse
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import project, textio      # noqa: E402

BLOCK = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class BlockParser(HTMLParser):
    """把 HTML 拆成 (tag, text) 的块序列。h1-h6 与 p 作为块，div 透明。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._cur = None
        self._buf = []

    def _flush(self, tag=None):
        t = " ".join("".join(self._buf).split())
        if t and (tag or self._cur):
            self.blocks.append((tag or self._cur, t))
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK:
            self._flush()
            self._cur = tag
        elif tag == "p":
            self._flush()
            self._cur = "p"
        elif tag in ("br",):
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag in BLOCK or tag == "p":
            if self._cur == tag or (tag in BLOCK and self._cur in BLOCK):
                self._flush(tag)
                self._cur = None
        elif tag == "div" and self._cur is None:
            self._flush("p")

    def handle_data(self, data):
        self._buf.append(data)


def blocks_from_html(hs, use_lxml=False):
    if use_lxml:
        try:
            from lxml import html as LH
            doc = LH.fromstring(hs)
            out = []
            for el in doc.body.iter():
                if el.tag in BLOCK or el.tag == "p":
                    t = " ".join(" ".join(el.itertext()).split())
                    if t:
                        out.append((el.tag, t))
            if out:
                return out
        except Exception:
            pass
    p = BlockParser()
    p.feed(hs)
    p._flush()
    return p.blocks


def epub_spine(z):
    opf_path = None
    try:
        cont = z.read("META-INF/container.xml").decode("utf-8", errors="ignore")
        m = re.search(r'full-path="([^"]+\.opf)"', cont)
        if m:
            opf_path = m.group(1)
    except KeyError:
        pass
    if not opf_path:
        cands = [n for n in z.namelist() if n.endswith(".opf")]
        opf_path = cands[0] if cands else None
    if not opf_path:
        raise SystemExit("这个 epub 里找不到 .opf")
    opf = z.read(opf_path).decode("utf-8", errors="ignore")
    base = os.path.dirname(opf_path)
    items = {}
    for m in re.finditer(r"<item\b([^>]+)>", opf):
        a = m.group(1)
        i = re.search(r'id="([^"]+)"', a)
        h = re.search(r'href="([^"]+)"', a)
        if i and h:
            items[i.group(1)] = h.group(1)
    spine = re.findall(r'<itemref[^>]*idref="([^"]+)"', opf)
    files = []
    for s in spine:
        h = items.get(s, "")
        if h.endswith((".html", ".xhtml", ".htm")):
            files.append(os.path.normpath(os.path.join(base, h)).replace("\\", "/"))
    return files


def extract_epub(path, drop):
    z = zipfile.ZipFile(path)
    files = epub_spine(z)
    lxml_ok = False
    try:
        import lxml  # noqa: F401
        lxml_ok = True
    except ImportError:
        pass

    out, heads, pos = [], [], 0
    cur = {"h1": "", "h2": ""}
    skip = False

    def emit(s):
        nonlocal pos
        out.append(s)
        pos += len(s) + 1

    for f in files:
        try:
            hs = z.read(f).decode("utf-8", errors="ignore")
        except KeyError:
            continue
        for tag, t in blocks_from_html(hs, lxml_ok):
            if tag == "h1":
                skip = False
                cur = {"h1": t, "h2": ""}
                heads.append({"level": 1, "title": t, "offset": pos})
                emit("\n# " + t)
            elif tag == "h2":
                skip = False
                cur["h2"] = t
                heads.append({"level": 2, "title": t, "offset": pos, "h1": cur["h1"]})
                emit("\n## " + t)
            elif tag in ("h3", "h4", "h5", "h6"):
                if t in drop:
                    skip = True
                    continue
                skip = False
                heads.append({"level": 3, "title": t, "offset": pos,
                              "h2": cur["h2"], "h1": cur["h1"]})
                emit("\n### " + t)
            else:
                if skip:
                    continue
                emit(t)
    return out, heads, len(files)


def extract_docx(path, drop):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    paras = re.findall(r"<w:p\b.*?</w:p>|<w:p\b[^>]*/>", xml, re.S)
    out, heads, pos = [], [], 0
    cur = {"h1": "", "h2": ""}
    skip = False

    def emit(s):
        nonlocal pos
        out.append(s)
        pos += len(s) + 1

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
            cur = {"h1": t, "h2": ""}
            heads.append({"level": 1, "title": t, "offset": pos})
            emit("\n# " + t)
        elif lvl == 2:
            cur["h2"] = t
            heads.append({"level": 2, "title": t, "offset": pos, "h1": cur["h1"]})
            emit("\n## " + t)
        elif lvl >= 3:
            heads.append({"level": 3, "title": t, "offset": pos,
                          "h2": cur["h2"], "h1": cur["h1"]})
            emit("\n### " + t)
        else:
            emit(t)
    return out, heads, len(paras)


TXT_HEAD = re.compile(r"^\s*(第[0-9零一二三四五六七八九十百千两]+[卷部章话回节])[\s　]*([^\n]{0,50})$")
TXT_H1 = re.compile(r"^\s*(第[0-9零一二三四五六七八九十百千两]+[卷部])[\s　]*([^\n]{0,60})$")


def extract_txt(path, drop):
    text = textio.read_text(path)
    out, heads, pos = [], [], 0
    cur = {"h1": "", "h2": ""}

    def emit(s):
        nonlocal pos
        out.append(s)
        pos += len(s) + 1

    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        m = TXT_H1.match(s)
        if m:
            cur = {"h1": s, "h2": ""}
            heads.append({"level": 1, "title": s, "offset": pos})
            emit("\n# " + s)
            continue
        m = TXT_HEAD.match(s)
        if m and len(s) <= 40:
            cur["h2"] = s
            heads.append({"level": 2, "title": s, "offset": pos, "h1": cur["h1"]})
            emit("\n## " + s)
            continue
        emit(s)
    return out, heads, 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--drop", default=None, help="要整段丢弃的标题，逗号分隔")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    cfg = project.load(a.config, need_source=not a.source)
    src = a.source or cfg["source"]
    drop = set(x.strip() for x in (a.drop or ",".join(cfg.get("drop_headings") or [])).split(",") if x.strip())
    outdir = a.out or cfg["paths"]["raw"]
    os.makedirs(outdir, exist_ok=True)

    ext = os.path.splitext(src)[1].lower()
    if ext == ".epub":
        out, heads, n = extract_epub(src, drop)
    elif ext == ".docx":
        out, heads, n = extract_docx(src, drop)
    else:
        out, heads, n = extract_txt(src, drop)

    text = "\n".join(out).strip() + "\n"
    textio.write_text(os.path.join(outdir, "_all.txt"), text)
    textio.write_json(os.path.join(outdir, "sections.json"), heads)

    from collections import Counter
    c = Counter(h["level"] for h in heads)
    print("来源：%s" % src)
    print("单元：%s" % n)
    print("字数：%d ｜ 行数：%d" % (len(text), text.count("\n") + 1))
    print("标题：h1 %d ｜ h2 %d ｜ h3 %d" % (c.get(1, 0), c.get(2, 0), c.get(3, 0)))
    print("→ %s" % os.path.join(outdir, "_all.txt"))
    print("检查第一屏：")
    print("\n".join(text.split("\n")[:12]))


if __name__ == "__main__":
    main()
