#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mcu-lab —— 51 单片机开发闭环命令行内核

把「写 C51 -> Keil 编译出 hex -> Proteus 仿真 -> 确定性判定通过/失败」串成一条命令。
所有子命令都输出单行 JSON，方便被 AI 工具直接调用。

用法：
  python mcu_lab.py check                                  # 环境自检
  python mcu_lab.py build  <file.c>                        # 编译出 hex
  python mcu_lab.py sim    <dsn> [--seconds 8] [--shot p]  # 打开电路跑仿真并截图
  python mcu_lab.py verify <dsn> [--wait 6]                # 确定性判定是否在跑
  python mcu_lab.py run    <file.c> <dsn> [--hex-name x.hex]# 编译+仿真+判定（推荐）
  python mcu_lab.py list                                   # 列出可用电路模板

设计原则：
  1) 不修改用户的原始电路文件——每次都在 work\<时间戳>\ 下做副本再仿真
  2) 判定不靠截图猜，用 verify.py 的进程 CPU 增长 + 失败标记文本
  3) 输出 JSON，字段稳定
"""
import argparse, importlib.util, json, os, shutil, subprocess, sys, time, glob

# Windows 控制台默认是 GBK：json.dumps(ensure_ascii=False) 一旦遇到 GBK 编不出的
# 字符（例如子进程输出里的 U+FFFD）就会 UnicodeEncodeError，整个工具链报错。
# 统一把标准输出切到 UTF-8，与插件侧 d.toString('utf8') 对齐。
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _dec(b):
    """子进程输出解码：Keil/build51 的中文提示是 GBK，先 UTF-8 再 GBK 兜底。"""
    if isinstance(b, str):
        return b
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")


def _env(name, default=""):
    """取环境变量；未设置或为空串时用 default。"""
    value = os.environ.get(name)
    return value if value else default


# ---------------------------------------------------------------------------
# 外部依赖位置：全部可用环境变量覆盖，不要写死在代码里。
#
#   DSH_MCU_LAB_IFACE      接口脚本目录（build51.py / proteus_ctl.py / verify.py）。
#                          默认指向随本仓库发布的 kernel/iface/。
#   DSH_MCU_LAB_KEIL       Keil C51 的 C51.exe 完整路径（仅 `check` 子命令体检用）。
#   DSH_MCU_LAB_ISIS       Proteus ISIS.EXE 完整路径（仅 `check` 子命令体检用）。
#   DSH_MCU_LAB_DSN_INDEX  电路索引 JSON（`check` 与 `list` 用；用自己的电路时可不设）。
#
# KEIL / ISIS / DSN_INDEX 留空表示"未设置"：`check` 会据实报 false，不猜测路径。
# ---------------------------------------------------------------------------
IFACE = _env("DSH_MCU_LAB_IFACE", os.path.join(HERE, "iface"))
KEIL = _env("DSH_MCU_LAB_KEIL", r"D:\keil\C51\BIN\C51.exe")
ISIS = _env("DSH_MCU_LAB_ISIS", r"D:\Proteus7\BIN\ISIS.EXE")
DSN_INDEX = _env("DSH_MCU_LAB_DSN_INDEX")

BUILD51 = os.path.join(IFACE, "build51.py")
PROTEUS_CTL = os.path.join(IFACE, "proteus_ctl.py")
VERIFY = os.path.join(IFACE, "verify.py")
PY = sys.executable
SDCC_SCRIPT = os.path.join(IFACE, "sdcc51.py")


def _tool_path(name):
    return shutil.which(name) or ""


def _compile_backend(choice="auto"):
    keil_ok = os.path.isfile(KEIL) and os.path.isfile(BUILD51)
    sdcc_ok = bool(_tool_path("sdcc")) and os.path.isfile(SDCC_SCRIPT)
    choice = (choice or "auto").lower()
    if choice == "keil":
        return "keil" if keil_ok else None
    if choice == "sdcc":
        return "sdcc" if sdcc_ok else None
    return "keil" if keil_ok else ("sdcc" if sdcc_ok else None)


def _build_source(src, choice="auto"):
    _clear_previous_outputs(src)
    compiler = _compile_backend(choice)
    if compiler == "keil":
        return run([PY, BUILD51, src], timeout=180), compiler
    if compiler == "sdcc":
        return run([PY, SDCC_SCRIPT, src], timeout=180), compiler
    return (127, "未找到可用编译器：请安装 Keil C51 或 SDCC（winget install --id Sdcc.Sdcc -e）"), None


def _hex_candidates(src):
    base = os.path.splitext(src)[0]
    return [p for p in (base + ".hex", base.upper() + ".hex", base + ".ihx") if os.path.exists(p)]


def _clear_previous_outputs(src):
    base = os.path.splitext(src)[0]
    for path in (base + ".hex", base.upper() + ".hex", base + ".ihx"):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def run(cmd, timeout=300, cwd=None):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd)
        return p.returncode, _dec(p.stdout) + _dec(p.stderr)
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT after %ss" % timeout
    except Exception as e:
        return 125, "RUN_FAILED: %s" % e


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False))
    return code


# dsn_index.json 只服务 `list`（列出课程电路模板），是**可选件**：它索引的是各人自备的
# 电路文件，本仓库不附带电路索引。所以它不参与"必需项"判定，缺失只作为提示。
OPTIONAL_CHECKS = ("dsn_index.json",)


def cmd_check(_a):
    sdcc = _tool_path("sdcc")
    items = {
        "keil_c51": os.path.exists(KEIL),
        "proteus_isis": os.path.exists(ISIS),
        "sdcc": bool(sdcc),
        "python3": bool(PY),
        "pywin32": importlib.util.find_spec("win32gui") is not None,
        "pillow": importlib.util.find_spec("PIL") is not None,
        "build51.py": os.path.exists(BUILD51),
        "proteus_ctl.py": os.path.exists(PROTEUS_CTL),
        "verify.py": os.path.exists(VERIFY),
        "dsn_index.json": os.path.exists(DSN_INDEX),
    }
    capabilities = {
        "offline_check": items["python3"] and os.path.isfile(os.path.join(HERE, "mcu_lab.py")),
        "sdcc_build": items["sdcc"] and os.path.isfile(SDCC_SCRIPT),
        "keil_build": items["keil_c51"] and items["build51.py"],
        "proteus_sim": items["proteus_isis"] and items["proteus_ctl.py"] and items["pywin32"] and items["pillow"],
        "offline_verify": items["python3"] and items["verify.py"],
    }
    ok = all(capabilities.values())
    hints = []
    if not items["sdcc"]:
        hints.append("安装 SDCC：winget install --id Sdcc.Sdcc -e，或把 sdcc.exe 加入 PATH")
    if not items["keil_c51"]:
        hints.append("未检测到 Keil C51：设置 DSH_MCU_LAB_KEIL 指向 C51.exe；Keil 编译未验证")
    if not items["proteus_isis"]:
        hints.append("未检测到 Proteus ISIS：设置 DSH_MCU_LAB_ISIS 指向 ISIS.EXE；商业仿真未验证")
    if not items["pywin32"] or not items["pillow"]:
        hints.append("Proteus 接口还需要依赖：python -m pip install pywin32 Pillow")
    return out({
        "ok": ok,
        "checks": items,
        "capabilities": capabilities,
        "compiler_selected": _compile_backend(),
        "hints": hints,
        "optional": {k: items[k] for k in OPTIONAL_CHECKS},
        "interface_dir": IFACE,
    }, 0 if ok else 1)


def cmd_build(a):
    src = os.path.abspath(a.file)
    if not os.path.exists(src):
        return out({"ok": False, "error": "源文件不存在: %s" % src}, 2)
    (rc, log), compiler = _build_source(src, getattr(a, "compiler", "auto"))
    hexes = _hex_candidates(src)
    if rc == 0 and not hexes:
        # 兜底：编译器可能把 hex 写成别的名字。只在本次编译成功时找，
        # 否则会把上一次编译残留的（甚至别的源文件的）hex 当成本次产物报出去。
        cand = glob.glob(os.path.join(os.path.dirname(src), "*.hex"))
        hexes = [cand[0]] if cand else []
    return out({
        "ok": rc == 0 and bool(hexes), "compiler": compiler,
        "rc": rc, "hex": hexes[0] if hexes else None,
        "log_tail": log[-1500:],
    }, 0 if rc == 0 and hexes else 1)


def _stage_dsn(dsn, hex_path, hex_name=None):
    """把 DSN 和 hex 复制到独立工作目录，绝不改原文件。"""
    if not os.path.isfile(dsn):
        raise FileNotFoundError("电路文件不存在: %s" % dsn)
    os.makedirs(WORK, exist_ok=True)
    wd = os.path.join(WORK, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(wd, exist_ok=True)
    dsn_src = os.path.abspath(dsn)
    dsn_dst = os.path.join(wd, os.path.basename(dsn_src))
    shutil.copy2(dsn_src, dsn_dst)
    target_hex = None
    if hex_path:
        name = hex_name or (os.path.splitext(os.path.basename(dsn_src))[0] + ".hex")
        target_hex = os.path.join(wd, name)
        shutil.copy2(hex_path, target_hex)
    return wd, dsn_dst, target_hex


def cmd_sim(a):
    if not os.path.isfile(a.dsn):
        return out({"ok": False, "stage": "sim", "error": "电路文件不存在: %s" % a.dsn}, 2)
    wd, dsn_dst, _ = _stage_dsn(a.dsn, None)
    shot = os.path.abspath(a.shot) if a.shot else os.path.join(wd, "sim.png")
    rc, log = run([PY, PROTEUS_CTL, "--dsn", dsn_dst, "--run-seconds", str(a.seconds),
                   "--shot", shot, "--kill"], timeout=180)
    return out({"ok": rc == 0 and os.path.exists(shot), "rc": rc,
                "shot": shot if os.path.exists(shot) else None,
                "workdir": wd, "log_tail": log[-800:]}, 0 if rc == 0 else 1)


def cmd_verify(a):
    if not os.path.isfile(a.dsn):
        return out({"ok": False, "stage": "verify", "error": "电路文件不存在: %s" % a.dsn}, 2)
    wd, dsn_dst, _ = _stage_dsn(a.dsn, None)
    ev = os.path.abspath(a.evidence_dir) if a.evidence_dir else os.path.join(wd, "evidence")
    os.makedirs(ev, exist_ok=True)
    verify_args = [PY, VERIFY, "--dsn", dsn_dst, "--wait", str(a.wait), "--evidence-dir", ev]
    if a.backend:
        verify_args += ["--backend", a.backend]
    rc, log = run(verify_args, timeout=180)
    verdict = None
    for line in reversed((log or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                verdict = json.loads(line)
                break
            except Exception:
                continue
    if verdict is None:
        return out({"ok": False, "rc": rc, "error": "验证器未返回 JSON", "log_tail": log[-800:]}, 1)
    verdict.update({"ok": bool(verdict.get("running")), "workdir": wd, "evidence_dir": ev})
    return out(verdict, 0 if verdict.get("running") else 1)


def cmd_run(a):
    """编译 -> 复制 hex 到电路工作目录 -> 确定性验证。"""
    t0 = time.time()
    src = os.path.abspath(a.file)
    if not os.path.exists(src):
        return out({"ok": False, "stage": "build", "error": "源文件不存在: %s" % src}, 2)
    if not os.path.isfile(a.dsn):
        return out({"ok": False, "stage": "run", "error": "电路文件不存在: %s" % a.dsn}, 2)
    (rc, log), compiler = _build_source(src, a.compiler)
    hexes = _hex_candidates(src)
    if not hexes:
        return out({"ok": False, "stage": "build", "rc": rc,
                    "error": "编译未产出 hex", "compiler": compiler, "log_tail": log[-1200:]}, 1)
    hex_path = hexes[0]

    wd, dsn_dst, hex_dst = _stage_dsn(a.dsn, hex_path, a.hex_name)
    ev = os.path.join(wd, "evidence")
    os.makedirs(ev, exist_ok=True)
    verify_args = [PY, VERIFY, "--dsn", dsn_dst, "--wait", str(a.wait), "--evidence-dir", ev]
    if a.backend:
        verify_args += ["--backend", a.backend]
    rc, vlog = run(verify_args, timeout=180)
    verdict = None
    for line in reversed((vlog or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                verdict = json.loads(line)
                break
            except Exception:
                continue
    elapsed = round(time.time() - t0, 1)
    if verdict is None:
        return out({"ok": False, "stage": "verify", "error": "验证器未返回 JSON",
                    "hex": hex_path, "workdir": wd, "log_tail": vlog[-800:]}, 1)
    running = bool(verdict.get("running"))
    return out({
        "ok": running,
        "stage": "done",
        "verdict": "PASS" if running else "FAIL",
        "hex": hex_path, "compiler": compiler,
        "hex_staged": hex_dst,
        "dsn_staged": dsn_dst,
        "workdir": wd,
        "evidence": verdict.get("evidence"),
        "errors": verdict.get("errors"),
        "status_text": verdict.get("status_text"),
        "elapsed_sec": elapsed,
    }, 0 if running else 1)


def cmd_list(_a):
    if not os.path.exists(DSN_INDEX):
        return out({"ok": False, "error": "未配置电路索引：设 DSH_MCU_LAB_DSN_INDEX 指向你的 dsn_index.json（本仓库不附带电路索引，mcu_list 依赖它）"}, 1)
    try:
        with open(DSN_INDEX, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return out({"ok": False, "error": str(e)}, 1)
    items = data if isinstance(data, list) else data.get("items", data)
    if isinstance(items, dict):
        items = [{"name": k, "path": v} for k, v in items.items()]
    return out({"ok": True, "count": len(items), "items": items[:80]}, 0)


def main():
    ap = argparse.ArgumentParser(prog="mcu_lab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("list").set_defaults(func=cmd_list)

    p = sub.add_parser("build"); p.add_argument("file"); p.add_argument("--compiler", choices=["auto", "keil", "sdcc"], default="auto"); p.set_defaults(func=cmd_build)

    p = sub.add_parser("sim"); p.add_argument("dsn")
    p.add_argument("--seconds", type=float, default=8); p.add_argument("--shot")
    p.set_defaults(func=cmd_sim)

    p = sub.add_parser("verify"); p.add_argument("dsn")
    p.add_argument("--wait", type=float, default=6); p.add_argument("--evidence-dir"); p.add_argument("--backend", choices=["proteus", "offline"], default="proteus")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("run"); p.add_argument("file"); p.add_argument("dsn")
    p.add_argument("--wait", type=float, default=6); p.add_argument("--hex-name"); p.add_argument("--compiler", choices=["auto", "keil", "sdcc"], default="auto"); p.add_argument("--backend", choices=["proteus", "offline"], default="proteus")
    p.set_defaults(func=cmd_run)

    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
