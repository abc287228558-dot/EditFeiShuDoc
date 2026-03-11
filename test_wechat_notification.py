#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试微信通知功能
"""

import sys
import os
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from notification_sender import NotificationSender

def test_basic_notification():
    """测试基本通知功能"""
    print("=== 测试基本微信通知功能 ===")
    
    try:
        # 创建通知发送器
        sender = NotificationSender("config.json")
        
        # 测试数据
        test_data = {
            'anchor_name': '测试主播',
            'product_name': '3个订单',
            'quantity': 3,
            'amount': '299.00',
            'order_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        print(f"发送测试通知...")
        print(f"主播: {test_data['anchor_name']}")
        print(f"订单: {test_data['product_name']}")
        print(f"金额: ¥{test_data['amount']}")
        
        # 发送通知
        success = sender.send_order_notification(test_data)
        
        if success:
            print("✅ 通知发送成功！")
            return True
        else:
            print("❌ 通知发送失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def test_applescript_sender():
    """直接测试AppleScript发送器"""
    print("\n=== 测试AppleScript发送器 ===")
    
    try:
        from wechat_applescript_sender import WeChatAppleScriptSender
        
        sender = WeChatAppleScriptSender()
        
        # 检查微信是否运行
        if not sender.check_wechat_running():
            print("启动微信...")
            if not sender.launch_wechat():
                print("❌ 无法启动微信")
                return False
        else:
            print("✅ 微信已在运行")
        
        # 测试消息
        test_message = """🎉 测试通知 🎉

这是一条测试消息，用于验证微信自动化功能是否正常工作。

测试时间：""" + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print("发送测试消息...")
        print("请确保:")
        print("1. 微信已登录")
        print("2. 配置文件中的群聊名称正确")
        print("3. 已授予系统辅助功能权限")
        
        # 从配置中读取群聊名称
        import json
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            groups = config.get('notification', {}).get('wechat', {}).get('groups', ['测试群'])
            group_name = groups[0] if groups else '测试群'
        except:
            group_name = '测试群'
        
        print(f"目标群聊: {group_name}")
        
        success = sender.send_message_via_keyboard(group_name, test_message)
        
        if success:
            print("✅ AppleScript发送成功！")
            return True
        else:
            print("❌ AppleScript发送失败")
            return False
            
    except Exception as e:
        print(f"❌ AppleScript测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("微信通知功能测试")
    print("=" * 50)
    
    # 检查配置文件
    if not os.path.exists('config.json'):
        print("❌ 配置文件 config.json 不存在")
        return
    
    # 检查微信通知配置
    try:
        import json
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        notification_config = config.get('notification', {}).get('wechat', {})
        
        if not notification_config.get('enabled', False):
            print("❌ 微信通知功能未启用")
            print("请在 config.json 中设置 notification.wechat.enabled = true")
            return
        
        groups = notification_config.get('groups', [])
        if not groups:
            print("❌ 未配置微信群聊")
            print("请在 config.json 中设置 notification.wechat.groups")
            return
        
        print(f"✅ 配置检查通过")
        print(f"发送方式: {notification_config.get('method', 'applescript')}")
        print(f"目标群聊: {', '.join(groups)}")
        
    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        return
    
    # 运行测试
    print("\n开始测试...")
    
    # 测试1: AppleScript发送器
    test1_success = test_applescript_sender()
    
    # 测试2: 集成通知功能
    test2_success = test_basic_notification()
    
    # 总结
    print("\n" + "=" * 50)
    print("测试结果:")
    print(f"AppleScript发送器: {'✅ 成功' if test1_success else '❌ 失败'}")
    print(f"集成通知功能: {'✅ 成功' if test2_success else '❌ 失败'}")
    
    if test1_success and test2_success:
        print("\n🎉 所有测试通过！微信通知功能已就绪。")
    else:
        print("\n⚠️  部分测试失败，请检查配置和权限设置。")
        print("\n故障排除建议:")
        print("1. 确保微信PC版已安装并登录")
        print("2. 检查系统偏好设置 > 安全性与隐私 > 辅助功能权限")
        print("3. 确认群聊名称在配置文件中正确设置")
        print("4. 检查微信是否处于前台或可见状态")

if __name__ == "__main__":
    main()