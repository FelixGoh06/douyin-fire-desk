# 故障排除

## 一键诊断

先执行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/doctor.sh
```

它会检查应用服务、Nginx、本机登录页、OpenClaw 定时器和最近日志。

## 网页打不开

```bash
sudo systemctl status douyin-fire-desk.service
sudo systemctl status nginx
sudo ss -lntp | grep 8787
sudo nginx -t
```

若服务正常但外部打不开，问题通常是云安全组或 UFW。确认放行安装时选择的端口，不是内部端口 `7788`。

## Nginx 显示 502

后台进程没有成功启动。查看日志：

```bash
sudo journalctl -u douyin-fire-desk.service -n 150 --no-pager
sudo systemctl restart douyin-fire-desk.service
```

检查 `/etc/douyin-fire-desk.env` 是否仍存在且 `DATABASE_PATH` 指向 `/var/lib/douyin-fire-desk/admin.db`。

## Chromium 或 Playwright 报错

重新安装浏览器依赖：

```bash
cd /opt/douyin-fire-desk
sudo PLAYWRIGHT_BROWSERS_PATH=/opt/douyin-fire-desk/.playwright .venv/bin/python -m playwright install --with-deps chromium
sudo systemctl restart douyin-fire-desk.service
```

## Cookie 状态失效

在 **账号管理** 编辑对应账号，重新粘贴最新 Cookie 并保存。不要把 Cookie 发到日志、Issue 或聊天中。随后点击该账号的 Cookie 检查或等待下一次健康检查。

## 好友找不到或检查未知

确认任务中的昵称和抖音聊天列表显示名完全一致。先点该任务的 **检查火花**，在实时日志中确认浏览器已进入正确账号和会话。`未知` 代表本次没有可靠识别结果，不能理解为“对方没续”。

## OpenClaw 没通知

```bash
sudo systemctl status douyin-fire-openclaw-notify.timer
sudo journalctl -u douyin-fire-openclaw-notify.service -n 100 --no-pager
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh
```

确认 `/etc/douyin-fire-desk-openclaw.env` 里的 `OPENCLAW_CHANNEL` 和 `OPENCLAW_NOTIFY_TARGET` 已填写，并且你已经通过官方 onboarding 配置该渠道。

## OpenClaw 找不到 Skill

Skill 名称是 `douyin-fire-admin`，不是项目目录名。使用完成 OpenClaw onboarding 的 Linux 用户重新安装：

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --user YOUR_LINUX_USER
```

## 更新后任务没有执行

```bash
sudo systemctl restart douyin-fire-desk.service
sudo journalctl -u douyin-fire-desk.service -f
```

确认任务没有被停用，且服务器时间和 `APP_TIMEZONE=Asia/Shanghai` 设置正确。
