"""Fail-closed execution journal. All order mutations are serialized by one worker."""
import json
import math
import sqlite3
from contextlib import contextmanager
from decimal import Decimal


class SafetyError(RuntimeError):
    pass


def number(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise SafetyError('유효하지 않은 API 수치')
    return result


def validate_settings(c):
    bounds = {'order_krw': (5000, 10000000), 'max_positions': (1, 50),
              'stop_pct': (0.1, 50), 'target_pct': (0.1, 100),
              'trailing_pct': (0.1, 50), 'first_fraction': (0.05, 0.95),
              'max_losses': (1, 100), 'top_n': (1, 500), 'poll_seconds': (5, 600)}
    for k, (low, high) in bounds.items():
        v = float(c[k])
        if not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{k}: {low} ~ {high} 범위로 입력하세요')
    for k in ('max_positions', 'max_losses', 'top_n', 'poll_seconds'):
        if float(c[k]) != int(c[k]):
            raise ValueError(f'{k}: 정수로 입력하세요')
    return c


def filled_order(order, uid, market, side):
    if not isinstance(order, dict) or order.get('uuid') != uid:
        raise SafetyError('주문 UUID 불일치')
    if order.get('market') != market or order.get('side') != side:
        raise SafetyError('주문 종목/방향 불일치')
    if order.get('state') not in ('done', 'cancel'):
        raise SafetyError('미종결 주문: 자동 재주문 금지')
    qty = number(order.get('executed_volume'))
    fee = number(order.get('paid_fee'))
    trades = order.get('trades', [])
    if not isinstance(trades, list):
        raise SafetyError('체결 내역 형식 오류')
    volume = sum(number(t['volume']) for t in trades)
    funds = sum(number(t['funds']) for t in trades)
    if abs(volume - qty) > max(1e-10, qty * 1e-7):
        raise SafetyError('체결 내역과 수량 불일치')
    if qty > 0 and funds <= 0:
        raise SafetyError('체결 금액 없음')
    return qty, funds, fee


def balances_map(rows):
    if not isinstance(rows, list) or not rows:
        raise SafetyError('잔고 응답 오류/빈 응답')
    result = {}
    for row in rows:
        cur = row['currency']
        if cur in result:
            raise SafetyError('중복 잔고')
        result[cur] = {'free': number(row['balance']), 'locked': number(row['locked']),
                       'avg': number(row['avg_buy_price'])}
    if 'KRW' not in result:
        raise SafetyError('원화 잔고 없음')
    return result


class Journal:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY, market TEXT, side TEXT, qty REAL, reason TEXT,
              uuid TEXT UNIQUE, status TEXT NOT NULL, response TEXT);
            CREATE TABLE IF NOT EXISTS events (uuid TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def load_state(self, default):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='state'").fetchone()
        return json.loads(row[0]) if row else default

    def save_state(self, state):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('state', ?)", (json.dumps(state),))

    def pending(self):
        with self.connect() as db:
            return db.execute("SELECT id,market,side,uuid,status FROM orders WHERE status != 'settled'").fetchall()

    def intent(self, market, side, qty, reason):
        if self.pending():
            raise SafetyError('미확인 주문이 있어 모든 신규 주문을 차단합니다')
        with self.connect() as db:
            return db.execute('INSERT INTO orders(market,side,qty,reason,status) VALUES(?,?,?,?,?)',
                              (market, side, qty, reason, 'intent')).lastrowid

    def accepted(self, oid, uid):
        with self.connect() as db:
            db.execute("UPDATE orders SET uuid=?,status='accepted' WHERE id=?", (uid, oid))

    def settle(self, oid, uid, state, event, response):
        # State, fill event and order status commit together; replay cannot double-count.
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('state',?)", (json.dumps(state),))
            if event:
                db.execute('INSERT INTO events VALUES(?,?)', (uid, json.dumps(event)))
            db.execute("UPDATE orders SET status='settled',response=? WHERE id=?",
                       (json.dumps(response), oid))

    def events(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM events ORDER BY rowid')]


def reconcile(positions, balances):
    """Never adopt manual holdings or silently alter strategy quantities."""
    for market, pos in positions.items():
        cur = market.split('-')[1]
        b = balances.get(cur, {'free': 0, 'locked': 0, 'avg': 0})
        expected = number(pos['qty'])
        if b['locked'] > 0 or abs(b['free'] - expected) > max(1e-8, expected * 1e-6):
            raise SafetyError(f'{market}: 저장 수량/가용 잔고 불일치 또는 잠긴 잔고')
        avg = number(pos['avg'])
        if avg <= 0 or abs(b['avg'] - avg) > max(0.01, avg * 0.001):
            raise SafetyError(f'{market}: 평균단가 불일치')


def sell_volume(qty):
    return float(Decimal(str(qty)).quantize(Decimal('0.00000001'), rounding='ROUND_DOWN'))
