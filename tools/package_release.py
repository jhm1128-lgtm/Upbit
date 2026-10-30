"""Package only application source/tests; never include private runtime files."""
import ast,hashlib,json,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
target=root/'releases'/version; target.mkdir(parents=True,exist_ok=True)
files=[p for p in root.iterdir() if p.is_file() and p.suffix in {'.py','.pyw','.bat','.vbs','.ps1','.ico'}]
files += [root/'requirements.txt',root/'VALIDATION.md',root/'VERSION']
files += list((root/'docs').glob('USER_GUIDE_*.md'))
files += list((root/'tests').glob('test_*.py'))
for p in files:
    if p.suffix in {'.py','.pyw'}: ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
guide=root/'docs'/f'USER_GUIDE_{version}.md'
assert guide.exists(),guide
patch_files=['validation_app.py','dashboard.py','main.py','market_guard.py','tray_icon.py','VERSION','VALIDATION.md',
             'trade_history.py','ui_widgets.py','log_view.py',
             'tests/test_app.py','tests/test_market_guard.py','tests/test_network.py','tests/test_history_tools.py']
patch_files += [p.relative_to(root).as_posix() for p in (root/'docs').glob('USER_GUIDE_*.md')]
outcomes=[]
for full in (True,False):
    out=target/(f'UpbitAutoTrading_{version}_Full.zip' if full else f'Upbit_{version}_UI_Update.zip')
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        prefix=f'UpbitAutoTrading_{version}/' if full else ''
        for p in files if full else [root/name for name in patch_files]:
            z.write(p,prefix+p.relative_to(root).as_posix())
        instructions=guide.read_text(encoding='utf-8')
        for userguide in (root/'docs').glob('USER_GUIDE_*.md'):
            instructions=instructions.replace(f']({userguide.name})',f'](docs/{userguide.name})')
        instructions=instructions.replace('](../VALIDATION.md)','](VALIDATION.md)')
        z.writestr(prefix+('README.md' if full else f'README_{version}.md'),instructions)
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert not any(n.endswith(('.sqlite3','.db','.env','.csv','.log','.lnk','settings.json')) for n in z.namelist())
    outcomes.append(dict(path=out.relative_to(root).as_posix(),bytes=out.stat().st_size,sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
manifest=root/'releases'/'manifest.json'
entries=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
entries=[item for item in entries if item['path'] not in {o['path'] for o in outcomes}]+outcomes
manifest.write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(outcomes,indent=2))
