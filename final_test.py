#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终验证测试 - 模拟真实订单通知
"""

import sys
import os
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from notification_sender import NotificationSender

def test_real_order_notification():
    """测试真实订单通知格式"""
    print("=== 真实订单通知测试 ===")
    
    try:
        # 创建通知发送器
        sender = NotificationSender("config.json")
        
        # 模拟真实订单数据
        order_data = {
            'anchor_name': '李佳琦',
            'product_name': '美妆套装',
            'quantity': 2,
            'amount': '588.00',
            'order_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        print("发送真实订单通知...")
        print(f"主播: {order_data['anchor_name']}")
        print(f"商品: {order_data['product_name']}")
        print(f"数量: {order_data['quantity']}")
        print(f"金额: ¥{order_data['amount']}")
        print(f"时间: {order_data['order_time']}")
        
        # 发送通知
        success = sender.send_order_notification(order_data)
        
        if success:
            print("✅ 真实订单通知发送成功！")
            return True
        else:
            print("❌ 真实订单通知发送失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def test_batch_notification():
    """测试批量订单通知"""
    print("\n=== 批量订单通知测试 ===")
    
    try:
        # 创建通知发送器
        sender = NotificationSender("config.json")
        
        # 模拟批量订单数据
        batch_data = {
            'anchor_name': '薇娅, 李佳琦, 辛巴',
            'product_name': '5个订单',
            'quantity': 5,
            'amount': '1299.50',
            'order_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        print("发送批量订单通知...")
        print(f"主播: {batch_data['anchor_name']}")
        print(f"订单: {batch_data['product_name']}")
        print(f"数量: {batch_data['quantity']}")
        print(f"总金额: ¥{batch_data['amount']}")
        print(f"时间: {batch_data['order_time']}")
        
        # 发送通知
        success = sender.send_order_notification(batch_data)
        
        if success:
            print("✅ 批量订单通知发送成功！")
            return True
        else:
            print("❌ 批量订单通知发送失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def test_special_characters():
    """测试特殊字符处理"""
    print("\n=== 特殊字符处理测试 ===")
    
    try:
        # 创建通知发送器
        sender = NotificationSender("config.json")
        
        # 包含特殊字符的订单数据
        special_data = {
            'anchor_name': '张三&李四',
            'product_name': '"限时特惠"商品',
            'quantity': 1,
            'amount': '99.99',
            'order_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        print("发送包含特殊字符的通知...")
        print(f"主播: {special_data['anchor_name']}")
        print(f"商品: {special_data['product_name']}")
        
        # 发送通知
        success = sender.send_order_notification(special_data)
        
        if success:
            print("✅ 特殊字符处理成功！")
            return True
        else:
            print("❌ 特殊字符处理失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("微信通知功能最终验证测试")
    print("=" * 50)
    
    # 检查配置
    if not os.path.exists('config.json'):
        print("❌ 配置文件不存在")
        return
    
    print("开始最终验证测试...")
    print("⚠️  请确保微信已登录且群聊存在")
    
    # 询问是否继续
    response = input("\n继续进行测试？(y/n): ").lower().strip()
    if response not in ['y', 'yes', '是']:
        print("测试已取消")
        return
    
    # 运行测试
    results = []
    
    # 测试1: 真实订单通知
    results.append(test_real_order_notification())
    
    # 等待用户确认
    input("\n按回车键继续下一个测试...")
    
    # 测试2: 批量订单通知
    results.append(test_batch_notification())
    
    # 等待用户确认
    input("\n按回车键继续下一个测试...")
    
    # 测试3: 特殊字符处理
    results.append(test_special_characters())
    
    # 总结结果
    print("\n" + "=" * 50)
    print("最终验证测试结果:")
    print(f"真实订单通知: {'✅ 成功' if results[0] else '❌ 失败'}")
    print(f"批量订单通知: {'✅ 成功' if results[1] else '❌ 失败'}")
    print(f"特殊字符处理: {'✅ 成功' if results[2] else '❌ 失败'}")
    
    success_count = sum(results)
    total_count = len(results)
    
    if success_count == total_count:
        print(f"\n🎉 所有测试通过！({success_count}/{total_count})")
        print("微信通知功能已完全就绪，可以投入生产使用。")
    else:
        print(f"\n⚠️  部分测试失败 ({success_count}/{total_count})")
        print("请检查失败的测试项目。")

if __name__ == "__main__":
    main()