"""
筱和灵眸(AethelEye) - PyInstaller打包配置 v2.0

打包后端为exe（onedir模式），包含所有依赖和Chromium浏览器。
前端dist和data目录在安装包阶段由 Inno Setup 负责放置。

使用:
    cd backend
    pyinstaller build.spec --noconfirm
"""
# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

# ── 路径定义 ──────────────────────────────────────────────
# SPECPATH = backend/
code_dir = Path(SPECPATH).parent  # 仓库根目录
backend_dir = Path(SPECPATH)      # backend/

# Playwright Chromium 浏览器路径
playwright_browsers_path = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
if not playwright_browsers_path:
    for p in [
        Path.home() / 'AppData' / 'Local' / 'ms-playwright',
        Path.home() / '.cache' / 'ms-playwright',
    ]:
        if p.exists():
            playwright_browsers_path = str(p)
            break

# 收集 Chromium
chromium_datas = []
if playwright_browsers_path and Path(playwright_browsers_path).exists():
    chromium_datas.append((playwright_browsers_path, 'ms-playwright'))

# 前端 dist（如果已构建）
frontend_datas = []
dist_dir = code_dir / 'dist'
if dist_dir.exists():
    frontend_datas.append((str(dist_dir), 'dist'))

# ── Analysis ──────────────────────────────────────────────
a = Analysis(
    [str(backend_dir / 'run.py')],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=[
        *frontend_datas,
        *chromium_datas,
    ],
    hiddenimports=[
        # uvicorn
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # SQLAlchemy + aiosqlite
        'sqlalchemy.dialects.sqlite',
        'aiosqlite',
        # Auth
        'bcrypt',
        'jwt',
        # Logging
        'loguru',
        # Pydantic
        'pydantic',
        'pydantic_settings',
        # Playwright
        'playwright',
        'playwright.sync_api',
        'playwright.async_api',
        'playwright._impl',
        'playwright._impl._browser',
        'playwright._impl._page',
        'greenlet',
        'greenlet._greenlet',
        # HTTP client
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'httpcore',
        # Scheduler
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.triggers.interval',
        'apscheduler.triggers.cron',
        # Crypto
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat.primitives.kdf.hkdf',
        # Image (watermark)
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        # multipart
        'multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(backend_dir / 'runtime_hook.py')],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
        'IPython',
        'notebook',
        'cv2',
        'torch',
        'tensorflow',
    ],
    noarchive=False,
    optimize=0,
)

# ── PYZ ───────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data)

# ── EXE（onedir 模式） ───────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AethelEye',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 保留控制台便于查看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# ── COLLECT ───────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['chromium*'],  # Chromium 不压缩，避免启动慢
    name='AethelEye',
)
