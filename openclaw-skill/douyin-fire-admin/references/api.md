# API 操作参考

## 查询与实时检查

- `overview`: 账号、任务、目标好友与调度概览，目标状态可能是历史缓存。
- `report --hours 24`: 执行汇总；目标包含 `last_checked_at` 和 `renewal_evidence`。
- `check-target --nickname "昵称"`: 发起新的检查并等待完成，用于回答某个好友今天是否续火。
- `check-all-targets`: 创建一个检查批次，串行执行所有启用任务并等待完成，用于回答全部好友今天的实时火花情况；结果按未续、未知、已续排序。
- `run-all --type send`: 创建一个发送批次，执行所有启用任务；完成后产生一条汇总通知。
- `GET /api/openclaw/runs/{run_id}`: 返回指定执行记录、逐好友 `contacts` 证据和是否已结束。

实时问题必须使用 `check-target`。`unknown` 表示无法判断，不能解释为未续。

所有修改通过：

```bash
python3 scripts/fire_admin.py command ACTION --data 'JSON'
```

## 账号与 Cookie

- `account.create`: `name`，可选 `cookie_value`、`enabled`、`timezone`、`target_url`、`notes`
- `account.update`: `account_id`，以及需修改的账号字段
- `account.toggle`: `account_id`
- `account.delete`: `account_id`
- `account.check` / `cookie.check`: `account_id`
- `cookie.check-all`: 无字段
- `cookie.update`: `account_id`、`cookie_value`；使用 `clear_cookie: true` 清空

## 任务

- `task.create`: `account_id`、`name`；可选 `enabled`、`send_time`、`night_check_enabled`、`night_check_time`、`timezone`、`message_template`、`retry_count`、`timeout_seconds`、`notes`、`targets`
- `task.update`: `task_id`，以及需修改的任务字段
- `task.toggle`: `task_id`
- `task.delete`: `task_id`
- `task.run`: `task_id`，可选 `task_type=send|night_check`
- `task.check`: `task_id`
- `task.run-all`: 无必填字段，可选 `task_type=send|night_check`
- `task.check-all`: 无字段，默认检查所有启用任务

批次命令返回 `batch_id` 和 `runs`。批次中的单个任务不会逐条产生完成通知，所有执行结束后只生成一个 `task_batch_completed` 汇总通知。

`targets` 可为昵称数组，也可为对象数组：

```json
[
  {"nickname":"陈科宏","enabled":true,"message_template":"续火"}
]
```

## 目标好友

- `target.create`: `task_id`、`nickname`；可选 `douyin_user_id`、`enabled`、`message_template`
- `target.update`: `target_id`，以及需修改的字段
- `target.toggle`: `target_id`
- `target.delete`: `target_id`

时间字段固定使用 `HH:MM`，时区默认 `Asia/Shanghai`。
