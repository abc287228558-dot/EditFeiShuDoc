import argparse
import csv
import datetime
import urllib.parse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from typing import Any, Dict, Optional, List, Tuple


_NIU_RUNTIME_STATUS_LOCK = threading.Lock()
_KUAISHOU_RUNTIME_STATUS_LOCK = threading.Lock()


def _niu_runtime_status_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), ".state", "niu_runtime_status.json")


def _save_niu_runtime_status(config_path: str, data: Dict[str, Any]) -> None:
    p = _niu_runtime_status_path(config_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _set_niu_runtime_item(config_path: str, key: str, patch: Dict[str, Any]) -> None:
    with _NIU_RUNTIME_STATUS_LOCK:
        p = _niu_runtime_status_path(config_path)
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        items = data.get("items")
        if not isinstance(items, dict):
            items = {}
        cur = items.get(key)
        if not isinstance(cur, dict):
            cur = {}
        cur.update(patch or {})
        items[key] = cur
        data["items"] = items
        data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_niu_runtime_status(config_path, data)


def _clear_niu_runtime_status(config_path: str) -> None:
    _save_niu_runtime_status(
        config_path,
        {
            "items": {},
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def _kuaishou_runtime_status_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), ".state", "kuaishou_runtime_status.json")


def _save_kuaishou_runtime_status(config_path: str, data: Dict[str, Any]) -> None:
    p = _kuaishou_runtime_status_path(config_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _set_kuaishou_runtime_item(config_path: str, key: str, patch: Dict[str, Any]) -> None:
    with _KUAISHOU_RUNTIME_STATUS_LOCK:
        p = _kuaishou_runtime_status_path(config_path)
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        items = data.get("items")
        if not isinstance(items, dict):
            items = {}
        cur = items.get(key)
        if not isinstance(cur, dict):
            cur = {}
        cur.update(patch or {})
        items[key] = cur
        data["items"] = items
        data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_kuaishou_runtime_status(config_path, data)


def _clear_kuaishou_runtime_status(config_path: str) -> None:
    _save_kuaishou_runtime_status(
        config_path,
        {
            "items": {},
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )



def _cleanup_keep_latest_files(dir_path: str, *, keep: int) -> None:
    if keep <= 0:
        return
    if not dir_path or not os.path.isdir(dir_path):
        return
    try:
        items = []
        for name in os.listdir(dir_path):
            p = os.path.join(dir_path, name)
            if not os.path.isfile(p):
                continue
            try:
                st = os.stat(p)
            except Exception:
                continue
            items.append((st.st_mtime, p))
        items.sort(reverse=True)
        for _, p in items[keep:]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        return


def load_accounts_from_anchor_csv(path: str) -> list:
    import csv

    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            reader.fieldnames = [n.strip() for n in reader.fieldnames]
        accounts = []
        for r in reader:
            acct = ((r.get("直播账号") or r.get("\ufeff直播账号") or "")).strip()
            if acct:
                accounts.append(acct)
        return accounts


def load_account_rows_from_anchor_csv(path: str) -> list:
    import csv

    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            reader.fieldnames = [n.strip() for n in reader.fieldnames]
        rows = []
        for r in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
        return rows


def _pick_account_id(row: Dict[str, str]) -> str:
    for k in [
        "niu_account_id",
        "accountId",
        "__accountId__",
        "账户ID",
        "牛后台账号ID",
    ]:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


def _norm_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    # Keep CJK + ASCII word chars/digits, drop emoji/symbols/spaces.
    s = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "", s)
    return s.lower()


def _niu_table_json_path(cfg: Dict[str, Any], config_path: str) -> str:
    raw = ((cfg.get("mapping") or {}).get("niu_table_json") or ".state/niu_table.json")
    raw_s = str(raw)
    if os.path.isabs(raw_s):
        return raw_s
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), raw_s)


def _load_niu_table_rows(cfg: Dict[str, Any], config_path: str) -> List[Dict[str, str]]:
    p = _niu_table_json_path(cfg, config_path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        out: List[Dict[str, str]] = []
        for it in data:
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or "").strip()
            if not url:
                continue
            out.append({"url": url})
        return out
    except Exception:
        return []


def _extract_niu_account_id_from_url(url: str) -> str:
    try:
        q = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(q.query)
        v = (qs.get("__accountId__") or [""])[0]
        v = str(v).strip()
        return v
    except Exception:
        return ""


def _niu_login_credentials() -> Tuple[str, str]:
    try:
        phone = str(os.environ.get("NIU_LOGIN_PHONE", "") or "").strip()
    except Exception:
        phone = ""
    try:
        password = str(os.environ.get("NIU_LOGIN_PASSWORD", "") or "").strip()
    except Exception:
        password = ""
    return phone, password


def _try_auto_login_niu(page: Any, *, timeout_ms: int) -> bool:
    phone, password = _niu_login_credentials()
    if not phone or not password:
        return False

    entry_selectors = [
        "button:has-text('立即登录')",
        "text=立即登录",
        "button:has-text('登录')",
        "text=登录",
    ]
    phone_selectors = [
        "input[placeholder='邮箱/快手号绑定的手机号']",
        "input[placeholder='请输入手机号']",
    ]
    password_selectors = [
        "input[placeholder='请输入密码']",
        "input[type='password']",
    ]
    login_button_selectors = [
        "button:has-text('登录')",
        "text=登录",
    ]

    try:
        def _find_visible_locator(selectors: List[str]):
            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    cnt = loc.count()
                except Exception:
                    continue
                for i in range(cnt):
                    try:
                        cand = loc.nth(i)
                        if cand.is_visible():
                            return cand
                    except Exception:
                        continue
            return None

        phone_input = _find_visible_locator(phone_selectors)
        if phone_input is None:
            for sel in entry_selectors:
                try:
                    loc = page.locator(sel)
                    cnt = loc.count()
                except Exception:
                    continue
                clicked = False
                for i in range(cnt):
                    try:
                        cand = loc.nth(i)
                        if not cand.is_visible():
                            continue
                        cand.click(timeout=min(timeout_ms, 5000))
                        page.wait_for_timeout(1000)
                        clicked = True
                        break
                    except Exception:
                        continue
                if clicked:
                    phone_input = _find_visible_locator(phone_selectors)
                    if phone_input is not None:
                        break

        if phone_input is None:
            return False

        password_input = _find_visible_locator(password_selectors)
        if password_input is None:
            return False

        phone_input.fill(phone)
        password_input.fill(password)

        try:
            agree = _find_visible_locator(["input[type='checkbox']"])
            if agree is not None and (not agree.is_checked()):
                agree.check(force=True)
        except Exception:
            pass

        clicked = False
        for sel in login_button_selectors:
            try:
                btn = _find_visible_locator([sel])
                if btn is None:
                    continue
                btn.click(timeout=min(timeout_ms, 5000))
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            return False

        page.wait_for_timeout(3000)
        return True
    except Exception:
        return False


