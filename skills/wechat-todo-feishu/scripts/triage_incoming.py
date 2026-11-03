#!/usr/bin/env python3
"""微信私聊来信语义分流（全自动）——判断每位联系人当前是否「待我动作」。

背景：按「最后一条是谁发的」机械判定，会把「好的，谢谢你」这类收尾道谢误算成待回
（2026-11-03 实测把 17 人里的 7 人误报成 13 人）。本脚本把每人最近 N 条双向正文
交给模型做语义判定，输出四类结论。

四类结论
  ⏳ 待我动作   对方在等答复/交付、提出新要求，或我方承诺未兑现、对方发来文件未回应
  ✅ 已收尾     对方末句是收尾语且诉求已闭环，不必再回
  ⏳ 等对方     最后一条是我方发的（发链接/给方案/提问），等对方回应
  ·  无实质     纯寒暄、新加好友打招呼

数据与隐私
  · 微信数据从本机解密缓存读取（~/.wechat-cli），不出本机
  · 只有对话正文与「联系人NN」匿名标签会发到所配置的模型端点；真实姓名不进 prompt
  · 端点走 OpenAI 兼容 chat/completions；默认复用本机 DSH 的 newapi 配置

用法
  python triage_incoming.py --hours 24
  python triage_incoming.py --hours 24 --show 6 --json out.json
  python triage_incoming.py --hours 24 --no-llm        # 仅机械规则，仅供排障对比
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
STATE = os.path.join(HOME, ".wechat-cli")
for _p in (os.path.join(STATE, "tool"), os.path.join(STATE, "deps")):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)

RELS = ["contact\\contact.db", "session\\session.db", "message\\message_0.db",
        "message\\message_1.db", "message\\message_2.db", "message\\biz_message_0.db"]

SYSTEM_TYPES = {10000, 10002}
SYSTEM_USERS = {"notifymessage", "weixin", "fmessage", "filehelper", "qqmail", "medianote",
                "tmessage", "qmessage", "floatbottle", "brandprivatemsg@hardcode",
                "brandservicesessionholder", "brandsessionholder", "opencustomerservicemsg",
                "@opencustomerservicemsg", "newsapp", "weibo", "linkedinplugin"}
SYSTEM_NAMES = {"服务通知", "微信团队", "文件传输助手", "朋友推荐消息"}
TYPE_LABEL = {3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "表情",
              48: "位置", 49: "链接/文件", 50: "通话"}

VERDICTS = ("待我动作", "已收尾", "等对方", "无实质")

SYSTEM_PROMPT = """你是微信私聊来信分流器。给定若干段「我」与「对方」的对话尾部，判断每位联系人当前的状态。

判定标准（严格按证据，禁止仅凭"最后一条是谁发的"下结论）：
1. 待我动作：对方在等我答复或等我交付内容；对方提出新要求/新指令；我方上一条承诺过（今天修/中午修好/过两周/稍后/我看看）但对话结束时尚未兑现；对方只发来文件或链接而我方尚未回应。
2. 已收尾：对方末句是收尾语（好的 / 好的谢谢 / 好滴 / 收到 / 嗯 / 可以了 / 好👌 等），且其诉求已在我方上一条得到答复或交付。
3. 等对方：最后一条是我方发的（发链接、给方案、提问），且我方没有未兑现的承诺。
4. 无实质：纯寒暄、新加好友打招呼、系统消息，无需跟进。

