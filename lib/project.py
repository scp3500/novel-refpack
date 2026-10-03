# -*- coding: utf-8 -*-
"""项目配置：读 config/project.json（模板见 config/project.example.json），
环境变量可覆盖模型相关字段。

所有脚本都用 `lib.project.load()` 拿配置，路径一律相对仓库根解析。
"""
import os
import sys

from . import textio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "project.json")
EXAMPLE = os.path.join(ROOT, "config", "project.example.json")

DEFAULTS = {
    "name": "mybook",
    "source": "",
    "chunk_chars": 60000,
    "quote_open": ["“", "「", "『"],
    "quote_close": ["”", "」", "』"],
    "person": "third",              # third / first，只写进提示词，供模型参考
    "names": [],
    "drop_headings": ["简介", "制作信息", "封面及彩页"],
    "protagonist": "",
    "vol_unit_word": "卷",          # 二层归纳的单位叫法：卷 / 章 / 篇 / ARC
    "llm": {},
    # 所有跑出来的东西都在 work/ 下，工具目录保持干净
    "paths": {
        "work": "work",
        "raw": "work/raw",
        "chunks": "work/chunks",
        "notes": "work/notes",
        "volumes": "work/volumes",
        "cache": "work/cache",
        "out": "work/out",
        "logs": "work/logs",
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None, need_source=False):
    p = path or CONFIG
    if not os.path.isfile(p):
        if os.path.isfile(EXAMPLE):
            sys.stderr.write(
                "没找到 %s\n先复制一份：cp config/project.example.json config/project.json\n" % p)
        sys.exit(2)
    cfg = _merge(DEFAULTS, textio.read_json(p, {}) or {})
    cfg["_path"] = p
    cfg["_root"] = ROOT

    # 环境变量覆盖
    llm = dict(cfg.get("llm") or {})
    for env, key in (("REFPACK_MODEL", "model"),
                     ("REFPACK_BASE_URL", "base_url"),
                     ("REFPACK_BACKEND", "backend"),
                     ("REFPACK_CONCURRENCY", "concurrency")):
        if os.environ.get(env):
            v = os.environ[env]
            llm[key] = int(v) if key == "concurrency" else v
    cfg["llm"] = llm

    if need_source and not cfg.get("source"):
        sys.stderr.write("config 里没填 source（书的路径）\n")
        sys.exit(2)

    # 引号体系
    from . import corpus
    corpus.set_quotes(cfg.get("quote_open"), cfg.get("quote_close"))

    for k, v in (cfg.get("paths") or {}).items():
        cfg["paths"][k] = os.path.join(ROOT, v)
    return cfg


def artifact(cfg, name):
    """work/ 下的单个文件，如 manifest.json / attrib.json / all_notes.md。"""
    return os.path.join(cfg["paths"]["work"], name)


def prompt(cfg, stem, **kw):
    """读 config/prompts/<stem>.txt，做 {key} 替换。"""
    path = os.path.join(ROOT, "config", "prompts", stem + ".txt")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    t = textio.read_text(path)
    for k, v in kw.items():
        t = t.replace("{" + k + "}", str(v))
    return t
