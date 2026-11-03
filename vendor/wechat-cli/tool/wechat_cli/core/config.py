"""配置加载 — 从 ~/.wechat-cli/ 读取自包含配置"""

import glob as glob_mod
import json
import os
import platform
import sys

_SYSTEM = platform.system().lower()

if _SYSTEM == "linux":
    _DEFAULT_PROCESS = "wechat"
elif _SYSTEM == "darwin":
    _DEFAULT_PROCESS = "WeChat"
else:
    _DEFAULT_PROCESS = "Weixin.exe"

# CLI 状态目录
STATE_DIR = os.path.expanduser("~/.wechat-cli")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
KEYS_FILE = os.path.join(STATE_DIR, "all_keys.json")


def _choose_candidate(candidates):
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        if not sys.stdin.isatty():
            return candidates[0]
        print("[!] 检测到多个微信数据目录:")
        for i, c in enumerate(candidates, 1):
            print(f"    {i}. {c}")
        print("    0. 跳过")
        try:
            while True:
                choice = input(f"请选择 [0-{len(candidates)}]: ").strip()
                if choice == "0":
                    return None
                if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                    return candidates[int(choice) - 1]
                print("    无效输入")
        except (EOFError, KeyboardInterrupt):
            print()
            return None
    return None


def _read_text_any_encoding(path):
    """按常见编码读文本（腾讯 ini 实测可能是 UTF-8，也可能是 GBK）。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    return None


def _existing_dirs_in_ini(path):
    """从 xwechat 的 *.ini 中挖出所有"确实存在的目录"。

    该文件有多种形态：`Key: D:\\path` 单行、或 `MyDocument:` 换行后跟路径。
    旧实现把整个文件内容当成一个路径、遇换行就整份丢弃，于是 4.x 微信在多数机器上
    探测失败（只能手动 --db-dir）。这里改成逐行扫描，两种形态都能命中。
    """
    text = _read_text_any_encoding(path)
    if not text:
        return []
    roots = []
    for raw_line in text.splitlines():
        line = raw_line.strip().strip('"').strip("'")
        if not line or "\x00" in line:
            continue
        candidates = [line]
        for sep in (":", "="):
            if sep in line:
                candidates.append(line.split(sep, 1)[1].strip().strip('"').strip("'"))
        for cand in candidates:
            if cand and os.path.isabs(cand) and os.path.isdir(cand):
                roots.append(cand)
    return roots


def _db_storage_under(root, seen):
    """收集 <root>/xwechat_files/*/db_storage，跨 root 去重。"""
    found = []
    pattern = os.path.join(root, "xwechat_files", "*", "db_storage")
    for match in glob_mod.glob(pattern):
        if not os.path.isdir(match):
            continue
        normalized = os.path.normcase(os.path.normpath(match))
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(match)
    return found


def _auto_detect_db_dir_windows():
    seen = set()
    candidates = []

    # ① 配置 ini 里登记的安装根目录（优先：用户可能把库放在了非默认盘）
    data_roots = []
    config_dir = os.path.join(os.environ.get("APPDATA", ""), "Tencent", "xwechat", "config")
    if os.path.isdir(config_dir):
        for ini_file in glob_mod.glob(os.path.join(config_dir, "*.ini")):
            data_roots.extend(_existing_dirs_in_ini(ini_file))
    for root in data_roots:
        candidates.extend(_db_storage_under(root, seen))

    # ② 兜底：微信 4.x 默认落在「文档」下（ini 缺失或未写 MyDocument 时命中）
    home = os.path.expanduser("~")
    for root in (os.path.join(home, "Documents"), os.path.join(home, "文档")):
        candidates.extend(_db_storage_under(root, seen))

    return _choose_candidate(candidates)


def _auto_detect_db_dir_linux():
    seen = set()
    candidates = []
    search_roots = [os.path.expanduser("~/Documents/xwechat_files")]
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        try:
            sudo_home = pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            sudo_home = None
        if sudo_home:
            fallback = os.path.join(sudo_home, "Documents", "xwechat_files")
            if fallback not in search_roots:
                search_roots.append(fallback)
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        pattern = os.path.join(root, "*", "db_storage")
        for match in glob_mod.glob(pattern):
            normalized = os.path.normcase(os.path.normpath(match))
            if os.path.isdir(match) and normalized not in seen:
                seen.add(normalized)
                candidates.append(match)
    old_path = os.path.expanduser("~/.local/share/weixin/data/db_storage")
    if os.path.isdir(old_path):
        normalized = os.path.normcase(os.path.normpath(old_path))
        if normalized not in seen:
            candidates.append(old_path)

    def _mtime(path):
        msg_dir = os.path.join(path, "message")
        target = msg_dir if os.path.isdir(msg_dir) else path
        try:
            return os.path.getmtime(target)
        except OSError:
            return 0
    candidates.sort(key=_mtime, reverse=True)
    return _choose_candidate(candidates)


def _auto_detect_db_dir_macos():
    base = os.path.expanduser("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
    if not os.path.isdir(base):
        return None
    seen = set()
    candidates = []
    pattern = os.path.join(base, "*", "db_storage")
    for match in glob_mod.glob(pattern):
        normalized = os.path.normcase(os.path.normpath(match))
        if os.path.isdir(match) and normalized not in seen:
            seen.add(normalized)
            candidates.append(match)
    return _choose_candidate(candidates)


def auto_detect_db_dir():
    if _SYSTEM == "windows":
        return _auto_detect_db_dir_windows()
    if _SYSTEM == "linux":
        return _auto_detect_db_dir_linux()
    if _SYSTEM == "darwin":
        return _auto_detect_db_dir_macos()
    return None


def load_config(config_path=None):
    """加载配置。默认从 ~/.wechat-cli/config.json 读取。"""
    if config_path is None:
        config_path = CONFIG_FILE

    cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError:
            cfg = {}

    # db_dir 缺失时，自动检测
    db_dir = cfg.get("db_dir", "")
    if not db_dir:
        detected = auto_detect_db_dir()
        if detected:
            cfg["db_dir"] = detected
        else:
            raise FileNotFoundError(
                "未找到微信数据目录。\n"
                "请运行: wechat-cli init"
            )

    # 设置默认值
    state_dir = os.path.dirname(os.path.abspath(config_path))
    cfg.setdefault("keys_file", os.path.join(state_dir, "all_keys.json"))
    cfg.setdefault("decrypted_dir", os.path.join(state_dir, "decrypted"))
    cfg.setdefault("decoded_image_dir", os.path.join(state_dir, "decoded_images"))
    cfg.setdefault("wechat_process", _DEFAULT_PROCESS)

    # 所有路径确保为绝对路径
    for key in ("db_dir", "keys_file", "decrypted_dir", "decoded_image_dir"):
        if key in cfg and not os.path.isabs(cfg[key]):
            cfg[key] = os.path.join(state_dir, cfg[key])

    # 推导微信数据根目录
    db_dir = cfg.get("db_dir", "")
    if db_dir and os.path.basename(db_dir) == "db_storage":
        cfg["wechat_base_dir"] = os.path.dirname(db_dir)
    else:
        cfg["wechat_base_dir"] = db_dir

    return cfg