只输出 JSON 数组，不要解释、不要 markdown 代码块：
[{"id":"联系人01","verdict":"待我动作","reason":"一句话证据","action":"若待我动作，写具体要做什么，否则空字符串"}]
verdict 只能是：待我动作 / 已收尾 / 等对方 / 无实质。"""


# ---------------- 解密缓存 ----------------
def load_paths(verbose=False):
    from wechat_cli.core.db_cache import DBCache
    keys = json.load(open(os.path.join(STATE, "all_keys.json"), encoding="utf-8"))
    cfg = json.load(open(os.path.join(STATE, "config.json"), encoding="utf-8"))
    cache = DBCache(keys, cfg["db_dir"])
    out = {}
    for rel in RELS:
        p = cache.get(rel)
        if p:
            out[rel] = p
            if verbose:
                print("  [库] %-26s %.1f MB" % (rel, os.path.getsize(p) / 1048576.0), file=sys.stderr)
    return out


def connect(path):
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=15)


def norm(t):
    for ch in ("\u2005", "\u200b", "\u200c", "\u2060", "\u00a0"):
        t = t.replace(ch, " " if ch == "\u2005" else "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def decode(raw, ct):
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        if ct == 4:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(bytes(raw)).decode("utf-8", "replace")
        return bytes(raw).decode("utf-8", "replace")
    except Exception:
        return ""


def is_person(username, names):
    if not username or username.endswith("@chatroom") or username.startswith("@"):
        return False
    if username in SYSTEM_USERS or username.endswith("@openim") or "@kefu.openim" in username:
        return False
    if username.endswith("@weclaw") or username.endswith("@app") or username.startswith("gh_"):
        return False
    return names.get(username, (username,))[0] not in SYSTEM_NAMES


# ---------------- 采集 ----------------
def collect(hours, limit_people=None):
    cutoff = time.time() - hours * 3600
    paths = load_paths()
    if "contact\\contact.db" not in paths or "session\\session.db" not in paths:
        sys.exit("缺少 contact/session 解密库，先跑一次 wxcli sessions")

    names = {}
    con = connect(paths["contact\\contact.db"])
    try:
        for u, remark, nick in con.execute("SELECT username, remark, nick_name FROM contact"):
            if u:
                names[u] = (remark or nick or u,)
    finally:
        con.close()

    con = connect(paths["session\\session.db"])
    try:
        sessions = con.execute("SELECT username, last_timestamp FROM SessionTable").fetchall()
    finally:
        con.close()

    db_tables = {}
    for rel in [r for r in paths if r.startswith("message\\")]:
        con = connect(paths[rel])
        try:
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
                db_tables[t] = (rel, paths[rel])
        finally:
            con.close()

    n2i_cache = {}

    def name_map(rel, path):
        if rel not in n2i_cache:
            con = connect(path)
            try:
                n2i_cache[rel] = {rid: un for rid, un in con.execute("SELECT rowid, user_name FROM Name2Id")}
            finally:
                con.close()
        return n2i_cache[rel]

    active = []
    for username, last_ts in sessions:
        if not last_ts or last_ts < cutoff:
            continue
        tbl = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
        if tbl in db_tables:
            active.append((username, tbl, db_tables[tbl]))

    convs, votes = [], Counter()
    for username, tbl, (rel, path) in active:
        if not is_person(username, names):
            continue
        nm = name_map(rel, path)
        con = connect(path)
        try:
            rows = con.execute(
                "SELECT real_sender_id, create_time, local_type, message_content, "
                "WCDB_CT_message_content, compress_content FROM [%s] WHERE create_time >= ? "
                "ORDER BY create_time" % tbl, (cutoff,)).fetchall()
        finally:
            con.close()
        msgs = []
        for sid, ts, ltype, content, ct, comp in rows:
            sender = nm.get(sid, "")
            ltype = (ltype or 0) & 0xFFFFFFFF
            if ltype in SYSTEM_TYPES:
                continue
            text = norm(decode(content if content is not None else comp, ct))
            if not text:
                continue
            msgs.append({"sender": sender, "ts": ts, "type": ltype,
                         "text": text if ltype == 1 else "[%s]" % TYPE_LABEL.get(ltype, "非文本")})
            if sender and sender != username:
                votes[sender] += 1
        if msgs:
            convs.append({"username": username, "name": names.get(username, (username,))[0], "msgs": msgs})

    me = votes.most_common(1)[0][0] if votes else None
    for c in convs:
        c["msgs"] = [{"who": "我" if m["sender"] == me else "对方", "ts": m["ts"],
                      "text": m["text"]} for m in c["msgs"]]
    convs.sort(key=lambda c: c["msgs"][-1]["ts"], reverse=True)
    if limit_people:
        convs = convs[:limit_people]
    return convs, me


# ---------------- 模型端点 ----------------
def resolve_endpoint():
    base = os.environ.get("TRIAGE_BASE_URL")
    key = os.environ.get("TRIAGE_API_KEY")
    model = os.environ.get("TRIAGE_MODEL")
    if base and key and model:
        return base, key, model

    # 回退：复用本机 DSH 的 newapi 配置（只读，不落盘、不打印）
    settings = os.path.join(HOME, ".dsh", "settings.yaml.imported")
    cred = os.path.join(HOME, ".dsh", ".credentials.yaml")
    if not base and os.path.exists(settings):
        m = re.search(r"newapi:\s*(?:\n\s+.*)*?\n\s+baseURL:\s*(\S+)", open(settings, encoding="utf-8").read())
        if m:
            base = m.group(1)
    if not key and os.path.exists(cred):
        refs, inrefs = {}, False
        for line in open(cred, encoding="utf-8"):
            if re.match(r"^refs:\s*$", line):
                inrefs = True
                continue
            if inrefs:
                mm = re.match(r"^\s{2}([A-Z0-9_]+):\s*(\S+)\s*$", line)
                if mm:
                    refs[mm.group(1)] = mm.group(2)
                elif line.strip() and not line.startswith(" "):
                    inrefs = False
        key = refs.get("NEWAPI_API_KEY") or refs.get("NEW_API_KEY")
    model = model or os.environ.get("TRIAGE_MODEL") or "deepseek-flash"
    if not base or not key:
        sys.exit("找不到模型端点：请设 TRIAGE_BASE_URL / TRIAGE_API_KEY / TRIAGE_MODEL，或 --no-llm")
    return base.rstrip("/"), key, model


def call_llm(base, key, model, payload, timeout=240):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": payload}],
        "temperature": 0, "max_tokens": 6000,
    }).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode())
    msg = j["choices"][0]["message"]
    return (msg.get("content") or "").strip(), (msg.get("reasoning_content") or "").strip()


def parse_verdicts(text):
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    i, j = raw.find("["), raw.rfind("]")
    if i >= 0 and j > i:
        raw = raw[i:j + 1]
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError:
        return None
    out = []
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        v = str(item.get("verdict", "")).strip()
        if v not in VERDICTS:
            continue
        out.append({"id": str(item.get("id", "")).strip(), "verdict": v,
                    "reason": str(item.get("reason", ""))[:160],
                    "action": str(item.get("action", ""))[:160]})
    return out or None


def judge_batch(convs, base, key, model, show, results, depth=0):
    """判一小批。推理模型偶尔会把 content 预算烧光返回空串，所以：先常规重试 →
    再从 reasoning_content 里捞 JSON → 还不行就二分批次重喂（人越少越稳）。"""
    tag = {c["username"]: "联系人%02d" % (i + 1) for i, c in enumerate(convs)}
    lines = []
    for c in convs:
        lines.append("[%s]" % tag[c["username"]])
        for m in c["msgs"][-show:]:
            lines.append("%s: %s" % (m["who"], m["text"][:180]))
        lines.append("")
    payload = "\n".join(lines)

    parsed = None
    for attempt in range(2):
        try:
            content, reasoning = call_llm(base, key, model, payload if attempt == 0 else
                                          payload + "\n\n上一次输出无法解析，请只输出 JSON 数组，不要任何其它文字。")
        except Exception as e:
            sys.exit("模型调用失败：%s" % e)
        parsed = parse_verdicts(content) or parse_verdicts(reasoning)
        if parsed:
            break

    if parsed:
        id2user = {v: k for k, v in tag.items()}
        got = 0
        for p in parsed:
            u = id2user.get(p["id"])
            if u:
                results[u] = p
                got += 1
        return got

    if len(convs) > 1 and depth < 4:
        mid = len(convs) // 2
        print("⚠️ 解析失败，二分重试（%d → %d + %d）" % (len(convs), mid, len(convs) - mid), file=sys.stderr)
        return (judge_batch(convs[:mid], base, key, model, show, results, depth + 1) +
                judge_batch(convs[mid:], base, key, model, show, results, depth + 1))

    print("⚠️ 单人仍无法解析，保守判为待我动作：%s" % convs[0]["name"], file=sys.stderr)
    return 0


def judge(convs, base, key, model, batch=6, show=8):
    results = {}
    for start in range(0, len(convs), batch):
        judge_batch(convs[start:start + batch], base, key, model, show, results)
    return results


# ---------------- 输出 ----------------
def main():
    ap = argparse.ArgumentParser(description="微信私聊来信语义分流")
    ap.add_argument("--hours", type=int, default=24, help="回看窗口（小时）")
    ap.add_argument("--show", type=int, default=8, help="每人送给模型的最近消息条数")
    ap.add_argument("--limit-people", type=int, default=0, help="只处理最近 N 人（调试用）")
    ap.add_argument("--json", default="", help="把结果写成 JSON 文件")
    ap.add_argument("--no-llm", action="store_true", help="只用机械规则（会误判，仅排障）")
    ap.add_argument("--quiet-paths", action="store_true")
    args = ap.parse_args()

    convs, me = collect(args.hours, args.limit_people or None)
    if not convs:
        print("窗口内没有私聊来信。")
        return

    if args.no_llm:
        for c in convs:
            last_from_me = c["msgs"][-1]["who"] == "我"
            c["verdict"] = "等对方" if last_from_me else "待我动作"
            c["reason"] = "机械规则：最后一条%s" % ("是我发的" if last_from_me else "是对方发的")
            c["action"] = ""
        model = "(无模型)"
    else:
        base, key, model = resolve_endpoint()
        if not args.quiet_paths:
            host = re.sub(r"^https?://", "", base).split("/")[0]
            print("模型端点：%s（模型 %s）" % (host, model), file=sys.stderr)
        judged = judge(convs, base, key, model, show=args.show)
        for c in convs:
            v = judged.get(c["username"])
            c["verdict"] = v["verdict"] if v else "待我动作"
            c["reason"] = v["reason"] if v else "模型未返回结论，保守判为待我动作"
            c["action"] = v["action"] if v else ""

    order = {v: i for i, v in enumerate(VERDICTS)}
    convs.sort(key=lambda c: (order[c["verdict"]], -c["msgs"][-1]["ts"]))
    counts = Counter(c["verdict"] for c in convs)

    def fmt(ts):
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")

    print("\n窗口：过去 %d 小时 ｜ 私聊联系人 %d 人 ｜ 我的 wxid：%s ｜ 判定：%s"
          % (args.hours, len(convs), me, model))
    print("汇总：" + " ｜ ".join("%s %d 人" % (v, counts.get(v, 0)) for v in VERDICTS))
    print()
    for v in VERDICTS:
        group = [c for c in convs if c["verdict"] == v]
        if not group:
            continue
        mark = {"待我动作": "⏳", "已收尾": "✅", "等对方": "⏳", "无实质": "·"}[v]
        print("=== %s %s（%d 人）===" % (mark, v, len(group)))
        for c in group:
            tail = c["msgs"][-1]
            print("  · %-22s 最后 %s %s: %s" % (c["name"][:22], fmt(tail["ts"]), tail["who"],
                                               tail["text"][:56]))
            if c["reason"]:
                print("      依据：%s" % c["reason"])
            if c["action"]:
                print("      动作：%s" % c["action"])
        print()

    if args.json:
        out = [{"name": c["name"], "username": c["username"], "verdict": c["verdict"],
                "reason": c["reason"], "action": c["action"],
                "last_at": datetime.fromtimestamp(c["msgs"][-1]["ts"]).strftime("%Y-%m-%d %H:%M"),
                "tail": [{"who": m["who"], "at": datetime.fromtimestamp(m["ts"]).strftime("%m-%d %H:%M"),
                          "text": m["text"]} for m in c["msgs"][-args.show:]]} for c in convs]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("结果已写入 %s" % args.json)


if __name__ == "__main__":
    main()