def _fetch_live_id_from_niu(
    *,
    account_id: str,
    user_data_dir: str,
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int = 180000,
    cdp_url: str = "",
) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("live_id_fetch_mode=niu requires Playwright") from e

    url = (
        "https://niu.e.kuaishou.com/reportV2/commonReport"
        "?slideReportSenceType=13&horizontalSenceType=131&__accountId__="
        + str(account_id)
    )

    os.makedirs(user_data_dir, exist_ok=True)
    with sync_playwright() as p:
        ctx = None
        browser = None
        page = None
        using_cdp = bool(cdp_url)
        if using_cdp:
            # Reuse an existing Chrome session (must be started with --remote-debugging-port).
            browser = p.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError(f"Connected to CDP but no browser contexts found: cdp_url={cdp_url}")
            ctx = browser.contexts[0]
        else:
            ctx = p.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=headless)
        try:
            page = ctx.new_page()
            # Attach listeners before navigation, otherwise we may miss early XHR.
            found: set = set()
            saw_any_json = False
            last_json_url = ""

            def _walk(obj: Any) -> None:
                try:
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            lk = str(k).lower()
                            if lk in {"liveid", "roomid", "直播id"}:
                                s = str(v).strip()
                                if s.isdigit():
                                    found.add(s)
                            _walk(v)
                    elif isinstance(obj, list):
                        for it in obj:
                            _walk(it)
                except Exception:
                    return

            def _on_response(resp: Any) -> None:
                nonlocal saw_any_json, last_json_url
                try:
                    headers = resp.headers or {}
                    ct = headers.get("content-type", "") or headers.get("Content-Type", "") or ""
                    if "application/json" not in ct:
                        return
                    saw_any_json = True
                    last_json_url = resp.url or ""
                    j = resp.json()
                    _walk(j)
                except Exception:
                    return

            try:
                page.on("response", _on_response)
            except Exception:
                pass

            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)

            # Best-effort: wait for XHR to complete.
            try:
                page.wait_for_load_state("networkidle", timeout=min(15000, timeout_ms))
            except Exception:
                pass

            def _looks_like_login() -> bool:
                try:
                    u = (page.url or "")
                    if any(k in u for k in ["passport", "login", "accounts", "sso"]):
                        return True
                    # niu may redirect unauthenticated users to a welcome/guide page.
                    if "/welcome" in u:
                        return True
                except Exception:
                    pass

                # Heuristics for login overlays/forms.
                try:
                    if page.get_by_text("登录").count() > 0 and page.get_by_text("手机号").count() > 0:
                        return True
                except Exception:
                    pass
                try:
                    if page.locator("input[type='password']").count() > 0:
                        return True
                except Exception:
                    pass
                # Welcome/guide pages often only have a login button.
                try:
                    if page.get_by_role("button", name="登录").count() > 0:
                        return True
                except Exception:
                    pass
                return False

            # If login is required, allow a headful run to complete login once and persist to profile.
            if _looks_like_login():
                auto_login_ok = _try_auto_login_niu(page, timeout_ms=timeout_ms)
                if auto_login_ok:
                    try:
                        page.wait_for_url(re.compile(r".*/reportV2/commonReport.*"), timeout=min(timeout_ms, 30000))
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(15000, timeout_ms))
                    except Exception:
                        pass
                if _looks_like_login():
                    if headless:
                        raise RuntimeError(
                            "Kuaishou niu page requires login. Run once with target.niu_headless=false to login, "
                            f"or provide NIU_LOGIN_PHONE / NIU_LOGIN_PASSWORD, then re-run headless. profile_dir={user_data_dir} url={page.url}"
                        )
                    print(
                        "[pipeline] niu page requires login. Please complete login in the opened browser window; waiting...",
                        file=sys.stderr,
                    )
                    deadline = time.time() + max(30.0, float(login_wait_ms) / 1000.0)
                    # Prefer waiting for redirect back to report page after login.
                    try:
                        page.wait_for_url(re.compile(r".*/reportV2/commonReport.*"), timeout=login_wait_ms)
                    except Exception:
                        pass
                    while time.time() < deadline:
                        try:
                            u = (page.url or "")
                            if (not _looks_like_login()) and ("/reportV2/commonReport" in u) and ("/welcome" not in u):
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(1000)
                    if _looks_like_login():
                        raise RuntimeError(
                            "Kuaishou niu login not completed within login_wait_ms. "
                            f"profile_dir={user_data_dir} url={page.url}"
                        )
                    # After login, give the app some time to load data.
                    page.wait_for_timeout(1200)
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(15000, timeout_ms))
                    except Exception:
                        pass

            # Give XHR a moment after attaching listeners.
            page.wait_for_timeout(1200)

            # Try pull JSON from performance entries (some apps embed data in script tags).
            try:
                state = page.evaluate(
                    """
                    () => {
                      const out = [];
                      for (const k of Object.keys(window)) {
                        if (k.toLowerCase().includes('state') || k.toLowerCase().includes('data')) {
                          try {
                            const v = window[k];
                            if (v && (typeof v === 'object')) out.push(v);
                          } catch (e) {}
                        }
                      }
                      return out;
                    }
                    """
                )
                _walk(state)
            except Exception:
                pass

            # Fallback: HTML regex.
            html = page.content()
            patterns = [
                r"\"liveId\"\s*:\s*\"?(\d+)\"?",
                r"\"直播ID\"\s*:\s*\"?(\d+)\"?",
                r"\"roomId\"\s*:\s*\"?(\d+)\"?",
            ]
            for pat in patterns:
                m = re.search(pat, html)
                if m:
                    found.add(m.group(1))

            # Fallback: DOM text parsing (the table often renders '直播ID：<digits>' as plain text).
            try:
                full_text = (
                    page.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText : ''")
                    or ""
                )
                if full_text:
                    # Prefer any liveId that appears in a block containing '直播中'.
                    best = ""
                    lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
                    for i, ln in enumerate(lines):
                        m = re.search(r"直播ID\s*[:：]\s*(\d+)", ln)
                        if not m:
                            continue
                        candidate = m.group(1)
                        found.add(candidate)
                        nearby = " ".join(lines[max(0, i - 3) : min(len(lines), i + 4)])
                        if "直播中" in nearby:
                            best = candidate
                            break
                    if best:
                        return best
            except Exception:
                pass

            if found:
                # Prefer the longest numeric id (heuristic).
                return sorted(found, key=lambda x: (len(x), x), reverse=True)[0]

            final_url = ""
            try:
                final_url = page.url or ""
            except Exception:
                final_url = ""
            debug_shot = ""
            debug_text = ""
            try:
                os.makedirs(".state", exist_ok=True)
                debug_shot = os.path.join(".state", f"niu_debug_{int(time.time())}.png")
                page.screenshot(path=debug_shot, full_page=True)
            except Exception:
                debug_shot = ""
            try:
                debug_text = (
                    (page.evaluate(
                        "() => (document.body && document.body.innerText) ? document.body.innerText.slice(0, 300) : ''"
                    )
                    or "")
                    .strip()
                )
            except Exception:
                debug_text = ""
            try:
                print(
                    f"[pipeline] niu live_id not found: using_cdp={using_cdp} login_detected={_looks_like_login()} saw_json={saw_any_json} last_json_url={last_json_url} final_url={final_url} screenshot={debug_shot} text_head={debug_text!r}",
                    file=sys.stderr,
                )
            except Exception:
                pass
            return ""
        finally:
            # If using CDP, do NOT close the user's Chrome. Only close our page.
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass
            if not using_cdp:
                try:
                    if ctx is not None:
                        ctx.close()
                except Exception:
                    pass


