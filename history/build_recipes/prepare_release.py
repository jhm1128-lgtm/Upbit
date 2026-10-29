import ast
from pathlib import Path
base = Path(__file__).parent
source = (base/'v1_1_reference/main.py').read_text(encoding='utf-8-sig')
tree = ast.parse(source)
keep = {'__init__','build_ui','refresh_history_views','refresh_profit_view','reset_profit_filters'}
lines = source.splitlines(keepends=True)
cls = next(n for n in tree.body if isinstance(n,ast.ClassDef))
out = source[:source.index('class UpbitAutoTrader:')] + 'class UpbitAutoTrader:\n'
for method in cls.body:
    if isinstance(method,ast.FunctionDef) and method.name in keep:
        out += ''.join(lines[method.lineno-1:method.end_lineno])+'\n\n'
out = out.replace('load_dotenv()', 'load_dotenv(override=False)')
# The legacy module only supplies the existing layout and history readers.
(base/'UpbitAutoTrading_v1.2/legacy_ui.py').write_text(out,encoding='utf-8')
