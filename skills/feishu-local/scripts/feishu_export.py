#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_export.py —— 飞书聊天记录增量导出（走本机已登录的 lark-cli，用户身份）

用途：把指定时间窗内「我」能看到的所有飞书会话消息导出为 markdown + 结构化 JSON，
供后续待办提取（triage）、归档、检索使用。

设计要点：
  * 身份固定 `--as user`（用户身份），因此读到的范围 = 你真能在飞书里看到的范围；
  * 先 `im +chat-list` 枚举全部会话（群 + 私聊，可按 --max-chats 限量），
    再逐会话 `im +chat-messages-list` 按 --start/--end 窗口拉取，空窗口直接跳过；
  * 每个会话一个 markdown 文件，另有 `_summary.md` 总览与 `_messages.json` 结构化数据；
  * 单会话失败不中断整体导出，错误记入 `_summary.md` 与返回码汇总；
  * 不写入、不修改 lark-cli 的任何凭据或配置，只读调用。

示例：
  # 导出最近 24 小时
  python feishu_export.py --hours 24

  # 导出 2026-11-01 ~ 2026-11-03，含图片/文件下载
  python feishu_export.py --start 2026-11-01T00:00:00+08:00 --end 2026-11-03T23:59:59+08:00 --download-resources

  # 只看群、只看名字里带「湖南」的会话
  python feishu_export.py --hours 48 --types group --name-match 湖南

无第三方依赖：只用标准库 + 本机 lark-cli。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- 基础工具

def _fix_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except Exception:
            pass


def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[feishu_export] 错误: {msg}", file=sys.stderr)
    raise SystemExit(code)


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- lark-cli 调用

class LarkCLI:
    """薄封装：定位 lark-cli，跑命令，解析 JSON。"""

    def __init__(self, lark_bin: str | None = None, page_delay: int = 200) -> None:
        self.page_delay = page_delay
        self.cmd = self._resolve(lark_bin)

    @staticmethod
    def _resolve(lark_bin: str | None) -> list[str]:
        cand = lark_bin or os.environ.get("LARK_CLI") or shutil.which("lark-cli")
        if not cand:
            die("PATH 里找不到 lark-cli。请安装 lark-cli 并用 `lark-cli auth login` 登录，"
                "或用 --lark-bin / 环境变量 LARK_CLI 指定可执行文件路径。")
        p = Path(cand)
        low = str(p).lower()
        if low.endswith((".cmd", ".bat")):
            # Windows 的 npm 包装器：CreateProcess 不能直跑 .cmd，交给 cmd.exe
            return ["cmd", "/c", str(p)]
        if low.endswith(".ps1"):
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)]
        return [str(p)]

    def run(self, args: list[str], *, expect_ok: bool = True) -> dict:
        full = self.cmd + args
        try:
            proc = subprocess.run(
                full, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300,
            )
        except FileNotFoundError:
            die(f"无法执行 lark-cli（{self.cmd[0]}）")
        except subprocess.TimeoutExpired:
            die("lark-cli 调用超时（300s），可能是网络或授权问题")
        out = (proc.stdout or "").strip()
        err_out = (proc.stderr or "").strip()
        if not out:
            # lark-cli 的失败信息写在 stderr，且同样是 JSON 信封
            payload = None
            if err_out.startswith("{"):
                try:
                    payload = json.loads(err_out)
                except json.JSONDecodeError:
                    payload = None
            if payload is not None:
                return payload
            if expect_ok:
                die(f"lark-cli 无输出，退出码 {proc.returncode}: {err_out[:500]}")
            return {}
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            if expect_ok:
                die(f"lark-cli 输出不是 JSON（退出码 {proc.returncode}）: "
                    f"{out[:300]} || stderr: {err_out[:300]}")
            return {}
        if expect_ok and not payload.get("ok", False):
            err = payload.get("error") or {}
            die(f"lark-cli 返回失败: {err.get('type')}/{err.get('subtype')} {err.get('message')}")
        return payload

    # -- 高层封装 -------------------------------------------------

    def auth_status(self) -> dict:
        return self.run(["auth", "status", "--json"])

    def list_chats(self, chat_types: list[str], page_limit: int, exclude_bots: bool) -> list[dict]:
        args = [
            "im", "+chat-list", "--as", "user",
            f"--types={','.join(chat_types)}",
            "--sort=active_time",          # 最近活跃的排前面，配合 --max-chats 才有意义
            "--page-size", "100",
            "--page-all", "--page-limit", str(page_limit),
            "--page-delay", str(self.page_delay),
            "--format", "json",
        ]
        payload = self.run(args)
        chats = (payload.get("data") or {}).get("chats") or []
        if exclude_bots:
            chats = [c for c in chats if c.get("p2p_target_type") != "bot"]
        return chats

    def list_messages(self, chat_id: str, start: str, end: str,
                      page_limit: int, download_resources: bool) -> tuple[list[dict], dict]:
        args = [
            "im", "+chat-messages-list", "--as", "user",
            "--chat-id", chat_id,
            "--start", start, "--end", end,
            "--order", "asc",
            "--page-size", "50",
            "--page-all", "--page-limit", str(page_limit),
            "--page-delay", str(self.page_delay),
            "--no-reactions",
            "--format", "json",
        ]
        if download_resources:
            args.append("--download-resources")
        payload = self.run(args, expect_ok=False)
        if not payload.get("ok", False):
            err = payload.get("error") or {}
            return [], {"chat_id": chat_id,
                        "error": f"{err.get('type')}/{err.get('subtype')}: {err.get('message')}"}
        data = payload.get("data") or {}
        return data.get("messages") or [], {}


