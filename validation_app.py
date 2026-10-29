"""v1.8 validation release: public market data, persisted paper trading, no real orders."""
import copy
import math
import csv
import io
import json
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import dashboard
import main
from main import pyupbit,pd,now_kst,fmt_num
from paper import Records,Paper
from trade_history import read_history,write_history,CATEGORIES,category
from daily_profit import daily_results,write_daily
from activity import activity_state
from market_guard import MarketGuard,POLICY,shock_reason,candle_time
from risk_records import RiskBook,benchmark
from tray_icon import TrayIcon
from network_guard import NetworkGuard
from market_data import MarketData,MarketDataError,CandleHistoryError


def stamp(): return now_kst().isoformat(timespec='seconds')


class ValidationApp(dashboard.Dashboard):
    def __init__(self,root):
        self.records=Records(main.BASE/'validation.sqlite3')
        with self.records.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS network_events(id INTEGER PRIMARY KEY,stamp TEXT,kind TEXT,payload TEXT);'
                'CREATE TABLE IF NOT EXISTS health_checks(id INTEGER PRIMARY KEY,stamp TEXT,payload TEXT);')
        self.market=MarketData()
        self.network=NetworkGuard(self.network_event)
        self.last_health_record=0
        self.quote_received={}
        self.run_id=stamp()
        self.paper=Paper(self.records)
        self.risk=RiskBook(self.records)
        self.regime=MarketGuard()
        self.reference=benchmark(self.records,main.BASE/'benchmark_v18.sqlite3',stamp(),self.paper.state)
        self.last_risk_mark=None
        self.tray=None
        self.exiting=False
        self.current_scan=None
        self.last_equity=0
        self.record_error=False
        super().__init__(root)
        root.title('UPBIT AUTO TRADING v1.8 · 가상매매 / 기록 검증 전용')
        self.live_enabled.set(False); self.live_event.clear()
        self.mode_var.set('가상매매 · 실거래 잠금')
        self.balance_text=f"가상 {self.paper.state['cash']:,.0f}원"
        self.safety_text='가상 검증 전용 · 실제 주문 없음'
        self.render_positions(copy.deepcopy(self.paper.state['positions']))
        self.records.log(stamp(),'session','v1.8 실행 · 가상 잔고/보유 복구')
        self.network_event('validation_segment',dict(version='1.8',run_id=self.run_id,
            settings={k:self.config[k] for k in main.DEFAULTS},risk_policy=POLICY,note='기존 잔고/기록 유지, 새 통신 검증 구간'))
        self.sync_trade_csv()
        self.refresh_ledger()
        self.tray=TrayIcon(main.BASE/'bitcoin.ico')
        self.tray.start()
        try: root.iconbitmap(str(main.BASE/'bitcoin.ico'))
        except tk.TclError: pass

    def build_ui(self):
        super().build_ui()
        self.disable_live(self.root)
        page=tk.Frame(self.tabs,bg=dashboard.BG)
        self.tabs.add(page,text='가상매매 / 기록')
        button=tk.Button(self.nav_buttons[0].master,text='▣   가상 기록',command=lambda:self.navigate(7),
            bg='#09213f',fg=dashboard.TEXT,relief='flat',anchor='w',font=('맑은 고딕',12,'bold'),padx=20,pady=15)
        button.pack(fill='x',padx=8,pady=3); self.nav_buttons.append(button)
        self.paper_summary=tk.Label(page,bg=dashboard.BG,fg=dashboard.CYAN,font=('맑은 고딕',12,'bold'),justify='left')
        self.paper_summary.pack(fill='x',padx=18,pady=14)
        ttk.Button(page,text='검토용 기록 ZIP 내보내기',command=self.export_records).pack(anchor='w',padx=18,pady=8)
        tk.Label(page,text='가상 초기자금 1,000,000원 · 편도 수수료 0.05% · 편도 불리한 슬리피지 0.05%\n'
            '가상 체결은 즉시 전량 체결 가정입니다. 실제 유동성/부분체결/통신 지연을 재현하지 않습니다.\n'
            '실제 계좌의 코인은 이 버전에서 손절·익절 감시하지 않습니다. 실거래 활성화는 잠겨 있습니다.\n'
            'validation.sqlite3에 스캔·지표·완료 캔들·시세·가상 거래·손익·로그가 누적 저장됩니다.',
            bg=dashboard.BG,fg=dashboard.MUTED,font=('맑은 고딕',10),justify='left').pack(anchor='w',padx=18,pady=10)
        self.paper_tree=self.table(page,[(k,t,w) for k,t,w in [('stamp','일시',170),('side','구분',60),('market','종목',95),('price','가상 체결가',100),('qty','수량',100),('fee','수수료',85),('pnl','실현손익',100),('reason','사유',100)]])
        self.tabs.tab(2,text='가상 보유 종목')
        self.tabs.tab(3,text='기존 실거래 내역')
        self.tabs.tab(4,text='기존 실거래 손익')
        self.nav_buttons[2].configure(text='◕   가상 보유')
        self.nav_buttons[3].configure(text='▤   기존 거래')
        self.nav_buttons[4].configure(text='▥   기존 손익')
        self.build_ledger()
        self.setup_daily_profit()
        self.build_activity_signal()
        self.network_label=tk.Label(self.tabs.master,bg=dashboard.BG,fg=dashboard.RED,anchor='w',wraplength=1100,
            text='통신 확인 전 · 신규 가상매수 잠금')
        self.network_label.pack(before=self.tabs,fill='x',padx=4,pady=4)
        self.market_label=tk.Label(self.tabs.master,bg=dashboard.BG,fg=dashboard.CYAN,anchor='w',wraplength=1100,
            text='시장 판단 전 · 신규 진입 잠금')
        self.market_label.pack(before=self.tabs,fill='x',padx=4,pady=4)

    def network_event(self,kind,payload):
        with self.records.db() as db:
            db.execute('INSERT INTO network_events(stamp,kind,payload) VALUES(?,?,?)',
                (stamp(),kind,json.dumps(payload,ensure_ascii=False,allow_nan=False)))

    def network_failure(self,scope,error):
        self.errors+=1
        self.network.fail(scope,error)
        self.regime.invalidate('통신 확인 필요 · 시장 재판정 대기')
        self.scan_text='통신 장애 · 신규 가상매수 잠금'

    def get_candidates(self):
        rows=self.market.universe()
        ranked=sorted(rows,key=lambda r:float(r['acc_trade_price_24h']),reverse=True)
        self.candidate_values={r['market']:float(r['acc_trade_price_24h']) for r in ranked[:self.config['top_n']]}
        self.day_changes={r['market']:float(r['signed_change_rate'])*100 for r in ranked}
        # Validate the liquid BTC reference, not every inactive market's last trade.
        reference=next((r for r in rows if r.get('market')=='KRW-BTC'),None)
        if reference is None: raise MarketDataError('BTC 기준 시세 누락')
        self.market.validate_quote(reference)
        self.universe_rows={r['market']:r for r in rows}
        for market in self.candidate_values:
            try: self.prices[market]=self.market.validate_quote(self.universe_rows[market])
            except MarketDataError: self.prices.pop(market,None)
        return list(self.candidate_values)

    def build_activity_signal(self):
        frame=tk.Frame(self.clock.master,bg='#051b34')
        frame.pack(side='right',padx=12)
        self.activity_canvas=tk.Canvas(frame,width=80,height=40,bg='#051b34',highlightthickness=0)
        self.activity_canvas.pack(side='left')
        self.activity_lights={}
        for x,key,label in [(13,'green','실행'),(40,'yellow','검색'),(67,'red','중지')]:
            self.activity_lights[key]=self.activity_canvas.create_oval(x-7,3,x+7,17,fill='#20344c',outline='#44617d')
            self.activity_canvas.create_text(x,30,text=label,fill=dashboard.MUTED,font=('맑은 고딕',8))
        self.activity_label=tk.Label(frame,text='중지됨',bg='#051b34',fg=dashboard.RED,font=('맑은 고딕',10,'bold'))
        self.activity_label.pack(side='left',padx=6)
        self.update_activity_signal()

    def update_activity_signal(self):
        alive=bool(self.worker and self.worker.is_alive())
        active,label=activity_state(self.running,alive,self.scan_text,self.record_error)
        if self.running and not self.record_error:
            health=self.network.snapshot()
            if health['state'] in ('offline','stale'): active,label='red','통신 장애 · 매수 잠금'
            elif health['state']!='healthy': active,label='yellow','통신 복구 확인 중'
        colors={'green':'#00dd9b','yellow':'#ffca3b','red':'#ff4b73'}
        for key,item in self.activity_lights.items():
            color=colors[key] if key==active else '#20344c'
            if key==active=='yellow' and int(time.monotonic()*2)%2: color='#997818'
            self.activity_canvas.itemconfigure(item,fill=color)
        self.activity_label.configure(text=label,fg=colors[active])

    def setup_daily_profit(self):
        self.daily_ready=True
        self.tabs.tab(4,text='가상 손익 · 일자별')
        self.nav_buttons[4].configure(text='▥   가상 손익')
        columns=[('date','일자 (KST)',105),('buys','매수',65),('sells','매도',65),
            ('stops','손절',65),('targets','1차 익절',80),('trailing','트레일링',85),
            ('fees','발생 수수료',110),('pnl','실현손익',120),('win','매도 승률',95),('equity','최종 조회 자산',130)]
        self.daily_tree.configure(columns=[c[0] for c in columns])
        for key,label,width in columns:
            self.daily_tree.heading(key,text=label); self.daily_tree.column(key,width=width,anchor='center')
        note=tk.Label(self.daily_tree.master.master,bg=dashboard.BG,fg=dashboard.MUTED,justify='left',anchor='w',
            text='가상 거래 DB 기준 · 매수만 있는 날도 표시 · 실현손익에는 배분한 매수/매도 수수료가 이미 반영됩니다.\n'
                 '승률은 부분매도를 포함한 매도 건수 기준입니다. 최종 조회 자산은 해당 날짜의 마지막 스냅샷이며 확정 마감자산이 아닙니다.')
        note.pack(fill='x',padx=10,pady=8)
        self.refresh_profit_view()

    def refresh_profit_view(self):
        if not getattr(self,'daily_ready',False):
            return super().refresh_profit_view()
        rows=daily_results(self.records)
        years=sorted({r['date'][:4] for r in rows},reverse=True)
        self.year_combo['values']=['전체']+years
        self.month_combo['values']=['전체']+[f'{i:02d}' for i in range(1,13)]
        self.day_combo['values']=['전체']+[f'{i:02d}' for i in range(1,32)]
        selected=[]
        for r in rows:
            date=r['date']
            if self.year_filter.get()!='전체' and date[:4]!=self.year_filter.get(): continue
            if self.month_filter.get()!='전체' and date[5:7]!=self.month_filter.get(): continue
            if self.day_filter.get()!='전체' and date[8:10]!=self.day_filter.get(): continue
            selected.append(r)
        self.daily_tree.delete(*self.daily_tree.get_children())
        for r in reversed(selected):
            self.daily_tree.insert('','end',iid=r['date'],values=(r['date'],r['buys'],r['sells'],r['stops'],r['targets'],r['trailing'],
                fmt_num(r['fees'],2),fmt_num(r['realized_pnl'],2),'—' if r['sell_win_rate_pct'] is None else f"{r['sell_win_rate_pct']:.1f}%",
                '조회 없음' if r['last_equity'] is None else fmt_num(r['last_equity'],2)))
        self.pnl_summary_label.configure(text=f"가상 실현손익 {sum(r['realized_pnl'] for r in selected):+,.2f}원  |  "
            f"매수 {sum(r['buys'] for r in selected)}건 · 매도 {sum(r['sells'] for r in selected)}건  |  "
            f"발생 수수료 {sum(r['fees'] for r in selected):,.2f}원")

    def build_ledger(self):
        page=self.trade_tree.master.master
        self.old_trade_wrap=self.trade_tree.master
        self.old_trade_wrap.pack_forget()
        self.tabs.tab(3,text='거래 내역')
        self.nav_buttons[3].configure(text='▤   거래 내역')
        head=tk.Frame(page,bg=dashboard.BG); head.pack(fill='x',padx=12,pady=8)
        tk.Label(head,text='가상 매수 · 매도 · 손절 · 익절 기록',bg=dashboard.BG,fg=dashboard.CYAN,
                 font=('맑은 고딕',13,'bold')).pack(side='left')
        ttk.Button(head,text='기존 실거래 기록 보기 / 숨기기',command=self.toggle_legacy_history).pack(side='right')
        controls=tk.Frame(page,bg=dashboard.BG); controls.pack(fill='x',padx=12,pady=6)
        self.history_filter=tk.StringVar(value='전체')
        select=ttk.Combobox(controls,textvariable=self.history_filter,values=CATEGORIES,state='readonly',width=13)
        select.pack(side='left',padx=(0,8)); select.bind('<<ComboboxSelected>>',lambda _:self.refresh_ledger())
        self.history_market=tk.StringVar()
        ttk.Label(controls,text='종목').pack(side='left')
        ttk.Entry(controls,textvariable=self.history_market,width=12).pack(side='left',padx=6)
        self.history_from=tk.StringVar(); self.history_to=tk.StringVar()
        for label,var in [('시작일',self.history_from),('종료일',self.history_to)]:
            ttk.Label(controls,text=label).pack(side='left',padx=5)
            ttk.Entry(controls,textvariable=var,width=11).pack(side='left')
        ttk.Button(controls,text='조회',command=self.refresh_ledger).pack(side='left',padx=8)
        ttk.Button(controls,text='전체 보기',command=self.reset_ledger).pack(side='left')
        self.ledger_summary=tk.Label(page,bg=dashboard.BG,fg=dashboard.TEXT,anchor='w',justify='left')
        self.ledger_summary.pack(fill='x',padx=12,pady=8)
        self.ledger_empty=tk.Label(page,bg=dashboard.BG,fg=dashboard.MUTED,anchor='w',justify='left',
            text='발생한 가상 거래만 표시합니다. 신호가 없으면 기록도 없습니다. 날짜는 YYYY-MM-DD 형식입니다.\n'
                 'paper_trades.csv 자동 저장 · 트레일링은 손실 종료일 수도 있으며, 익절 전체는 실현손익이 양수인 매도입니다.')
        self.ledger_empty.pack(fill='x',padx=12,pady=4)
        self.ledger_tree=self.table(page,[(k,t,w) for k,t,w in [('id','번호',50),('stamp','일시 (KST)',180),
            ('category','거래 유형',100),('market','종목',95),('price','가상 체결가',115),('qty','수량',110),
            ('funds','금액',100),('fee','수수료',85),('pnl','실현손익',100),('reason','사유',150)]])
        self.ledger_tree.tag_configure('buy',foreground=dashboard.CYAN)
        self.ledger_tree.tag_configure('stop',foreground=dashboard.RED)
        self.ledger_tree.tag_configure('sell',foreground=dashboard.GREEN)

    def toggle_legacy_history(self):
        if self.old_trade_wrap.winfo_manager(): self.old_trade_wrap.pack_forget()
        else: self.old_trade_wrap.pack(fill='both',expand=True)

    def reset_ledger(self):
        self.history_filter.set('전체'); self.history_market.set(''); self.history_from.set(''); self.history_to.set('')
        self.refresh_ledger()

    def refresh_ledger(self):
        from datetime import date
        start,end=self.history_from.get().strip(),self.history_to.get().strip()
        try:
            for value in (start,end):
                if value and (date.fromisoformat(value).isoformat()!=value): raise ValueError('날짜 형식')
            if start and end and start>end: raise ValueError('시작일이 종료일보다 늦습니다')
        except ValueError:
            messagebox.showerror('날짜 확인','날짜는 YYYY-MM-DD로 입력하고 시작일을 종료일 이전으로 지정하세요.'); return
        rows,s=read_history(self.records,self.history_filter.get(),self.history_market.get(),start,end)
        self.ledger_tree.delete(*self.ledger_tree.get_children())
        for e in rows:
            self.ledger_tree.insert('','end',iid=str(e['record_id']),values=(e['record_id'],e['stamp'],e['category'],e['market'],
                fmt_num(e['price'],4),fmt_num(e['qty'],8),fmt_num(e['funds'],2),fmt_num(e['fee'],2),
                '—' if e['side']=='BUY' else fmt_num(e['pnl'],2),e['reason']),
                tags=('buy',) if e['side']=='BUY' else ('stop',) if e['category']=='손절' else ('sell',))
        self.ledger_summary.configure(text=f"조회 {s['count']}건 · 매수 {s['buys']} · 매도 {s['sells']} · 손절 {s['stops']} · 1차 익절 {s['targets']} · 트레일링 {s['trailing']}\n"
            f"수수료 {s['fees']:,.2f}원 · 실현손익 {s['pnl']:+,.2f}원 · 최근 {len(rows)}건 표시 / CSV에는 전체 저장")

    def sync_trade_csv(self):
        try:
            write_history(self.records,main.BASE/'paper_trades.csv')
            write_daily(self.records,main.BASE/'paper_daily.csv')
            self.csv_error=False
        except Exception as e:
            self.csv_error=True; self.record_error=True
            if hasattr(self,'stop_event'): self.stop_event.set()
            self.log(f'거래 CSV 저장 실패: {e} · DB 기록은 보존됩니다. CSV를 열어두었다면 닫고 재시작하세요.')

    def disable_live(self,widget):
        if isinstance(widget,ttk.Checkbutton):
            widget.configure(text='실거래 잠금 · 가상검증 전용',state='disabled')
        for child in widget.winfo_children(): self.disable_live(child)

    def on_live_toggle(self):
        self.live_enabled.set(False); self.live_event.clear()
        messagebox.showinfo('실거래 잠금','v1.8은 가상 검증 전용입니다. 실제 주문을 보내지 않습니다.')

    def execute(self,*args,**kwargs):
        raise RuntimeError('v1.8은 실제 주문을 허용하지 않습니다')

    def update_mode(self):
        self.mode_var.set('가상매매 · 실거래 잠금')

    def refresh_balance(self):
        self.balance_text=f"가상 {self.paper.state['cash']:,.0f}원"
        self.log('가상 가용 원화를 갱신했습니다. 실제 계좌 조회는 수행하지 않습니다.')

    def log(self,message):
        # Failure to persist validation data stops paper actions instead of silently dropping logs.
        try: self.records.log(stamp(),'error' if any(s in message for s in ('오류','실패')) else 'info',str(message))
        except Exception:
            self.record_error=True
            if hasattr(self,'stop_event'): self.stop_event.set()
        super().log(message)

    def start(self):
        if self.worker and self.worker.is_alive(): return
        if self.record_error:
            messagebox.showerror('기록 저장 실패','디스크/기록 DB를 확인하고 재시작하세요. 기록 없이 검증을 진행하지 않습니다.')
            return
        self.network=NetworkGuard(self.network_event)
        self.regime=MarketGuard()
        self.run_id=stamp()
        self.network_event('validation_segment',dict(version='1.8',run_id=self.run_id,
            settings={k:self.config[k] for k in main.DEFAULTS},risk_policy=POLICY,note='시작 버튼 · 새 통신 확인 구간'))
        self.live_event.clear()
        super().start()
        self.update_activity_signal()

    def stop(self):
        super().stop()
        if hasattr(self,'activity_canvas'): self.update_activity_signal()

    def buy(self,market,inputs=None,received=None):
        decision=dict(scan_id=self.current_scan,policy=POLICY,signal=inputs or {},
                      market_state=self.regime.snapshot(),daily=dict(self.risk.daily),executed=False)
        def blocked(reason):
            self.last_entry_reason=reason
            decision.update(reason=reason,applied_order_krw=0.)
            self.risk.record('entry_decisions',stamp(),decision,market=market)
            return None
        if self.stop_event.is_set() or self.record_error: return blocked('중지/기록 오류')
        if not self.network.can_enter(): return blocked('통신 확인/복구 중 · 신규 가상매수 잠금')
        if not inputs or received is None or not 0<=time.monotonic()-received<=POLICY['max_sample_age']:
            return blocked('매수 신호 수신 지연/누락')
        if not inputs.get('strategy_pass'): return blocked('개별 진입 신호 미충족')
        if not 300<=now_kst().timestamp()-candle_time(inputs['candle_stamp'])<=POLICY['max_candle_age']:
            return blocked('완료 캔들 시각 만료')
        self.manage_positions()
        if not self.risk.daily['entry_allowed']: return blocked(self.risk.daily['reason'])
        config,reason=self.regime.entry_config(self.config,len(self.paper.state['positions']))
        if reason: return blocked(reason)
        try:
            quote=self.market.quotes([market])[market]
            self.prices[market]=quote; self.quote_received[market]=time.monotonic()
        except MarketDataError as e:
            self.network_failure('매수 직전 시세',e); return blocked(str(e))
        reason=shock_reason(inputs,quote)
        if reason: return blocked(reason)
        if self.stop_event.is_set() or not self.network.can_enter(): return blocked('중지/통신 잠금')
        if time.monotonic()-received>POLICY['max_sample_age']: return blocked('매수 직전 신호 만료')
        config,reason=self.regime.entry_config(self.config,len(self.paper.state['positions']))
        if reason: return blocked(reason)
        reason=self.paper.gate(market,config,stamp())
        if reason: return blocked(reason)
        decision.update(reason='진입 허용',applied_order_krw=config['order_krw'],quote=quote,
                        market_state=self.regime.snapshot(),daily=dict(self.risk.daily))
        self.risk.record('entry_decisions',stamp(),decision,market=market)
        event=self.paper.buy(market,quote,config,stamp())
        if event:
            self.last_entry_reason='가상매수 완료'
            self.risk.record('entry_decisions',stamp(),dict(decision,executed=True,trade_stamp=event['stamp']),market=market)
            self.sync_trade_csv()
            self.log(f"[가상매수] {market} · 적용금액 {event['funds']:,.0f}원 · {self.regime.snapshot()['state']}")
        return event

    def reference_buy(self,market,inputs,received):
        if not inputs.get('legacy_pass') or not self.network.can_enter() or self.stop_event.is_set(): return
        if time.monotonic()-received>POLICY['max_sample_age']: return
        if self.reference.gate(market,self.config,stamp()): return
        try: quote=self.market.quotes([market])[market]
        except MarketDataError as e:
            self.network_failure('비교 시세',e); return
        self.reference.buy(market,quote,self.config,stamp())

    def entry_signal(self,market):
        df=self.market.candles(market,count=80)
        if len(df)<55: raise CandleHistoryError('완료 캔들 수 부족 · 해당 종목 진입 제외')
        latest=pd.Timestamp(df.index[-1])
        if latest.tzinfo is None: latest=latest.tz_localize('Asia/Seoul')
        age=(pd.Timestamp(now_kst())-latest).total_seconds()
        if age>900 or age < -60: raise CandleHistoryError('오래된/미래 캔들 · 해당 종목 진입 제외')
        closed=df.iloc[:-1].copy()
        if not closed[['open','high','low','close','volume']].map(lambda x:pd.notna(x) and float(x)>=0 and float(x)<float('inf')).all().all():
            raise ValueError('비정상 캔들 수치')
        close=closed['close'].astype(float)
        sma20=float(close.rolling(20).mean().iloc[-1]); sma50=float(close.rolling(50).mean().iloc[-1])
        delta=close.diff(); gain=float(delta.clip(lower=0).rolling(14).mean().iloc[-1]); loss=float((-delta.clip(upper=0)).rolling(14).mean().iloc[-1])
        rsi=100. if loss==0 and gain>0 else 50. if loss==0 else 100-100/(1+gain/loss)
        last,previous=float(close.iloc[-1]),float(close.iloc[-2])
        if previous<=0 or last<=0: raise ValueError('0 이하 종가')
        trend=last>sma20>sma50; move=last/previous-1
        reasons=[]
        if not trend: reasons.append('SMA20/50 추세 미충족')
        if not 50<=rsi<=68: reasons.append('RSI 범위 50~68 이탈')
        if move>=.04: reasons.append('5분봉 급등 4% 이상')
        legacy_pass=not reasons
        shock_inputs=dict(candle_move=move,candle_high=float(closed['high'].iloc[-1]),
                          candle_low=float(closed['low'].iloc[-1]),previous_close=previous,closed_price=last)
        shock=shock_reason(shock_inputs)
        if shock: reasons.append(shock)
        candles=[]
        for index,row in closed.iterrows():
            candles.append(dict(stamp=str(index),**{k:float(row[k]) for k in ('open','high','low','close','volume')}))
        self.records.candles(market,candles)
        details=dict(rsi=rsi,sma20=sma20,sma50=sma50,closed_price=last,previous_close=previous,
            candle_move=move,trend=trend,candle_stamp=str(closed.index[-1]),candle_age_seconds=age,
            strategy_pass=not reasons,strategy_reason='; '.join(reasons),legacy_pass=legacy_pass,
            candle_high=shock_inputs['candle_high'],candle_low=shock_inputs['candle_low'])
        return not reasons,rsi,trend,'; '.join(reasons),details

    def manage_positions(self):
        quotes={}
        complete=True
        if self.stop_event.is_set(): return False
        primary=set(self.paper.state['positions'])
        markets=sorted(primary|set(self.reference.state['positions']))
        try:
            quotes,errors=self.market.holding_quotes(markets)
            if primary-set(quotes):
                complete=False; self.network_failure('보유 시세', '; '.join(errors))
        except MarketDataError as e:
            complete=False; self.network_failure('보유 시세',e)
        for market,price in quotes.items():
            self.prices[market]=price; self.quote_received[market]=time.monotonic()
        # Hide missing prices rather than continuing to display a cached portfolio quote.
        for market in set(markets)-set(quotes): self.prices.pop(market,None)
        events=self.paper.monitor(quotes,self.config,stamp())
        self.reference.monitor(quotes,self.config,stamp())
        self.risk.mark_equity(stamp(),self.paper.state,quotes)
        def value(state):
            return None if any(m not in quotes for m in state['positions']) else state['cash']+sum(p['qty']*quotes[m] for m,p in state['positions'].items())
        self.comparison=(value(self.paper.state),value(self.reference.state))
        self.last_risk_mark=time.monotonic()
        if events: self.sync_trade_csv()
        for event in events:
            self.log(f"[가상매도] {event['market']} {event['reason']} · 손익 {event['pnl']:+.2f}원")
        if time.monotonic()-self.last_equity>=15:
            self.records.snapshot(stamp(),self.paper.state,quotes)
            self.reference.records.snapshot(stamp(),self.reference.state,quotes)
            self.last_equity=time.monotonic()
        self.balance_text=f"가상 {self.paper.state['cash']:,.0f}원"
        self.messages.put(('positions',copy.deepcopy(self.paper.state['positions'])))
        if time.monotonic()-self.last_health_record>=15:
            with self.records.db() as db:
                db.execute('INSERT INTO health_checks(stamp,payload) VALUES(?,?)',
                    (stamp(),json.dumps(self.network.snapshot(),ensure_ascii=False,allow_nan=False)))
            self.last_health_record=time.monotonic()
        return complete

    def trade_loop(self):
        try:
            while not self.stop_event.is_set():
                scan=None
                try:
                    if not self.manage_positions(): raise MarketDataError('보유 시세 확인 실패')
                    scan=self.records.start_scan(stamp(),dict({k:self.config[k] for k in main.DEFAULTS},
                        version='1.8',run_id=self.run_id,risk_policy=POLICY))
                    self.current_scan=scan; self.scan_text='시장 판단을 위한 전체 후보 조회 중'
                    markets=self.get_candidates(); self.network.confirm_cycle()
                    staged=[]; samples={}
                    # Complete the market sample BEFORE considering the first new entry.
                    for i,market in enumerate(markets):
                        if self.stop_event.is_set(): break
                        details=dict(rank=i+1,trade_value_24h=self.candidate_values.get(market),quote=self.prices.get(market))
                        try:
                            signal,rsi,trend,reason,inputs=self.entry_signal(market)
                            received=time.monotonic(); details.update(inputs)
                            samples[market]=(inputs,received)
                            staged.append((market,signal,rsi,trend,reason,inputs,received,details))
                        except (MarketDataError,CandleHistoryError,ValueError) as e:
                            self.errors+=1; details.update(passed=False,error=str(e),reason='조회/처리 오류')
                            if isinstance(e,MarketDataError): self.network_failure('후보 조회',e)
                            self.records.observation(scan,market,stamp(),details)
                        if i%5==4: self.manage_positions()
                        if self.network.snapshot()['state'] in ('offline','stale'): break
                        if self.stop_event.wait(.2): break
                    if self.stop_event.is_set() or self.network.snapshot()['state'] in ('offline','stale'):
                        self.regime.invalidate('스캔 중단/통신 오류 · 신규 진입 잠금')
                    else:
                        self.regime.assess(samples,markets,now_kst().timestamp())
                    assessment=dict(self.regime.snapshot(),policy=POLICY,run_id=self.run_id,
                                    assessed_at=stamp(),settings={k:self.config[k] for k in main.DEFAULTS})
                    self.risk.record('market_checks',stamp(),assessment,scan=scan)
                    rows=[]
                    for i,(market,signal,rsi,trend,reason,inputs,received,details) in enumerate(staged):
                        if self.stop_event.is_set(): break
                        self.reference_buy(market,inputs,received)
                        config,gate=self.regime.entry_config(self.config,len(self.paper.state['positions']))
                        if not self.network.can_enter(): gate='통신 확인/복구 중 · 신규 가상매수 잠금'
                        elif not self.risk.daily['entry_allowed']: gate=self.risk.daily['reason']
                        elif not gate: gate=self.paper.gate(market,config,stamp())
                        passed=signal and not gate
                        details.update(passed=passed,gate=gate,reason='; '.join(filter(None,[reason,gate])) or '조건 충족',
                                       market_state=self.regime.snapshot(),applied_order_krw=config['order_krw'] if config and passed else 0.)
                        self.records.observation(scan,market,stamp(),details)
                        if passed:
                            event=self.buy(market,inputs,received)
                            details['executed']=bool(event)
                            if not event:
                                passed=False; details.update(passed=False,reason=self.last_entry_reason,applied_order_krw=0.)
                            self.records.observation(scan,market,stamp(),details)
                        rows.append((i+1,market,self.prices.get(market),rsi,trend,('통과' if passed else '제외')+' · '+details['reason']))
                        if i%5==4: self.manage_positions()
                    self.messages.put(('rows',rows))
                    status='interrupted' if self.stop_event.is_set() else 'network_error' if self.network.snapshot()['state'] in ('offline','stale') else 'complete'
                    self.records.finish_scan(scan,stamp(),status)
                    self.last_scan=now_kst().strftime('%H:%M:%S'); self.scan_text='시장 판단/가상검증 완료'
                    self.manage_positions()
                except Exception as e:
                    self.errors+=1; self.regime.invalidate('시장 스캔 오류 · 신규 진입 잠금')
                    self.scan_text='조회 오류 · 재시도 대기'
                    if isinstance(e,MarketDataError): self.network_failure('전체 조회',e)
                    if scan: self.records.finish_scan(scan,stamp(),'error')
                    if not isinstance(e,(MarketDataError,CandleHistoryError,ValueError)):
                        self.record_error=True; self.stop_event.set()
                    self.log(f'가상 검증 루프 오류: {e}')
                delay=max(self.config['poll_seconds'],30) if not self.network.can_enter() else self.config['poll_seconds']
                for tick in range(delay):
                    if self.stop_event.wait(1): break
                    # Keep evaluating fresh exits even when the entry regime is bear/unknown.
                    if tick%5==4:
                        try: self.manage_positions()
                        except Exception as e:
                            self.record_error=True; self.stop_event.set(); self.log(f'기록/가상 감시 실패: {e}')
        finally:
            self.running=False; self.scan_text='가상검증 중지됨'
            self.live_event.clear(); self.messages.put(('off',None))
            self.log('가상검증 종료 · 가상 보유/잔고는 다음 실행에 복구됩니다.')

    def on_close(self):
        if self.tray and self.tray.available:
            self.root.withdraw()
            return
        self.request_exit()

    def request_exit(self):
        if self.exiting: return
        self.exiting=True; self.stop(); self.closed=True
        self.root.after(100,self.finish_exit)

    def finish_exit(self):
        if self.worker and self.worker.is_alive():
            self.root.after(100,self.finish_exit); return
        if self.tray: self.tray.stop()
        self.root.destroy()

    def pump(self):
        if self.tray:
            for action in self.tray.actions():
                if action=='show': self.root.deiconify(); self.root.lift()
                elif action=='stop': self.stop(); self.root.deiconify()
                elif action=='quit': self.request_exit()
            if self.tray.failed and self.root.state()=='withdrawn': self.root.deiconify()
        super().pump()
        self.update_activity_signal()
        s=self.paper.state
        self.mode_var.set('가상매매 · 실거래 잠금')
        self.holding_var.set(f"가상 {len(s['positions'])} / {self.config['max_positions']}")
        self.loss_streak_var.set(f"가상 {s['loss_streak']} / {self.config['max_losses']}")
        self.safety_text='기록 저장 실패 · 중지 필요' if self.record_error else '가상 검증 전용 · 실제 주문 없음'
        market=self.regime.snapshot()
        if self.tray:
            self.tray.status(f"업비트 v1.8 · {'실행 중' if self.running else '중지됨'} · 시장 {market['state']}")
        names={'unknown':'판정 불가','recovering':'회복 확인','bear':'약세','cautious':'주의','normal':'정상'}
        breadth='자료 없음' if market['breadth'] is None else f"{market['breadth']*100:.1f}%"
        self.market_label.configure(text=f"시장 {names[market['state']]} · 상승 추세 {market['valid']}/{market['expected']} ({breadth}) · "
            f"{market['reason']} · {self.risk.daily['reason']} · X: 트레이로 숨김" if self.tray and self.tray.available else
            f"시장 {names[market['state']]} · 상승 추세 {breadth} · {market['reason']} · {self.risk.daily['reason']} · 트레이 사용 불가")
        health=self.network.snapshot()
        network_name={'checking':'시작 확인','recovering':'복구 확인','healthy':'정상','offline':'장애','stale':'수신 지연'}[health['state']]
        self.network_label.configure(text=f"통신 {network_name} · 마지막 종합 정상 수신 {health['last_success'] or '없음'} · "
            f"복구 확인 {min(health['successes'],2)}/2 · 신규 가상매수 {'가능' if health['entry_allowed'] and market['entry_allowed'] and self.risk.daily['entry_allowed'] and self.running else '잠금'} · "
            '통신 단절 동안 자동 청산 불가',fg=dashboard.GREEN if health['entry_allowed'] else dashboard.RED)
        self.today_label.configure(text=f"가상 누적 실현손익 {s['realized']:+,.0f}원\n누적 수수료 {s['fees']:,.0f}원 · 종료 {s['closed']}건",fg=dashboard.TEXT)
        self.paper_summary.configure(text=f"가상 잔고 {s['cash']:,.0f}원  |  가상 보유 {len(s['positions'])}종목  |  누적 실현손익 {s['realized']:+,.0f}원\n실제 주문 OFF · 기록은 시작 버튼을 누른 동안 누적됩니다.")
        if hasattr(self,'comparison'):
            current,reference=self.comparison
            values='평가 시세 부족' if current is None or reference is None else f'개선안 평가 {current:,.0f}원 / 기존 조건 비교 {reference:,.0f}원'
            self.paper_summary.configure(text=self.paper_summary.cget('text')+'\n'+values+' · 공통 조회 일정의 가상 비교')
        # Only refresh the last 500 ledger rows when the number of trades changes.
        with self.records.db() as db:
            count=db.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
            if count!=getattr(self,'last_trade_count',-1):
                events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM trades ORDER BY id DESC LIMIT 500')]
                self.paper_tree.delete(*self.paper_tree.get_children())
                for e in events:
                    self.paper_tree.insert('','end',values=(e['stamp'],'가상매수' if e['side']=='BUY' else '가상매도',e['market'],fmt_num(e['price'],4),fmt_num(e['qty'],8),fmt_num(e['fee'],2),fmt_num(e['pnl'],2),e['reason']))
                self.last_trade_count=count
                self.refresh_ledger()
                self.refresh_profit_view()
        if time.monotonic()-getattr(self,'last_daily_refresh',0)>=15:
            self.refresh_profit_view()
            self.last_daily_refresh=time.monotonic()

    def export_records(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('기록 내보내기','중지를 누르고 감시 종료 후 내보내 주세요. 종료 시까지의 기록을 묶습니다.')
            return
        target=main.BASE/'reports'; target.mkdir(exist_ok=True)
        path=target/f"validation_{now_kst():%Y%m%d_%H%M%S}.zip"
        export_bundle(self.records,path)
        messagebox.showinfo('내보내기 완료',f'{path}\n이 ZIP만 공유하세요. API 키/.env는 포함하지 않습니다.')


def export_bundle(records,path):
    with tempfile.TemporaryDirectory() as temp:
        snapshot=Path(temp)/'validation.sqlite3'
        src=sqlite3.connect(records.path); dst=sqlite3.connect(snapshot)
        try: src.backup(dst)
        finally: src.close(); dst.close()
        db=sqlite3.connect(snapshot)
        try:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts={t:db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('scans','observations','trades','logs','quotes','equity','candles','network_events','health_checks','market_checks','entry_decisions','risk_days') if t in tables}
            span=db.execute('SELECT MIN(started),MAX(ended) FROM scans').fetchone()
            state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            report=dict(risk_policy=POLICY,version='1.8',exported_at=stamp(),counts=counts,first_scan=span[0],last_scan_end=span[1],
                simulation_only=True,initial_cash=state['initial_cash'],cash=state['cash'],realized_pnl=state['realized'],
                fees=state['fees'],positions=state['positions'],closed=state['closed'],wins=state['wins'],
                fee_rate=state['fee'],slippage_bps=state['slippage_bps'],
                scan_status=dict(db.execute('SELECT status,COUNT(*) FROM scans GROUP BY status').fetchall()),
                log_kinds=dict(db.execute('SELECT kind,COUNT(*) FROM logs GROUP BY kind').fetchall()),
                warning='실제 주문 안전성 미검증. 가상 수익은 실거래 수익/안전성 증명이 아닙니다.')
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(snapshot,'validation.sqlite3')
                z.writestr('summary.json',json.dumps(report,ensure_ascii=False,indent=2))
                z.writestr('README.txt','가상검증 기록입니다. DB에는 지표/캔들/오류/가상거래가 들어 있습니다. API 키와 실제 계좌 DB는 포함하지 않습니다.\n가상 체결은 즉시 전량 체결을 가정하며 실제 부분체결/미확인 주문 복구 검증을 대신하지 않습니다.')
                for table in [t for t in ('scans','observations','trades','logs','equity','network_events','health_checks','market_checks','entry_decisions','risk_days') if t in tables]:
                    cursor=db.execute(f'SELECT * FROM {table}')
                    with io.TextIOWrapper(z.open(f'{table}.csv','w'),encoding='utf-8-sig',newline='') as output:
                        writer=csv.writer(output)
                        writer.writerow([d[0] for d in cursor.description]); writer.writerows(cursor)
                reference=Path(records.path).with_name('benchmark_v18.sqlite3')
                if reference.exists():
                    refcopy=Path(temp)/'benchmark_v18.sqlite3'
                    rs=sqlite3.connect(reference); rd=sqlite3.connect(refcopy)
                    try: rs.backup(rd)
                    finally: rs.close(); rd.close()
                    z.write(refcopy,'benchmark_v18.sqlite3')
                    rb=sqlite3.connect(refcopy)
                    try:
                        for tab in ('trades','equity'):
                            cursor=rb.execute(f'SELECT * FROM {tab}')
                            with io.TextIOWrapper(z.open(f'benchmark_{tab}.csv','w'),encoding='utf-8-sig',newline='') as output:
                                writer=csv.writer(output); writer.writerow([d[0] for d in cursor.description]); writer.writerows(cursor)
                        refstate=json.loads(rb.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                        z.writestr('benchmark_summary.json',json.dumps(dict(seed=refstate['benchmark_seed'],
                            cash=refstate['cash'],realized_pnl=refstate['realized'],positions=refstate['positions'],
                            limitation='v1.7 signals on common v1.8 scan schedule; not exact v1.7 execution replay'),ensure_ascii=False,indent=2))
                    finally: rb.close()
                daily={}
                with io.TextIOWrapper(z.open('paper_trades.csv','w'),encoding='utf-8-sig',newline='') as output:
                    fields=['record_id','category','stamp','side','market','quote','price','qty','funds','fee','pnl','reason','simulation']
                    writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
                    for rid,payload in db.execute('SELECT id,payload FROM trades ORDER BY id'):
                        event=json.loads(payload); writer.writerow(dict(event,record_id=rid,category=category(event)))
                        day=event['stamp'][:10]
                        d=daily.setdefault(day,dict(date=day,buys=0,sells=0,fees=0.,realized_pnl=0.))
                        d['buys' if event['side']=='BUY' else 'sells']+=1
                        d['fees']+=event['fee']; d['realized_pnl']+=event['pnl']
                with io.TextIOWrapper(z.open('paper_daily.csv','w'),encoding='utf-8-sig',newline='') as output:
                    writer=csv.DictWriter(output,fieldnames=['date','buys','sells','fees','realized_pnl'])
                    writer.writeheader(); writer.writerows(daily[d] for d in sorted(daily))
        finally: db.close()
    return path


if __name__=='__main__':
    import msvcrt
    lockfile=open(main.BASE/'.instance.lock','a+b'); lockfile.seek(0)
    if lockfile.read(1)==b'': lockfile.write(b'0'); lockfile.flush()
    lockfile.seek(0)
    try: msvcrt.locking(lockfile.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: raise SystemExit('이미 실행 중입니다.')
    root=tk.Tk(); ValidationApp(root); root.mainloop()
