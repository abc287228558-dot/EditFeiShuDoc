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
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    导出单个账号的数据
    
    Returns:
        (account, export_path, error_message)
    """
    try:
        # 导入放在函数内部，避免在主进程中导入 playwright
        import subprocess
        
        per_download_dir = os.path.join(download_dir, account)
        export_cmd = [
            sys.executable,
            "export_kuaishou.py",
            "--download-dir",
            per_download_dir,
            "--anchor-map-csv",
            anchor_map_csv,
            "--account",
            account,
        ]
        if headless:
            export_cmd.append("--headless")
        
        print(f"[parallel] Starting export for account={account}", file=sys.stderr)
        start_time = time.time()
        
        export_path = subprocess.check_output(
            export_cmd,
            text=True,
            timeout=timeout_ms / 1000.0,
        ).strip()
        
        elapsed = time.time() - start_time
        print(f"[parallel] Completed account={account} in {elapsed:.1f}s path={export_path}", file=sys.stderr)
        
        if not export_path:
            return (account, None, "export_kuaishou.py returned empty path")
        
        return (account, export_path, None)
        
    except subprocess.TimeoutExpired:
        return (account, None, f"Export timeout after {timeout_ms/1000.0}s")
    except Exception as e:
        return (account, None, str(e))


def export_parallel(
    accounts: List[str],
    anchor_map_csv: str,
    download_dir: str,
    headless: bool,
    timeout_ms: int,
    login_wait_ms: int,
    max_workers: Optional[int] = None,
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
            (account, anchor_map_csv, download_dir, headless, timeout_ms, login_wait_ms)
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
        headless=args.headless,
        timeout_ms=args.timeout_ms,
        login_wait_ms=args.login_wait_ms,
        max_workers=args.max_workers,
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
        sys.exit(1)


if __name__ == "__main__":
    # 设置 multiprocessing 启动方法为 spawn（macOS 上更稳定）
    multiprocessing.set_start_method("spawn", force=True)
    main()
