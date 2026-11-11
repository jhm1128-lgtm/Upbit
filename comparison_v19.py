"""Independent forward v1.9 control; starts from the upgrade portfolio, never resets it."""
import copy
from paper import Records,Paper
from risk_records import RiskBook

def open_control(primary,path,config,stamp):
    records=Records(path); risk=RiskBook(records)
    saved=records.load()
    if saved is None:
        saved=copy.deepcopy(primary.load())
        saved['comparison_v19_seed']=dict(stamp=stamp,version='1.9',settings=copy.deepcopy(config),
            note='동일 업그레이드 잔고에서 독립 v1.9 전략 시작; 공통 시세/조회 일정')
        records.commit(saved)
        with primary.db() as db: rows=db.execute('SELECT * FROM risk_days').fetchall()
        with records.db() as db: db.executemany('INSERT OR IGNORE INTO risk_days VALUES(?,?,?,?,?,?)',rows)
    elif 'comparison_v19_seed' not in saved:
        raise ValueError('v1.9 비교 원장 초기 상태 확인 실패')
    return Paper(records),risk,dict(saved['comparison_v19_seed']['settings'])
