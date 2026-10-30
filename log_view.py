"""Read-only, bounded paging through the complete persisted log table."""
import tkinter as tk
from tkinter import ttk,messagebox
from datetime import date
from ui_widgets import date_field

KINDS={'전체':'','오류':'error','일반':'info','스캔':'scan','실행/재시작':'session'}

def validate_range(start,end):
    for value in (start,end):
        if value and date.fromisoformat(value).isoformat()!=value: raise ValueError('YYYY-MM-DD 날짜가 필요합니다.')
    if start and end and start>end: raise ValueError('시작일이 종료일보다 늦습니다.')

def read_logs(records,kind='',keyword='',start='',end='',before=None,limit=200):
    validate_range(start,end)
    terms=[]; params=[]
    for expression,value in [('kind=?',kind),('substr(stamp,1,10)>=?',start),('substr(stamp,1,10)<=?',end)]:
        if value: terms.append(expression); params.append(value)
    if keyword:
        terms.append("message LIKE ? ESCAPE '!'")
        params.append('%'+keyword.replace('!','!!').replace('%','!%').replace('_','!_')+'%')
    if before is not None: terms.append('id<?'); params.append(before)
    where=' WHERE '+' AND '.join(terms) if terms else ''
    with records.db() as db:
        rows=db.execute('SELECT id,stamp,kind,message FROM logs'+where+' ORDER BY id DESC LIMIT ?',params+[limit+1]).fetchall()
    return rows[:limit],len(rows)>limit

class LogPanel:
    def __init__(self,app,page):
        self.app=app; self.anchors=[None]; self.rows=[]; self.more=False
        for child in page.winfo_children(): child.destroy()
        controls=ttk.Frame(page,padding=8); controls.pack(fill='x')
        self.kind=tk.StringVar(value='전체'); self.keyword=tk.StringVar()
        ttk.Label(controls,text='종류').pack(side='left')
        combo=ttk.Combobox(controls,textvariable=self.kind,values=list(KINDS),state='readonly',width=12)
        combo.pack(side='left',padx=(4,12)); combo.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        ttk.Label(controls,text='내용 검색').pack(side='left')
        search=ttk.Entry(controls,textvariable=self.keyword,width=30); search.pack(side='left',padx=5)
        search.bind('<Return>',lambda _:self.refresh())
        ttk.Button(controls,text='조회 / 최신',command=self.refresh,style='Accent.TButton').pack(side='left',padx=5)
        ttk.Button(controls,text='전체 보기',command=self.reset).pack(side='left',padx=5)
        dates=ttk.Frame(page,padding=(8,0,8,4)); dates.pack(fill='x')
        self.start=tk.StringVar(); self.end=tk.StringVar()
        for var,label in ((self.start,'시작일(포함)'),(self.end,'종료일(포함)')):
            date_field(dates,var,label,self.refresh,today=lambda:__import__('main').now_kst().date()).pack(side='left')
        navigation=ttk.Frame(page,padding=8); navigation.pack(fill='x')
        self.info=ttk.Label(navigation,text='저장된 누적 로그'); self.info.pack(side='left',fill='x',expand=True)
        self.newer=ttk.Button(navigation,text='◀ 최신 쪽',command=self.previous); self.newer.pack(side='left',padx=3)
        self.older=ttk.Button(navigation,text='이전 기록 ▶',command=self.next); self.older.pack(side='left',padx=3)
        ttk.Label(page,text='저장된 과거 로그를 페이지로 조회합니다. 화면은 200개씩 표시하며 원본 기록을 삭제하지 않습니다.\n'
            '최신 페이지는 이 메뉴를 보는 동안 주기적으로 갱신됩니다. 오래된 페이지는 읽는 위치를 유지합니다.').pack(anchor='w',padx=10,pady=4)
        self.tree=app.table(page,[('id','번호',70),('stamp','일시 (KST)',190),('kind','종류',100),('message','누적 로그 내용',900)])
        self.refresh()

    def refresh(self,keep_page=False):
        try:
            validate_range(self.start.get(),self.end.get())
        except ValueError as error: messagebox.showerror('날짜 확인',str(error)); return
        if not keep_page: self.anchors=[None]
        self.rows,self.more=read_logs(self.app.records,KINDS[self.kind.get()],self.keyword.get().strip(),
                                     self.start.get(),self.end.get(),self.anchors[-1])
        self.tree.delete(*self.tree.get_children())
        labels={value:key for key,value in KINDS.items()}
        for row in self.rows:
            self.tree.insert('','end',iid=str(row[0]),values=(row[0],row[1],labels.get(row[2],row[2]),row[3]))
        self.info.configure(text=f'누적 로그 · {len(self.anchors)}페이지 · {len(self.rows)}개 표시 · 최신순')
        self.newer.configure(state='normal' if len(self.anchors)>1 else 'disabled')
        self.older.configure(state='normal' if self.more else 'disabled')

    def next(self):
        if self.more and self.rows:
            self.anchors.append(self.rows[-1][0]); self.refresh(keep_page=True)
    def previous(self):
        if len(self.anchors)>1: self.anchors.pop(); self.refresh(keep_page=True)
    def reset(self):
        self.kind.set('전체'); self.keyword.set(''); self.start.set(''); self.end.set(''); self.refresh()
