#!/usr/bin/env node
"use strict";
/**
 * wechat-todo-feishu 一键安装器
 *   node bin/wechat-todo-feishu.js
 * 干三件事：装 skills（wechat-todo-feishu + wechat-local）→ 铺设 wechat-cli 工具链 →
 *          自动提取解密密钥（wxcli init）→ 预检本机 lark-cli（飞书同步走它，不写任何 MCP 配置）
 * 兼容：ZCode / OpenClaw（~/.agents|~/.zcode/skills）、Claude Code（~/.claude/skills）
 * 环境变量：WECHAT_TODO_SKILLS_DIR 指定 skills 目录；--skip-init 跳过解密密钥初始化
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
// 包内 vendor 只含 tool/ deps/ wxcli.cmd（Apache-2.0），绝不含也不会覆盖
// 用户本机的 all_keys.json（解密密钥）与 config.json（db_dir 配置）
const wcSrc = path.join(pkgRoot, "vendor", "wechat-cli");
const wcDest = path.join(home, ".wechat-cli");
let wcNote = "-";
if (fs.existsSync(wcSrc)) {
  fs.mkdirSync(wcDest, { recursive: true });
  for (const dir of ["tool", "deps"]) {
    fs.cpSync(path.join(wcSrc, dir), path.join(wcDest, dir), { recursive: true, force: true });
  }
  fs.copyFileSync(path.join(wcSrc, "wxcli.cmd"), path.join(wcDest, "wxcli.cmd"));
  wcNote = "wechat-cli-plus 0.2.4 (Apache-2.0) → ~/.wechat-cli（已存在则平滑更新）";
  ok("微信工具链 " + wcNote);
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
      initNote = "待手动 init";
      warn("自动 init 未成功（多半是微信没开）。保持微信运行后执行：~/.wechat-cli/wxcli.cmd init");
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
let larkNote = "未安装";
const larkPath = findLarkCli();
if (larkPath) {
  info("检测到 lark-cli：" + larkPath + "，验证登录态…");
  try {
    const r = cp.spawnSync(larkPath, ["auth", "status", "--json", "--verify"], {
      encoding: "utf8", timeout: 30000,
    });
    const out = (r.stdout || "") + (r.stderr || "");
    if (/ok"\s*:\s*true|"status"\s*:\s*"ok"|logged.?in|已登录/i.test(out) && !/not.?logged|未登录|invalid/i.test(out)) {
      larkNote = "已连接（登录态有效）";
      ok("lark-cli 登录态有效，飞书同步就绪");
    } else {
      larkNote = "已安装但登录态未确认";
      warn("lark-cli 登录态校验未通过，请先完成 lark-cli 登录（skill 首次引导也会再验一次）");
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
console.log("  · 解密密钥   : " + initNote);
console.log("  · lark-cli   : " + larkNote);
console.log("");
console.log("▶ 下一步：在你的 AI 助手里说「更新待办」——首次会引导你新建专用工作文件夹、");
console.log("  验证 lark-cli 并创建飞书台账（多维表格「微信待办台账」）。");
console.log("  基于 syskuku/wechat-todo 改造 · 原作 Syskuku_暮雪逢樱 www.imikufans.com");
