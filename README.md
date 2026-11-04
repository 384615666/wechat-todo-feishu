# wechat-todo-feishu

> 微信消息 → 待办整理 → **飞书**自动同步（多维表格台账 + 飞书任务双写）—— **一行命令、即插即用**的 AI 助手技能包

每天微信群里的通知、截止日期、文件散落各处？装上它之后，对你的 AI 助手说一句 **「更新待办」**，它就会：全量扫描微信新消息 → 判定哪些是要办的事 → 写成结构化待办文件 → 双写飞书（**多维表格「微信待办台账」**做全量记录与去重索引，**飞书任务**做提醒与勾选）→ 把新收到的文件分类归档 → 给你一份汇总报告。

> 本项目基于 [syskuku/wechat-todo](https://github.com/syskuku/wechat-todo)（原作 Syskuku_暮雪逢樱）改造：把滴答清单同步层替换为飞书，并**改走本机 `lark-cli`**——飞书侧已登录的机器**免建应用、免 OAuth、免写任何 MCP 配置**。微信读取、待办文件、归档等工作流逻辑与原版一致。

当前版本 **v1.1.0**（2026-11-04）· 变更见 [CHANGELOG.md](CHANGELOG.md)

兼容任何支持 **SKILL.md 规范**的 AI 编码/助手工具（ZCode、OpenClaw、Claude Code 等），Windows / macOS / Linux 通用。

---

## 前提条件

| 依赖 | 说明 |
|---|---|
| **微信桌面客户端**（Windows） | 微信读取在本机解密，需要装着微信运行 |
| **lark-cli 已安装并登录** | 飞书同步走它。已连好的机器零配置：安装器会自动预检 `lark-cli auth status` |
| AI 助手工具 | ZCode / Claude Code 等支持 SKILL.md 的工具（skills 会自动装进去） |
| Node.js ≥ 18 | 安装器运行需要 |
| **Python 3.11+**（x64 / ARM64 均可） | `wxcli` 由系统 python 驱动；安装器还用它自检并按本机架构补装原生依赖 |

## 安装

在目标机器上克隆并安装（私有仓库，需用有权限的 GitHub 账号登录）：

```bash
git clone https://github.com/384615666/wechat-todo-feishu.git
cd wechat-todo-feishu
node bin/wechat-todo-feishu.js
```

就这一条。它不是只丢给你一个说明文件——**该带的工具全部随包装好**：

| 组件 | 说明 | 装到哪 |
|---|---|---|
| `wechat-todo-feishu` skill | 待办主工作流（扫描→判定→写文件→双写飞书→归档→报告） | `~/.agents/skills/wechat-todo-feishu/` 等 |
| `wechat-local` skill | 微信消息查询/导出/检索的全部脚本（`search_all.py` 等） | `~/.agents/skills/wechat-local/` |
| `feishu-local` skill | 飞书聊天记录查询/导出/检索（`feishu_export.py` 批量导出），走本机已登录的 `lark-cli` 用户身份 | `~/.agents/skills/feishu-local/` |
| wechat-cli 工具链 | 开源 [wechat-cli-plus](https://github.com/maomao3334/wechat-cli-plus) 0.2.4（Apache-2.0），含全部 Python 依赖，**无需 pip 安装** | `~/.wechat-cli/` |
| 解密密钥初始化 | 自动检测并执行 `wxcli init`（保持微信运行即可，密钥从本机微信进程提取，数据不出本机） | `~/.wechat-cli/all_keys.json` |
| lark-cli 预检 | 自动探测本机 lark-cli 并校验登录态；**不写入、不修改任何凭据与配置** | — |
| 原生依赖自愈 | 校验 `~/.wechat-cli/deps` 里的原生模块与本机 CPU 架构/Python ABI 是否匹配，不匹配就用 python 补装同版本轮子——**x64 与 ARM64 Windows 都能装** | `~/.wechat-cli/deps/` |

安装器会检测你机器上已有的工具目录（`~/.agents/skills`、`~/.zcode/skills`、`~/.claude/skills`）并装入存在的那些；重复执行 = 覆盖升级。

<details>
<summary>环境变量开关</summary>

- `WECHAT_TODO_SKILLS_DIR` —— 自定义 skills 安装目录
- `--skip-init` —— 跳过解密密钥初始化
- `WECHAT_TODO_DEBUG=1` —— 打印原生依赖自检细节（排查架构/ABI 问题用）

</details>

---

## 飞书侧是什么架构

飞书同步通过**本机 `lark-cli`** 完成（复用它已有的登录态与身份），两个目标各司其职：

| 目标 | 角色 |
|---|---|
| **飞书任务** | 执行层：带截止日期的任务会出现在飞书「任务」里，手机弹提醒，可勾选完成，skill 会回读你勾掉的状态 |
| **多维表格「微信待办台账」** | 台账层：全部待办一行一条（含无截止占位），带来源/优先级/状态列，是去重索引与全量记录 |

若目标机器的 lark-cli 版本没有任务域，skill 会自动降级为**台账单写**并在每次汇报中注明（首次引导时也会探查并与你确认）。

首次运行 skill 时，引导会带你完成：验证 lark-cli 登录态 → 探查任务/多维表格能力 → 建「微信待办台账」（7 个字段：任务/截止日期/状态/优先级/来源/任务ID/原文摘录）→ 把表格参数写进工作区 README。

---

## 飞书聊天记录提取（feishu-local）

微信消息在本机解密读；**飞书没有本地可解密库**，消息在服务端，所以走 OpenAPI —— 用本机 `lark-cli` 的**用户身份**（`--as user`），读到的范围 = 你在飞书客户端里能看到的范围（含你加入的群、你的私聊、机器人私聊）。

```bash
# 我加入了哪些会话（p2p 需要用户身份）
lark-cli im +chat-list --as user --types=p2p,group --sort=active_time

# 某个会话在时间窗内的消息（必须带冒号的 ISO 8601 时区）
lark-cli im +chat-messages-list --as user --chat-id oc_xxx \
  --start 2026-11-01T00:00:00+08:00 --end 2026-11-03T23:59:59+08:00 \
  --order asc --page-all --page-limit 20

# 跨会话关键词搜索（找"截止/报名/审批/周会"这类）
lark-cli im +messages-search --as user --query "截止" --page-all --page-limit 5
```

批量导出（推荐入口，枚举全部会话 → 按窗口拉取 → 每会话 markdown + 结构化 JSON）：

```bash
python ~/.agents/skills/feishu-local/scripts/feishu_export.py --days 3
python ~/.agents/skills/feishu-local/scripts/feishu_export.py --hours 24 --download-resources
python ~/.agents/skills/feishu-local/scripts/feishu_export.py --name-match 湖南 --dry-run
```

产物：`原始消息/飞书/<日期窗>/<会话名>.md`（时间/发送人/类型/正文/附件）、`_messages.json`（供 triage 读）、`_summary.md`（会话清单与失败项）。

**能力边界（实测）**

- 读得到：群聊、私聊、机器人私聊（审批/任务助手/多维表格助手）、卡片消息（content 已压成 `<card>` 文本）、富文本、附件下载；
- 读不到：你没加入的群、别人的私聊、企业全量审计数据（那要走管理员导出）；
- 历史深度：实测可回溯到半年前（2026-03 实测可读），最终受群「新成员可见历史」与租户策略限制；
- 失败信息写在 **stderr**，`--types` 必须用 `=` 形式，`--page-all` 必须配 `--page-limit`——这些坑都写进了 skill 的 SKILL.md。

---

## 使用方法

### 1. 触发

装好后，在你的 AI 助手对话里直接说：

> **更新待办** ／ 生成今天的待办 ／ 同步飞书 ／ 整理微信消息 ／ 跑一下待办 ／ 汇总最近要办的事

### 2. 首次使用引导（只出现一次）

第一次触发时，skill 会带着你完成三件事，然后**把引导段从文件里自动删掉**，之后的每次运行都不再重复：

1. **新建专用工作文件夹**（最重要）——在电脑任意位置建一个文件夹作为唯一工作区，消息导出、`今日待办.md`、`待办总表.md`、`日期纪要/`、归档文件全放这里，让 agent 运行在该文件夹中；
2. **验证飞书 CLI**——`lark-cli auth status --json --verify` 校验登录态，`--help` 探查任务与多维表格能力；
3. **建飞书台账**——创建「微信待办台账」多维表格并记录参数；随后引导段自动移除。

> 若微信解密没就绪（`wxcli sessions` 报错），保持微信运行执行一次 `~/.wechat-cli/wxcli.cmd init` 即可。

### 3. 每次运行做什么（自动流程）

1. **定断点**——读工作区 README 里的上次同步时间；
2. **全量扫会话**——`wxcli sessions` 列出所有会话，凡断点后有新消息的逐个导出（不靠固定群名单，防漏新拉的群）；
3. **关键词补盲**——截止/交/报名/接龙/收到请回复 等多轮检索，补上扫描盲区；
4. **判定分类**——新待办 / 已完成 / 作废 / 纯通知 / 纯闲聊，同事项取最新版本，别人私聊交代的事优先；
5. **写文件**——生成 `日期纪要/当天.md`，重写 `今日待办.md`（绝对日期勾选清单），倒叙重排 `待办总表.md`；
6. **双写飞书**——先查台账全部记录 + 飞书未完成任务 + 已完成任务三样去重；你在飞书里勾掉的自动同步为"已完成"；新待办建飞书任务（带日期、弹提醒）+ 写台账行（含来源与原文）；
7. **归档文件**——新收到的 docx/xlsx/pdf/zip 打开确认内容后分类入文件夹；
8. **衔接校验 + 汇报**——旧未完成逐条对照不许凭空消失，最后输出断点范围、新增待办（按优先级排序）、飞书操作明细、文件去向、近三天硬截止 Top3。

### 4. 产出文件结构

```text
你的工作区/
├── README.md            ← 同步断点、必盯会话、个人范围与优先级规则、飞书台账参数
├── 今日待办.md            ← 每天打开这个：⚡硬截止 → 🟡顺手 → 📅接下来 → ✅已完成 → ⚠️已作废
├── 待办总表.md            ← 全部待办倒叙（最新在顶），飞书勾掉=已完成
├── 日期纪要/YYYY-MM-DD.md ← 每日消息背景与时间线
├── 原始消息/              ← 聊天记录导出存档
└── …归档的资料文件夹
```

### 5. 内置规则（踩坑沉淀，不用你再教）

- 绝对日期（永不写"今天"）、总表倒叙、全量会话扫描；
- 飞书单任务单日期；任务描述末尾附**通知原文逐字照抄**；台账"来源"列同步记录；
- 带日期的事项（哪怕可选、收到免回复）一律建任务；全部事项（含无截止）一律入台账；
- 建任务前三查去重（台账 + 未完成 + 已完成），**飞书勾掉=已完成**，不重复提交、不翻你的案；
- 范围过滤：通知限定"校本部/某年级/某职务"的，不派给范围外的用户；
- 优先级默认：本人组织职务 > 老师/上级 > 其他按紧急度（可在工作区 README 覆盖）。

---

## 更新与卸载

- **更新**：重跑 `node bin/wechat-todo-feishu.js`（覆盖最新版）。每次重跑都会重新铺 vendor 里的原生模块，随后自动按本机架构自愈，属预期行为；
- **卸载**：删除 skills 里的 `wechat-todo-feishu`、`wechat-local`、`feishu-local` 三个文件夹，以及 `~/.wechat-cli/`（如不再需要微信读取）；
- **数据安全**：解密密钥、db 配置、聊天数据永不出本机，安装包不包含也不覆盖你的任何凭据；lark-cli 的登录态由它自己管理，本包不读取不搬运。

## 常见问题

| 现象 | 处理 |
|---|---|
| `wxcli sessions` 报密钥错误/乱码 | 保持微信运行 → `~/.wechat-cli/wxcli.cmd init` |
| 报 `OSError: Cannot load '_cpuid_c.pyd': [WinError 193]` 或其它原生模块加载失败 | 包内原生依赖与本机架构不符。重跑 `node bin/wechat-todo-feishu.js` 会自动按本机架构补装；也可手动 `python -m pip install --target "%USERPROFILE%\.wechat-cli\deps" pycryptodome==3.23.0 psutil==7.2.2 zstandard==0.25.0` |
| 报 `zstandard has no attribute ZstdDecompressor` | 把 `~/.wechat-cli/deps/zstandard/*` 复制到 `%LOCALAPPDATA%\Temp\wechat-cli-plus-pydeps\zstandard\` |
| `wxcli init` 报"未自动检测到微信数据目录" | 4.x 微信数据在 `文档\xwechat_files\<wxid>\db_storage`。探测已支持多行 ini 与默认「文档」兜底；仍失败就显式指定：`~/.wechat-cli/wxcli.cmd init --db-dir "<该路径>"` |
| 安装器说 lark-cli 未找到 | `lark-cli` 不在 PATH 里；或登录态校验未过——先手动跑 `lark-cli auth status --json --verify` |
| 安装器说"仅机器人身份就绪 / 用户身份过期" | 机器人身份**不能**顶替用户身份（skill 规定 `--as user`）。执行 `lark-cli auth login`，10 分钟内完成设备码授权即可 |
| lark-cli 报权限/scope 不足 | 在 lark-cli 侧补授权；skill 会如实上报所缺 scope，不换身份绕过 |
| 没有飞书任务域 | 该版本 lark-cli 不支持任务域，skill 自动降级为台账单写并在汇报注明 |
| 微信换了版本/重装 | 重新 `wxcli init`，db_dir 会自动重探测 |

## 致谢与来源

- 原项目：**[syskuku/wechat-todo](https://github.com/syskuku/wechat-todo)** · 作者 **Syskuku_暮雪逢樱** · [www.imikufans.com](https://www.imikufans.com)（MIT）
- 微信读取：[wechat-cli-plus](https://github.com/maomao3334/wechat-cli-plus)（Apache-2.0）
- 飞书接入：本机 `lark-cli`（已登录，免自建应用）

License: skill 与安装器 MIT ｜ 内置 wechat-cli-plus Apache-2.0 ｜ 依赖库各随其原许可
