import argparse
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import requests


FEISHU_BASE_URL = "https://open.feishu.cn"


def _copy_table_cache_path() -> str:
    return os.path.join(".state", "copy_table_cache.json")


def _load_copy_table_cache() -> Dict[str, Any]:
    p = _copy_table_cache_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        return {}
    except Exception:
        return {}


def _save_copy_table_cache(data: Dict[str, Any]) -> None:
    p = _copy_table_cache_path()
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        return


def _append_copy_table_cache_from_values(values_ui: List[List[Any]]) -> None:
    if not values_ui:
        return
    try:
        idx_nick = TARGET_COLUMNS.index("快手昵称")
        idx_kid = TARGET_COLUMNS.index("快手id")
        idx_anchor = TARGET_COLUMNS.index("主播")
        idx_acct = TARGET_COLUMNS.index("直播账号")
    except Exception:
        return

    cache = _load_copy_table_cache()
    items = cache.get("items")
    if not isinstance(items, list):
        items = []

    existing_keys: Set[str] = set()
    for it in items:
        if isinstance(it, dict):
            k = str(it.get("key") or "")
            if k:
                existing_keys.add(k)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    for row in values_ui:
        if not isinstance(row, list):
            continue
        nick = str(row[idx_nick] if len(row) > idx_nick else "").strip()
        kid = str(row[idx_kid] if len(row) > idx_kid else "").strip()
        anchor = str(row[idx_anchor] if len(row) > idx_anchor else "").strip()
        acct = str(row[idx_acct] if len(row) > idx_acct else "").strip()
        if not (nick or kid or anchor or acct):
            continue
        key = "|".join([nick, kid, anchor, acct])
        if key in existing_keys:
            continue
        items.append(
            {
                "key": key,
                "nickname": nick,
                "kuaishou_id": kid,
                "anchor": anchor,
                "account": acct,
                "copied": False,
                "created_at": now,
            }
        )
        existing_keys.add(key)
        added += 1

    cache["items"] = items
    cache["updated_at"] = now
    _save_copy_table_cache(cache)
    try:
        if added:
            logging.info("copy_table_cache_appended items=%d", added)
    except Exception:
        pass


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _cleanup_keep_latest_files(dir_path: str, *, keep: int, exts: Optional[List[str]] = None, prefix: str = "") -> None:
    if keep < 0:
        return
    if not dir_path or not os.path.isdir(dir_path):
        return
    try:
        items: List[Tuple[float, str]] = []
        for name in os.listdir(dir_path):
            if prefix and not name.startswith(prefix):
                continue
            p = os.path.join(dir_path, name)
            if not os.path.isfile(p):
                continue
            if exts is not None:
                _, ext = os.path.splitext(name)
                if ext.lower() not in {e.lower() for e in exts}:
                    continue
            try:
                st = os.stat(p)
            except Exception:
                continue
            items.append((st.st_mtime, p))

        items.sort(reverse=True)
        # keep == 0 => delete all matched
        start = keep if keep > 0 else 0
        for _, p in items[start:]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        return


