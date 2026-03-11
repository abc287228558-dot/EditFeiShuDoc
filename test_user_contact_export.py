import argparse
import os
import sys
from typing import Any, Dict, List

import web_control_server as wcs


def _load_cfg(path: str) -> Dict[str, Any]:
    return wcs.load_json(path)


def _fake_rows(n: int, dept: str) -> List[List[str]]:
    out: List[List[str]] = []
    for i in range(1, n + 1):
        name = f"测试用户{i}"
        acct = f"test_user_{i:03d}"
        alias = f"测试别名{i}"
        phone = f"1380000{1000 + i:04d}"[-11:]
        out.append([name, acct, alias, dept, phone])
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--count", type=int, default=5)
    p.add_argument(
        "--dept",
        default="",
        help="Optional dept override. If empty, dept will be taken from frontend-saved config (.state/user_contact_cfg.json).",
    )
    args = p.parse_args()

    cfg = _load_cfg(args.config)

    export_dir = wcs._user_contact_export_dir(cfg, args)
    template_path = wcs._user_contact_template_xlsx_path(cfg, args)

    if not template_path or not os.path.exists(template_path):
        raise SystemExit(f"template_not_found: {template_path}")

    if not export_dir:
        export_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state")

    if export_dir.lower().startswith("smb://"):
        raise SystemExit(f"export_dir is smb url, please mount and use /Volumes/... path: {export_dir}")

    os.makedirs(export_dir, exist_ok=True)

    # Leave dept blank by default so export logic can apply saved dept config.
    dept = str(args.dept).strip()
    rows = _fake_rows(max(1, int(args.count)), dept)
    info = wcs._export_user_contact_xlsx_to_dir(cfg, args, rows, export_dir=export_dir)
    if not info.get("ok"):
        raise SystemExit(str(info))
    print(str(info.get("out_path") or ""))


if __name__ == "__main__":
    main()
