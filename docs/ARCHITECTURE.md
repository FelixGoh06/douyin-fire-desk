# 架构

```text
Browser -> Nginx (public port) -> FastAPI (127.0.0.1:7788)
                                      |
                                      +-> SQLite + encrypted Cookie
                                      +-> APScheduler -> Playwright/Chromium -> Douyin Web
                                      +-> local OpenClaw control API
                                                        |
OpenClaw Skill + notifier runtime ----+-> batch notifications -> OpenClaw channel
                  (systemd timer or container loop)
```

## 组件职责

- **FastAPI**：管理页面、账号/任务 CRUD、执行记录和本机控制 API。
- **SQLite**：保存任务、目标好友、运行记录、加密 Cookie 和通知队列。
- **APScheduler**：按任务时间运行续火、晚间检查与 Cookie 健康检查；同时间规则聚合为批次。
- **Playwright/Chromium**：使用独立浏览器 Profile 执行网页动作和识别。
- **OpenClaw Skill**：调用本机 token API，查询与执行真实任务，禁止读取 Cookie 明文。
- **Notifier runtime**：每分钟拉取已聚合的后台通知，调用配置的 OpenClaw channel 发送；普通主机用 systemd timer，缺少 systemd 的容器用后台循环。

## 数据流

1. 用户在 Web 页面保存账号与任务。
2. 调度器到点生成运行记录并交给浏览器执行器。
3. 浏览器执行结果写入实时日志和数据库。
4. 同一时间段的结果合并为一个通知记录。
5. OpenClaw notifier 读取未投递通知并发送一条汇总。

Web API 和 OpenClaw API 使用不同认证路径。公网 Nginx 配置拒绝 OpenClaw API，避免 Agent Token 暴露到公网。
