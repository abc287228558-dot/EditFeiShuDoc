import argparse
import os
import subprocess
import sys
import time
from typing import List


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _run(cmd: List[str], *, cwd: str, log_path: str) -> int:
    started = _ts()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n===== {started} =====\n")
        f.write(f"$ {' '.join(cmd)}\n")
        f.write(f"returncode={proc.returncode}\n")
        if proc.stdout:
            f.write("\n[stdout]\n")
            f.write(proc.stdout)
            if not proc.stdout.endswith("\n"):
                f.write("\n")
        if proc.stderr:
            f.write("\n[stderr]\n")
            f.write(proc.stderr)
            if not proc.stderr.endswith("\n"):
                f.write("\n")
    return proc.returncode


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--interval-seconds", type=int, default=120)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--all-accounts", action="store_true")
    p.add_argument("--account", default="")
    args = p.parse_args()

    if bool(args.all_accounts) == bool(args.account):
        raise RuntimeError("Must set exactly one of --all-accounts or --account")

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(repo_dir, config_path)

    log_path = os.path.join(repo_dir, ".state", "logs", "local_scheduler.log")

    cmd = [sys.executable, "run_pipeline.py", "--config", config_path]
    if args.headless:
        cmd.append("--headless")
    if args.all_accounts:
        cmd.append("--all-accounts")
    else:
        cmd.extend(["--account", args.account])

    print(f"[scheduler] repo={repo_dir}")
    print(f"[scheduler] interval_seconds={args.interval_seconds}")
    print(f"[scheduler] log={log_path}")
    print(f"[scheduler] cmd={' '.join(cmd)}")

    while True:
        t0 = time.time()
        rc = _run(cmd, cwd=repo_dir, log_path=log_path)
        print(f"[scheduler] {_ts()} done rc={rc}")
        elapsed = time.time() - t0
        sleep_s = max(0.0, float(args.interval_seconds) - elapsed)
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
