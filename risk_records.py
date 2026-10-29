import copy
import json
import math
from pathlib import Path
from paper import Records,Paper,trading_day
from market_guard import POLICY

class RiskBook:
    def __init__(self,records):
        self.records=records; self.daily=dict(entry_allowed=False,reason='당일 평가 확인 전',drawdown=None)
        with records.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS market_checks(id INTEGER PRIMARY KEY,stamp TEXT,scan_id INTEGER,payload TEXT);
            CREATE TABLE IF NOT EXISTS entry_decisions(id INTEGER PRIMARY KEY,stamp TEXT,market TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS risk_days(day TEXT PRIMARY KEY,stamp TEXT,baseline REAL,last_equity REAL,locked INTEGER,payload TEXT);
            ''')

    def record(self,table,stamp,payload,market=None,scan=None):
        encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        with self.records.db() as db:
            if table=='market_checks': db.execute('INSERT INTO market_checks(stamp,scan_id,payload) VALUES(?,?,?)',(stamp,scan,encoded))
            elif table=='entry_decisions': db.execute('INSERT INTO entry_decisions(stamp,market,payload) VALUES(?,?,?)',(stamp,market,encoded))
            else: raise ValueError('unknown risk table')

    def mark_equity(self,stamp,state,quotes):
        day=trading_day(stamp)
        if any(m not in quotes for m in state['positions']):
            self.daily=dict(entry_allowed=False,reason='보유 평가 시세 부족 · 신규 진입 잠금',drawdown=None)
            return self.daily
        equity=state['cash']+sum(p['qty']*quotes[m] for m,p in state['positions'].items())
        if not math.isfinite(equity) or equity<=0: raise ValueError('잘못된 평가자산')
        with self.records.db() as db:
            row=db.execute('SELECT baseline,locked FROM risk_days WHERE day=?',(day,)).fetchone()
            baseline,locked=row if row else (equity,0)
            dd=equity/baseline-1
            locked=bool(locked or dd<=-POLICY['daily_loss_limit'])
            self.daily=dict(entry_allowed=not locked,reason='당일 평가손실 2% 제한 · 신규 진입 잠금' if locked else '당일 손실 한도 이내',
                            drawdown=dd,baseline=baseline,equity=equity,day=day)
            db.execute('INSERT OR REPLACE INTO risk_days VALUES(?,?,?,?,?,?)',
                       (day,stamp,baseline,equity,int(locked),json.dumps(self.daily,ensure_ascii=False)))
        return self.daily

def benchmark(records,path,stamp,state):
    """Separate ledger, seeded once with unchanged current paper balances/locks."""
    reference_records=Records(Path(path))
    reference_state=reference_records.load()
    if reference_state is None:
        seeded=copy.deepcopy(state)
        seeded['benchmark_seed']=dict(stamp=stamp,policy='v1.7 signals, common v1.8 data schedule',
                                      realized=state['realized'],fees=state['fees'])
        reference_records.commit(seeded)
    elif 'benchmark_seed' not in reference_state:
        raise ValueError('비교 원장 초기 상태 확인 실패')
    return Paper(reference_records)
