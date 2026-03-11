import argparse
import json
import os
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_accounts_from_anchor_csv(path: str) -> List[str]:
    import csv

    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            reader.fieldnames = [n.strip() for n in reader.fieldnames]
        accounts: List[str] = []
        for r in reader:
            acct = ((r.get("直播账号") or r.get("\ufeff直播账号") or "")).strip()
            if acct:
                accounts.append(acct)
        return accounts


def run_capture_stdout_stream_stderr(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> str:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    merged_env.setdefault("PYTHONUNBUFFERED", "1")

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env,
        bufsize=1,
    )
    assert p.stdout is not None
    assert p.stderr is not None

    def _pump() -> None:
        try:
            for line in p.stderr:
                if not line:
                    continue
                sys.stderr.write(line)
                sys.stderr.flush()
        except Exception:
            return

    t = threading.Thread(target=_pump, daemon=True)
    t.start()

    out = p.stdout.read() or ""
    rc = p.wait()
    try:
        t.join(timeout=0.5)
    except Exception:
        pass

    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, output=out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--limit", type=int, default=18)
    ap.add_argument("--max-workers", type=int, default=-1)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    cfg = load_json(args.config)
    target_cfg = cfg.get("target") or {}
    mapping_cfg = cfg.get("mapping") or {}

    anchor_map_csv = str(mapping_cfg.get("anchor_map_csv", "") or "").strip()
    if not anchor_map_csv:
        raise RuntimeError("config.json missing mapping.anchor_map_csv")

    accounts = load_accounts_from_anchor_csv(anchor_map_csv)
    accounts = [a for a in accounts if a]
    if args.limit > 0:
        accounts = accounts[: args.limit]

    if not accounts:
        raise RuntimeError(f"No accounts found in {anchor_map_csv}")

    export_max_workers = int(target_cfg.get("export_max_workers", 2))
    if args.max_workers >= 0:
        export_max_workers = args.max_workers

    download_dir = os.path.join("exports")
    os.makedirs(download_dir, exist_ok=True)

    cmd = [
        sys.executable,
        "export_kuaishou_parallel.py",
        "--accounts",
        ",".join(accounts),
        "--anchor-map-csv",
        anchor_map_csv,
        "--download-dir",
        download_dir,
    ]
    if export_max_workers > 0:
        cmd.extend(["--max-workers", str(export_max_workers)])
    if args.headless:
        cmd.append("--headless")

    sys.stderr.write(
        f"[test] accounts={len(accounts)} max_workers={export_max_workers} anchor_map_csv={anchor_map_csv} download_dir={download_dir}\n"
    )
    sys.stderr.flush()

    out = run_capture_stdout_stream_stderr(cmd)
    sys.stdout.write(out)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
