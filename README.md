# 事务所业务编号管理系统

面向会计师事务所、税务师事务所及其他专业服务机构的项目管理工具，覆盖项目分配、业务编号、签字人、开票登记、收款登记、权限管理和 Excel 导出。

## 功能概览

- 管理人员、执业人员、后勤行政三类角色及权限控制
- 按操作年度、事务所、业务类型维护自定义编号规则
- 项目负责人和团队成员分配，支持姓名、拼音搜索
- 报告编号生成、回收和状态追踪
- 开票金额、收款金额及对应日期登记
- 签字人启用、禁用、导入和导出
- 项目和签字人 Excel 导出
- 首次启用向导：自定义管理员、事务所、业务类型和编号模板

## 技术栈

- 前端：React 18、TypeScript、Vite、Tailwind CSS、Radix UI
- 后端：Python、FastAPI、SQLAlchemy、SQLite、openpyxl
- 认证：JWT

## 环境要求

- Python 3.11 或更高版本
- Node.js 18 或更高版本（仅开发和重新构建前端时需要）

## 快速启动

### 开发模式

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

另开终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5174`。

### 单体模式

先执行 `npm run build`，将 `frontend/dist` 内容复制到 `backend/static`，再运行：

```bash
cd backend
python main.py
```

浏览器访问 `http://localhost:8000`。仓库只包含通用源码，旧版 Windows 启动脚本留在原工作目录，不作为新安装入口。

## 首次启用

首次打开系统会自动进入安装向导。请按向导完成：

1. 创建管理员账号和至少 8 位密码。
2. 选择首个编号年度。
3. 填写事务所名称。
4. 为每个事务所添加业务类型和编号模板。

编号模板必须包含 `{yyyy}` 和唯一的序号占位符，例如 `{nnn}`。安装完成后，使用新建账号登录，再到“用户管理”“签字人管理”和“编号年度配置”继续维护。

系统不会自动创建默认账号、示例事务所或示例文号。运行数据保存在 `backend/data/db.sqlite`，已通过 Git 忽略，不应提交到代码仓库。

出于首次安装安全考虑，安装向导需要在运行后端的电脑上打开；安装接口只接受本机请求。默认服务也只监听 `127.0.0.1`。需要局域网访问时，完成安装后再通过 `FIRM_MANAGER_HOST` 和 `FIRM_MANAGER_PORT` 配置监听地址与端口。

## 数据与配置

默认数据库路径为 `backend/data/db.sqlite`。部署时可以通过 `FIRM_MANAGER_DATA_DIR` 指定数据目录，或通过 `FIRM_MANAGER_DATABASE_URL` 指定 SQLAlchemy 数据库连接串。

JWT 签名密钥首次启动时自动生成在数据目录的 `jwt_secret` 文件中。也可通过 `FIRM_MANAGER_SECRET_KEY` 设置至少 32 个字符的密钥。前后端分开部署时，可用 `FIRM_MANAGER_CORS_ORIGINS` 指定允许的前端来源，多个来源用英文逗号分隔。

## 角色说明

- 管理人员：全部功能
- 执业人员：查看和编辑自己参与的项目，生成报告编号
- 后勤行政：查看项目，维护财务信息，导出数据，管理签字人

## 版本发布

每次推送都应对应一个递增版本号和 GitHub Release。提交说明与 Release 标题、更新说明使用简短中文，概括版本号及主要修改。正式发布前执行后端集成测试与前端构建，并确认运行数据库、密钥、工作记忆和构建产物未进入 Git 暂存区。
