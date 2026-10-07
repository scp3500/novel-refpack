# -*- coding: utf-8 -*-
"""测试公共工具。只依赖标准库。"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib import project, textio  # noqa: E402

HEAD = re.compile(r"^(#{1,6})\s+(.*)$")


def cn_num(n):
    digits = "零一二三四五六七八九"
    if n < 0:
        raise ValueError(n)
    if n < 10:
        return digits[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + digits[n - 10]
    if n < 100:
        t, o = divmod(n, 10)
        return digits[t] + "十" + (digits[o] if o else "")
    raise ValueError(n)


def load_script(fname):
    """按路径加载 scripts/<fname>，可反复调用。"""
    path = os.path.join(ROOT, "scripts", fname)
    key = "refpack_script_" + fname.replace(".", "_")
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def sections_from_text(text):
    """按 00_extract 的规则给带 # 标记的全文打 sections.json。"""
    heads, pos, cur_h1, cur_h2 = [], 0, "", ""
    for ln in text.split("\n"):
        m = HEAD.match(ln)
        if m:
            lvl, title = len(m.group(1)), m.group(2).strip()
            item = {"level": lvl, "title": title, "offset": pos}
            if lvl == 1:
                cur_h1, cur_h2 = title, ""
            elif lvl == 2:
                cur_h2 = title
                item["h1"] = cur_h1
            else:
                item["h1"], item["h2"] = cur_h1, cur_h2
            heads.append(item)
        pos += len(ln) + 1
    return heads


def write_extracted(raw_dir, text):
    text = text.strip() + "\n"
    os.makedirs(raw_dir, exist_ok=True)
    textio.write_text(os.path.join(raw_dir, "_all.txt"), text)
    textio.write_json(os.path.join(raw_dir, "sections.json"), sections_from_text(text))
    return text


def write_config(path, **over):
    """写一份可被 project.load 读的配置。paths 可用绝对路径。"""
    work = over.pop("work", None)
    cfg = {
        "name": "测试书",
        "source": "",
        "chunk_chars": 60000,
        "quote_open": ["“", "「", "『"],
        "quote_close": ["”", "」", "』"],
        "person": "third",
        "protagonist": "林舟",
        "vol_unit_word": "章",
        "names": ["林舟", "苏晚", "陈衡"],
        "drop_headings": ["简介", "制作信息"],
        "hard_settings": ["北境没有系统面板", "林舟不会死而复生"],
        "if_points": ["苏晚是否跟上北上的队伍"],
        "llm": {
            "backend": "command",
            "command": "",
            "concurrency": 4,
            "timeout": 30,
            "retries": 1,
        },
        "paths": {},
    }
    for k, v in over.items():
        if k == "llm" and isinstance(v, dict):
            cfg["llm"].update(v)
        elif k == "paths" and isinstance(v, dict):
            cfg["paths"].update(v)
        else:
            cfg[k] = v
    if work:
        cfg["paths"].update({
            "work": work,
            "raw": os.path.join(work, "raw"),
            "chunks": os.path.join(work, "chunks"),
            "notes": os.path.join(work, "notes"),
            "volumes": os.path.join(work, "volumes"),
            "cache": os.path.join(work, "cache"),
            "out": os.path.join(work, "out"),
            "logs": os.path.join(work, "logs"),
        })
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    return cfg


class TempProject:
    """临时目录 + 配置文件。默认把 work/ 放在临时目录里。"""

    def __init__(self, **over):
        self.over = over
        self.td = None
        self.cfg_path = None
        self.work = None

    def __enter__(self):
        self.td = tempfile.mkdtemp(prefix="refpack_test_")
        self.work = os.path.join(self.td, "work")
        os.makedirs(self.work, exist_ok=True)
        self.cfg_path = os.path.join(self.td, "project.json")
        write_config(self.cfg_path, work=self.work, **self.over)
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def load(self):
        return project.load(self.cfg_path)

    def raw_dir(self):
        return os.path.join(self.work, "raw")


class EnvRestore(unittest.TestCase):
    """改环境变量的用例跑完要还原。"""

    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        for k in list(os.environ):
            if k not in self._env:
                del os.environ[k]
        os.environ.update(self._env)
