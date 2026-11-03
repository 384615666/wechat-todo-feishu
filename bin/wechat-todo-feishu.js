#!/usr/bin/env node
"use strict";
/**
 * wechat-todo-feishu 一键安装器
 *   node bin/wechat-todo-feishu.js
 * 干四件事：装 skills（wechat-todo-feishu + wechat-local）→ 铺设 wechat-cli 工具链
 *          （并按宿主架构自愈原生依赖）→ 自动提取解密密钥（wxcli init）
 *          → 预检本机 lark-cli（飞书同步走它，用户身份/机器人身份分开判定，不写任何 MCP 配置）
 * 兼容：ZCode / OpenClaw（~/.agents|~/.zcode/skills）、Claude Code（~/.claude/skills）
 * 环境变量：WECHAT_TODO_SKILLS_DIR 指定 skills 目录；--skip-init 跳过解密密钥初始化；
 *          WECHAT_TODO_DEBUG=1 打印原生依赖自检细节
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");

const pkgRoot = path.join(__dirname, "..");
const home = os.homedir();
const args = process.argv.slice(2);
const skipInit = args.includes("--skip-init");
const ok = (m) => console.log("✅ " + m);
const info = (m) => console.log("ℹ️ " + m);
const warn = (m) => console.log("⚠️ " + m);

/* ---------- A. 安装 skills ---------- */
const skillsSrc = path.join(pkgRoot, "skills");
const skillNames = fs.readdirSync(skillsSrc).filter((f) =>
  fs.statSync(path.join(skillsSrc, f)).isDirectory()
);
const candidates = [
  [path.join(home, ".agents", "skills"), "ZCode / OpenClaw"],
  [path.join(home, ".zcode", "skills"), "ZCode（高优先级）"],
  [path.join(home, ".claude", "skills"), "Claude Code"],
];
let targets;
if (process.env.WECHAT_TODO_SKILLS_DIR) {
  targets = [[path.resolve(process.env.WECHAT_TODO_SKILLS_DIR), "自定义目录(WECHAT_TODO_SKILLS_DIR)"]];
} else {
  targets = candidates.filter(([dir]) => fs.existsSync(path.dirname(dir)));
  if (targets.length === 0) targets = [candidates[0]];
}
for (const [root, label] of targets) {
  for (const name of skillNames) {
    const dest = path.join(root, name);
    fs.mkdirSync(dest, { recursive: true });
    fs.cpSync(path.join(skillsSrc, name), dest, { recursive: true, force: true });
  }
  ok("skills 装入 " + root + "  ← " + label + "（" + skillNames.join("、") + "）");
}

/* ---------- B. 铺设 wechat-cli 工具链 ---------- */
// vendor 里的原生模块（.pyd）与打包机的 CPU 架构/ABI 绑定，本包按 Windows ARM64 打包；
// 在 x64 Windows 上加载即 OSError: Cannot load '_cpuid_c.pyd': [WinError 193]。
// 所以装完必须按宿主架构自检：剔除不符的 → 用本机 python 补装同版本轮子。
const NATIVE_PKGS = ["pycryptodome==3.23.0", "psutil==7.2.2", "zstandard==0.25.0"];
const pyExe = process.platform === "win32" ? "python" : "python3";
let nativeNote = "-";

function havePython() {
  try {
    return cp.spawnSync(pyExe, ["-V"], { encoding: "utf8", timeout: 20000 }).status === 0;
  } catch (e) {
    return false;
  }
}

function probeNativeDeps(depsDir) {
  const r = cp.spawnSync(pyExe, ["-c", "import Crypto.Cipher.AES, psutil, zstandard"], {
    encoding: "utf8", timeout: 90000,
    env: Object.assign({}, process.env, { PYTHONPATH: depsDir, PYTHONIOENCODING: "utf-8" }),
  });
  const tail = ((r.stderr || "") + (r.stdout || "")).trim().split(/\r?\n/).filter(Boolean).pop() || "";
  return { ok: r.status === 0, tail };
}

