import argparse
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from sync_to_feishu import FeishuClient, FeishuConfig, load_json


def _parse_excel_date(val: str) -> str:
    try:
        days = float(val)
        if days < 1 or days > 100000:
            return ""
        from datetime import timedelta

        base_date = datetime(1899, 12, 30)
        target_date = base_date + timedelta(days=days)
        return f"{target_date.month}月{target_date.day}日"
    except Exception:
        return ""


def _parse_excel_time(val: str) -> str:
    try:
        fraction = float(val)
        if fraction < 0 or fraction >= 1:
            return ""
        total_seconds = int(fraction * 24 * 60 * 60)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except Exception:
        return ""


def _to_excel_date(date_str: str) -> float:
    try:
        m = re.search(r"(\d+)月(\d+)日", str(date_str or ""))
        if not m:
            return 0.0
        month = int(m.group(1))
        day = int(m.group(2))
        now = datetime.now()
        target_date = datetime(now.year, month, day)
        base_date = datetime(1899, 12, 30)
        delta = target_date - base_date
        return float(delta.days)
    except Exception:
        return 0.0


def _to_excel_time(time_str: str) -> float:
    try:
        m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", str(time_str or "").strip())
        if not m:
            return 0.0
        hours = int(m.group(1))
        minutes = int(m.group(2))
        seconds = int(m.group(3)) if m.group(3) else 0
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds / (24 * 3600)
    except Exception:
        return 0.0


def _cell(row: List[Any], idx0: int) -> str:
    try:
        v = row[idx0]
        if v is None:
            return ""
        s = str(v).strip()
        if s.lower() in {"none", "null"}:
            return ""
        return s
    except Exception:
        return ""


def _resolve_delivery_sheet_id(client: FeishuClient, spreadsheet_token: str) -> str:
    sheets = client.list_sheets(spreadsheet_token)
    for s in sheets:
        if s.get("title") == "投放信息" and s.get("sheet_id"):
            return str(s.get("sheet_id"))
    raise RuntimeError("Cannot find sheet titled 投放信息")


def _find_summary_row(values: List[List[Any]]) -> int:
    for i, row in enumerate(values, start=1):
        if _cell(row, 0) == "汇总":
            return i
    raise RuntimeError("Cannot find 汇总 row")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--mode", choices=["no_inherit", "inherit_before", "inherit_after", "set_style"], default="inherit_before")
    ap.add_argument("--date", default="3月10日")
    ap.add_argument("--time", default="11:04")
    ap.add_argument("--account", default="琳琳好物")
    ap.add_argument("--live_id", default="123456789")
    args = ap.parse_args()

    cfg = load_json(args.config)
    feishu_cfg = cfg.get("feishu") or {}
    if not feishu_cfg.get("app_id") or not feishu_cfg.get("app_secret"):
        raise RuntimeError("Missing feishu.app_id/app_secret in config")

    client = FeishuClient(FeishuConfig(app_id=feishu_cfg["app_id"], app_secret=feishu_cfg["app_secret"]))
    spreadsheet_token = client.resolve_spreadsheet_token(
        wiki_url=(cfg.get("target") or {}).get("wiki_url", ""),
        spreadsheet_token=(cfg.get("target") or {}).get("spreadsheet_token", ""),
    )

    delivery_sheet_id = _resolve_delivery_sheet_id(client, spreadsheet_token)

    max_rows = 5000
    read_rng = f"{delivery_sheet_id}!A1:P{max_rows}"
    values = client.read_range_values(spreadsheet_token, read_rng)
    if not values:
        raise RuntimeError("投放信息 sheet empty")

    summary_row_1 = _find_summary_row(values)
    insert_at_1 = summary_row_1
    start_index_0 = insert_at_1 - 1

    inherit_style = ""
    if args.mode == "inherit_before":
        inherit_style = "BEFORE"
    elif args.mode == "inherit_after":
        inherit_style = "AFTER"
    elif args.mode == "no_inherit":
        inherit_style = ""
    elif args.mode == "set_style":
        inherit_style = ""

    resp = client.insert_dimension_range_rows(
        spreadsheet_token=spreadsheet_token,
        sheet_id=delivery_sheet_id,
        start_index_0=start_index_0,
        end_index_0=start_index_0 + 1,
        inherit_style=inherit_style,
    )

    excel_date = _to_excel_date(args.date)
    excel_time = _to_excel_time(args.time)

    write_row = [
        excel_date if excel_date > 0 else args.date,
        excel_time if excel_time > 0 else args.time,
        args.live_id,
        args.account,
        "",
        "",
    ]

    update_rng_af = f"{delivery_sheet_id}!A{insert_at_1}:F{insert_at_1}"
    client.update_values(spreadsheet_token, update_rng_af, [write_row])

    if args.mode == "set_style":
        client.set_cell_style(
            spreadsheet_token=spreadsheet_token,
            sheet_id=delivery_sheet_id,
            range_a1=f"A{insert_at_1}:A{insert_at_1}",
            formatter="yyyy-MM-dd",
        )
        client.set_cell_style(
            spreadsheet_token=spreadsheet_token,
            sheet_id=delivery_sheet_id,
            range_a1=f"B{insert_at_1}:B{insert_at_1}",
            formatter="HH:mm",
        )
        client.set_cell_alignment(
            spreadsheet_token=spreadsheet_token,
            sheet_id=delivery_sheet_id,
            range_a1=f"A{insert_at_1}:F{insert_at_1}",
            h_align=2,
            v_align=2,
        )

    read_back_rng = f"{delivery_sheet_id}!A{insert_at_1}:B{insert_at_1}"
    back = client.read_range_values(spreadsheet_token, read_back_rng)
    a_raw = _cell(back[0], 0) if back else ""
    b_raw = _cell(back[0], 1) if back else ""

    parsed_date = _parse_excel_date(a_raw) if a_raw else ""
    parsed_time = _parse_excel_time(b_raw) if b_raw else ""

    print(json.dumps({
        "insert_response": resp,
        "sheet_id": delivery_sheet_id,
        "insert_at_row": insert_at_1,
        "mode": args.mode,
        "inherit_style": inherit_style,
        "written": {"A": write_row[0], "B": write_row[1]},
        "read_back": {"A": a_raw, "B": b_raw},
        "parsed": {"A_as_date": parsed_date, "B_as_time": parsed_time},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
