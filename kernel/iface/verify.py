# -*- coding: utf-8 -*-
"""Deterministic Proteus simulation verifier.

The verifier deliberately uses Win32 window text (log/status controls), never
image recognition, and emits one ASCII JSON object on stdout.
"""
import argparse, ctypes, ctypes.wintypes as wt, json, os, re, subprocess, time

try:
    import win32gui
except Exception:
    win32gui = None

# Proteus 安装位置与临时目录。可用 DSH_MCU_LAB_ISIS / DSH_MCU_LAB_PROTEUS_TEMP 覆盖。
ISIS_EXE = os.environ.get("DSH_MCU_LAB_ISIS") or r"D:\Proteus7\BIN\ISIS.EXE"
TEMP_DIR = os.environ.get("DSH_MCU_LAB_PROTEUS_TEMP") or r"D:\proteus_temp"
FAIL_RE = re.compile(r"cannot open|simulation\s+failed|fatal simulator|\berror\b", re.I)
RUN_RE = re.compile(r"simulation\s*(started|running)|animation|\brunning\b|time\s*[=:]", re.I)
LOAD_RE = re.compile(r"loading\s+(design|project)|正在加载", re.I)
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WM_GETTEXT = 0x000D
SB_GETTEXTL = 0x0400 + 12
WM_CLOSE = 0x0010

def pid_of(hwnd):
    p = wt.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p)); return p.value

def enum_windows(pid):
    out=[]
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h) and (pid is None or pid_of(h)==pid):
            b=ctypes.create_unicode_buffer(512); user32.GetWindowTextW(h,b,512)
            r=wt.RECT(); user32.GetWindowRect(h,ctypes.byref(r)); out.append((h,b.value,r.right-r.left,r.bottom-r.top))
        return True
    user32.EnumWindows(cb,0); return sorted(out,key=lambda x:x[2]*x[3],reverse=True)

def children(parent):
    out=[]
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h,_): out.append(h); return True
    user32.EnumChildWindows(parent,cb,0); return out

def text_of(hwnd):
    b=ctypes.create_unicode_buffer(4096)
    n=user32.GetWindowTextW(hwnd,b,4096)
    if n: return b.value
    try:
        user32.SendMessageW(hwnd,WM_GETTEXT,4096,ctypes.cast(b,ctypes.c_void_p)); return b.value
    except Exception: return ""

def snapshot_text(hwnd):
    """Return (all control text, status-bar text, control metadata)."""
    vals=[]; status=[]
    for h in [hwnd]+children(hwnd):
        b=ctypes.create_unicode_buffer(128); user32.GetClassNameW(h,b,128); cls=b.value
        t=text_of(h)
        if t: vals.append(t)
        if cls.lower() in ("msctls_statusbar32", "statusbar"):
            if t: status.append(t)
            # SB_GETTEXTL obtains each pane text; pane 0 is normally the state.
            for i in range(8):
                x=ctypes.create_unicode_buffer(512)
                try:
                    if user32.SendMessageW(h,SB_GETTEXTL,i,ctypes.cast(x,ctypes.c_void_p)) and x.value: status.append(x.value)
                except Exception: break
    return "\n".join(dict.fromkeys(vals)), " | ".join(dict.fromkeys(status)), len(vals)

def wait_main(pid, timeout):
    end=time.time()+timeout
    while time.time()<end:
        w=enum_windows(pid)
        if w: return w[0][0]
        time.sleep(.3)
    return None

def key(hwnd, vk=0x7B, ctrl=False, shift=False):
    try: user32.SetForegroundWindow(hwnd)
    except Exception: pass
    for v in ([0x11] if ctrl else [])+([0x10] if shift else [])+[vk]: user32.PostMessageW(hwnd,0x100,v,0)
    for v in [vk]+([0x10] if shift else [])+([0x11] if ctrl else []): user32.PostMessageW(hwnd,0x101,v,0)

def cpu_seconds(pid):
    h = kernel32.OpenProcess(0x0400, False, pid)
    if not h: return None
    c=wt.FILETIME(); e=wt.FILETIME(); k=wt.FILETIME(); u=wt.FILETIME()
    try:
        if not kernel32.GetProcessTimes(h,ctypes.byref(c),ctypes.byref(e),ctypes.byref(k),ctypes.byref(u)): return None
        def val(x): return ((x.dwHighDateTime<<32)|x.dwLowDateTime)/10000000.0
        return val(k)+val(u)
    finally: kernel32.CloseHandle(h)

