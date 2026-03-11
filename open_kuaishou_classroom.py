#!/usr/bin/env python3
"""
打开快手课堂页面

根据主播映射表中的快手ID，打开对应的快手课堂学员管理页面
"""
import argparse
import csv
import os
import sys
import webbrowser
from typing import Dict, Optional


def load_anchor_map(csv_path: str) -> Dict[str, str]:
    """
    加载主播映射表
    
    Returns:
        {账号名: 快手ID}
    """
    anchor_map = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            account = row.get("直播账号", "").strip()
            ks_id = row.get("快手ID", "").strip()
            if account and ks_id:
                anchor_map[account] = ks_id
    return anchor_map


def get_classroom_url(ks_id: Optional[str] = None) -> str:
    """
    获取快手课堂URL
    
    Args:
        ks_id: 快手ID（可选），如果提供则添加到URL参数中
    
    Returns:
        快手课堂学员管理页面URL
    """
    base_url = "https://kt.kuaishou.com/student-management/offsite-student-management"
    
    # 如果提供了快手ID，可以添加到URL参数中（根据实际需要）
    # 目前快手课堂登录后会自动显示对应账号的数据
    return base_url


def open_classroom(account: Optional[str] = None, csv_path: str = "主播映射表.csv") -> None:
    """
    打开快手课堂页面
    
    Args:
        account: 账号名（可选），如果不提供则只打开快手课堂首页
        csv_path: 主播映射表CSV文件路径
    """
    ks_id = None
    
    if account:
        # 加载主播映射表
        if not os.path.exists(csv_path):
            print(f"❌ 主播映射表不存在: {csv_path}", file=sys.stderr)
            sys.exit(1)
        
        anchor_map = load_anchor_map(csv_path)
        
        if account not in anchor_map:
            print(f"❌ 账号不存在: {account}", file=sys.stderr)
            print(f"可用账号: {', '.join(anchor_map.keys())}", file=sys.stderr)
            sys.exit(1)
        
        ks_id = anchor_map[account]
        print(f"📱 账号: {account}")
        print(f"🆔 快手ID: {ks_id}")
    
    # 获取URL
    url = get_classroom_url(ks_id)
    print(f"🌐 打开快手课堂: {url}")
    
    # 在默认浏览器中打开
    webbrowser.open(url)
    print("✅ 已在浏览器中打开快手课堂页面")


def main():
    parser = argparse.ArgumentParser(
        description="打开快手课堂学员管理页面",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 打开快手课堂首页
  python3 open_kuaishou_classroom.py
  
  # 打开指定账号的快手课堂（需要先登录对应账号）
  python3 open_kuaishou_classroom.py --account 小新教带货
  
  # 使用自定义映射表
  python3 open_kuaishou_classroom.py --account 小新教带货 --csv 自定义映射表.csv
        """
    )
    
    parser.add_argument(
        "--account",
        help="账号名（主播映射表中的'直播账号'列）",
    )
    
    parser.add_argument(
        "--csv",
        default="主播映射表.csv",
        help="主播映射表CSV文件路径（默认: 主播映射表.csv）",
    )
    
    args = parser.parse_args()
    
    try:
        open_classroom(account=args.account, csv_path=args.csv)
    except KeyboardInterrupt:
        print("\n⚠️  用户中断", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
