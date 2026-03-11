#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查和设置macOS权限
"""

import subprocess
import sys
import os

def check_accessibility_permission():
    """检查辅助功能权限"""
    print("=== 检查辅助功能权限 ===")
    
    try:
        # 尝试执行需要辅助功能权限的AppleScript
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                key code 36
            end tell
            '''
        ], capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            print("✅ 辅助功能权限已授予")
            return True
        else:
            print("❌ 辅助功能权限未授予")
            print(f"错误信息: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ 权限检查超时")
        return False
    except Exception as e:
        print(f"❌ 权限检查失败: {e}")
        return False

def get_python_path():
    """获取当前Python解释器路径"""
    return sys.executable

def get_terminal_path():
    """获取终端应用路径"""
    return "/Applications/Utilities/Terminal.app"

def open_accessibility_settings():
    """打开辅助功能设置"""
    print("\n=== 打开辅助功能设置 ===")
    try:
        subprocess.run([
            'osascript', '-e', '''
            tell application "System Preferences"
                activate
                set current pane to pane "com.apple.preference.security"
                delay 1
                tell application "System Events"
                    tell process "System Preferences"
                        click button "Privacy" of tab group 1 of window 1
                        delay 1
                        select row 1 of table 1 of scroll area 1 of group 1 of tab group 1 of window 1
                    end tell
                end tell
            end tell
            '''
        ], check=True)
        print("✅ 已打开辅助功能设置页面")
        return True
    except Exception as e:
        print(f"❌ 无法自动打开设置页面: {e}")
        print("请手动打开: 系统偏好设置 > 安全性与隐私 > 隐私 > 辅助功能")
        return False

def show_permission_instructions():
    """显示权限设置说明"""
    python_path = get_python_path()
    terminal_path = get_terminal_path()
    
    print("\n" + "="*60)
    print("📋 权限设置说明")
    print("="*60)
    print("\n1. 打开系统偏好设置")
    print("2. 选择 '安全性与隐私'")
    print("3. 点击 '隐私' 标签")
    print("4. 在左侧列表中选择 '辅助功能'")
    print("5. 点击左下角的锁图标解锁")
    print("6. 点击 '+' 按钮添加以下应用之一:")
    print(f"   • Python解释器: {python_path}")
    print(f"   • 终端应用: {terminal_path}")
    print("   • 或者你正在使用的IDE (如VSCode、PyCharm等)")
    print("7. 确保勾选启用")
    print("8. 重新运行测试")
    
    print(f"\n💡 推荐添加: {python_path}")
    print("\n⚠️  注意: 添加权限后可能需要重启终端或IDE")

def test_wechat_activation():
    """测试微信激活功能"""
    print("\n=== 测试微信激活 ===")
    
    try:
        # 检查微信是否运行
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                return (name of processes) contains "WeChat"
            end tell
            '''
        ], capture_output=True, text=True)
        
        is_running = result.stdout.strip() == "true"
        print(f"微信运行状态: {'✅ 运行中' if is_running else '❌ 未运行'}")
        
        if not is_running:
            print("尝试启动微信...")
            subprocess.run([
                'osascript', '-e', 'tell application "WeChat" to activate'
            ], check=True)
            print("✅ 微信启动命令已发送")
        else:
            print("尝试激活微信窗口...")
            subprocess.run([
                'osascript', '-e', 'tell application "WeChat" to activate'
            ], check=True)
            print("✅ 微信激活命令已发送")
        
        return True
        
    except Exception as e:
        print(f"❌ 微信操作失败: {e}")
        return False

def main():
    """主函数"""
    print("macOS权限检查和设置工具")
    print("="*50)
    
    # 检查权限
    has_permission = check_accessibility_permission()
    
    if not has_permission:
        print("\n需要设置辅助功能权限才能使用微信自动化功能")
        
        # 询问是否打开设置
        response = input("\n是否自动打开辅助功能设置页面？(y/n): ").lower().strip()
        if response in ['y', 'yes', '是']:
            open_accessibility_settings()
        
        # 显示详细说明
        show_permission_instructions()
        
        print("\n" + "="*50)
        print("⚠️  请完成权限设置后重新运行测试")
        return
    
    # 权限正常，测试微信功能
    print("\n权限检查通过，测试微信功能...")
    test_wechat_activation()
    
    print("\n" + "="*50)
    print("✅ 权限检查完成，可以运行微信通知测试")
    print("运行命令: python3 test_wechat_notification.py")

if __name__ == "__main__":
    main()