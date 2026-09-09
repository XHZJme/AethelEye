# 第三方软件说明

AethelEye 使用多个第三方开源项目。项目本身的 Apache License 2.0 不会替代这些组件各自的许可证；使用者在源码、二进制或安装包再分发时，仍须遵守对应版本的版权声明、许可证、NOTICE 和其他适用条件。

## 直接依赖许可证快照

下表根据本次发布候选所锁定版本的包元数据生成，仅用于帮助审查；正式发布仍应随构建产物保留各组件原始许可证文本和版权声明。

| 后端依赖 | 锁定版本 | 包元数据声明的许可证 |
| --- | ---: | --- |
| FastAPI | 0.141.1 | MIT |
| Uvicorn | 0.52.4 | BSD-3-Clause |
| SQLAlchemy | 2.0.52 | MIT |
| aiosqlite | 0.22.1 | MIT |
| Pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| PyJWT | 2.13.0 | MIT |
| bcrypt | 5.0.0 | Apache-2.0 |
| Cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| Loguru | 0.7.3 | MIT |
| HTTPX | 0.28.1 | BSD-3-Clause |
| psutil | 7.2.2 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| APScheduler | 3.11.3 | MIT |
| Playwright | 1.62.0 | Apache-2.0 |
| Pillow | 12.3.0 | MIT-CMU |
| PyInstaller | 6.22.2 | GPL-2.0-or-later，附允许分发生成程序的特殊例外 |
| pystray | 0.19.5 | LGPL-3.0 |

| 前端依赖 | 锁定范围 | 包元数据声明的许可证 |
| --- | ---: | --- |
| Vue | `^3.4.21` | MIT |
| Vue Router | `^4.3.0` | MIT |
| Pinia | `^2.1.7` | MIT |
| Element Plus | `^2.6.1` | MIT |
| `@element-plus/icons-vue` | `^2.3.1` | MIT |
| Axios | `^1.20.0` | MIT |
| Apache ECharts | `^6.1.0` | Apache-2.0 |
| TypeScript | `^5.4.2` | Apache-2.0 |
| Vite | `^8.2.2` | MIT |
| `@vitejs/plugin-vue` | `^6.0.8` | MIT |
| `vue-tsc` | `^3.3.11` | MIT |
| `@types/node` | `^20.11.24` | MIT |

## 重要提示

- 精确依赖版本以 `frontend/package-lock.json` 和实际 Python 环境解析结果为准；
- Playwright 下载的浏览器包含 Chromium 及其第三方组件，二进制分发前必须保留相应版权与许可证文件；
- PyInstaller 的特殊例外不免除被打包依赖自身的义务；`pystray` 为 LGPL-3.0，生成 Windows 安装包前应专门核对其通知、源码提供和可替换/重新链接要求；
- 操作系统运行库、字体、图片、站点内容和其他随包资产可能有独立条款；
- 仓库中的第三方名称与商标仅用于说明兼容性或来源，权利归各自权利人所有；
- 发布者应在每次发版时重新生成软件物料清单（SBOM）并复核许可证，不应仅依赖本概览。
