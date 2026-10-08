"""Set up and run ResearchNexus locally.

    python start.py                   check dependencies, then run both servers
    python start.py stop [backend|frontend]      stop the servers
    python start.py restart [backend|frontend]   stop, then start again
    python start.py status            what is running, and the GPU found
    python start.py backend           only the backend   http://localhost:8000
    python start.py frontend          only the frontend  http://localhost:3000

    --skip-install   don't check or install dependencies (a faster restart)

Starting checks, and installs only what is missing:
- Python >= 3.10, the backend virtualenv (backend/.venv) and its packages;
- backend/.env's local secrets (generated once when absent, never printed);
- the database schema (migrated to the latest revision, after a backup);
- Node >= 20.9, npm, and frontend/node_modules.
It then detects the GPU and picks the background the frontend starts with:
the neural network on a dedicated GPU, the lightweight fibers on an
integrated one or a weak (software) renderer. The browser can still decide on
its own, and Settings overrides both.

The ports are fixed: the frontend runs only on 3000 and the backend only on
8000. If one is held by a ResearchNexus server left over from an earlier run,
that server is stopped and the new one starts on the same port. Anything else
holding the port is named and the start stops -- there is never a fallback
port.

Every server dies with this launcher, however it ends (Ctrl+C, the terminal
closing, the tool that started it exiting):
- on Windows the launcher joins a Job Object with KILL_ON_JOB_CLOSE, so
  everything it starts -- the venv's python redirector and the real
  interpreter behind it, npm, next and next's workers -- is killed with it,
  and it watches its own parent processes and stops when any one of them
  ends (on this machine a tool's own "stop" can't reach the children, since
  C:\\Windows\\System32 -- and with it taskkill -- is missing from PATH);
- elsewhere the servers run in their own process group, which is stopped
  when the launcher exits or its parent does.
Ctrl+C first asks each server to shut down cleanly, then ends what is left.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PORTS = {"backend": 8000, "frontend": 3000}
API_BASE = f"http://localhost:{PORTS['backend']}"
APP_ORIGIN = f"http://localhost:{PORTS['frontend']}"
WINDOWS = os.name == "nt"
MIN_PYTHON = (3, 10)
MIN_NODE = (20, 9)
VENV_PYTHON = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
READY_TIMEOUT_S = {"backend": 90.0, "frontend": 180.0}
STOP_GRACE_S = 8.0


def say(message: str) -> None:
    with contextlib.suppress(OSError, ValueError):  # the terminal has gone away
        print(f"[start] {message}", flush=True)


def fail(message: str) -> None:
    say(message)
    sys.exit(1)


def run(cmd: list[str], *, cwd: Path | None = None, timeout: float | None = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _system32(*parts: str) -> str:
    # full paths: System32 is not always on PATH
    return str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", *parts))


POWERSHELL = _system32("WindowsPowerShell", "v1.0", "powershell.exe")
NETSTAT = _system32("netstat.exe")


def powershell(script: str, timeout: float = 60) -> str:
    return run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout).stdout


# --------------------------------------------------------------------------
# processes and ports


@dataclass(frozen=True)
class Proc:
    pid: int
    parent: int
    name: str
    command: str


def process_table() -> dict[int, Proc]:
    """Every process on the machine: pid -> parent, exe name, command line."""
    table: dict[int, Proc] = {}
    if WINDOWS:
        out = powershell(
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        rows = json.loads(out or "[]")
        for r in [rows] if isinstance(rows, dict) else rows:
            pid = int(r["ProcessId"])
            table[pid] = Proc(pid, int(r.get("ParentProcessId") or 0), r.get("Name") or "", r.get("CommandLine") or "")
        return table
    for line in run(["ps", "-axo", "pid=,ppid=,args="]).stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            command = parts[2] if len(parts) > 2 else ""
            name = os.path.basename(command.split(" ", 1)[0]) if command else ""
            table[int(parts[0])] = Proc(int(parts[0]), int(parts[1]), name, command)
    return table


_TOP_LEVEL = {"explorer.exe", "services.exe", "wininit.exe", "svchost.exe", "launchd", "systemd", "init"}


def ancestors(pid: int, table: dict[int, Proc]) -> list[int]:
    """A process's live ancestors, nearest first, stopping below the desktop/session root."""
    chain: list[int] = []
    seen = {pid}
    cur = table[pid].parent if pid in table else 0
    while cur and cur not in seen and cur in table and table[cur].name.lower() not in _TOP_LEVEL:
        chain.append(cur)
        seen.add(cur)
        cur = table[cur].parent
    return chain


