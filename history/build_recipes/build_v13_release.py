import ast
import zipfile
from pathlib import Path

base=Path(__file__).parent
release=base/'UpbitAutoTrading_v1.3'
readme='''# 업비트 자동매매 v1.3 — 가상매매·기록 검증 전용

## 시작하기
1. 기존 프로그램을 중지하고 종료하세요. 기존 폴더는 백업으로 보관합니다.
2. 이 ZIP을 새 폴더에 압축 해제합니다. Windows Python 3.11 64bit를 대상으로 작성했습니다.
3. install.bat을 실행하고, 설치 완료 후 start.bat을 실행합니다. 인터넷 연결이 필요합니다.
4. 시작을 누르면 공개 시세 스캔과 가상매매, 기록 저장이 진행됩니다. API 키는 필요 없습니다.
5. 처음에는 10분 정도 실행한 뒤 중지하고 가상 기록 메뉴에서 ZIP 내보내기를 시험해 보세요.
6. 정상 저장을 확인한 다음 7일을 첫 검토 기간으로 잡으세요. PC 절전/앱 종료/통신 중단 중에는 감시하지 못합니다.

실행 파일(.exe)이 아닌 전체 Python 프로젝트입니다. requirements는 pandas==2.2.3입니다. 시험 환경은 Windows Python 3.12.14였으며, Python 3.11 직접 실행은 미검증입니다.

## v1.3 변경점
- 네온 대시보드·실제 조회 차트·위험관리 제어판을 유지했습니다.
- validation.sqlite3에 스캔 시작/완료/중단/오류, 후보 순위/거래대금/가격, RSI·SMA·추세·제외 사유, 완료된 5분봉, 가상 포지션 시세, 자산 스냅샷, 로그, 가상 매매를 누적 저장합니다.
- 조회 오류가 난 후보도 기록합니다. 중단으로 검사하지 못한 후보는 스캔 대기로 남으며, 해당 스캔은 중단으로 표시됩니다.
- 초기 가상 자금은 1,000,000원입니다. 편도 수수료 0.05%, 매수는 +0.05%/매도는 -0.05% 불리한 슬리피지를 가정합니다. 이 값은 실제 계좌 수수료나 실제 슬리피지 측정값이 아닙니다.
- 가상 1차 익절 후 잔량·트레일링·손절·최대 보유 종목 수·연속손절 제한·15분 재진입 대기를 적용합니다. 수익률 트리거는 가격 기준이며 실현손익은 수수료를 포함합니다.
- 가상 잔고/보유/수수료/손익/최고가/1차익절 여부/재진입 대기는 재시작 후 복원됩니다. KST 날짜가 바뀌면 가상 연속손절 횟수만 초기화합니다.
- 실제 계좌와 가상 기록은 분리됩니다. 기존 실거래 거래내역과 손익 탭은 기존 CSV를 읽는 용도입니다. 대시보드 보유와 손익은 가상 기록을 표시합니다. 실거래 계좌 보유 코인은 이 버전에서 자동 관리하지 않습니다.
- 실제 주문 체크박스는 잠겨 있습니다. start.bat은 validation_app.py를 실행합니다. main.py와 dashboard.py의 구버전 실행 진입점도 잠갔습니다. 이 버전을 실거래용으로 사용하지 마세요.

## 기존 버전에서 가져올 파일
설정을 유지하려면 settings.json을 복사하세요. 기존 거래 조회가 필요하면 transactions.csv, daily_pnl.csv, trades.csv를 복사할 수 있습니다. 실제 계좌 잔고는 가상 잔고로 인수하지 않습니다. .env는 필요 없습니다. 기존 execution.sqlite3/state.json은 운영 백업으로 보관하세요. 가상 DB와 섞거나 이름을 바꾸지 마세요.

v1.3을 다른 폴더로 이동할 때는 validation.sqlite3와 settings.json을 함께 복사해야 가상 검증을 이어갈 수 있습니다. 동일 프로그램을 다른 폴더에서 동시에 실행하지 마세요. 가상 검증을 유지하려면 DB를 삭제하지 마세요.

## 7일 후 전달할 파일
중지 → 감시 종료 확인 → 왼쪽 가상 기록 → 검토용 기록 ZIP 내보내기.

프로그램 폴더의 reports/validation_날짜_시간.zip을 이 채팅에 첨부하세요. 내보내기는 큰 DB에서 시간이 걸릴 수 있습니다. 내보내는 동안 종료하지 마세요.

ZIP에는 validation.sqlite3, summary.json, scans.csv, observations.csv, trades.csv, logs.csv, equity.csv, paper_trades.csv, paper_daily.csv, README.txt가 들어 있습니다. 처음 5개 CSV의 일부 열은 상세 구조를 보존하는 JSON입니다. paper_trades.csv와 paper_daily.csv는 읽기 쉬운 펼친 거래/일별 요약입니다. 캔들·시세 원본은 DB에 포함됩니다. API 키·.env·실계좌 execution.sqlite3는 포함하지 않습니다.

7일이 지났다고 실거래 전환 조건이 충족되는 것은 아닙니다. 스캔 중단/오류/데이터 공백, 전략 판단, 가상 손익·낙폭·비용, 손절/익절 발생 여부를 함께 검토해야 합니다. 조건이 발생하지 않은 기능은 별도 시험이 필요합니다. 며칠간 켜둔 기간 전체를 연속 정상 가동 시간으로 간주하지 마세요. 관찰 모드였던 v1.2 기간은 소급 기록할 수 없습니다.

## 시뮬레이션 한계
가상 주문은 조회한 가격에 비용을 적용해 즉시 전량 체결된다고 가정합니다. 실제 호가·시장 충격·부분체결·주문 거절·잔고 반영 지연을 재현하지 않습니다. 최소 매도 금액은 5,000원으로 가정하여 작은 잔량은 남을 수 있습니다. 감시는 순차 처리이며 거래소에 손절 주문을 미리 넣지 않습니다. 통신 장애 동안 가격 변동을 복원하지 못하며, 재연결 후 새 시세로만 판단합니다.

손익은 가상 결과입니다. 평가자산은 잔고+보유 시세이고 예상 청산 수수료를 공제하지 않습니다. 일부 보유 시세가 없으면 자산 스냅샷을 빈 값으로 남깁니다. 종목별 최신 시세가 있어도 모든 시세가 완전히 같은 시점에 조회된 것은 아닙니다. 관찰 기록은 디스크 용량이 허용하는 한 계속 누적되며 자동 삭제하지 않습니다.

실제 주문·미확인 주문의 자동 복구 안전성은 검증되지 않았습니다. 기존 모의 주문 시험은 실제 업비트 체결 검증을 대신하지 않습니다. v1.3의 가상매매 재시작 복구와 실계좌 주문 복구는 서로 다른 기능입니다. 실전 안전 또는 수익성을 보장하지 않습니다.

test.bat은 임시 DB·모의 시세·숨겨진 GUI로 시험합니다. 자세한 결과는 VALIDATION.md를 참고하세요.
'''
(release/'README.md').write_text(readme,encoding='utf-8')
report='''# v1.3 검증 결과

검증일: 2026-10-15 한국시간. Windows 64bit, Python 3.12.14, pandas 2.2.3, pyupbit 0.2.34.

기존 주문/GUI 모의 시험 23개 + 신규 가상매매/기록/루프/GUI 시험 12개 = 총 35개.

신규 범위: 편도 수수료/불리한 슬리피지, 중복매수 방지, 가상 재시작 복원, 부분익절→트레일링, 손절 제한→일일 초기화, 최대보유/가용금액/재진입 대기, 누락 시세/최소 주문액, 저장 실패 시 포트폴리오 보존, 스캔·오류·후보·가상 체결 기록, 중단 스캔 복원, ZIP 내보내기/비밀정보 제외, 가상 GUI/실주문 진입 차단.

실제 API 키와 실제 주문을 사용하지 않았습니다. 모의 입력으로 검증했습니다. Python 3.11 직접 실행, 실제 공개 API의 장시간 가동, 7일 연속 관찰, 화면 육안/DPI 비교, OS 강제 종료/디스크 고장, 실제 업비트 체결 및 실계좌 재시작 복구는 미검증입니다. 3.11 문법 파싱과 ZIP CRC 검사도 수행합니다.

v1.3은 실거래 잠금 버전이며 가상 체결은 즉시 전량 체결 가정입니다. 35개 시험 통과는 실전 안전성 보증이 아닙니다.
'''
(release/'VALIDATION.md').write_text(report,encoding='utf-8')
files=[p for p in release.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'reports' not in p.parts
       and p.suffix not in ('.pyc','.sqlite3','.lock') and p.name not in ('.env','state.json','settings.json','transactions.csv','daily_pnl.csv','trades.csv')]
for p in files:
    if p.suffix=='.py': ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,11))
path=base/'UpbitAutoTrading_v1.3_Validation.zip'
with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files): z.write(p,Path('UpbitAutoTrading_v1.3')/p.relative_to(release))
with zipfile.ZipFile(path) as z:
    assert z.testzip() is None
    assert not any(n.endswith('/.env') or n.endswith('.sqlite3') for n in z.namelist())
    print(path, 'files=',len(z.namelist()),'bytes=',path.stat().st_size,'CRC OK; Python 3.11 syntax OK')
