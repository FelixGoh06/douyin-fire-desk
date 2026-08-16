# 傻瓜式安装

这份流程适用于全新的 Debian 12、Ubuntu 22.04 或 Ubuntu 24.04 主机。推荐配置为 2 核、4 GB 内存、20 GB 磁盘；单账号日常占用较低，但首次下载 Chromium 会占用数 GB 磁盘。

## 先准备

1. 在云厂商安全组放行 TCP `22` 和 `8787`。
2. 使用 **系统主机的 SSH 终端** 登录服务器，而不是 Docker 容器终端。
3. 准备一个专门给 OpenClaw 登录的微信号，以及一个用于接收通知、向它发送指令的微信号。两个角色建议使用不同账号。
4. 准备模型服务的 Base URL、模型 ID 和 API Key；不要把 API Key、Cookie、服务器密码发到聊天或截图中。

> Web 后台的自动安装依赖 systemd 和 Nginx。腾讯云的“Docker 容器终端”通常没有 systemd，不能直接运行 `install.sh`。请连接云主机本身的 SSH；如果你已自行在容器中运行 Web 后台，仍可使用 OpenClaw 的容器兼容接入流程，见 [OpenClaw 集成](OPENCLAW.md)。

## 一条命令安装

### 中国大陆服务器

```bash
curl -fsSL https://gitee.com/gongyu2006/douyin-fire-desk/raw/main/bootstrap.sh | sudo bash
```

### 海外服务器

```bash
curl -fsSL https://raw.githubusercontent.com/FelixGoh06/douyin-fire-desk/main/bootstrap.sh | sudo bash -- --github
```

脚本自动完成：系统依赖、Python、Playwright、Chromium、Nginx、后台服务、管理员密码、OpenClaw、抖音后台 Skill、腾讯微信插件、Gateway 和通知投递器。

> 一键命令会自动把 OpenClaw 向导的键盘输入重新连接到当前终端。看到模型选择菜单后，直接使用方向键和 Enter；不要在该命令执行期间另开一个 Shell 再运行 `openclaw onboard`。

安装过程中只需要你处理以下内容：

1. **模型配置**：在 OpenClaw 菜单选择模型提供商，填写 API Key、Base URL 与模型 ID。自定义 OpenAI 兼容模型选择 `Custom Provider` -> `OpenAI-compatible`。
2. **微信扫码**：按终端二维码登录专用 OpenClaw 微信号。
3. **接收号配对**：用你的接收微信号给刚登录的 OpenClaw 微信号发送任意一条消息。安装器会自动等待 3 分钟、识别该接收号、完成配对，并将它设为自动汇报对象；不需要回终端按 Enter。

接收号配对不能被静默跳过：系统必须确认谁有权执行续火、读取状态和接收 Cookie 告警，不能把控制权限自动交给任意陌生人。

## 安装完成后

终端会显示：

```text
Web address: http://你的服务器IP:8787
Admin username: admin
Initial password: 随机密码
```

浏览器打开 `http://你的服务器公网IP:8787`。`7788` 是仅供 OpenClaw 调用的内部端口，绝不能作为公网后台地址或安全组放行端口。

如果忘记首次显示的密码，在服务器执行：

```bash
sudo bash /opt/douyin-fire-desk/scripts/show-admin-credentials.sh
```

它会再次显示当前管理员账号、密码和地址提示，不会修改密码。网页内也可以从左下角的 **修改密码** 修改。

## 不用一条命令时

大陆服务器：

```bash
git clone --depth 1 https://gitee.com/gongyu2006/douyin-fire-desk.git
cd douyin-fire-desk
sudo bash install.sh --with-openclaw
```

海外服务器：

```bash
git clone --depth 1 https://github.com/FelixGoh06/douyin-fire-desk.git
cd douyin-fire-desk
sudo bash install.sh --with-openclaw
```

`--with-openclaw` 现在会自动安装缺失的 OpenClaw 并执行微信接入；不再要求你手填 channel、target 或手动复制 Skill。

## 首次使用后台

1. 登录 **账号管理**，新增账号并粘贴 Cookie。
2. 打开 **任务管理**，创建任务，选择账号，填写目标好友昵称、发送时间和消息。
3. 先点击一次 **执行**，在实时日志确认浏览器找到了目标昵称。
4. 需要当晚确认对方有没有续火时，开启 **晚间检查** 并设置时间。
5. 在 **OpenClaw** 页面开启需要的续火汇报、晚间检查汇报、Cookie 健康检查和 Cookie 健康回复。

同一时间的任务自动合并为一条消息：续火按失败、成功排序；晚间检查按未续、未知、已续排序；Cookie 按未保存、失效、未知、有效排序。

## 端口与地址排查

网页打不开时，先在服务器执行：

```bash
sudo ss -lntp | grep -E ':(8787|7788)\\b'
sudo bash /opt/douyin-fire-desk/scripts/doctor.sh
```

- `0.0.0.0:8787` 或 `[::]:8787`：服务器已公开 Web 端口，检查安全组/UFW 是否放行 `8787`。
- 只有 `127.0.0.1:7788`：应用内部正常，但 Nginx 公网入口没有启动。运行 `sudo systemctl restart nginx douyin-fire-desk.service` 后重试。
- 使用 Docker：还需要在 Docker 主机映射 `8787:8787`；不要把 `7788` 映射公网。

Ubuntu 启用 UFW 时：

```bash
sudo ufw allow 8787/tcp
```

## 更新与卸载

更新：

```bash
cd /root/douyin-fire-desk
git pull
sudo bash install.sh --with-openclaw
```

卸载服务但保留数据：

```bash
sudo bash /opt/douyin-fire-desk/scripts/uninstall.sh
```

彻底清除账号、Cookie、浏览器 Profile、数据库与配置：

```bash
sudo bash /opt/douyin-fire-desk/scripts/uninstall.sh --purge
```
