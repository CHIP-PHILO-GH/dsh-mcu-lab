# -*- coding: utf-8 -*-
"""
C51 编译封装（build.ps1 的 Python 等价实现，便于 AI/脚本调用）

两种模式:
  1) 单文件:   python build51.py <file.c> [--inc <include_dir>]
               -> C51 -> BL51 -> OH51, 产出同名 .hex
  2) 工程:     python build51.py --proj <file.uvproj>
               -> UV4 -b 批处理编译, 产出工程配置的 .hex

返回: 0=成功, 1=编译错误, 2=参数错误; 打印 hex 路径与错误/警告计数。
"""
import argparse
import os
import re
import subprocess
import sys

# Keil 安装根目录。默认按常见的 <KEIL_DIR>；装在别处请设环境变量 DSH_MCU_LAB_KEIL_DIR。
KEIL_DIR = os.environ.get("DSH_MCU_LAB_KEIL_DIR") or next((os.path.join(r, n) for r in [os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")] + [f"{d}:\\" for d in "CDEFGHIJ"] for n in ("Keil", "keil", "Keil_v5") if r and os.path.isfile(os.path.join(r, n, "C51", "BIN", "C51.exe"))), "")
C51 = os.path.join(KEIL_DIR, r"C51\BIN\C51.exe")
BL51 = os.path.join(KEIL_DIR, r"C51\BIN\BL51.exe")
OH51 = os.path.join(KEIL_DIR, r"C51\BIN\OH51.exe")
UV4 = os.path.join(KEIL_DIR, r"UV4\Uv4.exe")


def run(cmd, cwd=None):
    """执行命令，返回 (returncode, stdout)。"""
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                       encoding="gbk", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def build_single(c_file):
    """C51 -> BL51 -> OH51 单文件编译。"""
    c_file = os.path.abspath(c_file)
    if not os.path.exists(c_file):
        print(f"ERR: 源文件不存在 {c_file}")
        return 1, None, 0, 0
    workdir = os.path.dirname(c_file)
    base = os.path.splitext(os.path.basename(c_file))[0]

    def count_err(out):
        m = re.findall(r"(\d+)\s+ERROR\s*\(S\)", out, re.I)
        return int(m[-1]) if m else 0

    def count_warn(out):
        m = re.findall(r"(\d+)\s+WARNING\s*\(S\)", out, re.I)
        return int(m[-1]) if m else 0

    # 1. C51 编译
    rc, out = run([C51, c_file], cwd=workdir)
    print(out[-1200:])
    errs = count_err(out)
    warns = count_warn(out)
    if rc != 0 or errs > 0:
        return 1, None, errs, warns

    # 2. BL51 链接（找生成的 .OBJ）
    obj = os.path.join(workdir, base + ".OBJ")
    if not os.path.exists(obj):
        obj = os.path.join(workdir, base + ".obj")
    rc, out = run([BL51, obj, "RAMSIZE(256)", "IDATA(80H)"], cwd=workdir)
    print(out[-1200:])
    errs = count_err(out)
    if rc != 0 or errs > 0:
        return 1, None, errs, warns

    # 3. OH51 转 HEX（绝对文件无扩展名，名=base大写）
    absfile = os.path.join(workdir, base.upper())
    rc, out = run([OH51, absfile], cwd=workdir)
    print(out[-800:])
    hex_path = os.path.join(workdir, base.upper() + ".hex")
    if not os.path.exists(hex_path):
        # 兜底：小写名
        hex_path = os.path.join(workdir, base + ".hex")
    if not os.path.exists(hex_path):
        print("ERR: 未产出 HEX")
        return 1, None, errs, warns
    return 0, hex_path, errs, warns


def build_project(proj_file, out_log=None):
    """UV4 -b 工程批处理编译。"""
    proj_file = os.path.abspath(proj_file)
    if not os.path.exists(proj_file):
        print(f"ERR: 工程不存在 {proj_file}")
        return 1, None, 0, 0
    log = out_log or (os.path.join(os.path.dirname(proj_file), "build.log"))
    p = subprocess.Popen([UV4, "-b", proj_file, "-o", log, "-j0"])
    # UV4 -b 异步，等待日志非空或进程退出
    import time
    for _ in range(60):
        time.sleep(1)
        if os.path.exists(log) and os.path.getsize(log) > 0:
            break
        if p.poll() is not None:
            break
    try:
        p.wait(timeout=30)
    except Exception:
        p.kill()
    with open(log, encoding="gbk", errors="replace") as f:
        text = f.read()
    print(text[-1500:])
    errs = len(re.findall(r"(\d+)\s+Error", text))
    warns = len(re.findall(r"(\d+)\s+Warning", text))
    ok = "0 Error" in text and "0 Warning" in text
    # 找 hex
    hexdir = os.path.dirname(proj_file)
    hexes = [f for f in os.listdir(hexdir) if f.lower().endswith(".hex")]
    hex_path = os.path.join(hexdir, hexes[0]) if hexes else None
    return 0 if ok else 1, hex_path, errs, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="单文件 .c 路径")
    ap.add_argument("--proj", help=".uvproj 工程路径")
    ap.add_argument("--log", help="工程编译日志输出路径")
    args = ap.parse_args()

    if args.proj:
        rc, hexp, e, w = build_project(args.proj, args.log)
    elif args.file:
        rc, hexp, e, w = build_single(args.file)
    else:
        print("用法: python build51.py <file.c> | --proj <file.uvproj>")
        sys.exit(2)

    print(f"\n=== 结果: errors={e} warnings={w} hex={hexp} ===")
    sys.exit(rc)


if __name__ == "__main__":
    main()



