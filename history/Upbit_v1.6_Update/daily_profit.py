"""KST daily paper results; never read legacy real-account CSVs."""
import csv
import json
import os
from pathlib import Path

FIELDS=['date','buys','sells','stops','targets','trailing','fees','realized_pnl','sell_win_rate_pct','last_equity','equity_stamp']


def daily_results(records):
    days={}
    def day(key):
        return days.setdefault(key,dict(date=key,buys=0,sells=0,stops=0,targets=0,trailing=0,fees=0.,realized_pnl=0.,wins=0,last_equity=None,equity_stamp=''))
    with records.db() as db:
        for (payload,) in db.execute('SELECT payload FROM trades ORDER BY id'):
            e=json.loads(payload); d=day(e['stamp'][:10]); d['fees']+=float(e['fee'])
            if e['side']=='BUY': d['buys']+=1
            else:
                d['sells']+=1; d['realized_pnl']+=float(e['pnl']); d['wins']+=int(float(e['pnl'])>0)
                if e['reason']=='손절': d['stops']+=1
                elif e['reason']=='1차 익절': d['targets']+=1
                elif e['reason']=='트레일링': d['trailing']+=1
        # Latest actual snapshot each KST date, including NULL when a quote is missing.
        for stamp,payload in db.execute('SELECT stamp,payload FROM equity WHERE id IN (SELECT MAX(id) FROM equity GROUP BY substr(stamp,1,10))'):
            e=json.loads(payload); d=day(stamp[:10]); d['last_equity']=e['equity']; d['equity_stamp']=stamp
    result=[]
    for key in sorted(days):
        d=days[key]; wins=d.pop('wins'); d['sell_win_rate_pct']=wins/d['sells']*100 if d['sells'] else None
        result.append(d)
    return result


def write_daily(records,path):
    path=Path(path); tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(daily_results(records))
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
    return path
