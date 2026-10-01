# 业码汇

<img src="docs/assets/yemahui-banner-large.png" alt="业码汇" width="100%">

当前版本 **0.2.0**。本版是《AI实施与验收总方案》批次A的基础交付，尚未完成五角色权限、客户开票版本与快照、15天设备签名租约、导出队列及Windows2019目标压测。进度见[实施状态](docs/实施状态.md)，发布说明见[版本说明](docs/releases/v0.2.0.md)。

## 安装

从[GitHub Release](https://github.com/byttao/FirmMatterCodeManagement/releases)下载完整Windows ZIP及SHA256SUMS.txt，校验后解压到新的固定本地目录，运行Manager.exe并选择一键启动。程序提供HTTP网页和API，默认0.0.0.0:8000，使用WinSW开机自启和异常重启；关闭管理工具不停止服务。客户不需要Python、Node、反向代理、域名或证书。

服务器本机访问http://127.0.0.1:8000/，其他电脑使用可路由的内网或公网IP。首次安装只能从真实本机连接完成。公网IP填写到管理工具外部地址中以纳入Host白名单。须单独放行Windows防火墙、云安全组或路由端口转发，程序不能绕过NAT。

HTTP不加密密码、会话及业务资料，Cookie和应用权限不能替代传输加密。生产data目录不得放在NAS或实时同步目录。

本版本不读取0.1.x数据库，不提供原地升级或迁移。保留旧数据、配置和密钥的备份；使用新目录初始化。未知结构会明确拒绝启动，绝不自动清库。管理工具的旧升级执行入口已停用。

## 本批行为

- 项目更新先检查对象权限，空更新返回422 empty_update，禁止注入编号等未知字段。
- 登录使用HttpOnly/SameSite=Lax Cookie，HTTP下不设置Secure。浏览器写操作带X-CSRF-Token；跨来源写入拒绝。会话不存localStorage。
- 账号安全页可改本人密码或退出所有设备。管理员重置密码、禁用账号及变更角色会使旧会话失效。
- 服务器返回请求编号，API响应no-store；正式短信登录未开放。
- SQLite开启WAL、实际外键约束、FULL同步和30秒busy_timeout。
- 当前三类角色、客户主数据和财务功能仍是批次B/C改造对象，不等同于总方案权限矩阵已实现。

## 源码开发与测试

Python3.11+、Node20+。前端生产API使用相对地址/api。请显式使用新的临时data目录，避免启动旧测试数据库。

```bash
python -m pip install -r backend/requirements.txt
python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
```

本地调试可设置FIRM_MANAGER_DATA_DIR、FIRM_MANAGER_PORT、FIRM_MANAGER_ALLOWED_HOSTS（逗号分隔）及FIRM_MANAGER_ALLOWED_PORTS。启动uvicorn时指定--no-proxy-headers，直接连接模式不信任客户端X-Forwarded-For/Host。仓库外原测试环境属于旧版，不能直接用于本版本。

## 发布

VERSION与frontend/package.json版本一致，推送v版本Tag触发仓库测试、Windows构建及EXE/服务启动检查；附件上传完整后发布Release。开发机GitHub流量使用指定代理，GitHub托管runner不使用内网代理。每批说明位于docs/releases。真实数据、密钥和许可证不得进入Git。

[第三方许可证](THIRD_PARTY_NOTICES.md) · [MIT](LICENSE)