def setup_logging() -> str:
    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", f"sync_{_now_ts()}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info("log_file=%s", log_path)
    return log_path


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _load_local_ui_dedup(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_local_ui_dedup(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


@dataclass
class FeishuConfig:
    app_id: str
    app_secret: str


class FeishuClient:
    def __init__(self, cfg: FeishuConfig, timeout_seconds: int = 30):
        self.cfg = cfg
        self.timeout_seconds = timeout_seconds
        self._tenant_token: Optional[str] = None
        self._tenant_token_expire_at: float = 0.0

    def _request(self, method: str, path: str, *, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None, json_body: Any = None) -> Dict[str, Any]:
        url = f"{FEISHU_BASE_URL}{path}"
        h = {"Content-Type": "application/json; charset=utf-8"}
        if headers:
            h.update(headers)
        resp = requests.request(method, url, headers=h, params=params, json=json_body, timeout=self.timeout_seconds)
        try:
            data = resp.json()
        except Exception as e:
            preview = (resp.text or "")[:500]

            raise RuntimeError(
                f"Non-JSON response from {url} (HTTP {resp.status_code}). "
                f"First 500 chars: {preview!r}"
            ) from e

        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} {url}: {data}")
        if isinstance(data, dict) and data.get("code", 0) != 0:
            raise RuntimeError(f"Feishu API error {url}: {data}")
        return data

    def tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_token and now < self._tenant_token_expire_at - 60:
            return self._tenant_token

        data = self._request(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            json_body={"app_id": self.cfg.app_id, "app_secret": self.cfg.app_secret},
        )
        token = data["tenant_access_token"]
        expire = int(data.get("expire", 3600))
        self._tenant_token = token
        self._tenant_token_expire_at = now + expire
        return token

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_access_token()}"}

    def wiki_url_to_node_token(self, wiki_url: str) -> str:
        m = re.search(r"/wiki/([A-Za-z0-9]+)", wiki_url)
        if not m:
            raise ValueError(f"Cannot parse wiki token from url: {wiki_url}")
        return m.group(1)

    def get_wiki_node(self, wiki_node_token: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/open-apis/wiki/v2/spaces/get_node",
            headers=self._auth_headers(),
            params={"token": wiki_node_token},
        )

    def resolve_spreadsheet_token(self, *, wiki_url: str, spreadsheet_token: str) -> str:
        if spreadsheet_token:
            return spreadsheet_token
        wiki_token = self.wiki_url_to_node_token(wiki_url)
        node = self.get_wiki_node(wiki_token)
        data = node.get("data", {})
        node_info = data.get("node", {})
        obj_token = node_info.get("obj_token") or node_info.get("objToken")
        obj_type = node_info.get("obj_type") or node_info.get("objType")
        if not obj_token or not obj_type:
            raise RuntimeError(f"Unexpected wiki node response: {node}")
        if str(obj_type).lower() not in {"sheet", "spreadsheet", "sheets"}:
            raise RuntimeError(f"Wiki node is not a spreadsheet: obj_type={obj_type}, obj_token={obj_token}")
        return obj_token

    def list_sheets(self, spreadsheet_token: str) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            f"/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
            headers=self._auth_headers(),
        )
        return data.get("data", {}).get("sheets", [])

    def resolve_sheet_id(self, *, spreadsheet_token: str, sheet_id: str, sheet_title: str) -> str:
        if sheet_id:
            return sheet_id
        sheets = self.list_sheets(spreadsheet_token)
        for s in sheets:
            if s.get("title") == sheet_title:
                sid = s.get("sheet_id")
                if sid:
                    return sid
        raise RuntimeError(f"Cannot find sheet by title={sheet_title}. Available: {[s.get('title') for s in sheets]}")

    def read_range_values(self, spreadsheet_token: str, range_a1: str) -> List[List[Any]]:
        data = self._request(
            "GET",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_a1}",
            headers=self._auth_headers(),
        )
        return data.get("data", {}).get("valueRange", {}).get("values", [])

    def append_values(self, spreadsheet_token: str, range_a1: str, values: List[List[Any]]) -> Dict[str, Any]:
        params = {"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}
        return self._request(
            "POST",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values_append",
            headers=self._auth_headers(),
            params=params,
            json_body={"valueRange": {"range": range_a1, "values": values}},
        )

    def update_values(self, spreadsheet_token: str, range_a1: str, values: List[List[Any]]) -> Dict[str, Any]:
        params = {"valueInputOption": "USER_ENTERED"}
        return self._request(
            "PUT",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values",
            headers=self._auth_headers(),
            params=params,
            json_body={"valueRange": {"range": range_a1, "values": values}},
        )

    def update_values_raw(self, spreadsheet_token: str, range_a1: str, values: List[List[Any]]) -> Dict[str, Any]:
        """使用 RAW 模式写入数据，不会自动解析数据类型，适合写入纯文本（如长数字字符串）"""
        params = {"valueInputOption": "RAW"}
        return self._request(
            "PUT",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values",
            headers=self._auth_headers(),
            params=params,
            json_body={"valueRange": {"range": range_a1, "values": values}},
        )

    def set_cell_format_text(self, spreadsheet_token: str, range_a1: str) -> Dict[str, Any]:
        """设置单元格格式为纯文本（formatter: @），避免绿色警告"""
        return self._request(
            "PUT",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/style",
            headers=self._auth_headers(),
            json_body={
                "appendStyle": {
                    "range": range_a1,
                    "style": {
                        "formatter": "@"
                    }
                }
            },
        )

    def insert_dimension_range_rows(
        self,
        *,
        spreadsheet_token: str,
        sheet_id: str,
        start_index_0: int,
        end_index_0: int,
        inherit_style: str = "BEFORE",
    ) -> Dict[str, Any]:
        body = {
            "dimension": {
                "sheetId": str(sheet_id),
                "majorDimension": "ROWS",
                "startIndex": int(start_index_0),
                "endIndex": int(end_index_0),
            },
            "inheritStyle": str(inherit_style),
        }
        return self._request(
            "POST",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/insert_dimension_range",
            headers=self._auth_headers(),
            json_body=body,
        )
    
    def set_cell_style(
        self,
        *,
        spreadsheet_token: str,
        sheet_id: str,
        range_a1: str,
        formatter: str,
    ) -> Dict[str, Any]:
        """设置单元格格式
        
        Args:
            spreadsheet_token: 电子表格 token
            sheet_id: 工作表 ID
            range_a1: 单元格范围，如 "B2:B100"（不包含 sheet_id 前缀）
            formatter: 格式类型，如 "yyyy-MM-dd HH:mm" 表示时间格式
        """
        # 飞书 API 需要完整的 range 格式：sheetId!A1:B2
        full_range = f"{sheet_id}!{range_a1}"
        
        body = {
            "appendStyle": {
                "range": full_range,
                "style": {
                    "formatter": formatter
                }
            }
        }
        return self._request(
            "PUT",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/style",
            headers=self._auth_headers(),
            json_body=body,
        )
    
    def set_cell_alignment(
        self,
        *,
        spreadsheet_token: str,
        sheet_id: str,
        range_a1: str,
        h_align: int = 2,
        v_align: int = 2,
    ) -> Dict[str, Any]:
        """设置单元格对齐方式
        
        Args:
            spreadsheet_token: 电子表格 token
            sheet_id: 工作表 ID
            range_a1: 单元格范围，如 "A2:F2"（不包含 sheet_id 前缀）
            h_align: 水平对齐方式，1=左对齐, 2=居中, 3=右对齐
            v_align: 垂直对齐方式，1=上对齐, 2=居中, 3=下对齐
        """
        full_range = f"{sheet_id}!{range_a1}"
        
        body = {
            "appendStyle": {
                "range": full_range,
                "style": {
                    "align": h_align,
                    "valign": v_align
                }
            }
        }
        return self._request(
            "PUT",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/style",
            headers=self._auth_headers(),
            json_body=body,
        )


def _is_feishu_permission_error(exc: Exception) -> bool:
    msg = str(exc)
    if "131006" in msg:
        return True
    if "91403" in msg:
        return True
    if "HTTP 403" in msg:
        return True
    if "forbidden" in msg.lower():
        return True
    if "permission denied" in msg.lower():
        return True
    return False


def _values_to_tsv(values: List[List[Any]]) -> str:
    # Spreadsheet paste format: tab-separated columns, newline-separated rows.
    # Ensure no None.
    lines: List[str] = []
    for row in values:
        cols = []
        for c in row:
            s = "" if c is None else str(c)
            s = s.replace("\r\n", "\n").replace("\r", "\n")
            cols.append(s)
        lines.append("\t".join(cols))
    return "\n".join(lines)


def _ui_append_values_via_wiki(
    *,
    wiki_url: str,
    sheet_title: str = "",
    values: List[List[Any]],
    user_data_dir: str,
    headless: bool,
    timeout_ms: int,
    wiki_password: str = "",
    force_a2: bool = True,
    screenshot_enabled: bool = True,
    paste_between_ms: int = 500,
    paste_apply_wait_ms: int = 2000,
    target_row: int = 0,
) -> None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError(
            "UI fallback requires Playwright. Please install playwright and browsers, or disable ui_fallback."
        ) from e

    wiki_url = (wiki_url or "").strip()
    if not wiki_url:
        raise RuntimeError("UI fallback requires target.wiki_url")

    tsv = _values_to_tsv(values)
    row_count = len(values)
    col_count = max((len(r) for r in values), default=0)
    logging.info("ui_mode_prepare rows=%d cols=%d tsv_chars=%d", row_count, col_count, len(tsv))

    user_data_dir = os.path.abspath(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)

    def _open_wiki_session():
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
        )
        try:
            # Improve reliability of clipboard operations on Feishu domain.
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://vcn13vbsobtc.feishu.cn")
        except Exception:
            pass
        page = ctx.new_page()
        page.goto(wiki_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(800)

        # Some wiki pages are protected by an access password.
        # If so, enter password and confirm before proceeding.
        try:
            pwd_box = page.get_by_placeholder("请输入密码")
            if pwd_box.count() > 0:
                pwd_box.first.wait_for(state="visible", timeout=3000)
                if not wiki_password:
                    if headless:
                        raise RuntimeError(
                            "Wiki page requires password but target.wiki_password is empty. "
                            "Either set target.wiki_password, or run once with ui_fallback_headless=false and enter it manually."
                        )
                    logging.info(
                        "ui_mode_password_required: please enter the wiki password in the opened browser window, then click 确定. "
                        "Waiting for unlock..."
                    )
                    # Wait until the password prompt disappears (user finished unlocking).
                    deadline_unlock = time.time() + max(10.0, timeout_ms / 1000.0)
                    while time.time() < deadline_unlock:
                        try:
                            if pwd_box.first.is_visible():
                                page.wait_for_timeout(500)
                                continue
                        except Exception:
                            pass
                        break
                    page.wait_for_timeout(1200)
                else:
                    pwd_box.first.fill(wiki_password)
                    try:
                        page.get_by_role("button", name="确定").click(timeout=3000)
                    except Exception:
                        # Fallback: press Enter.
                        page.keyboard.press("Enter")
                    page.wait_for_timeout(1200)
        except Exception as e:
            if "requires password" in str(e):
                raise
            # Ignore if password prompt not present.
            pass

        # If not logged in, Feishu usually redirects to a login host.
        if any(k in (page.url or "") for k in ["passport", "login", "accounts", "sso"]):
            raise RuntimeError(
                "Feishu UI fallback detected login page. Please run once with headless=false to complete login, "
                f"then re-run headless. profile_dir={user_data_dir} url={page.url}"
            )
        return ctx, page

    def _append_on_open_page(page):
        st = (sheet_title or "").strip()
        if st:
            clicked = False
            for _sel in [
                lambda: page.get_by_text(st, exact=True).first,
                lambda: page.get_by_role("tab", name=st),
                lambda: page.get_by_text(st).first,
            ]:
                try:
                    _sel().click(timeout=5000)
                    page.wait_for_timeout(800)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                logging.info("ui_mode_sheet_tab_click_failed title=%s", st)

        # Heuristic focus/detection selectors for sheet grid.
        primary_candidates = [
            "canvas",
            "div[role='grid']",
            "div[role='table']",
        ]
        fallback_candidates = [
            # contenteditable is often formula bar; keep it as last resort.
            "div[contenteditable='true']",
        ]

        # Find the frame that actually contains the sheet grid.
        t_detect0 = time.time()
        deadline = time.time() + (timeout_ms / 1000.0)
        sheet_frame = None
        while time.time() < deadline and sheet_frame is None:
            frames_to_try = [fr for fr in page.frames if fr != page.main_frame] + [page.main_frame]
            for fr in frames_to_try:
                for sel in primary_candidates:
                    try:
                        if fr.query_selector(sel) is None:
                            continue
                        sheet_frame = fr
                        break
                    except Exception:
                        continue
                if sheet_frame is not None:
                    break
            if sheet_frame is None:
                page.wait_for_timeout(150)

        if sheet_frame is None:
            deadline2 = time.time() + 5.0
            while time.time() < deadline2 and sheet_frame is None:
                frames_to_try = [fr for fr in page.frames if fr != page.main_frame] + [page.main_frame]
                for fr in frames_to_try:
                    for sel in fallback_candidates:
                        try:
                            if fr.query_selector(sel) is None:
                                continue
                            sheet_frame = fr
                            break
                        except Exception:
                            continue
                    if sheet_frame is not None:
                        break
                if sheet_frame is None:
                    page.wait_for_timeout(150)

        if sheet_frame is None:
            raise RuntimeError("UI fallback cannot find sheet grid in any frame")

        logging.info("ui_mode_grid_detect_ms=%d", int((time.time() - t_detect0) * 1000))

        try:
            logging.info("ui_mode_sheet_frame_url=%s", sheet_frame.url)
        except Exception:
            pass

        focused = False
        last_err: Optional[Exception] = None
        used_selector: str = ""

        try:
            page.mouse.click(120, 260)
        except Exception:
            pass

        t_focus0 = time.time()
        for sel in (primary_candidates + fallback_candidates):
            try:
                loc = sheet_frame.locator(sel).first
                loc.wait_for(state="visible", timeout=1500)
                try:
                    box = loc.bounding_box()
                except Exception:
                    box = None
                if box and box.get("width") and box.get("height"):
                    x = min(max(10.0, box["width"] * 0.08), box["width"] - 10.0)
                    y = min(max(20.0, box["height"] * 0.12), box["height"] - 10.0)
                    loc.click(timeout=8000, force=True, position={"x": x, "y": y})
                else:
                    loc.click(timeout=8000, force=True)
                focused = True
                used_selector = sel
                break
            except Exception as e:
                last_err = e
                continue

        if not focused:
            raise RuntimeError(f"UI fallback cannot focus sheet grid. last_error={last_err}")

        if used_selector:
            logging.info("ui_mode_focus_selector=%s", used_selector)

        logging.info("ui_mode_focus_ms=%d", int((time.time() - t_focus0) * 1000))

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            sheet_frame.locator("canvas").first.click(timeout=3000, force=True)
        except Exception:
            pass

        copied = sheet_frame.evaluate(
            """
            async (tsv) => {
              // Prefer modern clipboard API; fallback to execCommand.
              try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  await navigator.clipboard.writeText(tsv);
                  return true;
                }
              } catch (e) {
                // ignore
              }
              try {
                const ta = document.createElement('textarea');
                ta.value = tsv;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.left = '-10000px';
                ta.style.top = '0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                const ok = document.execCommand('copy');
                document.body.removeChild(ta);
                return !!ok;
              } catch (e) {
                return false;
              }
            }
            """,
            tsv,
        )
        logging.info("ui_mode_clipboard_copied=%s", bool(copied))

        for combo in [
            "Meta+Home",
            "Meta+ArrowUp",
            "Meta+ArrowLeft",
        ]:
            try:
                page.keyboard.press(combo)
            except Exception:
                pass

        if force_a2:
            try:
                page.keyboard.press("ArrowDown")
            except Exception:
                pass
            if paste_start_col != "A":
                try:
                    page.keyboard.press("ArrowRight")
                except Exception:
                    pass
        else:
            # 如果知道目标行号，直接跳转到那一行
            if target_row > 0:
                logging.info("ui_append_goto_row=%d", target_row)
                # 使用名称框跳转到指定行
                try:
                    # 尝试点击名称框
                    inputs = page.locator("input").all()
                    name_box = None
                    for loc in inputs[:30]:
                        try:
                            box = loc.bounding_box()
                            if not box or box["y"] > 240:
                                continue
                            if box["width"] > 160 or box["height"] > 40:
                                continue
                            name_box = loc
                            break
                        except Exception:
                            continue
                    
                    if name_box:
                        name_box.click(timeout=1000)
                        page.wait_for_timeout(100)
                        # 清空名称框
                        page.keyboard.press("Meta+A")
                        page.wait_for_timeout(50)
                        # 输入目标单元格地址
                        page.keyboard.type(f"A{target_row}")
                        page.wait_for_timeout(100)
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(500)
                        logging.info("ui_append_jumped_to_A%d", target_row)
                    else:
                        # 回退到默认位置 A2
                        logging.warning("ui_append_name_box_not_found, goto A2")
                        page.keyboard.press("Meta+Home")
                        page.wait_for_timeout(100)
                        page.keyboard.press("ArrowDown")
                except Exception as e:
                    logging.warning("ui_append_goto_row_failed err=%s, goto A2", e)
                    # 回退到默认位置 A2
                    try:
                        page.keyboard.press("Meta+Home")
                        page.wait_for_timeout(100)
                        page.keyboard.press("ArrowDown")
                    except Exception:
                        pass
            else:
                # 默认跳到 A2
                try:
                    page.keyboard.press("Meta+Home")
                    page.wait_for_timeout(100)
                    page.keyboard.press("ArrowDown")
                except Exception:
                    pass

        paste_attempts = 0
        for _ in range(2):
            paste_attempts += 1
            try:
                page.keyboard.press("Meta+V")
            except Exception:
                page.keyboard.press("Control+V")
            page.wait_for_timeout(max(0, int(paste_between_ms)))
        logging.info("ui_mode_paste_attempts=%d", paste_attempts)

        try:
            page.keyboard.press("Enter")
        except Exception:
            pass

        page.wait_for_timeout(max(0, int(paste_apply_wait_ms)))

        if screenshot_enabled:
            try:
                os.makedirs(os.path.join(".state"), exist_ok=True)
                ss_path = os.path.join(".state", f"feishu_ui_last_{_now_ts()}.png")
                page.screenshot(path=ss_path, full_page=True)
                logging.info("ui_mode_screenshot=%s", ss_path)
            except Exception as e:
                logging.info("ui_mode_screenshot_failed=%s", e)

    with sync_playwright() as p:
        ctx = None
        try:
            ctx, page = _open_wiki_session()
            _append_on_open_page(page)
        finally:
            try:
                if ctx is not None:
                    ctx.close()
            except Exception:
                pass


def _ui_open_wiki_session(
    *,
    p,
    wiki_url: str,
    user_data_dir: str,
    headless: bool,
    timeout_ms: int,
    wiki_password: str = "",
):
    wiki_url = (wiki_url or "").strip()
    if not wiki_url:
        raise RuntimeError("UI requires target.wiki_url")
    user_data_dir = os.path.abspath(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)

    ctx = p.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=headless)
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://vcn13vbsobtc.feishu.cn")
    except Exception:
        pass
    page = ctx.new_page()
    page.goto(wiki_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(800)

    try:
        pwd_box = page.get_by_placeholder("请输入密码")
        if pwd_box.count() > 0:
            pwd_box.first.wait_for(state="visible", timeout=3000)
            if not wiki_password:
                if headless:
                    raise RuntimeError(
                        "Wiki page requires password but target.wiki_password is empty. "
                        "Either set target.wiki_password, or run once with ui_fallback_headless=false and enter it manually."
                    )
                logging.info(
                    "ui_mode_password_required: please enter the wiki password in the opened browser window, then click 确定. "
                    "Waiting for unlock..."
                )
                deadline_unlock = time.time() + max(10.0, timeout_ms / 1000.0)
                while time.time() < deadline_unlock:
                    try:
                        if pwd_box.first.is_visible():
                            page.wait_for_timeout(500)
                            continue
                    except Exception:
                        pass
                    break
                page.wait_for_timeout(1200)
            else:
                pwd_box.first.fill(wiki_password)
                try:
                    page.get_by_role("button", name="确定").click(timeout=3000)
                except Exception:
                    page.keyboard.press("Enter")
                page.wait_for_timeout(1200)
    except Exception as e:
        if "requires password" in str(e):
            raise
        pass

    if any(k in (page.url or "") for k in ["passport", "login", "accounts", "sso"]):
        raise RuntimeError(
            "Feishu UI detected login page. Please run once with headless=false to complete login, "
            f"then re-run headless. profile_dir={user_data_dir} url={page.url}"
        )
    return ctx, page


def _ui_click_sheet_tab(page, sheet_title: str) -> None:
    st = (sheet_title or "").strip()
    if not st:
        return
    clicked = False
    for _sel in [
        lambda: page.get_by_text(st, exact=True).first,
        lambda: page.get_by_role("tab", name=st),
        lambda: page.get_by_text(st).first,
    ]:
        try:
            _sel().click(timeout=6000)
            page.wait_for_timeout(800)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        logging.info("ui_mode_sheet_tab_click_failed title=%s", st)


def _ui_append_values_on_open_page(
    *,
    page,
    sheet_title: str,
    values: List[List[Any]],
    timeout_ms: int,
    force_a2: bool,
    screenshot_enabled: bool,
    paste_between_ms: int,
    paste_apply_wait_ms: int,
    target_row_number: Optional[int] = None,
):
    def _find_name_box():
        # Prefer explicit selector first.
        for loc in [
            page.locator("input[placeholder='A1']").first,
            page.locator("input[aria-label*='名称']").first,
            page.locator("input[aria-label*='Name']").first,
        ]:
            try:
                loc.wait_for(state="visible", timeout=400)
                return loc
            except Exception:
                continue
        try:
            inputs = page.locator("input").all()
        except Exception:
            inputs = []
        for loc in inputs[:30]:
            try:
                loc.wait_for(state="visible", timeout=200)
                box = loc.bounding_box()
                if not box:
                    continue
                if box["y"] > 240:
                    continue
                if box["width"] > 180 or box["height"] > 44:
                    continue
                return loc
            except Exception:
                continue
        return None

    def _goto_cell_via_name_box(cell_ref: str) -> bool:
        nb = _find_name_box()
        if not nb:
            return False
        try:
            nb.click(timeout=1000)
            page.wait_for_timeout(80)
            page.keyboard.press("Meta+A")
            page.keyboard.type(cell_ref)
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            return True
        except Exception:
            return False

    def _refocus_grid() -> None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            sheet_frame.locator("canvas").first.click(timeout=3000, force=True)
            return
        except Exception:
            pass
        try:
            for sel in ["div[role='grid']", "div[role='table']", "div[contenteditable='true']"]:
                try:
                    sheet_frame.locator(sel).first.click(timeout=1500, force=True)
                    break
                except Exception:
                    continue
        except Exception:
            pass

    def _click_canvas_center() -> bool:
        try:
            loc = sheet_frame.locator("canvas").first
            loc.wait_for(state="visible", timeout=1200)
            box = loc.bounding_box()
            if not box:
                loc.click(timeout=3000, force=True)
                return True
            x = max(10.0, float(box.get("width", 0)) * 0.5)
            y = max(10.0, float(box.get("height", 0)) * 0.5)
            loc.click(timeout=3000, force=True, position={"x": x, "y": y})
            return True
        except Exception:
            return False

    st = (sheet_title or "").strip()
    values_to_paste = values
    values_tail_to_paste: Optional[List[List[Any]]] = None
    tail_start_col = ""
    paste_start_col = "A"
    if st == "用户对接信息":
        paste_start_col = "A"
        values_to_paste = [(list(r)[0:14] if isinstance(r, list) and len(r) > 0 else []) for r in (values or [])]
        values_tail_to_paste = [(list(r)[15:16] if isinstance(r, list) and len(r) > 0 else []) for r in (values or [])]
        tail_start_col = "P"

    tsv = _values_to_tsv(values_to_paste)
    row_count = len(values_to_paste)
    col_count = max((len(r) for r in values_to_paste), default=0)
    logging.info("ui_mode_prepare rows=%d cols=%d tsv_chars=%d", row_count, col_count, len(tsv))

    _ui_click_sheet_tab(page, sheet_title)
    try:
        page.wait_for_timeout(300)
    except Exception:
        pass

    primary_candidates = [
        "canvas",
        "div[role='grid']",
        "div[role='table']",
    ]
    fallback_candidates = [
        "div[contenteditable='true']",
    ]
    if st == "用户对接信息":
        # For this sheet we must paste into the real grid/canvas. If we fall back to a contenteditable,
        # TSV will collapse into one cell (A column).
        # Keep grid/table as primary options because some layouts don't expose a usable canvas locator.
        fallback_candidates = ["div[contenteditable='true']"]

    def _measure_first(el_frame, css: str) -> Optional[Dict[str, float]]:
        try:
            return el_frame.evaluate(
                """
                (sel) => {
                  try {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return { w: r.width || 0, h: r.height || 0 };
                  } catch (e) {
                    return null;
                  }
                }
                """,
                css,
            )
        except Exception:
            return None

    t_detect0 = time.time()
    deadline = time.time() + max(6.0, (timeout_ms / 1000.0))
    sheet_frame = None
    debug_frame_urls: List[str] = []
    debug_probe: Dict[str, Any] = {}
    while time.time() < deadline and sheet_frame is None:
        frames_to_try = [fr for fr in page.frames if fr != page.main_frame] + [page.main_frame]
        for fr in frames_to_try:
            try:
                if len(debug_frame_urls) < 8:
                    debug_frame_urls.append(str(getattr(fr, "url", "")))
            except Exception:
                pass
            for sel in primary_candidates:
                try:
                    sz = _measure_first(fr, sel)
                    if not sz:
                        continue
                    if float(sz.get("w", 0)) < 220 or float(sz.get("h", 0)) < 160:
                        continue
                    sheet_frame = fr
                    break
                except Exception:
                    continue
            if sheet_frame is not None:
                break
        if sheet_frame is None:
            page.wait_for_timeout(150)

    if sheet_frame is None:
        deadline2 = time.time() + 15.0
        while time.time() < deadline2 and sheet_frame is None:
            frames_to_try = [fr for fr in page.frames if fr != page.main_frame] + [page.main_frame]
            for fr in frames_to_try:
                for sel in fallback_candidates:
                    try:
                        sz = _measure_first(fr, sel)
                        if not sz:
                            continue
                        if float(sz.get("w", 0)) < 120 or float(sz.get("h", 0)) < 30:
                            continue
                        sheet_frame = fr
                        break
                    except Exception:
                        continue
                if sheet_frame is not None:
                    break
            if sheet_frame is None:
                page.wait_for_timeout(150)

    if sheet_frame is None:
        # Diagnostics to help identify why detection failed.
        try:
            frames_to_try = [fr for fr in page.frames if fr != page.main_frame] + [page.main_frame]
            for sel in (primary_candidates + fallback_candidates):
                best = None
                for fr in frames_to_try:
                    sz = _measure_first(fr, sel)
                    if not sz:
                        continue
                    if best is None or (float(sz.get("w", 0)) * float(sz.get("h", 0))) > (float(best.get("w", 0)) * float(best.get("h", 0))):
                        best = sz
                if best is not None:
                    debug_probe[sel] = best
        except Exception:
            pass
        raise RuntimeError(f"UI fallback cannot find sheet grid in any frame. frames_sample={debug_frame_urls} probe={debug_probe}")

    logging.info("ui_mode_grid_detect_ms=%d", int((time.time() - t_detect0) * 1000))
    try:
        logging.info("ui_mode_sheet_frame_url=%s", sheet_frame.url)
    except Exception:
        pass

    try:
        page.mouse.click(120, 260)
    except Exception:
        pass

    focused = False
    last_err: Optional[Exception] = None
    used_selector: str = ""

    t_focus0 = time.time()
    for sel in (primary_candidates + fallback_candidates):
        try:
            loc = sheet_frame.locator(sel).first
            loc.wait_for(state="visible", timeout=1500)
            try:
                box = loc.bounding_box()
            except Exception:
                box = None
            if box and box.get("width") and box.get("height"):
                x = min(max(10.0, box["width"] * 0.08), box["width"] - 10.0)
                y = min(max(20.0, box["height"] * 0.12), box["height"] - 10.0)
                loc.click(timeout=8000, force=True, position={"x": x, "y": y})
            else:
                loc.click(timeout=8000, force=True)
            focused = True
            used_selector = sel
            break
        except Exception as e:
            last_err = e
            continue

    if not focused:
        raise RuntimeError(f"UI fallback cannot focus sheet grid. last_error={last_err}")

    if used_selector:
        logging.info("ui_mode_focus_selector=%s", used_selector)
        if used_selector == "div[contenteditable='true']":
            logging.warning("ui_mode_focus_used_contenteditable, may cause paste_not_split")
            if st == "用户对接信息":
                raise RuntimeError("UI focus landed on contenteditable; aborting to avoid paste_not_split")
    logging.info("ui_mode_focus_ms=%d", int((time.time() - t_focus0) * 1000))

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        sheet_frame.locator("canvas").first.click(timeout=3000, force=True)
    except Exception:
        pass

    copied = sheet_frame.evaluate(
        """
        async (tsv) => {
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(tsv);
              return true;
            }
          } catch (e) {}
          try {
            const ta = document.createElement('textarea');
            ta.value = tsv;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.left = '-10000px';
            ta.style.top = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return !!ok;
          } catch (e) {
            return false;
          }
        }
        """,
        tsv,
    )
    logging.info("ui_mode_clipboard_copied=%s", bool(copied))

    for combo in ["Meta+Home", "Meta+ArrowUp", "Meta+ArrowLeft"]:
        try:
            page.keyboard.press(combo)
        except Exception:
            pass

    # Prefer jumping via name box to the exact paste start cell.
    # If we cannot compute target_row_number, fall back to bottom navigation
    # (avoid pasting into protected header/top rows).
    effective_row: Optional[int] = None
    if force_a2:
        effective_row = 2
        cell_address = f"{paste_start_col}{effective_row}"
        logging.info("ui_mode_jump_to_cell=%s", cell_address)
        jumped = _goto_cell_via_name_box(cell_address)
        if jumped:
            logging.info("ui_mode_jump_success")
        else:
            logging.warning("ui_mode_name_box_not_found, fallback to keyboard navigation")
            try:
                page.keyboard.press("Meta+Home")
            except Exception:
                pass
            try:
                page.keyboard.press("ArrowDown")
            except Exception:
                pass
            if paste_start_col != "A":
                try:
                    page.keyboard.press("ArrowRight")
                except Exception:
                    pass
    elif target_row_number is not None:
        effective_row = int(target_row_number)
        cell_address = f"{paste_start_col}{effective_row}"
        logging.info("ui_mode_jump_to_cell=%s", cell_address)
        jumped = _goto_cell_via_name_box(cell_address)
        if jumped:
            logging.info("ui_mode_jump_success")
            _refocus_grid()
            _click_canvas_center()
        else:
            logging.warning("ui_mode_jump_failed, fallback to bottom navigation")
            target_row_number = None

    if (not force_a2) and (target_row_number is None):
        # Fallback: go to bottom (Control/Meta+End), then to first column, then down one row.
        try:
            page.keyboard.press("Control+End")
        except Exception:
            try:
                page.keyboard.press("Meta+End")
            except Exception:
                pass
        try:
            page.keyboard.press("Home")
        except Exception:
            try:
                page.keyboard.press("Meta+ArrowLeft")
            except Exception:
                pass
        try:
            page.keyboard.press("ArrowDown")
        except Exception:
            pass
        if paste_start_col != "A":
            try:
                page.keyboard.press("ArrowRight")
            except Exception:
                pass

    paste_attempts = 0
    for _ in range(2):
        paste_attempts += 1
        if paste_attempts == 1:
            _refocus_grid()
            _click_canvas_center()
        try:
            page.keyboard.press("Meta+V")
        except Exception:
            page.keyboard.press("Control+V")
        page.wait_for_timeout(max(0, int(paste_between_ms)))
    logging.info("ui_mode_paste_attempts=%d", paste_attempts)

    try:
        page.keyboard.press("Enter")
    except Exception:
        pass
    page.wait_for_timeout(max(0, int(paste_apply_wait_ms)))

    if values_tail_to_paste is not None and tail_start_col and effective_row is not None:
        try:
            tail_tsv = _values_to_tsv(values_tail_to_paste)
            try:
                copied2 = sheet_frame.evaluate(
                    """
                    async (tsv) => {
                      try {
                        if (navigator.clipboard && navigator.clipboard.writeText) {
                          await navigator.clipboard.writeText(tsv);
                          return true;
                        }
                      } catch (e) {}
                      try {
                        const ta = document.createElement('textarea');
                        ta.value = tsv;
                        ta.setAttribute('readonly', '');
                        ta.style.position = 'fixed';
                        ta.style.left = '-10000px';
                        ta.style.top = '0';
                        document.body.appendChild(ta);
                        ta.focus();
                        ta.select();
                        const ok = document.execCommand('copy');
                        document.body.removeChild(ta);
                        return !!ok;
                      } catch (e) {
                        return false;
                      }
                    }
                    """,
                    tail_tsv,
                )
                logging.info("ui_mode_clipboard_copied_tail=%s", bool(copied2))
            except Exception:
                logging.info("ui_mode_clipboard_copied_tail=%s", False)

            cell2 = f"{tail_start_col}{int(effective_row)}"
            logging.info("ui_mode_jump_to_cell_tail=%s", cell2)
            _goto_cell_via_name_box(cell2)
            page.wait_for_timeout(200)
            _refocus_grid()
            _click_canvas_center()
            try:
                page.keyboard.press("Meta+V")
            except Exception:
                page.keyboard.press("Control+V")
            page.wait_for_timeout(max(0, int(paste_between_ms)))
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(max(0, int(paste_apply_wait_ms)))
        except Exception:
            pass

    # Detect protected-range dialog and fail fast.
    try:
        dlg = page.get_by_text("无法编辑")
        has_dlg = False
        try:
            has_dlg = dlg.count() > 0
        except Exception:
            has_dlg = False
        if has_dlg:
            ss_path = ""
            if screenshot_enabled:
                try:
                    os.makedirs(os.path.join(".state"), exist_ok=True)
                    ss_path = os.path.join(".state", f"feishu_ui_protected_{_now_ts()}.png")
                    page.screenshot(path=ss_path, full_page=True)
                except Exception:
                    ss_path = ""
            raise RuntimeError(f"UI append failed: protected range dialog shown. screenshot={ss_path}")
    except RuntimeError:
        raise
    except Exception:
        # Ignore detection errors.
        pass

    if screenshot_enabled:
        try:
            os.makedirs(os.path.join(".state"), exist_ok=True)
            ss_path = os.path.join(".state", f"feishu_ui_last_{_now_ts()}.png")
            page.screenshot(path=ss_path, full_page=True)
            logging.info("ui_mode_screenshot=%s", ss_path)
        except Exception as e:
            logging.info("ui_mode_screenshot_failed=%s", e)


def _ui_upsert_delivery_row_via_wiki(
    *,
    wiki_url: str,
    delivery_sheet_query_id: str = "",
    delivery_sheet_title: str,
    values_row: List[Any],
    target_row_1: int,
    insert_above_row_1: int = 0,
    expected_summary_row_1: int = 0,
    user_data_dir: str,
    headless: bool,
    timeout_ms: int,
    wiki_password: str = "",
    screenshot_enabled: bool = True,
    page=None,
    client: Optional[FeishuClient] = None,
    spreadsheet_token: str = "",
) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("UI delivery sheet upsert requires Playwright") from e

    wiki_url = (wiki_url or "").strip()
    if not wiki_url:
        raise RuntimeError("UI delivery sheet upsert requires target.wiki_url")

    if not isinstance(values_row, list) or not values_row:
        raise RuntimeError("values_row empty")
    # Pad to 16 columns (A:P)
    row = ["" if v is None else str(v) for v in values_row]
    while len(row) < 16:
        row.append("")
    row = row[:16]
    row_left = row[:6]
    row_right = row[7:16]
    tsv_left = "\t".join(row_left)
    tsv_right = "\t".join(row_right)

    def _copy_tsv(sheet_frame, tsv: str) -> bool:
        try:
            copied = sheet_frame.evaluate(
                """
                async (tsv) => {
                  try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                      await navigator.clipboard.writeText(tsv);
                      return true;
                    }
                  } catch (e) {}
                  try {
                    const ta = document.createElement('textarea');
                    ta.value = tsv;
                    ta.setAttribute('readonly', '');
                    ta.style.position = 'fixed';
                    ta.style.left = '-10000px';
                    ta.style.top = '0';
                    document.body.appendChild(ta);
                    ta.focus();
                    ta.select();
                    const ok = document.execCommand('copy');
                    document.body.removeChild(ta);
                    return !!ok;
                  } catch (e) {
                    return false;
                  }
                }
                """,
                tsv,
            )
            return bool(copied)
        except Exception:
            return False

    user_data_dir = os.path.abspath(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)

    def _try_click_sheet_tab(page) -> None:
        st = (delivery_sheet_title or "").strip()
        if not st:
            return
        for _sel in [
            lambda: page.get_by_text(st, exact=True).first,
            lambda: page.get_by_role("tab", name=st),
            lambda: page.get_by_text(st).first,
        ]:
            try:
                _sel().click(timeout=6000)
                page.wait_for_timeout(800)
                return
            except Exception:
                continue
        raise RuntimeError(f"Cannot click sheet tab: {st}")

    def _read_name_box_cell_ref(page) -> str:
        try:
            inputs = page.locator("input").all()
        except Exception:
            inputs = []
        for loc in inputs[:30]:
            try:
                box = loc.bounding_box()
                if not box:
                    continue
                if box["y"] > 240:
                    continue
                if box["width"] > 160 or box["height"] > 40:
                    continue
                v = ""
                try:
                    v = (loc.input_value() or "").strip()
                except Exception:
                    v = ""
                if v and re.fullmatch(r"[A-Z]{1,3}\d{1,6}", v):
                    return v
            except Exception:
                continue
        return ""

    def _ui_find_summary_row_1(page) -> int:
        return _ui_find_row_1_by_text(page, "汇总")

    def _ui_find_row_1_by_text(page, text: str) -> int:
        t = str(text or "").strip()
        if not t:
            return 0
        # Use in-page find to jump to the cell containing text, then parse the name-box ref.
        try:
            page.keyboard.press("Meta+F")
            page.wait_for_timeout(120)
            page.keyboard.type(t)
            page.wait_for_timeout(120)
            page.keyboard.press("Enter")
            page.wait_for_timeout(450)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        except Exception:
            return 0
        ref = _read_name_box_cell_ref(page)
        m = re.search(r"(\d{1,6})$", ref)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except Exception:
            return 0

    def _ui_click_row_header(page, sheet_frame, row_1: int) -> bool:
        # Click the left-side row number to select the whole row.
        # Feishu DOM can vary, so we use heuristics:
        # - match exact row number text
        # - pick elements near the left edge
        rn = str(int(row_1))
        candidates = []
        try:
            loc = sheet_frame.locator(f"text=\"{rn}\"")
            cnt = loc.count()
            for i in range(min(cnt, 40)):
                candidates.append(loc.nth(i))
        except Exception:
            candidates = []

        best = None
        best_score = None
        for cand in candidates:
            try:
                box = cand.bounding_box()
                if not box:
                    continue
                # Skip headers/toolbars.
                if box.get("y", 0) < 180:
                    continue
                # Prefer the left gutter where row numbers live.
                score = float(box.get("x", 9999)) + (0.01 * float(box.get("y", 0)))
                if best is None or (best_score is not None and score < best_score):
                    best = cand
                    best_score = score
            except Exception:
                continue

        if best is None:
            return False
        try:
            best.click(timeout=1500, force=True)
            page.wait_for_timeout(120)
            return True
        except Exception:
            return False

    def _ui_shift_summary_row_down_one(page, sheet_frame) -> int:
        # Move the 汇总 row down by 1 via cut/paste to create a blank row above it.
        # Returns the newly created blank row index (old summary row).
        srow_before = _ui_find_summary_row_1(page)
        if srow_before <= 1:
            return 0

        # Select summary row.
        _goto_cell(page, f"A{int(srow_before)}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        if not _ui_click_row_header(page, sheet_frame, int(srow_before)):
            try:
                page.keyboard.press("Shift+Space")
            except Exception:
                pass

        # Cut row.
        cut_ok = False
        for combo in ["Meta+X", "Control+X"]:
            try:
                page.keyboard.press(combo)
                page.wait_for_timeout(250)
                cut_ok = True
                break
            except Exception:
                continue
        if not cut_ok:
            return 0

        # Paste to next row (A{srow_before+1}).
        _goto_cell(page, f"A{int(srow_before) + 1}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        if not _ui_click_row_header(page, sheet_frame, int(srow_before) + 1):
            try:
                page.keyboard.press("Shift+Space")
            except Exception:
                pass

        paste_ok = False
        for combo in ["Meta+V", "Control+V"]:
            try:
                page.keyboard.press(combo)
                page.wait_for_timeout(600)
                paste_ok = True
                break
            except Exception:
                continue
        if not paste_ok:
            return 0

        # Verify summary moved down.
        srow_after = _ui_find_summary_row_1(page)
        if srow_after <= srow_before:
            return 0
        return int(srow_before)

    def _detect_sheet_frame(page):
        primary_candidates = ["canvas", "div[role='grid']", "div[role='table']"]
        deadline = time.time() + (timeout_ms / 1000.0)
        sheet_frame = None
        while time.time() < deadline and sheet_frame is None:
            frames_to_try = [fr for fr in page.frames if fr != page.main_frame] + [page.main_frame]
            for fr in frames_to_try:
                for sel in primary_candidates:
                    try:
                        if fr.query_selector(sel) is None:
                            continue
                        sheet_frame = fr
                        break
                    except Exception:
                        continue
                if sheet_frame is not None:
                    break
            if sheet_frame is None:
                page.wait_for_timeout(150)
        if sheet_frame is None:
            raise RuntimeError("UI delivery upsert cannot find sheet grid in any frame")
        return sheet_frame

    def _focus_grid(page, sheet_frame) -> None:
        try:
            page.mouse.click(120, 260)
        except Exception:
            pass
        last_err: Optional[Exception] = None
        for sel in ["canvas", "div[role='grid']", "div[role='table']", "div[contenteditable='true']"]:
            try:
                loc = sheet_frame.locator(sel).first
                loc.wait_for(state="visible", timeout=2000)
                box = None
                try:
                    box = loc.bounding_box()
                except Exception:
                    box = None
                if box and box.get("width") and box.get("height"):
                    x = min(max(10.0, box["width"] * 0.08), box["width"] - 10.0)
                    y = min(max(20.0, box["height"] * 0.12), box["height"] - 10.0)
                    loc.click(timeout=8000, force=True, position={"x": x, "y": y})
                else:
                    loc.click(timeout=8000, force=True)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"UI delivery upsert cannot focus grid. last_error={last_err}")

    def _goto_cell(page, cell_ref: str) -> None:
        # Prefer name box navigation (more reliable than Meta+G across Feishu variants).
        last_err: Optional[Exception] = None
        # Try common name-box selectors first.
        for loc in [
            page.locator("input[placeholder='A1']").first,
            page.locator("input[aria-label*='名称']").first,
            page.locator("input[aria-label*='Name']").first,
        ]:
            try:
                loc.wait_for(state="visible", timeout=400)
                loc.click(timeout=800, force=True)
                loc.fill(cell_ref)
                loc.press("Enter")
                page.wait_for_timeout(350)
                return
            except Exception as e:
                last_err = e

        try:
            inputs = page.locator("input").all()
        except Exception:
            inputs = []
        for loc in inputs[:30]:
            try:
                loc.wait_for(state="visible", timeout=200)
                box = loc.bounding_box()
                if not box:
                    continue
                # Name box is usually small and on the top bar.
                if box["y"] > 240:
                    continue
                if box["width"] > 160 or box["height"] > 40:
                    continue
                val = ""
                try:
                    val = (loc.input_value() or "").strip()
                except Exception:
                    val = ""
                if val and (not re.fullmatch(r"[A-Z]{1,3}\d{1,6}", val)):
                    continue
                loc.click(timeout=800, force=True)
                loc.fill(cell_ref)
                loc.press("Enter")
                page.wait_for_timeout(350)
                return
            except Exception as e:
                last_err = last_err or e
        raise RuntimeError(f"cannot goto cell {cell_ref}. last_err={last_err}")

    def _click_target_cell_a(page, sheet_frame, row_1: int) -> None:
        # Ensure the active cell is exactly A{row}. Avoid clicking arbitrary canvas coordinates
        # because it can change the row/column, causing shifted paste.
        try:
            _goto_cell(page, f"A{int(row_1)}")
        except Exception:
            pass
        for key in ["Escape", "Enter"]:
            try:
                page.keyboard.press(key)
            except Exception:
                pass
        page.wait_for_timeout(120)

    own_ctx = False
    ctx = None
    if page is None:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=headless)
            own_ctx = True
            try:
                try:
                    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://vcn13vbsobtc.feishu.cn")
                except Exception:
                    pass

                page = ctx.new_page()
                page.goto(wiki_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(900)

                # Password prompt (same handling as append)
                try:
                    pwd_box = page.get_by_placeholder("请输入密码")
                    if pwd_box.count() > 0:
                        pwd_box.first.wait_for(state="visible", timeout=3000)
                        if wiki_password:
                            pwd_box.first.fill(wiki_password)
                            try:
                                page.get_by_role("button", name="确定").click(timeout=3000)
                            except Exception:
                                page.keyboard.press("Enter")
                            page.wait_for_timeout(1200)
                except Exception:
                    pass

                if any(k in (page.url or "") for k in ["passport", "login", "accounts", "sso"]):
                    raise RuntimeError(
                        "Feishu UI delivery upsert detected login page. Please login once with headless=false. "
                        f"profile_dir={user_data_dir} url={page.url}"
                    )

                _try_click_sheet_tab(page)

                sheet_frame = _detect_sheet_frame(page)
                _focus_grid(page, sheet_frame)

                # When we insert a row above 汇总, the summary row shifts down by 1.
                expected_summary_after_1 = int(expected_summary_row_1 or 0)

                # Insert a blank row above 汇总 when requested.
                # Only use keyboard shortcuts (no context menus).
                if insert_above_row_1 is not None and int(insert_above_row_1) != 0:
                    insert_at = int(insert_above_row_1)
                    if int(expected_summary_row_1) > 0:
                        insert_at = int(expected_summary_row_1)
                    if insert_at <= 0:
                        srow = _ui_find_summary_row_1(page)
                        if srow <= 1:
                            raise RuntimeError("Cannot locate 汇总 row in UI for insertion")
                        insert_at = int(srow)

                    summary_before = 0
                    try:
                        summary_before = _ui_find_summary_row_1(page)
                    except Exception:
                        summary_before = 0

                    _click_target_cell_a(page, sheet_frame, int(insert_at))
                    if not _ui_click_row_header(page, sheet_frame, int(insert_at)):
                        try:
                            page.keyboard.press("Shift+Space")
                        except Exception:
                            pass

                    inserted = False
                    for combo in ["Control+Shift+=", "Meta+Shift+="]:
                        try:
                            page.keyboard.press(combo)
                            page.wait_for_timeout(800)
                            inserted = True
                            break
                        except Exception:
                            pass
                    if not inserted:
                        freed = _ui_shift_summary_row_down_one(page, sheet_frame)
                        if freed <= 0:
                            raise RuntimeError(
                                "Cannot insert a blank row above 汇总 via keyboard shortcut, and cannot shift 汇总 down. "
                                "Please add a few blank rows above 汇总 manually, or grant OpenAPI write permissions."
                            )
                        target_row_1 = int(freed)
                        insert_above_row_1 = 0
                        inserted = True

                    summary_after = _ui_find_summary_row_1(page)
                    if summary_before > 0 and summary_after > 0 and summary_after <= summary_before:
                        freed = _ui_shift_summary_row_down_one(page, sheet_frame)
                        if freed <= 0:
                            raise RuntimeError(
                                "Tried to insert a blank row above 汇总, but 汇总 row index did not move, and cannot shift 汇总 down. "
                                "Abort to avoid writing into 汇总 or below it. Please add blank rows above 汇总 manually."
                            )
                        target_row_1 = int(freed)
                        insert_above_row_1 = 0
                        summary_after = _ui_find_summary_row_1(page)

                    if int(expected_summary_row_1) > 0:
                        if int(target_row_1) <= 0:
                            # The inserted blank row is exactly insert_at (old summary row).
                            target_row_1 = max(2, int(insert_at))
                            expected_summary_after_1 = int(insert_at) + 1
                    else:
                        if summary_after > 1:
                            if int(target_row_1) <= 0:
                                target_row_1 = max(2, int(summary_after) - 1)
                        else:
                            if int(target_row_1) <= 0:
                                target_row_1 = max(2, int(insert_at) - 1)

                if int(target_row_1) <= 0:
                    srow = _ui_find_summary_row_1(page)
                    if srow > 1:
                        target_row_1 = max(2, int(srow) - 1)
                    else:
                        raise RuntimeError("Cannot locate 汇总 row in UI")

                if int(expected_summary_row_1) > 0:
                    srow_now = int(expected_summary_after_1 or expected_summary_row_1)
                else:
                    srow_now = _ui_find_summary_row_1(page)
                if srow_now <= 1:
                    raise RuntimeError("Cannot locate 汇总 row in UI (safety)")
                if int(target_row_1) >= int(srow_now):
                    target_row_1 = max(2, int(srow_now) - 1)

                _goto_cell(page, f"A{int(target_row_1)}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

                ref = _read_name_box_cell_ref(page)
                want = f"A{int(target_row_1)}"
                if not ref:
                    raise RuntimeError("Cannot read name-box cell ref (safety)")
                if ref.strip().upper() != want:
                    raise RuntimeError(f"Refuse to paste: active cell drifted to {ref!r}, want {want!r}")

                copied = _copy_tsv(sheet_frame, tsv_left)
                if not copied:
                    raise RuntimeError("UI delivery clipboard copy failed")

                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                _goto_cell(page, f"A{int(target_row_1)}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                try:
                    page.keyboard.press("Meta+V")
                except Exception:
                    page.keyboard.press("Control+V")
                page.wait_for_timeout(600)
                try:
                    page.keyboard.press("Enter")
                except Exception:
                    pass
                page.wait_for_timeout(900)

                copied2 = _copy_tsv(sheet_frame, tsv_right)
                if not copied2:
                    raise RuntimeError("UI delivery clipboard copy failed")
                _goto_cell(page, f"H{int(target_row_1)}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                try:
                    page.keyboard.press("Meta+V")
                except Exception:
                    page.keyboard.press("Control+V")
                page.wait_for_timeout(600)
                try:
                    page.keyboard.press("Enter")
                except Exception:
                    pass
                page.wait_for_timeout(1200)

                try:
                    srow_after = _ui_find_summary_row_1(page)
                except Exception:
                    srow_after = 0
                if int(expected_summary_row_1) > 0:
                    srow_after = int(expected_summary_after_1 or expected_summary_row_1)
                else:
                    # Meta+F based detection can occasionally land in a non-grid context and return A2.
                    # Treat very small values as unreliable and fallback to the pre-paste summary row.
                    if int(srow_after) <= 2:
                        srow_after = int(srow_now)
                
                logging.info("ui_delivery_post_check target_row=%d summary_row_after=%d", int(target_row_1), int(srow_after))
                
                if srow_after <= 0:
                    raise RuntimeError("Post-check failed: cannot find 汇总 after paste (可能被覆盖)")
                
                # 安全检查：确保没有写入汇总行或汇总行之后
                # 允许 target_row_1 = summary_row - 1（即写入汇总行的前一行）
                if int(target_row_1) >= int(srow_after):
                    raise RuntimeError(
                        f"Post-check failed: target row {int(target_row_1)} >= 汇总 row {int(srow_after)}, possible overwrite"
                    )

                if screenshot_enabled:
                    try:
                        os.makedirs(os.path.join(".state"), exist_ok=True)
                        ss_path = os.path.join(".state", f"feishu_delivery_ui_last_{_now_ts()}.png")
                        page.screenshot(path=ss_path, full_page=True)
                        logging.info("ui_delivery_screenshot=%s", ss_path)
                    except Exception as e:
                        logging.info("ui_delivery_screenshot_failed=%s", e)
                
                # 设置单元格居中对齐（使用 OpenAPI）
                if client and spreadsheet_token and delivery_sheet_query_id:
                    try:
                        # 设置 A-F 列居中对齐
                        client.set_cell_alignment(
                            spreadsheet_token=spreadsheet_token,
                            sheet_id=delivery_sheet_query_id,
                            range_a1=f"A{int(target_row_1)}:F{int(target_row_1)}",
                            h_align=2,  # 2=居中
                            v_align=2,  # 2=居中
                        )
                        # 设置 H 列居中对齐
                        client.set_cell_alignment(
                            spreadsheet_token=spreadsheet_token,
                            sheet_id=delivery_sheet_query_id,
                            range_a1=f"H{int(target_row_1)}:H{int(target_row_1)}",
                            h_align=2,  # 2=居中
                            v_align=2,  # 2=居中
                        )
                        logging.info("ui_delivery_alignment_set row=%d", int(target_row_1))
                    except Exception as e:
                        logging.warning("ui_delivery_alignment_failed row=%d err=%s", int(target_row_1), e)
            finally:
                try:
                    if ctx is not None:
                        ctx.close()
                except Exception:
                    pass
        return

    # Reuse an existing open page/session.
    try:
        _try_click_sheet_tab(page)
        if any(k in (page.url or "") for k in ["passport", "login", "accounts", "sso"]):
            raise RuntimeError(
                "Feishu UI delivery upsert detected login page. Please login once with headless=false. "
                f"profile_dir={user_data_dir} url={page.url}"
            )

        sheet_frame = _detect_sheet_frame(page)
        _focus_grid(page, sheet_frame)

        expected_summary_after_1 = int(expected_summary_row_1 or 0)

        if insert_above_row_1 is not None and int(insert_above_row_1) != 0:
            insert_at = int(insert_above_row_1)
            if int(expected_summary_row_1) > 0:
                insert_at = int(expected_summary_row_1)
            if insert_at <= 0:
                srow = _ui_find_summary_row_1(page)
                if srow <= 1:
                    raise RuntimeError("Cannot locate 汇总 row in UI")
                insert_at = int(srow)

            summary_before = _ui_find_summary_row_1(page)
            inserted = False
            try:
                if not _ui_click_row_header(page, sheet_frame, insert_at):
                    raise RuntimeError(f"Cannot click row header for insert_at={insert_at}")
                page.wait_for_timeout(180)
                for combo in ["Control+Shift+=", "Meta+Shift+="]:
                    try:
                        page.keyboard.press(combo)
                        inserted = True
                        break
                    except Exception:
                        continue
                page.wait_for_timeout(800)
            except Exception:
                inserted = False

            summary_after = _ui_find_summary_row_1(page)
            if (not inserted) or (summary_before > 0 and summary_after == summary_before):
                freed = _ui_shift_summary_row_down_one(page, sheet_frame)
                if freed <= 0:
                    raise RuntimeError(
                        "Cannot insert a blank row above 汇总 via keyboard shortcut, and cannot shift 汇总 down. "
                        "Please add a few blank rows above 汇总 manually, or grant OpenAPI write permissions."
                    )
                target_row_1 = int(freed)
                insert_above_row_1 = 0
                summary_after = _ui_find_summary_row_1(page)

            if summary_after > 1:
                if int(target_row_1) <= 0:
                    if int(expected_summary_row_1) > 0:
                        target_row_1 = max(2, int(insert_at))
                        expected_summary_after_1 = int(insert_at) + 1
                    else:
                        target_row_1 = max(2, int(summary_after) - 1)
            else:
                if int(target_row_1) <= 0:
                    target_row_1 = max(2, int(insert_at) - 1)

        if int(target_row_1) <= 0:
            srow = _ui_find_summary_row_1(page)
            if srow > 1:
                target_row_1 = max(2, int(srow) - 1)
            else:
                raise RuntimeError("Cannot locate 汇总 row in UI")

        if int(expected_summary_row_1) > 0:
            srow_now = int(expected_summary_after_1 or expected_summary_row_1)
        else:
            srow_now = _ui_find_summary_row_1(page)
        if srow_now <= 1:
            raise RuntimeError("Cannot locate 汇总 row in UI (safety)")
        if int(target_row_1) >= int(srow_now):
            target_row_1 = max(2, int(srow_now) - 1)

        _goto_cell(page, f"A{int(target_row_1)}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        try:
            ref = _read_name_box_cell_ref(page)
            want = f"A{int(target_row_1)}"
            if not ref:
                raise RuntimeError("Cannot read name-box cell ref (safety)")
            if ref.strip().upper() != want:
                raise RuntimeError(f"Safety check failed: name-box={ref!r} want={want!r}")
        except Exception:
            raise

        copied = _copy_tsv(sheet_frame, tsv_left)
        if not copied:
            raise RuntimeError("UI delivery clipboard copy failed")

        try:
            page.keyboard.press("Meta+V")
        except Exception:
            page.keyboard.press("Control+V")
        page.wait_for_timeout(600)
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass
        page.wait_for_timeout(900)

        copied2 = _copy_tsv(sheet_frame, tsv_right)
        if not copied2:
            raise RuntimeError("UI delivery clipboard copy failed")
        _goto_cell(page, f"H{int(target_row_1)}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            page.keyboard.press("Meta+V")
        except Exception:
            page.keyboard.press("Control+V")
        page.wait_for_timeout(600)
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass
        page.wait_for_timeout(1200)

        try:
            srow_after = _ui_find_summary_row_1(page)
        except Exception:
            srow_after = 0
        if int(expected_summary_row_1) > 0:
            srow_after = int(expected_summary_after_1 or expected_summary_row_1)
        else:
            if int(srow_after) <= 2:
                srow_after = int(srow_now)
        
        logging.info("ui_delivery_post_check target_row=%d summary_row_after=%d", int(target_row_1), int(srow_after))
        
        if srow_after <= 0:
            raise RuntimeError("Post-check failed: cannot find 汇总 after paste (可能被覆盖)")
        
        # 安全检查：确保没有写入汇总行或汇总行之后
        if int(target_row_1) >= int(srow_after):
            raise RuntimeError(
                f"Post-check failed: target row {int(target_row_1)} >= 汇总 row {int(srow_after)}, possible overwrite"
            )

        if screenshot_enabled:
            try:
                os.makedirs(os.path.join(".state"), exist_ok=True)
                ss_path = os.path.join(".state", f"feishu_delivery_ui_last_{_now_ts()}.png")
                page.screenshot(path=ss_path, full_page=True)
                logging.info("ui_delivery_screenshot=%s", ss_path)
            except Exception as e:
                logging.info("ui_delivery_screenshot_failed=%s", e)
        
        # 设置单元格居中对齐（使用 OpenAPI）
        if client and spreadsheet_token and delivery_sheet_query_id:
            try:
                # 设置 A-F 列居中对齐
                client.set_cell_alignment(
                    spreadsheet_token=spreadsheet_token,
                    sheet_id=delivery_sheet_query_id,
                    range_a1=f"A{int(target_row_1)}:F{int(target_row_1)}",
                    h_align=2,  # 2=居中
                    v_align=2,  # 2=居中
                )
                # 设置 H 列居中对齐
                client.set_cell_alignment(
                    spreadsheet_token=spreadsheet_token,
                    sheet_id=delivery_sheet_query_id,
                    range_a1=f"H{int(target_row_1)}:H{int(target_row_1)}",
                    h_align=2,  # 2=居中
                    v_align=2,  # 2=居中
                )
                logging.info("ui_delivery_alignment_set row=%d", int(target_row_1))
            except Exception as e:
                logging.warning("ui_delivery_alignment_failed row=%d err=%s", int(target_row_1), e)
    finally:
        pass


TARGET_COLUMNS = [
    "日期",
    "直播ID",
    "快手电话",
    "快手订单号",
    "快手昵称",
    "快手id",
    "主播",
    "直播账号",
    "是否添加",
    "企业微信昵称",
    "拨打次数",
    "目前是否在拨打",
    "客户情况",
    "退费金额",
    "实际报名账号",
    "备注",
]


def read_anchor_map(path: str) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str).fillna("")
    return df


def load_input_table(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    lower = path.lower()
    if lower.endswith(".csv"):
        df = pd.read_csv(path, dtype=str)
    elif lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        df = pd.read_excel(path, dtype=str, engine="openpyxl")
    elif lower.endswith(".xls"):
        df = pd.read_excel(path, dtype=str, engine="xlrd")
    else:
        raise ValueError(f"Unsupported file type: {path}")

    df = df.fillna("")
    return df


def normalize_rows(raw_df: pd.DataFrame, anchor_map: pd.DataFrame, *, live_id: str = "") -> pd.DataFrame:
    df = raw_df.copy()

    col_map = {c.strip(): c for c in df.columns}

    def pick(*names: str) -> str:
        for n in names:
            if n in col_map:
                return col_map[n]
        return ""

    out = pd.DataFrame({c: "" for c in TARGET_COLUMNS}, index=range(len(df)))

    # 日期：固定写今天 X月X日（按业务需求，不取导出表下单时间）
    today = datetime.now()
    if today.hour < 4:
        today = today - timedelta(days=1)
    out["日期"] = f"{today.month}月{today.day}日"

    if live_id:
        # 将直播ID转换为整数类型
        try:
            out["直播ID"] = int(float(str(live_id).strip()))
        except (ValueError, TypeError):
            out["直播ID"] = live_id

    # 直播ID：暂不处理

    # 导出表字段映射
    phone_col = pick("消费者手机号")
    order_col = pick("订单编号")
    nick_col = pick("学员快手昵称")
    kid_col = pick("学员快手ID")
    remark_col = pick("备注")

    if phone_col:
        # 将电话号码转换为整数类型，确保飞书识别为数字
        def to_phone_number(x):
            if x is None or str(x).strip() == "":
                return ""
            try:
                return int(float(str(x).strip()))
            except (ValueError, TypeError):
                return str(x).strip()
        out["快手电话"] = df[phone_col].apply(to_phone_number)
    if order_col:
        out["快手订单号"] = df[order_col]
    if nick_col:
        out["快手昵称"] = df[nick_col]
    if kid_col:
        # 将快手id转换为整数类型，确保飞书识别为数字
        def to_kid_number(x):
            if x is None or str(x).strip() == "":
                return ""
            try:
                return int(float(str(x).strip()))
            except (ValueError, TypeError):
                return str(x).strip()
        out["快手id"] = df[kid_col].apply(to_kid_number)
    if remark_col:
        out["备注"] = df[remark_col]

    if not anchor_map.empty:
        amap = anchor_map.copy()
        amap.columns = [c.strip() for c in amap.columns]
        if "快手ID" in amap.columns and "主播" in amap.columns:
            id_to_anchor = dict(zip(amap["快手ID"].astype(str), amap["主播"].astype(str)))
            out.loc[out["主播"].eq("") & out["快手id"].astype(str).isin(id_to_anchor.keys()), "主播"] = out.loc[
                out["主播"].eq("") & out["快手id"].astype(str).isin(id_to_anchor.keys()),
                "快手id",
            ].map(id_to_anchor)

        if "直播账号" in amap.columns and "主播" in amap.columns:
            acct_to_anchor = dict(zip(amap["直播账号"].astype(str), amap["主播"].astype(str)))
            out.loc[out["主播"].eq("") & out["直播账号"].astype(str).isin(acct_to_anchor.keys()), "主播"] = out.loc[
                out["主播"].eq("") & out["直播账号"].astype(str).isin(acct_to_anchor.keys()),
                "直播账号",
            ].map(acct_to_anchor)

    out = out.fillna("")
    return out


def apply_account_info(norm_df: pd.DataFrame, *, account: str, anchor_map: pd.DataFrame) -> pd.DataFrame:
    if not account:
        return norm_df

    df = norm_df.copy()
    df["直播账号"] = account

    if anchor_map is None or anchor_map.empty:
        return df

    amap = anchor_map.copy()
    amap.columns = [c.strip() for c in amap.columns]
    if "直播账号" in amap.columns and "主播" in amap.columns:
        match = amap[amap["直播账号"].astype(str).str.strip() == str(account).strip()]
        if not match.empty:
            anchor = str(match.iloc[0]["主播"])
            if anchor and anchor.strip():
                df["主播"] = anchor.strip()
    return df


def _resolve_col_index_by_header(
    client: "FeishuClient",
    spreadsheet_token: str,
    sheet_id: str,
    header_name: str,
    *,
    max_cols: int = 26,
) -> int:
    header_name = str(header_name or "").strip()
    if not header_name:
        return 0
    end_letter = chr(ord("A") + (int(max_cols) - 1))
    rng = f"{sheet_id}!A1:{end_letter}1"
    values = client.read_range_values(spreadsheet_token, rng)
    if not values or not isinstance(values, list):
        return 0
    row = values[0] if values else []
    if not isinstance(row, list):
        return 0

    want = header_name.strip()
    want_norm = "".join(want.split())
    for i, v in enumerate(row, 1):
        t = str(v or "").strip()
        if not t:
            continue
        if t == want:
            return int(i)
        t_norm = "".join(t.split())
        if t_norm == want_norm:
            return int(i)
    for i, v in enumerate(row, 1):
        t = str(v or "").strip()
        if not t:
            continue
        if want in t:
            return int(i)
        t_norm = "".join(t.split())
        if want_norm and want_norm in t_norm:
            return int(i)
    return 0


def _api_update_user_contact_rows_skip_anchor(
    *,
    client: "FeishuClient",
    spreadsheet_token: str,
    sheet_id: str,
    start_row: int,
    values: List[List[Any]],
) -> None:
    start_row = int(start_row)
    if start_row <= 0:
        start_row = 2
    if not values:
        return

    def to_int(x):
        """将值转换为整数类型"""
        if x is None or str(x).strip() == "":
            return ""
        try:
            return int(float(str(x).strip()))
        except (ValueError, TypeError):
            return str(x).strip()

    a_f_values: List[List[Any]] = []
    acct_values: List[List[Any]] = []
    remark_values: List[List[Any]] = []

    for r in values:
        rr = list(r) if isinstance(r, list) else []
        if len(rr) < 16:
            rr = rr + ([""] * (16 - len(rr)))
        # 转换数据类型：直播ID(1)、快手电话(2)、快手id(5) 为整数，快手订单号(3) 保持字符串（太长会丢失精度）
        row_af = [
            rr[0],              # 日期 - 字符串
            to_int(rr[1]),      # 直播ID - 整数
            to_int(rr[2]),      # 快手电话 - 整数
            rr[3],              # 快手订单号 - 字符串（18位数字转int会丢失精度）
            rr[4],              # 快手昵称 - 字符串
            to_int(rr[5]),      # 快手id - 整数
        ]
        a_f_values.append(row_af)
        acct_values.append([rr[7]])
        remark_values.append([rr[15]])

    end_row = start_row + max(0, len(a_f_values) - 1)

    acct_col_index = _resolve_col_index_by_header(client, spreadsheet_token, sheet_id, "直播账号")
    if not acct_col_index:
        acct_col_index = 8
    acct_col_letter = _col_letter(int(acct_col_index))

    remark_col_index = _resolve_col_index_by_header(client, spreadsheet_token, sheet_id, "备注")
    if not remark_col_index:
        remark_col_index = 16
    remark_col_letter = _col_letter(int(remark_col_index))

    logging.info(
        "user_contact_api_write_skip_anchor rows=%d start_row=%d end_row=%d acct_col=%s(%d) remark_col=%s(%d)",
        len(a_f_values),
        int(start_row),
        int(end_row),
        acct_col_letter,
        int(acct_col_index),
        remark_col_letter,
        int(remark_col_index),
    )

    rng_a_f = f"{sheet_id}!A{start_row}:F{end_row}"
    rng_acct = f"{sheet_id}!{acct_col_letter}{start_row}:{acct_col_letter}{end_row}"
    rng_remark = f"{sheet_id}!{remark_col_letter}{start_row}:{remark_col_letter}{end_row}"

    client.update_values(spreadsheet_token, rng_a_f, a_f_values)
    client.update_values(spreadsheet_token, rng_acct, acct_values)
    client.update_values(spreadsheet_token, rng_remark, remark_values)

    # 单独用 RAW 模式重写订单号列（D列），并设置格式为纯文本
    order_values = [[row[3]] for row in a_f_values]  # D列是索引3
    rng_order = f"{sheet_id}!D{start_row}:D{end_row}"
    client.update_values_raw(spreadsheet_token, rng_order, order_values)
    # 设置订单号列格式为纯文本（formatter: @），避免绿色警告
    client.set_cell_format_text(spreadsheet_token, rng_order)


def get_existing_dedup_keys(client: FeishuClient, spreadsheet_token: str, sheet_id: str, dedup_key_col_index_1based: int, max_rows: int = 5000) -> Set[str]:
    col_letter = chr(ord("A") + (dedup_key_col_index_1based - 1))
    rng = f"{sheet_id}!{col_letter}1:{col_letter}{max_rows}"
    values = client.read_range_values(spreadsheet_token, rng)
    s: Set[str] = set()
    for row in values:
        if not row:
            continue
        v = str(row[0]).strip()
        if v:
            s.add(v)
    return s


def get_existing_dedup_keys_and_last_row(
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    dedup_key_col_index_1based: int,
    *,
    max_rows: int = 5000,
) -> Tuple[Set[str], int]:
    col_letter = _col_letter(int(dedup_key_col_index_1based))
    s: Set[str] = set()
    last = 0

    hard_cap = max(1, int(max_rows))
    # 使用较大的初始块，避免在常见（<2000 行）情况下产生多次 API 调用。
    chunk = min(2048, hard_cap)
    start = 1
    while start <= hard_cap:
        end = min(hard_cap, start + chunk - 1)
        rng = f"{sheet_id}!{col_letter}{start}:{col_letter}{end}"
        values = client.read_range_values(spreadsheet_token, rng)

        chunk_last = 0
        for i0, row in enumerate(values or [], 0):
            if not row:
                continue
            v = row[0]
            if v is None:
                continue
            t = str(v).strip()
            if t:
                s.add(t)
                chunk_last = start + i0

        if chunk_last:
            last = max(last, chunk_last)

        if chunk_last < end:
            break

        start = end + 1
        chunk = min(hard_cap, chunk * 2)

    return s, int(last)


def resolve_dedup_col_index(
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    header_name: str,
    *,
    max_cols: int = 26,
) -> int:
    header_name = str(header_name or "").strip()
    if not header_name:
        return 0
    end_letter = chr(ord("A") + (int(max_cols) - 1))
    rng = f"{sheet_id}!A1:{end_letter}1"
    values = client.read_range_values(spreadsheet_token, rng)
    if not values or not isinstance(values, list):
        return 0
    row = values[0] if values else []
    if not isinstance(row, list):
        return 0
    for i, v in enumerate(row, 1):
        if str(v or "").strip() == header_name:
            return int(i)
    return 0


def detect_last_non_empty_row_in_col(
    client: FeishuClient,
    spreadsheet_token: str,
    sheet_id: str,
    col_index_1based: int,
    *,
    max_rows: int = 5000,
) -> int:
    col_letter = _col_letter(int(col_index_1based))
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


def _col_letter(col_index_1based: int) -> str:
    # Supports A..Z only (current sheets in this project are within this range).
    return chr(ord("A") + (int(col_index_1based) - 1))


def df_to_values(df: pd.DataFrame) -> List[List[Any]]:
    values: List[List[Any]] = []
    for _, row in df.iterrows():
        values.append([row.get(c, "") for c in TARGET_COLUMNS])
    return values


def cmd_list_sheets(args: argparse.Namespace) -> None:
    cfg = load_json(args.config)
    client = FeishuClient(FeishuConfig(cfg["feishu"]["app_id"], cfg["feishu"]["app_secret"]))

    spreadsheet_token = client.resolve_spreadsheet_token(
        wiki_url=cfg["target"].get("wiki_url", ""),
        spreadsheet_token=cfg["target"].get("spreadsheet_token", ""),
    )
    sheets = client.list_sheets(spreadsheet_token)
    for s in sheets:
        logging.info("sheet_title=%s sheet_id=%s", s.get("title"), s.get("sheet_id"))


def _cmd_sync_batch(args: argparse.Namespace, cfg: Dict[str, Any], client: FeishuClient) -> None:
    """批量同步多个账号的数据，只打开一次云表格"""
    batch_data = cfg["input"].get("batch_data", [])
    if not batch_data:
        logging.info("batch_mode enabled but no batch_data provided")
        return
    
    logging.info("batch_sync_start items=%d", len(batch_data))
    
    # 收集所有账号的标准化数据
    all_norm_rows = []
    anchor_map = read_anchor_map(cfg.get("mapping", {}).get("anchor_map_csv", ""))
    delivery_updates = []  # 投放信息表的更新列表
    processed_export_paths = set()  # 记录已处理的 export_path，避免重复处理用户对接信息
    
    for item in batch_data:
        input_path = item.get("export_path", "")
        account = item.get("account", "")
        live_id = item.get("live_id", "")
        niu_metrics = item.get("niu_metrics") or {}

        # 1) 用户对接信息表：允许失败（不应影响投放信息表写入）
        if input_path and (input_path not in processed_export_paths):
            try:
                raw_df = load_input_table(input_path)
                norm_df = normalize_rows(raw_df, anchor_map, live_id=str(live_id).strip())

                if account:
                    norm_df = apply_account_info(norm_df, account=account, anchor_map=anchor_map)

                if live_id:
                    norm_df["直播ID"] = str(live_id).strip()

                all_norm_rows.append(norm_df)
                processed_export_paths.add(input_path)
                logging.info("batch_sync_collected account=%s rows=%d", account, len(norm_df))
            except Exception as e:
                logging.warning("batch_sync_user_data_collect_failed account=%s export_path=%s err=%s", account, input_path, e)
                # do not continue; still collect delivery updates below
                processed_export_paths.add(input_path)

        # 2) 投放信息表：每场直播都要处理，独立于用户数据
        if niu_metrics:
            try:
                delivery_date_str = ""
                start_dt = str(niu_metrics.get("start_dt", "") or "").strip()
                start_hm = str(niu_metrics.get("start_hm", "") or "").strip()

                cutoff_hour = 3
                try:
                    cutoff_hour = int((cfg.get("target") or {}).get("delivery_day_cutoff_hour", 3) or 3)
                except Exception:
                    cutoff_hour = 3
                if cutoff_hour < 0:
                    cutoff_hour = 0
                if cutoff_hour > 23:
                    cutoff_hour = 23

                import re
                from datetime import datetime, timedelta

                base_dt: Optional[datetime] = None
                if start_dt:
                    # Prefer YYYY-MM-DD
                    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", start_dt)
                    if m:
                        yy = int(m.group(1))
                        mm = int(m.group(2))
                        dd = int(m.group(3))
                        hh = 0
                        mi = 0
                        # Try to parse time from start_dt, fallback to start_hm.
                        m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", start_dt)
                        if not m_time and start_hm:
                            m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", start_hm)
                        if m_time:
                            try:
                                hh = int(m_time.group(1))
                                mi = int(m_time.group(2))
                            except Exception:
                                hh = 0
                                mi = 0
                        try:
                            base_dt = datetime(yy, mm, dd, hh, mi)
                        except Exception:
                            base_dt = None
                    else:
                        # Fallback: MM-DD (only accept plausible months)
                        m2 = re.search(r"\b(\d{2})-(\d{2})\b", start_dt)
                        if m2:
                            mm = int(m2.group(1))
                            dd = int(m2.group(2))
                            if 1 <= mm <= 12 and 1 <= dd <= 31:
                                now = datetime.now()
                                hh = 0
                                mi = 0
                                m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", start_dt)
                                if not m_time and start_hm:
                                    m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", start_hm)
                                if m_time:
                                    try:
                                        hh = int(m_time.group(1))
                                        mi = int(m_time.group(2))
                                    except Exception:
                                        hh = 0
                                        mi = 0
                                try:
                                    base_dt = datetime(now.year, mm, dd, hh, mi)
                                except Exception:
                                    base_dt = None

                if base_dt is None:
                    base_dt = datetime.now()

                # 业务规则：凌晨 cutoff_hour 点前开播，归属到前一天（用于匹配“待播”行）
                eff_dt = base_dt
                try:
                    if int(eff_dt.hour) < int(cutoff_hour):
                        eff_dt = eff_dt - timedelta(days=1)
                except Exception:
                    pass

                delivery_date_str = f"{eff_dt.month}月{eff_dt.day}日"

                delivery_updates.append(
                    {
                        "account": account,
                        "date_str": delivery_date_str,
                        "live_id": str(live_id).strip(),
                        "niu_metrics": niu_metrics,
                    }
                )
                logging.info(
                    "batch_sync_delivery_collected account=%s date=%s live_id=%s start_hm=%s",
                    account,
                    delivery_date_str,
                    live_id,
                    niu_metrics.get("start_hm", ""),
                )
            except Exception as e:
                logging.warning("batch_sync_delivery_collect_failed account=%s err=%s", account, e)
    
    # 合并所有数据（用户对接信息表）
    combined_df = None
    if all_norm_rows:
        import pandas as pd

        combined_df = pd.concat(all_norm_rows, ignore_index=True)
        logging.info("batch_sync_combined total_rows=%d", len(combined_df))
    else:
        logging.info("batch_sync_no_user_data")
    
    # 使用原有的同步逻辑，但只打开一次云表格
    target_cfg = cfg.get("target") or {}
    wiki_url = target_cfg.get("wiki_url", "")
    wiki_password = str(target_cfg.get("wiki_password", "") or "")
    ui_force_a2 = bool(target_cfg.get("ui_force_a2", True))
    ui_screenshot_enabled = bool(target_cfg.get("ui_screenshot_enabled", True))
    ui_paste_between_ms = int(target_cfg.get("ui_paste_between_ms", 500))
    ui_paste_apply_wait_ms = int(target_cfg.get("ui_paste_apply_wait_ms", 2000))
    ui_fallback_enabled = bool(target_cfg.get("ui_fallback_enabled", True))
    ui_profile_dir = target_cfg.get("ui_fallback_profile_dir", os.path.join(".state", "feishu_profile"))
    ui_timeout_ms = int(target_cfg.get("ui_fallback_timeout_ms", 60000))
    ui_headless = bool(target_cfg.get("ui_fallback_headless", True))
    write_mode = str(target_cfg.get("write_mode", "auto")).strip().lower()
    prefer_ui_for_user_data = bool(target_cfg.get("prefer_ui_for_user_data", False))
    ui_dedup_enabled = bool(target_cfg.get("ui_dedup_enabled", True))
    ui_dedup_reset = bool(target_cfg.get("ui_dedup_reset", False))
    sync_delivery_sheet = bool(target_cfg.get("sync_delivery_sheet", True))
    delivery_write_mode = str(target_cfg.get("delivery_write_mode", "ui") or "ui").strip().lower()
    sheet_title = str((cfg.get("target") or {}).get("sheet_title", "Sheet1") or "Sheet1")
    sheet_id_cfg = str((cfg.get("target") or {}).get("sheet_id", "") or "")
    
    # 用户对接信息表：不强制从A2开始，而是追加到末尾
    if sheet_title.strip() == "用户对接信息":
        ui_force_a2 = False
    
    # 同步用户对接信息表（批量）
    # 尝试使用 OpenAPI 获取 spreadsheet_token 和 sheet_id
    spreadsheet_token = ""
    sheet_id = ""
    try:
        spreadsheet_token = client.resolve_spreadsheet_token(
            wiki_url=wiki_url,
            spreadsheet_token=(cfg.get("target") or {}).get("spreadsheet_token", ""),
        )
        sheets = client.list_sheets(spreadsheet_token)
        for s in sheets:
            if s.get("title") == sheet_title and s.get("sheet_id"):
                sheet_id = str(s.get("sheet_id"))
                break
        logging.info("batch_sync_openapi_success spreadsheet_token=%s sheet_id=%s", spreadsheet_token, sheet_id)
    except Exception as e:
        # OpenAPI 失败（可能是权限不足），稍后使用 UI 模式
        logging.warning("batch_sync_openapi_failed err=%s, will use UI mode", e)
        spreadsheet_token = ""
        sheet_id = ""
    
    # 准备用户对接信息表的数据
    has_user_data_to_append = False
    _export_xlsx = False
    values_ui = []
    target_row = 2
    
    if combined_df is not None and not combined_df.empty:
        if sheet_id and spreadsheet_token:
            # OpenAPI 可用，使用 OpenAPI 去重
            try:
                dedup_col_index = resolve_dedup_col_index(client, spreadsheet_token, sheet_id, "快手订单号")
                if not dedup_col_index:
                    dedup_col_index = TARGET_COLUMNS.index("快手订单号") + 1
                ui_seen, last_data_row = get_existing_dedup_keys_and_last_row(
                    client,
                    spreadsheet_token,
                    sheet_id,
                    int(dedup_col_index),
                    max_rows=5000,
                )
                combined_df["快手订单号"] = combined_df["快手订单号"].astype(str).str.strip()
                try:
                    non_empty_orders = combined_df[combined_df["快手订单号"].ne("")]["快手订单号"]
                    sample_orders = list(non_empty_orders.head(5))
                    sample_seen = list(sorted(list(ui_seen))[:5])
                    logging.info(
                        "batch_sync_dedup_debug dedup_col_index=%d combined_rows=%d orders_non_empty=%d ui_seen=%d sample_orders=%s sample_ui_seen=%s",
                        dedup_col_index,
                        len(combined_df),
                        int(getattr(non_empty_orders, "shape", [0])[0]),
                        len(ui_seen),
                        sample_orders,
                        sample_seen,
                    )
                except Exception as _e:
                    logging.info(
                        "batch_sync_dedup_debug dedup_col_index=%d combined_rows=%d ui_seen=%d",
                        dedup_col_index,
                        len(combined_df),
                        len(ui_seen),
                    )
                to_add = combined_df[~combined_df["快手订单号"].isin(ui_seen) & combined_df["快手订单号"].ne("")].copy()
                try:
                    logging.info("batch_sync_dedup_debug to_add=%d", len(to_add))
                except Exception:
                    pass
                
                if not to_add.empty:
                    has_user_data_to_append = True
                    _export_xlsx = True
                    values_ui = df_to_values(to_add)
                    _append_copy_table_cache_from_values(values_ui)
                    logging.info("batch_sync_append rows=%d", len(values_ui))
                    
                    try:
                        target_row = int(last_data_row) + 1
                        logging.info(
                            "batch_sync_detect_last_row col=%s last_data_row=%d target_row=%d",
                            _col_letter(int(dedup_col_index)),
                            int(last_data_row),
                            int(target_row),
                        )
                    except Exception as e_last:
                        logging.warning("batch_sync_detect_last_row_failed err=%s", e_last)
                        target_row = 2
                else:
                    logging.info("batch_sync_no_new_user_data")
            except Exception as e:
                logging.warning("batch_sync_dedup_failed err=%s, will append all data", e)
                # 去重失败，添加所有数据
                has_user_data_to_append = True
                values_ui = df_to_values(combined_df)
                _append_copy_table_cache_from_values(values_ui)
                logging.info("batch_sync_append_all rows=%d", len(values_ui))
        else:
            # OpenAPI 不可用，无法去重，添加所有数据
            has_user_data_to_append = True
            values_ui = df_to_values(combined_df)
            _append_copy_table_cache_from_values(values_ui)
            logging.info("batch_sync_no_openapi_append_all rows=%d", len(values_ui))
    
    # 同步投放信息表（批量）
    # 根据 delivery_write_mode 配置决定使用哪种模式
    delivery_failed = []
    if sync_delivery_sheet:
        use_api_mode = delivery_write_mode in ("api", "auto") and spreadsheet_token
        allow_ui_fallback = delivery_write_mode in ("ui", "auto") and ui_fallback_enabled
        
        if use_api_mode:
            # 尝试使用 OpenAPI 模式
            logging.info("batch_sync_delivery_try_api_mode count=%d", len(delivery_updates))
            for update in delivery_updates:
                try:
                    _sync_delivery_sheet(
                        client=client,
                        spreadsheet_token=spreadsheet_token,
                        anchor_map=anchor_map,
                        account=update["account"],
                        date_str=update["date_str"],
                        live_id=update["live_id"],
                        niu_metrics=update["niu_metrics"],
                    )
                except Exception as e:
                    # OpenAPI 错误
                    error_msg = str(e)
                    if "403" in error_msg or "Forbidden" in error_msg or "131006" in error_msg:
                        logging.warning("batch_sync_delivery_openapi_forbidden account=%s", update["account"])
                    elif "404" in error_msg:
                        logging.warning("batch_sync_delivery_openapi_404 account=%s", update["account"])
                    else:
                        logging.warning("batch_sync_delivery_openapi_failed account=%s err=%s", update["account"], e)
                    
                    if allow_ui_fallback:
                        logging.info("batch_sync_delivery_will_use_ui_fallback account=%s", update["account"])
                        delivery_failed.append(update)
                    else:
                        # 不允许回退，直接失败
                        logging.error("batch_sync_delivery_api_failed_no_fallback account=%s", update["account"])
        else:
            # 直接使用 UI 模式
            delivery_failed = delivery_updates
            logging.info("batch_sync_delivery_use_ui_mode count=%d mode=%s", len(delivery_failed), delivery_write_mode)
    
    # 处理用户对接信息表（如果有数据）
    if has_user_data_to_append:
        # 根据 write_mode 配置决定使用哪种模式
        use_api_for_user_data = bool(spreadsheet_token and sheet_id) and (not prefer_ui_for_user_data)
        
        if use_api_for_user_data:
            # 使用 OpenAPI 追加数据
            logging.info("batch_sync_api_append_user_data rows=%d mode=%s", len(values_ui), write_mode)
            try:
                _api_update_user_contact_rows_skip_anchor(
                    client=client,
                    spreadsheet_token=spreadsheet_token,
                    sheet_id=sheet_id,
                    start_row=int(target_row),
                    values=values_ui,
                )
                logging.info("batch_sync_api_update_tail_skip_anchor_done start_row=%d rows=%d", int(target_row), len(values_ui))
                try:
                    expected_orders = []
                    for r in values_ui[:5]:
                        if isinstance(r, list) and len(r) >= 4:
                            expected_orders.append(str(r[3]).strip())
                    expected_orders = [x for x in expected_orders if x]
                    dedup_col_index = resolve_dedup_col_index(client, spreadsheet_token, sheet_id, "快手订单号")
                    if not dedup_col_index:
                        dedup_col_index = TARGET_COLUMNS.index("快手订单号") + 1
                    ui_seen2, _last2 = get_existing_dedup_keys_and_last_row(
                        client,
                        spreadsheet_token,
                        sheet_id,
                        int(dedup_col_index),
                        max_rows=5000,
                    )
                    ok = False
                    if expected_orders:
                        ok = any(x in ui_seen2 for x in expected_orders)
                    logging.info(
                        "batch_sync_api_append_verify ok=%s expected_sample=%s",
                        bool(ok),
                        expected_orders[:3],
                    )
                except Exception as _e:
                    pass
            except Exception as e:
                error_msg = str(e)
                if "403" in error_msg or "Forbidden" in error_msg or "131006" in error_msg or "90218" in error_msg or "locked" in error_msg.lower():
                    logging.warning("batch_sync_api_append_forbidden_or_locked, will use UI fallback err=%s", error_msg[:200])
                    # When insert/append is blocked by locked cells, write into the detected tail rows
                    # by updating unlocked ranges (skip locked column O: 退费金额).
                    try:
                        start_row = int(target_row)
                        a_f_values = []
                        acct_values = []
                        remark_values = []
                        expected_orders = []
                        def to_int_val(x):
                            if x is None or str(x).strip() == "":
                                return ""
                            try:
                                return int(float(str(x).strip()))
                            except (ValueError, TypeError):
                                return str(x).strip()

                        for r in values_ui:
                            rr = list(r) if isinstance(r, list) else []
                            if len(rr) < 16:
                                rr = rr + ([""] * (16 - len(rr)))
                            # 转换数据类型：直播ID(1)、快手电话(2)、快手id(5) 为整数，快手订单号保持字符串
                            row_af = [
                                rr[0],                  # 日期 - 字符串
                                to_int_val(rr[1]),      # 直播ID - 整数
                                to_int_val(rr[2]),      # 快手电话 - 整数
                                rr[3],                  # 快手订单号 - 字符串（18位数字转int会丢失精度）
                                rr[4],                  # 快手昵称 - 字符串
                                to_int_val(rr[5]),      # 快手id - 整数
                            ]
                            a_f_values.append(row_af)
                            acct_values.append([rr[7]])
                            remark_values.append([rr[15]])
                            try:
                                expected_orders.append(str(rr[3] or "").strip())
                            except Exception:
                                pass
                        expected_orders = [x for x in expected_orders if x]
                        end_row = start_row + max(0, len(a_f_values) - 1)

                        acct_col_index = _resolve_col_index_by_header(client, spreadsheet_token, sheet_id, "直播账号")
                        if not acct_col_index:
                            acct_col_index = 8
                        acct_col_letter = _col_letter(int(acct_col_index))

                        remark_col_index = _resolve_col_index_by_header(client, spreadsheet_token, sheet_id, "备注")
                        if not remark_col_index:
                            remark_col_index = 16
                        remark_col_letter = _col_letter(int(remark_col_index))

                        rng_a_f = f"{sheet_id}!A{start_row}:F{end_row}"
                        rng_acct = f"{sheet_id}!{acct_col_letter}{start_row}:{acct_col_letter}{end_row}"
                        rng_remark = f"{sheet_id}!{remark_col_letter}{start_row}:{remark_col_letter}{end_row}"

                        resp1 = client.update_values(spreadsheet_token, rng_a_f, a_f_values)
                        resp2 = client.update_values(spreadsheet_token, rng_acct, acct_values)
                        resp3 = client.update_values(spreadsheet_token, rng_remark, remark_values)

                        # 单独用 RAW 模式重写订单号列（D列），并设置格式为纯文本
                        order_values = [[row[3]] for row in a_f_values]
                        rng_order = f"{sheet_id}!D{start_row}:D{end_row}"
                        client.update_values_raw(spreadsheet_token, rng_order, order_values)
                        client.set_cell_format_text(spreadsheet_token, rng_order)
                        logging.info(
                            "batch_sync_api_update_tail_success range_a_f=%s range_acct=%s range_remark=%s",
                            rng_a_f,
                            rng_acct,
                            rng_remark,
                        )
                        try:
                            logging.info("batch_sync_api_update_tail_response a_f=%s acct=%s remark=%s", resp1, resp2, resp3)
                        except Exception:
                            pass

                        dedup_col_index = resolve_dedup_col_index(client, spreadsheet_token, sheet_id, "快手订单号")
                        if not dedup_col_index:
                            dedup_col_index = 4
                        col_letter = _col_letter(int(dedup_col_index))
                        rng_verify = f"{sheet_id}!{col_letter}{start_row}:{col_letter}{end_row}"
                        got_values = client.read_range_values(spreadsheet_token, rng_verify)
                        got_orders = []
                        for rr in got_values:
                            if rr and len(rr) > 0:
                                got_orders.append(str(rr[0] or "").strip())
                        got_orders = [x for x in got_orders if x]
                        ok = False
                        if expected_orders:
                            ok = any(x in set(got_orders) for x in expected_orders)
                        logging.info(
                            "batch_sync_api_update_tail_verify ok=%s range=%s expected_sample=%s got_sample=%s",
                            bool(ok),
                            rng_verify,
                            expected_orders[:3],
                            got_orders[:3],
                        )
                    except Exception as e2:
                        # Do not fall back to UI for this sheet because UI paste is not reliable.
                        logging.error("batch_sync_api_update_tail_failed err=%s", e2)
                else:
                    logging.error("batch_sync_api_append_failed err=%s", e)
        else:
            # write_mode 是 "ui" 或者没有 OpenAPI 权限，使用 UI 模式
            logging.info("batch_sync_ui_append_user_data mode=%s has_openapi=%s", write_mode, bool(spreadsheet_token and sheet_id))
            logging.error("batch_sync_ui_append_disabled; UI fallback is not reliable for this sheet")

    if has_user_data_to_append and values_ui and _export_xlsx:
        try:
            # 导入 web_control_server 模块来使用导出功能
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import web_control_server as wcs
            
            # 准备导出数据（转换为 web_control_server 期望的格式）
            export_rows = []
            try:
                idx_phone = TARGET_COLUMNS.index("快手电话")
            except Exception:
                idx_phone = 2
            try:
                idx_nick = TARGET_COLUMNS.index("快手昵称")
            except Exception:
                idx_nick = 4
            try:
                idx_acct = TARGET_COLUMNS.index("直播账号")
            except Exception:
                idx_acct = -1
            try:
                idx_anchor = TARGET_COLUMNS.index("主播")
            except Exception:
                idx_anchor = -1
            try:
                idx_kid = TARGET_COLUMNS.index("快手id")
            except Exception:
                idx_kid = -1

            for row in values_ui:
                # values_ui follows TARGET_COLUMNS order:
                # [日期, 直播ID, 快手电话, 快手订单号, 快手昵称, ...]
                # web_control_server export expects 5 columns:
                # [姓名, 账号, 别名, 部门, 手机]
                # Business mapping:
                # - 姓名/别名: 快手昵称
                # - 账号/手机: 快手电话
                # - 部门: leave blank here; web_control_server will apply saved dept config.
                if not isinstance(row, list):
                    continue
                phone = row[idx_phone] if (idx_phone >= 0 and len(row) > idx_phone) else ""
                nick = row[idx_nick] if (idx_nick >= 0 and len(row) > idx_nick) else ""
                acct = row[idx_acct] if (idx_acct >= 0 and len(row) > idx_acct) else ""
                anchor = row[idx_anchor] if (idx_anchor >= 0 and len(row) > idx_anchor) else ""
                kid = row[idx_kid] if (idx_kid >= 0 and len(row) > idx_kid) else ""

                phone_s = "" if phone is None else str(phone).strip()
                nick_s = "" if nick is None else str(nick).strip()
                acct_s = "" if acct is None else str(acct).strip()
                anchor_s = "" if anchor is None else str(anchor).strip()
                kid_s = "" if kid is None else str(kid).strip()

                # Fallbacks:
                # - If nick missing, use anchor or account.
                # - If phone missing, keep blank but still allow row export if we have nick/account/id.
                if not nick_s:
                    nick_s = anchor_s or acct_s or kid_s
                acct_for_export = phone_s or acct_s or kid_s
                export_row = [
                    nick_s,
                    acct_for_export,
                    nick_s,
                    "",
                    phone_s,
                ]
                if any(str(x).strip() for x in export_row):
                    export_rows.append(export_row)
            
            if export_rows:
                # 创建一个简单的 args 对象
                class SimpleArgs:
                    def __init__(self, config_path):
                        self.config = config_path
                
                args_obj = SimpleArgs(args.config if hasattr(args, 'config') else 'config.json')

                export_dirs: List[str] = []
                try:
                    export_dir = wcs._user_contact_export_dir(cfg, args_obj)
                    if export_dir:
                        export_dirs.append(str(export_dir))
                except Exception:
                    pass

                try:
                    mapping = cfg.get("mapping") or {}
                    uc = str(mapping.get("user_contact_export_dir") or "").strip()
                    wz = str(mapping.get("wenzong_user_contact_export_dir") or "").strip()
                    is_wenzong = bool(wz) and bool(uc) and (uc == wz)
                except Exception:
                    is_wenzong = False

                try:
                    # 自动检测路径:优先使用本地路径,如果不存在则使用网络共享路径
                    local_base = "/Users/openclaw-mini/Desktop/共享文件夹"
                    network_base = "/Volumes/共享文件夹"
                    
                    # 选择可用的基础路径
                    base_path = local_base if os.path.exists(local_base) else network_base
                    
                    if is_wenzong:
                        export_dirs.append(f"{base_path}/WenZong")
                    else:
                        export_dirs.append(f"{base_path}/用户对接导出")
                except Exception:
                    pass

                export_dirs2: List[str] = []
                seen_dirs = set()
                for d in export_dirs:
                    dd = str(d or "").strip()
                    if not dd:
                        continue
                    if dd.lower().startswith("smb://"):
                        continue
                    if dd in seen_dirs:
                        continue
                    seen_dirs.add(dd)
                    export_dirs2.append(dd)

                if not export_dirs2:
                    logging.info("batch_sync_excel_export_skipped no_export_dir_configured")
                else:
                    dept = ""
                    try:
                        dept = wcs._load_user_contact_dept(cfg, args_obj)
                    except Exception:
                        dept = ""
                    try:
                        rows2 = wcs._apply_dept(export_rows, dept)
                    except Exception:
                        rows2 = export_rows
                    try:
                        seq = wcs._next_user_contact_seq(cfg, args_obj)
                    except Exception:
                        seq = 0
                    try:
                        name = f"{wcs._chinese_simple_num(int(seq))}、{wcs._now_ts()}.xlsx" if int(seq) > 0 else f"{wcs._now_ts()}.xlsx"
                    except Exception:
                        name = f"{wcs._now_ts()}.xlsx"

                    try:
                        payload = wcs._xlsx_bytes_from_rows_template(cfg, args_obj, rows2)
                    except Exception as e:
                        try:
                            print(f"[sync] template export failed, fallback to simple workbook: {e}", file=sys.stderr)
                        except Exception:
                            pass
                        payload = wcs._xlsx_bytes_from_rows(rows2)

                    ok_any = False
                    last_ok_path = ""
                    for d in export_dirs2:
                        try:
                            os.makedirs(d, exist_ok=True)
                            out_path = os.path.join(d, name)
                            with open(out_path, "wb") as f:
                                f.write(payload)
                            ok_any = True
                            last_ok_path = out_path
                            logging.info("batch_sync_excel_export_success file=%s path=%s", name, out_path)
                        except Exception as e:
                            logging.warning("batch_sync_excel_export_failed dir=%s err=%s", d, e)

                    if not ok_any:
                        logging.warning("batch_sync_excel_export_failed err=all_dirs_failed")
            else:
                logging.info("batch_sync_excel_export_skipped export_rows_empty")
        except Exception as e:
            logging.warning("batch_sync_excel_export_exception err=%s", e)

    if not sync_delivery_sheet:
        logging.info("batch_sync_skip_delivery_sheet")
        logging.info("batch_sync_done")
        return
    
    # 处理投放信息表：每条记录独立打开/关闭浏览器
    if delivery_failed and ui_fallback_enabled:
        logging.info("batch_sync_delivery_sequential count=%d", len(delivery_failed))
        for idx, update in enumerate(delivery_failed, 1):
            try:
                logging.info("batch_sync_delivery_sequential_item %d/%d account=%s", 
                             idx, len(delivery_failed), update["account"])
                # 每条记录独立处理：ui_page=None 会让函数自己打开和关闭浏览器
                _ui_sync_delivery_sheet_fallback(
                    client=client,
                    spreadsheet_token=spreadsheet_token,
                    wiki_url=wiki_url,
                    wiki_password=wiki_password,
                    ui_profile_dir=ui_profile_dir,
                    ui_headless=ui_headless,
                    ui_timeout_ms=ui_timeout_ms,
                    ui_screenshot_enabled=ui_screenshot_enabled,
                    anchor_map=anchor_map,
                    account=update["account"],
                    date_str=update["date_str"],
                    live_id=update["live_id"],
                    niu_metrics=update["niu_metrics"],
                    ui_page=None,  # 关键：传入 None，每次都打开/关闭浏览器
                )
                logging.info("batch_sync_delivery_sequential_success %d/%d", idx, len(delivery_failed))
            except Exception as e:
                logging.warning("batch_sync_delivery_sequential_failed %d/%d account=%s err=%s", 
                                idx, len(delivery_failed), update["account"], e)
    
    logging.info("batch_sync_done")


def cmd_sync(args: argparse.Namespace) -> None:
    cfg = load_json(args.config)
    client = FeishuClient(FeishuConfig(cfg["feishu"]["app_id"], cfg["feishu"]["app_secret"]))

    # 检查是否为批量模式
    if cfg.get("input", {}).get("batch_mode"):
        _cmd_sync_batch(args, cfg, client)
        return

    input_path = cfg["input"]["file_path"]
    dedup_key = cfg["input"].get("dedup_key", "快手订单号")
    if dedup_key != "快手订单号":
        raise RuntimeError("This script currently supports only dedup_key=快手订单号")

    raw_df = load_input_table(input_path)
    anchor_map = read_anchor_map(cfg.get("mapping", {}).get("anchor_map_csv", ""))
    live_id = (cfg.get("input") or {}).get("live_id") or ""
    niu_metrics = (cfg.get("input") or {}).get("niu_metrics") or {}
    # Regression/testing helper: allow forcing delivery UI flows even when niu_metrics isn't available.
    force_delivery_dummy_metrics = str(os.getenv("FORCE_DELIVERY_DUMMY_METRICS", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }
    if force_delivery_dummy_metrics and (not isinstance(niu_metrics, dict) or not niu_metrics):
        niu_metrics = {
            "start_hm": "00:00",
            "cost": "0",
            "direct_orders": "0",
            "live_id": str(live_id or "").strip(),
        }
    norm_df = normalize_rows(raw_df, anchor_map, live_id=str(live_id).strip())

    try:
        if not norm_df.empty:
            delivery_date_str = str(norm_df.iloc[0].get("日期", "") or "").strip()
        else:
            delivery_date_str = ""
    except Exception:
        delivery_date_str = ""

    # 投放信息表日期归属规则：凌晨 cutoff_hour 点前开播，归属到前一天。
    # 优先使用 niu_metrics.start_dt / start_hm 推导日期；否则回退到已有 delivery_date_str / today。
    try:
        cutoff_hour = 3
        try:
            cutoff_hour = int((cfg.get("target") or {}).get("delivery_day_cutoff_hour", 3) or 3)
        except Exception:
            cutoff_hour = 3
        if cutoff_hour < 0:
            cutoff_hour = 0
        if cutoff_hour > 23:
            cutoff_hour = 23

        start_dt = str((niu_metrics or {}).get("start_dt", "") or "").strip()
        start_hm = str((niu_metrics or {}).get("start_hm", "") or "").strip()
        base_dt = None
        if start_dt:
            import re

            m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", start_dt)
            if m:
                yy = int(m.group(1))
                mm = int(m.group(2))
                dd = int(m.group(3))
                hh = 0
                mi = 0
                m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", start_dt)
                if not m_time and start_hm:
                    m_time = re.search(r"\b(\d{1,2}):(\d{2})\b", start_hm)
                if m_time:
                    try:
                        hh = int(m_time.group(1))
                        mi = int(m_time.group(2))
                    except Exception:
                        hh = 0
                        mi = 0
                try:
                    base_dt = datetime(yy, mm, dd, hh, mi)
                except Exception:
                    base_dt = None

        if base_dt is not None:
            eff_dt = base_dt
            if int(eff_dt.hour) < int(cutoff_hour):
                eff_dt = eff_dt - timedelta(days=1)
            delivery_date_str = f"{eff_dt.month}月{eff_dt.day}日"
    except Exception:
        pass

    if not delivery_date_str:
        today = datetime.now()
        delivery_date_str = f"{today.month}月{today.day}日"

    account = (cfg.get("input") or {}).get("account", "")
    if account:
        norm_df = apply_account_info(norm_df, account=account, anchor_map=anchor_map)

    # Re-apply live_id at the very end to prevent any later transformations from clearing it.
    live_id_s = str(live_id).strip()
    if live_id_s:
        norm_df["直播ID"] = live_id_s
    try:
        if live_id_s:
            logging.info("live_id=%s first_row_live_id=%s", live_id_s, str(norm_df.iloc[0].get("直播ID", "")))
        else:
            logging.info("live_id=(empty)")
    except Exception:
        pass

    target_cfg = cfg.get("target") or {}
    wiki_url = target_cfg.get("wiki_url", "")
    wiki_password = str(target_cfg.get("wiki_password", "") or "")
    ui_force_a2 = bool(target_cfg.get("ui_force_a2", True))
    ui_screenshot_enabled = bool(target_cfg.get("ui_screenshot_enabled", True))
    ui_paste_between_ms = int(target_cfg.get("ui_paste_between_ms", 500))
    ui_paste_apply_wait_ms = int(target_cfg.get("ui_paste_apply_wait_ms", 2000))
    ui_fallback_enabled = bool(target_cfg.get("ui_fallback_enabled", True))
    ui_profile_dir = target_cfg.get("ui_fallback_profile_dir", os.path.join(".state", "feishu_profile"))
    ui_timeout_ms = int(target_cfg.get("ui_fallback_timeout_ms", 60000))
    ui_headless = bool(target_cfg.get("ui_fallback_headless", True))
    write_mode = str(target_cfg.get("write_mode", "auto")).strip().lower()
    ui_dedup_enabled = bool(target_cfg.get("ui_dedup_enabled", True))
    ui_dedup_reset = bool(target_cfg.get("ui_dedup_reset", False))
    sync_delivery_sheet = bool(target_cfg.get("sync_delivery_sheet", True))
    delivery_write_mode = str(target_cfg.get("delivery_write_mode", "ui") or "ui").strip().lower()

    sheet_title = str((cfg.get("target") or {}).get("sheet_title", "Sheet1") or "Sheet1")
    sheet_id_cfg = str((cfg.get("target") or {}).get("sheet_id", "") or "")

    # 用户对接信息：期望按时间顺序向下追加（旧的在上，新的在下），而不是每次从 A2 顶部覆盖/粘贴。
    if sheet_title.strip() == "用户对接信息":
        ui_force_a2 = False

    norm_df["快手订单号"] = norm_df["快手订单号"].astype(str).str.strip()
    candidate = norm_df[norm_df["快手订单号"].ne("")].copy()
    if candidate.empty:
        logging.info("Nothing to append.")
        if sync_delivery_sheet:
            # 投放信息：优先 OpenAPI 写（通常无权限），失败则 UI 插入/更新。
            try:
                force_delivery_ui = str(os.getenv("FORCE_DELIVERY_UI", "") or "").strip().lower() in {"1", "true", "yes", "y"}
                spreadsheet_token = client.resolve_spreadsheet_token(
                    wiki_url=wiki_url,
                    spreadsheet_token=(cfg.get("target") or {}).get("spreadsheet_token", ""),
                )
                if force_delivery_ui:
                    _ui_sync_delivery_sheet_fallback(
                        client=client,
                        spreadsheet_token=spreadsheet_token,
                        wiki_url=wiki_url,
                        wiki_password=wiki_password,
                        ui_profile_dir=ui_profile_dir,
                        ui_headless=ui_headless,
                        ui_timeout_ms=ui_timeout_ms,
                        ui_screenshot_enabled=ui_screenshot_enabled,
                        anchor_map=anchor_map,
                        account=str(account or "").strip(),
                        date_str=str(delivery_date_str).strip(),
                        live_id=str(live_id_s).strip(),
                        niu_metrics=niu_metrics,
                    )
                else:
                    try:
                        _sync_delivery_sheet(
                            client=client,
                            spreadsheet_token=spreadsheet_token,
                            anchor_map=anchor_map,
                            account=str(account or "").strip(),
                            date_str=str(delivery_date_str).strip(),
                            live_id=str(live_id_s).strip(),
                            niu_metrics=niu_metrics,
                        )
                        logging.info("delivery_sheet_openapi_done")
                    except Exception as e:
                        if _is_feishu_permission_error(e):
                            logging.warning("delivery_sheet_openapi_forbidden err=%s", e)
                        else:
                            logging.warning("delivery_sheet_openapi_failed err=%s", e)

                        _ui_sync_delivery_sheet_fallback(
                            client=client,
                            spreadsheet_token=spreadsheet_token,
                            wiki_url=wiki_url,
                            wiki_password=wiki_password,
                            ui_profile_dir=ui_profile_dir,
                            ui_headless=ui_headless,
                            ui_timeout_ms=ui_timeout_ms,
                            ui_screenshot_enabled=ui_screenshot_enabled,
                            anchor_map=anchor_map,
                            account=str(account or "").strip(),
                            date_str=str(delivery_date_str).strip(),
                            live_id=str(live_id_s).strip(),
                            niu_metrics=niu_metrics,
                        )
            except Exception as e:
                logging.warning("delivery_sheet_sync_failed err=%s", e)
        else:
            logging.info("skip_delivery_sheet")
        return

    # UI模式去重：从云文档读取已有订单号，而不是使用本地缓存
    ui_seen: Set[str] = set()
    if ui_dedup_enabled and not ui_dedup_reset:
        try:
            # 从云文档读取已有的订单号
            spreadsheet_token = client.resolve_spreadsheet_token(
                wiki_url=wiki_url,
                spreadsheet_token=(cfg.get("target") or {}).get("spreadsheet_token", ""),
            )
            sheets = client.list_sheets(spreadsheet_token)
            sheet_id = ""
            for s in sheets:
                if s.get("title") == sheet_title and s.get("sheet_id"):
                    sheet_id = str(s.get("sheet_id"))
                    break
            if sheet_id:
                dedup_col_index = resolve_dedup_col_index(client, spreadsheet_token, sheet_id, "快手订单号")
                if not dedup_col_index:
                    dedup_col_index = TARGET_COLUMNS.index("快手订单号") + 1
                ui_seen = get_existing_dedup_keys(client, spreadsheet_token, sheet_id, dedup_col_index)
                logging.info("ui_dedup_from_cloud order_count=%d", len(ui_seen))
        except Exception as e:
            logging.warning("ui_dedup_from_cloud_failed err=%s, fallback to local cache", e)
            # 失败时回退到本地缓存
            ui_dedup_path = os.path.join(".state", "feishu_ui_dedup.json")
            ui_dedup = _load_local_ui_dedup(ui_dedup_path)
            ui_key = wiki_url or "(empty_wiki_url)"
            ui_seen = set(map(str, (ui_dedup.get(ui_key) or [])))
    
    to_add_ui = candidate if not ui_dedup_enabled else candidate[~candidate["快手订单号"].isin(ui_seen)].copy()
    if not to_add_ui.empty and "日期" in to_add_ui.columns:
        def _date_key(v: Any) -> int:
            s = str(v or "").strip()
            m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
            if not m:
                m2 = re.search(r"\b\d{4}-(\d{1,2})-(\d{1,2})\b", s)
                if m2:
                    try:
                        return int(m2.group(1)) * 100 + int(m2.group(2))
                    except Exception:
                        return 0
                m3 = re.search(r"\b(\d{1,2})-(\d{1,2})\b", s)
                if m3:
                    try:
                        return int(m3.group(1)) * 100 + int(m3.group(2))
                    except Exception:
                        return 0
                return 0
            try:
                return int(m.group(1)) * 100 + int(m.group(2))
            except Exception:
                return 0

        to_add_ui = to_add_ui.assign(__date_key__=to_add_ui["日期"].map(_date_key)).sort_values(
            by=["__date_key__"], kind="stable"
        )
        try:
            to_add_ui = to_add_ui.drop(columns=["__date_key__"])
        except Exception:
            pass
    values_ui = df_to_values(to_add_ui)
    _append_copy_table_cache_from_values(values_ui)

    if write_mode == "ui":
        if not ui_fallback_enabled:
            raise RuntimeError("write_mode=ui but target.ui_fallback_enabled=false")
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError("write_mode=ui requires Playwright") from e

        # Single UI session: open wiki once, then append 用户对接信息 (if any), then update 投放信息.
        spreadsheet_token = client.resolve_spreadsheet_token(
            wiki_url=wiki_url,
            spreadsheet_token=(cfg.get("target") or {}).get("spreadsheet_token", ""),
        )

        with sync_playwright() as p:
            ctx = None
            try:
                ctx, page = _ui_open_wiki_session(
                    p=p,
                    wiki_url=wiki_url,
                    user_data_dir=ui_profile_dir,
                    headless=ui_headless,
                    timeout_ms=ui_timeout_ms,
                    wiki_password=wiki_password,
                )

                if values_ui:
                    logging.info(
                        "ui_mode_only rows_total=%d rows_to_write=%d ui_dedup_enabled=%s ui_dedup_reset=%s",
                        len(candidate),
                        len(values_ui),
                        ui_dedup_enabled,
                        ui_dedup_reset,
                    )
                    
                    # 对于用户对接信息表，先通过API获取A列（日期列）的最后一个非空行号
                    target_row_number = None
                    if not ui_force_a2:
                        try:
                            sheets = client.list_sheets(spreadsheet_token)
                            sheet_id = ""
                            for s in sheets:
                                if s.get("title") == sheet_title and s.get("sheet_id"):
                                    sheet_id = str(s.get("sheet_id"))
                                    break
                            if sheet_id:
                                # 读取A列的所有数据（日期列）
                                range_str = f"{sheet_id}!A:A"
                                values = client.read_range_values(spreadsheet_token, range_str)
                                # 找到最后一个非空行（跳过表头）
                                last_row = 1  # 默认从第2行开始（第1行是表头）
                                for i, row in enumerate(values):
                                    if i == 0:  # 跳过表头
                                        continue
                                    if row and len(row) > 0 and row[0] is not None and str(row[0]).strip():
                                        last_row = i + 1  # +1因为索引从0开始，行号从1开始
                                target_row_number = last_row + 1  # 在最后一个非空行的下一行开始写入
                                logging.info("ui_mode_detected_last_row=%d target_row=%d", last_row, target_row_number)
                        except Exception as e:
                            logging.warning("ui_mode_detect_last_row_failed err=%s, fallback to keyboard navigation", e)
                    
                    _ui_append_values_on_open_page(
                        page=page,
                        sheet_title=sheet_title,
                        values=values_ui,
                        timeout_ms=ui_timeout_ms,
                        force_a2=ui_force_a2,
                        screenshot_enabled=ui_screenshot_enabled,
                        paste_between_ms=ui_paste_between_ms,
                        paste_apply_wait_ms=ui_paste_apply_wait_ms,
                        target_row_number=target_row_number,
                    )
                    # UI去重现在基于云文档，不再需要保存本地缓存
                    logging.info("ui_append_done")
                else:
                    logging.info("Nothing to append.")

                if not sync_delivery_sheet:
                    logging.info("skip_delivery_sheet")
                    return

                # 投放信息：优先 OpenAPI 写（通常无权限），失败则 UI 插入/更新。
                try:
                    force_delivery_ui = str(os.getenv("FORCE_DELIVERY_UI", "") or "").strip().lower() in {"1", "true", "yes", "y"}
                    if force_delivery_ui:
                        _ui_sync_delivery_sheet_fallback(
                            client=client,
                            spreadsheet_token=spreadsheet_token,
                            wiki_url=wiki_url,
                            wiki_password=wiki_password,
                            ui_profile_dir=ui_profile_dir,
                            ui_headless=ui_headless,
                            ui_timeout_ms=ui_timeout_ms,
                            ui_screenshot_enabled=ui_screenshot_enabled,
                            anchor_map=anchor_map,
                            account=str(account or "").strip(),
                            date_str=str(delivery_date_str).strip(),
                            live_id=str(live_id_s).strip(),
                            niu_metrics=niu_metrics,
                            ui_page=page,
                        )
                    else:
                        try:
                            _sync_delivery_sheet(
                                client=client,
                                spreadsheet_token=spreadsheet_token,
                                anchor_map=anchor_map,
                                account=str(account or "").strip(),
                                date_str=str(delivery_date_str).strip(),
                                live_id=str(live_id_s).strip(),
                                niu_metrics=niu_metrics,
                            )
                            logging.info("delivery_sheet_openapi_done")
                        except Exception as e:
                            if _is_feishu_permission_error(e):
                                logging.warning("delivery_sheet_openapi_forbidden err=%s", e)
                            else:
                                logging.warning("delivery_sheet_openapi_failed err=%s", e)
                            _ui_sync_delivery_sheet_fallback(
                                client=client,
                                spreadsheet_token=spreadsheet_token,
                                wiki_url=wiki_url,
                                wiki_password=wiki_password,
                                ui_profile_dir=ui_profile_dir,
                                ui_headless=ui_headless,
                                ui_timeout_ms=ui_timeout_ms,
                                ui_screenshot_enabled=ui_screenshot_enabled,
                                anchor_map=anchor_map,
                                account=str(account or "").strip(),
                                date_str=str(delivery_date_str).strip(),
                                live_id=str(live_id_s).strip(),
                                niu_metrics=niu_metrics,
                                ui_page=page,
                            )
                except Exception:
                    logging.exception(
                        "delivery_sheet_sync_failed account=%r date_str=%r live_id=%r",
                        str(account or "").strip(),
                        str(delivery_date_str).strip(),
                        str(live_id_s).strip(),
                    )
            finally:
                try:
                    if ctx is not None:
                        ctx.close()
                except Exception:
                    pass
        return


def _ui_sync_delivery_sheet_fallback(
    *,
    client: FeishuClient,
    spreadsheet_token: str,
    wiki_url: str,
    wiki_password: str,
    ui_profile_dir: str,
    ui_headless: bool,
    ui_timeout_ms: int,
    ui_screenshot_enabled: bool,
    anchor_map: pd.DataFrame,
    account: str,
    date_str: str,
    live_id: str,
    niu_metrics: Any,
    ui_page=None,
) -> None:
    account = str(account or "").strip()
    date_str = str(date_str or "").strip()
    
    # 调试日志：打印传入的参数
    logging.info(
        "ui_delivery_fallback_called account=%r date_str=%r live_id=%r",
        account,
        date_str,
        live_id,
    )
    
    # 如果 spreadsheet_token 为空，尝试重新获取
    if not spreadsheet_token or not spreadsheet_token.strip():
        try:
            spreadsheet_token = client.resolve_spreadsheet_token(
                wiki_url=wiki_url,
                spreadsheet_token="",
            )
            logging.info("ui_delivery_resolved_spreadsheet_token token=%s", spreadsheet_token)
        except Exception as e:
            logging.warning("ui_delivery_resolve_token_failed err=%s", e)
            # 如果无法获取 token，则无法使用 OpenAPI 读取数据进行匹配
            # 只能使用 UI 模式直接写入
            pass
    
    if not account or not date_str:
        logging.warning(
            "ui_delivery_skip_missing_identity account=%r date_str=%r live_id=%r",
            account,
            date_str,
            str(live_id or "").strip(),
        )
        return
    if not isinstance(niu_metrics, dict) or not niu_metrics:
        logging.warning(
            "ui_delivery_skip_missing_metrics account=%r date_str=%r metrics_type=%s metrics_keys=%r",
            account,
            date_str,
            type(niu_metrics).__name__,
            sorted(list(niu_metrics.keys())) if isinstance(niu_metrics, dict) else None,
        )
        return

    # Q列：直播状态
    live_id_s = str(live_id or niu_metrics.get("live_id", "") or "").strip()
    is_live_flag = str(niu_metrics.get("is_live", "") or "").strip().lower() in {"1", "true", "yes", "y"}
    status_text = ""
    if is_live_flag:
        status_text = "直播中"
    elif live_id_s:
        status_text = "直播已结束"

    def _norm_acct(s: Any) -> str:
        try:
            t = str(s or "")
        except Exception:
            t = ""
        t = t.strip().lower()
        t = re.sub(r"\s+", "", t)
        return t
    
    def _norm_start_hm(s: Any) -> str:
        """规范化开播时间为 HH:MM 格式"""
        try:
            t = str(s or "").strip()
        except Exception:
            t = ""
        # 移除前导单引号（飞书表格中用于强制文本格式）
        if t.startswith("'"):
            t = t[1:]
        t = t.strip()
        # 匹配 HH:MM 格式
        m = re.search(r"(\d{1,2}):(\d{2})", t)
        if m:
            h = int(m.group(1))
            m_val = int(m.group(2))
            # 规范化为 HH:MM 格式（补零）
            return f"{h:02d}:{m_val:02d}"
        return ""

    def _date_key(v: Any) -> int:
        s = str(v or "").strip()
        
        # 尝试解析 Excel 日期序列号（如 46086）
        # Excel 的日期序列号从 1900-01-01 开始计数
        if s.isdigit() and len(s) == 5:  # Excel 日期序列号通常是 5 位数
            try:
                excel_serial = int(s)
                # 将 Excel 序列号转换为日期
                # Excel 从 1900-01-01 开始，但有个 bug：1900 年被错误地当作闰年
                # Python datetime 从 1899-12-30 开始计数可以兼容 Excel
                from datetime import datetime, timedelta
                base_date = datetime(1899, 12, 30)
                target_date = base_date + timedelta(days=excel_serial)
                return target_date.month * 100 + target_date.day
            except Exception:
                pass
        
        # 原有的日期格式解析
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
        if not m:
            m2 = re.search(r"\b\d{4}-(\d{1,2})-(\d{1,2})\b", s)
            if m2:
                try:
                    return int(m2.group(1)) * 100 + int(m2.group(2))
                except Exception:
                    return 0
            m3 = re.search(r"\b(\d{1,2})-(\d{1,2})\b", s)
            if m3:
                try:
                    return int(m3.group(1)) * 100 + int(m3.group(2))
                except Exception:
                    return 0
            return 0
        try:
            return int(m.group(1)) * 100 + int(m.group(2))
        except Exception:
            return 0

    want_date_key = _date_key(date_str)
    want_acct = _norm_acct(account)
    want_start_hm = _norm_start_hm(_pick_start_hm(niu_metrics))
    
    logging.info(
        "delivery_match_target date_str=%r date_key=%d acct=%r start_hm=%r",
        date_str,
        want_date_key,
        account,
        want_start_hm,
    )

    force_delivery_insert = str(os.getenv("FORCE_DELIVERY_INSERT", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }

    # Locate rows using OpenAPI READ.
    sheets = client.list_sheets(spreadsheet_token)
    delivery_sheet_id = ""
    for s in sheets:
        if s.get("title") == "投放信息" and s.get("sheet_id"):
            delivery_sheet_id = str(s.get("sheet_id"))
            break
    if not delivery_sheet_id:
        raise RuntimeError("Cannot find sheet titled 投放信息")

    max_rows = 5000
    rng = f"{delivery_sheet_id}!A1:P{max_rows}"
    values = client.read_range_values(spreadsheet_token, rng)
    if not values:
        raise RuntimeError("投放信息 sheet empty")

    # Resolve column indices from header row (row 1) to be robust to any past column shifts.
    header = values[0] if values else []
    header_map: Dict[str, int] = {}
    for idx0, v in enumerate(header or []):
        t = str(v).strip() if v is not None else ""
        if not t:
            continue
        header_map.setdefault(t, idx0)

    idx_date = header_map.get("日期", 0)
    idx_start = header_map.get("开播时间", 1)
    idx_live = header_map.get("直播间ID", 2)
    idx_acct = header_map.get("账号", 3)
    idx_kid = header_map.get("快手ID", 4)
    idx_anchor = header_map.get("主播", 5)
    idx_orders = header_map.get("单量", 6)
    idx_cost = header_map.get("消耗", 7)

    def _is_blank_identity_row(row: List[Any]) -> bool:
        # Blank means identity columns are empty: 日期/开播时间/直播间ID/账号/快手ID/主播
        for idx0 in [idx_date, idx_start, idx_live, idx_acct, idx_kid, idx_anchor]:
            try:
                if str(row[idx0]).strip():
                    return False
            except Exception:
                continue
        return True

    def _pick_blank_row_1(*, summary_row_1: int, summary_visible_in_api: bool) -> int:
        # Prefer a blank row immediately above 汇总 (but not 汇总 itself). If not visible, just pick the last blank row.
        if summary_visible_in_api and summary_row_1 > 2:
            for r1 in range(int(summary_row_1) - 1, 1, -1):
                row = values[r1 - 1] if (r1 - 1) < len(values) else []
                if _is_blank_identity_row(row):
                    return r1
            return 0
        # No summary row in API: scan all returned rows from bottom.
        for r1 in range(len(values), 1, -1):
            row = values[r1 - 1] if (r1 - 1) < len(values) else []
            if _is_blank_identity_row(row):
                return r1
        return 0

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

    summary_row_1 = 0
    for i, row in enumerate(values, start=1):
        found = False
        for c in (row or []):
            try:
                t = str(c).strip()
            except Exception:
                t = ""
            if not t:
                continue
            if t == "汇总" or ("汇总" in t):
                found = True
                break
        if found:
            summary_row_1 = i
            break
    summary_visible_in_api = summary_row_1 > 0
    logging.info(
        "delivery_api_read rows=%d summary_visible=%s summary_row_1=%d",
        len(values),
        bool(summary_visible_in_api),
        int(summary_row_1 or 0),
    )

    target_row_1 = 0
    # If summary isn't visible via API (merged/styled), don't trust row positions from API.
    # We'll let UI locate 汇总 and pick the row above it.
    if summary_visible_in_api:
        scan_end = summary_row_1
        for i in range(2, scan_end):
            row = values[i - 1] if i - 1 < len(values) else []
            row_date_key = _date_key(_cell(row, idx_date))
            row_acct = _norm_acct(_cell(row, idx_acct))
            row_start_hm = _norm_start_hm(_cell(row, idx_start))
            
            # 匹配规则：日期 + 账号 + 开播时间 三者都相同
            is_match = (
                row_acct and 
                (want_acct == row_acct) and 
                (want_date_key and want_date_key == row_date_key) and
                (want_start_hm and want_start_hm == row_start_hm)
            )
            
            # 调试日志
            if i >= scan_end - 6:
                logging.info(
                    "delivery_match_check r=%d row_date=%r row_date_key=%d want_date_key=%d row_acct=%r want_acct=%r row_start_hm=%r want_start_hm=%r match=%s",
                    i,
                    _cell(row, idx_date),
                    row_date_key,
                    want_date_key,
                    row_acct,
                    want_acct,
                    row_start_hm,
                    want_start_hm,
                    bool(is_match),
                )
            
            if is_match:
                target_row_1 = i
                break
    else:
        # Even if 汇总 isn't visible in API, try to locate an existing matching row.
        # This prevents duplicates when the sheet already contains (日期,账号,开播时间).
        for i in range(2, len(values) + 1):
            row = values[i - 1] if i - 1 < len(values) else []
            if not row:
                continue
            row_date_key = _date_key(_cell(row, idx_date))
            row_acct = _norm_acct(_cell(row, idx_acct))
            row_start_hm = _norm_start_hm(_cell(row, idx_start))
            
            # 匹配规则：日期 + 账号 + 开播时间 三者都相同
            is_match = (
                row_acct and 
                (want_acct == row_acct) and 
                (want_date_key and want_date_key == row_date_key) and
                (want_start_hm and want_start_hm == row_start_hm)
            )
            
            # 调试日志
            if i <= 10:
                logging.info(
                    "delivery_match_check_no_summary r=%d row_date=%r row_date_key=%d want_date_key=%d row_acct=%r want_acct=%r row_start_hm=%r want_start_hm=%r match=%s",
                    i,
                    _cell(row, idx_date),
                    row_date_key,
                    want_date_key,
                    row_acct,
                    want_acct,
                    row_start_hm,
                    want_start_hm,
                    bool(is_match),
                )
            
            if is_match:
                target_row_1 = i
                break

    insert_above_row_1 = 0
    if target_row_1 <= 0:
        if summary_visible_in_api:
            if force_delivery_insert:
                insert_above_row_1 = int(summary_row_1)
                target_row_1 = int(summary_row_1)
            else:
                # 从上往下查找第一个空行（占位符行）
                # 占位符行的判断：关键字段为空（开播时间/直播间ID/账号/快手ID/主播）
                def _is_placeholder(row: List[Any]) -> bool:
                    # Reusable row:
                    # identity columns must be empty: 开播时间/直播间ID/账号/快手ID/主播
                    # 日期 may already be filled (many sheets pre-fill 日期 on blank lines).
                    for idx0 in [idx_start, idx_live, idx_acct, idx_kid, idx_anchor]:
                        try:
                            if _cell(row, idx0):
                                return False
                        except Exception:
                            continue
                    return True

                picked = 0
                # 从下往上扫描（从汇总行上一行往上找），避免批量更新时多次命中同一个“第一个空行”导致覆盖。
                for r1 in range(int(summary_row_1) - 1, 1, -1):
                    row = values[r1 - 1] if (r1 - 1) < len(values) else []
                    is_placeholder = (not row) or _is_placeholder(row)
                    
                    # 调试日志：显示前几行和汇总前几行
                    if r1 <= 5 or r1 >= int(summary_row_1) - 3:
                        try:
                            logging.info(
                                "delivery_scan r=%d start=%r live=%r acct=%r kid=%r anchor=%r is_placeholder=%s",
                                int(r1),
                                _cell(row, idx_start),
                                _cell(row, idx_live),
                                _cell(row, idx_acct),
                                _cell(row, idx_kid),
                                _cell(row, idx_anchor),
                                bool(is_placeholder),
                            )
                        except Exception:
                            pass
                    
                    if is_placeholder:
                        picked = r1
                        break  # 找到第一个空行就停止
                
                if picked > 0:
                    # 计算空行到汇总行的距离
                    distance_to_summary = int(summary_row_1) - picked
                    # 如果空行离汇总行太近（<=2行），则插入新行以保持缓冲
                    # 这样可以避免很快就会覆盖汇总行
                    if distance_to_summary <= 2:
                        logging.info(
                            "delivery_near_summary picked=%d summary=%d distance=%d, will insert new row",
                            picked,
                            int(summary_row_1),
                            distance_to_summary,
                        )
                        insert_above_row_1 = int(summary_row_1)
                        target_row_1 = int(summary_row_1)
                    else:
                        target_row_1 = picked
                else:
                    # No placeholder row available above 汇总 -> request UI insertion above 汇总.
                    insert_above_row_1 = int(summary_row_1)
                    target_row_1 = int(summary_row_1)
        else:
            # OpenAPI cannot see 汇总 reliably; do not guess a row.
            # UI will locate 汇总 and write to (汇总-1). If that row isn't blank,
            # hard safety check will prevent writing into 汇总 or below.
            insert_above_row_1 = 0
            target_row_1 = 0

    # Never allow writing into summary row or below it.
    # Exception: when we explicitly request inserting a new blank row above 汇总,
    # we pass target_row_1==insert_above_row_1==summary_row_1 to mean "write into the new row".
    if summary_visible_in_api and int(target_row_1) >= int(summary_row_1):
        if not (int(insert_above_row_1 or 0) == int(summary_row_1) and int(target_row_1) == int(summary_row_1)):
            target_row_1 = 0

    start_hm = _pick_start_hm(niu_metrics)
    if start_hm:
        # Force display as HH:MM text (avoid being rendered as date/float by cell format).
        start_hm = "'" + start_hm
    direct_orders = _parse_num(niu_metrics.get("direct_orders", ""))
    cost = _parse_num(niu_metrics.get("cost", ""))
    anchor_info = _anchor_info_by_account(anchor_map, account)

    if target_row_1 > 0:
        # 找到已存在的行，直接替换单量和消耗，不累加
        pass

    # Write row values aligned to A:P columns (fixed by sheet header).
    values_row = [
        date_str,
        start_hm,
        str(live_id or niu_metrics.get("live_id", "") or "").strip(),
        account,
        anchor_info.get("快手ID", ""),
        anchor_info.get("主播", ""),
        "",  # G列（单量）留空，不编辑
        _fmt_num(cost, decimals=2),
    ]

    # 保持原有逻辑：只有直播中才编辑/新增投放信息内容。
    if is_live_flag:
        _ui_upsert_delivery_row_via_wiki(
            wiki_url=wiki_url,
            delivery_sheet_query_id=delivery_sheet_id,
            delivery_sheet_title="投放信息",
            values_row=values_row,
            target_row_1=target_row_1,
            insert_above_row_1=insert_above_row_1,
            expected_summary_row_1=int(summary_row_1 or 0),
            user_data_dir=ui_profile_dir,
            headless=ui_headless,
            timeout_ms=ui_timeout_ms,
            wiki_password=wiki_password,
            screenshot_enabled=True,
            page=ui_page,
            client=client,
            spreadsheet_token=spreadsheet_token,
        )
        logging.info("delivery_sheet_ui_upserted row=%d", target_row_1)

    # Q列直播状态：对所有金牛获取到的数据都回写。
    # 注意：为了不影响其它列数据，这里用 OpenAPI 单独更新 Q 列单元格。
    try:
        if status_text:
            row_1_to_write = 0
            if target_row_1 > 0:
                row_1_to_write = int(target_row_1)
            elif insert_above_row_1 > 0:
                row_1_to_write = int(insert_above_row_1)

            if row_1_to_write > 0:
                update_rng_q = f"{delivery_sheet_id}!Q{row_1_to_write}:Q{row_1_to_write}"
                client.update_values(spreadsheet_token, update_rng_q, [[status_text]])
                logging.info("delivery_status_updated row=%d status=%s", row_1_to_write, status_text)
            else:
                logging.info("delivery_status_skip_no_row account=%s live_id=%s status=%s", account, live_id_s, status_text)
    except Exception as e:
        logging.warning("delivery_status_update_failed account=%s err=%s", account, e)
    return

    if write_mode not in {"api", "auto"}:
        raise RuntimeError(f"Invalid target.write_mode={write_mode!r}. Use api/ui/auto")

    try:
        spreadsheet_token = client.resolve_spreadsheet_token(
            wiki_url=wiki_url,
            spreadsheet_token=(cfg.get("target") or {}).get("spreadsheet_token", ""),
        )

        sheet_title = sheet_title
        sheet_id_cfg = sheet_id_cfg

        sheets = client.list_sheets(spreadsheet_token)
        sheet_ids = {str(s.get("sheet_id")) for s in sheets if s.get("sheet_id")}

        sheet_id = ""
        if sheet_id_cfg and str(sheet_id_cfg) in sheet_ids:
            sheet_id = str(sheet_id_cfg)
        else:
            for s in sheets:
                if s.get("title") == sheet_title and s.get("sheet_id"):
                    sheet_id = str(s.get("sheet_id"))
                    break
            if not sheet_id:
                raise RuntimeError(
                    f"Cannot find sheet by title={sheet_title}. Available: {[s.get('title') for s in sheets]}"
                )

            cfg.setdefault("target", {})
            cfg["target"]["sheet_id"] = sheet_id
            if not (cfg["target"].get("spreadsheet_token") or "").strip():
                cfg["target"]["spreadsheet_token"] = spreadsheet_token
            save_json(args.config, cfg)
            logging.info("Updated config sheet_id=%s spreadsheet_token=%s", sheet_id, spreadsheet_token)

        dedup_col_index = resolve_dedup_col_index(client, spreadsheet_token, sheet_id, "快手订单号")
        if not dedup_col_index:
            dedup_col_index = TARGET_COLUMNS.index("快手订单号") + 1
        existing = get_existing_dedup_keys(client, spreadsheet_token, sheet_id, dedup_col_index)
        logging.info("existing_dedup_keys=%d", len(existing))

        norm_df["快手订单号"] = norm_df["快手订单号"].astype(str).str.strip()
        to_add2 = norm_df[~norm_df["快手订单号"].isin(existing) & norm_df["快手订单号"].ne("")].copy()
        if not to_add2.empty and "日期" in to_add2.columns:
            def _date_key(v: Any) -> int:
                s = str(v or "").strip()
                m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
                if not m:
                    m2 = re.search(r"\b\d{4}-(\d{1,2})-(\d{1,2})\b", s)
                    if m2:
                        try:
                            return int(m2.group(1)) * 100 + int(m2.group(2))
                        except Exception:
                            return 0
                    m3 = re.search(r"\b(\d{1,2})-(\d{1,2})\b", s)
                    if m3:
                        try:
                            return int(m3.group(1)) * 100 + int(m3.group(2))
                        except Exception:
                            return 0
                    return 0
                try:
                    return int(m.group(1)) * 100 + int(m.group(2))
                except Exception:
                    return 0

            to_add2 = to_add2.assign(__date_key__=to_add2["日期"].map(_date_key)).sort_values(
                by=["__date_key__"], kind="stable"
            )
            try:
                to_add2 = to_add2.drop(columns=["__date_key__"])
            except Exception:
                pass
        logging.info("input_rows=%d normalized_rows=%d to_append=%d", len(raw_df), len(norm_df), len(to_add2))
        if to_add2.empty:
            logging.info("Nothing to append.")
            return

        values2 = df_to_values(to_add2)

        # 需求变更：不填写 G 列（主播）。
        # 这里使用 update_values 按行段写入 A:F + “直播账号”列 + “备注”列。
        # 如果表头无法判断“直播账号”，默认回退写入 H 列（即按固定列跳过主播列）。
        start_row_1 = int(detect_last_non_empty_row_in_col(client, spreadsheet_token, sheet_id, int(dedup_col_index), max_rows=5000)) + 1
        _api_update_user_contact_rows_skip_anchor(
            client=client,
            spreadsheet_token=spreadsheet_token,
            sheet_id=sheet_id,
            start_row=int(start_row_1),
            values=values2,
        )
        logging.info("append_response=skipped (use update_values skip_anchor) start_row=%d rows=%d", int(start_row_1), len(values2))

        # 投放信息：按 日期+账号 累加更新；无则在“汇总”行上方插入。
        # Only attempt when we have account + niu_metrics.
        try:
            _sync_delivery_sheet(
                client=client,
                spreadsheet_token=spreadsheet_token,
                anchor_map=anchor_map,
                account=str(account or "").strip(),
                date_str=str(norm_df.iloc[0].get("日期", "") if not norm_df.empty else "").strip(),
                live_id=str(live_id_s).strip(),
                niu_metrics=niu_metrics,
            )
        except Exception as e:
            logging.warning("delivery_sheet_sync_failed err=%s", e)
        return
    except Exception as e:
        if write_mode == "api":
            raise
        if not (_is_feishu_permission_error(e) and ui_fallback_enabled):
            raise
        logging.warning("OpenAPI permission error, falling back to UI append. err=%s", e)

    if not values_ui:
        logging.info("Nothing to append.")
        return
    
    # 使用API读取表格，找到A列（日期列）最后一个非空行的下一行
    target_row = 2  # 默认从第2行开始（第1行是标题）
    try:
        # 读取日期列（A列）的所有数据
        col_a_range = f"{sheet_id}!A1:A5000"
        col_a_values = client.read_range_values(spreadsheet_token, col_a_range)
        
        # 从后往前找最后一个非空行
        for i in range(len(col_a_values) - 1, 0, -1):  # 从最后一行往前找，跳过表头
            row = col_a_values[i]
            if row and len(row) > 0 and row[0] is not None and str(row[0]).strip():
                target_row = i + 2  # i是0-based索引，+1转换为行号，再+1是下一行
                break
        
        logging.info("ui_append_target_row=%d (last_non_empty_row=%d)", target_row, target_row - 1)
    except Exception as e:
        logging.warning("ui_append_find_target_row_failed err=%s, will use default row 2", e)
        target_row = 2
    
    _ui_append_values_via_wiki(
        wiki_url=wiki_url,
        sheet_title=sheet_title,
        values=values_ui,
        user_data_dir=ui_profile_dir,
        headless=ui_headless,
        timeout_ms=ui_timeout_ms,
        wiki_password=wiki_password,
        force_a2=ui_force_a2,
        screenshot_enabled=ui_screenshot_enabled,
        paste_between_ms=ui_paste_between_ms,
        paste_apply_wait_ms=ui_paste_apply_wait_ms,
        target_row=target_row,
    )
    # UI去重现在基于云文档，不再需要保存本地缓存
    logging.info("ui_fallback_append_done")


def _parse_num(s: Any) -> float:
    try:
        t = str(s).strip().replace(",", "")
        if not t:
            return 0.0
        return float(t)
    except Exception:
        return 0.0


def _fmt_num(v: float, *, decimals: int = 2) -> str:
    try:
        if decimals <= 0:
            return str(int(round(v)))
        return f"{v:.{decimals}f}"
    except Exception:
        return str(v)


def _to_number_if_numeric(s: Any) -> Any:
    """如果字符串是纯数字，转换为数字类型；否则保持原样"""
    if s is None or s == "":
        return s
    
    s_str = str(s).strip()
    if not s_str:
        return s_str
    
    # 尝试转换为整数
    try:
        # 检查是否是纯数字（不包含小数点）
        if s_str.isdigit():
            return int(s_str)
    except:
        pass
    
    # 尝试转换为浮点数
    try:
        # 检查是否包含小数点
        if '.' in s_str:
            return float(s_str)
    except:
        pass
    
    # 无法转换，保持原样
    return s_str


def _extract_hm(start_dt: str) -> str:
    s = str(start_dt or "").strip()
    if not s:
        return ""
    m = re.search(r"\b(\d{2}):(\d{2}):\d{2}\b", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"\b(\d{2}):(\d{2})\b", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return ""


def _pick_start_hm(niu_metrics: Any) -> str:
    if isinstance(niu_metrics, dict):
        v = str(niu_metrics.get("start_hm", "") or "").strip()
        if v and re.fullmatch(r"\d{2}:\d{2}", v):
            return v
        v2 = str(niu_metrics.get("start_dt", "") or "").strip()
        hm = _extract_hm(v2)
        if hm:
            return hm
    return ""


def _anchor_info_by_account(anchor_map: pd.DataFrame, account: str) -> Dict[str, str]:
    out: Dict[str, str] = {"快手ID": "", "主播": ""}
    if anchor_map is None or anchor_map.empty:
        return out
    amap = anchor_map.copy()
    amap.columns = [c.strip() for c in amap.columns]
    if "直播账号" not in amap.columns:
        return out
    m = amap[amap["直播账号"].astype(str).str.strip() == str(account).strip()]
    if m.empty:
        return out
    r0 = m.iloc[0]
    if "快手ID" in amap.columns:
        out["快手ID"] = str(r0.get("快手ID", "") or "").strip()
    if "主播" in amap.columns:
        out["主播"] = str(r0.get("主播", "") or "").strip()
    return out


def _sync_delivery_sheet(
    *,
    client: FeishuClient,
    spreadsheet_token: str,
    anchor_map: pd.DataFrame,
    account: str,
    date_str: str,
    live_id: str,
    niu_metrics: Any,
) -> None:
    account = str(account or "").strip()
    date_str = str(date_str or "").strip()
    if not account or not date_str:
        return
    if not isinstance(niu_metrics, dict) or not niu_metrics:
        return

    # Q列：直播状态
    live_id_s = str(live_id or niu_metrics.get("live_id", "") or "").strip()
    is_live_flag = str(niu_metrics.get("is_live", "") or "").strip().lower() in {"1", "true", "yes", "y"}
    status_text = ""
    if is_live_flag:
        status_text = "直播中"
    elif live_id_s:
        status_text = "直播已结束"

    # Resolve 投放信息 sheet id.
    sheets = client.list_sheets(spreadsheet_token)
    delivery_sheet_id = ""
    for s in sheets:
        if s.get("title") == "投放信息" and s.get("sheet_id"):
            delivery_sheet_id = str(s.get("sheet_id"))
            break
    if not delivery_sheet_id:
        raise RuntimeError("Cannot find sheet titled 投放信息")

    # Read a window of rows to locate 汇总 and existing daily row.
    max_rows = 5000
    rng = f"{delivery_sheet_id}!A1:P{max_rows}"
    values = client.read_range_values(spreadsheet_token, rng)
    if not values:
        raise RuntimeError("投放信息 sheet empty")

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
    
    def _parse_excel_date(val: str) -> str:
        """将 Excel 日期序列号转换为 'X月X日' 格式"""
        try:
            # 检查是否是数字
            days = float(val)
            if days < 1 or days > 100000:
                return ""
            
            from datetime import datetime, timedelta
            # Excel 的起始日期是 1899-12-30（因为1900年闰年bug）
            base_date = datetime(1899, 12, 30)
            target_date = base_date + timedelta(days=days)
            
            # 返回 "X月X日" 格式
            return f"{target_date.month}月{target_date.day}日"
        except Exception:
            return ""
    
    def _parse_excel_time(val: str) -> str:
        """将 Excel 时间序列号转换为 HH:MM:SS 格式"""
        try:
            # 检查是否是小数
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
        """将 'X月X日' 格式转换为 Excel 日期序列号"""
        try:
            import re
            from datetime import datetime
            
            # 解析 "X月X日" 格式
            m = re.search(r"(\d+)月(\d+)日", date_str)
            if not m:
                return 0
            
            month = int(m.group(1))
            day = int(m.group(2))
            
            # 假设是当前年份
            from datetime import datetime
            now = datetime.now()
            year = now.year
            
            # 创建日期对象
            target_date = datetime(year, month, day)
            
            # 计算与 Excel 起始日期的天数差
            base_date = datetime(1899, 12, 30)
            delta = target_date - base_date
            
            return float(delta.days)
        except Exception:
            return 0
    
    def _to_excel_time(time_str: str) -> float:
        """将 'HH:MM' 或 'HH:MM:SS' 格式转换为 Excel 时间序列号"""
        try:
            import re
            
            # 解析 "HH:MM:SS" 或 "HH:MM" 格式
            m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", time_str)
            if not m:
                return 0
            
            hours = int(m.group(1))
            minutes = int(m.group(2))
            seconds = int(m.group(3)) if m.group(3) else 0
            
            # 转换为一天中的小数部分
            total_seconds = hours * 3600 + minutes * 60 + seconds
            fraction = total_seconds / (24 * 3600)
            
            return fraction
        except Exception:
            return 0

    summary_row_1 = 0
    for i, row in enumerate(values, start=1):
        if _cell(row, 0) == "汇总":
            summary_row_1 = i
            break
    if summary_row_1 <= 0:
        raise RuntimeError("Cannot find 汇总 row in 投放信息")

    # columns: A 日期, B 开播时间, C 直播间ID, D 账号, E 快手ID, F 主播, G 单量, H 消耗
    
    # 获取要匹配的开播时间
    start_hm = _extract_hm(str(niu_metrics.get("start_dt", "") or ""))
    if not start_hm:
        start_hm = str(niu_metrics.get("start_hm", "") or "").strip()
    
    def _norm_start_hm(s: str) -> str:
        """规范化开播时间为 HH:MM:SS 格式"""
        t = s.strip()
        if t.startswith("'"):
            t = t[1:]
        t = t.strip()
        # 尝试匹配 HH:MM:SS 格式
        m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", t)
        if m:
            h = int(m.group(1))
            m_val = int(m.group(2))
            s_val = int(m.group(3)) if m.group(3) else 0
            return f"{h:02d}:{m_val:02d}:{s_val:02d}"
        return ""
    
    want_start_hm = _norm_start_hm(start_hm)
    
    def _fuzzy_account_match(want_acct: str, row_acct: str) -> bool:
        """模糊匹配账号名称（去除表情符号等装饰字符）"""
        if not want_acct or not row_acct:
            return False
        
        # 完全匹配
        if want_acct == row_acct:
            return True
        
        # 移除常见的装饰字符（表情符号、特殊符号等）
        import re
        
        # 提取纯文本部分（移除表情符号和特殊符号）
        def _extract_core_text(s: str) -> str:
            # 移除表情符号（Unicode范围）
            s = re.sub(r'[\U0001F300-\U0001F9FF]', '', s)  # 表情符号
            s = re.sub(r'[\u2600-\u26FF]', '', s)  # 杂项符号
            s = re.sub(r'[\u2700-\u27BF]', '', s)  # 装饰符号
            # 移除常见装饰字符
            s = re.sub(r'[🌺🌸🌹🌻🌼🌷💐🎀🎁⭐✨💫🔥💯👍❤️💕💖]', '', s)
            # 移除空格和特殊符号
            s = re.sub(r'[\s\-_\.~`!@#$%^&*()+=\[\]{}|;:\'",<>?/\\]', '', s)
            return s.strip().lower()
        
        want_core = _extract_core_text(want_acct)
        row_core = _extract_core_text(row_acct)
        
        # 核心文本必须完全匹配（不允许部分匹配）
        if want_core and row_core and want_core == row_core:
            return True
        
        return False
    
    # 匹配规则优先级：
    # 1. 优先查找精确匹配：日期 + 账号 + 开播时间都相同
    # 2. 如果没有精确匹配，再查找待播数据：日期 + 账号相同但没有直播间ID
    target_row_1 = 0
    pending_row_1 = 0  # 待播数据行号
    
    logging.info(
        "delivery_match_search want_date=%r want_acct=%r want_start_hm=%r",
        date_str,
        account,
        want_start_hm,
    )
    
    # 调试：如果是井味味，打印所有行的详细信息
    debug_jingweiwei = (account == "井味味")
    if debug_jingweiwei:
        logging.info("=== DEBUG: 井味味 matching debug start ===")
        logging.info("DEBUG: summary_row_1=%d, will scan rows 2-%d", summary_row_1, summary_row_1 - 1)
    
    for i in range(2, summary_row_1):
        row = values[i - 1] if i - 1 < len(values) else []
        row_date_raw = _cell(row, 0)
        row_acct = _cell(row, 3)
        row_live_id = _cell(row, 2)  # 直播间ID
        row_start_time_raw = _cell(row, 1)
        
        # 调试：如果是井味味，打印每一行的信息
        if debug_jingweiwei and row_acct:
            logging.info("DEBUG: row=%d date_raw=%r acct=%r live_id=%r time_raw=%r", 
                        i, row_date_raw, row_acct, row_live_id, row_start_time_raw)
        
        # 尝试解析 Excel 日期格式
        row_date = row_date_raw
        if row_date and row_date.replace('.', '').replace('-', '').isdigit():
            parsed_date = _parse_excel_date(row_date)
            if parsed_date:
                row_date = parsed_date
        
        # 尝试解析 Excel 时间格式
        row_start_hm = _norm_start_hm(row_start_time_raw)
        if not row_start_hm and '.' in row_start_time_raw:
            parsed_time = _parse_excel_time(row_start_time_raw)
            if parsed_time:
                row_start_hm = parsed_time
        
        # 检查是否是待播数据（没有直播间ID）
        is_pending = not row_live_id or row_live_id.strip() == "" or row_live_id.lower() in {"none", "null"}
        
        # 日期匹配
        date_match = (row_date == date_str)
        
        # 开播时间匹配（允许1分钟误差）
        time_match = False
        if want_start_hm and row_start_hm:
            # 解析时间为分钟数进行比较
            def _time_to_minutes(t: str) -> int:
                try:
                    parts = t.split(':')
                    h = int(parts[0])
                    m = int(parts[1])
                    return h * 60 + m
                except:
                    return -1
            
            want_minutes = _time_to_minutes(want_start_hm)
            row_minutes = _time_to_minutes(row_start_hm)
            
            # 允许1分钟误差
            if want_minutes >= 0 and row_minutes >= 0:
                time_match = abs(want_minutes - row_minutes) <= 1
        
        # 账号匹配
        account_match_exact = (row_acct == account)
        account_match_fuzzy = _fuzzy_account_match(account, row_acct)
        
        # 调试：如果是井味味，打印匹配结果
        if debug_jingweiwei and (date_match or account_match_exact or account_match_fuzzy):
            logging.info("DEBUG: row=%d date_match=%s acct_exact=%s acct_fuzzy=%s time_match=%s is_pending=%s",
                        i, date_match, account_match_exact, account_match_fuzzy, time_match, is_pending)
        
        # 优先级1：精确匹配（日期 + 账号 + 开播时间）
        if date_match and account_match_exact and time_match:
            target_row_1 = i
            logging.info(
                "delivery_openapi_match_found row=%d date=%r acct=%r start_hm=%r live_id=%r",
                i,
                row_date,
                row_acct,
                row_start_hm,
                row_live_id,
            )
            # 找到精确匹配，立即使用，不再查找待播数据
            break
        
        # 优先级2：待播数据（日期 + 账号，但没有直播间ID）
        if is_pending and date_match and account_match_fuzzy:
            # 只记录第一个待播数据，继续查找是否有精确匹配
            if pending_row_1 == 0:
                pending_row_1 = i
                logging.info(
                    "delivery_pending_match_found row=%d date=%r acct=%r (fuzzy match: %r) row_time=%r live_id=empty",
                    i,
                    row_date,
                    row_acct,
                    account,
                    row_start_hm,
                )
        
        # 调试日志：显示待播数据的匹配情况
        if is_pending and i <= 110 and i >= 100:  # 只显示第100-110行
            logging.info(
                "delivery_pending_check row=%d is_pending=%s date=%r(%r) acct=%r time=%r(%r) date_match=%s acct_match=%s",
                i,
                is_pending,
                row_date,
                row_date_raw,
                row_acct,
                row_start_hm,
                row_start_time_raw,
                date_match,
                account_match_fuzzy,
            )
    
    # 调试：如果是井味味，打印最终结果
    if debug_jingweiwei:
        logging.info("=== DEBUG: 井味味 matching result: target_row_1=%d, pending_row_1=%d ===", 
                    target_row_1, pending_row_1)
    
    # 如果没有精确匹配，使用待播数据行
    if target_row_1 == 0 and pending_row_1 > 0:
        target_row_1 = pending_row_1
        logging.info(
            "delivery_use_pending_row row=%d (no exact match, using pending data)",
            pending_row_1,
        )
    
    if target_row_1 == 0:
        logging.info(
            "delivery_openapi_no_match date=%r acct=%r start_hm=%r, will create new row",
            date_str,
            account,
            want_start_hm,
        )

    direct_orders = _parse_num(niu_metrics.get("direct_orders", ""))
    cost = _parse_num(niu_metrics.get("cost", ""))
    anchor_info = _anchor_info_by_account(anchor_map, account)

    if target_row_1 > 0:
        row = values[target_row_1 - 1] if target_row_1 - 1 < len(values) else []
        
        # 直接替换单量和消耗，不累加
        new_orders = direct_orders
        new_cost = cost

        # Keep existing fields unless empty.
        b_raw = _cell(row, 1)
        c = _cell(row, 2) or str(live_id or niu_metrics.get("live_id", "") or "").strip()
        e = _cell(row, 4) or anchor_info.get("快手ID", "")
        f = _cell(row, 5) or anchor_info.get("主播", "")
        
        # 处理开播时间：优先使用新的 start_hm，否则使用现有值
        time_to_use = start_hm or b_raw
        
        # 转换为 Excel 格式
        excel_date = _to_excel_date(date_str)
        excel_time = _to_excel_time(time_to_use) if time_to_use else 0
        
        # 如果是 Excel 小数格式，直接使用
        if time_to_use and '.' in time_to_use and time_to_use.replace('.', '').replace('-', '').isdigit():
            try:
                excel_time = float(time_to_use)
            except:
                pass
        
        write_row = [
            excel_date if excel_date > 0 else date_str,  # A: 日期
            excel_time if excel_time > 0 else time_to_use,  # B: 开播时间（Excel 小数格式）
            _to_number_if_numeric(c),  # C: 直播间ID（纯数字转为数字类型）
            account,  # D: 账号
            _to_number_if_numeric(e),  # E: 快手ID（纯数字转为数字类型）
            f,  # F: 主播
        ]
        
        # 保持原有逻辑：只有直播中才编辑投放信息内容。
        if is_live_flag:
            # 更新 A-F 列（不包括 G 列单量）
            update_rng_af = f"{delivery_sheet_id}!A{target_row_1}:F{target_row_1}"
            client.update_values(spreadsheet_token, update_rng_af, [write_row])
        
            # 设置居中对齐
            try:
                client.set_cell_alignment(
                    spreadsheet_token=spreadsheet_token,
                    sheet_id=delivery_sheet_id,
                    range_a1=f"A{target_row_1}:F{target_row_1}",
                    h_align=2,  # 2=居中
                    v_align=2,  # 2=居中
                )
                logging.info(f"delivery_alignment_set_success row={target_row_1} range=A:F")
            except Exception as e:
                logging.warning(f"Failed to set alignment for row {target_row_1}: {e}")
        
            # 单独更新 H 列（消耗）- 使用数字类型而不是字符串
            update_rng_h = f"{delivery_sheet_id}!H{target_row_1}:H{target_row_1}"
            client.update_values(spreadsheet_token, update_rng_h, [[new_cost]])  # 直接使用数字
        
            # 设置 H 列居中对齐
            try:
                client.set_cell_alignment(
                    spreadsheet_token=spreadsheet_token,
                    sheet_id=delivery_sheet_id,
                    range_a1=f"H{target_row_1}:H{target_row_1}",  # 使用范围格式
                    h_align=2,  # 2=居中
                    v_align=2,  # 2=居中
                )
                logging.info(f"delivery_alignment_set_success row={target_row_1} range=H")
            except Exception as e:
                logging.warning(f"Failed to set alignment for H{target_row_1}: {e}")
        
        # Q列直播状态：对所有金牛获取到的数据都回写。
        if status_text:
            try:
                update_rng_q = f"{delivery_sheet_id}!Q{target_row_1}:Q{target_row_1}"
                client.update_values(spreadsheet_token, update_rng_q, [[status_text]])
                logging.info("delivery_status_updated row=%d status=%s", target_row_1, status_text)
            except Exception as e:
                logging.warning("delivery_status_update_failed row=%d err=%s", target_row_1, e)

        logging.info("delivery_sheet_updated row=%d date=%s account=%s", target_row_1, date_str, account)
        return

    # Insert before 汇总.
    # 保持原有逻辑：只有直播中才新增投放信息内容。
    if not is_live_flag:
        # 直播已结束：不新增行，避免污染表格，只尝试更新已存在行的 Q 列（上面 target_row_1 分支已处理）。
        logging.info("delivery_skip_insert_not_live account=%s date=%s live_id=%s", account, date_str, live_id_s)
        return

    insert_at_1 = summary_row_1
    start_index_0 = insert_at_1 - 1
    
    # 先插入行，不继承任何样式
    client.insert_dimension_range_rows(
        spreadsheet_token=spreadsheet_token,
        sheet_id=delivery_sheet_id,
        start_index_0=start_index_0,
        end_index_0=start_index_0 + 1,
        inherit_style="",  # 空字符串表示不继承样式
    )
    
    # 转换为 Excel 格式
    excel_date = _to_excel_date(date_str)
    excel_time = _to_excel_time(start_hm) if start_hm else 0

    write_row = [
        excel_date if excel_date > 0 else date_str,  # A: 日期
        excel_time if excel_time > 0 else start_hm,  # B: 开播时间（Excel 小数格式）
        _to_number_if_numeric(str(live_id or niu_metrics.get("live_id", "") or "").strip()),  # C: 直播间ID（纯数字转为数字类型）
        account,  # D: 账号
        _to_number_if_numeric(anchor_info.get("快手ID", "")),  # E: 快手ID（纯数字转为数字类型）
        anchor_info.get("主播", ""),  # F: 主播
    ]
    
    # 更新 A-F 列（不包括 G 列单量，让它继承公式）
    update_rng_af = f"{delivery_sheet_id}!A{insert_at_1}:F{insert_at_1}"
    client.update_values(spreadsheet_token, update_rng_af, [write_row])
    
    # 单独更新 H 列（消耗）- 使用数字类型而不是字符串
    update_rng_h = f"{delivery_sheet_id}!H{insert_at_1}:H{insert_at_1}"
    client.update_values(spreadsheet_token, update_rng_h, [[cost]])  # 直接使用数字
    
    # 写入数据后，设置对齐
    try:
        client.set_cell_alignment(
            spreadsheet_token=spreadsheet_token,
            sheet_id=delivery_sheet_id,
            range_a1=f"A{insert_at_1}:F{insert_at_1}",
            h_align=2,  # 2=居中
            v_align=2,  # 2=居中
        )
        logging.info(f"delivery_alignment_set_success row={insert_at_1} range=A:F")
    except Exception as e:
        logging.warning(f"Failed to set alignment for row {insert_at_1}: {e}")
    
    try:
        client.set_cell_alignment(
            spreadsheet_token=spreadsheet_token,
            sheet_id=delivery_sheet_id,
            range_a1=f"H{insert_at_1}:H{insert_at_1}",
            h_align=2,  # 2=居中
            v_align=2,  # 2=居中
        )
        logging.info(f"delivery_alignment_set_success row={insert_at_1} range=H")
    except Exception as e:
        logging.warning(f"Failed to set alignment for H{insert_at_1}: {e}")
    
    logging.info("delivery_sheet_inserted row=%d date=%s account=%s", insert_at_1, date_str, account)

    # Q列直播状态
    if status_text:
        try:
            update_rng_q = f"{delivery_sheet_id}!Q{insert_at_1}:Q{insert_at_1}"
            client.update_values(spreadsheet_token, update_rng_q, [[status_text]])
            logging.info("delivery_status_updated row=%d status=%s", insert_at_1, status_text)
        except Exception as e:
            logging.warning("delivery_status_update_failed row=%d err=%s", insert_at_1, e)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list-sheets")
    sp.set_defaults(func=cmd_list_sheets)

    sp = sub.add_parser("sync")
    sp.set_defaults(func=cmd_sync)

    return p


def main() -> None:
    log_path = setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    cfg_for_cleanup: Dict[str, Any] = {}
    try:
        cfg_for_cleanup = load_json(args.config)
    except Exception:
        cfg_for_cleanup = {}

    try:
        if not hasattr(args, "func") or args.func is None:
            raise RuntimeError(f"Unknown cmd: {args.cmd}")
        args.func(args)
    finally:
        try:
            target_cfg = cfg_for_cleanup.get("target") or {}
            keep_sync_logs = int(target_cfg.get("keep_sync_logs", 50))
            _cleanup_keep_latest_files("logs", keep=keep_sync_logs, exts=[".log"], prefix="sync_")
        except Exception:
            pass

        try:
            target_cfg = cfg_for_cleanup.get("target") or {}
            ui_keep_screenshots = int(target_cfg.get("ui_keep_screenshots", 10))
            _cleanup_keep_latest_files(
                os.path.join(".state"),
                keep=ui_keep_screenshots,
                exts=[".png"],
                prefix="feishu_ui_last_",
            )
            _cleanup_keep_latest_files(
                os.path.join(".state"),
                keep=ui_keep_screenshots,
                exts=[".png"],
                prefix="feishu_delivery_ui_last_",
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
