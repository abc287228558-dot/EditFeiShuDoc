#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信通知功能安装和配置脚本
"""

import os
import sys
import json
import subprocess
from pathlib import Path

def check_python_version():
    """检查Python版本"""
    if sys.version_info < (3, 7):
        print("❌ 需要Python 3.7或更高版本")
        return False
    print(f"✅ Python版本: {sys.version}")
    return True

def install_dependencies():
    """安装依赖包"""
    print("\n=== 安装依赖包 ===")
    
    # 检查是否存在requirements文件
    if not os.path.exists('requirements_wechat.txt'):
        print("❌ requirements_wechat.txt 文件不存在")
        return False
    
    try:
        # 安装依赖
        print("安装微信自动化依赖...")
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-r', 'requirements_wechat.txt'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 依赖安装成功")
            return True
        else:
            print(f"❌ 依赖安装失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 安装依赖时出错: {e}")
        return False

def check_wechat_config():
    """检查微信配置"""
    print("\n=== 检查微信配置 ===")
    
    if not os.path.exists('config.json'):
        print("❌ config.json 文件不存在")
        return False
    
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查通知配置
        notification = config.get('notification', {})
        wechat = notification.get('wechat', {})
        
        if not wechat:
            print("❌ 未找到微信通知配置")
            return False
        
        enabled = wechat.get('enabled', False)
        method = wechat.get('method', 'applescript')
        groups = wechat.get('groups', [])
        
        print(f"启用状态: {'✅ 已启用' if enabled else '❌ 未启用'}")
        print(f"发送方式: {method}")
        print(f"目标群聊: {groups if groups else '❌ 未配置'}")
        
        if not enabled:
            print("⚠️  微信通知功能未启用")
            return False
        
        if not groups:
            print("⚠️  未配置目标群聊")
            return False
        
        print("✅ 微信配置检查通过")
        return True
        
    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        return False

def check_macos_permissions():
    """检查macOS权限设置"""
    print("\n=== 检查macOS权限 ===")
    
    print("请确保已授予以下权限:")
    print("1. 系统偏好设置 > 安全性与隐私 > 隐私 > 辅助功能")
    print("   - 添加Python解释器或终端应用")
    print("   - 确保勾选启用")
    print("")
    print("2. 如果使用PyAutoGUI方案，还需要:")
    print("   - 系统偏好设置 > 安全性与隐私 > 隐私 > 屏幕录制")
    print("   - 添加Python解释器或终端应用")
    print("")
    
    response = input("是否已完成权限设置？(y/n): ").lower().strip()
    return response in ['y', 'yes', '是']

def check_wechat_app():
    """检查微信应用"""
    print("\n=== 检查微信应用 ===")
    
    # 检查微信是否安装
    wechat_path = "/Applications/WeChat.app"
    if not os.path.exists(wechat_path):
        print("❌ 未找到微信应用")
        print("请从App Store或官网下载安装微信PC版")
        return False
    
    print("✅ 微信应用已安装")
    
    # 检查微信是否运行
    try:
        result = subprocess.run([
            'osascript', '-e', 
            'tell application "System Events" to return (name of processes) contains "WeChat"'
        ], capture_output=True, text=True)
        
        is_running = result.stdout.strip() == "true"
        print(f"微信运行状态: {'✅ 运行中' if is_running else '⚠️  未运行'}")
        
        if not is_running:
            print("建议启动微信并登录后再进行测试")
        
        return True
        
    except Exception as e:
        print(f"⚠️  无法检查微信运行状态: {e}")
        return True

def setup_config_interactive():
    """交互式配置设置"""
    print("\n=== 配置微信通知 ===")
    
    if not os.path.exists('config.json'):
        print("❌ config.json 文件不存在，无法进行配置")
        return False
    
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 确保通知配置存在
        if 'notification' not in config:
            config['notification'] = {}
        
        if 'wechat' not in config['notification']:
            config['notification']['wechat'] = {}
        
        wechat_config = config['notification']['wechat']
        
        # 询问是否启用
        current_enabled = wechat_config.get('enabled', False)
        print(f"当前启用状态: {current_enabled}")
        enable = input("是否启用微信通知？(y/n): ").lower().strip()
        wechat_config['enabled'] = enable in ['y', 'yes', '是']
        
        if not wechat_config['enabled']:
            print("微信通知已禁用")
        else:
            # 选择发送方式
            current_method = wechat_config.get('method', 'applescript')
            print(f"当前发送方式: {current_method}")
            print("可选方式: applescript (推荐), pyautogui")
            method = input("选择发送方式 (直接回车使用applescript): ").strip()
            if not method:
                method = 'applescript'
            wechat_config['method'] = method
            
            # 配置群聊
            current_groups = wechat_config.get('groups', [])
            print(f"当前群聊: {current_groups}")
            groups_input = input("输入群聊名称 (多个用逗号分隔): ").strip()
            if groups_input:
                groups = [g.strip() for g in groups_input.split(',') if g.strip()]
                wechat_config['groups'] = groups
        
        # 保存配置
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print("✅ 配置已保存")
        return True
        
    except Exception as e:
        print(f"❌ 配置保存失败: {e}")
        return False

def run_test():
    """运行测试"""
    print("\n=== 运行测试 ===")
    
    if not os.path.exists('test_wechat_notification.py'):
        print("❌ 测试脚本不存在")
        return False
    
    try:
        print("启动微信通知测试...")
        result = subprocess.run([sys.executable, 'test_wechat_notification.py'], 
                              capture_output=False, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ 测试运行失败: {e}")
        return False

def main():
    """主安装流程"""
    print("微信通知功能安装向导")
    print("=" * 50)
    
    # 检查Python版本
    if not check_python_version():
        return
    
    # 安装依赖
    if not install_dependencies():
        print("⚠️  依赖安装失败，但可以继续配置")
    
    # 检查微信应用
    if not check_wechat_app():
        print("⚠️  微信应用检查失败，但可以继续配置")
    
    # 检查权限
    if not check_macos_permissions():
        print("⚠️  请先完成权限设置再继续")
        return
    
    # 检查配置
    config_ok = check_wechat_config()
    
    if not config_ok:
        print("\n需要配置微信通知设置")
        if not setup_config_interactive():
            return
    
    # 询问是否运行测试
    print("\n" + "=" * 50)
    test = input("是否运行测试？(y/n): ").lower().strip()
    
    if test in ['y', 'yes', '是']:
        run_test()
    
    print("\n🎉 安装配置完成！")
    print("\n使用说明:")
    print("1. 确保微信PC版已登录")
    print("2. 运行 python test_wechat_notification.py 测试功能")
    print("3. 在订单处理完成后会自动发送微信通知")

if __name__ == "__main__":
    main()