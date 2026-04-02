"""
并发导出多个快手课堂账号的数据

使用多进程并发打开多个浏览器实例，同时导出多个账号的数据，大幅提升速度。
"""
import argparse
import json
import multiprocessing
import os
import sys
import time
from typing import Dict, List, Optional, Tuple


def export_single_account(
    account: str,
    anchor_map_csv: str,
    download_dir: str,
    url: str,
    profile_base_dir: str,
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int,
    runtime_config: str,
    retries: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    导出单个账号的数据
    
    Returns:
        (account, export_path, error_message)
    """
    # 导入放在函数内部，避免在主进程中导入 playwright
    import subprocess

    def _tail(s: str, max_chars: int = 3000) -> str:
        s = str(s or "")
        if len(s) <= max_chars:
            return s
        return s[-max_chars:]

    per_download_dir = os.path.join(download_dir, account)
    export_cmd = [
        sys.executable,
        "export_kuaishou.py",
        "--url",
        url,
        "--download-dir",
        per_download_dir,
        "--anchor-map-csv",
        anchor_map_csv,
        "--account",
        account,
        "--profile-base-dir",
        profile_base_dir,
        "--runtime-config",
        runtime_config,
        "--status-key",
        account,
    ]
    if headless:
        export_cmd.append("--headless")

    max_attempts = max(1, int(retries) if retries is not None else 1)
    last_err: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[parallel] Starting export for account={account} attempt={attempt}/{max_attempts}", file=sys.stderr)
            start_time = time.time()

            proc = subprocess.run(
                export_cmd,
                text=True,
                capture_output=True,
                timeout=timeout_ms / 1000.0,
            )

            elapsed = time.time() - start_time
            stdout_s = (proc.stdout or "").strip()
            stderr_s = (proc.stderr or "").strip()

            if proc.returncode != 0:
                last_err = (
                    f"export_kuaishou.py exit_code={proc.returncode} elapsed={elapsed:.1f}s "
                    f"stderr_tail={_tail(stderr_s)!r}"
                )
                print(f"[parallel] account={account} failed attempt={attempt}/{max_attempts}: {last_err}", file=sys.stderr)
                if attempt < max_attempts:
                    time.sleep(min(5.0, 0.8 * attempt))
                    continue
                return (account, None, last_err)

            export_path = stdout_s
            if not export_path:
                last_err = f"export_kuaishou.py returned empty path elapsed={elapsed:.1f}s stderr_tail={_tail(stderr_s)!r}"
                print(f"[parallel] account={account} failed attempt={attempt}/{max_attempts}: {last_err}", file=sys.stderr)
                if attempt < max_attempts:
                    time.sleep(min(5.0, 0.8 * attempt))
                    continue
                return (account, None, last_err)

            print(f"[parallel] Completed account={account} in {elapsed:.1f}s path={export_path}", file=sys.stderr)
            return (account, export_path, None)
        except subprocess.TimeoutExpired:
            last_err = f"Export timeout after {timeout_ms/1000.0}s"
            print(f"[parallel] account={account} timeout attempt={attempt}/{max_attempts}", file=sys.stderr)
            if attempt < max_attempts:
                time.sleep(min(5.0, 0.8 * attempt))
                continue
            return (account, None, last_err)
        except Exception as e:
            last_err = str(e)
            print(f"[parallel] account={account} exception attempt={attempt}/{max_attempts}: {e}", file=sys.stderr)
            if attempt < max_attempts:
                time.sleep(min(5.0, 0.8 * attempt))
                continue
            return (account, None, last_err)

    return (account, None, last_err or "Unknown error")


def export_parallel(
    accounts: List[str],
    anchor_map_csv: str,
    download_dir: str,
    url: str,
    profile_base_dir: str,
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int,
    runtime_config: str,
    max_workers: Optional[int] = None,
    retries: int = 3,
) -> Dict[str, Dict[str, str]]:
    """
    并发导出多个账号的数据
    
    Args:
        accounts: 账号列表
        max_workers: 最大并发数，默认为账号数量（即全部并发）
    
    Returns:
        {
            "account1": {"export_path": "...", "error": None},
            "account2": {"export_path": None, "error": "..."},
        }
    """
    if not accounts:
        return {}
    
    # 默认全部并发，但可以通过 max_workers 限制
    if max_workers is None:
        max_workers = len(accounts)
    
    print(f"[parallel] Starting parallel export for {len(accounts)} accounts with {max_workers} workers", file=sys.stderr)
    start_time = time.time()
    
    # 使用进程池并发执行
    with multiprocessing.Pool(processes=max_workers) as pool:
        # 准备参数
        tasks = [
            (account, anchor_map_csv, download_dir, url, profile_base_dir, headless, timeout_ms, login_wait_ms, runtime_config, retries)
            for account in accounts
        ]
        
        # 并发执行
        results = pool.starmap(export_single_account, tasks)
    
    # 整理结果
    result_dict = {}
    success_count = 0
    for account, export_path, error in results:
        result_dict[account] = {
            "export_path": export_path,
            "error": error,
        }
        if export_path and not error:
            success_count += 1
    
    elapsed = time.time() - start_time
    print(
        f"[parallel] Completed {success_count}/{len(accounts)} accounts in {elapsed:.1f}s "
        f"(avg {elapsed/len(accounts):.1f}s per account)",
        file=sys.stderr
    )
    
    return result_dict


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="并发导出多个快手课堂账号的数据")
    p.add_argument(
        "--url",
        default="https://kt.kuaishou.com/student-management/offsite-student-management",
        help="快手课堂页面URL（默认站外学员管理）",
    )
    p.add_argument(
        "--accounts",
        required=True,
        help="账号列表，逗号分隔，例如：蓝精灵1,蓝精灵2,蓝精灵3",
    )
    p.add_argument(
        "--anchor-map-csv",
        required=True,
        help="主播映射表 CSV 文件路径",
    )
    p.add_argument(
        "--download-dir",
        default=os.path.join("exports"),
        help="导出文件保存目录",
    )
    p.add_argument(
        "--profile-base-dir",
        default=os.path.join(".state", "kuaishou_profiles_bg"),
        help="后台导出使用的 profile 基础目录",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="无头模式运行浏览器",
    )
    p.add_argument(
        "--timeout-ms",
        type=int,
        default=120000,
        help="单个账号导出超时时间（毫秒）",
    )
    p.add_argument(
        "--login-wait-ms",
        type=int,
        default=30 * 60 * 1000,
        help="登录等待时间（毫秒）",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="最大并发数，默认为账号数量（全部并发）",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=3,
        help="单账号失败重试次数（默认3）",
    )
    p.add_argument(
        "--runtime-config",
        default="",
        help="主配置文件路径，用于写入快手运行状态",
    )
    p.add_argument(
        "--strict-fail",
        action="store_true",
        help="如果有任意账号失败则返回非0退出码（默认不严格失败，便于主程序继续处理成功账号）",
    )
    p.add_argument(
        "--output-json",
        default="",
        help="输出结果到 JSON 文件",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    
    # 解析账号列表
    accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    if not accounts:
        print("Error: No accounts provided", file=sys.stderr)
        sys.exit(1)
    
    # 并发导出
    results = export_parallel(
        accounts=accounts,
        anchor_map_csv=args.anchor_map_csv,
        download_dir=args.download_dir,
        url=args.url,
        profile_base_dir=args.profile_base_dir,
        headless=args.headless,
        timeout_ms=args.timeout_ms,
        login_wait_ms=args.login_wait_ms,
        runtime_config=args.runtime_config,
        max_workers=args.max_workers,
        retries=args.retries,
    )
    
    # 输出结果
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[parallel] Results saved to {args.output_json}", file=sys.stderr)
    
    # 输出到 stdout（JSON 格式）
    print(json.dumps(results, ensure_ascii=False))
    
    # 检查是否有失败的账号
    failed = [acc for acc, res in results.items() if res["error"]]
    if failed:
        print(f"[parallel] Warning: {len(failed)} accounts failed: {failed}", file=sys.stderr)
        if args.strict_fail:
            sys.exit(1)


if __name__ == "__main__":
    # 设置 multiprocessing 启动方法为 spawn（macOS 上更稳定）
    multiprocessing.set_start_method("spawn", force=True)
    main()
