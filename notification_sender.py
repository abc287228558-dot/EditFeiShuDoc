#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单通知发送模块
支持多种通知方式：微信群、邮件、钉钉等
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# 延迟导入，避免在不需要时导入PyAutoGUI
def _import_wechat_senders():
    """延迟导入微信发送器，避免依赖问题"""
    try:
        from wechat_applescript_sender import WeChatAppleScriptSender
        applescript_sender = WeChatAppleScriptSender
    except ImportError as e:
        logging.warning(f"无法导入AppleScript发送器: {e}")
        applescript_sender = None
    
    try:
        from wechat_auto_sender import WeChatAutoSender
        pyautogui_sender = WeChatAutoSender
    except ImportError as e:
        logging.warning(f"无法导入PyAutoGUI发送器: {e}")
        pyautogui_sender = None
    
    return applescript_sender, pyautogui_sender

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NotificationSender:
    def __init__(self, config_path: str = "config.json"):
        """
        初始化通知发送器
        
        Args:
            config_path: 配置文件路径
        """
        self.config = self.load_config(config_path)
        self.wechat_sender = None
        self.init_wechat_sender()
    
    def load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 确保通知配置存在
            if 'notification' not in config:
                config['notification'] = {
                    'wechat': {
                        'enabled': True,
                        'method': 'applescript',  # 'applescript' 或 'pyautogui'
                        'groups': ['测试群'],
                        'template': {
                            'new_order': """🎉 新订单通知 🎉

订单信息：
- 主播：{anchor_name}
- 商品：{product_name}
- 数量：{quantity}
- 金额：¥{amount}
- 时间：{order_time}

请及时处理！"""
                        }
                    }
                }
                # 保存更新后的配置
                self.save_config(config_path, config)
            
            return config
            
        except FileNotFoundError:
            logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
            return self.get_default_config()
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return self.get_default_config()
    
    def save_config(self, config_path: str, config: Dict):
        """保存配置文件"""
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            'notification': {
                'wechat': {
                    'enabled': True,
                    'method': 'applescript',
                    'groups': ['测试群'],
                    'template': {
                        'new_order': """🎉 新订单通知 🎉

订单信息：
- 主播：{anchor_name}
- 商品：{product_name}
- 数量：{quantity}
- 金额：¥{amount}
- 时间：{order_time}

请及时处理！"""
                    }
                }
            }
        }
    
    def init_wechat_sender(self):
        """初始化微信发送器"""
        wechat_config = self.config.get('notification', {}).get('wechat', {})
        
        if not wechat_config.get('enabled', False):
            logger.info("微信通知已禁用")
            return
        
        method = wechat_config.get('method', 'applescript')
        
        try:
            # 延迟导入发送器
            WeChatAppleScriptSender, WeChatAutoSender = _import_wechat_senders()
            
            if method == 'applescript':
                if WeChatAppleScriptSender is None:
                    logger.error("AppleScript发送器不可用")
                    return
                self.wechat_sender = WeChatAppleScriptSender()
                logger.info("使用AppleScript方式发送微信消息")
            elif method == 'pyautogui':
                if WeChatAutoSender is None:
                    logger.error("PyAutoGUI发送器不可用，请安装依赖: pip install pyautogui opencv-python Pillow numpy")
                    return
                self.wechat_sender = WeChatAutoSender()
                logger.info("使用PyAutoGUI方式发送微信消息")
            else:
                logger.error(f"不支持的微信发送方式: {method}")
                
        except Exception as e:
            logger.error(f"初始化微信发送器失败: {e}")
    
    def format_message(self, template_name: str, data: Dict) -> str:
        """
        格式化消息模板
        
        Args:
            template_name: 模板名称
            data: 数据字典
            
        Returns:
            格式化后的消息
        """
        try:
            template = self.config['notification']['wechat']['template'].get(template_name, '')
            
            if not template:
                logger.warning(f"未找到模板: {template_name}")
                return str(data)
            
            # 添加当前时间
            data['current_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            return template.format(**data)
            
        except Exception as e:
            logger.error(f"格式化消息失败: {e}")
            return str(data)
    
    def send_wechat_notification(self, message: str, groups: Optional[List[str]] = None) -> bool:
        """
        发送微信群通知
        
        Args:
            message: 消息内容
            groups: 群聊列表，如果为None则使用配置中的默认群聊
            
        Returns:
            是否发送成功
        """
        if not self.wechat_sender:
            logger.error("微信发送器未初始化")
            return False
        
        if groups is None:
            groups = self.config['notification']['wechat'].get('groups', [])
        
        if not groups:
            logger.warning("没有配置微信群聊")
            return False
        
        success_count = 0
        
        for group in groups:
            try:
                if hasattr(self.wechat_sender, 'send_to_group'):
                    # PyAutoGUI方式
                    success = self.wechat_sender.send_to_group(group, message)
                else:
                    # AppleScript方式
                    success = self.wechat_sender.send_message_via_keyboard(group, message)
                
                if success:
                    success_count += 1
                    logger.info(f"成功发送到群聊: {group}")
                else:
                    logger.error(f"发送到群聊失败: {group}")
                    
            except Exception as e:
                logger.error(f"发送到群聊 {group} 时出错: {e}")
        
        return success_count > 0
    
    def send_order_notification(self, order_data: Dict) -> bool:
        """
        发送订单通知
        
        Args:
            order_data: 订单数据
            
        Returns:
            是否发送成功
        """
        try:
            # 格式化消息
            message = self.format_message('new_order', order_data)
            
            # 发送微信通知
            success = self.send_wechat_notification(message)
            
            if success:
                logger.info("订单通知发送成功")
            else:
                logger.error("订单通知发送失败")
            
            return success
            
        except Exception as e:
            logger.error(f"发送订单通知时出错: {e}")
            return False
    
    def test_notification(self):
        """测试通知功能"""
        test_data = {
            'anchor_name': '测试主播',
            'product_name': '测试商品',
            'quantity': 1,
            'amount': '99.00',
            'order_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        logger.info("开始测试通知功能...")
        success = self.send_order_notification(test_data)
        
        if success:
            print("✅ 通知测试成功")
        else:
            print("❌ 通知测试失败")
        
        return success


def main():
    """主函数 - 测试用法"""
    # 创建通知发送器
    sender = NotificationSender()
    
    # 测试通知
    sender.test_notification()


if __name__ == "__main__":
    main()