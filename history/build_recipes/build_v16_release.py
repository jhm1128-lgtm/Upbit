import ast
import zipfile
from pathlib import Path
base=Path(__file__).parent
release=base/'UpbitAutoTrading_v1.6'
for name in ('validation_app.py','main.py','dashboard.py'):
    p=release/name; p.write_text(p.read_text(encoding='utf-8-sig').replace('v1.5','v1.6'),encoding='utf-8')
notes='''# 업비트 v1.6 — 당일 재매수 금지 / 상태 신호등

## 당일 재매수 금지
손절·1차 익절·트레일링 등 실제로 가상 매도가 발생한 종목은 손익의 부호에 관계없이 같은 한국시간 날짜에 재매수하지 않습니다. 다른 종목의 매수는 기존 조건/위험 한도 안에서 가능합니다.
1차 익절 후 남은 보유 수량은 계속 감시하고 손절/트레일링 매도를 허용합니다. 매도 금액이 최소액 미달로 처리되지 않았다면 매도 이력이 생기지 않으므로 추가 제한도 생기지 않습니다.
제한은 KST 자정이 지나면 해당 종목에 대해 풀리지만 최대보유·연속손절·기존 15분 진입 대기 등 다른 조건은 유지합니다. 재시작해도 제한이 유지됩니다.
첫 실행 시 기존 DB의 매도 기록을 읽어 이미 오늘 매도한 종목도 제한합니다. 가상 잔고·포지션·과거 거래는 초기화하지 않습니다. 업데이트 전에 재매수해 이미 보유한 포지션은 강제로 청산하지 않고 기존 청산 규칙으로 감시합니다.
매수후보에는 '당일 매도 종목 · 재매수 금지 (KST 자정 해제)'를 표시합니다.

## 신호등
상단에 초록/노랑/빨강 표시와 상태명을 추가했습니다.
- 초록: 실행 중, 다음 검색 대기.
- 노랑 점멸: 조회/검색 중 또는 중지 처리 중. 조회 실패 후 재시도 대기도 노랑입니다.
- 빨강: 중지됨 또는 기록 저장 오류. 기록 오류는 오류 문구로 구분합니다.
이 표시는 프로그램 동작 상태이며 매수 추천이나 데이터/주문의 안전성 보증이 아닙니다.

## 기존 폴더 업데이트
중지 → 감시 종료 확인 → 창 닫기 → validation.sqlite3 백업 → 업데이트 ZIP을 C:\\UpbitAutoTrading에 풀어 프로그램 파일 덮어쓰기 → 기존 바탕화면 아이콘으로 재실행.
업데이트 ZIP에는 운영 DB·설정·CSV·API 키가 포함되지 않습니다. 기존 검증을 계속 이어갈 수 있습니다. 재설치할 필요 없습니다. v1.4/v1.5의 기존 모듈을 사용하는 업데이트입니다.
실거래 잠금 유지. Python 3.11 64bit 대상, pandas==2.2.3. 직접 시험은 Windows Python 3.12.14에서 수행했고 실제 주문/Python 3.11 직접 실행은 미검증입니다.
'''
(release/'README.md').write_text(notes,encoding='utf-8')
(release/'VALIDATION.md').write_text('''# v1.6 검증
Windows Python 3.12.14 64bit / pandas 2.2.3. 모의·GUI 시험 54개 통과.
기존 42개 + 당일 재진입 제한 6개 + 상태 신호등 6개. GUI 시험에 신호등 텍스트/검색 상태 검사를 추가했습니다.
확인: 손절 후 당일 재매수 차단, 다른 종목 진입 허용, 1차 익절 후 잔량 트레일링 유지, 재시작 제한 유지, 기존 DB 매도 이력 복원과 잔고/거래 보존, KST 자정 해제, 최소액 미달 매도는 제한 생성 없음, UTC 입력의 KST 날짜 경계, 실행/검색/중지처리/중지/기록오류/조회재시도 구분.
실제 공개 API 장시간 운용, 실제 주문, Python 3.11 직접 실행, 다양한 DPI 육안 확인은 미검증. 문법 파싱(3.11)과 ZIP CRC 검사 수행. 신호등이 초록이어도 실거래 안전성이나 수익성을 보장하지 않습니다.
''',encoding='utf-8')
files=[p for p in release.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'reports' not in p.parts and p.suffix not in ('.pyc','.sqlite3','.lock','.csv','.log') and p.name not in ('.env','state.json','settings.json')]
for p in files:
    if p.suffix in ('.py','.pyw'): ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
full=base/'UpbitAutoTrading_v1.6_ReentrySignal.zip'; patch=base/'Upbit_v1.6_Update.zip'
with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files: z.write(p,Path('UpbitAutoTrading_v1.6')/p.relative_to(release))
with zipfile.ZipFile(patch,'w',zipfile.ZIP_DEFLATED) as z:
    for name in ('paper.py','activity.py','validation_app.py','daily_profit.py','main.py','dashboard.py','README.md','VALIDATION.md'):
        z.write(release/name,name)
for p in (full,patch):
    with zipfile.ZipFile(p) as z: assert z.testzip() is None
    print(p,'bytes=',p.stat().st_size,'CRC OK, Python 3.11 syntax OK')
