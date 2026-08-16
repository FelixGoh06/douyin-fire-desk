# 傻瓜式安装

这份流程适用于全新的 Debian 12/13、Ubuntu 22.04/24.04、Rocky Linux 8/9、AlmaLinux 8/9、RHEL 8/9、CentOS Stream 9、Fedora 和 openEuler 主机。脚本会自动识别 `apt`、`dnf` 或 `yum`。推荐配置为 2 核、4 GB 内存、20 GB 磁盘；单账号日常占用较低，但首次下载 Chromium 会占用数 GB 磁盘。

当前安装器面向带 `systemd` 的常见云服务器；Alpine、Arch、SUSE 与没有 `systemd` 的容器环境暂未纳入自动安装范围。

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

执行后会先进入 `GONGYU` 主菜单：选择 `1` 是完整的一键安装；选择 `2` 只安装 Web 管理后台。完整安装会自动完成系统依赖、Python、Playwright、Chromium、Nginx、后台服务、管理员密码、OpenClaw、抖音后台 Skill、腾讯微信插件、Gateway 和通知投递器。

以后重复执行这条命令时，脚本会识别已有的 `/root/douyin-fire-desk`，不重复克隆或安装系统依赖，直接进入 `GONGYU` 主菜单。

> 一键命令会自动把 OpenClaw 向导的键盘输入重新连接到当前终端。看到模型选择菜单后，直接使用方向键和 Enter；不要在该命令执行期间另开一个 Shell 再运行 `openclaw onboard`。

选择完整安装后，只需要你处理以下内容：

1. **模型配置**：在 OpenClaw 菜单选择模型提供商，填写 API Key、Base URL 与模型 ID。自定义 OpenAI 兼容模型选择 `Custom Provider` -> `OpenAI-compatible`。
2. **微信扫码**：按终端二维码登录专用 OpenClaw 微信号。
3. **接收号配对**：用你的接收微信号给刚登录的 OpenClaw 微信号发送任意一条消息。安装器会自动等待 3 分钟，从微信配对记录或最新私聊记录识别该接收号，并将它设为自动汇报对象；不需要回终端按 Enter。

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

## GONGYU 主菜单

安装过 Web 管理平台后，在服务器输入 `gongyu` 可随时打开管理入口；非 root 用户会自动请求 sudo 权限。数字菜单包含：

1. 一键安装全部组件。
2. 只安装 Web 管理平台，并输出账号、密码、访问地址和端口放行提示。
3. 分级卸载：保留数据停服务、删除 Web 数据、移除本项目 OpenClaw 集成或清理本项目全部组件。
4. 从 OpenClaw 官方安装器安装或配置 OpenClaw；只保留模型向导交互，并确认 Gateway 已运行。
5. 安装/刷新 `douyin-fire-admin` Skill、微信插件或检查 OpenClaw 状态。未安装 OpenClaw 时会提示先选择 `4`。
6. 读取当前管理员用户名和密码。网页修改密码后，这里会显示新密码。
7. 检查并安装缺失的系统依赖；已安装 Web 时也会补齐 Python/Chromium 运行时。
8. 运行服务诊断。

每个二级菜单都可以输入 `0` 返回主菜单。卸载本项目不会删除可供其他程序使用的 OpenClaw 本体、模型配置或无关插件。

### 重复执行菜单时会发生什么

菜单会在每个入口先检查状态，不会把已正常运行的组件再安装一遍：

- 选择 `1` 时，已存在的 Web、Python、Chromium、OpenClaw、模型配置、Gateway、Skill、微信登录和通知接收者都会跳过；仅补齐缺失项。
- 选择 `2` 时，若 Web 管理平台已经正常安装，会直接显示当前账号、密码和地址，不会覆盖数据库、Cookie 或网页密码。
- 选择 `4` 时，已安装 OpenClaw 不会重新下载；已配置模型不会再次进入模型向导。Gateway 异常时只尝试修复 Gateway。
- 选择 `5` 时，已安装且未变更的 Skill 不会重复复制；微信已登录时不会再次要求扫码。若尚未设置通知接收者，只会等待接收微信号发消息完成配对。
- 选择 `7` 时，只安装缺少的系统包；Python 依赖和 Chromium 完整时也会跳过。

只有需要从仓库更新 Web 程序文件时，才显式使用强制更新命令。它会保留账号、Cookie、数据库和网页端已修改的管理员密码：

```bash
cd /root/douyin-fire-desk
git pull
sudo bash install.sh --force --with-openclaw
```

## 不用一条命令时

大陆服务器：

```bash
git clone --depth 1 https://gitee.com/gongyu2006/douyin-fire-desk.git
cd douyin-fire-desk
sudo bash gongyu.sh
```

海外服务器：

```bash
git clone --depth 1 https://github.com/FelixGoh06/douyin-fire-desk.git
cd douyin-fire-desk
sudo bash gongyu.sh
```

主菜单的 `1` 会自动安装缺失的 OpenClaw 并执行微信接入；不再要求你手填 channel、target 或手动复制 Skill。

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

Ubuntu/Debian 启用 UFW 时：

```bash
sudo ufw allow 8787/tcp
```

Rocky、AlmaLinux、RHEL、CentOS Stream、Fedora 或 openEuler 启用 firewalld 时：

```bash
sudo firewall-cmd --permanent --add-port=8787/tcp
sudo firewall-cmd --reload
```

## 更新与卸载

更新：

```bash
cd /root/douyin-fire-desk
git pull
sudo bash install.sh --force --with-openclaw
```

卸载服务但保留数据：

```bash
sudo bash /opt/douyin-fire-desk/scripts/uninstall.sh
```

彻底清除账号、Cookie、浏览器 Profile、数据库与配置：

```bash
sudo bash /opt/douyin-fire-desk/scripts/uninstall.sh --purge
```