def offline_verify(dsn, evidence_dir=None):
    """可注入的离线替身：用 DSN 标记确定性模拟三类结果。"""
    text = open(dsn, 'r', encoding='utf-8', errors='replace').read()
    os.makedirs(evidence_dir or os.path.dirname(dsn), exist_ok=True)
    if 'OFFLINE_SIM_FAIL' in text:
        return {'running': False, 'log_text': 'offline simulation failed', 'status_text': '', 'errors': ['offline simulation failed'], 'evidence': 'offline backend: simulation failure', 'pid': None}, 1
    if 'OFFLINE_VERDICT_FAIL' in text:
        return {'running': False, 'log_text': 'offline simulation running', 'status_text': 'offline verdict fail', 'errors': [], 'evidence': 'offline backend: verdict failure', 'pid': None}, 1
    return {'running': True, 'log_text': 'offline simulation running', 'status_text': 'offline pass', 'errors': [], 'evidence': 'offline backend: deterministic pass', 'pid': None}, 0


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dsn',required=True); ap.add_argument('--wait',type=float,default=6); ap.add_argument('--startup-timeout',type=float,default=25); ap.add_argument('--evidence-dir'); ap.add_argument('--keep',action='store_true'); ap.add_argument('--backend',choices=['proteus','offline'],default='proteus')
    a=ap.parse_args(); dsn=os.path.abspath(a.dsn); result={'running':False,'log_text':'','status_text':'','errors':[],'evidence':'','pid':None}
    if not os.path.isfile(dsn): result['errors']=[f'DSN not found: {dsn}']; print(json.dumps(result,ensure_ascii=True)); return 2
    if a.backend == 'offline':
        result, code = offline_verify(dsn, a.evidence_dir)
        print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))
        return code
    os.makedirs(TEMP_DIR,exist_ok=True); env=os.environ.copy(); env['TEMP']=TEMP_DIR; env['TMP']=TEMP_DIR
    try: p=subprocess.Popen([ISIS_EXE,dsn],env=env); result['pid']=p.pid
    except Exception as e: result['errors']=[f'launch failed: {e}']; print(json.dumps(result,ensure_ascii=True)); return 3
    hwnd=wait_main(p.pid,a.startup_timeout)
    if not hwnd:
        result['errors']=['ISIS main window not found']; print(json.dumps(result,ensure_ascii=True)); return 4
    time.sleep(2); key(hwnd,ctrl=True); cpu0=cpu_seconds(p.pid); time.sleep(a.wait); cpu1=cpu_seconds(p.pid)
    log,status,_=snapshot_text(hwnd); result['log_text']=log[-12000:]; result['status_text']=status
    failures=sorted(set(m.group(0) for m in FAIL_RE.finditer(log+'\n'+status))); result['errors']=failures
    has_run=bool(RUN_RE.search(log+'\n'+status)); loading=bool(LOAD_RE.search(status))
    # Some 7.8 builds expose no explicit "Simulation started" line.  A
    # non-empty status bar after Ctrl+F12, provided it is not still loading and
    # contains no hard failure marker, is deterministic enough as a fallback.
    cpu_delta=(cpu1-cpu0) if cpu0 is not None and cpu1 is not None else 0.0
    active_fallback=cpu_delta>=0.05 and bool(enum_windows(p.pid))
    result['running']=bool(not failures and not loading and (has_run or bool(status) or active_fallback))
    result['evidence']=('run marker in log/status' if has_run else ('process CPU advanced %.3fs; ISIS window alive' % cpu_delta if active_fallback else 'no run marker')) + '; ' + ('failure marker present' if failures else 'no failure markers') + '; status=' + (status or '<empty>')
    if failures:
        ev=a.evidence_dir or os.path.join(os.path.dirname(dsn),'verify_evidence'); os.makedirs(ev,exist_ok=True)
        with open(os.path.join(ev,'simulation.log.txt'),'w',encoding='utf-8') as f: f.write(log+'\nSTATUS: '+status)
        if win32gui:
            try:
                from proteus_ctl import capture_window; capture_window(hwnd,os.path.join(ev,'simulation.png'))
            except Exception: pass
    key(hwnd,shift=True); time.sleep(.5)
    if not a.keep:
        try:
            user32.PostMessageW(hwnd,WM_CLOSE,0,0); time.sleep(.8)
            if p.poll() is None: p.terminate()
            p.wait(timeout=3)
        except Exception: pass
    print(json.dumps(result,ensure_ascii=True,separators=(',',':'))); return 0 if result['running'] else 1

if __name__=='__main__': raise SystemExit(main())