def descendants(pid: int, table: dict[int, Proc]) -> list[int]:
    found: list[int] = []
    frontier = [pid]
    while frontier:
        parent = frontier.pop()
        kids = [p for p, proc in table.items() if proc.parent == parent and p != parent and p not in found]
        found.extend(kids)
        frontier.extend(kids)
    return found


def _norm(text: str) -> str:
    return text.lower().replace("/", "\\")


_OUR_PROGRAMS = ("start.py", "dev-server.py", "uvicorn", "app.main", "next", "npm")


def is_ours(command: str, root: Path = ROOT) -> bool:
    """A ResearchNexus dev server or launcher: one of our programs, run from this checkout."""
    c = _norm(command)
    return _norm(str(root)) in c and any(k in c for k in _OUR_PROGRAMS)


def is_launcher(command: str, root: Path = ROOT) -> bool:
    c = _norm(command)
    return _norm(str(root)) in c and ("start.py" in c or "dev-server.py" in c)


def stale_tree_root(owner: int, table: dict[int, Proc], protected: set[int]) -> int:
    """The process to stop, with everything under it, to free a port held by
    `owner`: the server's own chain of our processes (the real interpreter,
    the venv redirector; next and its workers), or -- when one started it --
    the ResearchNexus launcher above it."""
    chain: list[int] = []
    for pid in ancestors(owner, table):
        if pid in protected:
            break
        chain.append(pid)
    top = owner
    for pid in chain:
        if not is_ours(table[pid].command):
            break
        top = pid
    launchers = [pid for pid in chain if is_launcher(table[pid].command)]
    return launchers[-1] if launchers else top


def port_owner(port: int) -> int | None:
    if WINDOWS:
        for line in run([NETSTAT, "-ano"]).stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
                return int(parts[4])
        return None
    if shutil.which("lsof"):
        out = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]).stdout.split()
        return int(out[0]) if out else None
    if shutil.which("ss"):
        for line in run(["ss", "-ltnpH", f"sport = :{port}"]).stdout.splitlines():
            m = re.search(r"pid=(\d+)", line)
            if m:
                return int(m.group(1))
    return None


def listening(port: int) -> bool:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def terminate(pids: list[int]) -> None:
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)  # on Windows: TerminateProcess


def free_port(port: int, role: str) -> bool:
    """Stop a stale ResearchNexus server holding the port. Returns whether one
    was stopped; exits when something else holds the port."""
    owner = port_owner(port)
    if owner is None:
        return False
    table = process_table()
    proc = table.get(owner)
    if proc is None or not is_ours(proc.command):
        what = f"{proc.name} (pid {owner})" if proc else f"pid {owner}"
        fail(f"port {port} is held by {what}, which is not a ResearchNexus server. Stop it, then start again: "
             f"the {role} runs only on port {port}.")
    protected = {os.getpid(), *ancestors(os.getpid(), table)}
    top = stale_tree_root(owner, table, protected)
    say(f"port {port} is held by an earlier ResearchNexus {role} (pid {owner}); stopping it")
    terminate([*descendants(top, table), top])
    deadline = time.monotonic() + 15
    while port_owner(port) is not None and time.monotonic() < deadline:
        time.sleep(0.3)
    if port_owner(port) is not None:
        fail(f"port {port} is still busy (pid {port_owner(port)}); stop it and start again")
    return True


# --------------------------------------------------------------------------
# lifetime: every server dies with the launcher

