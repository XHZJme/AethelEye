# 部署与打包

本文仅介绍本地开发和 Windows 打包。AethelEye 默认面向单机学习环境，不建议未经加固直接暴露到公网。

## 开发运行

### 后端

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
playwright install chromium
cd backend
python run.py
```

默认地址：`http://127.0.0.1:8686`。

### 前端

```powershell
cd frontend
npm ci
npm run dev
```

默认地址：`http://127.0.0.1:5173`。

### 生产静态文件

```powershell
cd frontend
npm run type-check
npm run build
```

Vite 会把构建结果写入仓库根目录的 `dist/`，FastAPI 会在启动后托管该目录。

## Windows 打包

安装 Inno Setup 后，在仓库根目录运行：

```powershell
python build_all.py
```

脚本会安装/检查依赖、构建前端、下载 Playwright Chromium、用 PyInstaller 打包后端，并调用 Inno Setup 生成安装程序。所有输出位于 `backend/dist/`、`installer/output/` 或 `release/`，这些目录均不会提交到 Git。

## 发布前检查

1. 使用全新虚拟环境和全新 `data/` 目录完成启动测试；
2. 运行后端语法检查、前端类型检查和生产构建；
3. 使用密钥扫描器检查工作树、暂存区和完整 Git 历史；
4. 确认发布包不含数据库、日志、截图、录屏、浏览器资料、`.env` 或密钥文件；
5. 检查二进制包内全部第三方组件的许可证、NOTICE 和再分发条件；
6. 对安装、升级、卸载和数据保留行为做隔离环境测试；
7. 由有权限的负责人完成知识产权、数据保护和安全审批。

如需局域网或公网部署，至少增加 TLS、反向代理、来源白名单、强认证、防火墙、备份加密、审计与速率限制，并由安全人员重新评估。
