# Douyin Fire Desk

**抖音火花运营台**。面向个人服务器的 Web 管理后台：集中保存账号 Cookie、按昵称维护好友、定时发送续火消息、晚间检查对方是否续火，并可通过 OpenClaw 汇总通知和操作后台。

> Version: **v1.0.11** | License: [MIT](LICENSE) | Runtime: Debian/Ubuntu Linux

## 这是什么

Douyin Fire Desk 将浏览器自动化、任务调度和通知集中到一台 Linux 服务器。后台不会上传 Cookie；Cookie 在服务器本地数据库中使用 Fernet 加密保存。Web 页面是日常操作入口，OpenClaw 是可选的对话式操作和通知入口。

建议配置：**2 核 4 GB 内存**、20 GB 磁盘、Debian 12 或 Ubuntu 22.04/24.04。单账号日常运行通常远低于此配置；首次安装 Chromium 时会短暂占用更多磁盘和内存。

## 功能清单

| 模块 | 能力 |
| --- | --- |
| 账号管理 | 独立保存每个账号的 Cookie、浏览器 Profile、Cookie 状态与健康检查时间 |
| 好友与任务 | 任务和账号分离；一个任务可维护多个好友昵称、发送时刻、消息模板、重试参数 |
| 定时续火 | APScheduler 按任务时间执行；同一时间段的任务按批次汇总，而不是逐条打扰 |
| 晚间检查 | 自动读取目标好友当日火花状态；结果按“未续、未知、已续”排序 |
| Cookie 健康 | 每账号可设置每日检查时间；未保存、失效、未知、有效都会进入统一汇总 |
| 实时记录 | 从任务页执行或检查时，直接打开该任务的实时日志；任务可编辑、停用和删除 |
| 系统安全 | 系统页可验证当前密码后修改管理员密码，保存后自动重启并退出登录 |
| OpenClaw | 可查询真实状态、执行续火或检查、管理账号/任务/目标好友；自动汇报采用同时间批次合并 |
| 安全边界 | 管理后台经 Nginx 公开；OpenClaw 控制 API 只允许本机访问，公网请求被拒绝 |

完整操作见 [使用手册](docs/USAGE.md)，OpenClaw 见 [OpenClaw 集成](docs/OPENCLAW.md)。

## 一条命令安装

先在安全组/防火墙放行 TCP `8787`，然后用 **系统主机 SSH** 登录 Debian/Ubuntu 服务器。Web 后台安装依赖 systemd；不要在没有 systemd 的 Docker 容器终端直接运行这个主安装器。

**中国大陆服务器（Gitee 优先，自动回退 GitHub）：**

```bash
curl -fsSL https://gitee.com/gongyu2006/douyin-fire-desk/raw/main/bootstrap.sh | sudo bash
```

**海外服务器：**

```bash
curl -fsSL https://raw.githubusercontent.com/FelixGoh06/douyin-fire-desk/main/bootstrap.sh | sudo bash -- --github
```

该命令会自动安装后台、依赖、OpenClaw、`douyin-fire-admin` Skill、腾讯微信插件和通知投递器。首次只需要完成模型配置，以及微信扫码和接收号配对；不必手动填写 OpenClaw channel、target 或复制 Skill。

安装结束会输出 Web 地址和管理员密码。忘记密码或地址时，服务器执行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/show-admin-credentials.sh
```

逐步、带排错的说明在 [docs/INSTALL.md](docs/INSTALL.md)。

## 第一次使用

1. 进入 **账号管理**，新增账号并粘贴该账号 Cookie。
2. 进入 **任务管理**，创建任务，选择账号，添加目标好友昵称，填写每天发送时间与消息内容。
3. 点击任务的 **执行**，确认实时日志里能找到对应昵称并发送成功。
4. 需要确认对方当天是否也续火时，在任务中启用 **晚间检查**，填写检查时间。该功能需要 OpenClaw 已接入。
5. 在 **OpenClaw** 页面，为账号设置 Cookie 健康检查时间，并分别开启需要的“续火结果”“晚间检查结果”“Cookie 健康回复”。

## 通知与批次规则

- 同一时刻的续火任务完成后，发送一条合并通知，先列失败后列成功。
- 同一时刻的晚间检查完成后，发送一条合并通知，顺序为未续、未知、已续。
- 同一时刻的 Cookie 健康检查完成后，发送一条合并通知，顺序为未保存、失效、未知、有效。
- 不同时间段仍按各自设置的时间推送。

## 项目结构

```text
app/                         FastAPI 后台、调度器、浏览器执行器和页面
openclaw-skill/              可直接安装的 douyin-fire-admin Skill
scripts/                     OpenClaw 安装、诊断、卸载脚本
deploy/                      systemd 和 Nginx 模板
userscript/                  上游 ScriptCat 用户脚本及其 MIT 授权说明
docs/                        安装、操作、安全、排错和架构文档
```

## 维护命令

```bash
sudo bash /opt/douyin-fire-desk/scripts/doctor.sh
sudo journalctl -u douyin-fire-desk.service -f
sudo systemctl restart douyin-fire-desk.service
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --wechat --auto
sudo bash /opt/douyin-fire-desk/scripts/show-admin-credentials.sh
```

## 安全说明

- Cookie 等同于登录凭据。不要发送到 Issues、聊天记录、截图或 GitHub。
- `.env`、数据库、浏览器 Profile、OpenClaw 渠道配置都已被 `.gitignore` 排除。
- 仅 IP 访问时仍建议限制安全组来源 IP；长期使用建议配置域名与 HTTPS。
- 本项目只在服务器本地保存 Cookie，不向项目作者或任何第三方上传。
- 使用自动化前，请自行确认符合抖音及相关服务的规则和你的账号权限。

详细安全措施见 [docs/SECURITY.md](docs/SECURITY.md)。

## 上游致谢

`userscript/scriptcat-douyin-fire-helper.user.js` 来自 [dr-190/ScriptCat-Douyin-Fire-Helper](https://github.com/dr-190/ScriptCat-Douyin-Fire-Helper)，原作者为飔梦，遵循其附带的 MIT License。该用户脚本作为上游参考和可选配套组件保留，授权文本见 `userscript/LICENSE.upstream-MIT`。

## 贡献与更新

提交问题前请先阅读 [故障排除](docs/TROUBLESHOOTING.md)，并确保移除 Cookie、Token、服务器 IP 和任何个人聊天信息。贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。
