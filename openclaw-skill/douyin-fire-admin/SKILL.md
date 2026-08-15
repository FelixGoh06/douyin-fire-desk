---
name: douyin-fire-admin
description: 管理抖音续火后台的账号、Cookie 健康、定时任务、目标好友、发送与晚间火花检查，并生成执行日报或增量通知。用户提到续火、火花、抖音任务、Cookie 检测、执行任务、检查对方是否续火、添加或修改后台任务时使用。
---

# 抖音续火后台

通过 `scripts/fire_admin.py` 调用本机受令 API。始终读取真实后台数据，不根据聊天记忆猜测账号、任务 ID 或昵称。

## 常用操作

```bash
python3 scripts/fire_admin.py overview
python3 scripts/fire_admin.py report --hours 24
python3 scripts/fire_admin.py check-target --nickname "宝贝"
python3 scripts/fire_admin.py check-all-targets
python3 scripts/fire_admin.py run-all --type send
python3 scripts/fire_admin.py run --task-id 2 --type send
python3 scripts/fire_admin.py run --task-id 2 --type night_check
python3 scripts/fire_admin.py cookie-check --account-id 1
python3 scripts/fire_admin.py cookie-check-all
```

增删改使用统一命令，参数放进 JSON：

```bash
python3 scripts/fire_admin.py command task.create --data '{"account_id":1,"name":"每天给小号续火","send_time":"09:00","targets":["小号"]}'
python3 scripts/fire_admin.py command task.update --data '{"task_id":2,"send_time":"10:30","night_check_enabled":true}'
python3 scripts/fire_admin.py command target.update --data '{"target_id":3,"nickname":"新昵称"}'
python3 scripts/fire_admin.py command cookie.update --data '{"account_id":1,"cookie_value":"..."}'
```

完整 action 与字段见 [references/api.md](references/api.md)。

## 工作规则

- 先运行 `overview`，再按返回的真实 ID 操作。
- 用户问“某个好友今天续没续”“现在的火花情况”等实时问题时，必须运行 `check-target --nickname "准确昵称"`。该命令会发起新的晚间检查并等待本次结果；禁止直接用 `overview`、`report`、聊天记忆或旧消息回答实时状态。
- 用户只说“晚间检查”“检查火花情况”而没有明确昵称时，默认检查所有启用好友，必须运行 `check-all-targets`。用户问“今天他们都续了吗”“所有人的火花情况”等全量实时问题时也执行该命令，等待整批检查结束后再汇总。回答前确认 `expected_count == returned_count == answer_rows` 的条目数，并把 `answer_rows` 中每个人恰好列出一次；结果按未续、未知、已续排序，不要用日报缓存冒充实时结果。
- 只根据 `check-target` 返回的 `result.renewal_status` 回答：`renewed` 是已续，`not_renewed` 是未续，`unknown` 只能说无法判断。`unknown` 绝不等于未续。
- `last_fire_days`/`fire_days` 只是最近识别到的火花天数，不能证明对方今天是否续火。回答时同时说明 `checked_at`；命令返回 `waiting`、执行失败或没有目标结果时，明确说实时检查尚未得到结论。
- 用户只说“续火”“执行今天的续火”而没有明确好友或任务时，默认运行 `run-all --type send`，把所有启用任务作为一个批次执行。不要逐个好友回复排队或完成消息，等整批执行完成后的自动汇总通知。
- 明确指定单个好友或任务时才执行单任务。普通执行后说明已进入队列；自动通知必须按批次汇总，禁止一人一条连续推送。
- Cookie 只能写入，不能读取明文。不要在回答里复述用户提供的 Cookie。
- 删除账号、任务、好友，或清空 Cookie 前，必须让用户明确确认对象和动作。
- 修改昵称、时间、消息模板等可恢复配置时，执行后重新运行 `overview` 验证。
- 工具输出 JSON；回答时转换成简洁中文，不直接倾倒整段 JSON。

## 自动汇报

增量通知：

```bash
python3 scripts/fire_admin.py notifications --commit
```

返回 `status=no_changes` 时只回复 `NO_REPLY`。有批次通知时只发送一条汇总：晚间检查按未续、未知、已续排序；续火发送按失败、成功排序。Cookie 失效或缺失必须单独突出。

日报使用 `report --hours 24`，至少包含：执行总数、成功/失败、发送结果、晚间检查结果、各账号 Cookie 状态。引用缓存目标状态时必须带 `last_checked_at`；当天没有检查时间的目标只能标记“尚未完成今日检查”，不能推断已续或未续。
