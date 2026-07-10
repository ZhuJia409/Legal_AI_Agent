from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
INFRA_COMPOSE = ROOT_DIR / "infra" / "docker-compose.yml"
LOG_DIR = ROOT_DIR / "logs" / "dev"
BACKEND_HEALTH_PATH = "/health"
READY_TIMEOUT_SECONDS = 90


class StartupLogger:
    def __init__(self, log_file: Path) -> None:
        self.log_file = log_file
        self._lock = threading.Lock()

    def line(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        with self._lock:
            print(formatted, flush=True)
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(formatted + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the full local Legal AI Agent stack for PyCharm."
    )
    parser.add_argument(
        "--no-infra",
        action="store_true",
        help="Skip Docker Compose infrastructure. Intended for diagnostics only.",
    )
    parser.add_argument("--backend-port", default="8000", help="FastAPI port.")
    parser.add_argument("--frontend-port", default="3000", help="Next.js port.")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    startup_logger = StartupLogger(LOG_DIR / "startup.log")
    reset_log_files()
    startup_logger.line("Legal AI Agent full-stack startup")
    startup_logger.line(f"Project root: {ROOT_DIR}")
    startup_logger.line(f"Logs: {LOG_DIR}")

    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        startup_logger.line("ERROR: .env not found. Copy .env.example to .env first.")
        return 1

    env = build_child_environment(env_file)
    processes: list[subprocess.Popen[str]] = []
    stop_event = threading.Event()

    try:
        if not preflight(
            args.backend_port,
            args.frontend_port,
            require_docker=not args.no_infra,
            startup_logger=startup_logger,
        ):
            return 1

        if not args.no_infra:
            startup_logger.line("Starting Docker infrastructure...")
            run_once(
                "infra",
                [
                    "docker",
                    "compose",
                    "-f",
                    str(INFRA_COMPOSE),
                    "up",
                    "-d",
                ],
                cwd=ROOT_DIR,
                env=env,
                log_file=LOG_DIR / "infra.log",
                startup_logger=startup_logger,
            )
        else:
            startup_logger.line("Skipping Docker infrastructure because --no-infra was supplied.")

        processes.append(
            start_process(
                "backend",
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "app.main:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    args.backend_port,
                ],
                cwd=BACKEND_DIR,
                env=env,
                log_file=LOG_DIR / "backend.log",
                startup_logger=startup_logger,
            )
        )
        processes.append(
            start_process(
                "frontend",
                [
                    "pnpm.cmd" if os.name == "nt" else "pnpm",
                    "dev",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    args.frontend_port,
                ],
                cwd=FRONTEND_DIR,
                env=env,
                log_file=LOG_DIR / "frontend.log",
                startup_logger=startup_logger,
            )
        )

        backend_url = f"http://127.0.0.1:{args.backend_port}"
        frontend_url = f"http://127.0.0.1:{args.frontend_port}"
        wait_for_http(
            name="backend",
            url=f"{backend_url}{BACKEND_HEALTH_PATH}",
            process=processes[0],
            timeout_seconds=READY_TIMEOUT_SECONDS,
            startup_logger=startup_logger,
            log_file=LOG_DIR / "backend.log",
        )
        wait_for_http(
            name="frontend",
            url=frontend_url,
            process=processes[1],
            timeout_seconds=READY_TIMEOUT_SECONDS,
            startup_logger=startup_logger,
            log_file=LOG_DIR / "frontend.log",
        )

        startup_logger.line("Stack is ready.")
        startup_logger.line(f"Frontend: {frontend_url}")
        startup_logger.line(f"Backend docs: {backend_url}/docs")
        startup_logger.line(f"Backend health: {backend_url}{BACKEND_HEALTH_PATH}")
        startup_logger.line("Press Ctrl+C in PyCharm to stop backend and frontend.")

        while True:
            for process_name, process in zip(("backend", "frontend"), processes, strict=True):
                return_code = process.poll()
                if return_code is not None:
                    startup_logger.line(f"ERROR: {process_name} exited with code {return_code}.")
                    print_log_tail(LOG_DIR / f"{process_name}.log", startup_logger)
                    return return_code
            stop_event.wait(1)
    except KeyboardInterrupt:
        startup_logger.line("Stopping local development processes...")
        return 0
    except subprocess.CalledProcessError as exc:
        startup_logger.line(f"ERROR: command failed with code {exc.returncode}: {exc.cmd}")
        return exc.returncode
    except RuntimeError as exc:
        startup_logger.line(f"ERROR: {exc}")
        return 1
    finally:
        stop_event.set()
        stop_processes(processes, startup_logger)


