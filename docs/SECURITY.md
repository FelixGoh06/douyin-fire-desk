# 安全说明

## 敏感数据位置

| 内容 | 默认位置 | 处理方式 |
| --- | --- | --- |
| 后台账号、会话密钥、Cookie 加密密钥、Agent Token | `/etc/douyin-fire-desk.env` | `0600`，仅 root 可读 |
| OpenClaw 本机 API Token | `/etc/douyin-fire-desk-agent.env` | `0640`，仅 root 与 `douyin-fire-agent` 组可读 |
| OpenClaw 渠道与收件人 | `/etc/douyin-fire-desk-openclaw.env` | `0600`，仅 root 可读 |
| 加密后的 Cookie 与业务数据 | `/var/lib/douyin-fire-desk/admin.db` | 仅 `douyin-fire` 服务用户可写 |
| 浏览器登录 Profile | `/var/lib/douyin-fire-profiles/` | 仅 `douyin-fire` 服务用户可写 |

任何 Cookie、Token、Profile、数据库、环境文件、个人聊天截图都不应提交到 GitHub、发到 Issue 或粘贴到聊天中。

## 网络边界

- FastAPI 只监听 `127.0.0.1:7788`。
- Nginx 在公网端口转发 Web 页面。
- `/api/openclaw/` 被 Nginx 显式拒绝；OpenClaw 只通过服务器本机访问。
- 在云安全组中只放行你实际使用的端口；可进一步限制为自己的固定 IP。
- 仅 IP 访问也应使用强管理员密码。长期使用建议配域名、HTTPS 和 `SESSION_SECURE=1`。

## 备份

停服务后再备份，且只将备份保存到受信任的加密位置：

```bash
sudo systemctl stop douyin-fire-desk.service
sudo tar -czf douyin-fire-desk-backup.tgz /etc/douyin-fire-desk.env /var/lib/douyin-fire-desk /var/lib/douyin-fire-profiles
sudo systemctl start douyin-fire-desk.service
```

恢复时保持文件权限和所有者：

```bash
sudo chown -R douyin-fire:douyin-fire /var/lib/douyin-fire-desk /var/lib/douyin-fire-profiles
sudo chmod 600 /etc/douyin-fire-desk.env
```

## 漏洞报告

请不要在公开 Issue 披露可被利用的安全细节或真实凭据。使用 GitHub 私密安全报告功能，或先移除所有敏感信息后描述复现步骤。
