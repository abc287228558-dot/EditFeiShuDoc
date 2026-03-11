#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信群自动发送消息工具 - 基于AppleScript
适用于macOS PC微信客户端
"""

import subprocess
import time
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeChatAppleScriptSender:
    def __init__(self):
        self.wechat_app = "WeChat"
    
    def run_applescript(self, script: str) -> Optional[str]:
        """
        执行AppleScript脚本
        
        Args:
            script: AppleScript代码
            
        Returns:
            脚本执行结果或None
        """
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.error(f"AppleScript执行失败: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("AppleScript执行超时")
            return None
        except Exception as e:
            logger.error(f"执行AppleScript时出错: {e}")
            return None
    
    def activate_wechat(self) -> bool:
        """激活微信应用"""
        script = f'tell application "{self.wechat_app}" to activate'
        result = self.run_applescript(script)
        return result is not None
    
    def send_message_via_keyboard(self, group_name: str, message: str) -> bool:
        """
        通过键盘操作发送消息
        
        Args:
            group_name: 群聊名称
            message: 消息内容
            
        Returns:
            是否成功发送
        """
        try:
            # 激活微信
            if not self.activate_wechat():
                logger.error("无法激活微信")
                return False
            
            time.sleep(2)
            
            # 步骤1: 打开搜索 (Cmd+F)
            script1 = '''
            tell application "System Events"
                tell process "WeChat"
                    key code 3 using command down
                end tell
            end tell
            '''
            
            result1 = self.run_applescript(script1)
            if result1 is None:
                logger.error("打开搜索失败")
                return False
            
            time.sleep(1)
            
            # 步骤2: 输入群名称
            script2 = f'''
            tell application "System Events"
                keystroke "{group_name}"
            end tell
            '''
            
            result2 = self.run_applescript(script2)
            if result2 is None:
                logger.error("输入群名称失败")
                return False
            
            time.sleep(2)
            
            # 步骤3: 按回车选择群聊
            script3 = '''
            tell application "System Events"
                key code 36
            end tell
            '''
            
            result3 = self.run_applescript(script3)
            if result3 is None:
                logger.error("选择群聊失败")
                return False
            
            time.sleep(2)
            
            # 步骤4: 输入消息内容
            # 处理消息中的特殊字符
            safe_message = message.replace('"', '\\"').replace('\n', '\\n')
            script4 = f'''
            tell application "System Events"
                keystroke "{safe_message}"
            end tell
            '''
            
            result4 = self.run_applescript(script4)
            if result4 is None:
                logger.error("输入消息失败")
                return False
            
            time.sleep(1)
            
            # 步骤5: 发送消息 (回车)
            script5 = '''
            tell application "System Events"
                key code 36
            end tell
            '''
            
            result5 = self.run_applescript(script5)
            if result5 is None:
                logger.error("发送消息失败")
                return False
            
            logger.info(f"成功发送消息到群聊: {group_name}")
            return True
            
        except Exception as e:
            logger.error(f"发送消息时出错: {e}")
            return False
    
    def check_wechat_running(self) -> bool:
        """检查微信是否正在运行"""
        script = f'''
        tell application "System Events"
            return (name of processes) contains "{self.wechat_app}"
        end tell
        '''
        
        result = self.run_applescript(script)
        return result == "true"
    
    def launch_wechat(self) -> bool:
        """启动微信应用"""
        if self.check_wechat_running():
            logger.info("微信已在运行")
            return True
        
        script = f'tell application "{self.wechat_app}" to launch'
        result = self.run_applescript(script)
        
        if result is not None:
            logger.info("微信启动成功")
            time.sleep(5)  # 等待微信完全启动
            return True
        else:
            logger.error("微信启动失败")
            return False


def main():
    """主函数 - 示例用法"""
    sender = WeChatAppleScriptSender()
    
    # 检查并启动微信
    if not sender.launch_wechat():
        print("❌ 无法启动微信")
        return
    
    # 配置
    group_name = "测试群"  # 替换为实际群名
    message = """🎉 新订单通知 🎉

订单信息：
- 主播：张三
- 商品：测试商品
- 数量：1
- 金额：¥99.00
- 时间：2024-03-10 15:30:00

请及时处理！"""
    
    # 发送消息
    success = sender.send_message_via_keyboard(group_name, message)
    
    if success:
        print("✅ 消息发送成功")
    else:
        print("❌ 消息发送失败")


if __name__ == "__main__":
    main()