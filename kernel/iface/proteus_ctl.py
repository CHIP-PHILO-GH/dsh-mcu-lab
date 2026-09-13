# -*- coding: utf-8 -*-
"""
Proteus 仿真控制核心模块（纯 win32 API，兼容 64 位 Python）
控制 ISIS 7.x（安装位置由脚本自行定位）：打开 DSN、运行/停止仿真、窗口截图。

用法:
  python proteus_ctl.py --dsn <path.dsn> [--run-seconds N] [--shot <out.png>] [--kill]
  python proteus_ctl.py --list   # 列出当前 ISIS 窗口
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

import win32api
import win32con
import win32gui
import win32ui
from PIL import Image

# Proteus 安装位置与临时目录。可用 DSH_MCU_LAB_ISIS / DSH_MCU_LAB_PROTEUS_TEMP 覆盖。
ISIS_EXE = os.environ.get("DSH_MCU_LAB_ISIS") or next((os.path.join(r, n, "BIN", "ISIS.EXE") for r in [os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")] + [f"{d}:\\" for d in "CDEFGHIJ"] for n in ("Proteus 8 Professional", "Proteus7", "Proteus 8") if r and os.path.isfile(os.path.join(r, n, "BIN", "ISIS.EXE"))), "")
PROTEUS_TEMP = os.environ.get("DSH_MCU_LAB_PROTEUS_TEMP") or os.path.join(os.environ.get("TEMP", os.getcwd()), "dsh-mcu-lab-proteus")
TITLE_MARK = "ISIS Professional"
VK_CONTROL = 0x11
VK_F12 = 0x7B

user32 = ctypes.windll.user32


def _proc_id(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def find_windows(pid=None, title_mark=TITLE_MARK):
    """枚举可见顶层窗口，返回 [(hwnd, title, cls, w, h)]，按尺寸降序。"""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if pid is not None and _proc_id(hwnd) != pid:
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if title_mark in buf.value:
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            found.append((hwnd, buf.value, w, h))
        return True

    user32.EnumWindows(cb, 0)
    # 尺寸大的排前面（主窗口最大）
    found.sort(key=lambda x: x[2] * x[3], reverse=True)
    return found


def wait_main_hwnd(pid, timeout=25):
    """返回真实主窗口（尺寸最大的窗口，可能含设计名前缀）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = find_windows(pid)
        if wins:
            return wins[0][0], wins[0][1]
        time.sleep(0.5)
    return None, None


def bring_foreground(hwnd):
    """尽力把窗口置前（外部进程受限时用 AttachThreadInput 绕过前台锁）。"""
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        pass
    # 备用：AttachThreadInput
    try:
        fg = user32.GetForegroundWindow()
        cur = win32api.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        win_thread = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(fg_thread, win_thread, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(fg_thread, win_thread, False)
        return True
    except Exception:
        return False


def send_key_combo(hwnd, ctrl=False, shift=False, vk=VK_F12):
    """用 PostMessage 直接投递键盘消息到窗口（不依赖前台焦点，最可靠）。
    先置前台作为兜底，再用 PostMessage 发 WM_KEYDOWN/WM_KEYUP。
    """
    bring_foreground(hwnd)
    time.sleep(0.1)
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101

    def msg(k, v):
        user32.PostMessageW(hwnd, k, v, 0)

    if ctrl:
        msg(WM_KEYDOWN, VK_CONTROL)
    if shift:
        msg(WM_KEYDOWN, 0x10)
    msg(WM_KEYDOWN, vk)
    msg(WM_KEYUP, vk)
    if shift:
        msg(WM_KEYUP, 0x10)
    if ctrl:
        msg(WM_KEYUP, VK_CONTROL)
    time.sleep(0.2)


def run_sim(hwnd):
    send_key_combo(hwnd, ctrl=True)          # Ctrl+F12 运行
    time.sleep(0.5)


def pause_sim(hwnd):
    send_key_combo(hwnd)                     # F12 暂停
    time.sleep(0.3)


def stop_sim(hwnd):
    send_key_combo(hwnd, shift=True)         # Shift+F12 停止


def capture_window(hwnd, out_path):
    """PrintWindow 截图（PW_RENDERFULLCONTENT），失败回退 BitBlt。"""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        raise RuntimeError(f"无效窗口尺寸 {w}x{h}")
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)
    PW_RENDERFULLCONTENT = 2
    ok = user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
    if not ok:
        try:
            bring_foreground(hwnd)
            time.sleep(0.3)
            ok = user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0)
        except Exception:
            pass
    info = bmp.GetInfo()
    data = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           data, "raw", "BGRX", 0, 1)
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    img.save(out_path)
    return out_path, bool(ok)


WM_GETTEXT = 0x000D
WM_COMMAND = 0x0111
IDOK = 1
DLG_CLASS = "#32770"
ERROR_KEYWORDS = ["internal error", "cannot open", "simulation failed",
                  "0x0000e008", "no message found", "fatal simulator"]


