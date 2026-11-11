"""Fee-aware entry sizing. Existing positions are never force-rebalanced here."""
import math

CAPITAL_POLICY=dict(version='1.10',reserve_ratio=.20,minimum_order_krw=150000.,maximum_positions=5,
                    allocation='equal_remaining_affordable_slots',quote_ttl_seconds=15,
                    extra_positions_state='normal',concentration_limit='equal_total_affordable_slots')

def allocation_plan(state,quotes,config,market):
    info=dict(policy=CAPITAL_POLICY,state=market.get('state'),entry_allowed=False,reason='',order_krw=0.,
              equity=None,cash=state.get('cash'),reserve_cash=None,deployable_cash=0.,new_slots=0,
              effective_cap=0,held=len(state['positions']))
    def blocked(reason): info['reason']=reason; return None,info
    try:
        cash=float(state['cash']); fee=float(state['fee']); slip=float(state['slippage_bps'])/10000
        minimum=max(CAPITAL_POLICY['minimum_order_krw'],float(config['order_krw']))
        cap=min(CAPITAL_POLICY['maximum_positions'],int(config['max_positions']))
        if not all(math.isfinite(v) for v in (cash,fee,slip,minimum)) or cash<0 or not 0<=fee<=.01 or not 0<=slip<=.01 or cap<1:
            return blocked('자금 계산 수치 오류')
        holding_value=0.
        for symbol,position in state['positions'].items():
            price=float(quotes[symbol]); qty=float(position['qty'])
            if not math.isfinite(price) or price<=0 or not math.isfinite(qty) or qty<0:
                return blocked('보유 평가 수치 오류')
            holding_value+=qty*price
        equity=cash+holding_value
        if not math.isfinite(equity) or equity<=0: return blocked('총 평가자산 확인 필요')
        reserve=equity*CAPITAL_POLICY['reserve_ratio']
        deployable=max(0.,cash-reserve)
        slots=min(max(0,cap-info['held']),max(0,math.floor(deployable/(minimum*(1+fee)))))
        market_cap=market.get('position_cap')
        if market.get('state')!=CAPITAL_POLICY['extra_positions_state']: cap=min(cap,3)
        if market_cap is not None: cap=min(cap,int(market_cap))
        info.update(equity=equity,reserve_cash=reserve,deployable_cash=deployable,minimum_order_krw=minimum,
                    new_slots=min(slots,max(0,cap-info['held'])),effective_cap=min(cap,info['held']+slots))
        if not market.get('entry_allowed'): return blocked(market.get('reason','시장 진입 잠금'))
        if info['held']>=cap: return blocked('시장 상태별 최대 보유 도달')
        if slots<1: return blocked('현금 20%·최소 15만원 조건으로 추가 진입 불가')
        factor=float(market['size_factor'])
        if not math.isfinite(factor) or not 0<factor<=1: return blocked('시장별 주문 비율 오류')
        # Partial exits must not funnel all released cash into the last empty holding slot.
        total_slots=min(int(config['max_positions']),CAPITAL_POLICY['maximum_positions'],
                        max(0,math.floor(equity*(1-CAPITAL_POLICY['reserve_ratio'])/(minimum*(1+fee)))))
        if total_slots<1:return blocked('총자산 기준 최소 투자금액 부족')
        per_position_cap=equity*(1-CAPITAL_POLICY['reserve_ratio'])/(total_slots*(1+fee))
        funds=float(math.floor(min(deployable/(slots*(1+fee)),per_position_cap)*factor))
        info.update(total_affordable_slots=total_slots,per_position_cap=per_position_cap)
        if funds<minimum: return blocked('축소 금액이 종목당 최소 투자금액 미만')
        cash_after=cash-funds*(1+fee)
        equity_after=equity-funds*(fee+slip/(1+slip))
        if cash_after+1e-7<reserve: return blocked('매수 수수료 포함 현금 20% 확보 불가')
        result=dict(config,order_krw=funds,max_positions=info['effective_cap'],
                    capital_policy_version='1.10',minimum_order_krw=minimum,reserve_cash_min=reserve,
                    per_position_cap=per_position_cap)
        info.update(entry_allowed=True,reason='자금 조건 충족',order_krw=funds,
                    projected_cash=cash_after,projected_equity=equity_after,
                    projected_cash_ratio=cash_after/equity_after)
        return result,info
    except (ValueError,TypeError,KeyError,OverflowError):
        return blocked('보유 시세 누락/자금 판단 자료 부족')
