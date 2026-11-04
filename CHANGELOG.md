# 更新日志

本项目的版本按 [语义化版本](https://semver.org/lang/zh-CN/) 编号。安装/更新方式：重跑 `node bin/wechat-todo-feishu.js`。

## v1.1.0 — 2026-11-04

### 新增

- **`feishu-local` skill**：飞书聊天记录查询、导出、检索（走本机已登录 `lark-cli` 的**用户身份**，免建应用、免 MCP）。
  - 枚举会话（`im +chat-list`，群聊 + 私聊 + 机器人私聊）、按时间窗拉消息（`im +chat-messages-list`）、跨会话关键词搜索（`im +messages-search`）、附件下载；
  - 批量导出脚本 `scripts/feishu_export.py`：`--hours/--days/--start/--end` 定窗口，逐会话导出为 `原始消息/飞书/<日期窗>/<会话名>.md` + `_messages.json` + `_summary.md`；单会话失败不中断整体导出；
  - 踩坑沉淀进 SKILL.md：时间必须带冒号 ISO 8601（`+08:00`）→ 否则 `cannot parse time`；`--types` 必须 `=` 形式；`--page-all` 必须配 `--page-limit`；失败 JSON 落在 stderr；卡片/富文本/机器人私聊的判读要点。
- **私聊来信语义分流**：`skills/wechat-todo-feishu/scripts/triage_incoming.py`（全自动四分类：新增 / 已完成 / 作废 / 纯通知），替换原来的机械判定，降低误报。
- 安装器按 `skills/` 目录**动态装入全部 skill**（当前 3 个：`wechat-todo-feishu`、`wechat-local`、`feishu-local`）。

### 修复

- **x64 Windows 装不上**：原生依赖按宿主 CPU 架构自愈——剔除架构不符的 `.pyd`，再用本机 python 补装同版本轮子（`pycryptodome` / `psutil` / `zstandard`）；重复安装不再每次重新 pip。
- **`wxcli init` 的 db_dir 探测失效**：支持多行 ini、默认「文档」兜底，仍失败可显式 `--db-dir` 指定。
- **lark-cli 预检失真**：用户身份与机器人身份**分层判定**（skill 固定 `--as user`，bot 身份不再冒充 user）；校验不通过时给出可执行的修复建议。
- **缓存映射丢失**：修掉重装/升级后 `db_cache` 路径映射丢失的问题。
- 文档：README 增加「飞书聊天记录提取（feishu-local）」章节与能力边界说明；卸载说明补齐第三个 skill；`.gitignore` 忽略 `__pycache__/`、`*.pyc`。

### 兼容性

- 与 v1.0.0 的工作区产物（`今日待办.md`、`待办总表.md`、`日期纪要/`、飞书台账参数）完全兼容，直接覆盖升级即可。
- 新增依赖：无。飞书读取仍只依赖本机 `lark-cli` 登录态。

## v1.0.0 — 2026-11-01

- 首个版本：微信消息 → 待办整理 → 飞书同步（多维表格「微信待办台账」台账 + 飞书任务双写，走本机 `lark-cli`）。
- 一条命令安装：装 `wechat-todo-feishu` / `wechat-local` 两个 skill、铺设 `wechat-cli` 工具链、自动初始化解密密钥、预检 lark-cli。
- 内置规则：绝对日期、总表倒叙、全量会话扫描、建任务前三查去重、飞书勾掉=已完成。
