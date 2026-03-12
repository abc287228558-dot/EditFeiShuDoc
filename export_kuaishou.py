import argparse
import csv
import os
import re
import signal
import sys
import time
from datetime import datetime

from typing import Any, Optional

import fcntl

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_once(
    url: str,
    user_data_dir: str,
    download_dir: str,
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int,
    fallback_user_data_dir: str = "",
    anchor_map_csv: str = "",
    expected_account: str = "",
    ks_id: str = "",
) -> str:
    user_data_dir = os.path.abspath(user_data_dir)
    download_dir = os.path.abspath(download_dir)
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(download_dir, exist_ok=True)

    candidates = [user_data_dir]
    if fallback_user_data_dir:
        fallback_abs = os.path.abspath(fallback_user_data_dir)
        if fallback_abs and (fallback_abs not in candidates) and os.path.isdir(fallback_abs):
            candidates.append(fallback_abs)

    last_login_url = ""
    for cand_user_data_dir in candidates:
        os.makedirs(cand_user_data_dir, exist_ok=True)
        print(f"[kuaishou] profile_dir: {cand_user_data_dir}", file=sys.stderr)
        print(f"[kuaishou] download_dir: {download_dir}", file=sys.stderr)

        with sync_playwright() as p:
            browser = None

            def _graceful_exit(signum: int, frame: object) -> None:
                try:
                    if browser is not None:
                        browser.close()
                finally:
                    raise SystemExit(130)

            old_int = signal.signal(signal.SIGINT, _graceful_exit)
            old_term = signal.signal(signal.SIGTERM, _graceful_exit)

            try:
                last_launch_err: Exception = None  # type: ignore
                for attempt in range(1, 6):
                    try:
                        browser = p.chromium.launch_persistent_context(
                            user_data_dir=cand_user_data_dir,
                            headless=headless,
                            accept_downloads=True,
                            downloads_path=download_dir,
                        )
                        last_launch_err = None  # type: ignore
                        break
                    except Exception as e:
                        last_launch_err = e
                        msg = str(e)
                        if ("SingletonLock" in msg) or ("ProcessSingleton" in msg) or ("profile directory" in msg):
                            wait_s = min(8.0, 0.8 * attempt)
                            print(
                                f"[kuaishou] profile busy (attempt {attempt}/5). Waiting {wait_s:.1f}s then retry...",
                                file=sys.stderr,
                            )
                            time.sleep(wait_s)
                            continue
                        raise

                if browser is None:
                    raise RuntimeError(
                        "Kuaishou export cannot start browser: profile directory is already in use. "
                        "Please close any Chromium/Playwright windows using this profile, then retry. "
                        f"profile_dir={cand_user_data_dir} last_error={last_launch_err}"
                    )
                page = browser.new_page()

                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1200)

                if "kuaishou.com" not in page.url:
                    raise RuntimeError(f"Unexpected redirect: {page.url}")

                if "passport.kuaishou.com" in page.url or "id.kuaishou.com" in page.url:
                    last_login_url = page.url
                    if headless:
                        continue

                    print(
                        f"Detected login page (url={page.url}). Please complete login in the opened browser window...\n"
                        f"profile_dir={cand_user_data_dir}",
                        file=sys.stderr,
                    )
                    login_deadline_ms = max(timeout_ms, login_wait_ms)
                    try:
                        page.wait_for_url(
                            re.compile(r"https://kt\.kuaishou\.com/student-management/offsite-student-management"),
                            timeout=login_deadline_ms,
                        )
                    except PlaywrightTimeoutError as e:
                        raise RuntimeError(
                            "Login not completed in time. Please finish login in the opened browser window, then re-run."
                        ) from e

                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                    try:
                        browser.storage_state(path=os.path.join(cand_user_data_dir, "storage_state.json"))
                    except Exception:
                        pass

                def _text_only(s: Any) -> str:
                    t = str(s or "")
                    t = re.sub(r"\s+", "", t)
                    t = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]", "", t)
                    return t.strip()

                def _is_valid_display_name(name: str) -> bool:
                    n = _text_only(name)
                    if not n or len(n) < 2:
                        return False
                    for bad in [
                        "快手课堂经营者平台",
                        "快手课堂",
                        "课堂经营者平台",
                        "学生管理",
                        "站外学员管理",
                    ]:
                        if bad and bad in n:
                            return False
                    return True

                def _try_get_display_account_name() -> str:
                    candidates = [
                        "css=header [class*='user'] [class*='name']",
                        "css=header [class*='user']",
                        "css=[class*='user'] [class*='name']",
                        "css=[class*='user']",
                        "css=[class*='avatar'] + span",
                        "css=[class*='avatar']",
                    ]
                    for sel in candidates:
                        try:
                            loc = page.locator(sel).first
                            loc.wait_for(state="visible", timeout=1200)
                            txt = _text_only(loc.inner_text(timeout=1200))
                            if _is_valid_display_name(txt):
                                return txt
                        except Exception:
                            continue
                    return ""

                def _maybe_update_anchor_map_csv(new_name: str) -> None:
                    if not new_name:
                        return
                    if not anchor_map_csv:
                        return
                    if not os.path.exists(anchor_map_csv):
                        return
                    exp = _text_only(expected_account)
                    if exp and new_name == exp:
                        return
                    try:
                        lock_path = anchor_map_csv + ".lock"
                        with open(lock_path, "a", encoding="utf-8") as lock_f:
                            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                            try:
                                with open(anchor_map_csv, "r", encoding="utf-8-sig", newline="") as f:
                                    reader = csv.DictReader(f)
                                    fieldnames = reader.fieldnames or []
                                    rows = []
                                    for r in reader:
                                        rows.append({(k or "").strip(): (v or "") for k, v in r.items()})
                                if not fieldnames:
                                    return

                                def _norm_id(v: Any) -> str:
                                    return _text_only(v)

                                updated = False
                                for r in rows:
                                    rid = _norm_id(r.get("快手ID", ""))
                                    if ks_id and rid and rid == _norm_id(ks_id):
                                        r["直播账号"] = new_name
                                        updated = True
                                        break
                                if not updated and expected_account:
                                    for r in rows:
                                        if _text_only(r.get("直播账号", "")) == exp:
                                            r["直播账号"] = new_name
                                            updated = True
                                            break
                                if not updated:
                                    return

                                tmp_path = anchor_map_csv + ".tmp"
                                with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
                                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                                    writer.writeheader()
                                    for r in rows:
                                        out = {k: r.get(k, "") for k in fieldnames}
                                        writer.writerow(out)
                                os.replace(tmp_path, anchor_map_csv)
                                print(
                                    f"[kuaishou] anchor_map updated: expected={expected_account!r} -> new={new_name!r} (ks_id={ks_id!r})",
                                    file=sys.stderr,
                                )
                            finally:
                                try:
                                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"[kuaishou] anchor_map update failed: {e}", file=sys.stderr)

                try:
                    display_name = _try_get_display_account_name()
                    if display_name:
                        print(f"[kuaishou] detected_display_name={display_name!r}", file=sys.stderr)
                        _maybe_update_anchor_map_csv(display_name)
                    else:
                        print("[kuaishou] detected_display_name=''", file=sys.stderr)
                except Exception:
                    pass

                # 在凌晨0-5分时，点击"昨天"筛选按钮导出昨天的数据（避免跨天数据丢失）
                current_time = datetime.now()
                should_filter_yesterday = (current_time.hour == 0 and current_time.minute < 5)
                
                if should_filter_yesterday:
                    try:
                        print(f"[kuaishou] Current time: {current_time.strftime('%H:%M:%S')}, applying yesterday filter...", file=sys.stderr)
                        # 查找并点击"昨天"按钮
                        yesterday_btn = page.get_by_text("昨天", exact=True)
                        yesterday_btn.wait_for(state="visible", timeout=5000)
                        yesterday_btn.click()
                        page.wait_for_timeout(500)
                        
                        print("[kuaishou] Clicking '查询' button...", file=sys.stderr)
                        # 查找并点击"查询"按钮
                        query_btn = page.get_by_role("button", name="查询")
                        query_btn.wait_for(state="visible", timeout=5000)
                        query_btn.click()
                        
                        # 等待查询结果加载
                        page.wait_for_timeout(2000)
                        print("[kuaishou] Filter applied successfully (yesterday's data)", file=sys.stderr)
                    except PlaywrightTimeoutError as e:
                        print(f"[kuaishou] Warning: Could not apply '昨天' filter: {e}", file=sys.stderr)
                        print("[kuaishou] Continuing with current data...", file=sys.stderr)
                    except Exception as e:
                        print(f"[kuaishou] Warning: Error applying filter: {e}", file=sys.stderr)
                        print("[kuaishou] Continuing with current data...", file=sys.stderr)
                else:
                    print(f"[kuaishou] Current time: {current_time.strftime('%H:%M:%S')}, using default filter (today)", file=sys.stderr)

                try:
                    export_btn = page.get_by_role("button", name="导出")
                    export_btn.wait_for(state="visible", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    raise RuntimeError(f"Cannot find 导出 button. current_url={page.url}")

                export_btn.click()

                confirm_btn = page.get_by_role("button", name="确认导出")
                try:
                    confirm_btn.wait_for(state="visible", timeout=3000)
                except PlaywrightTimeoutError:
                    confirm_btn = None

                if confirm_btn is not None:
                    with page.expect_download(timeout=timeout_ms) as dl_info:
                        confirm_btn.click()
                    download = dl_info.value
                else:
                    with page.expect_download(timeout=timeout_ms) as dl_info:
                        export_btn.click()
                    download = dl_info.value

                suggested = download.suggested_filename
                if not suggested:
                    suggested = f"kuaishou_export_{_ts()}.xlsx"

                out_name = f"{_ts()}_{suggested}"
                out_path = os.path.join(download_dir, out_name)
                download.save_as(out_path)
                print(f"[kuaishou] export saved: {out_path}", file=sys.stderr)

                try:
                    browser.storage_state(path=os.path.join(cand_user_data_dir, "storage_state.json"))
                except Exception:
                    pass

                return out_path
            finally:
                signal.signal(signal.SIGINT, old_int)
                signal.signal(signal.SIGTERM, old_term)
                if browser is not None:
                    browser.close()

    if headless:
        raise RuntimeError(
            "Kuaishou classroom requires login but headless mode cannot complete it. "
            "Run once WITHOUT --headless to finish login in the opened browser window, then re-run. "
            f"profile_dir={user_data_dir} url={last_login_url}"
        )

    raise RuntimeError(
        f"Detected login page (url={last_login_url}). Please complete login in the opened browser window...\n"
        f"profile_dir={user_data_dir}"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--url",
        default="https://kt.kuaishou.com/student-management/offsite-student-management",
    )
    p.add_argument(
        "--user-data-dir",
        default=os.path.join(".state", "kuaishou_chromium"),
        help="Playwright persistent profile directory. If using --profile/--account, this will be auto-derived unless explicitly set.",
    )
    p.add_argument(
        "--profile",
        default="default",
        help="Profile name for persistent login. Maps to .state/kuaishou_profiles/<profile>. Ignored if --user-data-dir is explicitly set.",
    )
    p.add_argument(
        "--anchor-map-csv",
        default="",
        help="Anchor mapping CSV (主播映射表.csv). Used with --account to derive profile from 快手ID.",
    )
    p.add_argument(
        "--account",
        default="",
        help="直播账号 name in anchor-map CSV. If provided, will derive profile from its 快手ID.",
    )
    p.add_argument("--download-dir", default=os.path.join("exports"))
    p.add_argument("--headless", action="store_true")
    p.add_argument("--timeout-ms", type=int, default=120000)
    p.add_argument("--login-wait-ms", type=int, default=30 * 60 * 1000)
    return p


def main() -> None:
    args = build_parser().parse_args()

    user_data_dir = args.user_data_dir
    default_user_data_dir = os.path.join(".state", "kuaishou_chromium")
    fallback_user_data_dir = ""

    # If user didn't explicitly pass --user-data-dir, we allow deriving it from profile/account.
    if args.user_data_dir == default_user_data_dir:
        profile_name = args.profile
        ks_id = ""
        if args.account and args.anchor_map_csv:
            # Lazy CSV parsing to avoid adding heavy deps.
            with open(args.anchor_map_csv, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    # Strip whitespace and BOM to be compatible with headers like "\ufeff直播账号".
                    reader.fieldnames = [str(n).replace("\ufeff", "").strip() for n in reader.fieldnames]
                rows = []
                for r in reader:
                    rows.append({(k or "").strip(): (v or "") for k, v in r.items()})
            target = None
            for r in rows:
                acct_v = (r.get("直播账号") or r.get("\ufeff直播账号") or "").strip()
                if acct_v == args.account.strip():
                    target = r
                    break
            if not target:
                raise RuntimeError(f"Cannot find account={args.account!r} in {args.anchor_map_csv}")
            ks_id = (target.get("快手ID") or "").strip()
            if not ks_id:
                raise RuntimeError(f"Missing 快手ID for account={args.account!r} in {args.anchor_map_csv}")
            profile_name = ks_id

        if profile_name and profile_name != "default":
            user_data_dir = os.path.join(".state", "kuaishou_profiles", profile_name)
            fallback_user_data_dir = default_user_data_dir

    path = export_once(
        url=args.url,
        user_data_dir=user_data_dir,
        download_dir=args.download_dir,
        headless=args.headless,
        timeout_ms=args.timeout_ms,
        login_wait_ms=args.login_wait_ms,
        fallback_user_data_dir=fallback_user_data_dir,
        anchor_map_csv=args.anchor_map_csv,
        expected_account=args.account,
        ks_id=ks_id if 'ks_id' in locals() else "",
    )
    sys.stdout.write(path)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
