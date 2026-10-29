import csv
import copy
import json
import math
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
import legacy_ui as legacy
from legacy_ui import pyupbit, pd, now_kst, fmt_num
from safety import Journal, SafetyError, balances_map, reconcile, filled_order, validate_settings, sell_volume
import requests
import pyupbit.request_api as request_api


class BoundedTransport:
    """Timeout each pyupbit request; never retry order POST requests."""
    @staticmethod
    def get(url, **kwargs):
        kwargs.setdefault('timeout', (4, 10))
        return requests.get(url, **kwargs)

    @staticmethod
    def post(url, **kwargs):
        kwargs.setdefault('timeout', (4, 10))
        return requests.post(url, **kwargs)

    @staticmethod
    def delete(url, **kwargs):
        kwargs.setdefault('timeout', (4, 10))
        return requests.delete(url, **kwargs)


request_api.requests = BoundedTransport

DEFAULTS = dict(order_krw=150000, max_positions=3, stop_pct=3, target_pct=5,
                trailing_pct=2, first_fraction=0.5, max_losses=3, top_n=15, poll_seconds=15)
BG, PANEL, FIELD, TEXT, MUTED, ACCENT = '#0b1426', '#14223b', '#1b2e4b', '#e8efff', '#a7b9d6', '#45c9da'


