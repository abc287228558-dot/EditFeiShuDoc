# 获取 Spreadsheet Token 方法

## 方法概述

当需要为新的飞书云文档配置 `spreadsheet_token` 时，使用以下方法。

## 方法：通过浏览器网络请求获取

### 步骤 1: 准备脚本

创建临时脚本 `get_token.py`：

```python
from playwright.sync_api import sync_playwright
import re
import time

wiki_url = input("请输入 Wiki URL: ").strip()

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir='.state/feishu_profile',
        headless=False,
    )
    
    page = ctx.new_page()
    
    requests_log = []
    
    def log_request(route, request):
        url = request.url
        if 'spreadsheet' in url.lower():
            requests_log.append(url)
        route.continue_()
    
    page.route('**/*', log_request)
    
    page.goto(wiki_url, timeout=30000)
    time.sleep(5)
    
    print('\n找到的 spreadsheet 相关请求:')
    token = None
    for url in requests_log:
        print(url)
        m = re.search(r'spreadsheet_token=([A-Za-z0-9_-]{15,})', url)
        if m:
            token = m.group(1)
            print(f'  → Token: {token}')
    
    if token:
        print(f'\n✅ Spreadsheet Token: {token}')
    else:
        print('\n❌ 未找到 token')
    
    ctx.close()
```

### 步骤 2: 运行脚本

```bash
./.venv/bin/python get_token.py
```

### 步骤 3: 输入 Wiki URL

当提示时，输入云文档的 Wiki URL，例如：
- 正式环境: `https://my.feishu.cn/wiki/PWMUwFVPni4WY9kRunEckmW9n0g`
- 测试环境: `https://vcn13vbsobtc.feishu.cn/wiki/WuLowQPlOigCT9kQ089chCfun2e`

### 步骤 4: 等待浏览器加载

脚本会自动打开浏览器并访问云文档，等待 5 秒后会自动抓取网络请求中的 `spreadsheet_token`。

### 步骤 5: 复制 Token

从输出中复制 `spreadsheet_token`，例如：
```
✅ Spreadsheet Token: SVAcsW16FhALZjtiFrzcPKY9nyb
```

## 快捷命令（一行完成）

```bash
./.venv/bin/python -c "
from playwright.sync_api import sync_playwright
import re, time

wiki_url = '你的Wiki URL'  # 替换为实际的 Wiki URL

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir='.state/feishu_profile',
        headless=False,
    )
    page = ctx.new_page()
    requests_log = []
    
    def log_request(route, request):
        url = request.url
        if 'spreadsheet' in url.lower():
            requests_log.append(url)
        route.continue_()
    
    page.route('**/*', log_request)
    page.goto(wiki_url, timeout=30000)
    time.sleep(5)
    
    for url in requests_log:
        m = re.search(r'spreadsheet_token=([A-Za-z0-9_-]{15,})', url)
        if m:
            print(f'✅ Token: {m.group(1)}')
            break
    
    ctx.close()
"
```

## 原理说明

1. **使用 Playwright** 打开浏览器并访问飞书云文档
2. **监听网络请求**，捕获所有包含 `spreadsheet` 的 API 请求
3. **从请求 URL 中提取** `spreadsheet_token` 参数
4. 飞书云文档在加载时会向后端发送请求，URL 中包含 `spreadsheet_token=XXX` 参数

## 示例输出

```
找到的 spreadsheet 相关请求:
https://vcn13vbsobtc.feishu.cn/space/api/v2/sheet/connectors?spreadsheet_token=SVAcsW16FhALZjtiFrzcPKY9nyb&page_size=50
  → Token: SVAcsW16FhALZjtiFrzcPKY9nyb

✅ Spreadsheet Token: SVAcsW16FhALZjtiFrzcPKY9nyb
```

## 更新配置文件

获取到 token 后，更新对应环境的配置文件：

### 正式环境
编辑 `config.prod.json`：
```json
{
  "target": {
    "spreadsheet_token": "你获取到的token"
  }
}
```

### 测试环境
编辑 `config.test.json`：
```json
{
  "target": {
    "spreadsheet_token": "你获取到的token"
  }
}
```

## 注意事项

1. **浏览器配置文件**：脚本使用 `.state/feishu_profile` 作为浏览器配置文件目录，确保已登录飞书账号
2. **网络请求时机**：token 在页面加载时通过网络请求发送，所以需要等待页面完全加载
3. **Token 格式**：通常是 15 位以上的字母数字组合，如 `SVAcsW16FhALZjtiFrzcPKY9nyb`
4. **权限要求**：确保使用的飞书应用（app_id）有权限访问该云文档

## 已知的 Token 记录

### 正式环境
- **Wiki URL**: https://my.feishu.cn/wiki/PWMUwFVPni4WY9kRunEckmW9n0g
- **Spreadsheet Token**: `Czmks65lvh3qO3tibFgcws40nif`
- **App ID**: `cli_a9200e9641fadbc0`

### 测试环境
- **Wiki URL**: https://vcn13vbsobtc.feishu.cn/wiki/WuLowQPlOigCT9kQ089chCfun2e
- **Spreadsheet Token**: `SVAcsW16FhALZjtiFrzcPKY9nyb`
- **App ID**: `cli_a92cd34869b9dbd6`
