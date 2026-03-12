import argparse
import json
import os
import subprocess
import sys
import re
import time
import threading
from typing import Any, Dict, Optional



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
                if headless:
                    raise RuntimeError(
                        "Kuaishou niu page requires login. Run once with target.niu_headless=false to login, "
                        f"then re-run headless. profile_dir={user_data_dir} url={page.url}"
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
                if headless:
                    raise RuntimeError(
                        "Kuaishou niu page requires login. Run once with target.niu_headless=false to login, "
                        f"then re-run headless. profile_dir={user_data_dir} url={page.url}"
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
            try:
                page.wait_for_load_state("networkidle", timeout=min(15000, timeout_ms))
            except Exception:
                pass
            page.wait_for_timeout(1200)

            # Apply date filter to get data from last 7 days (avoid missing data after midnight).
            try:
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

            # Set page size to 20 items per page (to see more data without pagination).
            try:
                print("[pipeline] niu setting page size to 20 items...", file=sys.stderr)
                # 查找分页器中的每页显示数量选择器（通常在右下角）
                # Ant Design 的分页器类名通常是 .ant-pagination
                page_size_selector = page.locator(".ant-select-selector").filter(has_text=re.compile(r"条/页|每页")).first
                if page_size_selector.count() > 0:
                    page_size_selector.click()
                    page.wait_for_timeout(800)
                    # 选择20条/页选项
                    option_20 = page.locator(".ant-select-item-option").filter(has_text=re.compile(r"20\s*条")).first
                    if option_20.count() > 0:
                        option_20.click()
                        page.wait_for_timeout(1000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=min(10000, timeout_ms))
                        except Exception:
                            pass
                        page.wait_for_timeout(2000)
                        print("[pipeline] niu page size set to 20 successfully", file=sys.stderr)
                    else:
                        print("[pipeline] niu 20 items option not found, using default", file=sys.stderr)
                else:
                    print("[pipeline] niu page size selector not found, using default", file=sys.stderr)
            except Exception as e:
                print(f"[pipeline] niu page size setting failed: {e}, using default", file=sys.stderr)
                # Try to close any open popup.
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            # Parse from DOM text: (status + name) and '直播ID：<digits>'
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
            items = []  # (name, live_id, is_live, start_dt, cost, direct_orders)
            for i, ln in enumerate(lines):
                m = re.search(r"直播ID\s*[:：]\s*(\d+)", ln)
                if not m:
                    continue
                live_id = m.group(1)
                # Look back a few lines for the name/status line.
                name = ""
                is_live = False
                for j in range(max(0, i - 3), i + 1):
                    cand = lines[j]
                    if "直播中" in cand:
                        is_live = True
                    # Heuristic: a line that is not just numbers and not the '直播ID' line.
                    if "直播ID" in cand:
                        continue
                    if re.fullmatch(r"\d+", cand):
                        continue
                    # Skip obvious headers.
                    if cand in {"直播间", "直播时间"}:
                        continue
                    # Prefer the last suitable candidate.
                    name = cand
                if name:
                    # Remove status prefix if present.
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

                # 从 start_dt 中提取时分
                start_hm = ""
                try:
                    mm = re.search(r"\b(\d{2}):(\d{2})\b", start_dt)
                    if mm:
                        start_hm = f"{mm.group(1)}:{mm.group(2)}"
                except Exception:
                    start_hm = ""

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
                    # 在直播ID后面查找数据行
                    # 数据行格式：花费 时长 涨粉数 直接订单数 ... (空格分隔的数字)
                    for j in range(i + 1, min(len(lines), i + 5)):
                        cand = lines[j]
                        # 跳过日期时间行
                        if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", cand):
                            continue
                        # 查找包含多个数字的数据行
                        # 格式：花费 时长 涨粉数 直接订单数 ...
                        parts = cand.split()
                        if len(parts) >= 4:
                            # 第4个字段是直接订单数（索引3）
                            try:
                                # 移除逗号并验证是否为数字
                                val = parts[3].replace(',', '')
                                if val.isdigit():
                                    direct_orders = val
                                    break
                            except Exception:
                                pass
                except Exception:
                    direct_orders = ""

                items.append((name, live_id, is_live, start_dt, cost, direct_orders))

            live_map: Dict[str, str] = {}
            metrics_map: Dict[str, Dict[str, str]] = {}
            for name, live_id, is_live, start_dt, cost, direct_orders in items:
                if not name or not live_id:
                    continue
                
                # 根据 only_run_when_live 配置决定是否过滤
                if only_run_when_live and not is_live:
                    # 跳过已结束的直播
                    continue
                
                # 从 start_dt 中提取时分
                item_start_hm = ""
                try:
                    mm = re.search(r"\b(\d{2}):(\d{2})\b", start_dt)
                    if mm:
                        item_start_hm = f"{mm.group(1)}:{mm.group(2)}"
                except Exception:
                    item_start_hm = ""
                
                # First win.
                live_map.setdefault(name, live_id)
                metrics_map.setdefault(
                    name,
                    {
                        "live_id": str(live_id),
                        "start_dt": str(start_dt),
                        "start_hm": str(item_start_hm),
                        "cost": str(cost),
                        "direct_orders": str(direct_orders),
                        "is_live": str(is_live),  # 保留直播状态信息
                    },
                )

            if not live_map:
                print(
                    f"[pipeline] niu live map empty: using_cdp={using_cdp} final_url={getattr(page, 'url', '')}",
                    file=sys.stderr,
                )
            # Attach metrics for caller via attribute (keeps backward compat).
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



def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_capture_stdout_stream_stderr(cmd: list, *, env: Optional[Dict[str, str]] = None) -> str:
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
    niu_profile_dir = str(target_cfg.get("niu_profile_dir", os.path.join(".state", "niu_profile")))
    niu_headless = bool(target_cfg.get("niu_headless", True))
    niu_timeout_ms = int(target_cfg.get("niu_timeout_ms", 60000))
    niu_login_wait_ms = int(target_cfg.get("niu_login_wait_ms", 180000))
    niu_cdp_url = str(target_cfg.get("niu_cdp_url", "") or "").strip()
    niu_account_id_default = str(target_cfg.get("niu_account_id_default", "") or "").strip()
    show_missing_niu_account_mapping = bool(target_cfg.get("show_missing_niu_account_mapping", False))
    export_max_workers = int(target_cfg.get("export_max_workers", 2))
    download_dir = os.path.join("exports")

    # Keep only_run_when_live behavior even during headful niu login.
    # Otherwise, a headful login run with --all-accounts may export all accounts and spawn many browsers.

    anchor_map_csv = (cfg.get("mapping") or {}).get("anchor_map_csv") or ""

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
    
    # 从金牛网获取所有账号的数据。
    # 注意：为了支持投放信息表 Q 列“直播状态”写入，我们这里始终拉取包含“直播中/已结束”的完整列表，
    # 但后续是否写入/编辑投放信息内容仍由 only_run_when_live + is_live 决定。
    if live_id_fetch_enabled and live_id_fetch_mode == "niu" and accounts and anchor_map_csv:
        rows = load_account_rows_from_anchor_csv(anchor_map_csv)
        acct_to_row = {(r.get("直播账号") or r.get("\ufeff直播账号") or "").strip(): r for r in rows}
        # Group by distinct __accountId__ so we open commonReport once per accountId.
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

        for account_id, accts in groups.items():
            try:
                live_map = _fetch_live_map_from_niu(
                    account_id=account_id,
                    user_data_dir=niu_profile_dir,
                    headless=niu_headless,
                    timeout_ms=niu_timeout_ms,
                    login_wait_ms=niu_login_wait_ms,
                    cdp_url=niu_cdp_url,
                    # Always fetch full list so we can write Q column live status for ended lives too.
                    only_run_when_live=False,
                )

                live_map_norm: Dict[str, str] = {}
                metrics_map = getattr(_fetch_live_map_from_niu, "_last_metrics_map", {}) or {}
                metrics_map_norm: Dict[str, Dict[str, str]] = {}
                for k, v in (live_map or {}).items():
                    nk = _norm_name(k)
                    if nk and v:
                        live_map_norm.setdefault(nk, v)
                for k, mv in (metrics_map or {}).items():
                    nk = _norm_name(k)
                    if nk and isinstance(mv, dict):
                        metrics_map_norm.setdefault(nk, {str(kk): str(vv) for kk, vv in mv.items()})

                for acct in accts:
                    n_acct = _norm_name(acct)
                    if n_acct and (n_acct in live_map_norm):
                        live_id_by_account[acct] = live_map_norm[n_acct]
                        if n_acct in metrics_map_norm:
                            niu_metrics_by_account[acct] = metrics_map_norm[n_acct]
                        continue
                    # Containment fallback (handles slight name differences).
                    for nk, v in live_map_norm.items():
                        if not nk:
                            continue
                        if n_acct and (nk in n_acct or n_acct in nk):
                            live_id_by_account[acct] = v
                            if nk in metrics_map_norm:
                                niu_metrics_by_account[acct] = metrics_map_norm[nk]
                            break
            except Exception as e:
                print(f"[pipeline] live_id fetch failed for account_id={account_id!r}: {e}", file=sys.stderr)

    last_err: Optional[Exception] = None
    # 收集所有账号的导出数据
    export_data_list = []
    
    # 过滤需要导出的账号
    accounts_to_export = []
    account_metadata = {}  # 存储每个账号的元数据
    seen_accounts_norm: set = set()
    
    for acct in accounts:
        acct_s = str(acct or "").strip()
        acct_key = _norm_name(acct_s)
        if acct_key and acct_key in seen_accounts_norm:
            continue
        if acct_key:
            seen_accounts_norm.add(acct_key)
        auto_live_id = live_id_by_account.get(acct, "")
        auto_niu_metrics = niu_metrics_by_account.get(acct, {})
        effective_live_id = str(args.live_id or "").strip() or auto_live_id
        
        # 所有账号都要导出快手课堂数据（用户对接信息表）
        # only_run_when_live 只影响投放信息表的填写
        
        accounts_to_export.append(acct_s)
        account_metadata[acct_s] = {
            "live_id": effective_live_id,
            "niu_metrics": auto_niu_metrics if (acct and isinstance(auto_niu_metrics, dict) and auto_niu_metrics) else None,
        }
    
    # 判断是否使用并发导出
    use_parallel = len(accounts_to_export) > 1 and all(a for a in accounts_to_export)
    
    if use_parallel:
        # 并发导出多个账号
        print(f"[pipeline] Using parallel export for {len(accounts_to_export)} accounts", file=sys.stderr)
        
        parallel_cmd = [
            sys.executable,
            "export_kuaishou_parallel.py",
            "--accounts",
            ",".join(accounts_to_export),
            "--anchor-map-csv",
            anchor_map_csv,
            "--download-dir",
            download_dir,
        ]
        if export_max_workers > 0:
            parallel_cmd.extend(["--max-workers", str(export_max_workers)])
        if args.headless:
            parallel_cmd.append("--headless")
        
        try:
            result_json = _run_capture_stdout_stream_stderr(parallel_cmd).strip()
            results = json.loads(result_json)
            
            # 处理并发导出结果
            for acct in accounts_to_export:
                result = results.get(acct, {})
                export_path = result.get("export_path")
                error = result.get("error")
                
                if error:
                    last_err = RuntimeError(f"account={acct!r} export failed: {error}")
                    print(f"[pipeline] {last_err}", file=sys.stderr)
                    continue
                
                if not export_path:
                    last_err = RuntimeError(f"account={acct!r} export returned empty path")
                    print(f"[pipeline] {last_err}", file=sys.stderr)
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
            ]
            if args.headless:
                export_cmd.append("--headless")

            if acct:
                if not anchor_map_csv:
                    raise RuntimeError("config.json missing mapping.anchor_map_csv; required for --account/--all-accounts")
                export_cmd.extend(["--anchor-map-csv", anchor_map_csv, "--account", acct])

            try:
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
                
            except Exception as e:
                last_err = e
                if acct:
                    print(f"[pipeline] account={acct!r} export failed: {e}", file=sys.stderr)
                    continue
                raise
    
    # 批量同步所有账号的数据到飞书（只打开一次云表格）
    if export_data_list and not args.export_only:
        print(f"[pipeline] batch sync {len(export_data_list)} accounts to Feishu", file=sys.stderr)
        try:
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
        except Exception as e:
            last_err = e
            print(f"[pipeline] batch sync failed: {e}", file=sys.stderr)
            raise

    if last_err and len(accounts) > 1:
        raise last_err


if __name__ == "__main__":
    main()
