"""Windows notification area with no additional packages. Tk stays on its own thread."""
import ctypes
import os
import queue
import threading
from ctypes import wintypes as w

class TrayIcon:
    def __init__(self,path):
        self.path=str(path); self.available=False; self.failed=False; self.hwnd=None; self.error=None
        self.queue=queue.Queue(); self.thread=None; self._tooltip='업비트 v1.8 · 가상매매 중지 상태'

    def actions(self):
        result=[]
        while True:
            try: result.append(self.queue.get_nowait())
            except queue.Empty: return result

    def start(self):
        if os.name!='nt': self.failed=True; return
        self.thread=threading.Thread(target=self._run,name='upbit-tray',daemon=True)
        self.thread.start()

    def stop(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(w.HWND(self.hwnd),0x10,0,0)

    def status(self,text):
        if text!=self._tooltip:
            self._tooltip=text[:127]
            if self.available and hasattr(self,'nid'):
                self.nid.szTip=self._tooltip
                ctypes.windll.shell32.Shell_NotifyIconW(1,ctypes.byref(self.nid))

    def _run(self):
        user=ctypes.windll.user32; shell=ctypes.windll.shell32; kernel=ctypes.windll.kernel32
        LRESULT=ctypes.c_ssize_t; WPARAM=ctypes.c_size_t; LPARAM=ctypes.c_ssize_t
        PROC=ctypes.WINFUNCTYPE(LRESULT,w.HWND,w.UINT,WPARAM,LPARAM)
        class WC(ctypes.Structure):
            _fields_=[('style',w.UINT),('proc',PROC),('clsExtra',ctypes.c_int),('wndExtra',ctypes.c_int),
                      ('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('background',w.HBRUSH),
                      ('menuName',w.LPCWSTR),('className',w.LPCWSTR)]
        class NID(ctypes.Structure):
            _fields_=[('cbSize',w.DWORD),('hWnd',w.HWND),('uID',w.UINT),('uFlags',w.UINT),
                      ('uCallbackMessage',w.UINT),('hIcon',w.HICON),('szTip',w.WCHAR*128),
                      ('dwState',w.DWORD),('dwStateMask',w.DWORD),('szInfo',w.WCHAR*256),
                      ('uTimeout',w.UINT),('szInfoTitle',w.WCHAR*64),('dwInfoFlags',w.DWORD),
                      ('guidItem',ctypes.c_byte*16),('hBalloonIcon',w.HICON)]
        user.DefWindowProcW.argtypes=[w.HWND,w.UINT,WPARAM,LPARAM]; user.DefWindowProcW.restype=LRESULT
        user.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID]
        user.CreateWindowExW.restype=w.HWND
        user.LoadImageW.argtypes=[w.HINSTANCE,w.LPCWSTR,w.UINT,ctypes.c_int,ctypes.c_int,w.UINT]; user.LoadImageW.restype=w.HANDLE
        kernel.GetModuleHandleW.argtypes=[w.LPCWSTR]; kernel.GetModuleHandleW.restype=w.HMODULE
        user.RegisterClassW.argtypes=[ctypes.POINTER(WC)]
        user.CreatePopupMenu.restype=w.HMENU
        user.AppendMenuW.argtypes=[w.HMENU,w.UINT,ctypes.c_size_t,w.LPCWSTR]
        user.TrackPopupMenu.argtypes=[w.HMENU,w.UINT,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.LPVOID]
        user.DestroyMenu.argtypes=[w.HMENU]
        user.DestroyWindow.argtypes=[w.HWND]
        user.SetForegroundWindow.argtypes=[w.HWND]
        user.PostMessageW.argtypes=[w.HWND,w.UINT,WPARAM,LPARAM]
        user.UnregisterClassW.argtypes=[w.LPCWSTR,w.HINSTANCE]
        user.DestroyIcon.argtypes=[w.HICON]
        callback_message=0x8000+37
        taskbar_created=user.RegisterWindowMessageW('TaskbarCreated')
        def add_icon():
            self.nid.szTip=self._tooltip
            self.available=bool(shell.Shell_NotifyIconW(0,ctypes.byref(self.nid)))
            if not self.available: self.failed=True
        def callback(hwnd,msg,wp,lp):
            if msg==callback_message:
                if lp in (0x202,0x203): self.queue.put('show')
                elif lp in (0x205,0x7b):
                    menu=user.CreatePopupMenu(); point=w.POINT()
                    user.GetCursorPos(ctypes.byref(point))
                    for key,label in [(1,'창 열기'),(2,'매매 중지 · 창 열기'),(3,'프로그램 종료')]: user.AppendMenuW(menu,0,key,label)
                    user.SetForegroundWindow(hwnd)
                    choice=user.TrackPopupMenu(menu,0x180,point.x,point.y,0,hwnd,None)
                    user.DestroyMenu(menu); user.PostMessageW(hwnd,0,0,0)
                    if choice in (1,2,3): self.queue.put({1:'show',2:'stop',3:'quit'}[choice])
                return 0
            if msg==taskbar_created:
                add_icon(); return 0
            if msg==0x10:
                self.available=False; shell.Shell_NotifyIconW(2,ctypes.byref(self.nid)); user.DestroyWindow(hwnd); return 0
            if msg==2: user.PostQuitMessage(0); return 0
            return user.DefWindowProcW(hwnd,msg,wp,lp)
        icon=None; name=f'UpbitTrayV18_{os.getpid()}'
        instance=kernel.GetModuleHandleW(None)
        try:
            self.proc=PROC(callback)
            wc=WC(); wc.proc=self.proc; wc.instance=instance; wc.className=name
            if not user.RegisterClassW(ctypes.byref(wc)): raise OSError('tray class')
            self.hwnd=user.CreateWindowExW(0,name,'Upbit tray',0,0,0,0,0,None,None,instance,None)
            if not self.hwnd: raise OSError('tray window')
            icon=user.LoadImageW(None,self.path,1,32,32,0x10)
            if not icon: raise OSError('tray icon file')
            self.nid=NID(); self.nid.cbSize=ctypes.sizeof(NID); self.nid.hWnd=self.hwnd
            self.nid.uID=1; self.nid.uFlags=1|2|4; self.nid.uCallbackMessage=callback_message; self.nid.hIcon=icon
            add_icon()
            if not self.available: raise OSError('notification area unavailable')
            msg=w.MSG()
            while user.GetMessageW(ctypes.byref(msg),None,0,0)>0:
                user.TranslateMessage(ctypes.byref(msg)); user.DispatchMessageW(ctypes.byref(msg))
        except Exception as error:
            self.error=f'{type(error).__name__}: {error} (Win32 {kernel.GetLastError()})'
            self.failed=True
        finally:
            self.available=False
            if hasattr(self,'nid'): shell.Shell_NotifyIconW(2,ctypes.byref(self.nid))
            if self.hwnd: user.DestroyWindow(self.hwnd)
            self.hwnd=None
            if icon: user.DestroyIcon(icon)
            user.UnregisterClassW(name,instance)
