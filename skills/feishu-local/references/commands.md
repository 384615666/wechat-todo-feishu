# 飞书消息命令速查（lark-cli，用户身份）

所有命令都建议显式 `--as user`。输出默认 `--format json`；`--jq '<expr>'` 可在输出前过滤，`--dry-run` 只打印请求。

## 1. 会话枚举 `im +chat-list`

| 参数 | 说明 |
|---|---|
| `--types=p2p,group` | 会话类型；**省略 = 只有群**。`p2p` 仅用户身份可用 |
| `--sort=active_time` | 最近活跃排序（默认 `create_time`） |
| `--page-size 100` `--page-all` `--page-limit 20` `--page-delay 200` | 翻页三件套 |
| `--exclude-muted` | 过滤被静音的会话（用户身份） |
| `--name` 无 | 按名字找会话用 `+chat-search --query 群名` |

返回每个会话：`chat_id`、`name`、`chat_mode`（`group`/`p2p`）、`chat_app_link`、`p2p_target_id`、`p2p_target_type`（`user`/`bot`）、`external`、`owner_id`。

## 2. 拉消息 `im +chat-messages-list`

| 参数 | 说明 |
|---|---|
| `--chat-id oc_xxx` / `--user-id ou_xxx` | 二选一；私聊给 `--user-id` 会自动解析 chat_id |
| `--start` / `--end` | ISO 8601，**必须带冒号时区** `2026-11-01T00:00:00+08:00` |
| `--order asc\|desc` | 升序适合阅读/导出，降序适合"最近几条" |
| `--page-size 50` `--page-all` `--page-limit 20` `--page-delay 200` | 翻页；单页上限 50 |
| `--concise` | 直接输出紧凑 markdown（含参与人、时间轴），省自己渲染 |
| `--no-reactions` | 不附带表情回应（导出时更快） |
| `--download-resources` | 下载图片/文件到 `./lark-im-resources/`，并在消息上回填 `resources[]` |

单条消息结构（JSON）：`message_id`、`create_time`（`YYYY-MM-DD HH:MM`）、`msg_type`、`content`、`sender{id,name,sender_type,sender_i18n_names}`、`thread_id`、`updated/update_time`、`deleted`、`message_app_link`、`reactions`。

`msg_type` 常见值：`text`、`post`（富文本，content 已是扁平 markdown）、`image`、`file`、`audio`、`media`、`sticker`、`interactive`（卡片，content 为 `<card>…</card>` 文本）、`share_chat`、`share_user`、`merge_forward`（合并转发）、`system`、`video_chat`。

## 3. 跨会话搜索 `im +messages-search`

```bash
lark-cli im +messages-search --as user --query "报名截止" --page-all --page-limit 5
lark-cli im +messages-search --as user --query "上线" --chat-id oc_xxx --format json
```

支持 `--query`、`--chat-id`、`--sender`、时间范围、附件过滤；结果会自动用 mget 补全正文。依赖 `search:message` scope。**注意**：只能搜到你有权限的会话，且服务端索引有延迟（刚发的消息可能搜不到）——所以"补盲"要和 `+chat-messages-list` 全量扫配合，不要只靠搜索。

## 4. 按 ID 批量取 `im +messages-mget`

```bash
lark-cli im +messages-mget --as user --message-ids om_aaa,om_bbb   # 一次最多 50 个
```

## 5. 附件下载 `im +messages-resources-download`

```bash
lark-cli im +messages-resources-download --as user \
  --message-id om_xxx --file-key img_v3_xxx --type image --output ./out/img.jpg
```

文件夹型资源先展开：`lark-cli im files folder --recursive --file-key fld_xxx --srctype message --srcid om_xxx`。

## 6. 查接口定义 / 文档

```bash
lark-cli im --help                      # 全部 shortcut 与原生资源
lark-cli im +chat-messages-list --help  # 单个命令的全部参数与风险级别
lark-cli schema im.messages.list        # 原生 API 的 --params/--data 结构
lark-cli skills read lark-im            # 内嵌的飞书 IM 能力说明（含 lark-shared 认证篇）
```

## 7. PowerShell 下的引号陷阱

`lark-cli` 的 `.ps1` 包装器会吞掉嵌套双引号：

- JSON 类参数用 `@file` 传：`--data '@C:\path\payload.json'`
- `--types=p2p,group` 用等号形式，别用空格分隔
- 输出到文件用 `| Out-File -Encoding utf8`，失败信封在 **stderr**（`2>&1` 合并后注意位置）

## 8. 批量导出（本 skill 脚本）

```bash
python <skill目录>/scripts/feishu_export.py --hours 24
python <skill目录>/scripts/feishu_export.py --days 7 --out 原始消息/飞书 --types=p2p,group
python <skill目录>/scripts/feishu_export.py --chat-id oc_89eb67bef9a8d8de977ebbf8dce4be31 --days 2
python <skill目录>/scripts/feishu_export.py --dry-run            # 只看会扫哪些会话
python <skill目录>/scripts/feishu_export.py --exclude-bots --name-match 湖南
```

产物：

```
<out>/<日期窗>/
├── <会话名>.md         # 每会话一份，含时间、发送人、类型、正文、附件、thread
├── _messages.json      # 结构化（供 triage 脚本读）
└── _summary.md         # 会话清单、消息数、参与人、失败列表
```

退出码：`0` 全部成功；`1` 有个别会话读取失败（`_summary.md` 里能看到原因）；`2` 参数/环境错误。
