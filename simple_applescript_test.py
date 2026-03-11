#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的AppleScript测试
"""

import subprocess
import time

def test_basic_applescript():
    """测试基本AppleScript功能"""
    print("=== 测试基本AppleScript ===")
    
    try:
        result = subprocess.run([
            'osascript', '-e', 'return "Hello World"'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ 基本AppleScript: {result.stdout.strip()}")
        else:
            print(f"❌ 基本AppleScript失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 基本AppleScript异常: {e}")

def test_system_events():
    """测试System Events"""
    print("\n=== 测试System Events ===")
    
    try:
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                return "System Events OK"
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ System Events: {result.stdout.strip()}")
        else:
            print(f"❌ System Events失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ System Events异常: {e}")

def test_wechat_process():
    """测试微信进程检查"""
    print("\n=== 测试微信进程检查 ===")
    
    try:
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                set processList to name of processes
                return processList contains "WeChat"
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            is_running = result.stdout.strip() == "true"
            print(f"✅ 微信进程检查: {'运行中' if is_running else '未运行'}")
        else:
            print(f"❌ 微信进程检查失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 微信进程检查异常: {e}")

def test_wechat_activation():
    """测试微信激活"""
    print("\n=== 测试微信激活 ===")
    
    try:
        result = subprocess.run([
            'osascript', '-e', 'tell application "WeChat" to activate'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 微信激活成功")
        else:
            print(f"❌ 微信激活失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 微信激活异常: {e}")

def test_keystroke_simple():
    """测试简单按键"""
    print("\n=== 测试简单按键 ===")
    print("⚠️  这个测试会发送一个回车键，请确保当前没有重要的输入框处于焦点状态")
    
    response = input("继续测试按键功能？(y/n): ").lower().strip()
    if response not in ['y', 'yes', '是']:
        print("跳过按键测试")
        return
    
    try:
        print("3秒后发送按键...")
        time.sleep(3)
        
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                key code 36
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 按键发送成功")
        else:
            print(f"❌ 按键发送失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 按键发送异常: {e}")

def test_keystroke_with_text():
    """测试文本输入"""
    print("\n=== 测试文本输入 ===")
    print("⚠️  这个测试会输入文本，请确保当前有合适的输入框处于焦点状态")
    
    response = input("继续测试文本输入？(y/n): ").lower().strip()
    if response not in ['y', 'yes', '是']:
        print("跳过文本输入测试")
        return
    
    try:
        print("3秒后输入测试文本...")
        time.sleep(3)
        
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                keystroke "Hello from AppleScript"
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 文本输入成功")
        else:
            print(f"❌ 文本输入失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 文本输入异常: {e}")

def test_wechat_focus():
    """测试微信窗口聚焦"""
    print("\n=== 测试微信窗口聚焦 ===")
    
    try:
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                end tell
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 微信窗口聚焦成功")
        else:
            print(f"❌ 微信窗口聚焦失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 微信窗口聚焦异常: {e}")

def main():
    """主测试函数"""
    print("AppleScript功能诊断测试")
    print("="*50)
    
    # 基础测试
    test_basic_applescript()
    test_system_events()
    test_wechat_process()
    test_wechat_activation()
    test_wechat_focus()
    
    # 按键测试
    test_keystroke_simple()
    test_keystroke_with_text()
    
    print("\n" + "="*50)
    print("诊断测试完成")

if __name__ == "__main__":
    main()