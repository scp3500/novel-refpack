#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库路径索引与门禁自检工具（纯 Python 3.9+ 标准库，零新增依赖）。

用法：
  python scripts/repo_check.py                         # 默认执行 --check
  python scripts/repo_check.py --check                 # 查 REPO_MAP.md 覆盖 + 公开 JSON/正则 + 纯标准库合规
  python scripts/repo_check.py --skeleton lib/corpus.py # 用 AST 抽单文件符号与 CLI 骨架辅助更新 REPO_MAP.md
  python scripts/repo_check.py --full                  # --check + 跑通全量 tests/ 单元测试
"""
import argparse
import ast
import os
import re
import subprocess
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib import textio  # noqa: E402

REPO_MAP = os.path.join(ROOT, "REPO_MAP.md")

MANAGED_CODE_DIRS = ("lib", "stylefit", "scripts")
PUBLIC_STYLEFIT_DIRS = (
    "config/stylefit",
    "config/stylefit_general",
    "config/stylefit_modern",
    "config/stylefit_fantasy",
    "config/stylefit_tieba",
)
REGEX_JSON_NAMES = {"intents.json", "topics.json", "scene_rules.json", "funcs.json"}

# 明确声明为局部可选依赖的白名单（不可在模块顶层硬导入）
OPTIONAL_THIRD_PARTY = {
    "scripts/00_extract.py": {"lxml"},
    "scripts/chat_fetch_tieba.py": {"aiotieba"},
}
LOCAL_TOP_MODULES = {"lib", "stylefit", "scripts", "tests"}

_FALLBACK_STDLIB = {
    "__future__", "abc", "argparse", "ast", "asyncio", "base64", "bisect", "builtins",
    "codecs", "collections", "concurrent", "contextlib", "copy", "csv", "ctypes",
    "dataclasses", "datetime", "decimal", "difflib", "email", "enum", "errno",
    "fnmatch", "fractions", "functools", "gc", "getopt", "getpass", "glob", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "linecache", "locale", "logging",
    "lzma", "math", "mimetypes", "multiprocessing", "numbers", "operator", "os",
    "pathlib", "pickle", "pkgutil", "platform", "plistlib", "posixpath", "pprint",
    "queue", "random", "re", "reprlib", "secrets", "select", "selectors", "shlex",
    "shutil", "signal", "socket", "sqlite3", "ssl", "stat", "statistics", "string",
    "struct", "subprocess", "sys", "tarfile", "tempfile", "textwrap", "threading",
    "time", "timeit", "tkinter", "tokenize", "traceback", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings", "weakref",
    "webbrowser", "xml", "zipfile", "zlib",
}


def _stdlib_names():
    names = getattr(sys, "stdlib_module_names", None)
    return (set(names) | {"__future__"}) if names else set(_FALLBACK_STDLIB)


def discover_managed_code(root=ROOT):
    out = []
    for d in MANAGED_CODE_DIRS:
        full_d = os.path.join(root, d)
        if not os.path.isdir(full_d):
            continue
        for fn in sorted(os.listdir(full_d)):
            if fn.endswith(".py"):
                out.append("%s/%s" % (d, fn))
    return sorted(out)


def discover_public_jsons(root=ROOT):
    out = []
    for rel in ("config/project.example.json", "config/chat.example.json"):
        if os.path.isfile(os.path.join(root, rel)):
            out.append(rel)
    for d in PUBLIC_STYLEFIT_DIRS:
        full_d = os.path.join(root, d)
        if not os.path.isdir(full_d):
            continue
        for fn in sorted(os.listdir(full_d)):
            if fn.endswith(".json"):
                out.append("%s/%s" % (d, fn))
    return sorted(out)


def parse_registered_paths(map_path=REPO_MAP):
    r"""解析 REPO_MAP.md 索引段落中以 `- `path`` 登记的全部 .py 路径。"""
    if not os.path.isfile(map_path):
        return set()
    txt = textio.read_text(map_path)
    return set(re.findall(r"^\s*-\s+`([^`]+\.py)`", txt, re.MULTILINE))


def check_coverage(root=ROOT):
    code_files = set(discover_managed_code(root))
    registered = parse_registered_paths(os.path.join(root, "REPO_MAP.md"))
    missing = sorted(code_files - registered)
    orphan = sorted(registered - code_files)
    return missing, orphan


def check_jsons_and_regex(root=ROOT):
    errors = []
    for rel in discover_public_jsons(root):
        full = os.path.join(root, rel)
        try:
            with open(full, encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception as exc:
            errors.append("%s: JSON 解析失败 (%s)" % (rel, exc))
            continue
        if os.path.basename(rel) in REGEX_JSON_NAMES and isinstance(data, dict):
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                if not isinstance(v, str):
                    errors.append("%s[%s]: 期望正则字符串，实际为 %s" % (rel, k, type(v).__name__))
                    continue
                try:
                    re.compile(v)
                except re.error as exc:
                    errors.append("%s[%s]: 无效正则 (%s)" % (rel, k, exc))
    return errors


def check_stdlib_only(root=ROOT):
    stdlib = _stdlib_names()
    violations = []
    for rel in discover_managed_code(root):
        full = os.path.join(root, rel)
        try:
            tree = ast.parse(textio.read_text(full), filename=rel)
        except SyntaxError as exc:
            violations.append("%s: 语法错误 (%s)" % (rel, exc))
            continue
        allowed_opt = OPTIONAL_THIRD_PARTY.get(rel, set())
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if top not in stdlib and top not in LOCAL_TOP_MODULES:
                        violations.append("%s:%d 顶层禁止引入非标准库模块 `%s`" % (rel, node.lineno, top))
            elif isinstance(node, ast.ImportFrom):
                if (node.level and node.level > 0) or not node.module:
                    continue
                top = node.module.split(".", 1)[0]
                if top not in stdlib and top not in LOCAL_TOP_MODULES:
                    violations.append("%s:%d 顶层禁止引入非标准库模块 `%s`" % (rel, node.lineno, top))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if top not in stdlib and top not in LOCAL_TOP_MODULES and top not in allowed_opt:
                        violations.append("%s:%d 存在未申报的第三方依赖 `%s`" % (rel, node.lineno, top))
            elif isinstance(node, ast.ImportFrom):
                if (node.level and node.level > 0) or not node.module:
                    continue
                top = node.module.split(".", 1)[0]
                if top not in stdlib and top not in LOCAL_TOP_MODULES and top not in allowed_opt:
                    violations.append("%s:%d 存在未申报的第三方依赖 `%s`" % (rel, node.lineno, top))
    return sorted(set(violations))


def extract_skeleton(path, root=ROOT):
    """用 AST 抽取单文件符号与 CLI 参数骨架，辅助增量更新 REPO_MAP.md。"""
    full = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(full):
        raise FileNotFoundError(full)
    src = textio.read_text(full)
    tree = ast.parse(src, filename=full)
    rel = os.path.relpath(full, root).replace("\\", "/")

    imports, classes, funcs, cli_flags = [], [], [], []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(("." * (node.level or 0)) + (node.module or ""))
        elif isinstance(node, ast.ClassDef):
            ms = [n.name for n in node.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("__")]
            classes.append((node.name, node.lineno, ms))
        elif isinstance(node, ast.FunctionDef):
            args = [a.arg for a in node.args.args]
            doc = (ast.get_docstring(node) or "").splitlines()
            funcs.append((node.name, node.lineno, args, doc[0].strip() if doc else ""))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            flags = [
                a.value for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("-")
            ]
            if flags:
                cli_flags.append("/".join(flags))

    lines = [
        "# Skeleton: `%s` (%d lines)" % (rel, src.count("\n") + 1),
        "- Imports: %s" % (", ".join(sorted(set(imports))) or "—"),
    ]
    if cli_flags:
        lines.append("- CLI Flags: %s" % " ".join(cli_flags))
    if classes:
        lines.append("- Classes:")
        for cname, ln, ms in classes:
            lines.append("  - L%d `class %s` (%s)" % (ln, cname, ", ".join(ms) or "—"))
    if funcs:
        lines.append("- Functions:")
        for fname, ln, fargs, fdoc in funcs:
            lines.append("  - L%d `%s(%s)`%s" % (ln, fname, ", ".join(fargs), (" — " + fdoc) if fdoc else ""))
    return "\n".join(lines) + "\n"


def run_check(root=ROOT):
    ok = True
    print("=== REPO_MAP 路径索引与门禁自检 ===")

    missing, orphan = check_coverage(root)
    if missing or orphan:
        ok = False
        print("[FAIL] 1. REPO_MAP.md 路径覆盖不一致：")
        if missing:
            print("  未登记新文件：%s" % ", ".join(missing))
        if orphan:
            print("  已删除悬空条目：%s" % ", ".join(orphan))
    else:
        print("[OK]   1. 路径覆盖：全部 %d 个受管 .py 文件均已登记在 REPO_MAP.md" % len(discover_managed_code(root)))

    json_errs = check_jsons_and_regex(root)
    if json_errs:
        ok = False
        print("[FAIL] 2. 配置 JSON / 正则校验失败（%d 项）：" % len(json_errs))
        for e in json_errs:
            print("  - %s" % e)
    else:
        print("[OK]   2. 配置契约：全部 %d 个公开 JSON 与正则均合法可编译" % len(discover_public_jsons(root)))

    std_errs = check_stdlib_only(root)
    if std_errs:
        ok = False
        print("[FAIL] 3. 纯标准库红线违规（%d 项）：" % len(std_errs))
        for e in std_errs:
            print("  - %s" % e)
    else:
        print("[OK]   3. 依赖红线：全仓核心模块 100% 纯 Python 标准库合规")

    return ok


def main():
    textio.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="REPO_MAP 路径索引校验与符号骨架工具")
    ap.add_argument("--check", action="store_true", help="检查 REPO_MAP.md 路径覆盖、公开 JSON/正则与纯标准库合规")
    ap.add_argument("--skeleton", default=None, help="用 AST 抽取单文件符号与 CLI 参数骨架")
    ap.add_argument("--full", action="store_true", help="执行 --check 并联跑全量 tests/ 单元测试")
    a = ap.parse_args()

    if a.skeleton:
        print(extract_skeleton(a.skeleton, ROOT))
        return

    if not run_check(ROOT):
        sys.exit(1)

    if a.full:
        print("\n=== 运行全量单元测试（tests/）===", flush=True)
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ROOT,
        )
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
