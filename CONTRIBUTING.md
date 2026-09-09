# 贡献指南

感谢你改进 AethelEye。提交贡献即表示你有权提供相关内容，并同意按项目的 Apache License 2.0 授权该贡献。

## 开发要求

- 不提交真实账号、Cookie、Token、Webhook、API Key、数据库、日志、截图、录屏或任何生产/第三方数据；
- 测试和文档示例必须使用虚构数据；
- 不增加绕过验证码、访问控制、限流或隐藏自动化特征的功能；
- 新增外部通信时，必须默认关闭，并在 `PRIVACY.md` 中说明接收方、数据字段和触发条件；
- 新增依赖前检查许可证、维护状态和供应链风险；
- 保持后端默认监听本机地址，并为新增接口补充权限检查。

## 本地验证

```powershell
python -m compileall -q backend
cd frontend
npm ci
npm run type-check
npm run build
```

提交前请对工作树和暂存区运行密钥扫描，并人工检查图片、文档和二进制文件。

## Pull Request

请清楚说明变更目的、影响范围、验证方式和任何数据/网络/权限变化。安全问题请按 `SECURITY.md` 私下报告，不要先公开利用细节。
