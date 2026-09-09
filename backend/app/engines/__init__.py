"""
筱和灵眸(AethelEye) - 引擎包目录

此目录存放可插拔引擎包。每个引擎是一个子目录，包含 manifest.json + engine.py。
内置引擎（Playwright）不在此目录，通过 engine_registry._register_builtin_engines 注册。
"""
