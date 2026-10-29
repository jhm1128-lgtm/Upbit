"""No-console entry point; preserve startup/callback errors in startup.log."""
import os
from pathlib import Path
import runpy
import sys
import traceback

base = Path(__file__).resolve().parent
os.chdir(base)
sys.path.insert(0, str(base))

try:
    output = open(base / 'startup.log', 'a', encoding='utf-8', buffering=1)
    sys.stdout = output
    sys.stderr = output
    runpy.run_path(str(base / 'validation_app.py'), run_name='__main__')
except SystemExit as exc:
    if exc.code:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc.code), 'Upbit 실행 확인', 0x30)
except Exception:
    error = traceback.format_exc()
    try:
        sys.stderr.write(error)
    except Exception:
        pass
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,
        '프로그램을 실행하지 못했습니다.\n같은 폴더의 startup.log를 확인해 주세요.\n\n' + error[-1200:],
        'Upbit 실행 오류', 0x10)
