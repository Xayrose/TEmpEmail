import os
import subprocess
import sys
import time

port = os.getenv("PORT", "10000")
processes = {
    "telegram-bot": subprocess.Popen([sys.executable, "bot.py"]),
    "fastapi": subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", port]),
}
print("Started Telegram bot and FastAPI supervisor", flush=True)
try:
    while True:
        for name, process in processes.items():
            code = process.poll()
            if code is not None:
                print(f"{name} exited with code {code}; stopping service", flush=True)
                sys.exit(code if code else 1)
        time.sleep(2)
finally:
    for process in processes.values():
        if process.poll() is None:
            process.terminate()
    for process in processes.values():
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