if WINDOWS:
    import ctypes
    import ctypes.wintypes as wt

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _SYNCHRONIZE = 0x00100000
    _INFINITE = 0xFFFFFFFF
    _KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_EXTENDED_LIMITS = 9

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    # 64-bit handles: every call is typed, or ctypes truncates them to C ints
    for _name, _res, _args in (
        ("OpenProcess", wt.HANDLE, [wt.DWORD, wt.BOOL, wt.DWORD]),
        ("CreateJobObjectW", wt.HANDLE, [ctypes.c_void_p, wt.LPCWSTR]),
        ("SetInformationJobObject", wt.BOOL, [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]),
        ("AssignProcessToJobObject", wt.BOOL, [wt.HANDLE, wt.HANDLE]),
        ("GetCurrentProcess", wt.HANDLE, []),
        ("WaitForMultipleObjects", wt.DWORD, [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL, wt.DWORD]),
    ):
        _fn = getattr(_k32, _name)
        _fn.restype, _fn.argtypes = _res, _args


def join_kill_on_close_job() -> None:
    """Windows: everything started from here on dies when this process does."""
    if not WINDOWS:
        return
    job = _k32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
    if not job or not _k32.SetInformationJobObject(job, _JOB_EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise OSError(ctypes.get_last_error(), "could not create the process job")
    if not _k32.AssignProcessToJobObject(job, _k32.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "could not join the process job")
    # the handle is deliberately never closed: the job ends with this process


def watch_ancestors(on_exit: Callable[[], None]) -> None:
    """Call `on_exit` as soon as any parent of this launcher ends (the
    terminal, the tool that started it)."""
    table = process_table()
    chain = ancestors(os.getpid(), table)
    if not chain:
        return
    if WINDOWS:
        handles = [h for h in (_k32.OpenProcess(_SYNCHRONIZE, False, p) for p in chain) if h][:64]
        if not handles:
            return
        array = (wt.HANDLE * len(handles))(*handles)

        def wait() -> None:
            _k32.WaitForMultipleObjects(len(handles), array, False, _INFINITE)
            on_exit()
    else:

        def wait() -> None:
            while True:
                time.sleep(1)
                for pid in chain:
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        on_exit()
                        return

    threading.Thread(target=wait, daemon=True).start()


# --------------------------------------------------------------------------
# dependencies

_REQUIREMENTS_CHECK = r"""
import importlib.metadata as md, json, sys
try:
    import tomllib
except ImportError:
    from pip._vendor import tomli as tomllib
from pip._vendor.packaging.requirements import Requirement
project = tomllib.load(open(sys.argv[1], "rb"))["project"]
missing = []
for spec in project["dependencies"] + project.get("optional-dependencies", {}).get("dev", []):
    req = Requirement(spec)
    try:
        version = md.version(req.name)
    except md.PackageNotFoundError:
        missing.append(spec)
        continue
    if req.specifier and not req.specifier.contains(version, prereleases=True):
        missing.append(spec)
print(json.dumps(missing))
"""

_MIGRATION_CHECK = r"""
import json, os
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
cfg = Config("alembic.ini")
url = os.environ.get("RESEARCHNEXUS_DATABASE_URL") or cfg.get_main_option("sqlalchemy.url")
head = ScriptDirectory.from_config(cfg).get_current_head()
with create_engine(url).connect() as conn:
    current = MigrationContext.configure(conn).get_current_revision()
    tables = len(inspect(conn).get_table_names())
print(json.dumps({"url": url, "head": head, "current": current, "tables": tables}))
"""


def ensure_backend(install: bool) -> None:
    if not VENV_PYTHON.exists():
        if not install:
            fail("backend/.venv is missing; run `python start.py` without --skip-install to create it")
        say("creating the backend virtualenv (backend/.venv)")
        if subprocess.call([sys.executable, "-m", "venv", str(BACKEND / ".venv")]) != 0:
            fail("could not create backend/.venv")
    ensure_backend_secrets()
    if install:
        check = run([str(VENV_PYTHON), "-c", _REQUIREMENTS_CHECK, str(BACKEND / "pyproject.toml")], cwd=BACKEND)
        try:
            missing: list[str] | None = json.loads(check.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            missing = None  # pip's own parsers aren't available: install to be sure
        if missing is None or missing:
            say(f"installing backend packages{f' ({len(missing)} missing)' if missing else ''}")
            if subprocess.call([str(VENV_PYTHON), "-m", "pip", "install", "-e", f"{BACKEND}[dev]"], cwd=BACKEND) != 0:
                fail("installing the backend packages failed (see above)")
        else:
            say("backend packages are installed")
    migrate_database()


def ensure_backend_secrets() -> None:
    """backend/.env holds the local JWT and key-vault secrets. They are made
    once, when absent, and never printed. An existing key-vault secret is
    never replaced: saved LLM keys can't be decrypted without it."""
    env_file = BACKEND / ".env"
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    present = {line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line and not line.lstrip().startswith("#")}
    made: dict[str, str] = {}
    if "RESEARCHNEXUS_JWT_SECRET" not in present and not os.environ.get("RESEARCHNEXUS_JWT_SECRET"):
        made["RESEARCHNEXUS_JWT_SECRET"] = secrets.token_urlsafe(32)
    if "RESEARCHNEXUS_KEY_VAULT_SECRET" not in present and not os.environ.get("RESEARCHNEXUS_KEY_VAULT_SECRET"):
        made["RESEARCHNEXUS_KEY_VAULT_SECRET"] = base64.urlsafe_b64encode(os.urandom(32)).decode()  # a Fernet key
    if not made:
        return
    lines = [] if text.endswith("\n") or not text else [""]
    if not text:
        lines += ["# Local dev secrets (git-ignored). Keep KEY_VAULT_SECRET stable:",
                  "# saved LLM keys can't be decrypted after it changes."]
    lines += [f"{name}={value}" for name, value in made.items()]
    with env_file.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    say(f"added {', '.join(made)} to backend/.env (local only, never printed)")


def sqlite_backup(source: Path, target: Path) -> None:
    """A consistent copy of a SQLite database, made by SQLite itself: it
    includes writes still in the WAL file, which a file copy would miss."""
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def migrate_database() -> None:
    (BACKEND / "data").mkdir(exist_ok=True)
    check = run([str(VENV_PYTHON), "-c", _MIGRATION_CHECK], cwd=BACKEND)
    try:
        state = json.loads(check.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        fail(f"could not read the database's migration state:\n{check.stderr.strip()[-2000:]}")
    if state["current"] == state["head"]:
        say(f"database schema is current (revision {state['head']})")
        return
    if state["current"] is None and state["tables"]:
        say("the database has tables but no migration record; not migrating it (see backend/README.md)")
        return
    url: str = state["url"]
    if url.startswith("sqlite:///"):
        db_file = (BACKEND / url.removeprefix("sqlite:///")).resolve()
        if db_file.exists() and db_file.stat().st_size:
            backup = db_file.with_name(f"{db_file.name}.bak-pre-{state['head']}-{datetime.now():%Y%m%d-%H%M%S}")
            sqlite_backup(db_file, backup)
            say(f"backed up the database to {backup.relative_to(ROOT)}")
    say(f"migrating the database: {state['current'] or 'empty'} -> {state['head']}")
    if subprocess.call([str(VENV_PYTHON), "-m", "alembic", "upgrade", "head"], cwd=BACKEND) != 0:
        fail("the database migration failed (see above); the backup is next to the database")


def dev_script_port(script: str) -> int | None:
    m = re.search(r"(?:^|\s)(?:-p|--port)[\s=](\d+)", script)
    return int(m.group(1)) if m else None


def npm_command() -> str:
    npm = shutil.which("npm.cmd" if WINDOWS else "npm") or shutil.which("npm")
    if not npm:
        fail("npm was not found on PATH; install Node.js 20.9 or newer")
    return str(npm)


def ensure_frontend(install: bool) -> str:
    node = shutil.which("node")
    if not node:
        fail("node was not found on PATH; install Node.js 20.9 or newer")
    version = run([str(node), "--version"]).stdout.strip().lstrip("v")
    numbers = tuple(int(x) for x in re.findall(r"\d+", version)[:2])
    if numbers < MIN_NODE:
        fail(f"Node {version} is too old; ResearchNexus needs {MIN_NODE[0]}.{MIN_NODE[1]} or newer")
    npm = npm_command()
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    # without an explicit port, `next dev` silently moves to 3001, 3002, ...
    if dev_script_port(package.get("scripts", {}).get("dev", "")) != PORTS["frontend"]:
        fail(f"frontend/package.json's dev script must pin the port: `next dev -p {PORTS['frontend']}`")
    for env_file in sorted(FRONTEND.glob(".env*")):
        stray = {int(p) for p in re.findall(r"localhost:(\d+)", env_file.read_text(encoding="utf-8", errors="replace"))} - set(PORTS.values())
        if stray:
            fail(f"frontend/{env_file.name} points at port {', '.join(map(str, sorted(stray)))}; ResearchNexus uses only 3000 and 8000")
    names = [*package.get("dependencies", {}), *package.get("devDependencies", {})]
    missing = [n for n in names if not (FRONTEND / "node_modules" / n / "package.json").exists()]
    if missing:
        if not install:
            fail("frontend packages are missing; run `python start.py` without --skip-install")
        say(f"installing frontend packages ({len(missing)} missing)")
        if subprocess.call([npm, "install"], cwd=FRONTEND) != 0:
            fail("npm install failed (see above)")
    elif install:
        say(f"frontend packages are installed (Node {version})")
    return npm


# --------------------------------------------------------------------------
# GPU and background


@dataclass(frozen=True)
class Gpu:
    name: str
    tier: str  # "dedicated" | "integrated" | "software" | "unknown"


_SOFTWARE_RENDERERS = (
    "microsoft basic", "basic render", "remote display", "llvmpipe", "softpipe", "swiftshader",
    "virtualbox", "vmware", "parallels", "hyper-v", "qxl", "virtio", "cirrus", "citrix", "bochs",
)


def classify_gpu(name: str) -> str:
    n = " ".join(name.lower().split())
    if not n:
        return "unknown"
    if any(s in n for s in _SOFTWARE_RENDERERS):
        return "software"
    if any(s in n for s in ("nvidia", "geforce", "quadro", "tesla", "rtx")):
        return "dedicated"
    if re.search(r"\barc(\(tm\))? [ab]\d", n):  # Intel Arc A/B-series cards
        return "dedicated"
    if re.search(r"\bapple m\d", n):  # Apple silicon: integrated, but discrete-class
        return "dedicated"
    if "radeon" in n or "firepro" in n:
        return "dedicated" if re.search(r"\b(rx|pro|r9|r7|vii|firepro)\b", n) else "integrated"
    if any(s in n for s in ("intel", "uhd", "iris", "adreno", "mali", "vega", "powervr")):
        return "integrated"
    return "unknown"


def background_mode(gpus: list[Gpu]) -> str:
    """The background the frontend starts with: `neural` (the full animated
    network), `fibers` (the lightweight shader -- also where the GPU is weak
    and draws in software, at a lighter setting the browser picks), or `auto`
    (let the browser's own GPU check decide)."""
    tiers = {g.tier for g in gpus}
    if "dedicated" in tiers:
        return "neural"
    if tiers & {"integrated", "software"}:
        return "fibers"
    return "auto"


def _gpu_names() -> list[str]:
    if WINDOWS:
        return powershell("Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }", timeout=30).splitlines()
    if sys.platform == "darwin":
        data = json.loads(run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=30).stdout or "{}")
        return [d.get("sppci_model", "") for d in data.get("SPDisplaysDataType", [])]
    names: list[str] = []
    if shutil.which("nvidia-smi"):
        names += run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=30).stdout.splitlines()
    if shutil.which("lspci"):
        for line in run(["lspci"], timeout=30).stdout.splitlines():
            m = re.search(r"(?:VGA compatible|3D|Display) controller: (.+)", line)
            if m:
                names.append(m.group(1))
    return names


def detect_gpus() -> list[Gpu]:
    try:
        names = _gpu_names()
    except (OSError, subprocess.SubprocessError, ValueError):
        names = []
    return [Gpu(n, classify_gpu(n)) for n in dict.fromkeys(n.strip() for n in names if n.strip())]


_BACKGROUND_LABELS = {
    "neural": "the animated neural network",
    "fibers": "the lightweight fibers",
    "static": "a still background",
    "auto": "whatever the browser's GPU check picks",
}


# --------------------------------------------------------------------------
# servers


@dataclass
class Server:
    role: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str]
    proc: subprocess.Popen[str] | None = None

    @property
    def port(self) -> int:
        return PORTS[self.role]


