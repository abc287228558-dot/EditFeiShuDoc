import os
import shutil
from pathlib import Path

def clean_browser_caches():
    """清理浏览器缓存但保留登录状态"""
    
    # 要清理的目录列表
    profile_dirs = [
        '.state/kuaishou_profiles',
        '.state/niu_chrome_profile', 
        '.state/feishu_profile',
        '.state/niu_profile',
        '.state/kuaishou_chromium'
    ]
    
    # 需要删除的缓存目录
    cache_paths = [
        'Default/Cache',
        'Default/Code Cache', 
        'Default/GPUCache',
        'Default/DawnWebGPUCache',
        'Default/DawnGraphiteCache',
        'GrShaderCache',
        'ShaderCache',
        'GraphiteDawnCache',
        'Cache',
        'Code Cache',
        'GPUCache'
    ]
    
    total_freed = 0
    
    for profile_dir in profile_dirs:
        profile_path = Path(profile_dir)
        if not profile_path.exists():
            continue
            
        print(f"\n处理 {profile_dir}...")
        
        # 如果是包含多个账号的目录
        if profile_path.is_dir():
            for item in profile_path.iterdir():
                if item.is_dir():
                    for cache_rel_path in cache_paths:
                        cache_full_path = item / cache_rel_path
                        if cache_full_path.exists():
                            try:
                                size = sum(f.stat().st_size for f in cache_full_path.rglob('*') if f.is_file())
                                shutil.rmtree(cache_full_path, ignore_errors=True)
                                total_freed += size
                                print(f"  清理 {item.name}/{cache_rel_path}: {size/1024/1024:.1f}MB")
                            except Exception as e:
                                print(f"  跳过 {cache_full_path}: {e}")
    
    print(f"\n{'='*50}")
    print(f"总共释放: {total_freed/1024/1024/1024:.2f}GB")
    print(f"{'='*50}")

if __name__ == '__main__':
    clean_browser_caches()
