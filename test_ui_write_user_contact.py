import argparse
import json
from typing import Any, Dict, List

from sync_to_feishu import (
    FeishuClient,
    FeishuConfig,
    TARGET_COLUMNS,
    detect_last_non_empty_row_in_col,
    resolve_dedup_col_index,
    _ui_append_values_on_open_page,
    _ui_open_wiki_session,
)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _pad(values: List[Any], n: int) -> List[Any]:
    out = list(values)
    if len(out) < n:
        out.extend([""] * (n - len(out)))
    return out[:n]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--max-rows", type=int, default=5000)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = _load_json(args.config)
    feishu_cfg = cfg.get("feishu") or {}
    target_cfg = cfg.get("target") or {}

    client = FeishuClient(FeishuConfig(feishu_cfg["app_id"], feishu_cfg["app_secret"]))

    wiki_url = str(target_cfg.get("wiki_url") or "")
    wiki_password = str(target_cfg.get("wiki_password") or "")

    spreadsheet_token = client.resolve_spreadsheet_token(
        wiki_url=wiki_url,
        spreadsheet_token=str(target_cfg.get("spreadsheet_token") or ""),
    )

    sheet_title = str(target_cfg.get("sheet_title") or "用户对接信息")
    sheet_id = client.resolve_sheet_id(
        spreadsheet_token=spreadsheet_token,
        sheet_id="",
        sheet_title=sheet_title,
    )

    dedup_col_index = resolve_dedup_col_index(client, spreadsheet_token, sheet_id, "快手订单号")
    if not dedup_col_index:
        dedup_col_index = TARGET_COLUMNS.index("快手订单号") + 1

    last_data_row = detect_last_non_empty_row_in_col(
        client,
        spreadsheet_token,
        sheet_id,
        int(dedup_col_index),
        max_rows=int(args.max_rows),
    )
    target_row = int(last_data_row) + 1

    # Construct one test row following TARGET_COLUMNS order (A:P).
    # O column is locked in the sheet; UI paste should still place values into A:N and P, leaving O formula.
    test_order = f"UI_TEST_ORDER_{target_row}"
    test_row = _pad(
        [
            "2099-12-31",  # 日期
            "UI_TEST_LIVE_ID",  # 直播ID
            "13800000000",  # 快手电话
            test_order,  # 快手订单号
            "UI测试昵称",  # 快手昵称
            "UI测试主播",  # 主播
            "UI测试商品",  # 商品名称
            "1",  # 数量
            "9.99",  # 金额
            "",  # 备注
            "",  # 备注
            "",  # 备注
            "",  # 备注
            "",  # 备注
            "",  # O 退费金额(locked) - keep empty
            "UI测试P列",  # P
        ],
        16,
    )

    print("spreadsheet_token=", spreadsheet_token)
    print("sheet_id=", sheet_id)
    print("dedup_col_index=", dedup_col_index)
    print("last_data_row=", last_data_row)
    print("target_row=", target_row)
    print("test_order=", test_order)

    if args.dry_run:
        return

    from playwright.sync_api import sync_playwright

    ui_profile_dir = target_cfg.get("ui_fallback_profile_dir", ".state/feishu_profile")
    ui_timeout_ms = int(target_cfg.get("ui_fallback_timeout_ms", 60000))

    with sync_playwright() as p:
        ctx, page = _ui_open_wiki_session(
            p=p,
            wiki_url=wiki_url,
            user_data_dir=ui_profile_dir,
            headless=bool(args.headless),
            timeout_ms=ui_timeout_ms,
            wiki_password=wiki_password,
        )
        try:
            _ui_append_values_on_open_page(
                page=page,
                sheet_title=sheet_title,
                values=[test_row],
                timeout_ms=ui_timeout_ms,
                force_a2=False,
                screenshot_enabled=False,
                paste_between_ms=500,
                paste_apply_wait_ms=2500,
                target_row_number=target_row,
            )
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    # Read back and check if split worked.
    got = client.read_range_values(spreadsheet_token, f"{sheet_id}!A{target_row}:P{target_row}")
    row = got[0] if got else []

    def _cell(i: int) -> str:
        if not isinstance(row, list) or len(row) <= i:
            return ""
        v = row[i]
        if v is None:
            return ""
        return str(v).strip()

    a = _cell(0)
    d = _cell(3)
    b = _cell(1)

    print("read_back_A_P=", got)
    print("check_A=", a)
    print("check_B=", b)
    print("check_D(order)=", d)

    # If paste collapsed into one cell, D would be empty.
    ok = bool(d) and d == test_order
    if not ok:
        raise SystemExit("UI_WRITE_VERIFY_FAILED: D列快手订单号未写入/未分列")

    print("UI_WRITE_VERIFY_OK")


if __name__ == "__main__":
    main()
