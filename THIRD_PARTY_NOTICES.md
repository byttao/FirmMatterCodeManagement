# 第三方致谢

业码汇使用了以下开源项目。感谢各项目维护者和贡献者。第三方项目继续按照各自的许可证授权；本项目的 MIT 协议不替代或改变这些许可证。

## 运行时与后端

| 项目 | 用途 | 许可证 |
| --- | --- | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | Web API | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务 | BSD-3-Clause |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | 数据库访问 | MIT |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据校验 | MIT |
| [python-jose](https://github.com/mpdavis/python-jose) | JWT 认证 | MIT |
| [Passlib](https://bitbucket.org/ecollins/passlib) | 密码哈希 | BSD-3-Clause |
| [python-multipart](https://github.com/Kludex/python-multipart) | 文件上传 | Apache-2.0 |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) | Excel 导入导出 | MIT |
| [bcrypt](https://github.com/pyca/bcrypt) | 密码哈希算法 | Apache-2.0 |
| [pypinyin](https://github.com/mozillazg/python-pinyin) | 中文拼音搜索 | MIT |

## 前端与构建

| 项目 | 用途 | 许可证 |
| --- | --- | --- |
| [React](https://github.com/facebook/react) / [React DOM](https://github.com/facebook/react) | 前端界面 | MIT |
| [React Router](https://github.com/remix-run/react-router) | 页面路由 | MIT |
| [TypeScript](https://github.com/microsoft/TypeScript) | 类型检查 | Apache-2.0 |
| [Vite](https://github.com/vitejs/vite) | 前端构建 | MIT |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | 样式系统 | MIT |
| [Radix UI](https://github.com/radix-ui/primitives) | 无障碍 UI 组件 | MIT |
| [Axios](https://github.com/axios/axios) | HTTP 请求 | MIT |
| [Lucide](https://github.com/lucide-icons/lucide) | 图标 | ISC |
| [Recharts](https://github.com/recharts/recharts) | 数据图表 | MIT |
| [date-fns](https://github.com/date-fns/date-fns) | 日期处理 | MIT |

## Windows 发布工具

| 项目 | 用途 | 许可证 |
| --- | --- | --- |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | 构建自带运行时的 EXE | GPL-2.0-or-later with Bootloader Exception |
| [WinSW](https://github.com/winsw/winsw) | Windows 服务包装器 | MIT |

Windows 发布包中的 `LICENSE-WinSW.txt` 保存了随包发布的 WinSW 许可证文本。完整的直接依赖和传递依赖版本记录见 [`backend/requirements.txt`](backend/requirements.txt) 与 [`frontend/package-lock.json`](frontend/package-lock.json)。
