---
name: wechat-local
description: 查询、导出、分析本机微信聊天记录——按关键词/时间/群聊/联系人检索消息，导出 markdown，从群通知里提取待办、作业、截止日期、活动原文。当用户提到查微信消息、翻群通知、导出聊天记录、搜某个通知/任务（如手抄报、学籍表、报名截止）、分析对话、生成待办清单时使用；即使没说"微信"二字，只要涉及本机聊天记录、班级群/私聊内容都适用。
---

# 本机微信数据分析（wechat-local）

数据全在本机、纯离线解密，微信**不需要关闭**。核心是一个已配置好的 CLI 包装器和一个解密缓存。

## 环境事实（先记住这些路径）

| 东西 | 位置 |
|---|---|
| CLI 快捷命令 | `~/.wechat-cli/wxcli.cmd`（cmd/git-bash 均可直接调用） |
| 工具本体+依赖 | `~/.wechat-cli/tool/` + `~/.wechat-cli/deps/`（含 psutil、pycryptodome、zstandard、click） |
| 解密密钥 | `~/.wechat-cli/all_keys.json`（由 `wxcli init` 自动生成；失效处理见下文「维护」） |
| DB 配置 | `~/.wechat-cli/config.json` |
| 解密缓存 | `%TEMP%\wechat_cli_cache\`（按 mtime 自动失效重建，被系统清理也无妨） |
| 微信数据目录 | `wxcli init` 自动探测（记录在 `~/.wechat-cli/config.json` 的 db_dir） |
| 自己的 wxid | 运行 `wxcli sessions` 查看自己的 username |
| 历史分析脚本 | 可选，见上游项目 wechat-cli-plus 文档 |
| 待办工作流产出 | 由 wechat-todo skill 的用户工作区决定（见该 skill 首次引导） |

## 快速命令

```bash
# 最近会话（含未读、最后一条消息）
~/.wechat-cli/wxcli.cmd sessions --limit 30

# 某会话的消息（支持 --start-time/--end-time/--limit/--offset/--format json|text）
~/.wechat-cli/wxcli.cmd history "绯鸦FEily" --limit 100 --format text
~/.wechat-cli/wxcli.cmd history "某个群名" --start-time "2026-09-26" --end-time "2026-09-30"

# 导出为 markdown 文件（分析/存档用）
~/.wechat-cli/wxcli.cmd export "群名" --start-time "2026-09-01" --format markdown --limit 5000 --output out.md

# 关键词搜索（⚠️ 有盲区，见下节）
~/.wechat-cli/wxcli.cmd search "关键词" --limit 50