def _class_of(hwnd):
    c = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, c, 128)
    return c.value


def _child_windows(parent):
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        out.append(h)
        return True

    user32.EnumChildWindows(parent, cb, 0)
    return out


def _dialog_text(hwnd):
    """读取对话框及其 Static 子控件的拼接文本。"""
    parts = []
    b = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, b, 256)
    if b.value:
        parts.append(b.value)
    for child in _child_windows(hwnd):
        if _class_of(child) == "Static":
            b = ctypes.create_unicode_buffer(512)
            user32.SendMessageW(child, WM_GETTEXT, 512, ctypes.cast(b, ctypes.c_char_p))
            if b.value:
                parts.append(b.value)
    return " ".join(parts)


def dismiss_error_dialogs(pid, timeout=20):
    """自动消除仿真相关报错弹窗（0x0000E008、Cannot open SDF 等）。
    仅处理类名 #32770 且标题/正文含错误关键词的对话框，发 WM_COMMAND IDOK 关闭。
    返回处理的个数。不误关其它窗口。"""
    dismissed = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = None
        for hwnd, title, _w, _h in find_windows(pid):
            if _class_of(hwnd) == DLG_CLASS:
                text = (title + " " + _dialog_text(hwnd)).lower()
                if any(k in text for k in ERROR_KEYWORDS):
                    found = hwnd
                    break
        if found:
            try:
                user32.PostMessageW(found, WM_COMMAND, IDOK, 0)
                dismissed += 1
                print(f"  [dismiss] 已消除错误弹窗 {hex(found)}")
                time.sleep(0.8)
            except Exception as e:
                print(f"  [dismiss] 失败 {e}")
                break
        else:
            break
    return dismissed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run-seconds", type=int, default=6)
    ap.add_argument("--shot")
    ap.add_argument("--shots", type=int, default=0,
                    help="连拍 N 张（仿真运行中每隔 2s 拍一张，用于对比动画状态）")
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--kill", action="store_true", help="结束后关闭 ISIS")
    args = ap.parse_args()

    if args.list:
        for h, t, _w, _h in find_windows():
            print(f"hwnd={h}  title=[{t}]")
        return

    dsn = os.path.abspath(args.dsn)
    if not os.path.exists(dsn):
        print(f"ERR: DSN 不存在 {dsn}")
        sys.exit(2)

    # Proteus 7.8/PROSPICE is a legacy 32-bit process.  Keep its transient
    # SDF files in an ASCII-only directory without changing persistent
    # user/system TEMP variables.  Set both names because different builds
    # consult different variables.
    os.makedirs(PROTEUS_TEMP, exist_ok=True)
    child_env = os.environ.copy()
    child_env["TEMP"] = PROTEUS_TEMP
    child_env["TMP"] = PROTEUS_TEMP
    proc = subprocess.Popen([ISIS_EXE, dsn], env=child_env)
    print(f"ISIS PID={proc.pid}")
    hwnd, title = wait_main_hwnd(proc.pid)
    if hwnd is None:
        print("ERR: 未找到 ISIS 主窗口")
        proc.kill()
        sys.exit(3)
    print(f"主窗口 hwnd={hwnd} title=[{title}]")
    # 打开初期自动消除 splash/0x0000E008 等弹窗（非致命噪音）
    time.sleep(3)
    n = dismiss_error_dialogs(proc.pid)
    if n:
        print(f"打开阶段自动消除弹窗 {n} 个")

    if not args.no_run:
        print("运行仿真 (Ctrl+F12)...")
        run_sim(hwnd)
        # 消除运行期的报错弹窗（0x0000E008 / SDF 等，非致命时点掉继续）
        n = dismiss_error_dialogs(proc.pid)
        if n:
            print(f"运行期自动消除弹窗 {n} 个")
        time.sleep(args.run_seconds)
        if args.shots > 0:
            base = args.shot or os.path.join(os.path.dirname(dsn), "shot")
            for i in range(args.shots):
                p = f"{os.path.splitext(base)[0]}_{i+1}.png"
                out, ok = capture_window(hwnd, p)
                print(f"连拍[{i+1}] {'OK' if ok else 'Fallback'} -> {p}")
                time.sleep(2)
        elif args.shot:
            out, ok = capture_window(hwnd, args.shot)
            print(f"截图 {'OK' if ok else 'Fallback'} -> {out}")
        print("停止仿真 (Shift+F12)...")
        stop_sim(hwnd)
        time.sleep(1)
    elif args.shot:
        out, ok = capture_window(hwnd, args.shot)
        print(f"截图 {'OK' if ok else 'Fallback'} -> {out}")

    if args.kill:
        time.sleep(1)
        proc.terminate()
        print("ISIS 已关闭")
    else:
        print(f"ISIS 保持运行 PID={proc.pid}")


if __name__ == "__main__":
    main()



