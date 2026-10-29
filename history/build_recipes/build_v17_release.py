import ast
import zipfile
from pathlib import Path

base=Path(__file__).parent
release=base/'UpbitAutoTrading_v1.7'
for name in ('validation_app.py','main.py','dashboard.py'):
    p=release/name
    p.write_text(p.read_text(encoding='utf-8-sig').replace('v1.6','v1.7'),encoding='utf-8')
readme='''# 업비트 가상매매 v1.7 — 통신 장애 대응 보완

## 기존 사용자는 업데이트 ZIP 적용
1. 프로그램에서 중지를 누르고 감시 종료 후 창을 닫습니다.
2. 기존 validation.sqlite3를 별도로 백업합니다.
3. Upbit_v1.7_Network_Update.zip을 C:\\UpbitAutoTrading에 풀고 프로그램 파일을 덮어씁니다.
4. 기존 바탕화면 업비트 자동매매 아이콘으로 실행합니다. 재설치나 API 키 입력은 필요 없습니다.
5. 시작 직후 통신 복구 확인 1/2와 신규 매수 잠금이 보이는 것은 정상입니다. 5초 이상 떨어진 종합 확인 2회가 필요하며 보통 다음 스캔(약 30초 이후)에서 진입 잠금이 해제됩니다.

업데이트 ZIP에는 운영 DB·설정·CSV·.env가 들어 있지 않습니다. 기존 가상 잔고·보유·당일 재매수 제한·손익을 초기화하지 않습니다. 기존 바로가기가 launch.pyw를 실행하는 구조도 유지합니다. 새 폴더에 전체 ZIP을 설치하는 경우 Python 3.11 64bit 대상이며 install.bat 설치 후 실행.vbs를 더블클릭하세요. 실제 직접 시험은 Python 3.12.14에서 수행했습니다.

## 통신 안전 게이트
- 시작/재시작 시 신규 가상매수 잠금. 원화마켓 BTC 기준 시세와 현재 가상 보유종목 시세의 성공을 종합 확인합니다.
- 정상 종합 확인은 최소 5초 떨어진 2회가 필요합니다. 오류가 있으면 카운트를 초기화합니다.
- 마지막 종합 확인 후 45초를 넘으면 신규 가상매수를 차단합니다. 다음 정상 수신 1회만으로 바로 진입을 허용하지 않습니다.
- 매수 직전에 해당 종목의 시세를 다시 조회합니다. 누락/0/NaN/무한대/90초 초과 시각/10초 초과 미래 시각은 거부합니다. 시각 판정은 PC 시계에 의존하므로 Windows 시각 동기화가 필요합니다. 체결이 뜸한 종목은 보수적으로 제외될 수 있습니다.
- 네트워크/DNS/HTTP 오류는 통신 실패로 처리합니다. 충분한 캔들이 없는 경우는 해당 종목의 진입 제외로 구분합니다. 통신 실패 시 당회 후보 조회를 더 진행하지 않고 재시도합니다.
- 신규 매수를 잠가도 최신 시세가 확인된 기존 보유종목의 가상 손절/익절/트레일링은 계속 평가합니다. 일부 보유 시세가 누락됐으면 확인된 나머지 종목만 감시합니다.
- 조회 실패한 보유종목은 화면의 캐시 가격을 지워 오래된 현재가로 오해하지 않도록 합니다. 없는 가격을 만들어 청산하거나, 통신 공백 중 고점/저점을 복원하지 않습니다.
- 장애 시 대기 간격은 최소 30초입니다. 동일 오류는 횟수를 누적하되 상세 오류 기록은 60초 간격으로 줄입니다. 장애 시작/복구 확인/복구 완료는 별도 이벤트로 저장합니다.

## 표시와 기록
상단 신호등은 통신 장애/수신 지연 때 빨강, 복구 확인 때 노랑, 정상 실행 때 초록으로 표시합니다. 마지막 종합 정상 수신 시각과 복구 확인 횟수, 신규 가상매수 잠금 여부를 별도 줄에 표시합니다.
validation.sqlite3에 network_events(장애·복구·검증 구간·설정), health_checks(15초 단위 통신 상태)를 추가합니다. 기존 표는 삭제하지 않습니다. 재실행과 시작 버튼마다 새 검증 구간과 그때의 설정을 기록합니다. 앱을 껐던 시간은 정상 가동으로 간주하지 않습니다. 장애 지속 시간은 앱이 관측한 구간이며 앱 중단 전후의 전체 장애 시간을 확정하는 값은 아닙니다.
가상 기록 → 검토용 기록 ZIP 내보내기에 network_events.csv, health_checks.csv가 포함됩니다. summary.json의 버전 표기를 1.7로 바로잡았습니다. 기존 일자별 손익/거래 내역/paper_trades.csv/paper_daily.csv는 유지합니다.

## 추가 1주일 검증
적용한 시점부터 새 구간으로 구분하고 현재 매매 설정을 고정해 관찰하세요. 오래된 결과를 지우거나 검증을 위해 손절/익절/연속손절 제한을 임의로 바꾸지 마세요. 비가동 시간은 별도로 알려주세요. 재검토 때 네트워크 장애 빈도와 복구 후 진입 잠금, 실제 정상 관측 구간, 손익과 위험 관리 기록을 함께 확인합니다.
새 프리즘 전략이나 실거래 기능은 이번 수정에 추가하지 않았습니다. 신호등이 초록이거나 일주일이 지났다는 이유만으로 실거래를 승인하지 않습니다.

## 중요한 한계
이번 보완은 DNS/인터넷 장애의 운영체제 원인을 고치는 프로그램이 아닙니다. 연결이 끊긴 동안 자동 청산은 불가능하며 손실 상한을 보장하지 않습니다. 장애 후 재개 시 새 시세로 가상 청산하므로 손절 설정보다 손실이 클 수 있습니다. 거래소에 손절 주문을 미리 걸지 않습니다.
실거래 잠금 유지. 가상 체결은 수수료/불리한 슬리피지를 가정한 즉시 전량 체결이며 실제 호가·부분체결·주문 거절·잔고 반영을 검증하지 않습니다. 실제 주문, Python 3.11 직접 실행, 장기간 운용 및 다양한 DPI 육안 검증은 미완료입니다.

## 시험
test.bat으로 보완 범위 26개 모의/GUI 시험을 실행할 수 있습니다. 상세 결과는 VALIDATION.md를 참고하세요.
'''
(release/'README.md').write_text(readme,encoding='utf-8')
(release/'VALIDATION.md').write_text('''# v1.7 검증 결과 (2026-10-22 KST)

Windows Python 3.12.14 64bit / pandas 2.2.3 / pyupbit 0.2.34. 통신 보완 범위의 모의·GUI·통합 시험 26개 통과. 이전 버전 전체 54개 회귀 시험을 재실행했다고 주장하지 않습니다.

확인한 항목: 시작 잠금, 두 차례 간격 확인, 오류 후 카운트 초기화, 수신 지연 진입 차단, 긴 공백 후 재확인, 오류 기록 빈도 제한과 장애 지속 시간, 재시작 잠금, 최신/오래된/미래/NaN/0 시세, 누락 시세, 보유 일부 시세만 유효한 경우, 빈 응답, 요청 timeout, HTTP 오류, 진입 직전 조회 실패, 캐시 가격으로 청산하지 않음, 복구 확인 중 최신 시세의 청산 허용, 캔들 부족과 통신 오류 구분, 기존 가상 상태 보존, 전체 루프에서 첫 확인 시 매수 금지/다음 확인 후 매수, GUI 통신 표시, 당일 재매수 제한 유지, 실제 주문 진입 차단, 기록 ZIP의 통신 테이블과 버전.

공개 API 확인: ticker/all 298개 원화마켓 수신, BTC 응답 시각 유효, 5분 캔들 80개와 정렬 확인. 계좌 인증 및 실제 주문 없음. 제한 환경에서는 DNS 조회가 실패했으며 승인된 제한 외 조회에서 성공했습니다. 이는 사용자 PC의 모든 네트워크 문제 해결을 증명하지 않습니다.

미검증: 실제 주문/체결, Python 3.11 직접 실행, 장기간 실시간 운용, Windows 시간 오류 및 전원/디스크 고장, 모든 DPI 화면 비교. 3.11 문법 파싱 및 ZIP CRC 검사를 수행합니다.
''',encoding='utf-8')
files=[p for p in release.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'reports' not in p.parts
       and p.suffix not in ('.pyc','.sqlite3','.lock','.csv','.log') and p.name not in ('.env','state.json','settings.json')]
for p in files:
    if p.suffix in ('.py','.pyw'): ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
full=base/'UpbitAutoTrading_v1.7_NetworkGuard.zip'; patch=base/'Upbit_v1.7_Network_Update.zip'
with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files: z.write(p,Path('UpbitAutoTrading_v1.7')/p.relative_to(release))
with zipfile.ZipFile(patch,'w',zipfile.ZIP_DEFLATED) as z:
    for name in ('validation_app.py','dashboard.py','network_guard.py','market_data.py','README.md','VALIDATION.md'):
        z.write(release/name,name)
for path in (full,patch):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert not any(n.endswith('.sqlite3') or n.endswith('/.env') for n in z.namelist())
    print(path,'bytes=',path.stat().st_size,'CRC OK; Python 3.11 syntax OK')
