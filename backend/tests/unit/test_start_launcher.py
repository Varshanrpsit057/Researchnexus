"""The repo-root launcher (`python start.py`): the decisions it makes before
it starts anything -- which GPU tier a machine has, which background the
frontend starts with, which processes on a port are a stale ResearchNexus
server it may stop, and that the frontend's port is pinned."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("researchnexus_start", ROOT / "start.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    writes_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no __pycache__ left at the repo root
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes_bytecode
    return module


start = _load()


@pytest.mark.parametrize(
    ("name", "tier"),
    [
        ("NVIDIA GeForce RTX 4060 Ti", "dedicated"),
        ("NVIDIA Quadro P2000", "dedicated"),
        ("AMD Radeon RX 7800 XT", "dedicated"),
        ("AMD Radeon Pro W6800", "dedicated"),
        ("Intel(R) Arc(TM) A770 Graphics", "dedicated"),
        ("Apple M2 Pro", "dedicated"),
        ("Intel(R) UHD Graphics 770", "integrated"),
        ("Intel(R) Iris(R) Xe Graphics", "integrated"),
        ("Intel(R) Arc(TM) Graphics", "integrated"),  # Meteor Lake's built-in GPU, not an Arc card
        ("AMD Radeon(TM) Graphics", "integrated"),
        ("AMD Radeon 780M Graphics", "integrated"),
        ("Microsoft Basic Display Adapter", "software"),
        ("Microsoft Remote Display Adapter", "software"),
        ("llvmpipe (LLVM 15.0.7, 256 bits)", "software"),
        ("VMware SVGA 3D", "software"),
        ("", "unknown"),
        ("Some Future Accelerator", "unknown"),
    ],
)
def test_classify_gpu(name: str, tier: str) -> None:
    assert start.classify_gpu(name) == tier


def test_background_follows_the_best_gpu() -> None:
    gpu = start.Gpu
    # a laptop with both: the dedicated GPU decides
    assert start.background_mode([gpu("Intel UHD", "integrated"), gpu("RTX 4060", "dedicated")]) == "neural"
    assert start.background_mode([gpu("Intel UHD", "integrated")]) == "fibers"
    assert start.background_mode([gpu("Microsoft Basic Display Adapter", "software")]) == "static"
    # nothing known: the browser's own check decides
    assert start.background_mode([]) == "auto"
    assert start.background_mode([gpu("?", "unknown")]) == "auto"


ROOT_PATH = Path(r"H:\Researchnexus")


# --- machines without NVIDIA, CUDA or any GPU tool (remediation Phase 17) ---


def test_no_gpu_tool_at_all_starts_with_the_browsers_own_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows without PowerShell, a query that times out, or a malformed answer: no crash, no guess
    import subprocess

    for error in (FileNotFoundError("powershell"), subprocess.TimeoutExpired("powershell", 30), ValueError("bad json")):
        def broken(error: Exception = error) -> list[str]:
            raise error

        monkeypatch.setattr(start, "_gpu_names", broken)
        assert start.detect_gpus() == []
        assert start.background_mode(start.detect_gpus()) == "auto"


def test_linux_without_nvidia_smi_or_lspci_asks_nothing_it_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(start, "WINDOWS", False)
    monkeypatch.setattr(start.sys, "platform", "linux")
    monkeypatch.setattr(start.shutil, "which", lambda _name: None)

    def never(*_a: object, **_k: object) -> None:
        raise AssertionError("ran a tool that isn't installed")

    monkeypatch.setattr(start, "run", never)
    assert start.detect_gpus() == []


@pytest.mark.parametrize(
    ("names", "background"),
    [
        (["Intel(R) UHD Graphics 620"], "fibers"),  # a thin laptop: integrated only
        (["AMD Radeon(TM) Graphics"], "fibers"),  # an AMD APU laptop
        (["Intel(R) Iris(R) Xe Graphics", "NVIDIA GeForce RTX 4060 Laptop GPU"], "neural"),  # hybrid: the dGPU decides
        (["Microsoft Basic Display Adapter"], "static"),  # no driver: software only
        (["VMware SVGA 3D"], "static"),  # a virtual machine
        ([], "auto"),  # nothing reported
    ],
)
def test_the_background_follows_what_the_machine_reports(
    monkeypatch: pytest.MonkeyPatch, names: list[str], background: str
) -> None:
    monkeypatch.setattr(start, "_gpu_names", lambda: names)
    assert start.background_mode(start.detect_gpus()) == background


def test_the_frontend_is_told_the_startup_background() -> None:
    server = start.frontend_server("npm", "fibers")
    assert server.env["NEXT_PUBLIC_RN_BACKGROUND"] == "fibers"
    assert server.env["PORT"] == "3000"


@pytest.mark.parametrize(
    ("command", "ours"),
    [
        (r"C:\Python310\python.exe -m uvicorn app.main:app --app-dir H:\Researchnexus\backend --port 8000", True),
        (r'"C:\Program Files\nodejs\node.exe" H:\Researchnexus\frontend\node_modules\next\dist\server\lib\start-server.js', True),
        (r"C:\Python310\python.exe H:/Researchnexus/.claude/dev-server.py backend", True),
        (r"C:\Python310\python.exe H:\Researchnexus\start.py", True),
        # another project's server on the same port is never ours to stop
        (r"C:\Python310\python.exe -m uvicorn main:app --app-dir D:\other-project --port 8000", False),
        # our folder, but not one of our servers (an editor, a shell)
        (r'"C:\Program Files\Microsoft VS Code\Code.exe" H:\Researchnexus', False),
        # a real interpreter behind the venv redirector, without --app-dir: unrecognisable
        (r"C:\Python310\python.exe -m uvicorn app.main:app --port 8000", False),
    ],
)
def test_is_ours(command: str, ours: bool) -> None:
    assert start.is_ours(command, ROOT_PATH) is ours


def _table(*rows: tuple[int, int, str, str]) -> dict:
    return {pid: start.Proc(pid, parent, name, cmd) for pid, parent, name, cmd in rows}


def test_stale_server_is_stopped_from_its_launcher_down() -> None:
    root = str(start.ROOT)
    table = _table(
        (1, 0, "explorer.exe", "explorer.exe"),
        (10, 1, "powershell.exe", "powershell.exe"),
        (20, 10, "python.exe", f"python.exe {root}\\start.py"),
        (30, 20, "python.exe", f"{root}\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir {root}\\backend"),
        (31, 30, "python.exe", f"C:\\Python310\\python.exe -m uvicorn app.main:app --app-dir {root}\\backend"),
    )
    # the launcher above the port's owner goes, with everything under it
    assert start.stale_tree_root(31, table, protected={999}) == 20
    assert sorted(start.descendants(20, table)) == [30, 31]


def test_stale_server_without_a_recognisable_launcher_stops_at_its_own_chain() -> None:
    root = str(start.ROOT)
    table = _table(
        (1, 0, "explorer.exe", "explorer.exe"),
        (10, 1, "powershell.exe", "powershell.exe"),
        (20, 10, "python.exe", "python.exe start.py"),  # started with a relative path
        (30, 20, "python.exe", f"{root}\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir {root}\\backend"),
        (31, 30, "python.exe", f"C:\\Python310\\python.exe -m uvicorn app.main:app --app-dir {root}\\backend"),
    )
    # the server's own chain; that launcher then sees its server end and stops itself
    assert start.stale_tree_root(31, table, protected={999}) == 30


def test_the_running_launcher_and_its_parents_are_never_stopped() -> None:
    root = str(start.ROOT)
    table = _table(
        (1, 0, "explorer.exe", "explorer.exe"),
        (20, 1, "python.exe", f"python.exe {root}\\start.py"),  # this very launcher
        (30, 20, "python.exe", f"{root}\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir {root}\\backend"),
    )
    assert start.stale_tree_root(30, table, protected={20}) == 30


@pytest.mark.parametrize(
    ("script", "port"),
    [("next dev -p 3000", 3000), ("next dev --port 3000", 3000), ("next dev --port=3000", 3000), ("next dev", None)],
)
def test_dev_script_port(script: str, port: int | None) -> None:
    assert start.dev_script_port(script) == port


def test_the_project_pins_its_ports() -> None:
    import json

    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert start.dev_script_port(package["scripts"]["dev"]) == start.PORTS["frontend"] == 3000
    assert start.PORTS["backend"] == 8000
    assert start.API_BASE == "http://localhost:8000"
