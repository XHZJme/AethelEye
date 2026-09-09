"""
筱和灵眸(AethelEye) - MCP Server 模块

将 AethelEye 的核心能力暴露为 MCP (Model Context Protocol) Tools，
使得 Claude Desktop / OpenClaw / Hermes 等外部 Agent 可调用。

端口：8687（独立于主应用 FastAPI，安全隔离）
"""
