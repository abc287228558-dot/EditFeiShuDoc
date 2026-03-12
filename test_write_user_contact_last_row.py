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

    # Values layout: A:P (16 columns). O is locked, so we skip it.
    # We'll write A:N (14 cols) + P (1 col). O left unchanged.
    values_a_n = _pad(
        [
            "2099-12-31",  # 日期
            "TEST_LIVE_ID",
            "13800000000",  # 快手电话
            "TEST_ORDER_20991231",  # 快手订单号
            "测试昵称",  # 快手昵称
            "测试主播",  # 主播
            "测试商品",  # 商品名称
            "1",  # 数量
            "9.99",  # 金额
            "测试备注1",
            "测试备注2",
            "测试备注3",
            "测试备注4",
            "测试备注5",
        ],
        14,
    )
    value_p = [["测试P列"]]

    range_a_n = f"{sheet_id}!A{row}:N{row}"
    range_p = f"{sheet_id}!P{row}:P{row}"

    if args.dry_run:
        print("[dry-run] spreadsheet_token=", spreadsheet_token)
        print("[dry-run] sheet_id=", sheet_id)
        print("[dry-run] detected_last_row=", detected_last_row)
        print("[dry-run] target_row=", row)
        print("[dry-run] range_a_n=", range_a_n)
        print("[dry-run] range_p=", range_p)
        print("[dry-run] values_a_n=", values_a_n)
        print("[dry-run] value_p=", value_p)
        return

    if not bool(args.write):
        return

    resp1 = client.update_values(spreadsheet_token, range_a_n, [values_a_n])
    resp2 = client.update_values(spreadsheet_token, range_p, value_p)

    read_back = client.read_range_values(spreadsheet_token, f"{sheet_id}!A{row}:P{row}")

    print("update A:N response=", resp1)
    print("update P response=", resp2)
    print("read back A:P=", read_back)


if __name__ == "__main__":
    main()
