# -*- coding: utf-8 -*-
"""微信全量关键词检索（含 zstd 压缩消息，补上 wxcli search 的盲区）

用法:
  python search_all.py <关键词> [--context N] [--chat 显示名或username] [--limit N]

输出: >> 命中行 / 空格缩进行为上下文
前置: 解密缓存存在；若报缓存缺失，先跑一条 wxcli 命令（如 sessions）触发解密。
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

SENDER_PREFIX = re.compile(r"^(?:wxid_[A-Za-z0-9_]+|gh_[A-Za-z0-9_]+):\s*\n?")

sys.path.insert(0, os.path.join(os.environ["LOCALAPPDATA"], "Temp",
                                "wechat-cli-plus-pydeps"))
try:
    import zstandard as zstd
except ImportError:
    sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".wechat-cli", "deps"))
    import zstandard as zstd

CACHE = os.path.join(os.environ["TEMP"], "wechat_cli_cache")


def find_db(rel_key):
    """按 rel_key 取解密缓存路径（_mtimes.json 里有 rel_key -> path 映射）"""
    mt = os.path.join(CACHE, "_mtimes.json")
    if os.path.isfile(mt):
        with open(mt, encoding="utf-8") as f:
            info = json.load(f).get(rel_key)
        if info and os.path.isfile(info["path"]):
            return info["path"]
    return None


def display_names():
    """username -> 显示名（备注优先），来自解密的 contact.db"""
    names = {}
    p = find_db(r"contact\contact.db")
    if not p:
        return names
    try:
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as con:
            for un, remark, nick in con.execute(
                    "SELECT username, remark, nick_name FROM contact"):
                if un:
                    names[un] = remark or nick or un
    except sqlite3.Error:
        pass
    return names


def table_owner_map(con):
    """Msg_<md5> 表名 -> 会话 username；返回 (表映射, rowid->username)"""
    mapping = {}
    rowid_map = {}
    try:
        rows = con.execute("SELECT rowid, user_name FROM Name2Id").fetchall()
    except sqlite3.Error:
        return mapping, rowid_map
    for rid, un in rows:
        if un:
            rowid_map[rid] = un
            mapping["Msg_" + hashlib.md5(un.encode()).hexdigest()] = un
    return mapping, rowid_map


def dec(mc, ct, dctx):
    if mc is None:
        return ""
    if isinstance(mc, bytes):
        if ct == 4:
            try:
                return dctx.decompress(mc).decode("utf-8", errors="replace")
            except Exception:
                return ""
        return mc.decode("utf-8", errors="replace")
    return mc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword")
    ap.add_argument("--context", type=int, default=0, help="附带前后N条消息")
    ap.add_argument("--chat", default=None, help="限定会话（显示名或username）")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    dbs = []
    for rel in (r"message\message_0.db", r"message\biz_message_0.db"):
        p = find_db(rel)
        if p and p not in dbs:
            dbs.append(p)
    if not dbs:
        print("解密缓存缺失：先运行一次 ~/.wechat-cli/wxcli.cmd sessions",
              file=sys.stderr)
        sys.exit(1)

    dctx = zstd.ZstdDecompressor()
    names = display_names()
    hits = 0

    for path in dbs:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            owners, rowids = table_owner_map(con)
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'Msg_%'")]
            for t in tables:
                owner = owners.get(t, "")
                disp = names.get(owner, owner)
                if args.chat and args.chat not in (disp, owner):
                    continue
                try:
                    rows = con.execute(
                        f"SELECT local_id, local_type, create_time, real_sender_id, "
                        f"message_content, WCDB_CT_message_content FROM [{t}] "
                        f"ORDER BY local_id").fetchall()
                except sqlite3.Error:
                    continue
                texts = [dec(r[4], r[5], dctx) for r in rows]
                for i, s in enumerate(texts):
                    if args.keyword not in s:
                        continue
                    if hits >= args.limit:
                        break
                    lo = max(0, i - args.context)
                    hi = min(len(rows), i + args.context + 1)
                    for j in range(lo, hi):
                        lid, _lt, ts, sid, _mc, _ct = rows[j]
                        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                        sender_un = rowids.get(sid, "")
                        sender = names.get(sender_un, sender_un) or "?"
                        body = SENDER_PREFIX.sub("", texts[j]).replace("\n", " ")[:200]
                        marker = ">>" if j == i else "  "
                        print(f"{marker} [{when}] {disp} | {sender}: {body}")
                    if args.context:
                        print("-" * 60)
                    hits += 1
                if hits >= args.limit:
                    break
        if hits >= args.limit:
            break
    print(f"共 {hits} 条命中", file=sys.stderr)


if __name__ == "__main__":
    main()
