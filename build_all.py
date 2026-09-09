"""
筱和灵眸(AethelEye) - 自动打包脚本 v2.0

执行完整打包流程：
1. 前端构建 (npm run build)
2. 安装Python依赖
3. 安装Playwright Chromium
4. 后端打包 (PyInstaller)
5. 生成安装包 (Inno Setup)

使用方法：
    cd AethelEye/
    python build_all.py
"""
import subprocess
import sys
import os
import time
from pathlib import Path
import shutil

# 项目路径（build_all.py 在仓库根目录）
SCRIPT_DIR = Path(__file__).parent
CODE_DIR = SCRIPT_DIR
FRONTEND_DIR = CODE_DIR / "frontend"
BACKEND_DIR = CODE_DIR / "backend"
INSTALLER_DIR = CODE_DIR / "installer"

# 输出目录（在项目代码下创建 release/ 文件夹）
OUTPUT_DIR = CODE_DIR / "release"
INSTALLER_OUTPUT = INSTALLER_DIR / "output"

def run_command(cmd: str, cwd: Path = None, check: bool = True) -> subprocess.CompletedProcess:
    """执行命令"""
    print(f"\n执行: {cmd}")
    print(f"目录: {cwd or Path.cwd()}")

    result = subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if check and result.returncode != 0:
        print(f"命令执行失败: {cmd}")
        sys.exit(1)

    return result


def step1_build_frontend():
    """步骤1: 构建前端"""
    print("\n" + "="*50)
    print("步骤1: 构建前端 (Vue + Vite)")
    print("="*50)

    # 检查node_modules是否存在
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        print("安装前端依赖...")
        run_command("npm install", cwd=FRONTEND_DIR)

    # 构建前端
    print("构建前端...")
    run_command("npm run build", cwd=FRONTEND_DIR)

    # 验证构建产物
    dist_dir = CODE_DIR / "dist"
    if not dist_dir.exists():
        print("错误: 前端构建产物不存在")
        sys.exit(1)

    print(f"前端构建完成: {dist_dir}")


def step2_install_backend_deps():
    """步骤2: 安装后端Python依赖"""
    print("\n" + "="*50)
    print("步骤2: 安装后端Python依赖")
    print("="*50)

    requirements = BACKEND_DIR / "requirements.txt"
    if requirements.exists():
        print("安装Python依赖...")
        run_command("pip install -r requirements.txt", cwd=BACKEND_DIR)

    print("Python依赖安装完成")


def step3_install_chromium():
    """步骤3: 安装Playwright Chromium"""
    print("\n" + "="*50)
    print("步骤3: 安装Playwright Chromium浏览器")
    print("="*50)

    # 使用用户默认路径（PyInstaller build.spec 会自动发现）
    default_path = Path.home() / 'AppData' / 'Local' / 'ms-playwright'
    if default_path.exists():
        print(f"Chromium 已存在: {default_path}")
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(default_path)
        return

    print("下载Chromium...")
    run_command("playwright install chromium", cwd=BACKEND_DIR)
    print("Chromium安装完成")


def step4_build_backend():
    """步骤4: PyInstaller打包后端"""
    print("\n" + "="*50)
    print("步骤4: PyInstaller打包后端")
    print("="*50)

    # 清理旧产物
    old_dist = BACKEND_DIR / "dist"
    old_build = BACKEND_DIR / "build"
    if old_dist.exists():
        shutil.rmtree(old_dist)
    if old_build.exists():
        shutil.rmtree(old_build)

    # 执行PyInstaller
    build_spec = BACKEND_DIR / "build.spec"
    print(f"打包配置: {build_spec}")
    run_command("pyinstaller build.spec --noconfirm", cwd=BACKEND_DIR)

    # 验证打包产物
    exe_dir = BACKEND_DIR / "dist" / "AethelEye"
    exe_file = exe_dir / "AethelEye.exe"

    if not exe_file.exists():
        print("错误: exe文件不存在")
        sys.exit(1)

    print(f"后端打包完成: {exe_file}")
    print(f"打包目录大小: {get_dir_size(exe_dir):.1f} MB")


