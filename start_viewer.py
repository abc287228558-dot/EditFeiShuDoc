#!/usr/bin/env python3
"""
启动主播映射表查看器

在本地启动一个简单的HTTP服务器，用于查看主播映射表并快速打开快手课堂
"""
import argparse
import http.server
import os
import socketserver
import sys
import webbrowser
from threading import Timer


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器，添加CORS支持"""
    
    def end_headers(self):
        # 添加CORS头，允许跨域访问
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def log_message(self, format, *args):
        # 简化日志输出
        if args[1] == '200':
            print(f"✓ {args[0]}")
        else:
            super().log_message(format, *args)


def open_browser(url: str, delay: float = 1.5):
    """延迟打开浏览器"""
    def _open():
        print(f"\n🌐 正在打开浏览器: {url}")
        webbrowser.open(url)
    
    Timer(delay, _open).start()


def start_server(port: int = 8000, auto_open: bool = True):
    """
    启动HTTP服务器
    
    Args:
        port: 端口号
        auto_open: 是否自动打开浏览器
    """
    # 检查必要文件
    if not os.path.exists("主播映射表.csv"):
        print("❌ 错误: 找不到'主播映射表.csv'文件", file=sys.stderr)
        print("请确保在包含主播映射表的目录中运行此脚本", file=sys.stderr)
        sys.exit(1)
    
    if not os.path.exists("anchor_map_viewer.html"):
        print("❌ 错误: 找不到'anchor_map_viewer.html'文件", file=sys.stderr)
        sys.exit(1)
    
    # 创建服务器
    handler = CustomHTTPRequestHandler
    
    try:
        with socketserver.TCPServer(("", port), handler) as httpd:
            url = f"http://localhost:{port}/anchor_map_viewer.html"
            
            print("=" * 60)
            print("📱 主播映射表查看器")
            print("=" * 60)
            print(f"🚀 服务器已启动: http://localhost:{port}")
            print(f"📄 访问地址: {url}")
            print("=" * 60)
            print("按 Ctrl+C 停止服务器")
            print("=" * 60)
            
            # 自动打开浏览器
            if auto_open:
                open_browser(url)
            
            # 启动服务器
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n\n⚠️  服务器已停止")
        sys.exit(0)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ 错误: 端口 {port} 已被占用", file=sys.stderr)
            print(f"请尝试使用其他端口: python3 start_viewer.py --port 8001", file=sys.stderr)
        else:
            print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="启动主播映射表查看器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认端口8000启动
  python3 start_viewer.py
  
  # 使用自定义端口
  python3 start_viewer.py --port 8080
  
  # 不自动打开浏览器
  python3 start_viewer.py --no-open
        """
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP服务器端口（默认: 8000）",
    )
    
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="不自动打开浏览器",
    )
    
    args = parser.parse_args()
    
    try:
        start_server(port=args.port, auto_open=not args.no_open)
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
