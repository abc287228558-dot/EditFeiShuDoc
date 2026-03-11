# 微信自动化设置指南

## 1. 安装依赖

```bash
pip install -r requirements_wechat.txt
```

## 2. macOS权限设置

### 辅助功能权限
1. 打开 `系统偏好设置` > `安全性与隐私` > `隐私`
2. 选择 `辅助功能`
3. 点击锁图标解锁
4. 添加你的Python解释器或终端应用
5. 确保勾选启用

### 屏幕录制权限（PyAutoGUI方案需要）
1. 在同一个隐私设置页面
2. 选择 `屏幕录制`
3. 添加Python解释器或终端应用
4. 确保勾选启用

## 3. 微信设置

1. 确保微信PC版已安装并登录
2. 建议关闭微信的自动更新，避免界面变化
3. 设置微信窗口为固定大小和位置

## 4. 配置文件设置

在 `config.json` 中添加通知配置：

```json
{
  "notification": {
    "wechat": {
      "enabled": true,
      "method": "applescript",
      "groups": ["订单通知群", "运营群"],
      "template": {
        "new_order": "🎉 新订单通知 🎉\n\n订单信息：\n- 主播：{anchor_name}\n- 商品：{product_name}\n- 数量：{quantity}\n- 金额：¥{amount}\n- 时间：{order_time}\n\n请及时处理！"
      }
    }
  }
}
```

## 5. 使用方法

### 方法1: AppleScript方式（推荐）
```python
from notification_sender import NotificationSender

sender = NotificationSender()
order_data = {
    'anchor_name': '张三',
    'product_name': '测试商品',
    'quantity': 1,
    'amount': '99.00',
    'order_time': '2024-03-10 15:30:00'
}

sender.send_order_notification(order_data)
```

### 方法2: PyAutoGUI方式
需要先截取模板图片：
```python
from wechat_auto_sender import WeChatAutoSender

sender = WeChatAutoSender()
# 截取搜索框模板
sender.capture_template("search_box", "微信搜索框")
# 截取消息输入框模板
sender.capture_template("message_input", "消息输入框")
```

## 6. 集成到现有项目

在你的订单处理代码中添加：

```python
from notification_sender import NotificationSender

# 初始化通知发送器
notifier = NotificationSender()

# 在订单处理完成后发送通知
def process_order(order_info):
    # ... 现有的订单处理逻辑 ...
    
    # 发送微信通知
    notification_data = {
        'anchor_name': order_info.get('anchor_name', ''),
        'product_name': order_info.get('product_name', ''),
        'quantity': order_info.get('quantity', 1),
        'amount': order_info.get('amount', '0.00'),
        'order_time': order_info.get('order_time', '')
    }
    
    notifier.send_order_notification(notification_data)
```

## 7. 故障排除

### 常见问题
1. **权限不足**: 确保已授予辅助功能和屏幕录制权限
2. **微信未激活**: 确保微信窗口可见且未最小化
3. **群聊名称错误**: 检查群聊名称是否完全匹配
4. **网络问题**: 确保微信已正常登录

### 调试模式
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 测试功能
```python
from notification_sender import NotificationSender
sender = NotificationSender()
sender.test_notification()
```

## 8. 安全建议

1. 不要在生产环境中使用过高的自动化频率
2. 建议添加发送间隔限制，避免被微信限制
3. 定期检查微信客户端更新，及时调整脚本
4. 备份重要的模板图片和配置文件