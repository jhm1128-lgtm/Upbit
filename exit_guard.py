"""Paper-only profit protection on a fresh, observed non-BEAR -> BEAR transition."""
import math
import time

EXIT_POLICY=dict(version='1.10',mode='bear_transition_profit',sell_fraction=1.,signal_ttl_seconds=90,
                 minimum_net_profit=0.,start_in_bear='wait_for_new_transition')

class BearExitGuard:
    def __init__(self,clock=time.monotonic):
        self.clock=clock; self.previous=None; self.pending={}; self.signal=None; self.armed_at=None

    def observe(self,snapshot,positions,stamp):
        now=self.clock(); state=snapshot.get('state'); breadth=snapshot.get('breadth')
        valid=state in ('normal','cautious','bear') and isinstance(breadth,(int,float)) and math.isfinite(breadth) and 0<=breadth<=1
        if not valid:
            self.previous=None; self.pending={}; return False
        transition=(state=='bear' and self.previous is not None and self.previous[1] in ('normal','cautious')
                    and 0<=now-self.previous[0]<=EXIT_POLICY['signal_ttl_seconds'])
        if state!='bear': self.pending={}
        if transition:
            self.pending={m:p['opened_at'] for m,p in positions.items()}
            self.signal=dict(stamp=stamp,breadth=breadth,frame=snapshot.get('frame'))
            self.armed_at=now
        self.previous=(now,state)
        return transition

    def evaluate(self,paper,quotes,snapshot,stamp,record):
        events=[]
        if not self.pending:return events
        if (snapshot.get('state')!='bear' or self.armed_at is None
                or not 0<=self.clock()-self.armed_at<=EXIT_POLICY['signal_ttl_seconds']):
            self.pending={}; return events
        for market,opened in list(self.pending.items()):
            position=paper.state['positions'].get(market)
            if position is None or position['opened_at']!=opened:
                self.pending.pop(market);continue
            if market not in quotes:continue  # No cached/fabricated quote; retry only inside the signal TTL.
            quote=quotes[market]
            if not isinstance(quote,(int,float)) or not math.isfinite(quote) or quote<=0:continue
            self.pending.pop(market)
            qty=position['qty']; price=quote*(1-paper.state['slippage_bps']/10000)
            funds=qty*price; fee=funds*paper.state['fee']
            net=funds-fee-position['avg']*qty-position['entry_fee_remaining']
            payload=dict(policy=EXIT_POLICY,signal=self.signal,market=market,opened_at=opened,quote=quote,
                         expected_net_pnl=net,quantity=qty,executed=False)
            if net<=EXIT_POLICY['minimum_net_profit']:
                payload['reason']='비용 반영 현재 순이익 없음'
            elif funds<5000:payload['reason']='최소 매도금액 미만'
            else:
                # Journal intent before the atomic ledger commit; outcome is a separate record.
                record(stamp,dict(payload,stage='intent',reason='BEAR 전환 · 현재 순이익 보호'))
                event=paper.sell(market,quote,qty,'BEAR 수익 보호',stamp)
                if event:
                    events.append(event);payload.update(executed=True,realized_pnl=event['pnl'])
                payload['reason']='BEAR 수익 보호' if event else '원장 매도 보류'
            record(stamp,dict(payload,stage='result'))
        return events
