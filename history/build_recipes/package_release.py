import ast
import json
import zipfile
import sys
from pathlib import Path
base = Path(__file__).parent
release = base/'UpbitAutoTrading_v1.2'
files = [p for p in release.rglob('*') if p.is_file() and '__pycache__' not in p.parts
         and p.suffix not in ('.pyc','.sqlite3','.lock') and p.name not in ('state.json','transactions.csv','daily_pnl.csv','.env')]
for p in files:
    if p.suffix == '.py':
        ast.parse(p.read_text(encoding='utf-8'),feature_version=(3,11))
    if p.suffix in ('.py','.md','.txt','.example'):
        assert 'L4xV6' not in p.read_text(encoding='utf-8'), 'source sample key leaked'
zip_path = base/(sys.argv[1] if len(sys.argv)>1 else 'UpbitAutoTrading_v1.2.zip')
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files): z.write(p,Path('UpbitAutoTrading_v1.2')/p.relative_to(release))
with zipfile.ZipFile(zip_path) as z:
    assert z.testzip() is None
    names = z.namelist()
    assert any(n.endswith('/.env.example') for n in names)
    print(json.dumps({'zip':str(zip_path),'files':len(names),'bytes':zip_path.stat().st_size,
                      'python_311_syntax':'pass','crc':'pass'},ensure_ascii=False))
