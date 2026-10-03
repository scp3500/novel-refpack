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
import json
import time
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import textio

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

class CommandBackend:
    """把提示词落成文件，跑一条命令，再读输出。

    模板里可用：{prompt_file} {out_file} {chunk_file}
    命令跑完若 {out_file} 不存在，就取命令的 stdout 当结果。
    """

    def __init__(self, cfg):
        self.cfg = cfg
        if not cfg.get("command"):
            raise ValueError("backend=command 时必须配置 llm.command")

    def __call__(self, prompt, system=None, chunk_file=None, out_file=None):
        import tempfile
        d = tempfile.mkdtemp(prefix="refpack_")
        pf = os.path.join(d, "prompt.txt")
        of = out_file or os.path.join(d, "out.txt")
        full = (system + "\n\n" + prompt) if system else prompt
        textio.write_text(pf, full)
        cmd = self.cfg["command"].format(
            prompt_file=pf, out_file=of, chunk_file=chunk_file or "")
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore",
                           timeout=self.cfg["timeout"])
        if os.path.isfile(of) and os.path.getsize(of) > 0:
            return textio.read_text(of).strip()
        if p.stdout and p.stdout.strip():
            return p.stdout.strip()
        raise RuntimeError("命令没产出内容（exit %s）：%s" % (p.returncode, (p.stderr or "")[:300]))


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
        for attempt in range(1, max(1, retries) + 1):
            try:
                work(key, payload)
                return key, None
            except Exception as e:      # noqa: BLE001
                last = e
                time.sleep(min(30, 2 ** attempt))
        return key, last

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(one, it) for it in jobs]
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
    print("[%s] 完成 %d / 失败 %d" % (label, len(done), len(failed)))
    if failed:
        print("[%s] 失败清单：%s" % (label, ", ".join(str(x) for x in failed)))
    return done, failed
