#!/usr/bin/env python3
"""
打开快手课堂浏览器（带登录状态）

这个脚本会打开一个Playwright浏览器窗口，加载指定账号的登录状态。
浏览器会保持打开状态，直到用户手动关闭。
"""
import argparse
import os
import sys
from playwright.sync_api import sync_playwright


def open_classroom(profile_dir: str, classroom_url: str, account: str = "", ks_id: str = ""):
    """
    打开快手课堂浏览器
    
    Args:
        profile_dir: Profile目录路径
        classroom_url: 快手课堂URL
        account: 账号名（用于日志）
        ks_id: 快手ID（用于日志）
    """
    profile_dir = os.path.abspath(profile_dir)
    
    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir, exist_ok=True)
        print(f"[kuaishou] Created profile directory: {profile_dir}", file=sys.stderr)
    
    print(f"[kuaishou] Opening classroom", file=sys.stderr)
    if account:
        print(f"[kuaishou]   Account: {account}", file=sys.stderr)
    if ks_id:
        print(f"[kuaishou]   KS ID: {ks_id}", file=sys.stderr)
    print(f"[kuaishou]   Profile: {profile_dir}", file=sys.stderr)
    print(f"[kuaishou]   URL: {classroom_url}", file=sys.stderr)
    
    with sync_playwright() as p:
        # 启动带持久化上下文的浏览器
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
        )
        
        try:
            # 打开新页面
            page = ctx.new_page()
            
            # 访问快手课堂
            print(f"[kuaishou] Loading page...", file=sys.stderr)
            page.goto(classroom_url, wait_until="domcontentloaded", timeout=60000)
            
            print(f"[kuaishou] Browser opened successfully!", file=sys.stderr)
            print(f"[kuaishou] Close the browser window when done.", file=sys.stderr)
            
            # 保持浏览器打开，等待用户手动关闭
            # 通过检查页面是否还存在来判断浏览器是否被关闭
            try:
                while True:
                    # 检查是否还有打开的页面
                    if not ctx.pages:
                        print(f"[kuaishou] All pages closed, exiting...", file=sys.stderr)
                        break
                    
                    # 等待一段时间再检查
                    page.wait_for_timeout(1000)
                    
            except KeyboardInterrupt:
                print(f"[kuaishou] Interrupted by user", file=sys.stderr)
            except Exception as e:
                print(f"[kuaishou] Error while waiting: {e}", file=sys.stderr)
                
        except Exception as e:
            print(f"[kuaishou] Error opening classroom: {e}", file=sys.stderr)
            raise
        finally:
            # 不需要手动关闭，用户关闭窗口后会自动退出
            pass


def main():
    parser = argparse.ArgumentParser(
        description="打开快手课堂浏览器（带登录状态）"
    )
    
    parser.add_argument(
        "--profile-dir",
        required=True,
        help="Profile目录路径"
    )
    
    parser.add_argument(
        "--url",
        default="https://kt.kuaishou.com/student-management/offsite-student-management",
        help="快手课堂URL"
    )
    
    parser.add_argument(
        "--account",
        default="",
        help="账号名（用于日志）"
    )
    
    parser.add_argument(
        "--ks-id",
        default="",
        help="快手ID（用于日志）"
    )
    
    args = parser.parse_args()
    
    try:
        open_classroom(
            profile_dir=args.profile_dir,
            classroom_url=args.url,
            account=args.account,
            ks_id=args.ks_id
        )
    except KeyboardInterrupt:
        print("\n[kuaishou] Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n[kuaishou] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
