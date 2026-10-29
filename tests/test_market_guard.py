import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from market_guard import MarketGuard,POLICY,shock_reason
from risk_records import RiskBook,benchmark
from paper import Records,Paper

NOW=datetime(2026,10,29,1,tzinfo=timezone.utc).timestamp()
STAMP='2026-10-29T10:00:00+09:00'

def inputs(age=300,trend=True):
    return dict(trend=trend,candle_stamp=datetime.fromtimestamp(NOW-age,timezone.utc).isoformat(),
                candle_move=.01,candle_high=102.,candle_low=99.,previous_close=100.,closed_price=101.,strategy_pass=True,legacy_pass=True)

class MarketGuardTests(unittest.TestCase):
    def setUp(self):
        self.t=0.; self.g=MarketGuard(clock=lambda:self.t)
    def assess(self,up=10,age=300,n=15,expected=15):
        return self.g.assess({f'KRW-{i}':(inputs(age,i<up),self.t) for i in range(n)},[f'KRW-{i}' for i in range(expected)],NOW)
    def ready(self): self.assess(age=600); self.assess(age=300)
    def test_initial_unknown_locked(self): self.assertFalse(self.g.snapshot()['entry_allowed'])
    def test_same_candle_never_confirms_recovery(self):
        for _ in range(5): self.assess()
        self.assertEqual(self.g.snapshot()['state'],'recovering')
    def test_two_distinct_completed_candles_allow_normal(self):
        self.ready(); self.assertEqual(self.g.snapshot()['state'],'normal')
    def test_bear_blocks_immediately(self):
        self.ready(); self.assess(up=4); self.assertEqual(self.g.snapshot()['state'],'bear')
    def test_bear_to_normal_requires_two_new_frames(self):
        self.assess(up=4,age=600); self.assess(age=600)
        self.assertFalse(self.g.snapshot()['entry_allowed'])
        self.assess(age=300); self.assertTrue(self.g.snapshot()['entry_allowed'])
    def test_normal_to_cautious_reduces_immediately(self):
        self.ready(); self.assess(up=6)
        c,reason=self.g.entry_config(dict(order_krw=150000,max_positions=3),0)
        self.assertEqual(c['order_krw'],75000); self.assertEqual(c['max_positions'],1)
        self.assertFalse(reason)
        self.assertIsNone(self.g.entry_config(dict(order_krw=150000,max_positions=3),1)[0])
    def test_missing_coverage_is_unknown_not_bear(self):
        self.ready(); self.assess(n=10)
        self.assertEqual(self.g.snapshot()['state'],'unknown')
    def test_stale_samples_cannot_enable_entries(self):
        samples={f'KRW-{i}':(inputs(),0) for i in range(15)}; self.t=46
        self.g.assess(samples,list(samples),NOW)
        self.assertEqual(self.g.snapshot()['state'],'unknown')
    def test_stale_assessment_resets_recovery(self):
        self.ready(); self.t=91
        self.assertEqual(self.g.snapshot()['state'],'unknown')
        self.assess(); self.assertFalse(self.g.snapshot()['entry_allowed'])
    def test_future_or_unfinished_candles_are_unknown(self):
        for age in (-300,0,299,661):
            self.assess(age=age); self.assertEqual(self.g.snapshot()['state'],'unknown')
    def test_btc_cannot_define_market_alone(self):
        self.g.assess({'KRW-BTC':(inputs(),0)},['KRW-BTC'],NOW)
        self.assertFalse(self.g.snapshot()['entry_allowed'])
    def test_minimum_order_never_rounds_up(self):
        self.assess(up=6,age=600); self.assess(up=6)
        self.assertIsNone(self.g.entry_config(dict(order_krw=5000,max_positions=3),0)[0])
    def test_bad_input_is_fail_closed(self):
        self.g.assess({'KRW-X':({},0)},['KRW-X'],NOW)
        self.assertFalse(self.g.snapshot()['entry_allowed'])

class ShockTests(unittest.TestCase):
    def test_normal(self): self.assertEqual(shock_reason(inputs(),101.),'')
    def test_blast_historical_crash_rejected(self):
        p=inputs(); p.update(candle_move=-.3066666667,candle_high=.235,candle_low=.146,previous_close=.225,closed_price=.156)
        self.assertIn('급락',shock_reason(p,.158))
    def test_large_range_rejected(self):
        p=inputs(); p.update(candle_high=110,candle_low=99)
        self.assertIn('진폭',shock_reason(p,101))
    def test_live_quote_gap_both_directions_rejected(self):
        for quote in (98,104): self.assertIn('괴리',shock_reason(inputs(),quote))
    def test_missing_bad_numeric_rejected(self):
        self.assertTrue(shock_reason({}))
        for x in (float('nan'),float('inf'),0):
            p=inputs(); p['previous_close']=x; self.assertTrue(shock_reason(p))

class RiskBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.p=Path(self.tmp.name)
        self.records=Records(self.p/'validation.sqlite3'); self.paper=Paper(self.records)
        self.r=RiskBook(self.records)
    def tearDown(self): self.tmp.cleanup()
    def test_daily_loss_latches_and_survives_restart(self):
        state=self.paper.state
        self.r.mark_equity(STAMP,state,{})
        down=copy.deepcopy(state); down['cash']=970000
        self.assertFalse(self.r.mark_equity(STAMP,down,{})['entry_allowed'])
        restarted=RiskBook(self.records)
        self.assertFalse(restarted.mark_equity(STAMP,state,{})['entry_allowed'])
        self.assertTrue(restarted.mark_equity('2026-10-30T00:00:01+09:00',state,{})['entry_allowed'])
    def test_missing_held_price_blocks_entries(self):
        self.paper.buy('KRW-X',100,self.paper_config(),STAMP)
        self.assertFalse(self.r.mark_equity(STAMP,self.paper.state,{})['entry_allowed'])
    def paper_config(self): return dict(order_krw=150000,max_positions=3,max_losses=7)
    def test_reference_isolated_and_seed_survives_restart(self):
        original=copy.deepcopy(self.paper.state)
        ref=benchmark(self.records,self.p/'benchmark_v18.sqlite3',STAMP,original)
        ref.buy('KRW-X',100,self.paper_config(),STAMP)
        self.assertEqual(self.paper.state,original)
        restored=benchmark(self.records,self.p/'benchmark_v18.sqlite3',STAMP,original)
        self.assertIn('KRW-X',restored.state['positions'])
        self.assertEqual(restored.state['benchmark_seed']['stamp'],STAMP)

if __name__=='__main__': unittest.main()
