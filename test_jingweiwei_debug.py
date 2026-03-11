#!/usr/bin/env python3
"""测试井味味的同步情况"""

import json
import sys
import subprocess

# 创建一个只包含井味味的测试配置
config = {
    "feishu": {
        "app_id": "cli_a9200e9641fadbc0",
        "app_secret": "9tjBqUG6qRtDWxNqybbHeeNdx1A1hoSi"
    },
    "target": {
        "wiki_url": "https://my.feishu.cn/wiki/PWMUwFVPni4WY9kRunEckmW9n0g?sheet=J04Dnw",
        "spreadsheet_token": "",
        "sheet_id": "99e724",
        "sheet_title": "用户对接信息",
        "write_mode": "ui",
        "sync_delivery_sheet": True,
        "delivery_write_mode": "api",
        "ui_fallback_enabled": True,
        "ui_fallback_headless": False,
        "ui_fallback_profile_dir": ".state/feishu_profile",
        "ui_fallback_timeout_ms": 60000,
    },
    "input": {
        "file_path": "站外履约课学员表单.xls",
        "batch_mode": True,
        "batch_data": [
            {
                "account": "井味味",
                "export_path": "exports/井味味/20260309_212440_站外履约课学员表单.xls",
                "live_id": "14500288968",
                "niu_metrics": {
                    "start_dt": "2026-03-09",
                    "start_hm": "20:27",
                    "direct_orders": 10,
                    "cost": 100.5,
                    "live_id": "14500288968"
                }
            }
        ]
    },
    "mapping": {
        "anchor_map_csv": "主播映射表.csv"
    }
}

# 保存测试配置
with open(".state/config.test_jingweiwei.json", "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print("测试配置已创建: .state/config.test_jingweiwei.json")
print("开始测试井味味的同步...")

# 运行同步
result = subprocess.run(
    ["python3", "sync_to_feishu.py", "--config", ".state/config.test_jingweiwei.json", "sync"],
    capture_output=True,
    text=True
)

print("\n=== 标准输出 ===")
print(result.stdout)

print("\n=== 标准错误 ===")
print(result.stderr)

print(f"\n=== 退出码: {result.returncode} ===")

# 查找最新的日志文件
import os
import glob

log_files = glob.glob("logs/sync_*.log")
if log_files:
    latest_log = max(log_files, key=os.path.getmtime)
    print(f"\n=== 最新日志: {latest_log} ===")
    with open(latest_log, "r", encoding="utf-8") as f:
        lines = f.readlines()
        # 只打印包含井味味或DEBUG的行
        for line in lines:
            if "井味味" in line or "DEBUG" in line or "delivery_" in line:
                print(line.rstrip())
