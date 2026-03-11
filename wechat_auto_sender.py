#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信群自动发送消息工具 - 基于PyAutoGUI和图像识别
适用于macOS PC微信客户端
"""

import pyautogui
import time
import cv2
import numpy as np
from PIL import Image
import os
import logging
from typing import Optional, Tuple

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeChatAutoSender:
    def __init__(self):
        # 设置PyAutoGUI安全模式
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.5
        
        # 模板图片路径
        self.template_dir = "wechat_templates"
        self.ensure_template_dir()
        
    def ensure_template_dir(self):
        """确保模板图片目录存在"""
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            logger.info(f"创建模板目录: {self.template_dir}")
    
    def find_image_on_screen(self, template_path: str, confidence: float = 0.8) -> Optional[Tuple[int, int]]:
        """
        在屏幕上查找模板图片
        
        Args:
            template_path: 模板图片路径
            confidence: 匹配置信度 (0-1)
            
        Returns:
            找到的位置坐标 (x, y) 或 None
        """
        try:
            if not os.path.exists(template_path):
                logger.warning(f"模板图片不存在: {template_path}")
                return None
                
            location = pyautogui.locateOnScreen(template_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                logger.info(f"找到图片 {template_path} 在位置: {center}")
                return center
            else:
                logger.debug(f"未找到图片: {template_path}")
                return None
        except Exception as e:
            logger.error(f"查找图片时出错: {e}")
            return None
    
    def activate_wechat(self) -> bool:
        """激活微信窗口"""
        try:
            # 尝试通过AppleScript激活微信
            os.system('osascript -e \'tell application "WeChat" to activate\'')
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"激活微信失败: {e}")
            return False
    
    def find_and_click_group(self, group_name: str) -> bool:
        """
        查找并点击指定群聊
        
        Args:
            group_name: 群聊名称
            
        Returns:
            是否成功找到并点击群聊
        """
        try:
            # 先激活微信
            if not self.activate_wechat():
                return False
            
            # 点击搜索框
            search_template = f"{self.template_dir}/search_box.png"
            search_pos = self.find_image_on_screen(search_template)
            
            if search_pos:
                pyautogui.click(search_pos)
                time.sleep(1)
            else:
                # 如果没有搜索框模板，使用快捷键
                pyautogui.hotkey('cmd', 'f')
                time.sleep(1)
            
            # 输入群名称
            pyautogui.typewrite(group_name)
            time.sleep(2)
            
            # 按回车选择第一个结果
            pyautogui.press('enter')
            time.sleep(2)
            
            logger.info(f"成功选择群聊: {group_name}")
            return True
            
        except Exception as e:
            logger.error(f"查找群聊失败: {e}")
            return False
    
    def send_message(self, message: str) -> bool:
        """
        发送消息到当前聊天窗口
        
        Args:
            message: 要发送的消息内容
            
        Returns:
            是否成功发送
        """
        try:
            # 查找消息输入框
            input_template = f"{self.template_dir}/message_input.png"
            input_pos = self.find_image_on_screen(input_template)
            
            if input_pos:
                pyautogui.click(input_pos)
            else:
                # 如果没有模板，点击屏幕下方区域（通常是输入框位置）
                screen_width, screen_height = pyautogui.size()
                pyautogui.click(screen_width // 2, screen_height - 100)
            
            time.sleep(1)
            
            # 输入消息
            pyautogui.typewrite(message)
            time.sleep(1)
            
            # 发送消息
            pyautogui.press('enter')
            time.sleep(1)
            
            logger.info(f"成功发送消息: {message[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False
    
    def send_to_group(self, group_name: str, message: str) -> bool:
        """
        向指定群聊发送消息
        
        Args:
            group_name: 群聊名称
            message: 消息内容
            
        Returns:
            是否成功发送
        """
        try:
            logger.info(f"开始向群聊 '{group_name}' 发送消息")
            
            # 查找并点击群聊
            if not self.find_and_click_group(group_name):
                logger.error("无法找到指定群聊")
                return False
            
            # 发送消息
            if not self.send_message(message):
                logger.error("发送消息失败")
                return False
            
            logger.info("消息发送成功")
            return True
            
        except Exception as e:
            logger.error(f"发送群消息失败: {e}")
            return False
    
    def capture_template(self, template_name: str, description: str = ""):
        """
        辅助方法：截取屏幕区域作为模板
        
        Args:
            template_name: 模板文件名
            description: 模板描述
        """
        print(f"请准备截取模板: {template_name}")
        if description:
            print(f"说明: {description}")
        print("按回车键开始截取，按ESC键取消...")
        
        key = input()
        if key.lower() == 'esc':
            return
        
        print("请在5秒内将鼠标移动到要截取的区域...")
        time.sleep(5)
        
        # 让用户选择区域
        print("请拖拽选择要截取的区域...")
        region = pyautogui.screenshot()
        
        # 这里可以添加更复杂的区域选择逻辑
        # 简化版本：直接保存整个屏幕截图
        template_path = f"{self.template_dir}/{template_name}.png"
        region.save(template_path)
        print(f"模板已保存: {template_path}")


def main():
    """主函数 - 示例用法"""
    sender = WeChatAutoSender()
    
    # 配置
    group_name = "测试群"  # 替换为实际群名
    message = """
🎉 新订单通知 🎉

订单信息：
- 主播：张三
- 商品：测试商品
- 数量：1
- 金额：¥99.00
- 时间：2024-03-10 15:30:00

请及时处理！
    """.strip()
    
    # 发送消息
    success = sender.send_to_group(group_name, message)
    
    if success:
        print("✅ 消息发送成功")
    else:
        print("❌ 消息发送失败")


if __name__ == "__main__":
    main()