<!-- DOUYIN-FIRE-REALTIME-POLICY:BEGIN -->
## 抖音续火实时查询强制规则（CRITICAL）

任何包含“续火”“火花”“今天续了吗”“他们都续了吗”“谁没续”等状态查询的问题，都必须遵守：

1. 禁止根据聊天历史、记忆、旧 `overview`、旧 `report` 或 `notifications` 推断当前状态。
2. 先读取 `douyin-fire-admin/SKILL.md`，再从 Skill 根目录执行 `python3 scripts/fire_admin.py ...`。
3. 查询单个好友时执行 `python3 scripts/fire_admin.py check-target --nickname "准确昵称"`。
4. 用户没有明确昵称，只说“晚间检查”“检查火花情况”，或查询全部、他们、所有人时，默认执行 `python3 scripts/fire_admin.py check-all-targets`。
5. 全量回答前必须确认 `expected_count == returned_count == answer_rows` 条目数，并把 `answer_rows` 中每个人恰好列出一次。人数不相等时禁止给出结论，只能报告数据不完整。
6. 只引用本次命令输出。`unknown`、结果缺失、执行失败只能说“尚未确认”，绝不能说“未续”。
7. 不得主动提议发送消息；只有用户明确要求发送时才执行发送任务。
8. 用户明确要求“续火”但没有指定好友或任务时，默认执行 `python3 scripts/fire_admin.py run-all --type send`。整批完成后只汇总一次，禁止逐个好友连续回复。
<!-- DOUYIN-FIRE-REALTIME-POLICY:END -->