function peMachine(file) { // 仅 Windows PE 有效；非 PE/读失败返回 null
  try {
    const head = Buffer.alloc(0x40);
    let fd = fs.openSync(file, "r");
    fs.readSync(fd, head, 0, 0x40, 0);
    fs.closeSync(fd);
    if (head.readUInt16LE(0) !== 0x5a4d) return null; // "MZ"
    const pe = Buffer.alloc(6);
    fd = fs.openSync(file, "r");
    fs.readSync(fd, pe, 0, 6, head.readUInt32LE(0x3c));
    fs.closeSync(fd);
    if (pe.readUInt32LE(0) !== 0x00004550) return null; // "PE\0\0"
    return pe.readUInt16LE(4); // 0x8664=x64, 0xAA64=ARM64
  } catch (e) {
    return null;
  }
}

function purgeWrongArch(depsDir) {
  if (process.platform !== "win32") return [];
  const host = process.arch === "arm64" ? 0xaa64 : 0x8664;
  const removed = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) {
      return;
    }
    for (const ent of entries) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) { walk(p); continue; }
      if (!ent.name.endsWith(".pyd")) continue;
      const m = peMachine(p);
      if (m && m !== host) { fs.rmSync(p, { force: true }); removed.push(path.relative(depsDir, p)); }
    }
  };
  walk(depsDir);
  return removed;
}

function ensureNativeDeps(depsDir) {
  if (path.basename(depsDir) !== "deps") {
    warn("内部参数异常：原生依赖目录应指向 ~/.wechat-cli/deps，实际为 " + depsDir);
    return "跳过（路径异常）";
  }
  if (!fs.existsSync(depsDir)) return "无 deps 目录，跳过";
  if (!havePython()) {
    warn("未找到 python（" + pyExe + " 不在 PATH）：微信读取无法自检，请先安装 Python 3.11+");
    return "未自检（缺 python）";
  }
  const removed = purgeWrongArch(depsDir);
  let probe = probeNativeDeps(depsDir);
  if (process.env.WECHAT_TODO_DEBUG) {
    console.log("[debug] deps=" + depsDir + " purge=" + removed.length + " probe=" + JSON.stringify(probe));
  }
  if (probe.ok) {
    ok("原生依赖可用" + (removed.length ? "（已剔除 " + removed.length + " 个与本机架构不符的模块）" : ""));
    return removed.length ? "已剔除 " + removed.length + " 个异架构模块" : "与本机架构一致";
  }
  info("原生依赖与本机架构/ABI 不符，用本机 python 补装 " + NATIVE_PKGS.join(" / ") + " …");
  const cleanEnv = Object.assign({}, process.env);
  delete cleanEnv.PYTHONPATH;
  const r = cp.spawnSync(pyExe, ["-m", "pip", "install", "--only-binary=:all:", "--no-cache-dir",
    "--upgrade", "--no-deps", "--target", depsDir].concat(NATIVE_PKGS),
    { encoding: "utf8", timeout: 300000, env: cleanEnv });
  purgeWrongArch(depsDir);
  probe = probeNativeDeps(depsDir);
  if (probe.ok) {
    ok("原生依赖已自愈（已按 " + process.arch + " 补装）");
    return "已按 " + process.arch + " 补装";
  }
  const why = probe.tail || ((r.stderr || "") + (r.stdout || "")).trim().split(/\r?\n/).filter(Boolean).pop() || "未知错误";
  warn("原生依赖补装失败：" + why + "（多半是没网或 pip 不可用）");
  warn("可手动执行：python -m pip install --target \"" + depsDir + "\" " + NATIVE_PKGS.join(" "));
  return "自愈失败，需手动补装";
}

// 铺 deps 时跳过与本机架构不符的 .pyd：否则 vendor 里的 ARM64 原生模块会覆盖掉
// 上次已补装好的 x64 同名文件（pycryptodome 的扩展名不带 ABI 后缀，必然同名冲突），
// 每次重装都得重新 pip 一遍。跳过之后本机架构的模块能原地保留，重装即幂等。
function copyDepsFiltered(srcDeps, destDeps) {
  const host = process.platform === "win32" ? (process.arch === "arm64" ? 0xaa64 : 0x8664) : null;
  fs.cpSync(srcDeps, destDeps, {
    recursive: true, force: true,
    filter: (src) => {
      if (!host || !src.toLowerCase().endsWith(".pyd")) return true;
      const m = peMachine(src);
      return !m || m === host; // 非 PE（读不出架构）或同架构才铺
    },
  });
}

