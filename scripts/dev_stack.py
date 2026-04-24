import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import shutil
from pathlib import Path


def stream_output(prefix: str, proc: subprocess.Popen[str]) -> None:
    if proc.stdout is None:
        return
    for line in proc.stdout:
        print(f"[{prefix}] {line.rstrip()}")


def kill_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Chaster Brain API + dashboard in one terminal."
    )
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8010)
    parser.add_argument("--dashboard-port", type=int, default=5174)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    brain_root = script_dir.parent
    dashboard_root = brain_root / "dashboard"

    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        args.api_host,
        "--port",
        str(args.api_port),
    ]
    npm_exe = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm_exe:
        print(
            "Could not find npm in PATH. Install Node.js and ensure npm is available in this terminal."
        )
        return 1

    dashboard_cmd = [npm_exe, "run", "dev", "--", "--port", str(args.dashboard_port)]

    print("Starting Chaster Brain stack...")
    print(f"- API:       http://{args.api_host}:{args.api_port}")
    print(f"- Dashboard: http://127.0.0.1:{args.dashboard_port}")
    print("Press Ctrl+C to stop both.")

    api_proc = subprocess.Popen(
        api_cmd,
        cwd=brain_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        dashboard_proc = subprocess.Popen(
            dashboard_cmd,
            cwd=dashboard_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except Exception:
        kill_process_tree(api_proc)
        raise

    threads = [
        threading.Thread(target=stream_output, args=("api", api_proc), daemon=True),
        threading.Thread(
            target=stream_output, args=("dashboard", dashboard_proc), daemon=True
        ),
    ]
    for t in threads:
        t.start()

    try:
        while True:
            api_code = api_proc.poll()
            dash_code = dashboard_proc.poll()
            if api_code is not None:
                print(f"API exited with code {api_code}. Stopping dashboard...")
                kill_process_tree(dashboard_proc)
                return api_code
            if dash_code is not None:
                print(f"Dashboard exited with code {dash_code}. Stopping API...")
                kill_process_tree(api_proc)
                return dash_code
            signal.pause() if os.name != "nt" else time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping services...")
        kill_process_tree(api_proc)
        kill_process_tree(dashboard_proc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
