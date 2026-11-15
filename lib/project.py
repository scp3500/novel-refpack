# -*- coding: utf-8 -*-
"""项目配置：读 config/project.json（模板见 config/project.example.json），
环境变量可覆盖模型相关字段。

所有脚本都用 `lib.project.load()` 拿配置，路径一律相对仓库根解析。
"""
import os
import re
import sys
import glob

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
    "aliases": {},                  # {"主名": ["别名1", "昵称2"]}，归属统计时并入主名
    "bans_file": "",                # 可选，自定义禁区 markdown（相对仓库根或绝对路径）
    "drop_headings": ["简介", "制作信息", "封面及彩页"],
    "protagonist": "",
    "vol_unit_word": "卷",          # 二层归纳的单位叫法：卷 / 章 / 篇 / ARC
    "style_only": False,            # True 时仅蒸馏通用文风，剥离原书剧情与角色绑定
    "anonymize": False,             # True 时将角色名/设定框脱敏为中性代称（甲/乙/丙）
    "budget": {
        "preset": "standard",       # compact(60KB) / standard(150KB) / rich(300KB) / full(不裁剪)
        "target_kb": None,          # 显式指定总体积 KB（覆盖 preset）
        "max_tokens": None,         # 显式指定估算总 Token 上限（覆盖 preset）
        "example_ratio": 0.70,      # 例子集在合并包/总预算中的占比（默认 70% 例子 : 30% 摘要）
    },
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
    p = path or os.environ.get("REFPACK_CONFIG") or CONFIG
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
        cfg["paths"][k] = v if os.path.isabs(v) else os.path.join(ROOT, v)
    return cfg


def resolve_bans_file(cfg):
    """定位禁区说明文件：优先 project.json 的 bans_file，其次 config/bans.md。"""
    custom = (cfg.get("bans_file") or "").strip()
    if custom:
        p = custom if os.path.isabs(custom) else os.path.join(ROOT, custom)
        if os.path.isfile(p):
            return p
    default = os.path.join(ROOT, "config", "bans.md")
    return default if os.path.isfile(default) else None


def artifact(cfg, name):
    """work/ 下的单个文件，如 manifest.json / attrib.json / all_notes.md。"""
    return os.path.join(cfg["paths"]["work"], name)


def vol_notes(cfg, with_missing=False):
    """卷纪要 notes/vol/vol_NN.md，按 volume_map.json 的卷序返回 [(卷条目, 路径)]。

    以卷映射为准：重建卷映射后残留的旧 vol_NN.md 不会混进来，
    最后一项就是真正的最后一卷。with_missing=True 时缺纪要的卷也列出（路径不存在）。
    没有 volume_map.json 时退回按文件名里的数字排序。
    """
    vdir = os.path.join(cfg["paths"]["notes"], "vol")
    vmap = textio.read_json(artifact(cfg, "volume_map.json"), None)
    if vmap:
        out = [(v, os.path.join(vdir, "vol_%02d.md" % v["i"])) for v in vmap]
        return out if with_missing else [x for x in out if os.path.isfile(x[1])]
    files = sorted(glob.glob(os.path.join(vdir, "vol_*.md")), key=textio.natural_key)
    return [(None, f) for f in files]


def load_chat_config(path=None):
    p = path or os.environ.get("CHAT_CONFIG")
    if not p:
        cand = os.path.join(ROOT, "config", "chat.json")
        p = cand if os.path.isfile(cand) else os.path.join(ROOT, "config", "chat.example.json")
    if not os.path.isfile(p):
        sys.stderr.write("未找到配置文件：%s\n" % p)
        sys.exit(2)
    cfg = textio.read_json(p, {}) or {}
    cfg["_path"] = p
    return cfg


def chat_work_dir(cfg=None):
    w = (cfg or {}).get("work_dir") or "work"
    return w if os.path.isabs(w) else os.path.join(ROOT, w)


def prompt(cfg, stem, **kw):
    """读 config/prompts/<stem>.txt，做单遍 {key} 替换（防书名或标题含占位符导致二次展开）。"""
    path = os.path.join(ROOT, "config", "prompts", stem + ".txt")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    t = textio.read_text(path)
    if not kw:
        return t
    pat = re.compile(r"\{(" + "|".join(re.escape(k) for k in kw) + r")\}")
    return pat.sub(lambda m: str(kw[m.group(1)]), t)