# 联系人 / 单会话统计 / 未读
~/.wechat-cli/wxcli.cmd contacts --query "李"
~/.wechat-cli/wxcli.cmd stats "群名"
~/.wechat-cli/wxcli.cmd unread
```

会话名直接用 `wxcli sessions` 返回的显示名，或 wxid/chatroom id 均可。

## ⚠️ 最大的坑：压缩消息搜不到

微信 4.x 的很多通知是 **zstd 压缩存储**（`WCDB_CT_message_content=4`），`search` 命令对它们**完全失明**——曾因此差点漏掉一条中秋手抄报通知。凡涉及"搜通知/找原文"，必须用解压检索脚本：

```bash
python <skill目录>/scripts/search_all.py 手抄报
python <skill目录>/scripts/search_all.py 中秋 --context   # 附上下文前后各3条
```

它直接读解密缓存，明文+压缩全覆盖，输出 `表名 lid 时间 发送者 内容`。

## 深度分析（直接查解密后的 SQLite）

需要聚合统计、跨会话提取时，直接用 Python 打开缓存库（只读）：

1. 拿解密库路径：`from wechat_cli.core...` 或读 `%TEMP%\wechat_cli_cache\_mtimes.json`（rel_key→path 映射）；缓存过期就先跑一次任意 wxcli 命令让它重建。
2. 库结构（message_0.db）：
   - 每个会话一张表 `Msg_<md5(会话username)>`；`Name2Id(rowid→user_name)`，`real_sender_id` = Name2Id rowid
   - 消息列：`local_type, create_time, message_content, compress_content, packed_info_data, WCDB_CT_message_content`
   - 解压：`zstandard.ZstdDecompressor().decompress(bytes)`，`ct==4` 才需要
   - 类型码：低32位=基础类型（1文本3图片47表情10000系统…），高32位=子类型（49系看 appmsg `<type>`：5链接6文件19合并记录33小程序53接龙57引用2000转账）；解析参考 `~/.wechat-cli/tool/wechat_cli/core/messages.py`
3. 会话名↔username↔表名互查：`contact.db` 的 `contact(username, remark, nick_name)`；群聊 username 形如 `58740406937@chatroom`
4. 参考实现：`<workspace>/wechat_analysis/analyze.py`（全局统计报告的完整写法，含解密缓存加载模板）

## 图片 / 媒体

- 图片在 `msg/attach/<md5(会话username)>/<YYYY-MM>/Img/<hash>.dat`，hash 取自消息表 `packed_info_data`（二进制里可见32位hex）
- `.dat` 是微信 V2 加密（头 `07 08 56 32 08 07` + aes_size/xor_size，前1KB AES-128-ECB + 尾部单字节异或，xor_key 可由 `_t.dat` 尾两字节 vs FFD9 推出）
- **本地密钥提取：已试尽，判定当前不可行**（2026-09-30 结论）：
  - 磁盘 1568 万 + 5 进程内存 2456 万候选（[A-Za-z0-9] 滑窗 + UTF-16，多模板严格校验）全部落空 → 密钥**不是 ASCII 字符串**（大概率是原始二进制或运行时派生），模式匹配路线到头了
  - ⚠️ 教训一：单模板 3 字节 FFD8FF 校验在千万级候选下**必出假阳性**（曾"找到"C0AD52FE00902A1D，解出非法头 `ffd8ff29`，已废弃删除）
  - ⚠️ 教训二：图片 XML 里的 `aeskey` 是 CDN 下载密钥，不是本地解密密钥（试过，无效）
  - `find_image_key.py` 保留在 workspace 供未来微信版本再战；若哪天它输出 `image_key.json` 则解密自动完成
- **读图的实用路径（2026-10-06 实测更新，按优先级）**：
  1. **明文缓存（免密钥，先查这里）**：`xwechat_files/wxid_.../cache/<YYYY-MM>/Message/<md5(会话username)>/`
     - `Thumb/<msgid>_<epoch>_thumb.jpg` 明文缩略图（120px 居多认内容用；也有 540x720/2400x426 能读字）
     - `ImageTemp/<msgid>_<epoch>_mid_temp_convert` 明文中图（无扩展名，JPEG/PNG/wxgf，最大 1920x1080，读文字优先找它）
     - 微信渲染过就落盘；文件名时间戳可对回消息
  2. **内存抠图（免密钥，图没缓存时用）**：`<workspace>/wechat_analysis/mem_carve.py` → 扫 Weixin.exe 可读内存按 FFD8/IEND 抠图 → `carved/ok/`（Pillow 全解码校验过的）。2026-10-06 实测 1.9GB 内存抠出 105 张真图。**要读某张特定图：先在微信里点开它再跑**（加载过才在内存里）
  3. 通知先试 `search_all.py`——很多"图片通知"其实带压缩正文，根本不用看图
  4. 兜底：请用户在微信里右键另存/截图发过来
- **原图 .dat 仍不可解**（2026-10-06 复核）：微信 4.1.15.13 ≥ 4.0.3.36（chatlog FAQ：该版本起密钥不再驻留内存）；4425 个 .dat 全是 `07 08 56 32` 新格式（社区 dat2img 标 FIXME），DB 密钥/salt 试过无效；唯一能取图片密钥的 wx_key 工具 10-05 被 DMCA 下架。AES 密钥候选验证：模板 = 任意 `_t.dat` 的 `data[15:31]`，解密首块须为 FFD8FF+合法 marker，多模板全过才算
- 视频无加密（mp4）；文件消息（type49 sub6）文件名在 appmsg `<title>`，磁盘 `msg/file/<YYYY-MM>/<title>` 直接可取

## 提取待办工作流（群通知 → 可勾选清单）

成熟模板（曾产出完整的「消息代办」文件夹）：

1. 圈定会话和时间窗 → `export` 各会话为 markdown（原始记录留档）
2. 用 `search_all.py` 扫关键词补盲（任务词、活动词、截止、报名、交、填）
3. 逐条读导出文件，区分：**待办（带截止日期）/ 已完成 / 作废（群里被澄清误传的）/ 纯通知**
4. 产出结构：`今日待办.md`（勾选清单，滚动到当天）+ `待办总表.md`（按截止排序）+ `日期纪要/` + `原始消息/`，markdown 复选框 `- [ ]` / `- [x]`
5. 注意力清单：@所有人 后无正文的 = 待跟进；「误传/发错了/不要报名」= 作废项单独标红；同一活动多次改期的取最新

## 维护

- **密钥失效**（报 key 相关错误或解密出乱码）：微信保持运行 → `~/.wechat-cli/wxcli.cmd init`（会从进程内存重新提取）
- **换电脑/重装微信**：同上 init；config.json 的 db_dir 会自动探测
- 工具源码自带零网络请求（曾核验），数据不出本机
- 若 wxcli 本身坏了：工具是普通 Python 包，`PYTHONPATH=~/.wechat-cli/tool;~/.wechat-cli/deps python ~/.wechat-cli/tool/entry.py <子命令>` 等价

更细的命令参数见 `references/commands.md`；解压检索脚本在 `scripts/search_all.py`。
