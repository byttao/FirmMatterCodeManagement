事务所业务编号管理系统 - Windows 服务器版

1. 解压整个 ZIP 到固定目录，例如 C:\FirmMatterCodeManagement。
2. 双击 Manager.exe，接受 Windows 管理员权限提示。
3. 设置监听范围、端口和可选的外部 IP/域名，点击“一键启动”。
4. 管理工具将安装开机自启的 Windows 服务、配置入站防火墙，并打开本机首次启用页面。
5. 在首次启用页面创建管理员，填写本所名称、业务类型和编号模板。

完整图文说明：双击“安装与初始化.html”。
Manager.exe 和 BackendServer.exe 已包含 Python 运行时；正式运行不需要另装 Python 或 Node.js。
关闭 Manager.exe 不会停止后台服务。业务数据和密钥保存在 data 目录。
发布包不附带额外的 Python 安装包；如需维护源码，请在开发环境单独安装 Python 和依赖。

公网访问前请配置 DNS/路由；敏感业务建议使用 HTTPS 反向代理。