# ---------------------------------------------------------------- 渲染

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(name: str, fallback: str, maxlen: int = 60) -> str:
    cleaned = _BAD_CHARS.sub("_", (name or "").strip()).strip(" ._")
    if not cleaned:
        cleaned = fallback
    return cleaned[:maxlen]


def render_chat_md(chat: dict, messages: list[dict], window: tuple[str, str]) -> str:
    mode = "群聊" if chat.get("chat_mode") == "group" else "私聊"
    kind = ""
    if chat.get("p2p_target_type") == "bot":
        kind = " · 机器人"
    lines = [
        f"# {chat.get('name') or chat.get('chat_id')}",
        "",
        f"> {mode}{kind} ｜ chat_id `{chat.get('chat_id')}` ｜ 消息 {len(messages)} 条 ｜ "
        f"{window[0]} ~ {window[1]}",
        f"> 会话链接：{chat.get('chat_app_link') or '—'}",
        "",
        "## 消息",
        "",
    ]
    for m in messages:
        ts = m.get("create_time") or ""
        sender = ((m.get("sender") or {}).get("name") or "").strip()
        stype = (m.get("sender") or {}).get("sender_type") or ""
        if m.get("msg_type") == "system" and not sender:
            sender = "系统"
        elif not sender:
            sender = (m.get("sender") or {}).get("id") or "未知"
        mtype = m.get("msg_type") or "text"
        tag = f"`{mtype}`"
        if stype == "app":
            tag += " 🤖"
        head = f"- `{ts}` · **{sender}** · {tag}"
        if m.get("updated"):
            head += f" · 已编辑({m.get('update_time')})"
        lines.append(head)
        content = (m.get("content") or "").strip()
        if content:
            for ln in content.splitlines():
                lines.append(f"  > {ln}" if ln.strip() else "  >")
        # 附件（--download-resources 时 lark-cli 会回填 resources）
        for res in m.get("resources") or []:
            path = res.get("local_path") or res.get("path") or res.get("file_path") or ""
            name = res.get("file_name") or res.get("name") or res.get("file_key") or "附件"
            lines.append(f"  > 📎 {name} → `{path or '（未下载）'}`")
        if m.get("thread_id"):
            lines.append(f"  > 🧵 thread `{m.get('thread_id')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_summary(day: str, window: tuple[str, str], exported: list[dict],
                   errors: list[dict], skipped: int) -> str:
    total = sum(c["count"] for c in exported)
    lines = [
        f"# 飞书消息导出 · {day}",
        "",
        f"- 时间窗：{window[0]} ~ {window[1]}",
        f"- 有消息的会话：{len(exported)} 个 ｜ 消息合计：{total} 条 ｜ 空窗口跳过：{skipped} 个",
        "",
        "## 会话明细",
        "",
        "| 会话 | 类型 | 消息数 | 参与人 |",
        "|---|---|---|---|",
    ]
    for c in sorted(exported, key=lambda x: (-x["count"], x["name"])):
        who = "、".join(c.get("senders") or []) or "—"
        lines.append(f"| {c['name']} | {c['mode']} | {c['count']} | {who[:80]} |")
    if errors:
        lines += ["", "## 读取失败", ""]
        for e in errors:
            lines.append(f"- `{e['chat_id']}`：{e['error']}")
    lines += ["", "> 由 feishu_export.py 生成；消息内容来自飞书 OpenAPI（用户身份），仅本机留存。", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程

def parse_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    now = datetime.now().astimezone()
    if args.start or args.end:
        end = _parse_iso(args.end) if args.end else now
        if args.start:
            start = _parse_iso(args.start)
        else:
            start = end - timedelta(hours=24)
        return start, end
    hours = args.hours if args.hours is not None else (args.days or 1) * 24
    return now - timedelta(hours=hours), now


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.astimezone()
        except ValueError:
            continue
    try:  # Python 3.11 fromisoformat 较宽松
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.astimezone()
    except ValueError:
        die(f"无法解析时间：{s}（示例 2026-11-01T00:00:00+08:00）")


def iso(dt: datetime) -> str:
    """lark-cli 只接受 ISO 8601 带冒号的时区偏移（+08:00），不接受 +0800。"""
    return dt.astimezone().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    _fix_stdout()
    ap = argparse.ArgumentParser(
        description="导出飞书聊天记录（走本机 lark-cli 用户身份）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--hours", type=float, help="最近 N 小时（默认 24）")
    ap.add_argument("--days", type=float, help="最近 N 天（= N*24 小时）")
    ap.add_argument("--start", help="开始时间，ISO 8601，如 2026-11-01T00:00:00+08:00")
    ap.add_argument("--end", help="结束时间，ISO 8601，默认现在")
    ap.add_argument("--out", default="原始消息/飞书", help="输出根目录（默认 原始消息/飞书）")
    ap.add_argument("--types", default="p2p,group", help="会话类型，默认 p2p,group")
    ap.add_argument("--name-match", default=None, help="只导出名称包含该子串的会话")
    ap.add_argument("--chat-id", action="append", default=None, help="只导出指定 chat_id，可重复")
    ap.add_argument("--exclude-bots", action="store_true", help="跳过机器人私聊（审批/助手等）")
    ap.add_argument("--max-chats", type=int, default=400, help="最多检查多少个会话（默认 400）")
    ap.add_argument("--page-limit", type=int, default=30, help="单会话最多翻页数（默认 30，每页 50 条）")
    ap.add_argument("--page-delay", type=int, default=200, help="翻页间隔毫秒（默认 200，防限流）")
    ap.add_argument("--download-resources", action="store_true", help="同时下载图片/文件附件")
    ap.add_argument("--json-out", default=None, help="结构化消息 JSON 的路径（默认与 markdown 同目录 _messages.json）")
    ap.add_argument("--lark-bin", default=None, help="lark-cli 可执行文件路径（默认从 PATH 找）")
    ap.add_argument("--dry-run", action="store_true", help="只枚举会话，不拉消息")
    args = ap.parse_args(argv)

    types = [t.strip() for t in (args.types or "").split(",") if t.strip()]
    if not set(types) <= {"p2p", "group"} or not types:
        die("--types 只能是 p2p / group 的组合，如 --types=p2p,group")

    start, end = parse_window(args)
    if start >= end:
        die("开始时间必须早于结束时间")
    win = (start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"))
    day = start.strftime("%Y-%m-%d")
    if start.date() != end.date():
        day = f"{start.strftime('%Y-%m-%d')}_{end.strftime('%Y-%m-%d')}"

    cli = LarkCLI(args.lark_bin, page_delay=args.page_delay)

    log(f"[feishu_export] 时间窗 {win[0]} ~ {win[1]}")
    log(f"[feishu_export] 枚举会话（{','.join(types)}）…")
    chats = cli.list_chats(types, page_limit=20, exclude_bots=args.exclude_bots)
    if args.chat_id:
        wanted = set(args.chat_id)
        chats = [c for c in chats if c.get("chat_id") in wanted]
    if args.name_match:
        chats = [c for c in chats if args.name_match in (c.get("name") or "")]
    if not chats:
        log("[feishu_export] 没有匹配的会话（检查 --types / --name-match / --chat-id）")
        return 0
    log(f"[feishu_export] 会话总数 {len(chats)}，逐个拉取消息…")
    if args.dry_run:
        for c in chats[:50]:
            log(f"  - {c.get('chat_mode'):5s} {c.get('name')}  ({c.get('chat_id')})")
        if len(chats) > 50:
            log(f"  … 其余 {len(chats) - 50} 个略")
        return 0

    out_dir = Path(args.out).expanduser().resolve() / day
    msgs_dir = out_dir
    msgs_dir.mkdir(parents=True, exist_ok=True)
    if args.download_resources:
        os.chdir(msgs_dir)   # lark-cli 把附件下载到 ./lark-im-resources/

    exported: list[dict] = []
    errors: list[dict] = []
    skipped = 0
    structured: dict = {"window": {"start": iso(start), "end": iso(end)}, "chats": []}
    used_names: set[str] = set()

    for idx, chat in enumerate(chats, 1):
        cid = chat.get("chat_id") or ""
        name = chat.get("name") or cid
        prefix = f"[{idx}/{len(chats)}]"
        if args.max_chats and idx > args.max_chats:
            log(f"{prefix} 达到 --max-chats 上限，停止")
            break
        messages, err = cli.list_messages(cid, iso(start), iso(end), args.page_limit,
                                          args.download_resources)
        if err:
            errors.append(err)
            log(f"{prefix} ✗ {name}：{err['error'][:120]}")
            continue
        if not messages:
            skipped += 1
            continue

        fname = safe_name(name, cid[:16])
        if fname in used_names:
            fname = f"{fname}_{cid[-6:]}"
        used_names.add(fname)
        (msgs_dir / f"{fname}.md").write_text(
            render_chat_md(chat, messages, win), encoding="utf-8")

        senders: list[str] = []
        for m in messages:
            s = ((m.get("sender") or {}).get("name") or "").strip()
            if s and s not in senders:
                senders.append(s)
        exported.append({
            "name": name, "chat_id": cid,
            "mode": "群聊" if chat.get("chat_mode") == "group" else "私聊",
            "count": len(messages), "senders": senders,
        })
        structured["chats"].append({
            "chat_id": cid, "name": name, "chat_mode": chat.get("chat_mode"),
            "p2p_target_type": chat.get("p2p_target_type"),
            "messages": [
                {
                    "message_id": m.get("message_id"),
                    "create_time": m.get("create_time"),
                    "msg_type": m.get("msg_type"),
                    "sender_name": (m.get("sender") or {}).get("name"),
                    "sender_type": (m.get("sender") or {}).get("sender_type"),
                    "sender_id": (m.get("sender") or {}).get("id"),
                    "content": m.get("content"),
                    "thread_id": m.get("thread_id"),
                    "resources": m.get("resources"),
                }
                for m in messages
            ],
        })
        log(f"{prefix} ✓ {name}：{len(messages)} 条")

    (msgs_dir / "_summary.md").write_text(
        render_summary(day, win, exported, errors, skipped), encoding="utf-8")
    json_path = Path(args.json_out) if args.json_out else (msgs_dir / "_messages.json")
    json_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(c["count"] for c in exported)
    log("")
    log(f"[feishu_export] 完成：{len(exported)} 个会话 / {total} 条消息 / 跳过空会话 {skipped} 个"
        f" / 失败 {len(errors)} 个")
    log(f"[feishu_export] 输出目录：{msgs_dir}")
    log(f"[feishu_export] 结构化数据：{json_path}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