def atomic_json(path, value):
    temp = Path(str(path) + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class UpbitAutoTrader(legacy.UpbitAutoTrader):
    def __init__(self, root):
        self.messages = queue.Queue()
        self.stop_event = threading.Event()
        self.live_event = threading.Event()
        self.errors = 0
        self.prices = {}
        self.scan_text = '대기'
        self.last_scan = '-'
        self.balance_text = '조회 전'
        self.safety_text = '시작 전 잔고 대조 필요'
        self.ready = False
        self.fault = False
        self.config = DEFAULTS.copy()
        self.journal = Journal(BASE / 'execution.sqlite3')
        if (BASE / 'settings.json').exists():
            self.config.update(json.loads((BASE / 'settings.json').read_text(encoding='utf-8')))
        validate_settings(self.config)
        super().__init__(root)
        self.root.title('Upbit Auto Trading v1.2 · 체결 확인 / 안전 잠금')
        self.root.geometry('1460x960')
        self.root.after(250, self.pump)

    def build_ui(self):
        super().build_ui()
        self.root.configure(bg=BG)
        style = ttk.Style()
        style.configure('.', background=PANEL, foreground=TEXT, font=('맑은 고딕', 10),
                        fieldbackground=FIELD, bordercolor=BG, lightcolor=PANEL, darkcolor=BG)
        style.configure('TFrame', background=PANEL)
        style.configure('TLabel', background=PANEL, foreground=TEXT)
        style.configure('TLabelframe', background=PANEL, bordercolor=FIELD)
        style.configure('TLabelframe.Label', foreground=ACCENT, background=PANEL)
        style.configure('TButton', background=FIELD, foreground=TEXT, padding=6)
        style.map('TButton', background=[('active', '#28466b')])
        style.configure('TCheckbutton', background=PANEL, foreground=TEXT)
        style.configure('TCheckbutton', indicatorbackground=FIELD, indicatorforeground=ACCENT)
        style.map('TCheckbutton', background=[('active', PANEL)])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(18, 10))
        style.map('TNotebook.Tab', background=[('selected', FIELD)], foreground=[('selected', ACCENT)])
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=31, borderwidth=0)
        style.configure('Treeview.Heading', background=FIELD, foreground=ACCENT, padding=8)
        style.map('Treeview', background=[('selected', '#28517a')], foreground=[('selected', '#ffffff')])
        style.map('Treeview.Heading', background=[('active', '#28466b')])
        style.configure('TCombobox', fieldbackground=FIELD, background=FIELD, foreground=TEXT)
        style.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TEXT)],
                  selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TEXT)])
        style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT)
        style.configure('TScrollbar', background=FIELD, troughcolor=BG, arrowcolor=ACCENT,
                        bordercolor=BG, lightcolor=FIELD, darkcolor=FIELD)
        self.root.option_add('*TCombobox*Listbox.background', FIELD)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#28517a')
        self.log_text.configure(bg=BG, fg=TEXT, insertbackground=TEXT, selectbackground=FIELD,
                                highlightthickness=0, relief='flat')
        self.recolor(self.root)
        self.replace_copy(self.root)
        self.candidate_tree.configure(columns=('rank','market','value','price','rsi','trend','signal','reason'))
        heads = [('rank','순위',55),('market','종목',110),('value','24시간 거래대금',170),
                 ('price','현재가',110),('rsi','RSI(14)',80),('trend','추세',90),
                 ('signal','조건 통과',100),('reason','제외 / 대기 사유',420)]
        for c, title, width in heads:
            self.candidate_tree.heading(c, text=title)
            self.candidate_tree.column(c, width=width, anchor='center')
        for tree in (self.position_tree,self.trade_tree,self.daily_tree,self.candidate_tree):
            parent = tree.master
            tree.pack_forget()
            bar = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
            bar.pack(side='right', fill='y')
            hbar = ttk.Scrollbar(parent, orient='horizontal', command=tree.xview)
            hbar.pack(side='bottom', fill='x')
            tree.configure(yscrollcommand=bar.set, xscrollcommand=hbar.set)
            tree.pack(fill='both', expand=True)
        settings_tab = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(settings_tab, text='위험관리 제어판')
        self.setting_vars = {}
        specs = [('order_krw','1회 매수 금액 (원)'),('max_positions','최대 보유 종목 수'),
                 ('stop_pct','손절 (%) · 양수 입력'),('target_pct','1차 익절 (%)'),
                 ('trailing_pct','트레일링 하락 (%)'),('first_fraction','1차 매도 비율 (0~1)'),
                 ('max_losses','연속 손절 제한 (회)'),('top_n','거래대금 상위 종목 수'),
                 ('poll_seconds','스캔 사이 대기 (초)')]
        for i,(key,label) in enumerate(specs):
            ttk.Label(settings_tab,text=label).grid(row=i,column=0,sticky='w',pady=6)
            var = tk.StringVar(value=str(self.config[key]))
            self.setting_vars[key] = var
            ttk.Entry(settings_tab,textvariable=var,width=20).grid(row=i,column=1,padx=25,pady=6)
        ttk.Button(settings_tab,text='설정 저장 · 중지 상태에서 적용',command=self.save_settings).grid(row=9,column=0,columnspan=2,pady=16)
        ttk.Label(settings_tab,text='최대보유는 종목 수 제한입니다. 손절 연속 횟수는 KST 자정에 초기화됩니다.\n'
                  '설정은 settings.json에 저장됩니다. 실거래 허용 상태는 저장하지 않습니다.\n'
                  '실거래는 모의 API 시험만 수행했으며 실제 체결·Python 3.11 환경 검증은 완료되지 않았습니다.\n'
                  '미확인 주문이 있으면 execution.sqlite3를 삭제하지 말고 업비트 주문내역을 먼저 대조하세요.',
                  foreground=MUTED).grid(row=10,column=0,columnspan=3,sticky='w',pady=10)

    def recolor(self, widget):
        if isinstance(widget, ttk.Label):
            widget.configure(foreground=TEXT)
        for child in widget.winfo_children():
            self.recolor(child)

    def replace_copy(self, widget):
        if isinstance(widget, ttk.Label):
            text = str(widget.cget('text'))
            if text.startswith('1회 150,000'):
                widget.configure(text='위험관리 제어판에서 설정 · 실제 체결 확인 후 반영',foreground=ACCENT)
            elif text.startswith('거래대금 상위 후보'):
                widget.configure(text='거래대금 상위 N종목 전체 표시 · 완료된 5분봉 기준 · 제외 종목도 순위에 표시')
            elif text.startswith('매수·매도 이벤트'):
                widget.configure(text='v1.1 기록 유지 · v1.2는 확인된 체결만 기록 · 구 기록 손익은 추정치')
        for child in widget.winfo_children():
            self.replace_copy(child)

    def load_state(self):
        old = dict(positions={},loss_streak=0,paused_for_day=False,last_reset_date=now_kst().date().isoformat())
        if (BASE/'state.json').exists():
            old.update(json.loads((BASE/'state.json').read_text(encoding='utf-8')))
        state = self.journal.load_state(old)
        self.positions = state['positions']
        self.loss_streak = int(state['loss_streak'])
        self.paused_for_day = bool(state['paused_for_day'])
        self.last_reset_date = state['last_reset_date']
        if self.journal.pending():
            self.fault = True
            self.safety_text = '미확인 주문: 실거래 잠금 · 수동 대조 필요'

    def state(self):
        return dict(positions=self.positions,loss_streak=self.loss_streak,
                    paused_for_day=self.paused_for_day,last_reset_date=self.last_reset_date)

    def save_state(self):
        self.journal.save_state(self.state())
        atomic_json(BASE/'state.json',self.state())

    def save_settings(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('설정','중지 후 감시 종료를 기다려 주세요.')
            return
        try:
            c = {k:float(v.get()) for k,v in self.setting_vars.items()}
            validate_settings(c)
            for k in ('max_positions','max_losses','top_n','poll_seconds'):
                c[k] = int(c[k])
            atomic_json(BASE/'settings.json',c)
            self.config = c
            self.log('위험관리 설정 저장 완료')
        except Exception as e:
            messagebox.showerror('설정 오류',str(e))

    def log(self, message):
        self.messages.put(('log',f"[{now_kst():%Y-%m-%d %H:%M:%S}] {message}"))

    def drain_log_queue(self):
        pass  # All Tk operations are performed by pump on the GUI thread.

    def pump(self):
        for _ in range(300):
            try:
                kind,payload = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.log_text.configure(state='normal')
                self.log_text.insert('end',payload+'\n')
                if int(self.log_text.index('end-1c').split('.')[0]) > 4000:
                    self.log_text.delete('1.0','1001.0')
                self.log_text.see('end')
                self.log_text.configure(state='disabled')
            elif kind == 'rows':
                self.update_candidate_view(payload)
            elif kind == 'history':
                self.refresh_history_views()
            elif kind == 'positions':
                self.render_positions(payload)
            elif kind == 'off':
                self.live_enabled.set(False)
                self.update_mode()
        self.krw_balance.set(self.balance_text)
        self.last_scan_var.set(self.last_scan)
        self.loss_streak_var.set(f"{self.loss_streak} / {self.config['max_losses']}")
        self.status.set(f"{self.scan_text} · 오류 {self.errors}회 · {self.safety_text}")
        self.root.after(250,self.pump)

    def on_live_toggle(self):
        if self.live_enabled.get():
            if self.running or self.fault or not self.ready:
                self.live_enabled.set(False)
                messagebox.showwarning('실거래 잠금','관찰 모드 시작으로 잔고 대조를 완료한 뒤 중지하고 활성화하세요.\n미확인 주문/잔고 불일치는 수동 확인이 필요합니다.')
            elif not messagebox.askyesno('실거래 확인','실제 자금으로 주문합니다. 실제 거래소 통합 검증은 미완료입니다.\n프로그램/통신 중단 시 손절 감시도 중단됩니다.\n실거래를 허용할까요?'):
                self.live_enabled.set(False)
        self.live_event.set() if self.live_enabled.get() else self.live_event.clear()
        self.update_mode()

    def update_mode(self):
        self.mode_var.set('실거래 허용 · 체결 확인' if self.live_enabled.get() else '관찰 모드 · 주문 OFF')

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        if self.live_event.is_set() and (not self.ready or self.fault):
            self.lock('실거래 시작 요건 미충족')
            return
        self.running = True
        self.stop_event.clear()
        self.worker = threading.Thread(target=self.trade_loop,daemon=True)
        self.worker.start()

    def stop(self):
        self.running = False
        self.stop_event.set()
        self.live_event.clear()
        self.live_enabled.set(False)
        self.update_mode()
        self.log('중지 요청: 이미 접수한 주문은 취소되지 않습니다. 체결 대조 종료까지 기다리세요.')

    def on_close(self):
        self.stop()
        if self.worker and self.worker.is_alive():
            self.scan_text = '종료 대기: 진행 중인 주문/조회 확인 중'
            self.root.after(250,self.on_close_wait)
        else:
            self.root.destroy()

    def on_close_wait(self):
        if self.worker and self.worker.is_alive():
            self.root.after(250,self.on_close_wait)
        else:
            self.root.destroy()

    def lock(self, reason):
        self.fault = True
        self.ready = False
        self.live_event.clear()
        self.safety_text = '주문 잠금: '+reason
        self.messages.put(('off',None))
        self.log(self.safety_text)

    def refresh_balance(self):
        if self.worker and self.worker.is_alive():
            self.log('감시 루프에서 잔고를 갱신합니다.')
            return
        self.worker = threading.Thread(target=self.sync_safe,daemon=True)
        self.worker.start()

    def sync_safe(self):
        try:
            self.sync()
            self.messages.put(('positions',copy.deepcopy(self.positions)))
        except Exception as e:
            self.errors += 1
            self.lock(str(e))

    def sync(self):
        if not self.upbit:
            self.safety_text = 'API 키 없음 · 공개 시세 관찰만 가능'
            self.ready = False
            return None
        if self.journal.pending():
            raise SafetyError('미확인 주문 존재: execution.sqlite3 및 업비트 내역 대조 필요')
        balances = balances_map(self.upbit.get_balances())
        if any(b['locked'] > 0 for b in balances.values()):
            raise SafetyError('잠긴 계좌 잔고: 외부 미체결 주문을 확인하세요')
        reconcile(self.positions,balances)
        self.balance_text = f"{balances['KRW']['free']:,.0f}원"
        self.ready = not self.fault
        self.safety_text = '잔고 대조 완료' if self.ready else '오류 잠금 유지 · 원인 확인 후 재시작'
        return balances

    def get_candidates(self):
        import requests
        response = requests.get('https://api.upbit.com/v1/ticker/all',
                                params={'quote_currencies':'KRW'},timeout=(4,10))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data,list) or not data:
            raise ValueError('거래대금 응답 오류')
        rows = sorted(data,key=lambda x:float(x['acc_trade_price_24h']),reverse=True)
        self.candidate_values = {r['market']:float(r['acc_trade_price_24h']) for r in rows[:self.config['top_n']]}
        for r in rows:
            self.prices[r['market']] = float(r['trade_price'])
        self.day_changes = {r['market']:float(r['signed_change_rate'])*100 for r in rows}
        return list(self.candidate_values)

    def entry_signal(self, market):
        df = pyupbit.get_ohlcv(market,interval='minute5',count=80)
        if df is None or len(df) < 55:
            raise ValueError('캔들 부족/조회 실패')
        latest = pd.Timestamp(df.index[-1])
        if latest.tzinfo is None:
            latest = latest.tz_localize('Asia/Seoul')
        age = (pd.Timestamp(now_kst())-latest).total_seconds()
        if age > 900 or age < -60:
            raise ValueError('오래된/미래 캔들')
        close = df.iloc[:-1]['close'].astype(float)
        sma20,sma50 = close.rolling(20).mean().iloc[-1],close.rolling(50).mean().iloc[-1]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi = 100.0 if loss == 0 and gain > 0 else 50.0 if loss == 0 else 100-100/(1+gain/loss)
        last,prev = float(close.iloc[-1]),float(close.iloc[-2])
        if not all(math.isfinite(v) for v in (sma20,sma50,rsi,last,prev)) or prev <= 0:
            raise ValueError('캔들 지표 오류')
        trend = last > sma20 > sma50
        reasons = []
        if not trend: reasons.append('SMA20/50 추세 미충족')
        if not 50 <= rsi <= 68: reasons.append('RSI 범위 50~68 이탈')
        if last/prev-1 >= 0.04: reasons.append('5분봉 급등 4% 이상')
        return not reasons,rsi,trend,'; '.join(reasons)

    def market_price(self,market):
        return self.prices.get(market)

    def trade_loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.check_midnight_reset()
                    self.sync()
                    self.scan_text = '거래대금 조회 중'
                    markets = self.get_candidates()
                    self.manage_positions()
                    rows = []
                    for rank,market in enumerate(markets,1):
                        rows.append((rank,market,self.prices.get(market),None,None,'스캔 대기'))
                    self.messages.put(('rows',list(rows)))
                    for idx,market in enumerate(markets):
                        if self.stop_event.is_set(): break
                        self.scan_text = f'스캔 {idx+1}/{len(markets)} · {market}'
                        try:
                            signal,rsi,trend,reason = self.entry_signal(market)
                            gates = []
                            if market in ('KRW-BTC','KRW-USDT','KRW-USDC','KRW-DAI'): gates.append('전략 제외 종목')
                            if market in self.positions: gates.append('이미 보유')
                            if len(self.positions) >= self.config['max_positions']: gates.append('최대 보유 도달')
                            if self.loss_streak >= self.config['max_losses'] or self.paused_for_day: gates.append('연속 손절 제한')
                            if time.time()-self.last_entry_time.get(market,0) < 900: gates.append('15분 재진입 대기')
                            if self.fault: gates.append('안전 잠금')
                            reason = '; '.join(filter(None,[reason]+gates))
                            passed = signal and not gates
                            rows[idx] = (idx+1,market,self.prices.get(market),rsi,trend,('통과' if passed else '제외')+' · '+(reason or '조건 충족'))
                            if passed:
                                self.buy(market)
                        except Exception as e:
                            self.errors += 1
                            rows[idx] = (idx+1,market,self.prices.get(market),None,None,'조회 오류: '+str(e))
                            self.log(f'{market}: {e}')
                        self.messages.put(('rows',list(rows)))
                        # Continue risk monitoring while a long candidate scan is in progress.
                        if idx % 5 == 4:
                            self.manage_positions()
                        if self.stop_event.wait(0.18): break
                    self.last_scan = now_kst().strftime('%H:%M:%S')
                    self.scan_text = '스캔 완료'
                    self.save_state()
                    self.messages.put(('positions',copy.deepcopy(self.positions)))
                    self.export_history()
                except Exception as e:
                    self.errors += 1
                    self.lock(str(e))
                # Position monitoring continues between scans.
                for _ in range(self.config['poll_seconds']):
                    if self.stop_event.wait(1): break
                    try:
                        self.manage_positions()
                    except Exception as e:
                        self.errors += 1
                        self.lock(str(e))
        finally:
            self.running = False
            self.scan_text = '중지됨'
            self.live_event.clear()
            self.messages.put(('off',None))

    def check_midnight_reset(self):
        today = now_kst().date().isoformat()
        if today != self.last_reset_date:
            self.loss_streak = 0
            self.paused_for_day = False
            self.last_reset_date = today
            self.save_state()

    def buy(self,market):
        self.last_entry_time[market] = time.time()
        if not self.live_event.is_set():
            self.log(f'[관찰] {market}: 매수 조건 통과 · 주문 없음')
            return
        self.execute(market,'bid',self.config['order_krw'],'시장가 매수')

    def execute(self,market,side,amount,reason):
        if self.stop_event.is_set() or not self.live_event.is_set() or self.fault:
            return False
        oid = None
        try:
            before = self.sync()
            if before is None or not self.ready: raise SafetyError('잔고 대조 미완료')
            currency = market.split('-')[1]
            holding = before.get(currency,{'free':0,'locked':0,'avg':0})
            if side == 'bid':
                if holding['free']+holding['locked'] > 0: raise SafetyError('수동 보유 종목은 자동 매수 금지')
                if before['KRW']['free'] < amount*1.01:
                    self.log('매수 생략: 수수료 여유 포함 원화 부족')
                    return False
            else:
                amount = sell_volume(min(amount,holding['free']))
                price = pyupbit.get_current_price(market)
                if not price or amount*float(price) < 5000:
                    self.log(f'{market}: 최소 주문액 미달/시세 없음 · 자동 매도 보류')
                    return False
            # Cancellation is checked immediately before the durable intent.
            if self.stop_event.is_set() or not self.live_event.is_set(): return False
            oid = self.journal.intent(market,side,amount,reason)
            response = self.upbit.buy_market_order(market,amount) if side == 'bid' else self.upbit.sell_market_order(market,amount)
            if not isinstance(response,dict) or not response.get('uuid'):
                raise SafetyError('주문 응답 불명확: 자동 재주문 금지')
            uid = response['uuid']
            self.journal.accepted(oid,uid)
            order = None
            for _ in range(20):
                order = self.upbit.get_individual_order(uid)
                if isinstance(order,dict) and order.get('state') in ('done','cancel'): break
                time.sleep(1)
            qty,funds,fee = filled_order(order,uid,market,side)
            expected = holding['free'] + (qty if side == 'bid' else -qty)
            if expected < -1e-8: raise SafetyError('체결 수량이 보유량 초과')
            after = None
            for _ in range(5):
                after = balances_map(self.upbit.get_balances())
                b = after.get(currency,{'free':0,'locked':0,'avg':0})
                expected_krw = before['KRW']['free'] + (funds-fee if side == 'ask' else -funds-fee)
                if b['locked'] == 0 and abs(b['free']-expected) <= max(1e-8,qty*1e-6) and abs(after['KRW']['free']-expected_krw) <= 1:
                    break
                time.sleep(1)
            else:
                raise SafetyError('체결 후 잔고/원화 변화 불일치')
            state = copy.deepcopy(self.state())
            event = None
            if qty > 0:
                price = funds/qty
                pnl,rate = 0,0
                if side == 'bid':
                    state['positions'][market] = dict(avg=price,qty=qty,initial_qty=qty,peak=price,
                        first_target_done=False,opened_at=now_kst().isoformat(),entry_uuid=uid,entry_fee_remaining=fee)
                else:
                    pos = state['positions'][market]
                    allocated_fee = pos.get('entry_fee_remaining',pos['avg']*pos['qty']*legacy.FEE_ESTIMATE)*qty/pos['qty']
                    pnl = funds-fee-pos['avg']*qty-allocated_fee
                    rate = pnl/(pos['avg']*qty+allocated_fee)*100
                    pos['entry_fee_remaining'] = max(0,pos.get('entry_fee_remaining',pos['avg']*pos['qty']*legacy.FEE_ESTIMATE)-allocated_fee)
                    pos['qty'] = max(0,expected)
                    if reason == '1차 익절':
                        pos['first_target_done'] = True
                        pos['peak'] = price
                    if pos['qty'] <= 1e-10:
                        del state['positions'][market]
                        if reason == '손절': state['loss_streak'] += 1
                        elif pnl > 0: state['loss_streak'] = 0
                        state['paused_for_day'] = state['loss_streak'] >= self.config['max_losses']
                event = dict(uuid=uid,time=now_kst().strftime('%Y-%m-%d %H:%M:%S'),side='매수' if side=='bid' else '매도',
                             market=market,price=price,qty=qty,amount=funds,realized_pnl_est=pnl,return_pct_est=rate,reason=reason)
            reconcile(state['positions'],after)
            self.journal.settle(oid,uid,state,event,order)
            self.positions = state['positions']
            self.loss_streak = state['loss_streak']
            self.paused_for_day = state['paused_for_day']
            atomic_json(BASE/'state.json',state)
            self.log(f'{market}: 종결 체결 확인 · 수량 {qty:.8f} · {reason}')
            self.export_history()
            self.messages.put(('positions',copy.deepcopy(self.positions)))
            return qty > 0
        except Exception as e:
            self.errors += 1
            self.lock(f'{market}: {e}')
            return False

    def manage_positions(self):
        for market,pos in list(self.positions.items()):
            if self.stop_event.is_set(): break
            price = pyupbit.get_current_price(market)
            if not price or not math.isfinite(float(price)) or float(price) <= 0:
                raise SafetyError(f'{market}: 보유종목 시세 조회 실패')
            price = float(price)
            self.prices[market] = price
            pos['peak'] = max(pos.get('peak',pos['avg']),price)
            pct = (price/pos['avg']-1)*100
            reason,qty = None,pos['qty']
            if pct <= -self.config['stop_pct']: reason = '손절'
            elif not pos.get('first_target_done') and pct >= self.config['target_pct']:
                reason,qty = '1차 익절',qty*self.config['first_fraction']
            elif pos.get('first_target_done') and price <= pos['peak']*(1-self.config['trailing_pct']/100): reason = '트레일링'
            if reason:
                if self.live_event.is_set(): self.execute(market,'ask',qty,reason)
                elif time.time()-getattr(self,'last_notice',{}).get(market,0) > 60:
                    self.log(f'[관찰] {market}: {reason} 조건 · 실제 매도 없음')
                    if not hasattr(self,'last_notice'): self.last_notice = {}
                    self.last_notice[market] = time.time()
        if self.positions: self.save_state()

    def refresh_tables(self):
        self.render_positions(copy.deepcopy(self.positions))

    def render_positions(self,positions):
        self.position_tree.delete(*self.position_tree.get_children())
        for market,pos in positions.items():
            price = self.prices.get(market)
            pnl = (price/pos['avg']-1)*100 if price and pos['avg'] else None
            self.position_tree.insert('','end',values=(market,fmt_num(pos['avg'],4),fmt_num(price,4),
                f'{pnl:+.2f}%' if pnl is not None else '-',fmt_num(pos['qty'],8),
                '완료' if pos.get('first_target_done') else '대기',fmt_num(pos.get('peak'),4)))

    def update_candidate_view(self,rows):
        self.candidate_tree.delete(*self.candidate_tree.get_children())
        for rank,market,price,rsi,trend,reason in rows:
            self.candidate_tree.insert('','end',values=(rank,market,fmt_num(self.candidate_values.get(market),0),
                fmt_num(price,4),fmt_num(rsi,1),'-' if trend is None else '상승' if trend else '미충족',
                '통과' if reason.startswith('통과') else '대기' if reason=='스캔 대기' else '제외',reason))

    def export_history(self):
        # Retain v1.1 rows and rebuild v1.2 rows from the transactional journal.
        path = BASE/'transactions.csv'
        rows = []
        if path.exists():
            with path.open(encoding='utf-8-sig',newline='') as f:
                rows = [r for r in csv.DictReader(f) if not r.get('uuid')]
        rows += self.journal.events()
        fields = ['time','side','market','price','qty','amount','realized_pnl_est','return_pct_est','reason','uuid']
        self.write_csv(path,fields,rows)
        daily_path = BASE/'daily_pnl.csv'
        old = []
        if daily_path.exists():
            with daily_path.open(encoding='utf-8-sig',newline='') as f: old = list(csv.DictReader(f))
        dates = {e['time'][:10] for e in self.journal.events() if e['side']=='매도'}
        daily = [r for r in old if r['date'] not in dates]
        for date in sorted(dates):
            sells = [r for r in rows if r['side']=='매도' and r['time'].startswith(date)]
            previous = next((r for r in old if r['date']==date),{})
            daily.append(dict(date=date,realized_pnl=sum(float(r['realized_pnl_est']) for r in sells),
                              return_pct=previous.get('return_pct',''),closing_assets=previous.get('closing_assets',''),
                              trade_count=len(sells),win_rate_pct=sum(float(r['realized_pnl_est'])>0 for r in sells)/len(sells)*100))
        self.write_csv(daily_path,['date','realized_pnl','return_pct','closing_assets','trade_count','win_rate_pct'],sorted(daily,key=lambda r:r['date']))
        self.messages.put(('history',None))

    @staticmethod
    def write_csv(path,fields,rows):
        temp = Path(str(path)+'.tmp')
        with temp.open('w',encoding='utf-8-sig',newline='') as f:
            writer = csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,path)


if __name__ == '__main__':
    raise SystemExit('v1.7은 start.bat 또는 validation_app.py로 실행하세요. 이 구버전 진입점은 잠겨 있습니다.')
    # Windows releases the file lock automatically after a crash.
    import msvcrt
    lockfile = open(BASE/'.instance.lock','a+b')
    lockfile.seek(0)
    if lockfile.read(1) == b'': lockfile.write(b'0'); lockfile.flush()
    lockfile.seek(0)
    try:
        msvcrt.locking(lockfile.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        raise SystemExit('이미 실행 중입니다. 중복 실행을 종료하세요.')
    root = tk.Tk()
    try:
        app = UpbitAutoTrader(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror('시작 실패',str(e))
        raise
