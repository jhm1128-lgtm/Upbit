import json
import tempfile
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import main
from validation_app import ValidationApp,export_bundle
from network_guard import NetworkGuard
from market_data import MarketDataError

TIME='2026-10-22T09:00:00+09:00'

class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.patcher=patch.object(main,'BASE',self.base); self.patcher.start()
        self.env=patch.dict('os.environ',{'UPBIT_ACCESS_KEY':'','UPBIT_SECRET_KEY':''}); self.env.start()
        self.root=tk.Tk(); self.root.withdraw(); self.a=ValidationApp(self.root)
        self.t=0
        self.a.network=NetworkGuard(self.a.network_event,clock=lambda:self.t,wall=lambda:TIME)
    def tearDown(self):
        self.root.destroy(); self.env.stop(); self.patcher.stop(); self.tmp.cleanup()
    def ready(self): self.a.network.confirm_cycle(); self.t=5; self.a.network.confirm_cycle()
    def test_locked_buy_never_fetches_or_mutates(self):
        with patch.object(self.a.market,'quotes') as call:
            self.a.buy('KRW-X'); call.assert_not_called()
        self.assertEqual(self.a.paper.state['positions'],{})
    def test_failed_prebuy_quote_locks(self):
        self.ready()
        with patch.object(self.a.market,'quotes',side_effect=MarketDataError('DNS')): self.a.buy('KRW-X')
        self.assertFalse(self.a.network.can_enter()); self.assertFalse(self.a.paper.state['positions'])
    def test_recovered_buy_and_daily_lock(self):
        self.ready()
        with patch.object(self.a.market,'quotes',return_value={'KRW-X':10000}): self.a.buy('KRW-X')
        self.assertIn('KRW-X',self.a.paper.state['positions'])
        self.a.paper.monitor({'KRW-X':9500},self.a.config,TIME)
        self.assertIn('당일',self.a.paper.gate('KRW-X',self.a.config,TIME))
    def test_missing_quotes_do_not_sell_at_cached_price(self):
        self.a.paper.buy('KRW-X',10000,self.a.config,TIME); self.a.prices['KRW-X']=9500
        with patch.object(self.a.market,'holding_quotes',side_effect=MarketDataError('DNS')):
            self.assertFalse(self.a.manage_positions())
        self.assertIn('KRW-X',self.a.paper.state['positions']); self.assertNotIn('KRW-X',self.a.prices)
    def test_fresh_exit_allowed_during_recovery(self):
        self.a.paper.buy('KRW-X',10000,self.a.config,TIME)
        with patch.object(self.a.market,'holding_quotes',return_value=({'KRW-X':9500},[])):
            self.a.manage_positions()
        self.assertFalse(self.a.paper.state['positions']); self.assertFalse(self.a.network.can_enter())
    def test_export_health_and_correct_version(self):
        self.a.network.fail('DNS','test'); self.ready()
        out=self.base/'test.zip'; export_bundle(self.a.records,out)
        with zipfile.ZipFile(out) as z:
            self.assertIn('network_events.csv',z.namelist()); self.assertIn('health_checks.csv',z.namelist())
            report=json.loads(z.read('summary.json')); self.assertEqual(report['version'],'1.7')
            self.assertFalse(any(n.endswith('.env') for n in z.namelist()))
    def test_gui_network_red_and_settings_preserved(self):
        self.a.running=True; self.a.network.fail('DNS','test'); self.a.pump()
        self.assertIn('통신 장애',self.a.activity_label.cget('text'))
        self.assertIn('잠금',self.a.network_label.cget('text'))
        self.assertEqual(self.a.config['stop_pct'],3)
        with self.assertRaises(RuntimeError): self.a.execute('KRW-X','bid',5000,'test')

    def test_candle_shortage_is_not_network_failure(self):
        with patch.object(self.a.market,'candles',return_value=main.pd.DataFrame([{'close':1}])):
            from market_data import CandleHistoryError
            with self.assertRaises(CandleHistoryError): self.a.entry_signal('KRW-X')
        self.assertEqual(self.a.network.snapshot()['failures'],0)

    def test_existing_state_survives_app_restart(self):
        self.a.paper.buy('KRW-X',10000,self.a.config,TIME)
        state=json.loads(json.dumps(self.a.paper.state))
        newroot=tk.Tk(); newroot.withdraw()
        try:
            restored=ValidationApp(newroot)
            self.assertEqual(restored.paper.state,state)
            self.assertFalse(restored.network.can_enter())
        finally: newroot.destroy()

    def test_full_loop_warms_up_before_buying(self):
        a=self.a
        class Event:
            stopped=False
            waits=0
            def is_set(inner): return inner.stopped
            def set(inner): inner.stopped=True
            def wait(inner,seconds):
                if seconds==1:
                    inner.waits+=1; self.t+=1
                    if inner.waits>=31: inner.stopped=True
                return inner.stopped
        a.stop_event=Event(); a.running=True
        rows=[dict(market=m,trade_price=10000,acc_trade_price_24h=v,signed_change_rate=.01,timestamp=1000000)
              for m,v in [('KRW-BTC',200000000),('KRW-X',100000000)]]
        with patch.object(a.market,'universe',return_value=rows), \
             patch.object(a.market,'clock',return_value=1000), \
             patch.object(a.market,'quotes',return_value={'KRW-X':10000}), \
             patch.object(a.market,'holding_quotes',return_value=({'KRW-X':10000},[])), \
             patch.object(a,'entry_signal',return_value=(True,55.,True,'',dict(rsi=55.))):
            a.trade_loop()
        with a.records.db() as db:
            events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM trades')]
            observations=[json.loads(r[0]) for r in db.execute('SELECT payload FROM observations')]
        self.assertEqual(len(events),1)
        self.assertTrue(any('잠금' in v.get('gate','') for v in observations))
        self.assertFalse(a.running)

if __name__=='__main__': unittest.main()
