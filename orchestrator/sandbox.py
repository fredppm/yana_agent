"""
sandbox.py — Isolated code execution for YANA.

Runs LLM-generated code in an ephemeral container (Docker/Podman) outside the
YANA process. Host filesystem and network are isolated by default.

Two-phase execution:
  Phase 1 — dep install (network allowed, PyPI reachable)
  Phase 2 — code execution (--network none unless allow_network=True)

Hard limits (floors — providers.yaml may raise but not lower):
  execution timeout: 30 s
  install timeout:   60 s
  memory:            256 MB
  CPU:               1 core
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


# ---------------------------------------------------------------------------
# Runtime interface
# ---------------------------------------------------------------------------


class SandboxRuntime(ABC):
    @abstractmethod
    def run(
        self,
        code: str,
        deps: list[str],
        allow_network: bool = False,
    ) -> ExecutionResult: ...


# ---------------------------------------------------------------------------
# Docker / Podman runtime
# ---------------------------------------------------------------------------

_EXEC_TIMEOUT_FLOOR = 30  # seconds
_INSTALL_TIMEOUT_FLOOR = 60
_MEMORY_FLOOR = "256m"
_CPU_FLOOR = "1"


@dataclass
class DockerRuntime(SandboxRuntime):
    image: str = "python:3.11-slim"
    exec_timeout: int = _EXEC_TIMEOUT_FLOOR
    install_timeout: int = _INSTALL_TIMEOUT_FLOOR
    memory: str = _MEMORY_FLOOR
    cpus: str = _CPU_FLOOR

    def __post_init__(self) -> None:
        self._cmd = self._detect_runtime()
        # Enforce floors — caller cannot go below minimums
        self.exec_timeout = max(self.exec_timeout, _EXEC_TIMEOUT_FLOOR)
        self.install_timeout = max(self.install_timeout, _INSTALL_TIMEOUT_FLOOR)

    @staticmethod
    def _detect_runtime() -> str:
        for candidate in ("docker", "podman"):
            if shutil.which(candidate):
                return candidate
        raise RuntimeError("sandbox: neither docker nor podman found — cannot run sandbox")

    def run(
        self,
        code: str,
        deps: list[str],
        allow_network: bool = False,
    ) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="yana-sandbox-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "code.py").write_text(code, encoding="utf-8")

            if deps:
                install_result = self._install(deps, tmp_path)
                if not install_result.success:
                    return install_result

            return self._execute(tmp_path, allow_network)

    def _base_flags(self, tmp_path: Path) -> list[str]:
        return [
            self._cmd,
            "run",
            "--rm",
            "-v",
            f"{tmp_path}:/workspace",
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
        ]

    def _install(self, deps: list[str], tmp_path: Path) -> ExecutionResult:
        """Phase 1 — install deps with network access (PyPI reachable)."""
        cmd = [
            *self._base_flags(tmp_path),
            self.image,
            "pip",
            "install",
            "--quiet",
            "--target",
            "/workspace/pkgs",
            *deps,
        ]
        return self._run_cmd(cmd, timeout=self.install_timeout)

    def _execute(self, tmp_path: Path, allow_network: bool) -> ExecutionResult:
        """Phase 2 — execute code, network blocked unless allow_network=True."""
        flags = self._base_flags(tmp_path)
        if not allow_network:
            flags += ["--network", "none"]
        cmd = [
            *flags,
            "-e",
            "PYTHONPATH=/workspace/pkgs",
            self.image,
            "python",
            "/workspace/code.py",
        ]
        return self._run_cmd(cmd, timeout=self.exec_timeout)

    @staticmethod
    def _run_cmd(cmd: list[str], timeout: int) -> ExecutionResult:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ExecutionResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                stdout="",
                stderr=f"sandbox: execution timed out after {timeout}s",
                exit_code=1,
                timed_out=True,
            )
        except Exception as exc:
            return ExecutionResult(
                stdout="",
                stderr=f"sandbox: runtime error — {exc}",
                exit_code=1,
            )


# ---------------------------------------------------------------------------
# Stub runtime — for tests
# ---------------------------------------------------------------------------


@dataclass
class StubRuntime(SandboxRuntime):
    """Returns a fixed result. Inject via load_runtime() in tests."""

    result: ExecutionResult = field(
        default_factory=lambda: ExecutionResult(stdout="ok", stderr="", exit_code=0)
    )
    calls: list[dict] = field(default_factory=list)

    def run(
        self,
        code: str,
        deps: list[str],
        allow_network: bool = False,
    ) -> ExecutionResult:
        self.calls.append({"code": code, "deps": deps, "allow_network": allow_network})
        return self.result


# ---------------------------------------------------------------------------
# Runtime loader — reads providers.yaml
# ---------------------------------------------------------------------------


def load_runtime(config: dict | None = None) -> SandboxRuntime:
    """
    Build a SandboxRuntime from providers.yaml sandbox section.

    config: pre-loaded providers dict (pass in tests to avoid file I/O).
    If omitted, loads providers.yaml via providers.load_providers().
    """
    if config is None:
        from llm import load_providers

        config = load_providers()

    sandbox_cfg: dict = config.get("sandbox", {})
    runtime_key = sandbox_cfg.get("runtime", "docker")

    if runtime_key == "stub":
        return StubRuntime()

    if runtime_key in ("docker", "podman"):
        kwargs: dict = {}
        if "image" in sandbox_cfg:
            kwargs["image"] = sandbox_cfg["image"]
        if "exec_timeout" in sandbox_cfg:
            kwargs["exec_timeout"] = int(sandbox_cfg["exec_timeout"])
        if "install_timeout" in sandbox_cfg:
            kwargs["install_timeout"] = int(sandbox_cfg["install_timeout"])
        if "memory" in sandbox_cfg:
            kwargs["memory"] = sandbox_cfg["memory"]
        if "cpus" in sandbox_cfg:
            kwargs["cpus"] = str(sandbox_cfg["cpus"])
        return DockerRuntime(**kwargs)

    raise ValueError(f"sandbox: unknown runtime {runtime_key!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    code: str,
    deps: list[str] | None = None,
    allow_network: bool = False,
    *,
    runtime: SandboxRuntime | None = None,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Execute code in an isolated sandbox.

    Args:
        code:           Python source to execute.
        deps:           PyPI packages to install before execution.
        allow_network:  Grant outbound network access during execution.
                        Default False — all outbound traffic blocked.
        runtime:        Override runtime (for tests).
        config:         Override providers config dict (for tests).

    Returns:
        ExecutionResult with stdout, stderr, exit_code, timed_out.
    """
    rt = runtime or load_runtime(config)
    return rt.run(code=code, deps=deps or [], allow_network=allow_network)
