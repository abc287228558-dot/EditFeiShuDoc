#!/usr/bin/env python3
"""
金牛网日期筛选功能模块
提供独立的日期筛选函数，可集成到主流程中
"""


def apply_niu_date_filter(page, timeout_ms: int = 60000, days: int = 7) -> bool:
    """
    在金牛网页面上应用日期筛选
    
    Args:
        page: Playwright page对象
        timeout_ms: 超时时间（毫秒）
        days: 筛选天数，默认7天
    
    Returns:
        bool: 筛选是否成功
    """
    try:
        print(f"[niu_filter] 开始应用日期筛选（最近{days}天）...")
        
        # 1. 查找并点击日期选择器
        date_picker = page.locator(".ant-picker").first
        if date_picker.count() == 0:
            print("[niu_filter] 未找到日期选择器")
            return False
        
        print("[niu_filter] 点击日期选择器...")
        date_picker.click()
        page.wait_for_timeout(1000)
        
        # 2. 查找并点击"最近N天"选项
        # 根据days参数构建匹配文本
        if days == 7:
            pattern = "text=/最近7天|近7天|7天/i"
        elif days == 30:
            pattern = "text=/最近30天|近30天|30天/i"
        else:
            pattern = f"text=/最近{days}天|近{days}天|{days}天/i"
        
        recent_option = page.locator(pattern).first
        if recent_option.count() == 0:
            print(f"[niu_filter] 未找到'最近{days}天'选项")
            # 尝试关闭弹窗
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False
        
        print(f"[niu_filter] 点击'最近{days}天'...")
        recent_option.click()
        page.wait_for_timeout(1000)
        
        # 3. 等待页面刷新
        print("[niu_filter] 等待页面刷新...")
        try:
            page.wait_for_load_state("networkidle", timeout=min(10000, timeout_ms))
        except Exception:
            pass
        page.wait_for_timeout(2000)
        
        print("[niu_filter] ✓ 日期筛选成功")
        return True
        
    except Exception as e:
        print(f"[niu_filter] ✗ 日期筛选失败: {e}")
        # 尝试关闭可能打开的弹窗
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
        return False


def test_date_filter():
    """测试日期筛选功能"""
    import os
    from playwright.sync_api import sync_playwright
    
    account_id = "99212581"
    user_data_dir = os.path.join(".state", "niu_profile")
    url = (
        "https://niu.e.kuaishou.com/reportV2/commonReport"
        "?slideReportSenceType=13&horizontalSenceType=131&__accountId__="
        + str(account_id)
    )
    
    print("[test] 测试金牛网日期筛选功能")
    
    os.makedirs(user_data_dir, exist_ok=True)
    
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False
        )
        
        try:
            page = ctx.new_page()
            
            # 打开页面
            print("[test] 打开金牛网...")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            
            # 应用日期筛选
            success = apply_niu_date_filter(page, timeout_ms=60000, days=7)
            
            if success:
                print("\n[test] ✓ 测试成功！")
            else:
                print("\n[test] ✗ 测试失败！")
            
            # 保持浏览器打开供观察
            print("\n浏览器将保持打开15秒供观察...")
            page.wait_for_timeout(15000)
            
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    test_date_filter()
