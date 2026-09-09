"""
筱和灵眸(AethelEye) - PyInstaller运行时Hook

打包后的初始化：
  1. 设置 Playwright 浏览器路径
  2. 将工作目录切换到 exe 所在目录（确保相对路径可用）
"""
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # exe 所在目录（安装目录）
    exe_dir = Path(sys.executable).resolve().parent
    # _MEIPASS 是 PyInstaller 解压的临时目录
    meipass = Path(sys._MEIPASS)

    # 切换工作目录到安装目录
    os.chdir(str(exe_dir))

    # Playwright 浏览器：优先 _internal/ms-playwright，其次 exe_dir/ms-playwright
    for candidate in [meipass / 'ms-playwright', exe_dir / 'ms-playwright']:
        if candidate.exists():
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(candidate)
            break