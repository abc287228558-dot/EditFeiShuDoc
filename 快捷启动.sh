#!/bin/bash
# 快手课堂快捷入口 - 快速启动脚本

echo "=================================="
echo "  快手课堂快捷入口"
echo "=================================="
echo ""
echo "请选择操作方式："
echo ""
echo "1) 启动网页界面（推荐）"
echo "2) 命令行打开（输入账号名）"
echo "3) 查看所有账号列表"
echo "4) 退出"
echo ""
read -p "请输入选项 (1-4): " choice

case $choice in
    1)
        echo ""
        echo "🚀 正在启动网页界面..."
        python3 start_viewer.py
        ;;
    2)
        echo ""
        read -p "请输入账号名: " account
        if [ -z "$account" ]; then
            echo "❌ 账号名不能为空"
            exit 1
        fi
        python3 open_kuaishou_classroom.py --account "$account"
        ;;
    3)
        echo ""
        echo "📋 可用账号列表："
        echo "=================================="
        tail -n +2 主播映射表.csv | awk -F',' '{if ($1) print "  • " $1 " (" $5 ")"}'
        echo "=================================="
        ;;
    4)
        echo "👋 再见！"
        exit 0
        ;;
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac
