"""Calendar picker and table sizing; no trading state is changed here."""
import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk,font

def shift_month(year,month,delta):
    index=(year-1)*12+month-1+delta
    if not 0<=index<9999*12: return year,month
    return index//12+1,index%12+1

def autofit_column(tree,column,max_width=760):
    columns=list(tree['columns'])
    if column.startswith('#'):
        index=int(column[1:])-1
        if not 0<=index<len(columns): return
        column=columns[index]
    if column not in columns: return
    style=ttk.Style(tree)
    name=tree.cget('style') or 'Treeview'
    body=font.Font(root=tree,font=style.lookup(name,'font') or 'TkDefaultFont')
    heading=font.Font(root=tree,font=style.lookup(name+'.Heading','font') or body)
    width=heading.measure(tree.heading(column,'text'))+24
    for item in tree.get_children(''):
        text=str(tree.set(item,column))
        width=max(width,max((body.measure(line) for line in text.splitlines()),default=0)+24)
    width=max(int(tree.column(column,'minwidth')),min(width,max_width))
    tree.column(column,width=width,stretch=False)
    return width

def autofit_separator(tree,event):
    if tree.identify_region(event.x,event.y)!='separator': return
    autofit_column(tree,tree.identify_column(event.x))
    return 'break'

class DatePicker(tk.Toplevel):
    def __init__(self,parent,variable,title='날짜 선택',today=None,on_select=None):
        super().__init__(parent)
        self.variable=variable; self.on_select=on_select; self.today=today or date.today()
        try: selected=date.fromisoformat(variable.get())
        except ValueError: selected=self.today
        self.selected=selected
        self.year,self.month=selected.year,selected.month
        self.title(title); self.resizable(False,False); self.transient(parent.winfo_toplevel())
        self.configure(bg='#edf3f8')
        head=ttk.Frame(self,padding=10); head.pack(fill='x')
        for label,delta in [('◀ 연',-12),('◀ 월',-1)]:
            ttk.Button(head,text=label,command=lambda n=delta:self.move(n)).pack(side='left',padx=2)
        self.caption=ttk.Label(head,width=15,anchor='center'); self.caption.pack(side='left',padx=5)
        for label,delta in [('월 ▶',1),('연 ▶',12)]:
            ttk.Button(head,text=label,command=lambda n=delta:self.move(n)).pack(side='left',padx=2)
        self.days=ttk.Frame(self,padding=(12,0,12,8)); self.days.pack(fill='both',expand=True)
        footer=ttk.Frame(self,padding=(10,0,10,10)); footer.pack(fill='x')
        ttk.Label(footer,text='←/→: 월 이동 · ↑/↓: 연 이동').pack(side='left',padx=5)
        ttk.Button(footer,text='오늘',command=lambda:self.choose(self.today.day,self.today.year,self.today.month)).pack(side='right')
        self.bind('<Left>',lambda _:self.key_move(-1)); self.bind('<Right>',lambda _:self.key_move(1))
        self.bind('<Up>',lambda _:self.key_move(-12)); self.bind('<Down>',lambda _:self.key_move(12))
        self.bind('<Escape>',lambda _:self.destroy())
        self.render(); self.update_idletasks()
        x=parent.winfo_rootx(); y=parent.winfo_rooty()+parent.winfo_height()
        x=max(0,min(x,self.winfo_screenwidth()-self.winfo_reqwidth()-12))
        y=max(0,min(y,self.winfo_screenheight()-self.winfo_reqheight()-40))
        self.geometry(f'+{x}+{y}'); self.grab_set(); self.focus_set()

    def key_move(self,delta): self.move(delta); return 'break'
    def move(self,delta): self.year,self.month=shift_month(self.year,self.month,delta); self.render()
    def render(self):
        for child in self.days.winfo_children(): child.destroy()
        self.caption.configure(text=f'{self.year}년 {self.month:02}월')
        for col,label in enumerate(('월','화','수','목','금','토','일')):
            ttk.Label(self.days,text=label,anchor='center',width=6).grid(row=0,column=col,padx=2,pady=4)
        for row,week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(self.year,self.month),1):
            for col,day in enumerate(week):
                if day:
                    style='Accent.TButton' if date(self.year,self.month,day)==self.selected else 'TButton'
                    button=ttk.Button(self.days,text=str(day),width=5,style=style,command=lambda n=day:self.choose(n))
                    button.grid(row=row,column=col,padx=2,pady=2)
    def choose(self,day,year=None,month=None):
        self.variable.set(date(year or self.year,month or self.month,day).isoformat())
        callback=self.on_select; self.destroy()
        if callback: callback()

def date_field(parent,variable,label,on_select=None,today=None):
    frame=ttk.Frame(parent)
    ttk.Label(frame,text=label).pack(side='left',padx=(0,5))
    entry=ttk.Entry(frame,textvariable=variable,width=12,state='readonly'); entry.pack(side='left')
    def show(_=None):
        DatePicker(entry,variable,title=label+' 선택',today=today() if today else None,on_select=on_select)
        return 'break'
    entry.bind('<Button-1>',show); entry.bind('<Return>',show); entry.bind('<space>',show)
    ttk.Button(frame,text='달력 ▾',command=show).pack(side='left',padx=(3,8))
    return frame