def _fetch_live_map_from_niu(
    *,
    account_id: str,
    user_data_dir: str,
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int = 180000,
    cdp_url: str = "",
    only_run_when_live: bool = True,
    debug_hold_ms: int = 0,
    metrics_out: Optional[Dict[str, Dict[str, str]]] = None,
    status_callback: Optional[Any] = None,
) -> Dict[str, str]:
    """Return mapping of 快手名称 -> 直播ID for rows that look like '直播中' in the list.

    This avoids per-account navigation by parsing the list page once.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("live_id_fetch_mode=niu requires Playwright") from e

    url = (
        "https://niu.e.kuaishou.com/reportV2/commonReport"
        "?slideReportSenceType=13&horizontalSenceType=131&__accountId__="
        + str(account_id)
    )

    def _status(progress: int, message: str) -> None:
        if status_callback is None:
            return
        try:
            status_callback(int(progress), str(message))
        except Exception:
            return

    def _run_once() -> Dict[str, str]:
        os.makedirs(user_data_dir, exist_ok=True)
        with sync_playwright() as p:
            ctx = None
            browser = None
            page = None
            using_cdp = bool(cdp_url)
            if using_cdp:
                try:
                    browser = p.chromium.connect_over_cdp(cdp_url)
                    if not browser.contexts:
                        raise RuntimeError(f"Connected to CDP but no browser contexts found: cdp_url={cdp_url}")
                    ctx = browser.contexts[0]
                except Exception as e:
                    # Auto fallback to non-CDP mode (persistent context) when CDP is not available.
                    try:
                        print(f"[pipeline] niu CDP connect failed; falling back to Playwright. err={e}", file=sys.stderr)
                    except Exception:
                        pass
                    using_cdp = False
                    browser = None
                    ctx = None
            if not using_cdp:
                ctx = p.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=headless)

            try:
                page = ctx.new_page()
                _status(10, "打开金牛页面")
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)

                # Reuse the same login detection/wait strategy as single live_id fetch.
                def _looks_like_login() -> bool:
                    try:
                        u = (page.url or "")
                        if any(k in u for k in ["passport", "login", "accounts", "sso"]):
                            return True
                        if "/welcome" in u:
                            return True
                    except Exception:
                        pass
                    try:
                        if page.get_by_text("登录").count() > 0 and page.get_by_text("手机号").count() > 0:
                            return True
                    except Exception:
                        pass
                    try:
                        if page.locator("input[type='password']").count() > 0:
                            return True
                    except Exception:
                        pass
                    try:
                        if page.get_by_role("button", name="登录").count() > 0:
                            return True
                    except Exception:
                        pass
                    return False

                if _looks_like_login():
                    _status(25, "金牛登录中")
                    auto_login_ok = _try_auto_login_niu(page, timeout_ms=timeout_ms)
                    if auto_login_ok:
                        try:
                            page.wait_for_url(re.compile(r".*/reportV2/commonReport.*"), timeout=min(timeout_ms, 30000))
                        except Exception:
                            pass
                        page.wait_for_timeout(1500)
                        try:
                            page.wait_for_load_state("networkidle", timeout=min(15000, timeout_ms))
                        except Exception:
                            pass
                    if _looks_like_login():
                        _status(100, "登录状态已过期")
                        if headless:
                            raise RuntimeError(
                                "Kuaishou niu page requires login. Run once with target.niu_headless=false to login, "
                                f"or provide NIU_LOGIN_PHONE / NIU_LOGIN_PASSWORD, then re-run headless. profile_dir={user_data_dir} url={page.url}"
                            )
                        print(
                            "[pipeline] niu page requires login. Please complete login in the opened browser window; waiting...",
                            file=sys.stderr,
                        )
                        deadline = time.time() + max(30.0, float(login_wait_ms) / 1000.0)
                        try:
                            page.wait_for_url(re.compile(r".*/reportV2/commonReport.*"), timeout=login_wait_ms)
                        except Exception:
                            pass
                        while time.time() < deadline:
                            try:
                                u = (page.url or "")
                                if (not _looks_like_login()) and ("/reportV2/commonReport" in u) and ("/welcome" not in u):
                                    break
                            except Exception:
                                pass
                            page.wait_for_timeout(1000)
                        if _looks_like_login():
                            raise RuntimeError(
                                "Kuaishou niu login not completed within login_wait_ms. "
                                f"profile_dir={user_data_dir} url={page.url}"
                            )
                        page.wait_for_timeout(1200)

                # Give the table time to render.
                _status(45, "加载列表中")
                try:
                    page.wait_for_load_state("networkidle", timeout=min(15000, timeout_ms))
                except Exception:
                    pass
                page.wait_for_timeout(1200)

                # Apply date filter to get data from last 7 days (avoid missing data after midnight).
                try:
                    _status(55, "应用日期筛选")
                    print("[pipeline] niu applying date filter (last 7 days)...", file=sys.stderr)
                    date_picker = page.locator(".ant-picker").first
                    if date_picker.count() > 0:
                        date_picker.click()
                        page.wait_for_timeout(1000)
                        recent_7days = page.locator("text=/最近7天|近7天|7天/i").first
                        if recent_7days.count() > 0:
                            recent_7days.click()
                            page.wait_for_timeout(1000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=min(10000, timeout_ms))
                            except Exception:
                                pass
                            page.wait_for_timeout(2000)
                            print("[pipeline] niu date filter applied successfully", file=sys.stderr)
                        else:
                            print("[pipeline] niu date filter option not found, using default", file=sys.stderr)
                    else:
                        print("[pipeline] niu date picker not found, using default", file=sys.stderr)
                except Exception as e:
                    print(f"[pipeline] niu date filter failed: {e}, using default", file=sys.stderr)
                    # Try to close any open popup.
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

                # Set page size to 50 items per page (to see more data without pagination).
                try:
                    _status(65, "调整每页条数")
                    print("[pipeline] niu setting page size to 50 items...", file=sys.stderr)
                    page_size_selector = page.locator(".ant-select-selector").filter(has_text=re.compile(r"条/页|每页")).first
                    if page_size_selector.count() > 0:
                        page_size_selector.click()
                        page.wait_for_timeout(800)
                        option_50 = page.locator(".ant-select-item-option").filter(has_text=re.compile(r"50\s*条")).first
                        if option_50.count() > 0:
                            option_50.click()
                            page.wait_for_timeout(1000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=min(10000, timeout_ms))
                            except Exception:
                                pass
                            page.wait_for_timeout(2000)
                            print("[pipeline] niu page size set to 50 successfully", file=sys.stderr)
                        else:
                            print("[pipeline] niu 50 items option not found, using default", file=sys.stderr)
                    else:
                        print("[pipeline] niu page size selector not found, using default", file=sys.stderr)
                except Exception as e:
                    print(f"[pipeline] niu page size setting failed: {e}, using default", file=sys.stderr)
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

                # Debug: keep the browser open for manual inspection.
                try:
                    hold_ms = int(debug_hold_ms or 0)
                except Exception:
                    hold_ms = 0
                if (not using_cdp) and (not headless) and hold_ms > 0:
                    try:
                        print(f"[pipeline] niu debug_hold_ms={hold_ms}: keeping browser open...", file=sys.stderr)
                    except Exception:
                        pass
                    page.wait_for_timeout(hold_ms)

                # Parse from DOM text: (status + name) and '直播ID：<digits>'
                _status(80, "获取数据中")
                full_text = ""
                try:
                    full_text = (
                        page.evaluate(
                            "() => (document.body && document.body.innerText) ? document.body.innerText : ''"
                        )
                        or ""
                    )
                except Exception:
                    full_text = ""

                lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
                items = []

                def _extract_dt_text(text: str) -> str:
                    t = str(text or "").strip()
                    if not t:
                        return ""
                    mm = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", t)
                    if mm:
                        return mm.group(0)
                    mm = re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\b", t)
                    if mm:
                        return mm.group(0)
                    mm = re.search(r"\b\d{2}:\d{2}(?::\d{2})?\b", t)
                    if mm:
                        return mm.group(0)
                    return ""

                for i, ln in enumerate(lines):
                    m = re.search(r"直播ID\s*[:：]\s*(\d+)", ln)
                    if not m:
                        continue
                    live_id = m.group(1)
                    name = ""
                    is_live = False
                    for j in range(max(0, i - 3), i + 1):
                        cand = lines[j]
                        if "直播中" in cand:
                            is_live = True
                        if "直播ID" in cand:
                            continue
                        if re.fullmatch(r"\d+", cand):
                            continue
                        if cand in {"直播间", "直播时间"}:
                            continue
                        name = cand
                    if name:
                        name = re.sub(r"^(直播中|直播已结束)\s*", "", name).strip()

                    start_dt = ""
                    try:
                        for j in range(i + 1, min(len(lines), i + 16)):
                            cand = lines[j]
                            mm = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", cand)
                            if mm:
                                start_dt = mm.group(0)
                                break
                            mm = re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\b", cand)
                            if mm:
                                start_dt = mm.group(0)
                                break
                            mm = re.search(r"\b\d{2}:\d{2}(?::\d{2})?\b", cand)
                            if mm and ("直播" in " ".join(lines[max(0, j - 2) : j + 2]) or "开播" in " ".join(lines[max(0, j - 2) : j + 2])):
                                start_dt = mm.group(0)
                                break
                    except Exception:
                        start_dt = ""

                    end_dt = ""
                    try:
                        window_start = max(0, i - 4)
                        window_end = min(len(lines), i + 20)
                        for j in range(window_start, window_end):
                            cand = lines[j]
                            near = " ".join(lines[max(window_start, j - 1) : min(window_end, j + 2)])
                            if ("结束" not in near) and ("下播" not in near):
                                continue
                            end_dt = _extract_dt_text(cand)
                            if end_dt:
                                break
                            for k in range(j + 1, min(window_end, j + 3)):
                                end_dt = _extract_dt_text(lines[k])
                                if end_dt:
                                    break
                            if end_dt:
                                break
                    except Exception:
                        end_dt = ""

                    cost = ""
                    try:
                        for j in range(i + 1, min(len(lines), i + 18)):
                            cand = lines[j]
                            if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", cand):
                                continue
                            mm = re.search(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b", cand)
                            if mm:
                                cost = mm.group(0)
                                break
                    except Exception:
                        cost = ""

                    direct_orders = ""
                    try:
                        for j in range(i + 1, min(len(lines), i + 5)):
                            cand = lines[j]
                            if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", cand):
                                continue
                            parts = cand.split()
                            if len(parts) >= 4:
                                try:
                                    val = parts[3].replace(",", "")
                                    if val.isdigit():
                                        direct_orders = val
                                        break
                                except Exception:
                                    pass
                    except Exception:
                        direct_orders = ""

                    items.append((name, live_id, is_live, start_dt, end_dt, cost, direct_orders))

                live_map: Dict[str, str] = {}
                metrics_map: Dict[str, Dict[str, str]] = {}

                def _parse_dt_ts(s: str) -> int:
                    t = (s or "").strip()
                    if not t:
                        return 0
                    try:
                        if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", t):
                            return int(time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S")))
                    except Exception:
                        pass
                    try:
                        if re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\b", t):
                            now = time.localtime()
                            year = now.tm_year
                            if re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b", t):
                                return int(time.mktime(time.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M:%S")))
                            return int(time.mktime(time.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M")))
                    except Exception:
                        pass
                    try:
                        if re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", t):
                            now = time.localtime()
                            prefix = f"{now.tm_year:04d}-{now.tm_mon:02d}-{now.tm_mday:02d} "
                            if len(t.split(":")) == 3:
                                return int(time.mktime(time.strptime(prefix + t, "%Y-%m-%d %H:%M:%S")))
                            return int(time.mktime(time.strptime(prefix + t, "%Y-%m-%d %H:%M")))
                    except Exception:
                        pass
                    return 0

                for name, live_id, is_live, start_dt, end_dt, cost, direct_orders in items:
                    if not name or not live_id:
                        continue
                    if only_run_when_live and not is_live:
                        continue
                    item_start_hm = ""
                    try:
                        mm = re.search(r"\b(\d{2}):(\d{2})\b", start_dt)
                        if mm:
                            item_start_hm = f"{mm.group(1)}:{mm.group(2)}"
                    except Exception:
                        item_start_hm = ""

                    new_m = {
                        "live_id": str(live_id),
                        "start_dt": str(start_dt),
                        "start_hm": str(item_start_hm),
                        "end_dt": str(end_dt),
                        "cost": str(cost),
                        "direct_orders": str(direct_orders),
                        "is_live": str(is_live),
                    }

                    # 同一账号名有多个直播间时，优先选择正在直播的，其次选开播时间最晚的
                    old_m = metrics_map.get(name)
                    if old_m is not None:
                        old_live = str(old_m.get("is_live", "")).lower() in {"1", "true", "yes", "y"}
                        new_live = str(is_live).lower() in {"1", "true", "yes", "y"}
                        if new_live and not old_live:
                            pass  # new is better
                        elif old_live and not new_live:
                            continue  # old is better, skip new
                        else:
                            old_ts = _parse_dt_ts(old_m.get("start_dt", ""))
                            new_ts = _parse_dt_ts(start_dt)
                            if new_ts <= old_ts:
                                continue  # old is newer or equal, skip new

                    live_map[name] = live_id
                    metrics_map[name] = new_m

                if not live_map:
                    _status(100, "未获取到数据")
                    print(
                        f"[pipeline] niu live map empty: using_cdp={using_cdp} final_url={getattr(page, 'url', '')}",
                        file=sys.stderr,
                    )
                else:
                    _status(100, f"已获取数据 {len(live_map)} 条")
                if metrics_out is not None:
                    try:
                        metrics_out.clear()
                        metrics_out.update({str(k): {str(kk): str(vv) for kk, vv in (mv or {}).items()} for k, mv in metrics_map.items()})
                    except Exception:
                        pass
                else:
                    try:
                        setattr(_fetch_live_map_from_niu, "_last_metrics_map", metrics_map)
                    except Exception:
                        pass
                return live_map
            finally:
                try:
                    if page is not None:
                        page.close()
                except Exception:
                    pass
                if not using_cdp:
                    try:
                        if ctx is not None:
                            ctx.close()
                    except Exception:
                        pass

    # Run with a single retry on Playwright driver disconnect/crash.
    try:
        return _run_once()
    except Exception as e:
        msg = str(e)
        if (
            "Connection closed while reading from the driver" in msg
            or "TargetClosedError" in msg
            or "Connection closed" in msg
        ):
            try:
                print(f"[pipeline] niu driver crash/disconnect; retrying once... err={msg}", file=sys.stderr)
            except Exception:
                pass
            time.sleep(1.0)
            return _run_once()
        raise


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_capture_stdout_stream_stderr_tolerate_failure(cmd: List[str]) -> Tuple[int, str]:
    merged_env = os.environ.copy()
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

    def _pump_stderr() -> None:
        try:
            for line in p.stderr:
                if not line:
                    continue
                try:
                    sys.stderr.write(line)
                    sys.stderr.flush()
                except Exception:
                    pass
        except Exception:
            return

    t = threading.Thread(target=_pump_stderr, daemon=True)
    t.start()
    out = p.stdout.read() or ""
    rc = p.wait()
    try:
        t.join(timeout=0.5)
    except Exception:
        pass
    return rc, out


def _run_capture_stdout_stream_stderr(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> str:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    # Make sure child process logs are not buffered when piped.
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

    def _pump_stderr() -> None:
        try:
            for line in p.stderr:
                if not line:
                    continue
                sys.stderr.write(line)
                sys.stderr.flush()
        except Exception:
            return

    t = threading.Thread(target=_pump_stderr, daemon=True)
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
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--account", default="", help="Run pipeline for one 直播账号 in anchor-map CSV")
    p.add_argument("--all-accounts", action="store_true", help="Run pipeline for all accounts in anchor-map CSV")
    p.add_argument("--export-only", action="store_true", help="Only export/download (capture login), do not sync to Feishu")
    p.add_argument("--live-id", default="", help="Fill Feishu column 直播ID with this value for this run")
    args = p.parse_args()

    cfg = load_json(args.config)
    target_cfg = cfg.get("target") or {}
    keep_exports = int(target_cfg.get("keep_exports", 20))

    live_id_fetch_enabled = bool(target_cfg.get("live_id_fetch_enabled", False))
    live_id_fetch_mode = str(target_cfg.get("live_id_fetch_mode", "")).strip().lower()
    only_run_when_live = bool(target_cfg.get("only_run_when_live", True))
    niu_profile_dir = str(
        target_cfg.get(
            "niu_profile_dir_bg",
            target_cfg.get("niu_profile_dir", os.path.join(".state", "niu_pw_profiles_bg", "default")),
        )
    )
    kuaishou_profile_base_dir_bg = str(
        target_cfg.get("kuaishou_profile_dir_bg", os.path.join(".state", "kuaishou_profiles_bg"))
    )
    niu_headless = bool(target_cfg.get("niu_headless", True))
    niu_timeout_ms = int(target_cfg.get("niu_timeout_ms", 60000))
    niu_login_wait_ms = int(target_cfg.get("niu_login_wait_ms", 180000))
    niu_cdp_url = str(target_cfg.get("niu_cdp_url", "") or "").strip()
    try:
        niu_debug_hold_ms = int(target_cfg.get("niu_debug_hold_ms", 0) or 0)
    except Exception:
        niu_debug_hold_ms = 0
    if niu_debug_hold_ms <= 0:
        try:
            niu_debug_hold_ms = int(os.environ.get("NIU_DEBUG_HOLD_MS", "0") or "0")
        except Exception:
            niu_debug_hold_ms = 0
    niu_account_id_default = str(target_cfg.get("niu_account_id_default", "") or "").strip()
    show_missing_niu_account_mapping = bool(target_cfg.get("show_missing_niu_account_mapping", False))
    export_max_workers = int(target_cfg.get("export_max_workers", 2))
    download_dir = os.path.join("exports")

    # Keep only_run_when_live behavior even during headful niu login.
    # Otherwise, a headful login run with --all-accounts may export all accounts and spawn many browsers.

    mapping_cfg = cfg.get("mapping") or {}
    anchor_map_csv = mapping_cfg.get("anchor_map_csv") or ""
    wenzong_anchor_map_csv = mapping_cfg.get("wenzong_anchor_map_csv") or ""

    # Optional: allow multiple niu logins by mapping accountId -> dedicated profile dir.
    # This is driven by web_control_server "金牛表" (.state/niu_table.json) where each row can be opened and logged-in.
    niu_profile_dir_by_account_id: Dict[str, str] = {}
    niu_status_meta_by_account_id: Dict[str, Dict[str, str]] = {}
    try:
        niu_rows = _load_niu_table_rows(cfg, args.config)
        for idx, it in enumerate(niu_rows):
            url = str((it or {}).get("url") or "").strip()
            if not url:
                continue
            aid = _extract_niu_account_id_from_url(url)
            if not aid:
                continue
            slot_dir = os.path.join(os.path.dirname(os.path.abspath(args.config)), ".state", "niu_pw_profiles_bg", f"slot_{idx}")
            niu_profile_dir_by_account_id.setdefault(aid, slot_dir)
            niu_status_meta_by_account_id.setdefault(
                aid,
                {
                    "slot_key": f"slot_{idx}",
                    "label": f"金牛{idx + 1}",
                    "account_id": str(aid),
                    "url": url,
                    "profile_dir": slot_dir,
                },
            )
    except Exception:
        niu_profile_dir_by_account_id = {}
        niu_status_meta_by_account_id = {}

    wenzong_cfg = cfg.get("wenzong") or {}
    wenzong_enabled = bool(wenzong_cfg.get("enabled", False))
    wenzong_classroom_url = str(wenzong_cfg.get("classroom_url") or "").strip() or "https://kt.kuaishou.com/student-management/offsite-student-management"
    wenzong_target_cfg = wenzong_cfg.get("target") or {}

    if args.account and args.all_accounts:
        raise RuntimeError("--account and --all-accounts cannot be used together")

    if args.all_accounts:
        accounts = load_accounts_from_anchor_csv(anchor_map_csv)
        if not accounts:
            raise RuntimeError(f"No accounts found in anchor_map_csv={anchor_map_csv!r}")
    elif args.account:
        accounts = [args.account]
    else:
        accounts = [""]

    live_id_by_account: Dict[str, str] = {}
    niu_metrics_by_account: Dict[str, Dict[str, str]] = {}
    _clear_niu_runtime_status(args.config)
    
    # 从金牛网获取所有账号的数据。
    # 注意：为了支持投放信息表 Q 列“直播状态”写入，我们这里始终拉取包含“直播中/已结束”的完整列表，
    # 但后续是否写入/编辑投放信息内容仍由 only_run_when_live + is_live 决定。
    if live_id_fetch_enabled and live_id_fetch_mode == "niu" and accounts and anchor_map_csv:
        rows = load_account_rows_from_anchor_csv(anchor_map_csv)
        acct_to_row = {(r.get("直播账号") or r.get("\ufeff直播账号") or "").strip(): r for r in rows}

        # New behavior: drive niu fetch by "金牛表" URLs. Each row is an independent __accountId__ login slot.
        # If 金牛表 is empty, fall back to anchor-map provided accountId mapping (or default).
        account_ids_from_niu_table: List[str] = []
        try:
            account_ids_from_niu_table = [str(k).strip() for k in niu_profile_dir_by_account_id.keys() if str(k).strip()]
        except Exception:
            account_ids_from_niu_table = []

        for aid in account_ids_from_niu_table:
            meta = niu_status_meta_by_account_id.get(str(aid), {})
            slot_key = str(meta.get("slot_key") or str(aid))
            _set_niu_runtime_item(
                args.config,
                slot_key,
                {
                    "label": str(meta.get("label") or slot_key),
                    "account_id": str(aid),
                    "url": str(meta.get("url") or ""),
                    "profile_dir": str(meta.get("profile_dir") or ""),
                    "running": False,
                    "progress": 0,
                    "message": "等待运行",
                    "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )

        # Aggregate all fetched niu rows across accountIds, then match by name.
        agg_live_map_norm: Dict[str, str] = {}
        agg_metrics_map_norm: Dict[str, Dict[str, str]] = {}

        def _metrics_same_session(a: Any, b: Any) -> bool:
            try:
                if not isinstance(a, dict) or not isinstance(b, dict):
                    return False
                a_dt = str(a.get("start_dt", "") or "").strip()
                b_dt = str(b.get("start_dt", "") or "").strip()
                a_hm = str(a.get("start_hm", "") or "").strip()
                b_hm = str(b.get("start_hm", "") or "").strip()

                import re

                def _date_part(s: str) -> str:
                    m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", s)
                    if m:
                        return m.group(0)
                    m2 = re.search(r"\b\d{2}-\d{2}\b", s)
                    if m2:
                        return m2.group(0)
                    return ""

                a_date = _date_part(a_dt)
                b_date = _date_part(b_dt)
                if a_date and b_date and a_date != b_date:
                    return False

                # Prefer start_hm comparison when available.
                if a_hm and b_hm:
                    return a_hm == b_hm

                # Fall back to raw start_dt compare when hm missing.
                if a_dt and b_dt:
                    return a_dt == b_dt

                return False
            except Exception:
                return False

        def _sum_metric(dst: Dict[str, str], src: Dict[str, str], key: str) -> None:
            try:
                import re

                def _to_float(x: Any) -> float:
                    s = str(x or "").strip().replace(",", "")
                    if not s:
                        return 0.0
                    # keep digits / dot / minus
                    s2 = re.sub(r"[^0-9.\-]", "", s)
                    if not s2 or s2 in {"-", ".", "-."}:
                        return 0.0
                    return float(s2)

                a = _to_float(dst.get(key, ""))
                b = _to_float(src.get(key, ""))
                dst[key] = str(a + b)
            except Exception:
                return

        def _parse_start_dt_ts(s: Any) -> int:
            try:
                t = str(s or "").strip()
            except Exception:
                t = ""
            if not t:
                return 0
            try:
                if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", t):
                    return int(time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S")))
            except Exception:
                pass
            try:
                if re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\b", t):
                    now = time.localtime()
                    year = now.tm_year
                    if re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b", t):
                        return int(time.mktime(time.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M:%S")))
                    return int(time.mktime(time.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M")))
            except Exception:
                pass
            try:
                if re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", t):
                    now = time.localtime()
                    prefix = f"{now.tm_year:04d}-{now.tm_mon:02d}-{now.tm_mday:02d} "
                    if len(t.split(":")) == 3:
                        return int(time.mktime(time.strptime(prefix + t, "%Y-%m-%d %H:%M:%S")))
                    return int(time.mktime(time.strptime(prefix + t, "%Y-%m-%d %H:%M")))
            except Exception:
                pass
            return 0

        def _is_live_flag(m: Dict[str, str]) -> bool:
            try:
                v = str((m or {}).get("is_live", "") or "").strip().lower()
            except Exception:
                v = ""
            return v in {"1", "true", "yes", "y"}

        def _parse_metric_dt(s: Any) -> Optional[datetime.datetime]:
            try:
                t = str(s or "").strip()
            except Exception:
                t = ""
            if not t:
                return None
            try:
                if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", t):
                    return datetime.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            try:
                if re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b", t):
                    now = datetime.datetime.now()
                    return datetime.datetime.strptime(f"{now.year}-{t}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            try:
                if re.search(r"\b\d{2}-\d{2}\s+\d{2}:\d{2}\b", t):
                    now = datetime.datetime.now()
                    return datetime.datetime.strptime(f"{now.year}-{t}", "%Y-%m-%d %H:%M")
            except Exception:
                pass
            try:
                if re.fullmatch(r"\d{2}:\d{2}:\d{2}", t):
                    now = datetime.datetime.now()
                    prefix = f"{now.year:04d}-{now.month:02d}-{now.day:02d} "
                    return datetime.datetime.strptime(prefix + t, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            try:
                if re.fullmatch(r"\d{2}:\d{2}", t):
                    now = datetime.datetime.now()
                    prefix = f"{now.year:04d}-{now.month:02d}-{now.day:02d} "
                    return datetime.datetime.strptime(prefix + t, "%Y-%m-%d %H:%M")
            except Exception:
                pass
            return None

        def _user_live_id_allowed(m: Any) -> bool:
            if not isinstance(m, dict) or not m:
                return True
            live_id_s = str(m.get("live_id", "") or "").strip()
            if not live_id_s:
                return False
            if _is_live_flag(m):
                return True
            end_dt = _parse_metric_dt(m.get("end_dt", ""))
            if end_dt is None:
                return False
            return datetime.datetime.now() <= (end_dt + datetime.timedelta(minutes=30))

        def _choose_better(old_m: Optional[Dict[str, str]], new_m: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
            if not isinstance(new_m, dict) or not new_m:
                return old_m
            if not isinstance(old_m, dict) or not old_m:
                return new_m
            old_live = _is_live_flag(old_m)
            new_live = _is_live_flag(new_m)
            if new_live and (not old_live):
                return new_m
            if old_live and (not new_live):
                return old_m
            old_ts = _parse_start_dt_ts(old_m.get("start_dt", ""))
            new_ts = _parse_start_dt_ts(new_m.get("start_dt", ""))
            if new_ts > old_ts:
                return new_m
            return old_m

        def _merge_into_agg(live_map: Dict[str, str], metrics_map: Dict[str, Any]) -> None:
            for k, mv in (metrics_map or {}).items():
                nk = _norm_name(k)
                if not nk:
                    continue
                if not isinstance(mv, dict):
                    continue

                new_m = {str(kk): str(vv) for kk, vv in mv.items()}
                old_m = agg_metrics_map_norm.get(nk)

                if isinstance(old_m, dict) and old_m and _metrics_same_session(old_m, new_m):
                    _sum_metric(old_m, new_m, "cost")
                    _sum_metric(old_m, new_m, "direct_orders")
                    agg_metrics_map_norm[nk] = old_m
                    continue

                chosen = _choose_better(old_m, new_m)
                if chosen is not None:
                    agg_metrics_map_norm[nk] = chosen
                    live_id_s = str(chosen.get("live_id", "") or "").strip()
                    if live_id_s:
                        agg_live_map_norm[nk] = live_id_s

            for k, v in (live_map or {}).items():
                nk = _norm_name(k)
                vv = str(v or "").strip()
                if not nk or not vv:
                    continue
                if nk in agg_metrics_map_norm:
                    continue
                old_live_id = str(agg_live_map_norm.get(nk, "") or "").strip()
                if not old_live_id:
                    agg_live_map_norm[nk] = vv

        def _fetch_one_account_id(account_id: str) -> tuple:
            # Prefer the per-accountId profile dir (opened/logged-in via web "金牛表"), fallback to single default.
            niu_user_data_dir = niu_profile_dir_by_account_id.get(str(account_id), niu_profile_dir)
            meta = niu_status_meta_by_account_id.get(str(account_id), {})
            slot_key = str(meta.get("slot_key") or str(account_id))

            def _report(progress: int, message: str) -> None:
                _set_niu_runtime_item(
                    args.config,
                    slot_key,
                    {
                        "label": str(meta.get("label") or slot_key),
                        "account_id": str(account_id),
                        "url": str(meta.get("url") or ""),
                        "profile_dir": str(meta.get("profile_dir") or niu_user_data_dir),
                        "running": True,
                        "progress": int(progress),
                        "message": str(message),
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )

            _report(1, "准备开始")
            local_metrics: Dict[str, Dict[str, str]] = {}
            try:
                live_map = _fetch_live_map_from_niu(
                    account_id=account_id,
                    user_data_dir=niu_user_data_dir,
                    headless=niu_headless,
                    timeout_ms=niu_timeout_ms,
                    login_wait_ms=niu_login_wait_ms,
                    cdp_url=niu_cdp_url,
                    # Always fetch full list so we can write Q column live status for ended lives too.
                    only_run_when_live=False,
                    debug_hold_ms=niu_debug_hold_ms,
                    metrics_out=local_metrics,
                    status_callback=_report,
                )
                _set_niu_runtime_item(
                    args.config,
                    slot_key,
                    {
                        "label": str(meta.get("label") or slot_key),
                        "account_id": str(account_id),
                        "url": str(meta.get("url") or ""),
                        "profile_dir": str(meta.get("profile_dir") or niu_user_data_dir),
                        "running": False,
                        "ok": True,
                        "progress": 100,
                        "message": f"已获取数据，等待下一步（{len(live_map)}条）",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                return (account_id, live_map, local_metrics)
            except Exception as e:
                msg = str(e)
                status_message = "获取失败"
                if "requires login" in msg or "login not completed" in msg or "登录" in msg:
                    status_message = "登录状态已过期"
                _set_niu_runtime_item(
                    args.config,
                    slot_key,
                    {
                        "label": str(meta.get("label") or slot_key),
                        "account_id": str(account_id),
                        "url": str(meta.get("url") or ""),
                        "profile_dir": str(meta.get("profile_dir") or niu_user_data_dir),
                        "running": False,
                        "ok": False,
                        "progress": 100,
                        "message": f"{status_message}: {msg[:160]}",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                if ("SingletonLock" in msg) or ("ProcessSingleton" in msg) or ("profile directory" in msg and "Aborting" in msg):
                    raise RuntimeError(
                        "金牛 profile 被占用（SingletonLock）。请先关闭对应的 Chromium 窗口后重试。"
                        f" account_id={account_id} profile_dir={niu_user_data_dir} err={msg}"
                    )
                if niu_debug_hold_ms > 0:
                    raise RuntimeError(f"金牛取数失败（debug_hold_ms启用，已中止流程）: account_id={account_id} err={msg}")
                print(f"[pipeline] niu fetch failed: account_id={account_id} err={msg}", file=sys.stderr)
                return (account_id, {}, {})

        if account_ids_from_niu_table:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            max_workers = min(len(account_ids_from_niu_table), 4)
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = [ex.submit(_fetch_one_account_id, account_id) for account_id in account_ids_from_niu_table]
                for fut in as_completed(futs):
                    account_id, live_map, metrics_map = fut.result()
                    _merge_into_agg(live_map, metrics_map)
        else:
            # Fallback: use anchor-map provided accountId mapping (or default).
            groups: Dict[str, list] = {}
            for acct in accounts:
                r = acct_to_row.get(acct, {})
                account_id = _pick_account_id(r)
                if not account_id:
                    account_id = niu_account_id_default
                    if show_missing_niu_account_mapping and account_id:
                        print(
                            f"[pipeline] account={acct!r}: missing niu accountId mapping; using niu_account_id_default={account_id}",
                            file=sys.stderr,
                        )
                if not account_id:
                    continue
                groups.setdefault(str(account_id), []).append(acct)
            for account_id in groups.keys():
                _, live_map, metrics_map = _fetch_one_account_id(account_id)
                _merge_into_agg(live_map, metrics_map)

        # Now match each account name against aggregated data.
        for acct in accounts:
            n_acct = _norm_name(acct)
            if n_acct and (n_acct in agg_live_map_norm):
                live_id_by_account[acct] = agg_live_map_norm[n_acct]
                if n_acct in agg_metrics_map_norm:
                    niu_metrics_by_account[acct] = agg_metrics_map_norm[n_acct]
                continue
            for nk, v in agg_live_map_norm.items():
                if not nk:
                    continue
                if n_acct and (nk in n_acct or n_acct in nk):
                    live_id_by_account[acct] = v
                    if nk in agg_metrics_map_norm:
                        niu_metrics_by_account[acct] = agg_metrics_map_norm[nk]
                    break

    last_err: Optional[Exception] = None
    # 收集所有账号的导出数据
    export_data_list = []
    _clear_kuaishou_runtime_status(args.config)
    
    # 过滤需要导出的账号
    accounts_to_export = []
    account_metadata = {}  # 存储每个账号的元数据
    seen_accounts_norm: set = set()

    # Guardrail: only export accounts that exist in anchor_map_csv.
    # Some upstream data may contain non-account labels (e.g. "快手课堂经营者平台"), which would make
    # export_kuaishou_parallel.py fail the whole batch.
    anchor_accounts_set: set = set()
    try:
        anchor_accounts_set = {str(a or "").strip() for a in load_accounts_from_anchor_csv(anchor_map_csv)}
    except Exception:
        anchor_accounts_set = set()
    skipped_accounts: List[str] = []
    
    for acct in accounts:
        acct_s = str(acct or "").strip()
        if anchor_accounts_set and acct_s and (acct_s not in anchor_accounts_set):
            skipped_accounts.append(acct_s)
            continue
        acct_key = _norm_name(acct_s)
        if acct_key and acct_key in seen_accounts_norm:
            continue
        if acct_key:
            seen_accounts_norm.add(acct_key)
        auto_live_id = live_id_by_account.get(acct, "")
        auto_niu_metrics = niu_metrics_by_account.get(acct, {})
        effective_live_id = str(args.live_id or "").strip() or auto_live_id
        if (not str(args.live_id or "").strip()) and isinstance(auto_niu_metrics, dict) and auto_niu_metrics:
            if not _user_live_id_allowed(auto_niu_metrics):
                effective_live_id = ""
        
        # 所有账号都要导出快手课堂数据（用户对接信息表）
        # only_run_when_live 只影响投放信息表的填写
        
        accounts_to_export.append(acct_s)
        account_metadata[acct_s] = {
            "live_id": effective_live_id,
            "niu_metrics": auto_niu_metrics if (acct and isinstance(auto_niu_metrics, dict) and auto_niu_metrics) else None,
        }

    if skipped_accounts:
        try:
            print(f"[pipeline] Skipping {len(skipped_accounts)} accounts not in anchor_map_csv: {skipped_accounts}", file=sys.stderr)
        except Exception:
            pass

    for acct in accounts_to_export:
        _set_kuaishou_runtime_item(
            args.config,
            acct,
            {
                "label": acct,
                "running": False,
                "ok": False,
                "progress": 0,
                "message": "等待导出",
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
    
    # 判断是否使用并发导出
    use_parallel = len(accounts_to_export) > 1 and all(a for a in accounts_to_export)
    
    if use_parallel:
        # 并发导出多个账号
        print(f"[pipeline] Using parallel export for {len(accounts_to_export)} accounts", file=sys.stderr)
        
        parallel_cmd = [
            sys.executable,
            "export_kuaishou_parallel.py",
            "--url",
            "https://kt.kuaishou.com/student-management/offsite-student-management",
            "--accounts",
            ",".join(accounts_to_export),
            "--anchor-map-csv",
            anchor_map_csv,
            "--download-dir",
            download_dir,
            "--profile-base-dir",
            kuaishou_profile_base_dir_bg,
            "--runtime-config",
            args.config,
        ]
        if export_max_workers > 0:
            parallel_cmd.extend(["--max-workers", str(export_max_workers)])
        if args.headless:
            parallel_cmd.append("--headless")
        
        try:
            for acct in accounts_to_export:
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": True,
                        "ok": False,
                        "progress": 1,
                        "message": "已进入后台导出队列",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            exit_code, result_json_raw = _run_capture_stdout_stream_stderr_tolerate_failure(parallel_cmd)
            result_json = (result_json_raw or "").strip()
            results = json.loads(result_json) if result_json else {}
            if exit_code != 0:
                print(f"[pipeline] parallel export exited with code={exit_code} (will continue with successful accounts)", file=sys.stderr)
            
            # 处理并发导出结果
            failed_accounts: List[str] = []
            for acct in accounts_to_export:
                result = results.get(acct, {})
                export_path = result.get("export_path")
                error = result.get("error")
                
                if error:
                    last_err = RuntimeError(f"account={acct!r} export failed: {error}")
                    print(f"[pipeline] {last_err}", file=sys.stderr)
                    failed_accounts.append(acct)
                    status_message = "导出失败"
                    if "requires login" in str(error) or "login" in str(error).lower() or "登录" in str(error):
                        status_message = "登录状态已过期"
                    _set_kuaishou_runtime_item(
                        args.config,
                        acct,
                        {
                            "label": acct,
                            "running": False,
                            "ok": False,
                            "progress": 100,
                            "message": f"{status_message}: {str(error)[:160]}",
                            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    )
                    continue

                if not export_path:
                    last_err = RuntimeError(f"account={acct!r} export returned empty path")
                    print(f"[pipeline] {last_err}", file=sys.stderr)
                    failed_accounts.append(acct)
                    _set_kuaishou_runtime_item(
                        args.config,
                        acct,
                        {
                            "label": acct,
                            "running": False,
                            "ok": False,
                            "progress": 100,
                            "message": "导出失败: 未返回导出文件路径",
                            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    )
                    continue
                
                # 清理旧文件
                per_download_dir = os.path.join(download_dir, acct)
                try:
                    _cleanup_keep_latest_files(per_download_dir, keep=keep_exports)
                except Exception:
                    pass
                
                if not args.export_only:
                    metadata = account_metadata[acct]
                    # 投放信息表写入：是否编辑/新增由 sync_to_feishu 内部根据 niu_metrics['is_live'] 决定。
                    # 这里保持传递完整 niu_metrics，以便写入 Q 列“直播状态”。
                    include_niu_metrics = metadata["niu_metrics"]
                    
                    export_data_list.append({
                        "export_path": export_path,
                        "account": acct,
                        "live_id": metadata["live_id"],
                        "niu_metrics": include_niu_metrics,
                    })
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": False,
                        "ok": True,
                        "progress": 100,
                        "message": "已导出完成，等待下一步",
                        "export_path": export_path,
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )

            if failed_accounts:
                try:
                    print(f"[pipeline] parallel export failed accounts ({len(failed_accounts)}): {failed_accounts}", file=sys.stderr)
                except Exception:
                    pass
        
        except Exception as e:
            last_err = e
            print(f"[pipeline] parallel export failed: {e}", file=sys.stderr)
            raise
    
    else:
        # 串行导出（单个账号或空账号）
        for acct in accounts_to_export:
            metadata = account_metadata[acct]
            per_download_dir = download_dir if not acct else os.path.join(download_dir, acct)
            export_cmd = [
                sys.executable,
                "export_kuaishou.py",
                "--download-dir",
                per_download_dir,
                "--profile-base-dir",
                kuaishou_profile_base_dir_bg,
                "--runtime-config",
                args.config,
                "--status-key",
                acct,
            ]
            if args.headless:
                export_cmd.append("--headless")

            if acct:
                if not anchor_map_csv:
                    raise RuntimeError("config.json missing mapping.anchor_map_csv; required for --account/--all-accounts")
                export_cmd.extend(["--anchor-map-csv", anchor_map_csv, "--account", acct])

            try:
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": True,
                        "ok": False,
                        "progress": 1,
                        "message": "开始导出",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                export_path = subprocess.check_output(export_cmd, text=True).strip()
                if not export_path:
                    raise RuntimeError("export_kuaishou.py returned empty path")

                # Retention: keep only the latest exports to avoid disk growth.
                try:
                    _cleanup_keep_latest_files(per_download_dir, keep=keep_exports)
                except Exception:
                    pass

                if args.export_only:
                    continue

                # 收集导出数据，稍后批量同步
                metadata = account_metadata[acct]
                # 投放信息表写入：是否编辑/新增由 sync_to_feishu 内部根据 niu_metrics['is_live'] 决定。
                # 这里保持传递完整 niu_metrics，以便写入 Q 列“直播状态”。
                include_niu_metrics = metadata["niu_metrics"]
                
                export_data_list.append({
                    "export_path": export_path,
                    "account": acct,
                    "live_id": metadata["live_id"],
                    "niu_metrics": include_niu_metrics,
                })
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": False,
                        "ok": True,
                        "progress": 100,
                        "message": "已导出完成，等待下一步",
                        "export_path": export_path,
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                
            except Exception as e:
                last_err = e
                msg = str(e)
                status_message = "导出失败"
                if "requires login" in msg or "login" in msg.lower() or "登录" in msg:
                    status_message = "登录状态已过期"
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": False,
                        "ok": False,
                        "progress": 100,
                        "message": f"{status_message}: {msg[:160]}",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                if acct:
                    print(f"[pipeline] account={acct!r} export failed: {e}", file=sys.stderr)
                    continue
                raise
    
    # 批量同步所有账号的数据到飞书（只打开一次云表格）
    if export_data_list and not args.export_only:
        print(f"[pipeline] batch sync {len(export_data_list)} accounts to Feishu", file=sys.stderr)
        try:
            for item in export_data_list:
                acct = str(item.get("account") or "").strip()
                if not acct:
                    continue
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": True,
                        "ok": True,
                        "progress": 100,
                        "message": "已导出完成，正在同步飞书",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            # 创建批量同步配置
            cfg_copy = cfg.copy()
            cfg_copy["input"] = {
                "batch_mode": True,
                "batch_data": export_data_list,
            }
            tmp_cfg_path = os.path.join(".state", "config.runtime.json")
            os.makedirs(os.path.dirname(tmp_cfg_path), exist_ok=True)
            with open(tmp_cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg_copy, f, ensure_ascii=False, indent=2)

            sync_cmd = [sys.executable, "sync_to_feishu.py", "--config", tmp_cfg_path, "sync"]
            subprocess.check_call(sync_cmd)
            for item in export_data_list:
                acct = str(item.get("account") or "").strip()
                if not acct:
                    continue
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": False,
                        "ok": True,
                        "progress": 100,
                        "message": "主流程已完成",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
        except Exception as e:
            last_err = e
            print(f"[pipeline] batch sync failed: {e}", file=sys.stderr)
            for item in export_data_list:
                acct = str(item.get("account") or "").strip()
                if not acct:
                    continue
                _set_kuaishou_runtime_item(
                    args.config,
                    acct,
                    {
                        "label": acct,
                        "running": False,
                        "ok": False,
                        "progress": 100,
                        "message": f"同步飞书失败: {str(e)[:160]}",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            raise

    # WenZong 流程：在主流程完成后串行执行（独立云文档/独立主播映射表；不写投放信息表）
    if (not args.export_only) and wenzong_enabled:
        try:
            if not wenzong_anchor_map_csv:
                raise RuntimeError("config.json missing mapping.wenzong_anchor_map_csv")

            wz_accounts = []
            if args.all_accounts:
                wz_accounts = load_accounts_from_anchor_csv(wenzong_anchor_map_csv)
                if not wz_accounts:
                    raise RuntimeError(f"No accounts found in wenzong_anchor_map_csv={wenzong_anchor_map_csv!r}")
            elif args.account:
                wz_accounts = [args.account]
            else:
                wz_accounts = [""]

            # De-dup like main flow
            wz_seen: set = set()
            wz_accounts_to_export = []
            for acct in wz_accounts:
                acct_s = str(acct or "").strip()
                acct_key = _norm_name(acct_s)
                if acct_key and acct_key in wz_seen:
                    continue
                if acct_key:
                    wz_seen.add(acct_key)
                wz_accounts_to_export.append(acct_s)

            wz_export_data_list = []
            wz_use_parallel = len(wz_accounts_to_export) > 1 and all(a for a in wz_accounts_to_export)
            if wz_use_parallel:
                print(f"[pipeline] WenZong: Using parallel export for {len(wz_accounts_to_export)} accounts", file=sys.stderr)
                wz_parallel_cmd = [
                    sys.executable,
                    "export_kuaishou_parallel.py",
                    "--url",
                    wenzong_classroom_url,
                    "--accounts",
                    ",".join(wz_accounts_to_export),
                    "--anchor-map-csv",
                    wenzong_anchor_map_csv,
                    "--download-dir",
                    download_dir,
                    "--profile-base-dir",
                    kuaishou_profile_base_dir_bg,
                ]
                if export_max_workers > 0:
                    wz_parallel_cmd.extend(["--max-workers", str(export_max_workers)])
                if args.headless:
                    wz_parallel_cmd.append("--headless")

                wz_result_json = _run_capture_stdout_stream_stderr(wz_parallel_cmd).strip()
                wz_results = json.loads(wz_result_json)
                for acct in wz_accounts_to_export:
                    result = wz_results.get(acct, {})
                    export_path = result.get("export_path")
                    error = result.get("error")
                    if error:
                        print(f"[pipeline] WenZong: account={acct!r} export failed: {error}", file=sys.stderr)
                        continue
                    if not export_path:
                        print(f"[pipeline] WenZong: account={acct!r} export returned empty path", file=sys.stderr)
                        continue
                    per_download_dir = os.path.join(download_dir, acct)
                    try:
                        _cleanup_keep_latest_files(per_download_dir, keep=keep_exports)
                    except Exception:
                        pass
                    wz_export_data_list.append({"export_path": export_path, "account": acct, "live_id": "", "niu_metrics": None})
            else:
                for acct in wz_accounts_to_export:
                    per_download_dir = download_dir if not acct else os.path.join(download_dir, acct)
                    export_cmd = [
                        sys.executable,
                        "export_kuaishou.py",
                        "--url",
                        wenzong_classroom_url,
                        "--download-dir",
                        per_download_dir,
                        "--profile-base-dir",
                        kuaishou_profile_base_dir_bg,
                    ]
                    if args.headless:
                        export_cmd.append("--headless")
                    if acct:
                        export_cmd.extend(["--anchor-map-csv", wenzong_anchor_map_csv, "--account", acct])
                    export_path = subprocess.check_output(export_cmd, text=True).strip()
                    if not export_path:
                        print(f"[pipeline] WenZong: account={acct!r} export returned empty path", file=sys.stderr)
                        continue
                    try:
                        _cleanup_keep_latest_files(per_download_dir, keep=keep_exports)
                    except Exception:
                        pass
                    wz_export_data_list.append({"export_path": export_path, "account": acct, "live_id": "", "niu_metrics": None})

            if wz_export_data_list:
                print(f"[pipeline] WenZong: batch sync {len(wz_export_data_list)} accounts to Feishu", file=sys.stderr)
                wz_cfg_copy = cfg.copy()
                wz_cfg_copy["target"] = wenzong_target_cfg
                wz_cfg_copy["mapping"] = dict(wz_cfg_copy.get("mapping") or {})
                wz_cfg_copy["mapping"]["anchor_map_csv"] = wenzong_anchor_map_csv
                try:
                    wz_uc_dir = (wz_cfg_copy["mapping"].get("wenzong_user_contact_export_dir") or "").strip()
                except Exception:
                    wz_uc_dir = ""
                if wz_uc_dir:
                    wz_cfg_copy["mapping"]["user_contact_export_dir"] = wz_uc_dir

                try:
                    wz_uc_cfg_json = (wz_cfg_copy["mapping"].get("wenzong_user_contact_cfg_json") or "").strip()
                except Exception:
                    wz_uc_cfg_json = ""
                if wz_uc_cfg_json:
                    wz_cfg_copy["mapping"]["user_contact_cfg_json"] = wz_uc_cfg_json

                try:
                    wz_uc_seq_json = (wz_cfg_copy["mapping"].get("wenzong_user_contact_seq_json") or "").strip()
                except Exception:
                    wz_uc_seq_json = ""
                if wz_uc_seq_json:
                    wz_cfg_copy["mapping"]["user_contact_seq_json"] = wz_uc_seq_json
                wz_cfg_copy["input"] = {"batch_mode": True, "batch_data": wz_export_data_list}
                tmp_wz_cfg_path = os.path.join(".state", "config.runtime.wenzong.json")
                os.makedirs(os.path.dirname(tmp_wz_cfg_path), exist_ok=True)
                with open(tmp_wz_cfg_path, "w", encoding="utf-8") as f:
                    json.dump(wz_cfg_copy, f, ensure_ascii=False, indent=2)
                wz_sync_cmd = [sys.executable, "sync_to_feishu.py", "--config", tmp_wz_cfg_path, "sync"]
                subprocess.check_call(wz_sync_cmd)
        except Exception as e:
            last_err = e
            print(f"[pipeline] WenZong flow failed: {e}", file=sys.stderr)
            raise

    if last_err and len(accounts) > 1:
        raise last_err


if __name__ == "__main__":
    main()
