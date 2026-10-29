"""Persistent, atomic paper portfolio. Never calls an exchange order API."""
import copy
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta


def trading_day(stamp):
    parsed=datetime.fromisoformat(stamp)
    if parsed.tzinfo is None: raise ValueError('시간대 없는 거래 시각')
    return parsed.astimezone(timezone(timedelta(hours=9))).date().isoformat()


class Records:
    def __init__(self,path):
        self.path = str(path)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY,started TEXT,ended TEXT,status TEXT,settings TEXT);
            CREATE TABLE IF NOT EXISTS observations(scan_id INTEGER,market TEXT,stamp TEXT,payload TEXT,PRIMARY KEY(scan_id,market));
            CREATE TABLE IF NOT EXISTS candles(market TEXT,stamp TEXT,payload TEXT,PRIMARY KEY(market,stamp));
            CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,stamp TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,stamp TEXT,kind TEXT,message TEXT);
            CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY,stamp TEXT,market TEXT,price REAL);
            CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY,stamp TEXT,payload TEXT);
            ''')
            db.execute("UPDATE scans SET status='interrupted' WHERE status='running'")

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=20)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db: yield db
        finally: db.close()

    def log(self,stamp,kind,message):
        with self.db() as db: db.execute('INSERT INTO logs(stamp,kind,message) VALUES(?,?,?)',(stamp,kind,message))

    def start_scan(self,stamp,settings):
        with self.db() as db:
            return db.execute('INSERT INTO scans(started,status,settings) VALUES(?,?,?)',(stamp,'running',json.dumps(settings))).lastrowid

    def finish_scan(self,scan,stamp,status):
        if scan:
            with self.db() as db: db.execute('UPDATE scans SET ended=?,status=? WHERE id=?',(stamp,status,scan))

    def observation(self,scan,market,stamp,payload):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?)',(scan,market,stamp,json.dumps(payload,allow_nan=False)))

    def candles(self,market,rows):
        with self.db() as db:
            db.executemany('INSERT OR REPLACE INTO candles VALUES(?,?,?)',[(market,r['stamp'],json.dumps(r,allow_nan=False)) for r in rows])

    def load(self):
        with self.db() as db:
            row=db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def commit(self,state,event=None):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(json.dumps(state,allow_nan=False),))
            if event: db.execute('INSERT INTO trades(stamp,payload) VALUES(?,?)',(event['stamp'],json.dumps(event,allow_nan=False)))

    def snapshot(self,stamp,state,prices):
        missing=[m for m in state['positions'] if m not in prices]
        equity=None if missing else state['cash']+sum(p['qty']*prices[m] for m,p in state['positions'].items())
        payload=dict(cash=state['cash'],equity=equity,realized=state['realized'],fees=state['fees'],missing_prices=missing)
        with self.db() as db:
            db.execute('INSERT INTO equity(stamp,payload) VALUES(?,?)',(stamp,json.dumps(payload,allow_nan=False)))
            db.executemany('INSERT INTO quotes(stamp,market,price) VALUES(?,?,?)',[(stamp,m,p) for m,p in prices.items()])


class Paper:
    def __init__(self,records,initial_cash=1000000,fee=.0005,slippage_bps=5):
        if initial_cash < 5000 or not 0<=fee<=.01 or not 0<=slippage_bps<=100:
            raise ValueError('가상 초기잔고/수수료/슬리피지 범위 오류')
        self.records=records
        self.state=records.load() or dict(cash=initial_cash,initial_cash=initial_cash,positions={},
            realized=0.,fees=0.,loss_streak=0,day='',cooldowns={},fee=fee,slippage_bps=slippage_bps,
            closed=0,wins=0,started=None)
        # Recover daily reentry locks from existing v1.3-v1.5 SELL history.
        # Trade history and balances are left intact; this is additive state migration.
        if self.state.get('reentry_policy_version')!=1:
            sold_dates=self.state.setdefault('sold_dates',{})
            with records.db() as db:
                for (payload,) in db.execute('SELECT payload FROM trades'):
                    event=json.loads(payload)
                    if event['side']=='SELL':
                        day=trading_day(event['stamp']); market=event['market']
                        sold_dates[market]=max(day,sold_dates.get(market,''))
            self.state['reentry_policy_version']=1
        records.commit(self.state)

    def tick_day(self,stamp):
        day=trading_day(stamp)
        if self.state['day']!=day:
            s=copy.deepcopy(self.state); s['day']=day; s['loss_streak']=0
            self.records.commit(s); self.state=s

    def gate(self,market,c,stamp):
        self.tick_day(stamp)
        s=self.state
        if market in ('KRW-BTC','KRW-USDT','KRW-USDC','KRW-DAI'): return '전략 제외 종목'
        if s.get('sold_dates',{}).get(market)==trading_day(stamp): return '당일 매도 종목 · 재매수 금지 (KST 자정 해제)'
        if market in s['positions']: return '가상 보유 중'
        if len(s['positions'])>=c['max_positions']: return '가상 최대 보유 도달'
        if s['loss_streak']>=c['max_losses']: return '가상 연속 손절 제한'
        elapsed=datetime.fromisoformat(stamp).timestamp()-s['cooldowns'].get(market,0)
        if elapsed<900: return '가상 15분 재진입 대기'
        if s['cash']<c['order_krw']*(1+s['fee']): return '가상 원화 부족'
        return ''

    def buy(self,market,quote,c,stamp):
        if not math.isfinite(quote) or quote<=0: raise ValueError('잘못된 가상 매수가')
        reason=self.gate(market,c,stamp)
        if reason: return None
        s=copy.deepcopy(self.state)
        price=quote*(1+s['slippage_bps']/10000)
        funds=float(c['order_krw']); qty=funds/price; fee=funds*s['fee']
        s['cash']-=funds+fee; s['fees']+=fee
        s['cooldowns'][market]=datetime.fromisoformat(stamp).timestamp()
        s['positions'][market]=dict(avg=price,qty=qty,initial_qty=qty,peak=quote,
            first_target_done=False,entry_fee_remaining=fee,opened_at=stamp,realized=0.)
        if not s['started']: s['started']=stamp
        event=dict(stamp=stamp,side='BUY',market=market,quote=quote,price=price,qty=qty,funds=funds,fee=fee,pnl=0.,reason='가상 진입',simulation=True)
        self.records.commit(s,event); self.state=s
        return event

    def sell(self,market,quote,qty,reason,stamp):
        if not math.isfinite(quote) or quote<=0: raise ValueError('잘못된 가상 매도가')
        s=copy.deepcopy(self.state); p=s['positions'][market]
        qty=min(float(qty),p['qty'])
        if not math.isfinite(qty) or qty<=0: raise ValueError('잘못된 가상 매도 수량')
        price=quote*(1-s['slippage_bps']/10000); funds=qty*price
        if funds<5000: return None
        fee=funds*s['fee']; entry_fee=p['entry_fee_remaining']*qty/p['qty']
        pnl=funds-fee-p['avg']*qty-entry_fee
        s['cash']+=funds-fee; s['fees']+=fee; s['realized']+=pnl
        s.setdefault('sold_dates',{})[market]=trading_day(stamp)
        p['realized']+=pnl; p['entry_fee_remaining']-=entry_fee; p['qty']-=qty
        if reason=='1차 익절': p['first_target_done']=True; p['peak']=quote
        if p['qty']<=max(1e-12,p['initial_qty']*1e-10):
            s['closed']+=1
            if p['realized']>0: s['wins']+=1
            if reason=='손절': s['loss_streak']+=1
            elif p['realized']>0: s['loss_streak']=0
            del s['positions'][market]
        event=dict(stamp=stamp,side='SELL',market=market,quote=quote,price=price,qty=qty,funds=funds,fee=fee,pnl=pnl,reason=reason,simulation=True)
        self.records.commit(s,event); self.state=s
        return event

    def monitor(self,prices,c,stamp):
        self.tick_day(stamp)
        events=[]
        for market in list(self.state['positions']):
            if market not in prices: continue
            quote=prices[market]
            if not math.isfinite(quote) or quote<=0: raise ValueError('잘못된 가상 감시 시세')
            p=self.state['positions'][market]
            if quote>p['peak']:
                s=copy.deepcopy(self.state); s['positions'][market]['peak']=quote
                self.records.commit(s); self.state=s; p=s['positions'][market]
            pct=(quote/p['avg']-1)*100
            reason=None; qty=p['qty']
            if pct<=-c['stop_pct']: reason='손절'
            elif not p['first_target_done'] and pct>=c['target_pct']:
                reason='1차 익절'; qty*=c['first_fraction']
            elif p['first_target_done'] and quote<=p['peak']*(1-c['trailing_pct']/100): reason='트레일링'
            if reason:
                event=self.sell(market,quote,qty,reason,stamp)
                if event: events.append(event)
        return events