// 包内 vendor 只含 tool/ deps/ wxcli.cmd（Apache-2.0），绝不含也不会覆盖
// 用户本机的 all_keys.json（解密密钥）与 config.json（db_dir 配置）
const wcSrc = path.join(pkgRoot, "vendor", "wechat-cli");
const wcDest = path.join(home, ".wechat-cli");
let wcNote = "-";
if (fs.existsSync(wcSrc)) {
  fs.mkdirSync(wcDest, { recursive: true });
  fs.cpSync(path.join(wcSrc, "tool"), path.join(wcDest, "tool"), { recursive: true, force: true });
  copyDepsFiltered(path.join(wcSrc, "deps"), path.join(wcDest, "deps"));
  fs.copyFileSync(path.join(wcSrc, "wxcli.cmd"), path.join(wcDest, "wxcli.cmd"));
  wcNote = "wechat-cli-plus 0.2.4 (Apache-2.0) → ~/.wechat-cli（已存在则平滑更新）";
  ok("微信工具链 " + wcNote);
  nativeNote = ensureNativeDeps(path.join(wcDest, "deps"));
} else {
  warn("包内缺少 vendor/wechat-cli，微信读取能力未安装");
}

/* ---------- C. 解密密钥初始化 ---------- */
let initNote = "跳过";
const keysFile = path.join(wcDest, "all_keys.json");
if (fs.existsSync(keysFile)) {
  initNote = "密钥已存在（沿用本机）";
  info("解密密钥已存在，跳过初始化");
} else if (skipInit) {
  initNote = "已按 --skip-init 跳过";
} else if (process.platform === "win32") {
  info("未检测到解密密钥，自动执行 wxcli init（请确认微信客户端正在运行）…");
  try {
    const r = cp.spawnSync("cmd", ["/c", path.join(wcDest, "wxcli.cmd"), "init"], {
      encoding: "utf8", timeout: 120000,
    });
    if (r.status === 0) { initNote = "init 自动完成"; ok("解密密钥已生成，微信读取就绪"); }
    else {
      const tail = ((r.stderr || "") + (r.stdout || "")).trim().split(/\r?\n/).filter(Boolean).pop() || "";
      initNote = "待手动 init";
      warn("自动 init 未成功：" + (tail || "未知原因"));
      warn("先确认微信客户端正在运行；若提示找不到数据目录，执行：~/.wechat-cli/wxcli.cmd init --db-dir \"<微信数据目录>\\db_storage\"");
    }
  } catch (e) {
    initNote = "待手动 init";
    warn("init 异常：" + e.message + "；稍后手动执行 ~/.wechat-cli/wxcli.cmd init");
  }
} else {
  initNote = "非 Windows 需手动安装";
  warn("非 Windows 平台：请参考上游 github.com/maomao3334/wechat-cli-plus 手动安装");
}

/* ---------- D. lark-cli 就绪预检（飞书同步走本机 lark-cli，免建应用免 MCP） ---------- */
function findLarkCli() {
  const probe = process.platform === "win32" ? "where" : "which";
  try {
    const r = cp.spawnSync(probe, [process.platform === "win32" ? "lark-cli.cmd" : "lark-cli"], {
      encoding: "utf8",
    });
    const line = (r.stdout || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean)[0];
    return line || null;
  } catch (e) {
    return null;
  }
}
// Node 20+ 出于安全限制拒绝直接 spawn .cmd/.bat（静默返回 EINVAL），Windows 上必须经 cmd /c 调。
function spawnCli(file, args, opts) {
  const o = Object.assign({ encoding: "utf8" }, opts || {});
  if (process.platform === "win32" && /\.(cmd|bat)$/i.test(file)) {
    return cp.spawnSync(process.env.ComSpec || "cmd.exe", ["/c", file].concat(args), o);
  }
  return cp.spawnSync(file, args, o);
}

