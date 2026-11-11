import copy
import random
import tempfile
import unittest
from pathlib import Path
from capital import allocation_plan
from paper import Records,Paper

CONFIG=dict(order_krw=150000,max_positions=5,max_losses=7)
BULL=dict(state='normal',entry_allowed=True,size_factor=1.,position_cap=None,reason='BULL')
CAUTIOUS=dict(state='cautious',entry_allowed=True,size_factor=.5,position_cap=1,reason='NORMAL')
TIME='2026-11-04T18:00:00+09:00'
def empty(cash): return dict(cash=cash,positions={},fee=.0005,slippage_bps=5)

class CapitalTests(unittest.TestCase):
    def test_700000_supports_three_equal_entries(self):
        config,plan=allocation_plan(empty(700000),{},CONFIG,BULL)
        self.assertEqual(plan['new_slots'],3); self.assertEqual(plan['effective_cap'],3)
        self.assertEqual(config['order_krw'],186573)
        self.assertGreaterEqual(plan['projected_cash_ratio'],.2)

    def test_million_supports_five_entries(self):
        config,plan=allocation_plan(empty(1000000),{},CONFIG,BULL)
        self.assertEqual(plan['new_slots'],5); self.assertEqual(config['order_krw'],159920)

    def test_three_existing_positions_can_add_fourth_and_fifth_in_bull(self):
        with tempfile.TemporaryDirectory() as folder:
            paper=Paper(Records(Path(folder)/'test.sqlite3'))
            quotes={}
            for i in range(3):
                symbol=f'KRW-X{i}'; paper.buy(symbol,100,CONFIG,TIME); quotes[symbol]=100
            for i in (3,4):
                config,plan=allocation_plan(paper.state,quotes,CONFIG,BULL)
                self.assertIsNotNone(config); self.assertGreaterEqual(config['order_krw'],150000)
                symbol=f'KRW-X{i}'; self.assertIsNotNone(paper.buy(symbol,100,config,TIME)); quotes[symbol]=100
                equity=paper.state['cash']+sum(p['qty']*quotes[m] for m,p in paper.state['positions'].items())
                self.assertGreaterEqual(paper.state['cash']/equity,.2)
            self.assertEqual(len(paper.state['positions']),5)
            self.assertIsNone(allocation_plan(paper.state,quotes,CONFIG,BULL)[0])

    def test_700000_with_three_positions_cannot_force_fourth(self):
        state=empty(250000); state['positions']={f'KRW-X{i}':dict(qty=1500) for i in range(3)}
        config,plan=allocation_plan(state,{m:100 for m in state['positions']},CONFIG,BULL)
        self.assertIsNone(config); self.assertEqual(plan['new_slots'],0)

    def test_fee_included_in_affordability_boundary(self):
        self.assertIsNone(allocation_plan(empty(187500),{},CONFIG,BULL)[0])
        self.assertIsNotNone(allocation_plan(empty(187594),{},CONFIG,BULL)[0])

    def test_cautious_cannot_round_up_below_minimum(self):
        config,plan=allocation_plan(empty(1000000),{},CONFIG,CAUTIOUS)
        self.assertIsNone(config); self.assertIn('최소',plan['reason'])
        config,plan=allocation_plan(empty(2000000),{},CONFIG,CAUTIOUS)
        self.assertGreaterEqual(config['order_krw'],150000); self.assertEqual(config['max_positions'],1)

    def test_existing_three_are_blocked_in_cautious(self):
        state=empty(1000000); state['positions']={f'KRW-X{i}':dict(qty=10) for i in range(3)}
        self.assertIsNone(allocation_plan(state,{m:100 for m in state['positions']},CONFIG,CAUTIOUS)[0])

    def test_extra_slots_require_bull_even_if_market_cap_is_unspecified(self):
        state=empty(1000000); state['positions']={f'KRW-X{i}':dict(qty=10) for i in range(3)}
        not_bull=dict(CAUTIOUS,position_cap=None,size_factor=1.)
        self.assertIsNone(allocation_plan(state,{m:100 for m in state['positions']},CONFIG,not_bull)[0])

    def test_bear_unknown_and_missing_prices_block(self):
        for state_name in ('bear','unknown','recovering'):
            market=dict(BULL,state=state_name,entry_allowed=False,reason=state_name)
            self.assertIsNone(allocation_plan(empty(1000000),{},CONFIG,market)[0])
        state=empty(1000000); state['positions']={'KRW-X':dict(qty=100)}
        self.assertIsNone(allocation_plan(state,{},CONFIG,BULL)[0])

    def test_hard_cap_is_five_and_low_setting_cannot_lower_minimum(self):
        config,plan=allocation_plan(empty(1000000),{},dict(CONFIG,max_positions=50,order_krw=5000),BULL)
        self.assertEqual(config['max_positions'],5)
        self.assertGreaterEqual(config['order_krw'],150000)

    def test_atomic_paper_gate_rechecks_minimum_and_reserve(self):
        with tempfile.TemporaryDirectory() as folder:
            paper=Paper(Records(Path(folder)/'test.sqlite3'))
            config,plan=allocation_plan(paper.state,{},CONFIG,BULL)
            self.assertIsNone(paper.buy('KRW-X',100,dict(config,order_krw=149999),TIME))
            self.assertIsNone(paper.buy('KRW-X',100,dict(config,order_krw=850000),TIME))
            self.assertEqual(paper.state['cash'],1000000)

    def test_random_portfolios_preserve_reserve_after_fees_and_slippage(self):
        rng=random.Random(19); checked=0
        for _ in range(500):
            state=empty(rng.uniform(0,3000000)); quotes={}
            for i in range(rng.randrange(6)):
                symbol=f'KRW-X{i}'; state['positions'][symbol]=dict(qty=rng.uniform(1,2000)); quotes[symbol]=rng.uniform(1,200)
            saved=copy.deepcopy(state)
            config,plan=allocation_plan(state,quotes,CONFIG,BULL)
            if config:
                self.assertGreaterEqual(plan['projected_cash_ratio']+1e-12,.2)
                self.assertGreaterEqual(config['order_krw'],150000)
                self.assertLessEqual(config['max_positions'],5); checked+=1
                self.assertLessEqual(config['order_krw'],plan['per_position_cap'])
            self.assertEqual(state,saved)
        self.assertGreater(checked,50)

    def test_partial_exits_cannot_concentrate_released_cash_into_last_slot(self):
        from capital_v19 import allocation_plan as old_plan
        state=empty(626000);state['positions']={f'KRW-X{i}':dict(qty=850) for i in range(4)}
        quotes={m:100 for m in state['positions']}
        old,_=old_plan(state,quotes,CONFIG,BULL)
        config,info=allocation_plan(state,quotes,CONFIG,BULL)
        self.assertGreater(old['order_krw'],400000)
        self.assertLess(config['order_krw'],200000)
        self.assertGreaterEqual(config['order_krw'],150000)
        self.assertEqual(info['total_affordable_slots'],5)

    def test_ledger_rejects_cap_tampering_even_when_reserve_would_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            paper=Paper(Records(Path(folder)/'test.sqlite3'))
            config,info=allocation_plan(paper.state,{},CONFIG,BULL)
            self.assertIn('집중',paper.gate('KRW-X',dict(config,order_krw=200000),TIME))

if __name__=='__main__': unittest.main()
