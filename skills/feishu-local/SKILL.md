---
name: feishu-local
description: 查询、导出、分析本机飞书（Lark）聊天记录——枚举会话、按时间窗拉取群聊/私聊消息、跨会话关键词搜索、下载消息里的图片文件、批量导出 markdown。当用户提到查飞书消息、翻飞书群通知、导出飞书聊天记录、搜飞书里的某条通知/文件、从飞书群里提取待办与截止日期、把飞书消息并入待办汇总时使用；即使没说"飞书"二字，只要涉及 lark-cli、飞书群/私聊内容都适用。
---

# 本机飞书聊天数据（feishu-local）

飞书**没有**微信那种本地可解密数据库：消息在服务端，读法是走 OpenAPI。本机 `lark-cli` 已用你的**用户身份**登录，因此能读到「你在飞书客户端里能看到的全部会话与消息」——等价于你自己翻聊天记录，只是批量、可脚本化。

> 一句话：微信靠本地解密，飞书靠 OpenAPI + 本机登录态。数据只落本机，不上传任何第三方。

## 环境事实（先记住这些）

| 东西 | 位置 / 值 |
|---|---|
| CLI | `lark-cli`（`%APPDATA%\npm\lark-cli.cmd`，PATH 里直接用） |
| 登录态 | `lark-cli auth status --json --verify`（`--as user` 用你的 user_access_token） |
| 身份要求 | **一律 `--as user`**。bot 身份只能看机器人被拉进的群，且 sender 语义不同 |
| user token | 约 2h 有效、refresh token 约 7 天；被自动刷新，长期不用需 `lark-cli auth login` 重新设备码授权 |
| 批量导出脚本 | `<skill目录>/scripts/feishu_export.py` |
| 导出产物 | `<工作区>/原始消息/飞书/<日期窗>/<会话名>.md` + `_messages.json` + `_summary.md` |

## 快速命令

```bash
# 1) 我加入的会话（默认只有群；p2p 必须用户身份）
lark-cli im +chat-list --as user --types=group --page-all --page-limit 20
lark-cli im +chat-list --as user --types=p2p,group --sort=active_time --format json

# 2) 某会话的消息（时间窗 + 翻页 + 升序）
lark-cli im +chat-messages-list --as user --chat-id oc_xxx \
  --start 2026-11-01T00:00:00+08:00 --end 2026-11-03T23:59:59+08:00 \
  --order asc --page-size 50 --page-all --page-limit 20 --format json

# 3) 私聊：可直接给对方的 open_id
lark-cli im +chat-messages-list --as user --user-id ou_xxx --page-size 50 --format json

# 4) 跨会话关键词搜索（找"截止/报名/周会"这类）
lark-cli im +messages-search --as user --query "周会" --page-all --page-limit 5

# 5) 只看人话（省的自己渲染）
lark-cli im +chat-messages-list --as user --chat-id oc_xxx --page-size 20 --concise

# 6) 下载消息里的图片/文件
lark-cli im +chat-messages-list --as user --chat-id oc_xxx --page-size 20 --download-resources

# 7) 批量导出（推荐入口）
python <skill目录>/scripts/feishu_export.py --hours 24
python <skill目录>/scripts/feishu_export.py --days 3 --types=p2p,group --name-match 项目
python <skill目录>/scripts/feishu_export.py --start 2026-11-01T00:00:00+08:00 --end 2026-11-03T12:00:00+08:00 --download-resources
```

`chat_id` 形如 `oc_xxx`，`user_id` 形如 `ou_xxx`，`message_id` 形如 `om_xxx`。会话名→chat_id 用 `+chat-list` 或 `+chat-search --query 群名`。

## ⚠️ 踩过的坑（照抄，别重新踩）

1. **时间必须带冒号的 ISO 8601**：`2026-11-01T00:00:00+08:00` ✅，`2026-11-01T00:00:00+0800` ❌（报 `--start: cannot parse time`）。
2. **`--types` 要用 `=` 形式**：`--types=p2p,group` ✅。写成 `--types p2p,group` 时 PowerShell 会拼成 `"p2p group"` 再报 `invalid value`。
3. **失败信息走 stderr、stdout 为空**：`ok:false` 的 JSON 信封在 **stderr**。脚本里先读 stdout，空了再解析 stderr，否则只能看到空错误。
4. **`--page-all` 必须配 `--page-limit`**（默认 10 页），每页最多 50 条；翻页间隔用 `--page-delay 200` 防限流。
5. **历史可见范围 = 你在客户端能翻到的范围**：受群设置/租户策略限制（比如"新成员可见历史"关闭的群，你入群前的消息读不到；离职/被移出后也读不到）。这不是"企业全量聊天"，也读不到别人私聊。
6. **机器人私聊别一刀切排除**：`审批` / `任务助手` / `云文档助手` / `多维表格助手` 这些 p2p 里全是待办线索（审批通过、任务派发、报表）。`--exclude-bots` 只是可选开关。
7. **卡片消息（`interactive`）**：`content` 已被压成 `<card title=...>...</card>` 的 markdown 文本，直接可读，不用解 JSON。
8. **`post`（富文本）**：`content` 已是扁平 markdown（含 `![Image](img_key)`），无需二次解析。
9. **系统/服务消息多**：`msg_type` 为 `system`、`video_chat` 的（"Meeting has started"、视频会议卡片）一般不含待办，判读时略过。
10. **附件是 `file_key`/`img_key`，不是本地文件**：要落地必须 `--download-resources`（落到 `./lark-im-resources/`）或 `+messages-resources-download`；文件夹型资源要先 `im files folder --recursive` 展开。

## 提取待办工作流（飞书侧）

1. **定窗口**：读工作区 README 的「数据截至（飞书）」，取上一次导出时间到现在。
2. **全量扫，不预设名单**：`feishu_export.py --days N` 枚举**全部**会话并在窗口内拉消息（新拉的群、临时私聊都在内，防漏）。
3. **补盲**：对关键词（截止/报名/审批/周会/交付/上线/明天/本周）跑 `+messages-search`，覆盖导出漏掉的边角。
4. **判读**：别人私聊直接交代的 > 群里 @我/指名的 > 泛群通知；飞书里的「审批抄送」「任务派发」「@所有人」是高频待办源；卡片消息要点出**标题和关键字段**（时间、金额、单号）。
5. **去重**：与微信侧、飞书台账、飞书任务三处比对，同一件事只留一条，来源标注 `飞书/<会话名>` 或 `微信/<会话名>`。
6. **归档**：导出文件留在 `原始消息/飞书/<日期窗>/`，附件按原有归档规则分类。

## 维护

- **token 过期 / `auth status` 显示 needs_refresh 且刷新失败**：`lark-cli auth login`，按提示完成设备码授权（10 分钟内）。
- **报权限/scope 不足**：飞书消息读取依赖 `im:message:readonly`、`im:chat:read`、`im:chat.members:read`、`search:message`。缺就如实上报所缺 scope，不要换 bot 身份绕过（会读出不同结果）。
- **`lark-cli update`**：升级后 shortcut 名可能变化，先 `lark-cli im --help` 确认。
- 想确认某接口的参数结构：`lark-cli schema im.messages.list`；高阶 shortcut 用法：`lark-cli im +chat-messages-list --help`。

更细的命令/字段说明见 `references/commands.md`；批量导出脚本在 `scripts/feishu_export.py`。
