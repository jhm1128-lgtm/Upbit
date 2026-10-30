"""Provisional paper-validation policy; no fitted profit claims or exchange orders."""
import copy
import math
import threading
import time
from datetime import datetime, timezone, timedelta

POLICY = dict(version='1.8', bear_breadth=1/3, normal_breadth=.5,
              minimum_candidates=10, minimum_coverage=.8, confirmations=2,
              cautious_size=.5, cautious_max_positions=1, assessment_ttl=90,
              max_sample_age=45, max_candle_age=660, max_drop=.04,
              max_range=.08, max_quote_deviation=.02, daily_loss_limit=.02)
STABLES={'KRW-USDT','KRW-USDC','KRW-DAI'}

def candle_time(value):
    d=datetime.fromisoformat(str(value))
    if d.tzinfo is None: d=d.replace(tzinfo=timezone(timedelta(hours=9)))
    return d.timestamp()

def shock_reason(inputs,quote=None,policy=POLICY):
    try:
        move=float(inputs['candle_move']); high=float(inputs['candle_high'])
        low=float(inputs['candle_low']); previous=float(inputs['previous_close'])
        closed=float(inputs['closed_price'])
        if not all(math.isfinite(x) for x in (move,high,low,previous,closed)) or min(low,previous,closed)<=0 or high<low:
            return '급변 판단 수치 오류'
        if move<=-policy['max_drop']: return '완료 5분봉 급락 4% 이상'
        if (high-low)/previous>=policy['max_range']: return '완료 5분봉 진폭 8% 이상'
        if quote is not None:
            quote=float(quote)
            if not math.isfinite(quote) or quote<=0: return '매수 직전 가격 오류'
            if abs(quote/closed-1)>=policy['max_quote_deviation']: return '매수 직전 가격과 신호 종가 괴리 2% 이상'
    except (KeyError,ValueError,TypeError): return '급변 판단 자료 부족'
    return ''

class MarketGuard:
    def __init__(self,clock=time.monotonic,policy=None):
        self.clock=clock; self.policy=copy.deepcopy(policy or POLICY)
        self.lock=threading.RLock(); self.updated=None; self.pending=None; self.count=0; self.frame=None
        self.data=dict(state='unknown',reason='시장 판단 전',breadth=None,rising=None,valid=0,expected=0,
                       confirmation_count=0,entry_allowed=False,size_factor=0.,position_cap=0)

    def invalidate(self,reason):
        with self.lock:
            self.updated=None; self.pending=None; self.count=0; self.frame=None
            self.data.update(state='unknown',reason=reason,entry_allowed=False,size_factor=0.,position_cap=0,
                             confirmation_count=0,breadth=None,rising=None)
            return dict(self.data)

    def assess(self,samples,expected,wall):
        with self.lock:
            now=self.clock(); policy=self.policy
            if self.updated is not None and now-self.updated>policy['assessment_ttl']:
                self.invalidate('시장 판단 수신 지연')
            valid=[]
            for market,(inputs,received) in samples.items():
                if market in STABLES: continue
                try:
                    age=wall-candle_time(inputs['candle_stamp'])
                    if (type(inputs['trend']) is bool and 0<=now-received<=policy['max_sample_age']
                        and 300<=age<=policy['max_candle_age']): valid.append(inputs)
                except (KeyError,TypeError,ValueError): pass
            expected=len(set(expected)-STABLES)
            self.data.update(valid=len(valid),expected=expected,breadth=None)
            if expected<policy['minimum_candidates'] or len(valid)<policy['minimum_candidates'] or len(valid)/expected<policy['minimum_coverage']:
                return self.invalidate('시장 판단 자료 부족 · 신규 진입 잠금')
            rising=sum(v['trend'] for v in valid)
            breadth=rising/len(valid)
            frame=min(candle_time(v['candle_stamp']) for v in valid)
            target='bear' if breadth<policy['bear_breadth'] else 'normal' if breadth>=policy['normal_breadth'] else 'cautious'
            self.updated=now; self.data.update(breadth=breadth,rising=rising,frame=frame)
            current=self.data['state']
            if target=='bear':
                self.pending=None; self.count=0; self.frame=frame
                state='bear'; reason='후보군 추세 약세 · 신규 진입 잠금'
            elif current==target:
                self.pending=None; self.count=0; self.frame=frame
                state=target; reason='후보군 추세 정상' if target=='normal' else '후보군 추세 주의 · 축소 진입'
            elif current=='normal' and target=='cautious':
                self.pending=None; self.count=0; self.frame=frame
                state='cautious'; reason='추세 약화 · 즉시 축소 진입'
            else:
                if self.pending!=target:
                    self.pending=target; self.count=1; self.frame=frame
                elif frame>self.frame:
                    self.count+=1; self.frame=frame
                state=current if current=='cautious' else 'recovering'
                reason=f'서로 다른 완료 5분봉 회복 확인 {self.count}/{policy["confirmations"]}'
                if self.count>=policy['confirmations']:
                    state=target; self.pending=None
                    reason='후보군 추세 정상' if target=='normal' else '후보군 추세 주의 · 축소 진입'
            allowed=state in ('normal','cautious')
            self.data.update(state=state,reason=reason,confirmation_count=self.count,
                             entry_allowed=allowed,size_factor=1. if state=='normal' else policy['cautious_size'] if state=='cautious' else 0.,
                             position_cap=None if state=='normal' else policy['cautious_max_positions'] if state=='cautious' else 0)
            return dict(self.data)

    def snapshot(self):
        with self.lock:
            if self.updated is not None and self.clock()-self.updated>self.policy['assessment_ttl']:
                return self.invalidate('시장 판단 수신 지연 · 신규 진입 잠금')
            return dict(self.data)

    def entry_config(self,config,position_count):
        state=self.snapshot()
        if not state['entry_allowed']: return None,state['reason']
        result=dict(config); result['order_krw']=float(config['order_krw'])*state['size_factor']
        if state['position_cap'] is not None: result['max_positions']=min(int(config['max_positions']),state['position_cap'])
        if result['order_krw']<5000: return None,'축소 주문금액이 최소 5,000원 미만'
        if position_count>=result['max_positions']: return None,'시장 상태별 최대 보유 도달'
        return result,''

def market_counts_text(snapshot):
    valid,expected=snapshot['valid'],snapshot['expected']
    prefix=f'분석 가능 {valid}/{expected}'
    if snapshot['breadth'] is None or not valid:
        return prefix+' · 상승 추세 자료 없음'
    rising=snapshot.get('rising')
    if rising is None: rising=round(snapshot['breadth']*valid)
    return prefix+f" · 상승 {rising}/{valid} ({snapshot['breadth']*100:.1f}%)"