def reset_log_files() -> None:
    for name in ("startup.log", "infra.log", "backend.log", "frontend.log"):
        path = LOG_DIR / name
        path.write_text("", encoding="utf-8")


def build_child_environment(env_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(parse_dotenv(env_file))
    env.setdefault("BACKEND_API_BASE_URL", "http://127.0.0.1:8000")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def parse_dotenv(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def preflight(
    backend_port: str,
    frontend_port: str,
    *,
    require_docker: bool,
    startup_logger: StartupLogger,
) -> bool:
    startup_logger.line("Running preflight checks...")
    required = ["uv", "git"]
    if require_docker:
        required.append("docker")
    required.append("pnpm.cmd" if os.name == "nt" else "pnpm")
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        startup_logger.line(f"ERROR: missing command(s): {', '.join(missing)}")
        return False

    ports = [("backend", backend_port), ("frontend", frontend_port)]
    busy_ports = [f"{name}:{port}" for name, port in ports if is_port_open("127.0.0.1", int(port))]
    if busy_ports:
        startup_logger.line(
            "ERROR: required port(s) already in use: "
            + ", ".join(busy_ports)
            + ". Stop the existing process or choose another port."
        )
        return False

    startup_logger.line("Preflight checks passed.")
    return True


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def run_once(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_file: Path,
    startup_logger: StartupLogger,
) -> None:
    startup_logger.line(f"[{name}] {' '.join(command)}")
    with log_file.open("a", encoding="utf-8") as log_handle:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdout:
            log_handle.write(process.stdout)
            for line in process.stdout.splitlines():
                startup_logger.line(f"[{name}] {line}")
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)


def start_process(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_file: Path,
    startup_logger: StartupLogger,
) -> subprocess.Popen[str]:
    startup_logger.line(f"[{name}] {' '.join(command)}")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    threading.Thread(
        target=stream_output,
        args=(name, process, log_file, startup_logger),
        daemon=True,
    ).start()
    return process


def stream_output(
    name: str,
    process: subprocess.Popen[str],
    log_file: Path,
    startup_logger: StartupLogger,
) -> None:
    if process.stdout is None:
        return
    with log_file.open("a", encoding="utf-8") as log_handle:
        for line in process.stdout:
            clean_line = line.rstrip()
            log_handle.write(clean_line + "\n")
            log_handle.flush()
            startup_logger.line(f"[{name}] {clean_line}")


def wait_for_http(
    *,
    name: str,
    url: str,
    process: subprocess.Popen[str],
    timeout_seconds: int,
    startup_logger: StartupLogger,
    log_file: Path,
) -> None:
    startup_logger.line(f"Waiting for {name}: {url}")
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            print_log_tail(log_file, startup_logger)
            raise RuntimeError(f"{name} exited before becoming ready (code {return_code}).")
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 500:
                    startup_logger.line(f"{name} is reachable ({response.status}).")
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(1)
    print_log_tail(log_file, startup_logger)
    raise RuntimeError(f"{name} did not become ready within {timeout_seconds}s. {last_error}")


def print_log_tail(log_file: Path, startup_logger: StartupLogger, line_count: int = 40) -> None:
    if not log_file.exists():
        return
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return
    startup_logger.line(f"Last {min(line_count, len(lines))} lines from {log_file}:")
    for line in lines[-line_count:]:
        startup_logger.line(f"  {line}")


def stop_processes(processes: list[subprocess.Popen[str]], startup_logger: StartupLogger) -> None:
    for process in processes:
        if process.poll() is None:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()

    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                startup_logger.line(f"Force killing process tree for PID {process.pid}.")
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