function parseLooseJson(text) {
  const s = String(text || "");
  const i = s.indexOf("{");
  if (i < 0) return null;
  try {
    return JSON.parse(s.slice(i));
  } catch (e) {
    return null;
  }
}

// lark-cli 的身份是分层的：bot 就绪 ≠ 用户身份可用。而 skill 明确要求 --as user，
// 所以必须分别判定，不能拿机器人身份冒充（旧实现只跑正则，既会误报也会漏报）。
function judgeLark(st) {
  const ids = (st && st.identities) || {};
  const user = ids.user || {};
  const bot = ids.bot || {};
  const userOk = user.status === "ready" && user.tokenStatus !== "expired";
  const botOk = bot.status === "ready";
  if (userOk) {
    return {
      level: "ok", note: "已连接（用户身份 " + (user.userName || user.openId || "user") + "）",
      msg: "lark-cli 用户身份有效，飞书同步就绪",
    };
  }
  if (botOk) {
    const why = user.tokenStatus === "expired" ? "已过期" : ("缺失（" + (user.message || "no user token") + "）");
    return {
      level: "warn", note: "仅机器人身份就绪，用户身份" + (user.tokenStatus === "expired" ? "过期" : "缺失"),
      msg: "lark-cli 只有机器人身份可用，用户身份" + why + "。skill 要求 --as user，请执行：lark-cli auth login",
    };
  }
  return { level: "warn", note: "未登录", msg: "lark-cli 未登录，请先执行：lark-cli auth login" };
}

let larkNote = "未安装";
const larkPath = findLarkCli();
if (larkPath) {
  info("检测到 lark-cli：" + larkPath + "，验证登录态…");
  try {
    const r = spawnCli(larkPath, ["auth", "status", "--json", "--verify"], { timeout: 30000 });
    if (r.error) throw new Error((r.error.code || r.error.message) + "（调用 " + larkPath + " 失败）");
    const st = parseLooseJson(r.stdout) || parseLooseJson(r.stderr);
    if (st) {
      const v = judgeLark(st);
      larkNote = v.note;
      if (v.level === "ok") ok(v.msg); else warn(v.msg);
    } else {
      // 老版本 lark-cli 可能不吐 JSON，退回文本判断
      const out = (r.stdout || "") + (r.stderr || "");
      if (/ok"\s*:\s*true|"status"\s*:\s*"ok"|logged.?in|已登录/i.test(out) && !/not.?logged|未登录|invalid/i.test(out)) {
        larkNote = "已连接（登录态有效）";
        ok("lark-cli 登录态有效，飞书同步就绪");
      } else {
        larkNote = "已安装但登录态未确认";
        warn("lark-cli 登录态校验未通过，请先完成 lark-cli 登录（skill 首次引导也会再验一次）");
      }
    }
  } catch (e) {
    larkNote = "已安装但校验失败";
    warn("lark-cli auth status 执行失败：" + e.message + "（首次运行时 skill 会再验一次）");
  }
} else {
  warn("未找到 lark-cli：飞书同步将不可用。请先安装并登录 lark-cli（已有登录的机器请检查 PATH）");
}

/* ---------- E. 汇总 ---------- */
console.log("");
console.log("════════════════════════════════════════════════════");
console.log("📦 wechat-todo-feishu 安装完成");
console.log("  · skills     : " + skillNames.join(", ") + " → " + targets.map((t) => t[0]).join("  ;  "));
console.log("  · 微信工具链 : " + wcNote);
console.log("  · 原生依赖   : " + nativeNote);
console.log("  · 解密密钥   : " + initNote);
console.log("  · lark-cli   : " + larkNote);
console.log("");
console.log("▶ 下一步：在你的 AI 助手里说「更新待办」——首次会引导你新建专用工作文件夹、");
console.log("  验证 lark-cli 并创建飞书台账（多维表格「微信待办台账」）。");
console.log("  基于 syskuku/wechat-todo 改造 · 原作 Syskuku_暮雪逢樱 www.imikufans.com");
