import ast
import zipfile
from pathlib import Path

base=Path(__file__).parent
release=base/'UpbitAutoTrading_v1.4'
for filename in ('validation_app.py','dashboard.py','main.py'):
    p=release/filename
    source=p.read_text(encoding='utf-8-sig').replace('v1.3','v1.4')
    p.write_text(source,encoding='utf-8')
previous=(base/'UpbitAutoTrading_v1.3/README.md').read_text(encoding='utf-8').replace('v1.3','v1.4').replace('7일','5일')
changes='''# v1.4 거래 내역 개선

## 검은 창 없이 실행
설치는 install.bat으로 한 번만 진행합니다. 이후에는 프로그램 폴더의 **실행.vbs**를 더블클릭하세요. Python GUI 전용 실행기를 사용하므로 검은 명령창을 유지하지 않습니다.
바탕화면에는 실행.vbs의 바로가기를 만들어 사용하세요. 실행.vbs 파일 자체를 프로그램 폴더 밖으로 옮기지는 마세요. 실행 실패 시 startup.log에 오류가 기록되고 안내 창이 나타납니다. start.bat은 문제 확인용으로 계속 사용할 수 있습니다.

왼쪽 **거래 내역**을 누르면 가상 매수·매도·손절·1차 익절·트레일링 기록이 기본으로 표시됩니다.
종목·시작일·종료일·유형으로 필터링하고 번호·KST 일시·가상 체결가·수량·금액·수수료·실현손익·사유를 확인할 수 있습니다.
화면은 최근 2,000건, 합계와 CSV는 전체 기록 기준입니다. 가상 기록 메뉴의 최근 500건 보기와 ZIP 내보내기도 유지합니다.
기존 실거래 CSV는 거래 내역의 '기존 실거래 기록 보기 / 숨기기'로 별도 조회합니다. 가상 기록과 섞어 합산하지 않습니다.

**익절 전체**는 실현손익이 양수인 매도만 표시합니다. 트레일링은 급락 시 손실일 수도 있어 별도 유형으로 표시합니다.
매수의 실현손익은 화면에서 —입니다. 실제로 발생한 가상 체결만 기록하며, 진입 신호가 없으면 매수 기록도 없습니다.

## 기존 검증을 이어가는 업데이트
1. v1.3에서 중지를 누르고 감시 종료 후 프로그램을 종료합니다.
2. 기존 validation.sqlite3를 별도 백업합니다. 이 DB에 지금까지의 가상 거래·잔고·보유·스캔이 들어 있습니다.
3. 이 ZIP을 새 폴더에 풉니다. validation.sqlite3와 settings.json(있는 경우)을 새 프로그램 폴더에 복사합니다.
4. install.bat → start.bat 순서로 실행합니다. 기존 파일/폴더를 지우거나 DB를 새로 만들지 마세요.
5. 거래 내역에 이전 기록이 보이는지 확인하고 시작합니다. 기존 5일 검증을 이어갈 수 있습니다.

## 자동 저장 CSV
시작 시와 가상 거래 발생 시 프로그램 폴더에 **paper_trades.csv**를 자동 저장합니다. SQLite 기록을 번호 기준으로 재생성해 중복을 방지합니다.
이전 v1.3에 저장된 가상 체결도 자동으로 CSV에 복원됩니다. DB가 기준이고 CSV는 읽기 편한 사본입니다.
CSV를 Excel 등으로 열어 잠근 경우 저장이 실패할 수 있습니다. 이때 DB 기록을 보존하고 가상 실행을 중지합니다. CSV를 닫고 재시작하세요.
기록 내보내기 ZIP의 paper_trades.csv에도 번호와 거래 유형을 포함합니다.

실거래 잠금과 가상 매매 규칙은 유지했습니다. 실제 주문과 Python 3.11 직접 실행은 미검증입니다.

---

'''
(release/'README.md').write_text(changes+previous,encoding='utf-8')
(release/'VALIDATION.md').write_text('''# v1.4 검증 결과

Windows Python 3.12.14 64bit / pandas 2.2.3에서 모의·GUI 시험 총 39개 통과.
이전 35개 시험을 유지하고 거래 이력 시험 4개를 추가했습니다. 기존 GUI 시험에 원장·손절 필터·CSV 잠금 실패 시 DB 보존과 중지 검사를 추가했습니다.

확인 범위: 기존 DB의 CSV 복원, 재생성/재시작 중복 방지, 매수·손절 기록 구분, 부분익절·트레일링 조회, 종목·날짜 필터, 화면 표시 제한과 전체 합계 분리, 손실 트레일링의 익절 분류 방지, 빈 기록에 가짜 거래 없음, ZIP의 번호/유형 포함, 원장 GUI 표시, CSV 저장 실패 시 체결/가상 상태 보존.

실제 공개 API 장시간 가동·실제 계좌 주문/체결·Python 3.11 직접 실행·다양한 DPI의 육안 검증은 미완료입니다. 3.11 문법 파싱과 ZIP CRC 검사는 수행했습니다. 가상 체결은 즉시 전량 체결 가정이며, 실전 안전성 보장이 아닙니다.
''',encoding='utf-8')
files=[p for p in release.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'reports' not in p.parts
       and p.suffix not in ('.pyc','.sqlite3','.lock','.csv') and p.name not in ('.env','state.json','settings.json')]
for p in files:
    if p.suffix in ('.py','.pyw'): ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
path=base/'UpbitAutoTrading_v1.4_TradeHistory.zip'
with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files): z.write(p,Path('UpbitAutoTrading_v1.4')/p.relative_to(release))
with zipfile.ZipFile(path) as z:
    assert z.testzip() is None
    print(path,'files=',len(z.namelist()),'bytes=',path.stat().st_size,'CRC OK, Python 3.11 syntax OK')
