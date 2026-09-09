"""
筱和灵眸(AethelEye) - 启动脚本

用于开发和打包后的启动
"""
import sys
from pathlib import Path

# 添加项目路径
if __name__ == "__main__":
    # 开发模式：直接运行
    from app.main import main
    main()