"""Package only application source/tests; never include private runtime files."""
import ast,hashlib,json,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
target=root/'releases'/version; target.mkdir(parents=True,exist_ok=True)
files=[p for p in root.iterdir() if p.is_file() and p.suffix in {'.py','.pyw','.bat','.vbs','.ps1','.ico'}]
files += [root/'requirements.txt',root/'VALIDATION.md',root/'docs'/'USER_GUIDE_v1.8.md']
files += list((root/'tests').glob('test_*.py'))
for p in files:
    if p.suffix in {'.py','.pyw'}: ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
out=target/f'UpbitAutoTrading_{version}_Source.zip'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files: z.write(p,p.relative_to(root))
with zipfile.ZipFile(out) as z: assert z.testzip() is None
print(json.dumps(dict(path=str(out),sha256=hashlib.sha256(out.read_bytes()).hexdigest()),indent=2))
