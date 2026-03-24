import argparse
import json
from typing import Any, Dict, List

from sync_to_feishu import FeishuClient, FeishuConfig


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _pad(values: List[Any], n: int) -> List[Any]:
    out = list(values)
    if len(out) < n:
        out.extend([""] * (n - len(out)))
    return out[:n]


def _detect_last_non_empty_row(
    *,
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    col_letter: str,
    max_rows: int,
) -> int:
    col_letter = str(col_letter or "A").strip().upper() or "A"
    rng = f"{sheet_id}!{col_letter}1:{col_letter}{int(max_rows)}"
    values = client.read_range_values(spreadsheet_token, rng)
    last = 0
    for i, row in enumerate(values or [], 1):
        if not row or len(row) <= 0:
            continue
        v = row[0]
        if v is None:
            continue
        if str(v).strip():
            last = i
    return int(last)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--row", type=int, default=0, help="Target row number to overwrite (1-based). Use 0 to auto-detect last row")
    p.add_argument(
        "--detect-col",
        default="D",
        help="Column letter used to detect last data row (default: D for 快手订单号). Use A if you want to detect by 日期 column.",
    )
    p.add_argument("--max-rows", type=int, default=5000)
    p.add_argument("--write", action="store_true", help="Actually write test data (otherwise only detect + print)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = _load_json(args.config)
    feishu_cfg = cfg.get("feishu") or {}
    target_cfg = cfg.get("target") or {}

    client = FeishuClient(FeishuConfig(feishu_cfg["app_id"], feishu_cfg["app_secret"]))

    spreadsheet_token = client.resolve_spreadsheet_token(
        wiki_url=str(target_cfg.get("wiki_url") or ""),
        spreadsheet_token=str(target_cfg.get("spreadsheet_token") or ""),
    )
    sheet_title = str(target_cfg.get("sheet_title") or "用户对接信息")
    # Some configs store a sheet_id for a different sheet (e.g. 投放信息). Resolve by title first.
    sheet_id_cfg = str(target_cfg.get("sheet_id") or "").strip()
    try:
        sheet_id = client.resolve_sheet_id(
            spreadsheet_token=spreadsheet_token,
            sheet_id="",
            sheet_title=sheet_title,
        )
    except Exception:
        sheet_id = client.resolve_sheet_id(
            spreadsheet_token=spreadsheet_token,
            sheet_id=sheet_id_cfg,
            sheet_title=sheet_title,
        )

    detected_last_row = _detect_last_non_empty_row(
        client=client,
        spreadsheet_token=spreadsheet_token,
        sheet_id=sheet_id,
        col_letter=str(args.detect_col or "A"),
        max_rows=int(args.max_rows),
    )
    print("detected_last_data_row=", detected_last_row)
    print("next_write_row=", int(detected_last_row) + 1)

    row = int(args.row)
    if row <= 0:
        row = int(detected_last_row) + 1

    # Values layout: A:P (16 columns).
    # Requirement: skip G column (主播). We'll write A:F + H(直播账号) + P(备注).
    values_a_f = _pad(
        [
            "2099-12-31",  # 日期
            "TEST_LIVE_ID",
            "13800000000",  # 快手电话
            "TEST_ORDER_20991231",  # 快手订单号
            "测试昵称",  # 快手昵称
            "KSID_123456",  # 快手id
        ],
        6,
    )

    value_h = [["TEST_LIVE_ACCOUNT"]]
    value_p = [["测试备注(新需求)"]]

    range_a_f = f"{sheet_id}!A{row}:F{row}"
    range_h = f"{sheet_id}!H{row}:H{row}"
    range_p = f"{sheet_id}!P{row}:P{row}"

    if args.dry_run:
        print("[dry-run] spreadsheet_token=", spreadsheet_token)
        print("[dry-run] sheet_id=", sheet_id)
        print("[dry-run] detected_last_row=", detected_last_row)
        print("[dry-run] target_row=", row)
        print("[dry-run] range_a_f=", range_a_f)
        print("[dry-run] range_h=", range_h)
        print("[dry-run] range_p=", range_p)
        print("[dry-run] values_a_f=", values_a_f)
        print("[dry-run] value_h=", value_h)
        print("[dry-run] value_p=", value_p)
        return

    if not bool(args.write):
        return

    resp1 = client.update_values(spreadsheet_token, range_a_f, [values_a_f])
    resp2 = client.update_values(spreadsheet_token, range_h, value_h)
    resp3 = client.update_values(spreadsheet_token, range_p, value_p)

    read_back = client.read_range_values(spreadsheet_token, f"{sheet_id}!A{row}:P{row}")

    print("update A:F response=", resp1)
    print("update H response=", resp2)
    print("update P response=", resp3)
    print("read back A:P=", read_back)


if __name__ == "__main__":
    main()