def backend_server() -> Server:
    env = {**os.environ, "RESEARCHNEXUS_CORS_ALLOWED_ORIGINS": json.dumps([APP_ORIGIN]),
           "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    # --app-dir puts this checkout's path on the command line, which is how a
    # later start recognises a stale server as ours
    cmd = [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND),
           "--host", "127.0.0.1", "--port", str(PORTS["backend"])]
    return Server("backend", cmd, BACKEND, env)


def frontend_server(npm: str, background: str) -> Server:
    env = {**os.environ, "NEXT_PUBLIC_API_BASE_URL": API_BASE, "PORT": str(PORTS["frontend"]),
           "NEXT_PUBLIC_RN_BACKGROUND": background}
    return Server("frontend", [npm, "run", "dev"], FRONTEND, env)


def spawn(server: Server) -> None:
    server.proc = subprocess.Popen(
        server.cmd, cwd=server.cwd, env=server.env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        # its own group: Ctrl+C reaches only the launcher, which then stops it in order
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0), start_new_session=not WINDOWS,
    )

    def pump() -> None:
        assert server.proc is not None and server.proc.stdout is not None
        for line in server.proc.stdout:
            with contextlib.suppress(OSError, ValueError):
                print(f"[{server.role}] {line.rstrip()}", flush=True)

    threading.Thread(target=pump, daemon=True).start()


