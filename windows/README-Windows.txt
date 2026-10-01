业码汇 - Windows 服务器版

1. 解压整个 ZIP 到固定目录，例如 C:\FirmMatterCodeManagement。
2. 双击 Manager.exe，接受 Windows 管理员权限提示。
3. 确认监听范围、端口和可选的外部 IP/域名，点击“一键启动”。默认监听 `0.0.0.0:8000`，无需手动修改即可通过本机、局域网 IP 或公网 IP 访问。
4. 管理工具将安装开机自启的 Windows 服务、配置入站防火墙，并打开本机首次启用页面。
5. 在首次启用页面创建管理员，填写本所名称、业务类型和编号模板。

完整图文说明：双击“安装与初始化.html”。
安装包内的 `yemahui-banner-small.png` 和 `favicon.ico` 用于安装说明页面品牌展示。
Manager.exe 和 BackendServer.exe 使用 PyInstaller 文件夹模式；运行所需的 Python 运行时分别位于 Manager-internal 和 BackendServer-internal。正式运行不需要另装 Python 或 Node.js，也不会在每次启动时解压运行时。
两个 EXE 必须与各自的 -internal 目录一起保留，不能单独复制到其他位置。
v0.6.1 使用结构600，不读取旧数据库、不做原地升级。请保留原数据和密钥备份，在新的本地目录解压完整ZIP并初始化测试。
首次安装生成开票资料加密密钥data/billing.key，请受控备份；已有账号时缺密钥将拒绝启动，不能自动生成替代密钥。
关闭 Manager.exe 不会停止后台服务。业务数据和密钥保存在 data 目录。
发布包不附带额外的 Python 安装包；如需维护源码，请在开发环境单独安装 Python 和依赖。

公网访问前请放行主机防火墙、云安全组或路由器端口转发，并在管理工具中填写公网IP作为Host白名单。系统直接提供HTTP，不包含HTTPS；HTTP不加密密码和资料，本轮不以反向代理或证书作为运行前置条件。

设备身份data/device-identity.json与授权缓存license-state.json应与开票密钥一起受控备份；缺失原身份拒绝替代。发行公钥随包预置，永久使用权也需每15天联网核验。

导出任务由主服务监管的单独进程生成，默认每实例同时生成1项、下载1项、100KiB/s；文件24小时后清理。备份与恢复页提供密码加密完整备份，命令行恢复须使用同版程序及空data目录，详见docs/导出与备份恢复.md。
