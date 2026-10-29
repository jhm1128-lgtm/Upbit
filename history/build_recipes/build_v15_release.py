import ast
import zipfile
from pathlib import Path

base=Path(__file__).parent
release=base/'UpbitAutoTrading_v1.5'
for filename in ('validation_app.py','dashboard.py','main.py'):
    p=release/filename
    p.write_text(p.read_text(encoding='utf-8-sig').replace('v1.4','v1.5'),encoding='utf-8')
notes='''# v1.5 일자별 가상 손익 수정

기존 손익 메뉴가 실거래 CSV를 읽어 가상매매 결과를 표시하지 않던 문제를 수정했습니다. 기본 메뉴는 **가상 손익**입니다.
validation.sqlite3의 기존 기록을 날짜별로 즉시 집계하므로 이전 기록도 표시됩니다. 가상매매 규칙과 실거래 잠금은 유지합니다.

표시 항목: KST 날짜, 매수/매도 횟수, 손절/1차 익절/트레일링 횟수, 발생 수수료, 실현손익, 매도 건별 승률, 해당 날짜의 최종 조회 자산.
매수만 있는 날짜도 표시합니다. 날짜 필터가 적용되며 새 거래 발생 시와 15초마다 화면을 갱신합니다.
paper_daily.csv는 시작 및 새 거래 발생 시 자동 재생성합니다. 화면의 최신 자산 스냅샷은 CSV 생성 이후일 수 있습니다.

실현손익에는 배분한 매수·매도 수수료가 이미 반영되므로 수수료 합계를 다시 차감하지 않습니다. 발생 수수료는 발생 날짜 기준이며, 전날 매수 수수료 일부가 다음 날 매도 손익에 배분될 수 있습니다.
승률은 포지션 단위가 아닌 부분익절을 포함한 매도 건수 기준입니다. 매도가 없는 날은 —로 표시합니다.
최종 조회 자산은 확정 마감자산이 아닙니다. 시세 누락 스냅샷이면 조회 없음으로 표시하고 과거 값으로 채우지 않습니다. 신뢰할 일초 자산 기준이 없으므로 일별 수익률을 만들어 표시하지 않습니다.

## 기존 폴더에 업데이트
1. 실행 중인 프로그램에서 중지를 누르고 감시 종료 후 창을 닫습니다.
2. validation.sqlite3를 별도 백업합니다. 기록을 지우거나 초기화하지 마세요.
3. Upbit_v1.5_DailyProfit_Update.zip의 파일을 C:\\UpbitAutoTrading 폴더에 풀고 같은 이름의 프로그램 파일만 덮어씁니다.
4. 기존 바탕화면 업비트 자동매매 아이콘으로 다시 실행합니다. 재설치/API 키 입력은 필요 없습니다.

이 업데이트 ZIP에는 validation.sqlite3·settings.json·CSV·.env가 없으므로 기존 운영 기록을 덮어쓰지 않습니다. v1.4 설치 환경용 업데이트입니다. 새로 설치하려면 전체 프로젝트 ZIP을 사용하세요.

모의/GUI 42개 시험 통과. 실제 주문 및 Python 3.11 직접 실행은 미검증이며 가상 검증 기간이 실거래 승인으로 이어지는 것은 아닙니다.

---

'''
prior=(base/'UpbitAutoTrading_v1.4/README.md').read_text(encoding='utf-8').replace('v1.4','v1.5')
(release/'README.md').write_text(notes+prior,encoding='utf-8')
(release/'VALIDATION.md').write_text('''# v1.5 검증 결과
Windows Python 3.12.14 64bit / pandas 2.2.3: 기존 39개 + 일별 집계 3개 = 42개 모의·GUI 시험 통과.
추가 확인: KST 자정 전 매수/다음 날 부분익절·트레일링 날짜 분리, 매수만 있는 날짜 표시, 수수료·실현손익 합계 일치, 매도 없는 날 승률 공란, 최신 누락 시세를 이전 평가액으로 채우지 않음, 빈 DB에 가짜 날짜 생성 없음, CSV 재생성 중복 방지. 기존 GUI 시험에 손익 표의 매수/매도/손절 건수와 날짜 필터 검사를 추가했습니다.
실제 주문·Python 3.11 직접 실행·장기간 공개 API 운영·화면 육안 비교는 미검증입니다. 실거래 잠금 유지. 3.11 문법 파싱 및 ZIP CRC 검사 수행.
''',encoding='utf-8')
files=[p for p in release.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'reports' not in p.parts
       and p.suffix not in ('.pyc','.sqlite3','.lock','.csv','.log') and p.name not in ('.env','state.json','settings.json')]
for p in files:
    if p.suffix in ('.py','.pyw'): ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
full=base/'UpbitAutoTrading_v1.5_DailyProfit.zip'
patch=base/'Upbit_v1.5_DailyProfit_Update.zip'
with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files: z.write(p,Path('UpbitAutoTrading_v1.5')/p.relative_to(release))
with zipfile.ZipFile(patch,'w',zipfile.ZIP_DEFLATED) as z:
    for name in ('validation_app.py','daily_profit.py','main.py','dashboard.py','README.md','VALIDATION.md'):
        z.write(release/name,name)
for path in (full,patch):
    with zipfile.ZipFile(path) as z: assert z.testzip() is None
    print(path,'bytes=',path.stat().st_size,'CRC OK, Python 3.11 syntax OK')