def backend_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTS['backend']}/health", timeout=2) as resp:
            return bool(resp.status == 200)
    except OSError:
        return False


def wait_ready(server: Server, stop: threading.Event) -> bool:
    assert server.proc is not None
    deadline = time.monotonic() + READY_TIMEOUT_S[server.role]
    while time.monotonic() < deadline and not stop.is_set():
        if server.proc.poll() is not None:
            return False
        if backend_healthy() if server.role == "backend" else listening(server.port):
            return True
        time.sleep(0.4)
    return False


def stop_server(server: Server) -> None:
    """Ask the server to shut down cleanly, then end whatever is left of it."""
    proc = server.proc
    if proc is None:
        return
    before = process_table()
    tree = [*descendants(proc.pid, before), proc.pid]
    if proc.poll() is None:
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)  # uvicorn shuts down cleanly on it
            else:
                os.killpg(proc.pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_GRACE_S
    while time.monotonic() < deadline and (proc.poll() is None or listening(server.port)):
        time.sleep(0.2)
    after = process_table()
    # only what is still the same process: a pid can be reused once it exits
    terminate([p for p in tree if p in after and after[p].command == before[p].command])
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)


def supervise(servers: list[Server], background: str | None, gpus: list[Gpu]) -> int:
    stop = threading.Event()

    def parent_ended() -> None:
        say("the terminal or tool that started this ended; stopping")
        stop.set()

    watch_ancestors(parent_ended)
    for sig in ("SIGTERM", "SIGBREAK", "SIGHUP"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), lambda *_: stop.set())

    def stop_all() -> None:
        # a stuck shutdown can't hold the launcher: its end takes the servers with it
        watchdog = threading.Timer(30, lambda: os._exit(0))
        watchdog.daemon = True
        watchdog.start()
        for s in reversed(servers):
            stop_server(s)
        say("stopped")

    code = 0
    try:
        for s in servers:
            spawn(s)
        for s in servers:
            if not wait_ready(s, stop):
                if stop.is_set():
                    return 0
                assert s.proc is not None
                exited = s.proc.poll()
                reason = f"exited with code {exited}" if exited is not None else f"wasn't ready after {READY_TIMEOUT_S[s.role]:.0f}s"
                say(f"the {s.role} {reason}; stopping (its output is above)")
                return 1
            say(f"{s.role} ready on http://localhost:{s.port}")
        if len(servers) == 2:
            say("ResearchNexus is running")
            say(f"  app  {APP_ORIGIN}")
            say(f"  api  {API_BASE}")
        if background is not None:
            found = ", ".join(g.name for g in gpus) or "no GPU found"
            say(f"  background: {_BACKGROUND_LABELS[background]} ({found})")
        say("Press Ctrl+C to stop.")
        while not stop.is_set():
            for s in servers:
                assert s.proc is not None
                exited = s.proc.poll()
                if exited is not None:
                    say(f"the {s.role} stopped (exit code {exited}); stopping everything")
                    code = 1
                    stop.set()
            stop.wait(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        say("stopping")
        stop_all()
    return code


# --------------------------------------------------------------------------
# commands


def cmd_run(roles: list[str], install: bool) -> int:
    for role in roles:  # first, so migrations never run under a live server
        free_port(PORTS[role], role)
    npm = ""
    if "backend" in roles:
        ensure_backend(install)
    if "frontend" in roles:
        npm = ensure_frontend(install)
    background: str | None = None
    gpus: list[Gpu] = []
    if "frontend" in roles:
        gpus = detect_gpus()
        background = background_mode(gpus)
    join_kill_on_close_job()
    servers = [backend_server()] if "backend" in roles else []
    if "frontend" in roles:
        servers.append(frontend_server(npm, background or "auto"))
    return supervise(servers, background, gpus)


def cmd_stop(roles: list[str]) -> int:
    for role in roles:
        if free_port(PORTS[role], role):
            say(f"{role} stopped; port {PORTS[role]} is free")
        else:
            say(f"{role} is not running; port {PORTS[role]} is free")
    return 0


def cmd_status() -> int:
    table: dict[int, Proc] | None = None
    for role, port in PORTS.items():
        owner = port_owner(port)
        if owner is None:
            say(f"{role}: not running (port {port} is free)")
            continue
        table = table or process_table()
        proc = table.get(owner)
        if proc is None or not is_ours(proc.command):
            say(f"{role}: port {port} is held by {proc.name if proc else 'pid'} {owner}, which is not ResearchNexus")
            continue
        detail = ""
        if role == "backend":
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
                    body = json.loads(resp.read())
                detail = f", health {body.get('status')}, version {body.get('version')}"
            except (OSError, ValueError):
                detail = ", not answering /health"
        say(f"{role}: running on http://localhost:{port} (pid {owner}{detail})")
    gpus = detect_gpus()
    for g in gpus:
        say(f"GPU: {g.name} ({g.tier})")
    if not gpus:
        say("GPU: none found")
    say(f"background at start: {_BACKGROUND_LABELS[background_mode(gpus)]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python start.py",
        description="Set up and run ResearchNexus: frontend http://localhost:3000, backend http://localhost:8000.",
    )
    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "stop", "restart", "status", "backend", "frontend"])
    parser.add_argument("target", nargs="?", choices=["backend", "frontend"],
                        help="with stop or restart: only this server")
    parser.add_argument("--skip-install", action="store_true", help="don't check or install dependencies")
    args = parser.parse_args(argv)
    if args.target and args.command not in ("stop", "restart"):
        parser.error("a server name goes only after stop or restart")
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is needed (this is {sys.version.split()[0]})")
    if WINDOWS:
        with contextlib.suppress(AttributeError, ValueError):
            sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    roles = [args.target] if args.target else list(PORTS)
    if args.command == "status":
        return cmd_status()
    if args.command == "stop":
        return cmd_stop(roles)
    if args.command in ("backend", "frontend"):
        roles = [args.command]
    return cmd_run(roles, install=not args.skip_install)


if __name__ == "__main__":
    sys.exit(main())
