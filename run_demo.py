"""
run_demo.py — starts the backend API and Streamlit frontend together.

Usage:
    .venv/Scripts/python.exe run_demo.py    (Windows)
    .venv/bin/python run_demo.py            (macOS/Linux)

Stops both processes with Ctrl+C. Set AML_USE_MOCKS=1 in .env to run against
mock tools instead of the real dataset/detectors.
"""

import os
import subprocess
import sys
import time
import webbrowser

BACKEND_CMD = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"]
FRONTEND_CMD = [sys.executable, "-m", "streamlit", "run", "frontend/app.py", "--server.headless", "true"]


def main() -> None:
    env = os.environ.copy()
    env.setdefault("AML_API_URL", "http://127.0.0.1:8000")

    print("Starting backend  (uvicorn backend.main:app) on http://127.0.0.1:8000 ...")
    backend = subprocess.Popen(BACKEND_CMD, env=env)

    time.sleep(2)  # give the API a moment to bind before the UI's first health check

    print("Starting frontend (streamlit run frontend/app.py) on http://localhost:8501 ...")
    frontend = subprocess.Popen(FRONTEND_CMD, env=env)

    try:
        webbrowser.open("http://localhost:8501")
    except Exception:
        pass

    print("\nBoth running. Press Ctrl+C to stop.\n")
    try:
        while True:
            if backend.poll() is not None:
                print("Backend exited unexpectedly — check its output above.")
                break
            if frontend.poll() is not None:
                print("Frontend exited unexpectedly — check its output above.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for proc in (frontend, backend):
            if proc.poll() is None:
                proc.terminate()
        for proc in (frontend, backend):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
