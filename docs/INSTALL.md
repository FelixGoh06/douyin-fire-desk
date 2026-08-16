# 傻瓜式安装

本文按“刚买好服务器”的情况写。安装脚本支持 **Debian 12、Ubuntu 22.04、Ubuntu 24.04**，会自动安装 Python、Nginx、Playwright、Chromium、systemd 服务所需依赖。

## 0. 准备清单

- 一台 2 核 4 GB 以上的 Linux 服务器，建议至少 20 GB 磁盘。
- 服务器公网 IP、root 密码或 SSH 密钥。
- 在云厂商安全组中放行 TCP `22`（SSH）和 `8787`（后台）。
- 一台能打开浏览器的电脑或手机。

端口 `8787` 可替换。例如想使用 `9000`，将后续安装命令的 `--port 9000` 一并带上，并在安全组放行 `9000`。

## 1. 登录服务器

Windows 可以使用 PowerShell，macOS/Linux 使用 Terminal：

```bash
ssh root@你的服务器IP
```

第一次连接输入 `yes`，再输入服务器密码。看到类似 `root@...:~#` 表示已经登录成功。

## 2. 下载项目

在服务器执行下面三行，可直接复制：

```bash
apt-get update
apt-get install -y git
git clone https://github.com/FelixGoh06/douyin-fire-desk.git
```

进入目录：

```bash
cd douyin-fire-desk
```

如果你已经下载过项目，更新时使用：

```bash
cd douyin-fire-desk
git pull
sudo bash install.sh
```

## 3. 一键安装

普通安装：

```bash
sudo bash install.sh
```

脚本会依次：

1. 检查系统类型并更新软件源。
2. 自动安装缺失的 `curl`、Git、Python、venv、Nginx、OpenSSL、Xvfb。
3. 创建独立系统用户、数据目录和浏览器 Profile 目录。
4. 安装 Python 依赖、Playwright 和 Chromium。
5. 自动生成管理员密码、会话密钥、Cookie 加密密钥和 OpenClaw API Token。
6. 建立 `douyin-fire-desk.service` 与 Nginx 反向代理，并启动服务。

安装结束时会显示如下信息：

```text
Web address: http://你的服务器IP:8787
Admin username: admin
Initial password: 一串随机密码
```

立即把这串密码保存到安全位置。它不会再次显示；服务器上保存位置为 `/etc/douyin-fire-desk.env`。

## 4. 打开后台

浏览器输入：

```text
http://你的服务器IP:8787
```

用户名是 `admin`，密码是上一步末尾显示的初始密码。登录后按 [使用手册](USAGE.md) 添加账号和任务。

如果网页打不开，优先检查：

```bash
sudo bash /opt/douyin-fire-desk/scripts/doctor.sh
sudo ss -lntp | grep 8787
```

再确认云安全组和服务器防火墙允许 TCP `8787`。Ubuntu 使用 UFW 时可执行：

```bash
sudo ufw allow 8787/tcp
```

## 5. 选择 OpenClaw（可选）

想要自动汇报和对话式操作，安装时选择 `y`，或直接执行：

```bash
sudo bash install.sh --with-openclaw
```

服务器还没有 OpenClaw 时，使用：

```bash
sudo bash install.sh --install-openclaw
```

该命令会调用 OpenClaw 官方安装地址 `https://openclaw.ai/install.sh`。首次安装会启动官方 `openclaw onboard --install-daemon`；根据屏幕提示完成你的消息渠道登录。随后填写通知渠道和收件人。详细步骤在 [OPENCLAW.md](OPENCLAW.md)。

## 常用参数

```bash
sudo bash install.sh --port 9000
sudo bash install.sh --without-openclaw
sudo bash install.sh --with-openclaw
sudo bash install.sh --install-openclaw
sudo bash install.sh --non-interactive --without-openclaw
```

## 卸载与保留数据

停止服务但保留数据库、Cookie、Profile 和配置：

```bash
sudo bash /opt/douyin-fire-desk/scripts/uninstall.sh
```

彻底删除所有运行数据（不可恢复）：

```bash
sudo bash /opt/douyin-fire-desk/scripts/uninstall.sh --purge
```
