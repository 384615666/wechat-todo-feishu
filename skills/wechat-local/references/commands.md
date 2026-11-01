# wxcli 命令参考（wechat-cli-plus 0.2.4）

包装器：`~/.wechat-cli/wxcli.cmd`（等价 `PYTHONPATH=tool;deps python tool/entry.py <cmd>`）
输出：默认 JSON（可读性好），`history` 支持 `--format text`。

## init
```bash
wxcli.cmd init        # 提取/重建密钥（微信须在运行）；key 失效时先跑这个
```

## sessions — 最近会话
```bash
wxcli.cmd sessions                 # 全部，按最后消息时间倒序
wxcli.cmd sessions --limit 30
```
字段：chat(显示名), username, is_group, unread, last_message, msg_type, sender, timestamp, time

## history — 单会话消息
```bash
wxcli.cmd history "显示名或wxid" [选项]
  --limit N          条数（默认50）
  --offset N         分页
  --start-time "YYYY-MM-DD [HH:MM[:SS]]"
  --end-time   "YYYY-MM-DD [HH:MM[:SS]]"
  --format json|text
  --type text|image|voice|video|sticker|location|link|file|call|system
  --media            解析媒体文件的磁盘路径（图片/文件/视频/语音）
```

## export — 导出为文件
```bash
wxcli.cmd export "会话名" [选项]
  --format markdown|txt     （默认 markdown）
  --output 路径.md
  --start-time / --end-time / --limit（默认500，大群给5000）
```
markdown 格式：头部含时间范围/条数，正文每行 `- [YYYY-MM-DD HH:MM] 发送者: 内容`，多行内容续行缩进，引用消息带 `↳ 回复 某人:`。

## search — 关键词搜索 ⚠️有盲区
```bash
wxcli.cmd search "关键词" [--limit N] [--offset N] [--chat 限定会话]
```
**压缩消息（zstd）搜不到** —— 找通知/原文一律改用本 skill 的 `scripts/search_all.py`。
返回 JSON：scope, count, results[]（每条是格式化字符串）, failures[]。

## contacts — 联系人
```bash
wxcli.cmd contacts                    # 全部
wxcli.cmd contacts --query "李"        # 过滤
```

## stats — 单会话统计（需要 CHAT_NAME 参数）
```bash
wxcli.cmd stats "会话名"
```

## unread — 未读会话
```bash
wxcli.cmd unread
```

## new-messages — 增量新消息（轮询场景）
```bash
wxcli.cmd new-messages
```

## members / favorites
```bash
wxcli.cmd members "群名"     # 群成员
wxcli.cmd favorites          # 收藏
```

## 常见组合

```bash
# 某群近3天全部消息导出后人工读
wxcli.cmd export "【班群】马院2601班" --start-time "2026-09-26" --limit 5000 --output 班群.md

# 全局找某人发的通知（注意压缩盲区，配合 search_all.py）
wxcli.cmd search "截止" --limit 30
python <skill>/scripts/search_all.py 截止 --context 1
```

## 错误速查

| 现象 | 处理 |
|---|---|
| `密钥文件不存在` | `wxcli.cmd init`（微信运行中） |
| 解密输出乱码/报 key 错 | 同上，重建 `~/.wechat-cli/all_keys.json` |
| `找不到聊天对象` | 用 `sessions` 核对显示名；或直接给 username/wxid |
| `解密缓存缺失`（search_all.py） | 先跑 `wxcli.cmd sessions` 触发一次解密 |
| wxcli 无响应/被占用 | 微信正在写库，稍等重试；或关闭微信再跑 |
