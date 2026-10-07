# -*- coding: utf-8 -*-
"""模型调用后端。两种模式 + 并发批处理，只依赖标准库。

  openai   —— 任何 OpenAI 兼容端点（/chat/completions）：本地 vLLM / Ollama /
              LM Studio / 各家云端 API。
  command  —— 任意命令行工具。提示词写成 {prompt_file}，输出读 {out_file}
              （或读 stdout）。把你的 agent / CLI 接进来用这个，
              也就是「一个任务一个子代理」的跑法：每个子代理独立上下文，
              一片 / 一卷互不干扰。并发怎么开见 docs/PARALLEL.md。

配置见 config/project.json 的 llm 段，或 docs/CONFIG.md。
"""
import os
import re
import json
import shlex
import shutil
import signal
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import textio

# Ctrl-C 时置位：停止重试，并结束所有在跑的命令
ABORT = threading.Event()
_LIVE = set()
_LIVE_LOCK = threading.Lock()

DEFAULTS = {
    "backend": "openai",
    "base_url": "http://127.0.0.1:8000/v1",
    "api_key_env": "OPENAI_API_KEY",
    "model": "gpt-4o-mini",
    "temperature": 0.3,
    "max_tokens": 4096,
    "timeout": 600,
    "retries": 3,
    "concurrency": 16,
    "command": "",
    "extra_body": {},
}


# ────────────────────────── openai 后端 ──────────────────────────

class OpenAIBackend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.url = cfg["base_url"].rstrip("/") + "/chat/completions"
        self.key = os.environ.get(cfg.get("api_key_env") or "", "") or "sk-none"

    def __call__(self, prompt, system=None):
        body = {
            "model": self.cfg["model"],
            "messages": ([{"role": "system", "content": system}] if system else [])
                        + [{"role": "user", "content": prompt}],
            "temperature": self.cfg["temperature"],
            "max_tokens": self.cfg["max_tokens"],
        }
        body.update(self.cfg.get("extra_body") or {})
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=self.cfg["timeout"]) as r:
            j = json.loads(r.read().decode("utf-8", errors="ignore"))
        ch = j.get("choices") or []
        if not ch:
            raise RuntimeError("接口没返回 choices：%s" % str(j)[:300])
        msg = ch[0].get("message") or {}
        txt = msg.get("content")
        if isinstance(txt, list):   # 兼容 [{type:text,text:...}]
            txt = "".join(x.get("text", "") for x in txt if isinstance(x, dict))
        return (txt or "").strip()


# ────────────────────────── command 后端 ──────────────────────────

PLACEHOLDER = re.compile(r"\{(prompt_file|out_file|chunk_file)\}")


def _quote(path, ctx):
    """按占位符所在的引号环境转义路径（ctx：None / "'" / '"'）。"""
    if os.name == "nt":                          # cmd.exe 只认双引号
        return path if ctx == '"' else '"%s"' % path
    if ctx == '"':
        return re.sub(r'([\\"$`])', r"\\\1", path)
    if ctx == "'":
        return path.replace("'", "'\"'\"'")
    return shlex.quote(path)


def render_command(tpl, values):
    """把 {prompt_file} / {out_file} / {chunk_file} 换成转义好的路径。

    不用 str.format：命令里常有 awk '{print}'、JSON 这类花括号。
    模板里自己加了引号的（"{out_file}"、'{out_file}'）按所在引号转义，不会引号套引号。
    """
    out, i, ctx = [], 0, None
    while i < len(tpl):
        m = PLACEHOLDER.match(tpl, i)
        if m:
            out.append(_quote(values.get(m.group(1)) or "", ctx))
            i = m.end()
            continue
        c = tpl[i]
        if c == "\\" and ctx != "'" and os.name != "nt" and i + 1 < len(tpl):
            out.append(tpl[i:i + 2])
            i += 2
            continue
        if (c == '"' or (c == "'" and os.name != "nt")) and ctx in (None, c):
            ctx = None if ctx == c else c
        out.append(c)
        i += 1
    return "".join(out)


