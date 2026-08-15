# OpenClaw 集成

OpenClaw 是可选组件。接入后它有两种职责：接收后台自动汇总通知，以及在你的对话渠道中调用 `douyin-fire-admin` Skill 操作后台。

## 自动接入

在项目目录执行：

```bash
sudo bash install.sh --with-openclaw
```

如果服务器尚未安装 OpenClaw：

```bash
sudo bash install.sh --install-openclaw
```

第二条命令会使用 OpenClaw 官方安装方式：

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
openclaw onboard --install-daemon
```

安装器不会编造或猜测你的消息渠道账号。官方 onboarding 完成后，脚本会询问两项内容：

- `OpenClaw notification channel`：你在 OpenClaw 中已配置的渠道名。
- `Notification recipient / target`：该渠道下接收汇报的用户或会话标识。

不确定时可以先留空，之后重新运行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh
```

## 验证 Skill

Skill 名称固定为：`douyin-fire-admin`。

安装脚本结尾会打印验证命令。通常可以使用：

```bash
sudo -u YOUR_LINUX_USER HOME=/home/YOUR_LINUX_USER openclaw skills info douyin-fire-admin
```

如果 Skill 没有出现，先确认当前对话使用的就是完成 onboarding 的同一个 Linux 用户，再重新执行 `setup-openclaw.sh --user YOUR_LINUX_USER`。

## OpenClaw 可以做什么

Skill 调用后台本机 API，并总是先读取实时数据，不应根据聊天记忆猜测状态。它支持：

- 查看账号、任务、好友、Cookie 状态和近 24 小时汇总。
- 指定昵称进行即时火花检查。
- 检查所有启用好友的当日火花状态。
- 执行单个任务或所有启用任务的续火。
- 对指定账号执行 Cookie 检查，或检查全部账号。
- 创建、编辑、停用或删除账号、任务和好友目标。

推荐对话表达：

```text
检查“宝贝”今天有没有续火
检查所有人的火花情况
执行今天所有续火任务
查看 Cookie 健康状态
给账号 A 新增一个每天 09:00 的续火任务，好友昵称是小明
```

对于“今天是否续火”的问题，Skill 会启动一次新的检查并等待结果。返回 `unknown` 时只能说无法判断，绝不会把未知误报成未续。Cookie 可以写入或更新，但 Skill 不会读取和回复 Cookie 明文。

## 自动通知规则

通知服务是 `douyin-fire-openclaw-notify.timer`，每分钟拉取后台通知。后台本身负责定时和批次聚合，通知服务只负责投递。

- 同时间续火：一条汇总，失败在前、成功在后。
- 同时间晚间检查：一条汇总，未续、未知、已续依次排列。
- 同时间 Cookie 检查：一条汇总，未保存、失效、未知、有效依次排列。
- 不同时间段：在各自时间发送各自汇总。

检查计时由后台 APScheduler 完成。不要额外创建旧式“固定 Cookie cron”，否则会出现重复检查或重复通知。

## 服务维护

```bash
sudo systemctl status douyin-fire-openclaw-notify.timer
sudo journalctl -u douyin-fire-openclaw-notify.service -n 100 --no-pager
sudo systemctl restart douyin-fire-openclaw-notify.timer
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh
```

通知渠道和收件人配置保存在 `/etc/douyin-fire-desk-openclaw.env`，权限为 `0600`。修改后执行：

```bash
sudo systemctl restart douyin-fire-openclaw-notify.timer
```

不要把该文件、`/etc/douyin-fire-desk.env`、数据库或浏览器 Profile 上传到 GitHub。

Skill 只读取 `/etc/douyin-fire-desk-agent.env` 中最小化的本机 API Token，不能读取管理员密码或 Cookie 加密密钥。安装时会把 OpenClaw 所在 Linux 用户加入 `douyin-fire-agent` 组；若 OpenClaw 已在运行，重启它的 gateway 或重新登录该 Linux 用户一次，使新组权限生效。