def step5_build_installer():
    """步骤5: 生成Inno Setup安装包"""
    print("\n" + "="*50)
    print("步骤5: 生成安装包")
    print("="*50)

    # 检查Inno Setup是否安装
    iscc_paths = [
        Path(os.environ.get('ProgramFiles', 'C:\\Program Files')) / 'Inno Setup 6' / 'ISCC.exe',
        Path(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')) / 'Inno Setup 6' / 'ISCC.exe',
    ]

    iscc = None
    for p in iscc_paths:
        if p.exists():
            iscc = p
            break

    if not iscc:
        print("警告: Inno Setup未安装，跳过安装包生成")
        print("请手动安装Inno Setup 6并编译 setup.iss")
        print(f"安装包脚本位置: {INSTALLER_DIR / 'setup.iss'}")
        return False

    # 创建输出目录
    INSTALLER_OUTPUT.mkdir(parents=True, exist_ok=True)

    # 编译Inno Setup脚本
    setup_iss = INSTALLER_DIR / "setup.iss"
    print(f"编译安装脚本: {setup_iss}")
    run_command(f'"{iscc}" "{setup_iss}"', cwd=INSTALLER_DIR)

    # 验证安装包
    installer = INSTALLER_OUTPUT / "AethelEye_Setup_v2.0.0.exe"
    if installer.exists():
        print(f"\n安装包生成完成: {installer}")
        print(f"安装包大小: {installer.stat().st_size / 1024 / 1024:.1f} MB")
        return installer
    else:
        print("警告: 安装包生成可能失败")
        return False


def step6_copy_to_release(installer_path=None):
    """步骤6: 复制产物到 release/ 目录"""
    print("\n" + "="*50)
    print("步骤6: 整理发布目录")
    print("="*50)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 复制安装包
    if installer_path and Path(installer_path).exists():
        dest = OUTPUT_DIR / Path(installer_path).name
        shutil.copy2(installer_path, dest)
        print(f"安装包: {dest}")

    # 复制便携版（PyInstaller onedir）
    exe_src = BACKEND_DIR / "dist" / "AethelEye"
    if exe_src.exists():
        portable_dir = OUTPUT_DIR / "AethelEye_Portable_v2.0.0"
        if portable_dir.exists():
            shutil.rmtree(portable_dir)
        shutil.copytree(exe_src, portable_dir)
        # 复制前端dist到便携版
        dist_src = CODE_DIR / "dist"
        if dist_src.exists():
            shutil.copytree(dist_src, portable_dir / "dist", dirs_exist_ok=True)
        print(f"便携版: {portable_dir}")

    print(f"\n发布目录: {OUTPUT_DIR}")


def get_dir_size(path: Path) -> float:
    """计算目录大小（MB）"""
    total = 0
    for p in path.rglob('*'):
        if p.is_file():
            total += p.stat().st_size
    return total / 1024 / 1024


def main():
    """执行完整打包流程"""
    start_time = time.time()

    print("\n" + "="*60)
    print("  筱和灵眸(AethelEye) 自动打包脚本 v2.0")
    print("="*60)
    print(f"代码目录: {CODE_DIR}")

    try:
        step1_build_frontend()
        step2_install_backend_deps()
        step3_install_chromium()
        step4_build_backend()
        installer_path = step5_build_installer()
        step6_copy_to_release(installer_path)

        elapsed = time.time() - start_time
        print("\n" + "="*60)
        print(f"  打包完成！耗时 {elapsed:.0f} 秒")
        print("="*60)

        print(f"\n产物位置: {OUTPUT_DIR}")
        print(f"  便携版: release/AethelEye_Portable_v2.0.0/")
        if installer_path:
            print(f"  安装包: release/{Path(str(installer_path)).name}")
        print(f"\n打包完成。分发前请复核许可证、第三方组件和数据清洁结果。")

    except Exception as e:
        print(f"\n打包失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