def _kill_tree(p):
    """结束 shell 及它起的全部子孙进程。只杀 shell 的话，真正干活的 agent 会变成孤儿
    继续跑，和下一次重试同时写同一个输出。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        if sig == signal.SIGTERM:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass


def kill_all():
    with _LIVE_LOCK:
        live = list(_LIVE)
    for p in live:
        _kill_tree(p)


def run_command(cmd, timeout):
    """跑一条 shell 命令，返回 (exit, stdout, stderr)；超时结束整个进程组后抛 TimeoutError。

    子进程放进独立的进程组 / 会话，所以终端的 Ctrl-C 不会直接送到它们，
    由 run_batch 捕获 KeyboardInterrupt 后调 kill_all() 统一收尾。
    """
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
        else {"start_new_session": True}
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="ignore", **kw)
    with _LIVE_LOCK:
        _LIVE.add(p)
    try:
        so, se = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        try:
            p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            for s in (p.stdout, p.stderr):
                try:
                    s.close()
                except Exception:      # noqa: BLE001
                    pass
        raise TimeoutError("命令超时（%s 秒），已结束整个进程组" % timeout)
    finally:
        with _LIVE_LOCK:
            _LIVE.discard(p)
    return p.returncode, so, se


class CommandBackend:
    """把提示词落成文件，跑一条命令，再读输出。

    模板里可用：{prompt_file} {out_file} {chunk_file}（路径会自动转义）。
    {out_file} 是目标文件旁边的临时文件：命令中途失败 / 超时不会留下半截的目标文件，
    结果由调用方校验后再原子写入。命令跑完若 {out_file} 为空，就取 stdout 当结果；
    退出码非 0 一律算失败（哪怕写了一半输出）。
    """

    def __init__(self, cfg):
        self.cfg = cfg
        if not cfg.get("command"):
            raise ValueError("backend=command 时必须配置 llm.command")

    def __call__(self, prompt, system=None, chunk_file=None, out_file=None):
        d = tempfile.mkdtemp(prefix="refpack_")
        pf = os.path.join(d, "prompt.txt")
        if out_file:
            os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
            of = textio.tmp_sibling(out_file)
        else:
            of = os.path.join(d, "out.txt")
        try:
            textio.write_text(pf, (system + "\n\n" + prompt) if system else prompt)
            cmd = render_command(self.cfg["command"], {
                "prompt_file": pf, "out_file": of,
                "chunk_file": os.path.abspath(chunk_file) if chunk_file else ""})
            code, so, se = run_command(cmd, self.cfg["timeout"])
            if code != 0:
                raise RuntimeError("命令失败（exit %s）：%s" % (code, (se or so or "").strip()[:300]))
            if os.path.isfile(of) and os.path.getsize(of) > 0:
                return textio.read_text(of).strip()
            if so and so.strip():
                return so.strip()
            raise RuntimeError("命令没产出内容（exit 0）：%s" % (se or "").strip()[:300])
        finally:
            shutil.rmtree(d, ignore_errors=True)
            if out_file:
                try:
                    os.unlink(of)
                except OSError:
                    pass


def build(cfg=None):
    """cfg 为 llm 段；返回 callable(prompt, system=None, ...) -> str"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    if c["backend"] == "command":
        return CommandBackend(c)
    return OpenAIBackend(c)


def run_batch(jobs, work, concurrency=16, label="job", logdir="logs",
              on_done=None, retries=3):
    """jobs: 可迭代的 (key, payload)。work(key, payload) -> 结果字符串。

    结果写入由调用方在 work() 内完成；这里只负责并发、重试和日志。
    """
    os.makedirs(logdir, exist_ok=True)
    jobs = list(jobs)
    done, failed = [], []
    if not jobs:
        print("[%s] 没有待办任务" % label)
        return done, failed

    def one(item):
        key, payload = item
        last = None
        tries = max(1, retries)
        for attempt in range(1, tries + 1):
            if ABORT.is_set():
                return key, last or RuntimeError("已中断")
            try:
                work(key, payload)
                return key, None
            except Exception as e:      # noqa: BLE001
                last = e
                if attempt < tries:
                    ABORT.wait(min(30, 2 ** attempt))
        return key, last

    ABORT.clear()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(one, it) for it in jobs]
        try:
            for i, f in enumerate(as_completed(futs), 1):
                key, err = f.result()
                log = os.path.join(logdir, "%s-%s.log" % (label, str(key).replace("/", "_")))
                if err is None:
                    done.append(key)
                    textio.write_text(log, "OK\n")
                    print("[%s] %d/%d  OK  %s" % (label, i, len(jobs), key))
                else:
                    failed.append(key)
                    textio.write_text(log, "FAIL: %r\n" % (err,))
                    print("[%s] %d/%d  FAIL %s  %r" % (label, i, len(jobs), key, err))
                if on_done:
                    on_done(key, err)
        except KeyboardInterrupt:
            ABORT.set()
            for f in futs:
                f.cancel()
            kill_all()
            print("\n[%s] 已中断，在跑的命令已结束；重跑同一条命令会跳过已完成的" % label)
            raise
    print("[%s] 完成 %d / 失败 %d" % (label, len(done), len(failed)))
    if failed:
        print("[%s] 失败清单：%s" % (label, ", ".join(str(x) for x in failed)))
        print("[%s] 日志：%s/%s-*.log" % (label, logdir, label))
        print("[%s] 修好后重跑同一条命令即可（已完成的会自动跳过）" % label)
        # 非零退出，避免上游拿不完整的数据继续往下拼成品
        raise SystemExit(1)
    return done, failed
