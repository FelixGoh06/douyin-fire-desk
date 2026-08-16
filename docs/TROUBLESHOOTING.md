# 故障排除

## 一键诊断

普通主机先执行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/doctor.sh
```

## GitHub 克隆卡住或报 TLS 错误

国内服务器不要反复重试 GitHub，直接使用 Gitee：

```bash
curl -fsSL https://gitee.com/gongyu2006/douyin-fire-desk/raw/main/bootstrap.sh | sudo bash
```

如果你已在项目目录：

```bash
git remote -v
git pull
```

不要把 GitHub 用户名改进 Gitee 链接；大陆镜像固定为 `gongyu2006/douyin-fire-desk`。

## 不知道网页地址、账号或密码

运行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/show-admin-credentials.sh
```

默认 Web 地址格式是 `http://服务器公网IP:8787`，默认账号为 `admin`。该工具显示的是当前密码，密码在网页里修改后也会同步显示新值。

## 网页打不开

```bash
sudo systemctl status douyin-fire-desk.service nginx
sudo ss -lntp | grep -E ':(8787|7788)\\b'
sudo nginx -t
```

确认云安全组和 UFW 放行 `8787`，不要放行内部端口 `7788`。如果是在 Docker 内，确认 Docker 主机有 `8787:8787` 端口映射。

## Nginx 显示 502

```bash
sudo journalctl -u douyin-fire-desk.service -n 150 --no-pager
sudo systemctl restart douyin-fire-desk.service nginx
```

检查 `/etc/douyin-fire-desk.env` 是否仍存在，且 `DATABASE_PATH` 指向 `/var/lib/douyin-fire-desk/admin.db`。

## OpenClaw 显示 Gateway not reachable

普通主机：

```bash
openclaw gateway status
openclaw gateway restart
```

Docker 容器没有 systemd 时，不要使用 `openclaw gateway install`。重新执行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --wechat --auto
```

脚本会自动使用后台 Gateway。查看日志：

```bash
tail -n 100 /var/lib/douyin-fire-desk/openclaw-runtime/gateway.log
```

## 微信扫码成功但没有收到通知

先确认微信通道：

```bash
openclaw channels status --probe
```

然后确认接收微信号已经向机器人账号发过一条消息，再重跑：

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --wechat --auto
```

脚本需要从配对请求中取得接收者的 `@im.wechat` 标识；未完成这个安全配对时，Skill 仍可工作，但定时报告不会发出。

## OpenClaw 找不到 douyin-fire-admin

```bash
sudo bash /opt/douyin-fire-desk/scripts/setup-openclaw.sh --auto
openclaw skills info douyin-fire-admin
```

Skill 名称固定是 `douyin-fire-admin`，不是项目目录名。

## Cookie 失效、好友找不到或检查未知

- Cookie 失效：在 **账号管理** 编辑账号，粘贴最新 Cookie，保存后点击 Cookie 检查。
- 找不到好友：昵称必须与抖音聊天列表显示名完全一致；先点任务的 **检查火花** 并查看实时日志。
- `未知`：当前检查没有可靠识别到结果，不等于对方没有续火。

## Chromium/Playwright 报错

```bash
cd /opt/douyin-fire-desk
sudo PLAYWRIGHT_BROWSERS_PATH=/opt/douyin-fire-desk/.playwright .venv/bin/python -m playwright install --with-deps chromium
sudo systemctl restart douyin-fire-desk.service
```
