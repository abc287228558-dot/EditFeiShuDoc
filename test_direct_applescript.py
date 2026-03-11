#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接测试AppleScript微信发送
"""

import subprocess
import time

def test_wechat_search():
    """测试微信搜索功能"""
    print("=== 测试微信搜索功能 ===")
    print("请确保微信窗口可见，3秒后开始测试...")
    time.sleep(3)
    
    try:
        # 激活微信
        subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'], check=True)
        time.sleep(1)
        
        # 打开搜索
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                tell process "WeChat"
                    key code 3 using command down
                end tell
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 搜索快捷键发送成功")
            time.sleep(2)
            
            # 输入测试文本
            test_text = "测试"
            result2 = subprocess.run([
                'osascript', '-e', f'''
                tell application "System Events"
                    keystroke "{test_text}"
                end tell
                '''
            ], capture_output=True, text=True)
            
            if result2.returncode == 0:
                print("✅ 测试文本输入成功")
                time.sleep(1)
                
                # 清除输入
                subprocess.run([
                    'osascript', '-e', '''
                    tell application "System Events"
                        key code 51 using command down
                    end tell
                    '''
                ], capture_output=True, text=True)
                print("✅ 清除输入成功")
                
            else:
                print(f"❌ 文本输入失败: {result2.stderr}")
        else:
            print(f"❌ 搜索快捷键失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 测试异常: {e}")

def test_step_by_step_message(group_name="测试群", message="这是一条测试消息"):
    """分步测试消息发送"""
    print(f"\n=== 分步测试消息发送 ===")
    print(f"目标群聊: {group_name}")
    print(f"消息内容: {message}")
    print("请确保微信窗口可见，5秒后开始测试...")
    time.sleep(5)
    
    try:
        # 步骤1: 激活微信
        print("步骤1: 激活微信...")
        subprocess.run(['osascript', '-e', 'tell application "WeChat" to activate'], check=True)
        time.sleep(2)
        
        # 步骤2: 打开搜索
        print("步骤2: 打开搜索...")
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                tell process "WeChat"
                    key code 3 using command down
                end tell
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ 打开搜索失败: {result.stderr}")
            return False
        
        time.sleep(1)
        
        # 步骤3: 输入群名称
        print(f"步骤3: 输入群名称 '{group_name}'...")
        result = subprocess.run([
            'osascript', '-e', f'''
            tell application "System Events"
                keystroke "{group_name}"
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ 输入群名称失败: {result.stderr}")
            return False
        
        time.sleep(2)
        
        # 步骤4: 选择群聊
        print("步骤4: 选择群聊...")
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                key code 36
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ 选择群聊失败: {result.stderr}")
            return False
        
        time.sleep(2)
        
        # 步骤5: 输入消息
        print(f"步骤5: 输入消息 '{message}'...")
        result = subprocess.run([
            'osascript', '-e', f'''
            tell application "System Events"
                keystroke "{message}"
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ 输入消息失败: {result.stderr}")
            return False
        
        time.sleep(1)
        
        # 步骤6: 发送消息
        print("步骤6: 发送消息...")
        result = subprocess.run([
            'osascript', '-e', '''
            tell application "System Events"
                key code 36
            end tell
            '''
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ 发送消息失败: {result.stderr}")
            return False
        
        print("✅ 消息发送完成！")
        return True
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        return False

def main():
    """主测试函数"""
    print("直接AppleScript微信测试")
    print("="*50)
    
    # 基础搜索测试
    test_wechat_search()
    
    # 询问是否进行完整测试
    print("\n" + "="*50)
    response = input("是否进行完整的消息发送测试？(y/n): ").lower().strip()
    
    if response in ['y', 'yes', '是']:
        # 询问群聊名称
        group_name = input("请输入群聊名称 (直接回车使用'测试群'): ").strip()
        if not group_name:
            group_name = "测试群"
        
        # 进行完整测试
        success = test_step_by_step_message(group_name)
        
        if success:
            print("\n🎉 测试成功！微信消息发送功能正常。")
        else:
            print("\n❌ 测试失败，请检查群聊名称和微信状态。")
    else:
        print("跳过完整测试")

if __name__ == "__main__":
    main()