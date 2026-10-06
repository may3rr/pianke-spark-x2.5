"""Owns the two llama-server processes (4B and 1.7B). Each runs on its own
loopback port with Metal offload; nothing listens beyond 127.0.0.1."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

import httpx

from ..config import EXTERNAL_LLM, LLAMA_SERVER, MODELS, MODELS_DIR, ModelSpec


@dataclass
class ServerState:
    spec: ModelSpec
    status: str = "stopped"  # stopped | loading | ready | missing | error
    error: str | None = None
    started_at: float | None = None
    ready_at: float | None = None
    proc: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def base_url(self) -> str:
        if EXTERNAL_LLM:
            return EXTERNAL_LLM.rstrip("/")
        return f"http://127.0.0.1:{self.spec.port}"

    def public(self) -> dict:
        path = MODELS_DIR / self.spec.file
        return {
            "key": self.spec.key,
            "name": self.spec.name,
            "file": self.spec.file,
            "status": self.status,
            "error": self.error,
            "ctx": self.spec.ctx,
            "size_bytes": path.stat().st_size if path.exists() else None,
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
        for key in self.servers:
            threading.Thread(target=self._start, args=(key,), daemon=True).start()

    def _start(self, key: str) -> None:
        st = self.servers[key]
        if EXTERNAL_LLM:
            st.status = "loading"
            st.started_at = time.time()
            self._wait_ready(st)
            return
        path = MODELS_DIR / st.spec.file
        if not path.exists():
            st.status = "missing"
            st.error = f"没有找到模型文件 {path}"
            return
        binary = shutil.which(LLAMA_SERVER) or LLAMA_SERVER
        if self._healthy(st):  # a previous run left it up — reuse
            st.status = "ready"
            st.started_at = st.ready_at = time.time()
            return
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
            )
        except OSError as e:
            st.status = "error"
            st.error = f"无法启动 llama-server：{e}"
            return
        self._wait_ready(st)

    def _healthy(self, st: ServerState) -> bool:
        try:
            r = httpx.get(f"{st.base_url}/health", timeout=1.5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _wait_ready(self, st: ServerState, timeout: float = 180) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
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
        st.status = "error"
        st.error = "模型加载超时"

    def stop_all(self) -> None:
        for st in self.servers.values():
            if st.proc and st.proc.poll() is None:
                st.proc.terminate()
                try:
                    st.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    st.proc.kill()
            st.proc = None
            st.status = "stopped"

    # ------------------------------------------------------------ queries

    def url(self, key: str) -> str:
        return self.servers[key].base_url

    def ready(self, key: str) -> bool:
        return self.servers[key].status == "ready"

    def wait(self, key: str, timeout: float = 240) -> None:
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
