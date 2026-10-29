"""Reference-inspired dashboard; execution remains in main.UpbitAutoTrader."""
import math
import queue
import threading
import tkinter as tk
from tkinter import ttk
import main as engine
from main import now_kst, fmt_num, pyupbit

BG = '#031025'
PANEL = '#071d38'
EDGE = '#174d7a'
TEXT = '#e9f1ff'
MUTED = '#9db9db'
CYAN = '#00d8ed'
BLUE = '#0878ff'
GREEN = '#00ca93'
RED = '#ff4b73'


class Dashboard(engine.UpbitAutoTrader):
    def __init__(self,root):
        self.chart_results = queue.Queue()
        self.chart_generation = 0
        self.chart_busy = False
        self.chart_data = None
        self.chart_market = 'KRW-BTC'
        self.chart_interval = 'minute5'
        self.closed = False
        self.nav_buttons = []
        super().__init__(root)
        root.title('UPBIT AUTO TRADING v1.6 · Neon Dashboard')
        root.geometry('1536x1000')
        root.minsize(1150,800)
        root.after(500,self.request_chart)
        root.after(60000,self.auto_chart)

    def box(self,parent,title,color=CYAN):
        f = tk.Frame(parent,bg=PANEL,highlightbackground=EDGE,highlightthickness=1)
        tk.Label(f,text=title,bg=PANEL,fg=color,font=('맑은 고딕',12,'bold'),anchor='w').pack(fill='x',padx=12,pady=(10,8))
        return f

    def table(self,parent,columns):
        wrap = tk.Frame(parent,bg=PANEL)
        wrap.pack(fill='both',expand=True,padx=8,pady=(0,8))
        tree = ttk.Treeview(wrap,columns=[c[0] for c in columns],show='headings',style='Neon.Treeview')
        for key,title,width in columns:
            tree.heading(key,text=title)
            tree.column(key,width=width,minwidth=50,anchor='center',stretch=True)
        vs = ttk.Scrollbar(wrap,orient='vertical',command=tree.yview)
        hs = ttk.Scrollbar(wrap,orient='horizontal',command=tree.xview)
        vs.pack(side='right',fill='y'); hs.pack(side='bottom',fill='x')
        tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        tree.pack(fill='both',expand=True)
        tree.tag_configure('pass',foreground=GREEN,background='#07372f')
        tree.tag_configure('error',foreground=RED)
        return tree

    def build_ui(self):
        # Retain the tested settings variables/history initialization, then replace the layout.
        super().build_ui()
        for child in self.root.winfo_children(): child.destroy()
        self.root.configure(bg=BG)
        style = ttk.Style()
        style.configure('Neon.Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=29,font=('맑은 고딕',9),borderwidth=0)
        style.configure('Neon.Treeview.Heading',background='#102c4d',foreground=TEXT,font=('맑은 고딕',9,'bold'),padding=7)
        style.map('Neon.Treeview',background=[('selected','#164c7a')],foreground=[('selected',TEXT)])
        style.layout('Hidden.TNotebook.Tab',[])
        style.configure('Hidden.TNotebook',background=BG,borderwidth=0)
        header = tk.Frame(self.root,bg='#051b34',height=58)
        header.pack(fill='x')
        tk.Label(header,text='▥  UPBIT AUTO TRADING',bg='#051b34',fg=TEXT,font=('Segoe UI',21,'bold')).pack(side='left',padx=18,pady=9)
        tk.Label(header,text='v1.6',bg='#051b34',fg=CYAN,font=('Segoe UI',15,'bold')).pack(side='left')
        tk.Label(header,text='거래대금 상위 + 추세 + RSI   |   손절 · 익절 · 트레일링',bg='#051b34',fg=MUTED,font=('맑은 고딕',10)).pack(side='left',padx=22)
        self.clock = tk.Label(header,bg='#051b34',fg=TEXT,font=('Segoe UI',10))
        self.clock.pack(side='right',padx=18)
        body = tk.Frame(self.root,bg=BG); body.pack(fill='both',expand=True)
        sidebar = tk.Frame(body,bg='#09213f',width=174); sidebar.pack(side='left',fill='y'); sidebar.pack_propagate(False)
        area = tk.Frame(body,bg=BG); area.pack(side='left',fill='both',expand=True,padx=12,pady=12)
        cards = tk.Frame(area,bg=BG); cards.pack(fill='x')
        self.holding_var = tk.StringVar(value='0 / 3')
        for i,(icon,title,var,color) in enumerate([
            ('₩','원화 잔고',self.krw_balance,CYAN),('⊘','연속 손절',self.loss_streak_var,RED),
            ('◉','모드',self.mode_var,'#af8bff'),('◷','마지막 스캔',self.last_scan_var,GREEN),
            ('◕','보유 종목',self.holding_var,'#ffbb43')]):
            cards.columnconfigure(i,weight=1)
            card = tk.Frame(cards,bg=PANEL,highlightbackground=color,highlightthickness=1)
            card.grid(row=0,column=i,sticky='nsew',padx=(0,8 if i<4 else 0))
            tk.Label(card,text=icon,bg=PANEL,fg=color,font=('Segoe UI',29,'bold')).pack(side='left',padx=10,pady=14)
            inner = tk.Frame(card,bg=PANEL); inner.pack(side='left',fill='both',expand=True,pady=12)
            tk.Label(inner,text=title,bg=PANEL,fg=color,font=('맑은 고딕',10,'bold'),anchor='w').pack(fill='x')
            tk.Label(inner,textvariable=var,bg=PANEL,fg=TEXT,font=('맑은 고딕',13,'bold'),anchor='w').pack(fill='x',pady=(6,0))
        controls = tk.Frame(area,bg=BG); controls.pack(fill='x',pady=12)
        left = self.box(controls,'⚙  자동매매 제어'); left.pack(side='left',fill='both',expand=True,padx=(0,10))
        row = tk.Frame(left,bg=PANEL); row.pack(fill='x',padx=12,pady=(0,12))
        ttk.Checkbutton(row,text='실전 주문 활성화 (실제 자금 사용)',variable=self.live_enabled,command=self.on_live_toggle).pack(side='left',padx=(0,12))
        for text,command,color in [('▶ 시작',self.start,'#00a979'),('■ 중지',self.stop,'#dc365b'),('⟳ 잔고 새로고침',self.refresh_balance,'#164575')]:
            tk.Button(row,text=text,command=command,bg=color,fg='white',activebackground=color,activeforeground='white',relief='flat',font=('맑은 고딕',10,'bold'),padx=14,pady=7).pack(side='left',padx=4)
        right = self.box(controls,'⚙  매매 기본 설정 (현재값)',TEXT); right.pack(side='left',fill='both')
        self.config_label = tk.Label(right,bg=PANEL,fg=MUTED,font=('맑은 고딕',9),wraplength=420,justify='left')
        self.config_label.pack(padx=12,pady=(0,12))
        tk.Label(area,textvariable=self.status,bg=BG,fg=MUTED,font=('맑은 고딕',9),anchor='w').pack(fill='x',pady=(0,7))
        self.tabs = ttk.Notebook(area,style='Hidden.TNotebook'); self.tabs.pack(fill='both',expand=True)
        pages = [tk.Frame(self.tabs,bg=BG) for _ in range(7)]
        titles = ['대시보드','매수 후보','보유 종목','거래 내역','손익 현황','전략 설정','로그']
        for i,(page,title) in enumerate(zip(pages,titles)):
            self.tabs.add(page,text=title)
            button = tk.Button(sidebar,text=['⌂','▧','◕','▤','▥','⚙','☷'][i]+'   '+title,command=lambda n=i:self.navigate(n),bg='#09213f',fg=TEXT,activebackground=BLUE,activeforeground='white',relief='flat',anchor='w',font=('맑은 고딕',12,'bold'),padx=20,pady=15)
            button.pack(fill='x',padx=8,pady=(10 if i==0 else 3,3)); self.nav_buttons.append(button)
        tk.Label(sidebar,text='NEON DASHBOARD\nv1.6\n\n실거래 잠금',bg='#09213f',fg=MUTED,font=('Segoe UI',9),justify='left').pack(side='bottom',pady=25)
        dash = pages[0]
        dash.rowconfigure(0,weight=6); dash.rowconfigure(1,weight=2); dash.rowconfigure(2,weight=2)
        dash.columnconfigure(0,weight=7); dash.columnconfigure(1,weight=3)
        candidates = [('rank','순위',45),('market','코인',95),('price','현재가',100),('change','등락(전일)',85),('value','거래대금(24h)',110),('rsi','RSI(5m)',70),('trend','추세',70),('signal','신호',65),('reason','상세 사유',260)]
        cb = self.box(dash,'▤  매수 후보 · 거래대금 상위 스캔 결과','#ffcd4b'); cb.grid(row=0,column=0,sticky='nsew',padx=(0,10),pady=(0,10))
        self.dash_candidate_tree = self.table(cb,candidates)
        self.dash_candidate_tree.bind('<<TreeviewSelect>>',self.select_chart)
        chart = self.box(dash,'▥  차트 미리보기','#b78dff'); chart.grid(row=0,column=1,sticky='nsew',pady=(0,10))
        self.chart_title = tk.Label(chart,text='BTC / KRW · 조회 대기',bg=PANEL,fg=TEXT,font=('맑은 고딕',12,'bold'),anchor='w'); self.chart_title.pack(fill='x',padx=12)
        intervals = tk.Frame(chart,bg=PANEL); intervals.pack(fill='x',padx=10,pady=5)
        self.interval_buttons = {}
        for label,interval in [('5분','minute5'),('15분','minute15'),('1시간','minute60'),('4시간','minute240')]:
            button = tk.Button(intervals,text=label,command=lambda v=interval:self.set_interval(v),bg='#123858',fg=TEXT,relief='flat',padx=8,pady=4)
            button.pack(side='left',padx=2); self.interval_buttons[interval]=button
        self.chart_canvas = tk.Canvas(chart,bg='#04162c',highlightthickness=0)
        self.chart_canvas.pack(fill='both',expand=True,padx=10,pady=(0,10)); self.chart_canvas.bind('<Configure>',lambda _:self.draw_chart())
        positions = [('market','코인',95),('avg','평균 매수가',110),('price','현재가',100),('pnl','수익률',85),('qty','보유 수량',110),('target','1차 익절',75),('peak','진입 후 최고가',110)]
        pb = self.box(dash,'◕  보유 종목','#ffcd4b'); pb.grid(row=1,column=0,sticky='nsew',padx=(0,10),pady=(0,10))
        self.dash_position_tree = self.table(pb,positions)
        profit = self.box(dash,'◷  오늘의 손익 현황',GREEN); profit.grid(row=1,column=1,sticky='nsew',pady=(0,10))
        self.today_label = tk.Label(profit,bg=PANEL,fg=TEXT,font=('맑은 고딕',12,'bold'),justify='left',anchor='nw'); self.today_label.pack(fill='both',expand=True,padx=12,pady=8)
        log = self.box(dash,'▣  로그','#b78dff'); log.grid(row=2,column=0,columnspan=2,sticky='nsew')
        self.log_text = tk.Text(log,bg='#03162c',fg=MUTED,insertbackground=TEXT,relief='flat',height=4,font=('Consolas',9),state='disabled',wrap='word')
        self.log_text.pack(fill='both',expand=True,padx=10,pady=(0,10))
        self.candidate_tree = self.table(pages[1],[(key,title,width) for key,title,width in [candidates[0],candidates[1],candidates[4],candidates[2],*candidates[5:]]])
        self.candidate_tree.bind('<<TreeviewSelect>>',self.select_chart)
        self.position_tree = self.table(pages[2],positions)
        self.trade_tree = self.table(pages[3],[(x,y,120) for x,y in [('time','일시'),('side','구분'),('market','종목'),('price','체결단가'),('qty','수량'),('amount','금액'),('pnl','손익'),('rate','수익률'),('reason','사유')]])
        filters = tk.Frame(pages[4],bg=BG); filters.pack(fill='x',pady=8)
        for label,var,attr in [('연도',self.year_filter,'year_combo'),('월',self.month_filter,'month_combo'),('일',self.day_filter,'day_combo')]:
            tk.Label(filters,text=label,bg=BG,fg=TEXT).pack(side='left',padx=8)
            combo = ttk.Combobox(filters,textvariable=var,width=8,state='readonly'); combo.pack(side='left'); setattr(self,attr,combo)
        ttk.Button(filters,text='조회',command=self.refresh_profit_view).pack(side='left',padx=10)
        ttk.Button(filters,text='전체 보기',command=self.reset_profit_filters).pack(side='left')
        self.pnl_summary_label = ttk.Label(pages[4]); self.pnl_summary_label.pack(fill='x',pady=8)
        self.daily_tree = self.table(pages[4],[(x,y,130) for x,y in [('date','일자'),('pnl','실현손익'),('rate','수익률'),('assets','마감자산'),('count','매도 횟수'),('winrate','승률')]])
        specs = [('order_krw','1회 매수 금액 (원)'),('max_positions','최대 보유 종목 수'),('stop_pct','손절 (%)'),('target_pct','1차 익절 (%)'),('trailing_pct','트레일링 (%)'),('first_fraction','1차 매도 비율'),('max_losses','연속 손절 제한'),('top_n','거래대금 상위 N'),('poll_seconds','스캔 사이 대기 (초)')]
        for i,(key,label) in enumerate(specs):
            tk.Label(pages[5],text=label,bg=BG,fg=TEXT,font=('맑은 고딕',11)).grid(row=i,column=0,padx=20,pady=8,sticky='w')
            ttk.Entry(pages[5],textvariable=self.setting_vars[key],width=22).grid(row=i,column=1,padx=20,pady=8)
        ttk.Button(pages[5],text='설정 저장 · 중지 후 적용',command=self.save_settings).grid(row=9,column=0,columnspan=2,pady=12)
        tk.Label(pages[5],text='미확인 주문/잔고 불일치 시 실거래 잠금\n실제 체결 및 Python 3.11 직접 실행 검증 미완료',bg=BG,fg=MUTED).grid(row=10,column=0,columnspan=3,padx=20,pady=10,sticky='w')
        tk.Label(pages[6],text='실시간 로그는 대시보드 하단에 표시됩니다.',bg=BG,fg=MUTED,font=('맑은 고딕',12)).pack(pady=30)
        ttk.Button(pages[6],text='대시보드 로그 보기',command=lambda:self.navigate(0)).pack()
        self.refresh_history_views(); self.navigate(0)

    def navigate(self,index):
        self.tabs.select(index)
        for i,button in enumerate(self.nav_buttons): button.configure(bg=BLUE if i==index else '#09213f')

    def pump(self):
        super().pump()
        self.clock.configure(text=now_kst().strftime('%Y-%m-%d  %H:%M:%S'))
        self.holding_var.set(f"{len(self.positions)} / {self.config['max_positions']}")
        c = self.config
        self.config_label.configure(text=f"1회 {c['order_krw']:,.0f}원  |  최대 {c['max_positions']}종목\n손절 -{c['stop_pct']:g}%  |  1차 +{c['target_pct']:g}%  |  트레일링 -{c['trailing_pct']:g}%")
        today = now_kst().strftime('%Y-%m-%d')
        sells = [r for r in self.trade_rows if r.get('side')=='매도' and r.get('time','').startswith(today)]
        pnl = sum(float(r.get('realized_pnl_est',0) or 0) for r in sells)
        self.today_label.configure(text=f"실현 손익  {pnl:+,.0f}원\n매도 {len(sells)}회   ·   추정/체결 기록 합산",fg=RED if pnl>0 else CYAN if pnl<0 else TEXT)
        try:
            while True:
                generation,market,interval,data,error = self.chart_results.get_nowait()
                if generation != self.chart_generation: continue
                self.chart_busy = False
                if market != self.chart_market or interval != self.chart_interval:
                    self.request_chart()
                    continue
                self.chart_data = data
                self.chart_error = error
                self.chart_title.configure(text=f"{market[4:]} / KRW  ·  {fmt_num(data[-1]['close'],2) if data else '조회 실패'}")
                self.draw_chart()
        except queue.Empty: pass

    def update_candidate_view(self,rows):
        super().update_candidate_view(rows)
        selected = self.chart_market
        tree = self.dash_candidate_tree
        tree.delete(*tree.get_children())
        for rank,market,price,rsi,trend,reason in rows:
            change = getattr(self,'day_changes',{}).get(market)
            tree.insert('','end',iid=market,values=(rank,market,fmt_num(price,2),f'{change:+.2f}%' if change is not None else '—',fmt_num(self.candidate_values.get(market),0),fmt_num(rsi,1),'-' if trend is None else '▲ 상승' if trend else '미충족','통과' if reason.startswith('통과') else '대기' if reason=='스캔 대기' else '제외',reason),tags=('pass',) if reason.startswith('통과') else ('error',) if '오류' in reason else ())

    def render_positions(self,positions):
        super().render_positions(positions)
        if not hasattr(self,'dash_position_tree'): return
        t = self.dash_position_tree; t.delete(*t.get_children())
        for item in self.position_tree.get_children(): t.insert('','end',values=self.position_tree.item(item,'values'))
        if not positions: t.insert('','end',values=('보유 없음',)+('',)*6)

    def select_chart(self,event):
        tree = event.widget
        selected = tree.selection()
        if not selected: return
        market = tree.item(selected[0],'values')[1]
        if market != self.chart_market:
            self.chart_market = market
            self.navigate(0)
            self.request_chart()

    def set_interval(self,interval):
        self.chart_interval = interval; self.request_chart()

    def auto_chart(self):
        if self.closed: return
        if not self.chart_busy: self.request_chart()
        self.root.after(60000,self.auto_chart)

    def request_chart(self):
        if self.closed: return
        if self.chart_busy: return
        self.chart_generation += 1
        generation,market,interval = self.chart_generation,self.chart_market,self.chart_interval
        self.chart_busy = True
        self.chart_data = None
        self.chart_error = '시세 조회 중…'
        self.chart_title.configure(text=f'{market[4:]} / KRW · 조회 중')
        for key,button in self.interval_buttons.items(): button.configure(bg=BLUE if key==interval else '#123858')
        self.draw_chart()
        def worker():
            data,error = None,''
            try:
                df = pyupbit.get_ohlcv(market,interval=interval,count=100)
                if df is None or len(df)<20: raise ValueError('캔들 데이터 부족')
                for col in ('open','high','low','close','volume'):
                    if not df[col].map(lambda x:math.isfinite(float(x)) and float(x)>=0).all(): raise ValueError('비정상 차트 데이터')
                df = df.copy(); df['sma20']=df['close'].rolling(20).mean(); df['sma50']=df['close'].rolling(50).mean()
                df['stamp'] = df.index.astype(str)
                data = df.tail(60).to_dict('records')
            except Exception as e: error = str(e)
            self.chart_results.put((generation,market,interval,data,error))
        threading.Thread(target=worker,daemon=True).start()

    def draw_chart(self):
        canvas = self.chart_canvas; canvas.delete('all')
        w,h = canvas.winfo_width(),canvas.winfo_height()
        if not self.chart_data:
            canvas.create_text(w/2,h/2,text=getattr(self,'chart_error','종목을 선택하면 실제 캔들을 조회합니다'),fill=MUTED,width=max(80,w-20))
            return
        data = self.chart_data
        left,right,top,bottom = 12,max(30,w-62),15,max(40,h-28)
        price_bottom = top+(bottom-top)*.72
        low,high = min(r['low'] for r in data),max(r['high'] for r in data)
        span = max(high-low,high*.001,1e-8); low-=span*.07; high+=span*.07
        def y(price): return price_bottom-(price-low)/(high-low)*(price_bottom-top)
        step = (right-left)/len(data)
        for i in range(5):
            yy = top+(price_bottom-top)*i/4
            canvas.create_line(left,yy,right,yy,fill='#113353')
            value = high-(high-low)*i/4
            canvas.create_text(right+5,yy,text=fmt_num(value,0 if high>=100 else 2),anchor='w',fill=MUTED,font=('Segoe UI',8))
        vmax = max(max(r['volume'] for r in data),1e-10)
        for i,r in enumerate(data):
            x=left+(i+.5)*step; color = RED if r['close']>=r['open'] else GREEN
            canvas.create_line(x,y(r['high']),x,y(r['low']),fill=color)
            y1,y2=y(r['open']),y(r['close'])
            canvas.create_rectangle(x-step*.32,min(y1,y2),x+step*.32,max(y1,y2)+1,fill=color,outline=color)
            vh=r['volume']/vmax*(bottom-price_bottom-15)
            canvas.create_rectangle(x-step*.32,bottom-vh,x+step*.32,bottom,fill=color,outline='')
        for col,color in [('sma20','#f9ce37'),('sma50','#1ca8ff')]:
            points=[]
            for i,r in enumerate(data):
                if math.isfinite(r[col]): points.extend((left+(i+.5)*step,y(r[col])))
            if len(points)>=4: canvas.create_line(*points,fill=color,width=1.3)
        for i in (0,len(data)//2,len(data)-1):
            canvas.create_text(left+(i+.5)*step,bottom+14,text=data[i]['stamp'][11:16],fill=MUTED,font=('Segoe UI',8))
        canvas.create_text(left+3,top+2,text='SMA20  /  SMA50   ·   거래량',fill=MUTED,anchor='nw',font=('Segoe UI',8))

    def on_close(self):
        self.closed = True
        super().on_close()


if __name__ == '__main__':
    raise SystemExit('v1.6은 start.bat 또는 validation_app.py로 실행하세요. 이 구버전 진입점은 잠겨 있습니다.')
    import msvcrt
    lockfile = open(engine.BASE/'.instance.lock','a+b')
    lockfile.seek(0)
    if lockfile.read(1)==b'': lockfile.write(b'0'); lockfile.flush()
    lockfile.seek(0)
    try: msvcrt.locking(lockfile.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: raise SystemExit('이미 실행 중입니다.')
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


