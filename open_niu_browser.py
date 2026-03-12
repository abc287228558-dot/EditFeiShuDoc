#!/usr/bin/env python3
"""打开金牛报表浏览器（带登录状态）

与 run_pipeline.py 的金牛取数逻辑保持一致：使用 Playwright Chromium 的持久化 profile。
浏览器会保持打开，直到用户手动关闭。
"""

import argparse
import os
import sys
import subprocess
from playwright.sync_api import sync_playwright


def open_niu(profile_dir: str, url: str) -> None:
    profile_dir = os.path.abspath(profile_dir)

    # If user accidentally points to old system-Chrome-based profile dir, it may crash Playwright Chromium.
    try:
        if os.sep + "niu_profiles" + os.sep in profile_dir:
            print(
                "[niu] Warning: profile_dir is under .state/niu_profiles (may be created by system Chrome). "
                "Recommended to use .state/niu_pw_profiles/... for Playwright.",
                file=sys.stderr,
            )
    except Exception:
        pass

    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir, exist_ok=True)
        print(f"[niu] Created profile directory: {profile_dir}", file=sys.stderr)

    print("[niu] Opening niu page", file=sys.stderr)
    print(f"[niu]   Profile: {profile_dir}", file=sys.stderr)
    print(f"[niu]   URL: {url}", file=sys.stderr)

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
            )
        except Exception as e:
            # If the profile is already in use, Chromium refuses to start a second instance
            # to prevent profile corruption (SingletonLock / ProcessSingleton). In this case,
            # reuse the existing running Chromium instance and just open the URL.
            msg = str(e)
            if ("SingletonLock" in msg) or ("ProcessSingleton" in msg) or ("profile directory" in msg and "Aborting" in msg):
                try:
                    exe = p.chromium.executable_path
                    app_path = exe
                    # Convert .../Chromium.app/Contents/MacOS/Chromium -> .../Chromium.app
                    if "/Contents/MacOS/" in exe:
                        app_path = exe.split("/Contents/MacOS/")[0]
                    subprocess.Popen(
                        ["open", "-a", app_path, url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    print(
                        f"[niu] Profile is busy; reused existing Chromium instance. app={app_path} url={url}",
                        file=sys.stderr,
                    )
                    return
                except Exception as e2:
                    raise RuntimeError(f"Profile is busy and fallback open failed: {e2}") from e
            raise

        try:
            page = ctx.new_page()
            print("[niu] Loading page...", file=sys.stderr)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            print("[niu] Browser opened successfully!", file=sys.stderr)
            print("[niu] Close the browser window when done.", file=sys.stderr)

            try:
                while True:
                    if not ctx.pages:
                        print("[niu] All pages closed, exiting...", file=sys.stderr)
                        break
                    page.wait_for_timeout(1000)
            except KeyboardInterrupt:
                print("[niu] Interrupted by user", file=sys.stderr)
            except Exception as e:
                print(f"[niu] Error while waiting: {e}", file=sys.stderr)

        finally:
            # Let the user close the window; then the script exits.
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="打开金牛报表浏览器（带登录状态）")
    parser.add_argument("--profile-dir", required=True, help="Profile目录路径")
    parser.add_argument("--url", required=True, help="金牛报表URL")
    args = parser.parse_args()

    try:
        open_niu(profile_dir=args.profile_dir, url=args.url)
    except KeyboardInterrupt:
        print("\n[niu] Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n[niu] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
