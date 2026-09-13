# -*- coding: utf-8 -*-
"""
SDCC 编译封装（Keil build51.py 的开源替代，.c -> .hex）

用法:
    python sdcc51.py <file.c> [--out <hex名>] [--opt]
        -> SDCC -mmcs51 编译, 产出同名 .hex（Intel HEX，Proteus 可直接加载）

特点:
  * 调用 D:\\sdcc\\bin\\sdcc.exe（官方 4.6.0），进程级注入 PATH（sdcc 驱动按名字
    找 cc1/sdcpp，必须在 PATH 中），不修改系统 PATH
  * -I 指向接口目录 sdcc-inc/（内含 reg52.h shim，转发 SDCC 自带 8052.h，
    让 Keil 风格 #include <reg52.h> 代码零修改可编译）
  * SDCC 默认输出 <名>.ihx（Intel HEX 格式），脚本复制为 .hex
  * 输出/退出码风格与 build51.py 一致：0=成功 1=编译失败

返回: 0=成功, 1=编译错误, 2=参数错误
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

# SDCC 工具链目录。可用 DSH_MCU_LAB_SDCC_BIN 覆盖。
def _find_sdcc_bin():
    configured = os.environ.get("DSH_MCU_LAB_SDCC_BIN")
    if configured:
        return configured
    exe = shutil.which("sdcc")
    return os.path.dirname(exe) if exe else r"D:\sdcc\bin"

SDCC_BIN = _find_sdcc_bin()
SHIM_INC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdcc-inc")  # Keil 兼容头 shim


def run(cmd, cwd=None):
    env = dict(os.environ)
    env["PATH"] = SDCC_BIN + os.pathsep + env.get("PATH", "")
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def build_single(c_file, out_name=None):
    c_file = os.path.abspath(c_file)
    if not os.path.exists(c_file):
        print(f"ERR: 源文件不存在 {c_file}")
        return 1, None, 0, 0
    workdir = os.path.dirname(c_file)
    base = out_name or os.path.splitext(os.path.basename(c_file))[0]

    exe = shutil.which("sdcc", path=SDCC_BIN) or os.path.join(SDCC_BIN, "sdcc.exe")
    cmd = [exe, "-mmcs51",
           "-I", SHIM_INC, c_file]
    print("RUN: " + " ".join(cmd))
    rc, out = run(cmd, cwd=workdir)
    print(out[-1500:])
    errs = len(re.findall(r"(?:fatal\s+)?error", out, re.I))
    warns = len(re.findall(r"warning\s+\d+", out, re.I))
    if rc != 0:
        return 1, None, errs, warns

    ihx = os.path.join(workdir, base + ".ihx")
    if not os.path.exists(ihx):
        # SDCC 输出名 = 源 basename（若 -o 未指定时）
        src_base = os.path.splitext(os.path.basename(c_file))[0]
        ihx = os.path.join(workdir, src_base + ".ihx")
    if not os.path.exists(ihx):
        print("ERR: 未产出 IHX/HEX")
        return 1, None, errs, warns
    hex_path = os.path.join(workdir, base + ".hex")
    shutil.copyfile(ihx, hex_path)
    print(f"HEX: {hex_path} ({os.path.getsize(hex_path)} B)")
    return 0, hex_path, errs, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="单文件 .c 路径")
    ap.add_argument("--out", help="输出 hex 基名（默认同源名）")
    args = ap.parse_args()

    rc, hexp, e, w = build_single(args.file, args.out)
    print(f"\n=== SDCC 结果: errors={e} warnings={w} hex={hexp} ===")
    sys.exit(rc)


if __name__ == "__main__":
    main()
