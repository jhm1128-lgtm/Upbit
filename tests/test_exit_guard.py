import copy
import tempfile
import unittest
from pathlib import Path
from exit_guard import BearExitGuard
from paper import Records,Paper
from comparison_v19 import open_control
from risk_records import RiskBook
from trade_history import category,matches

TIME='2026-11-11T19:00:00+09:00'
CONFIG=dict(order_krw=150000,max_positions=5,max_losses=7,stop_pct=3,target_pct=3,trailing_pct=2,first_fraction=.5)
def market(state):return dict(state=state,breadth=.2 if state=='bear' else .8,frame=1000)

class ExitGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.records=Records(Path(self.tmp.name)/'test.sqlite3')
        self.paper=Paper(self.records);self.paper.buy('KRW-X',100,CONFIG,TIME)
        self.t=0;self.guard=BearExitGuard(clock=lambda:self.t);self.audit=[]
    def tearDown(self):self.tmp.cleanup()
    def observe(self,state):return self.guard.observe(market(state),self.paper.state['positions'],TIME)
    def evaluate(self,quotes,snapshot=None):
        return self.guard.evaluate(self.paper,quotes,snapshot or market('bear'),TIME,lambda s,v:self.audit.append(v))
    def arm(self):self.observe('normal');self.t+=1;self.assertTrue(self.observe('bear'))

    def test_profit_is_net_of_all_costs_and_event_is_idempotent(self):
        self.arm();events=self.evaluate({'KRW-X':101})
        self.assertEqual(len(events),1);self.assertGreater(events[0]['pnl'],0)
        self.assertEqual(events[0]['reason'],'BEAR 수익 보호');self.assertFalse(self.paper.state['positions'])
        self.assertEqual([v['stage'] for v in self.audit],['intent','result'])
        self.assertEqual(self.evaluate({'KRW-X':101}),[])
        self.assertTrue(matches(events[0],'BEAR 수익 보호'));self.assertTrue(matches(events[0],'익절 전체'))
        self.assertEqual(category(events[0]),'BEAR 수익 보호')

    def test_small_gross_gain_and_loss_are_not_profit_protection(self):
        self.arm();self.assertEqual(self.evaluate({'KRW-X':100.1}),[])
        self.assertIn('KRW-X',self.paper.state['positions']);self.assertFalse(self.audit[-1]['executed'])
        self.assertEqual(self.evaluate({'KRW-X':102}),[]) # Only first fresh quote of the transition.

    def test_starting_bear_unknown_and_recovering_never_create_transition(self):
        for state in ('bear','unknown','recovering'):
            self.guard=BearExitGuard(clock=lambda:self.t)
            self.observe(state);self.observe('bear');self.assertEqual(self.evaluate({'KRW-X':102}),[])

    def test_stale_previous_assessment_cannot_arm(self):
        self.observe('normal');self.t+=91;self.assertFalse(self.observe('bear'))
        self.assertEqual(self.evaluate({'KRW-X':102}),[])

    def test_missing_quote_waits_but_expires_and_ignores_cached_prices(self):
        self.arm();self.assertEqual(self.evaluate({}),[]);self.assertTrue(self.guard.pending)
        self.t+=91;self.assertEqual(self.evaluate({'KRW-X':102}),[])
        self.assertFalse(self.guard.pending)

    def test_missing_quote_can_complete_inside_valid_signal(self):
        self.arm();self.evaluate({});self.t+=15
        self.assertEqual(len(self.evaluate({'KRW-X':102})),1)

    def test_nonfinite_price_and_invalid_market_do_not_sell(self):
        self.arm();self.assertEqual(self.evaluate({'KRW-X':float('nan')}),[])
        self.observe('unknown');self.assertEqual(self.evaluate({'KRW-X':102}),[])

    def test_remaining_cost_after_first_target_and_closed_position(self):
        self.paper.monitor({'KRW-X':104},CONFIG,TIME)
        old=copy.deepcopy(self.paper.state['positions']['KRW-X']);self.arm()
        events=self.evaluate({'KRW-X':104});self.assertEqual(events[0]['qty'],old['qty'])
        expected=old['qty']*104*.9995*.9995-old['avg']*old['qty']-old['entry_fee_remaining']
        self.assertAlmostEqual(events[0]['pnl'],expected)

    def test_new_position_identity_cannot_receive_old_signal(self):
        self.arm();self.paper.state['positions']['KRW-X']['opened_at']='2026-11-11T19:01:00+09:00'
        self.assertEqual(self.evaluate({'KRW-X':102}),[])

    def test_control_seed_freezes_settings_and_keeps_independent_state(self):
        risk=RiskBook(self.records);risk.mark_equity(TIME,self.paper.state,{'KRW-X':100})
        path=Path(self.tmp.name)/'control.sqlite3'
        control,crisk,config=open_control(self.records,path,CONFIG,TIME)
        before=copy.deepcopy(control.state);self.arm();self.evaluate({'KRW-X':102})
        self.assertEqual(control.state,before)
        restored,_,settings=open_control(self.records,path,dict(CONFIG,max_positions=1),TIME)
        self.assertEqual(settings,CONFIG);self.assertEqual(restored.state,before)
        with control.records.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM risk_days').fetchone()[0],1)

if __name__=='__main__':unittest.main()
