本目录仅用于源码维护时存放开发人员自行准备的前置环境文件，不会打包进 Windows Release。

Windows 发布包中的 Manager.exe、BackendServer.exe 和服务包装器均已自带运行环境，正式运行无需安装 Python、Node.js 或 Rust。
如需在服务器上直接运行源码或排查 Python 脚本，请在开发环境单独安装匹配版本的 Python 和依赖。
请不要用源码模式覆盖发布包中的 data 目录。升级请优先使用 Manager.exe。
