业码汇 - Windows 服务器版

1. 解压整个 ZIP 到固定目录，例如 C:\FirmMatterCodeManagement。
2. 双击 Manager.exe，接受 Windows 管理员权限提示。
3. 确认监听范围、端口和可选的外部 IP/域名，点击“一键启动”。默认监听 `0.0.0.0:8000`，无需手动修改即可通过本机、局域网 IP 或公网 IP 访问。
4. 管理工具将安装开机自启的 Windows 服务、配置入站防火墙，并打开本机首次启用页面。
5. 在首次启用页面创建管理员，填写本所名称、业务类型和编号模板。

完整图文说明：双击“安装与初始化.html”。
安装包内的 `yemahui-banner-small.png` 和 `favicon.ico` 用于安装说明页面品牌展示。
Manager.exe 和 BackendServer.exe 使用 PyInstaller 文件夹模式；运行所需的 Python 运行时分别位于 Manager-internal 和 BackendServer-internal。正式运行不需要另装 Python 或 Node.js，也不会在每次启动时解压运行时。
两个 EXE 必须与各自的 -internal 目录一起保留，不能单独复制到其他位置。升级请在管理工具中选择完整的 Release ZIP，工具会整体替换运行时目录并保留 data。
从旧的单文件版第一次切换时：先停服务并关闭旧管理工具，备份 data，将新版 ZIP 解压覆盖原目录（保留 data），再运行新版 Manager.exe。旧版管理工具不能直接安装文件夹模式 ZIP。
关闭 Manager.exe 不会停止后台服务。业务数据和密钥保存在 data 目录。
发布包不附带额外的 Python 安装包；如需维护源码，请在开发环境单独安装 Python 和依赖。

公网访问前请放行主机防火墙、云安全组或路由器端口转发；系统直接提供 HTTP，不包含 HTTPS，敏感业务建议另行配置 HTTPS 反向代理。
