"""The repo-root launcher (`python start.py`): the decisions it makes before
it starts anything -- which GPU tier a machine has, which background the
frontend starts with, which processes on a port are a stale ResearchNexus
server it may stop, and that the frontend's port is pinned."""

from __future__ import annotations

import importlib.util
import json
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
    assert start.background_mode([gpu("Microsoft Basic Display Adapter", "software")]) == "fibers"  # weak: the light fibers
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
        (["Microsoft Basic Display Adapter"], "fibers"),  # no driver: software only, the light fibers
        (["VMware SVGA 3D"], "fibers"),  # a virtual machine
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


def test_a_virtualenv_from_another_computer_is_recognised(tmp_path: Path) -> None:
    """A zipped folder carries backend/.venv along; its pyvenv.cfg names the
    first computer's Python, which isn't on the next one (2026-10-09)."""
    import venv

    here = tmp_path / "made-here"
    venv.create(here, with_pip=False)
    assert start.venv_problem(here) is None  # a virtualenv made on this computer runs

    bindir, exe = ("Scripts", "python.exe") if start.WINDOWS else ("bin", "python")
    copied = tmp_path / "copied"
    (copied / bindir).mkdir(parents=True)
    (copied / bindir / exe).write_bytes((here / bindir / exe).read_bytes())
    elsewhere = r"C:\Users\someone-else\AppData\Local\Programs\Python\Python310" if start.WINDOWS else "/home/someone-else/python3.10"
    (copied / "pyvenv.cfg").write_text(f"home = {elsewhere}\ninclude-system-site-packages = false\nversion = 3.10.11\n", encoding="utf-8")
    problem = start.venv_problem(copied)
    assert problem is not None and "another computer" in problem and elsewhere in problem

    (copied / "pyvenv.cfg").unlink()
    assert start.venv_problem(copied) == "it is incomplete"


def test_frontend_packages_installed_elsewhere_are_checked_again(tmp_path: Path) -> None:
    here = {"platform": "win32", "arch": "amd64", "folder": r"D:\ResearchNexus"}
    marker = tmp_path / ".researchnexus-installed-for.json"
    assert start.node_modules_refresh_reason(marker, here) is not None  # no record: installed by someone else
    marker.write_text(json.dumps(here), encoding="utf-8")
    assert start.node_modules_refresh_reason(marker, here) is None
    assert "another kind of computer" in (start.node_modules_refresh_reason(marker, {**here, "platform": "darwin", "arch": "arm64"}) or "")
    assert "moved" in (start.node_modules_refresh_reason(marker, {**here, "folder": r"C:\Users\friend\ResearchNexus"}) or "")


def test_remove_tree_removes_read_only_files(tmp_path: Path) -> None:
    folder = tmp_path / "old"
    folder.mkdir()
    locked = folder / "read-only.txt"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(0o400)
    start.remove_tree(folder)
    assert not folder.exists()
