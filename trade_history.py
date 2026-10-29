"""Human-readable projection of the canonical SQLite paper-trade ledger."""
import csv
import json
import os
from pathlib import Path

FIELDS=['record_id','stamp','simulation','category','side','market','quote','price','qty','funds','fee','pnl','reason']
CATEGORIES=['전체','매수','매도 전체','손절','익절 전체','1차 익절','트레일링','기타 매도']


def category(event):
    if event['side']=='BUY': return '매수'
    reason=event.get('reason','')
    return reason if reason in ('손절','1차 익절','트레일링') else '기타 매도'


def matches(event,selected):
    c=category(event)
    if selected=='전체': return True
    if selected=='매도 전체': return event['side']=='SELL'
    # Trailing can realize a loss after a gap; it is never called a profitable exit blindly.
    if selected=='익절 전체': return event['side']=='SELL' and float(event.get('pnl',0))>0
    return c==selected


def read_history(records,selected='전체',market='',date_from='',date_to='',limit=2000):
    rows=[]; summary=dict(count=0,buys=0,sells=0,stops=0,targets=0,trailing=0,fees=0.,pnl=0.)
    with records.db() as db:
        for rid,payload in db.execute('SELECT id,payload FROM trades ORDER BY id DESC'):
            e=json.loads(payload)
            if not matches(e,selected): continue
            if market.strip().upper() not in e['market'].upper(): continue
            date=e['stamp'][:10]
            if date_from and date<date_from: continue
            if date_to and date>date_to: continue
            c=category(e); summary['count']+=1
            summary['buys' if e['side']=='BUY' else 'sells']+=1
            if c=='손절': summary['stops']+=1
            elif c=='1차 익절': summary['targets']+=1
            elif c=='트레일링': summary['trailing']+=1
            summary['fees']+=e['fee']; summary['pnl']+=e['pnl']
            if len(rows)<limit: rows.append(dict(e,record_id=rid,category=c))
    return rows,summary


def write_history(records,path):
    """Atomic rebuild from IDs, so restart/recovery never appends duplicates."""
    path=Path(path); temp=path.with_name(path.name+'.tmp')
    with records.db() as db:
        with temp.open('w',encoding='utf-8-sig',newline='') as output:
            writer=csv.DictWriter(output,fieldnames=FIELDS,extrasaction='ignore'); writer.writeheader()
            for rid,payload in db.execute('SELECT id,payload FROM trades ORDER BY id'):
                e=json.loads(payload)
                writer.writerow(dict(e,record_id=rid,category=category(e)))
            output.flush(); os.fsync(output.fileno())
    os.replace(temp,path)
    return path
