# OpenClaw 集成

OpenClaw 负责两件事：在微信里对话式管理后台，以及把后台已聚合的续火、晚间检查和 Cookie 结果推送到微信。

## 自动接入

在已安装后台的服务器执行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --install-openclaw --wechat --auto
```

日常安装直接使用 `sudo bash install.sh --with-openclaw` 即可，它会自动调用上面的流程。

流程会自动：

- 从 OpenClaw 官方安装器安装 CLI。
- 打开中文模型配置向导，并验证模型。
- 安装 `douyin-fire-admin` Skill。
- 安装腾讯 `@tencent-weixin/openclaw-weixin` 插件。
- 启动 Gateway；没有 systemd 的容器使用受控 `nohup` 后台进程。
- 显示微信登录二维码。
- 识别首个已配对接收微信号，将其设为通知接收者。
- 启动每分钟的通知投递器。普通主机使用 systemd timer；容器使用后台循环。

## 微信角色与配对

- **OpenClaw 微信号**：终端二维码扫码登录的账号，作为机器人发送消息。
- **接收微信号**：你平时使用、接收报告并发送管理指令的账号。

扫码后，用接收微信号给 OpenClaw 微信号发送一条任意消息。脚本会自动等待 3 分钟、批准该配对请求，并只把该账号作为自动报告目标；不需要再回终端确认。

如果第一次没有识别成功，先确认接收号已发消息，再重跑：

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --wechat --auto
```

不要把自己的主力微信号同时作为机器人号和接收号。微信插件按私聊工作，稳定方案是使用两个账号。

## Web 后台如何与 OpenClaw 通信

没有公网 API 对接步骤。两者在同一服务器上通过以下本机地址通信：

```text
OpenClaw Skill -> http://127.0.0.1:7788/api/openclaw -> Douyin Fire Desk
```

Skill 只读取 `/etc/douyin-fire-desk-agent.env` 内的最小 API Token；它不能读取管理员密码或 Cookie 明文。Nginx 会拒绝公网请求 `/api/openclaw/`。

验证连接：

```bash
sudo -u root HOME=/root openclaw skills info douyin-fire-admin
python3 /root/.openclaw/workspace/skills/douyin-fire-admin/scripts/fire_admin.py overview
```

第二条命令返回账号、任务 JSON 即代表 Web 后台和 Skill 已连通。若显示账号/任务均为 `0`，表示这是新服务器上的空数据库，不是对接失败。

## 可以在微信里说什么

```text
检查“宝贝”今天有没有续火
检查所有人的火花情况
执行今天所有续火任务
查看 Cookie 健康状态
给账号 A 新增一个每天 09:00 的续火任务，好友昵称是小明
```

Skill 每次查询“今天是否续火”都会触发一次新的检查；`unknown` 只表示无法可靠识别，绝不会被说成“没续”。

## 服务与日志

普通 Ubuntu/Debian 主机：

```bash
sudo systemctl status douyin-fire-openclaw-notify.timer
sudo journalctl -u douyin-fire-openclaw-notify.service -n 100 --no-pager
```

Docker 容器：

```bash
openclaw gateway status
tail -n 100 /var/lib/douyin-fire-desk/openclaw-runtime/gateway.log
tail -n 100 /var/lib/douyin-fire-desk/openclaw-runtime/notifier.log
```

容器必须由 Docker/Compose 配置为自动重启；容器重建后重新运行 `setup-openclaw.sh --wechat --auto`，以恢复后台 Gateway 和通知循环。
