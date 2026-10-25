"""Owns the two llama-server processes (4B and 1.7B). Each runs on its own
loopback port with Metal offload; nothing listens beyond 127.0.0.1.

Local servers start on first use, not at launch: the 4B with its 128K
context takes about 5 GB, too much to hold while the user is only browsing.
PIANKE_PRELOAD=1 restores loading both at launch.

In API mode (settings.py) both roles point at an OpenAI-compatible endpoint
instead and no local process runs."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field

import httpx

from ..config import EXTERNAL_LLM, HOME, LLAMA_SERVER, MODELS, MODELS_DIR, ModelSpec
from . import settings as llm_settings


@dataclass
class ServerState:
    spec: ModelSpec
    status: str = "stopped"  # stopped | idle | loading | ready | missing | error
    error: str | None = None
    started_at: float | None = None
    ready_at: float | None = None
    proc: subprocess.Popen | None = field(default=None, repr=False)
    # API mode: {"base_url", "api_key", "model", "ctx", "host"}
    remote: dict | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.remote["model"] if self.remote else self.spec.name

    @property
    def ctx(self) -> int:
        return self.remote["ctx"] if self.remote else self.spec.ctx

    @property
    def base_url(self) -> str:
        if self.remote:
            return self.remote["base_url"]
        if EXTERNAL_LLM:
            return EXTERNAL_LLM.rstrip("/")
        return f"http://127.0.0.1:{self.spec.port}"

    def public(self) -> dict:
        path = MODELS_DIR / self.spec.file
        return {
            "key": self.spec.key,
            "name": self.name,
            "provider": "api" if self.remote else "local",
            "host": self.remote["host"] if self.remote else "",
            "file": "" if self.remote else self.spec.file,
            "status": self.status,
            "error": self.error,
            "ctx": self.ctx,
            "size_bytes": path.stat().st_size if path.exists() and not self.remote else None,
            "load_seconds": (
                round(self.ready_at - self.started_at, 1)
                if self.ready_at and self.started_at
                else None
            ),
        }


class Runtime:
    def __init__(self) -> None:
        self.servers = {k: ServerState(spec) for k, spec in MODELS.items()}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle

    def start_all(self) -> None:
        self.apply(llm_settings.load())

    def apply(self, s: dict) -> None:
        """Point both roles at what the settings say; called at launch and
        whenever the settings page saves."""
        with self._lock:
            for key, st in self.servers.items():
                if s["mode"] == "api":
                    self._stop(st)
                    model = s["big_model"] if key == "big" else (s["small_model"] or s["big_model"])
                    st.remote = {
                        "base_url": s["base_url"],
                        "api_key": s["api_key"],
                        "model": model or "未填写模型名",
                        "ctx": s["ctx"],
                        "host": llm_settings.host(s),
                    }
                    st.started_at = st.ready_at = time.time()
                    if s["base_url"] and model:
                        st.status, st.error = "ready", None
                    else:
                        st.status, st.error = "error", "在设置里填写接口地址和模型名"
                elif st.remote or st.status in ("stopped", "missing", "error"):
                    st.remote = None
                    st.status, st.error = "idle", None
                    if os.environ.get("PIANKE_PRELOAD") == "1":
                        self._ensure(st)

    def _ensure(self, st: ServerState) -> None:
        """Start an idle local server in the background (caller holds the lock)."""
        if st.status != "idle":
            return
        st.status = "loading"  # claimed: a second caller won't launch a twin
        threading.Thread(target=self._start, args=(st.spec.key,), daemon=True).start()

    def _start(self, key: str) -> None:
        st = self.servers[key]
        # under the lock so a switch to API mode can't interleave with a launch
        with self._lock:
            if st.remote:
                return
            wait = self._launch(st)
        if wait:
            self._wait_ready(st)

    def _launch(self, st: ServerState) -> bool:
        """Start (or reuse) the local server; True if it needs waiting on."""
        if EXTERNAL_LLM:
            st.status = "loading"
            st.started_at = time.time()
            return True
        path = MODELS_DIR / st.spec.file
        if not path.exists():
            st.status = "missing"
            st.error = f"没有找到模型文件 {path}"
            return False
        binary = shutil.which(LLAMA_SERVER) or LLAMA_SERVER
        who = self._who_listens(st)
        if self._healthy(st):
            if who in ("ours", "unknown"):
                # a previous run left it up (or something intentionally
                # shares the port) — reuse it
                st.status = "ready"
                st.started_at = st.ready_at = time.time()
                return False
            if who == "ours-stale":
                # our leftover, but serving different weights: it's ours
                # (pid file under our HOME), so put it down and start fresh
                self._kill_pid_file(st)
            else:  # a stranger holds our port; don't adopt, don't kill
                st.status = "error"
                st.error = f"端口 {st.spec.port} 被其他程序占用，模型没法启动。关掉那个程序再试。"
                return False
        elif who in ("ours", "ours-stale"):
            self._kill_pid_file(st)  # our leftover hung without listening
        args = [
            binary,
            "-m", str(path),
            "--host", "127.0.0.1",
            "--port", str(st.spec.port),
            "-c", str(st.spec.ctx),
            "-ngl", "99",
            "-fa", "on",
            "-np", "1",
            "--jinja",
            # thinking text comes back in reasoning_content, not in content
            "--reasoning-format", "deepseek",
            # reuse the KV of a shared prompt prefix (the taste profile)
            "--cache-reuse", "256",
            "--no-webui",
        ]
        st.status = "loading"
        st.error = None
        st.started_at = time.time()
        try:
            st.proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                # its own process group: a group kill can never miss it, and
                # it never receives signals meant for the backend
                process_group=0,
            )
        except OSError as e:
            st.status = "error"
            st.error = f"无法启动 llama-server：{e}"
            return False
        try:
            (HOME / f"llama-{st.spec.port}.pid").write_text(str(st.proc.pid))
        except OSError:
            pass
        return True

    def _who_listens(self, st: ServerState) -> str:
        """Classify the process the pid file points at: ours (our
        llama-server on the right weights), ours-stale (ours, other weights),
        stranger, or unknown (no/stale pid file)."""
        try:
            pid = int((HOME / f"llama-{st.spec.port}.pid").read_text().strip())
        except (OSError, ValueError):
            return "unknown"
        try:
            r = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=5,
            )
            cmd = r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        if not cmd:
            return "unknown"
        if "llama-server" not in cmd:
            return "stranger"
        if f"--port {st.spec.port}" not in cmd:
            # the pid was recycled by some other llama-server (the user's
            # own, on another port): not ours, never kill it
            return "unknown"
        return "ours" if st.spec.file in cmd else "ours-stale"

    def _kill_pid_file(self, st: ServerState) -> None:
        try:
            pid = int((HOME / f"llama-{st.spec.port}.pid").read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            return
        for _ in range(10):  # let the port actually free up
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.5)

    def _healthy(self, st: ServerState) -> bool:
        try:
            r = httpx.get(f"{st.base_url}/health", timeout=1.5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _wait_ready(self, st: ServerState, timeout: float = 180) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if st.remote:  # switched to API mode while this was loading
                return
            if st.proc is not None and st.proc.poll() is not None:
                tail = (st.proc.stderr.read() if st.proc.stderr else "")[-800:]
                st.status = "error"
                st.error = f"llama-server 退出：{tail.strip()}"
                return
            if self._healthy(st):
                st.status = "ready"
                st.ready_at = time.time()
                # drain stderr so the pipe never blocks the server
                if st.proc and st.proc.stderr:
                    threading.Thread(
                        target=lambda s=st.proc.stderr: [None for _ in s],
                        daemon=True,
                    ).start()
                return
            time.sleep(0.5)
        if not st.remote:
            st.status = "error"
            st.error = "模型加载超时"

    def stop_all(self) -> None:
        for st in self.servers.values():
            self._stop(st)

    def _stop(self, st: ServerState) -> None:
        if st.proc and st.proc.poll() is None:
            st.proc.terminate()
            try:
                st.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(st.proc.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        st.proc.kill()
                    except OSError:
                        pass
        st.proc = None
        st.status = "stopped"

    def watch_parent(self) -> None:
        """Die with the app: if Electron goes away without stopping us (force
        quit, crash), our parent pid changes and we shut the models down and
        leave, instead of turning into an orphan holding several GB."""
        ppid = os.getppid()

        def run() -> None:
            while True:
                time.sleep(2)
                if os.getppid() != ppid:
                    self.stop_all()
                    os._exit(0)

        threading.Thread(target=run, daemon=True, name="parent-watch").start()

    # ------------------------------------------------------------ queries

    def url(self, key: str) -> str:
        return self.servers[key].base_url

    def ready(self, key: str) -> bool:
        return self.servers[key].status == "ready"

    def wait(self, key: str, timeout: float = 240) -> None:
        with self._lock:
            self._ensure(self.servers[key])
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.servers[key].status
            if s == "ready":
                return
            if s in ("missing", "error"):
                raise RuntimeError(self.servers[key].error or "模型不可用")
            time.sleep(0.3)
        raise RuntimeError("等待模型加载超时")

    def public(self) -> list[dict]:
        return [s.public() for s in self.servers.values()]


runtime = Runtime()
