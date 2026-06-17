"""
test_sandbox.py — Sandbox execution tests.

No Docker calls. All container operations are mocked via StubRuntime or
subprocess.run patches. Safe to run anywhere.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sandbox import (
    DockerRuntime,
    ExecutionResult,
    StubRuntime,
    load_runtime,
    run,
)

# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_success_true_when_exit_0(self) -> None:
        r = ExecutionResult(stdout="hi", stderr="", exit_code=0)
        assert r.success is True

    def test_success_false_when_exit_nonzero(self) -> None:
        r = ExecutionResult(stdout="", stderr="err", exit_code=1)
        assert r.success is False

    def test_success_false_when_timed_out(self) -> None:
        r = ExecutionResult(stdout="", stderr="", exit_code=0, timed_out=True)
        assert r.success is False


# ---------------------------------------------------------------------------
# StubRuntime
# ---------------------------------------------------------------------------


class TestStubRuntime:
    def test_returns_configured_result(self) -> None:
        expected = ExecutionResult(stdout="hello", stderr="", exit_code=0)
        stub = StubRuntime(result=expected)
        result = stub.run(code="print('hello')", deps=[])
        assert result.stdout == "hello"

    def test_records_calls(self) -> None:
        stub = StubRuntime()
        stub.run(code="x=1", deps=["numpy"], allow_network=True)
        assert len(stub.calls) == 1
        assert stub.calls[0] == {
            "code": "x=1",
            "deps": ["numpy"],
            "allow_network": True,
        }

    def test_default_result_is_success(self) -> None:
        stub = StubRuntime()
        assert stub.run(code="", deps=[]).success


# ---------------------------------------------------------------------------
# load_runtime
# ---------------------------------------------------------------------------


class TestLoadRuntime:
    def test_stub_runtime_from_config(self) -> None:
        rt = load_runtime(config={"sandbox": {"runtime": "stub"}})
        assert isinstance(rt, StubRuntime)

    def test_docker_runtime_from_config(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            rt = load_runtime(config={"sandbox": {"runtime": "docker"}})
        assert isinstance(rt, DockerRuntime)

    def test_docker_runtime_default_when_no_sandbox_key(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            rt = load_runtime(config={})
        assert isinstance(rt, DockerRuntime)

    def test_custom_image_passed_through(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            rt = load_runtime(config={"sandbox": {"runtime": "docker", "image": "python:3.12"}})
        assert isinstance(rt, DockerRuntime)
        assert rt.image == "python:3.12"

    def test_unknown_runtime_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown runtime"):
            load_runtime(config={"sandbox": {"runtime": "firecracker"}})


# ---------------------------------------------------------------------------
# DockerRuntime — timeout floor enforcement
# ---------------------------------------------------------------------------


class TestDockerRuntimeFloors:
    def _make(self, **kwargs) -> DockerRuntime:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            return DockerRuntime(**kwargs)

    def test_exec_timeout_cannot_go_below_floor(self) -> None:
        rt = self._make(exec_timeout=5)
        assert rt.exec_timeout == 30

    def test_install_timeout_cannot_go_below_floor(self) -> None:
        rt = self._make(install_timeout=10)
        assert rt.install_timeout == 60

    def test_timeouts_above_floor_accepted(self) -> None:
        rt = self._make(exec_timeout=120, install_timeout=180)
        assert rt.exec_timeout == 120
        assert rt.install_timeout == 180


# ---------------------------------------------------------------------------
# DockerRuntime — network flags
# ---------------------------------------------------------------------------


class TestDockerRuntimeNetwork:
    def _make(self) -> DockerRuntime:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            return DockerRuntime()

    def _run_mock(self, returncode: int = 0) -> MagicMock:
        m = MagicMock()
        m.returncode = returncode
        m.stdout = "ok"
        m.stderr = ""
        return m

    def test_network_none_by_default(self) -> None:
        rt = self._make()
        with patch("subprocess.run", return_value=self._run_mock()) as mock_run:
            rt.run(code="print(1)", deps=[])
        cmd = mock_run.call_args[0][0]
        assert "--network" in cmd
        assert "none" in cmd

    def test_no_network_none_when_allow_network(self) -> None:
        rt = self._make()
        with patch("subprocess.run", return_value=self._run_mock()) as mock_run:
            rt.run(code="print(1)", deps=[], allow_network=True)
        cmd = mock_run.call_args[0][0]
        assert "none" not in cmd

    def test_install_phase_has_no_network_none_flag(self) -> None:
        rt = self._make()
        calls: list[list[str]] = []

        def _capture(cmd: list[str], **_: object) -> MagicMock:
            calls.append(cmd)
            return self._run_mock()

        with patch("subprocess.run", side_effect=_capture):
            rt.run(code="import numpy", deps=["numpy"])

        install_cmd = calls[0]
        exec_cmd = calls[1]
        # install phase must not have --network none
        install_pairs = list(itertools.pairwise(install_cmd))
        assert ("--network", "none") not in install_pairs
        # exec phase must have --network none
        exec_pairs = list(itertools.pairwise(exec_cmd))
        assert ("--network", "none") in exec_pairs


# ---------------------------------------------------------------------------
# DockerRuntime — timeout behaviour
# ---------------------------------------------------------------------------


class TestDockerRuntimeTimeout:
    def _make(self) -> DockerRuntime:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            return DockerRuntime()

    def test_timeout_returns_timed_out_result(self) -> None:
        import subprocess as sp

        rt = self._make()
        with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="docker", timeout=30)):
            result = rt.run(code="while True: pass", deps=[])

        assert result.timed_out is True
        assert result.success is False

    def test_runtime_error_returns_failure(self) -> None:
        rt = self._make()
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            result = rt.run(code="print(1)", deps=[])

        assert result.success is False
        assert "runtime error" in result.stderr


# ---------------------------------------------------------------------------
# DockerRuntime — install failure short-circuits execution
# ---------------------------------------------------------------------------


class TestDockerRuntimeInstallFailure:
    def _make(self) -> DockerRuntime:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            return DockerRuntime()

    def test_failed_install_skips_execution(self) -> None:
        fail = MagicMock(returncode=1, stdout="", stderr="ERROR: no matching distribution")
        rt = self._make()
        with patch("subprocess.run", return_value=fail) as mock_run:
            result = rt.run(code="import fakelib", deps=["fakelib==0.0.0"])

        # Only one docker run call — install failed, exec skipped
        assert mock_run.call_count == 1
        assert result.success is False


# ---------------------------------------------------------------------------
# Public run() API
# ---------------------------------------------------------------------------


class TestPublicRunApi:
    def test_uses_stub_runtime_when_injected(self) -> None:
        stub = StubRuntime(result=ExecutionResult(stdout="42", stderr="", exit_code=0))
        result = run(code="print(42)", runtime=stub)
        assert result.stdout == "42"

    def test_deps_default_to_empty_list(self) -> None:
        stub = StubRuntime()
        run(code="x=1", runtime=stub)
        assert stub.calls[0]["deps"] == []

    def test_allow_network_defaults_false(self) -> None:
        stub = StubRuntime()
        run(code="x=1", runtime=stub)
        assert stub.calls[0]["allow_network"] is False

    def test_config_passed_to_load_runtime(self) -> None:
        # When runtime not injected, config dict is forwarded to load_runtime
        result = run(
            code="print(1)",
            config={"sandbox": {"runtime": "stub"}},
        )
        assert result.success
