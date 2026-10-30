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
from market_guard import MarketGuard
import time
from types import SimpleNamespace
from datetime import timedelta

TIME='2026-10-22T09:00:00+09:00'

class AppTests(unittest.TestCase):
    def setUp(self):
        self.tray_patch=patch('validation_app.TrayIcon.start'); self.tray_patch.start()
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.patcher=patch.object(main,'BASE',self.base); self.patcher.start()
        self.env=patch.dict('os.environ',{'UPBIT_ACCESS_KEY':'','UPBIT_SECRET_KEY':''}); self.env.start()
        self.root=tk.Tk(); self.root.withdraw(); self.a=ValidationApp(self.root)
        self.t=0
        self.a.network=NetworkGuard(self.a.network_event,clock=lambda:self.t,wall=lambda:TIME)
    def tearDown(self):
        self.destroy_root(self.root); self.env.stop(); self.patcher.stop(); self.tmp.cleanup(); self.tray_patch.stop()
    def destroy_root(self,root):
        for timer in root.tk.call('after','info'): root.after_cancel(timer)
        root.update_idletasks()
        root.destroy()
    def signal(self,age=300):
        return dict(rsi=55.,trend=True,candle_stamp=(main.now_kst()-timedelta(seconds=age)).isoformat(),
                    candle_move=.01,candle_high=102.,candle_low=99.,previous_close=100.,closed_price=100.,
                    strategy_pass=True,legacy_pass=True)
    def ready(self):
        self.a.network.confirm_cycle(); self.t=5; self.a.network.confirm_cycle()
        for age in (600,300):
            samples={f'KRW-{i}':(self.signal(age),time.monotonic()) for i in range(15)}
            self.a.regime.assess(samples,list(samples),main.now_kst().timestamp())
    def buy(self,market): return self.a.buy(market,self.signal(),time.monotonic())
    def test_locked_buy_never_fetches_or_mutates(self):
        with patch.object(self.a.market,'quotes') as call:
            self.a.buy('KRW-X'); call.assert_not_called()
        self.assertEqual(self.a.paper.state['positions'],{})
    def test_failed_prebuy_quote_locks(self):
        self.ready()
        with patch.object(self.a.market,'quotes',side_effect=MarketDataError('DNS')): self.buy('KRW-X')
        self.assertFalse(self.a.network.can_enter()); self.assertFalse(self.a.paper.state['positions'])
    def test_recovered_buy_and_daily_lock(self):
        self.ready()
        with patch.object(self.a.market,'quotes',return_value={'KRW-X':100}): self.buy('KRW-X')
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
            report=json.loads(z.read('summary.json')); self.assertEqual(report['version'],'1.8.1')
            self.assertIn('market_checks.csv',z.namelist()); self.assertIn('entry_decisions.csv',z.namelist())
            self.assertIn('benchmark_v18.sqlite3',z.namelist())
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
        finally: self.destroy_root(newroot)

    def test_full_loop_insufficient_market_sample_blocks_entries(self):
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
        self.assertEqual(len(events),0)
        self.assertTrue(any('잠금' in v.get('gate','') for v in observations))
        self.assertFalse(a.running)

    def test_bear_keeps_fresh_exit_monitoring(self):
        self.a.paper.buy('KRW-X',100,self.a.config,TIME)
        self.a.regime.invalidate('약세 진입 잠금')
        with patch.object(self.a.market,'holding_quotes',return_value=({'KRW-X':95},[])):
            self.a.manage_positions()
        self.assertFalse(self.a.paper.state['positions'])

    def test_final_quote_deviation_blocks_mutation(self):
        self.ready()
        with patch.object(self.a.market,'quotes',return_value={'KRW-X':110}): self.buy('KRW-X')
        self.assertFalse(self.a.paper.state['positions']); self.assertIn('괴리',self.a.last_entry_reason)

    def test_tray_close_hides_and_stop_keeps_window_accessible(self):
        self.a.tray.available=True; self.a.on_close()
        self.assertEqual(self.root.state(),'withdrawn')
        self.a.tray.queue.put('show'); self.a.pump()
        self.assertNotEqual(self.root.state(),'withdrawn')

    def test_minimize_hides_to_tray_without_stopping_worker(self):
        self.a.tray.available=True; self.a.running=True
        with patch.object(self.root,'state',return_value='iconic'), patch.object(self.root,'withdraw') as hide:
            self.a.hide_minimized_window(); hide.assert_called_once()
        self.assertTrue(self.a.running); self.assertFalse(self.a.stop_event.is_set())

    def test_minimize_without_tray_retains_window(self):
        self.a.tray.available=False
        with patch.object(self.root,'state',return_value='iconic'), patch.object(self.root,'withdraw') as hide:
            self.a.hide_minimized_window(); hide.assert_not_called()

    def test_child_unmap_does_not_hide_root(self):
        with patch.object(self.root,'after_idle') as idle:
            self.a.on_window_unmap(SimpleNamespace(widget=self.a.dash_position_tree))
            idle.assert_not_called()

    def test_dashboard_allocates_more_height_to_candidates(self):
        self.a.closed=True  # Prevent chart HTTP callbacks during the layout-only render.
        self.root.geometry('1536x1000'); self.root.deiconify(); self.root.update()
        self.assertGreater(self.a.dash_candidate_tree.winfo_height(),self.a.dash_position_tree.winfo_height())
        self.assertLessEqual(int(self.a.dash_position_tree['height']),6)
        self.assertEqual(self.a.dashboard_page.grid_rowconfigure(1)['weight'],0)

    def test_market_badge_and_counts_show_current_bear_state(self):
        samples={f'KRW-{i}':(dict(self.signal(),trend=i==0),time.monotonic()) for i in range(14)}
        self.a.regime.assess(samples,list(samples),main.now_kst().timestamp())
        self.a.pump()
        self.assertEqual(self.a.market_badge.cget('text'),'BEAR · 약세')
        self.assertIn('상승 1/14 (7.1%)',self.a.market_label.cget('text'))

    def test_fee_display_stays_positive_and_does_not_change_pnl(self):
        self.a.paper.state['fees']=18570.; self.a.paper.state['realized']=-77922.
        self.a.pump()
        text=self.a.today_label.cget('text')
        self.assertIn('누적 수수료 18,570원',text)
        self.assertIn('-77,922원',text)
        self.assertEqual(self.a.paper.state['realized'],-77922.)

    def test_candidate_menu_removed_other_navigation_kept(self):
        self.assertEqual(self.a.tabs.tab(1,'state'),'hidden')
        self.assertEqual(self.a.nav_buttons[1].winfo_manager(),'')
        self.a.navigate(1)
        self.assertEqual(self.a.tabs.index(self.a.tabs.select()),0)
        for page in (2,3,4,5,6,7):
            self.a.navigate(page)
            self.assertEqual(self.a.tabs.index(self.a.tabs.select()),page)

    def test_market_unknown_blocks_buy_even_with_network_ready(self):
        self.ready(); self.a.regime.invalidate('자료 부족')
        with patch.object(self.a.market,'quotes') as call:
            self.buy('KRW-X'); call.assert_not_called()
        self.assertFalse(self.a.paper.state['positions'])

    def run_sample_loop(self,up):
        a=self.a; self.ready(); calls=[]; bought_after=[]
        class Event:
            stopped=False
            def is_set(inner): return inner.stopped
            def set(inner): inner.stopped=True
            def wait(inner,seconds):
                if seconds==1: inner.stopped=True
                return inner.stopped
        a.stop_event=Event(); a.running=True
        markets=['KRW-BTC']+[f'KRW-X{i}' for i in range(11)]
        rows=[dict(market=m,trade_price=100,acc_trade_price_24h=1e8-i,signed_change_rate=.01,timestamp=1000000) for i,m in enumerate(markets)]
        def signal(market):
            i=markets.index(market); calls.append(market)
            p=self.signal(); p.update(trend=i<up,strategy_pass=i<up,legacy_pass=i<up)
            return i<up,55.,i<up,'' if i<up else '추세 미충족',p
        original=a.paper.buy
        def buy(*args,**kwargs):
            bought_after.append(len(calls)); return original(*args,**kwargs)
        with patch.object(a.market,'universe',return_value=rows), patch.object(a.market,'clock',return_value=1000), \
             patch.object(a.market,'quotes',side_effect=lambda ms:{m:100 for m in ms}), \
             patch.object(a.market,'holding_quotes',side_effect=lambda ms:({m:100 for m in ms},[])), \
             patch.object(a,'entry_signal',side_effect=signal), patch.object(a.paper,'buy',side_effect=buy):
            a.trade_loop()
        return calls,bought_after

    def test_full_market_sample_precedes_any_main_entry(self):
        calls,bought_after=self.run_sample_loop(12)
        self.assertEqual(len(calls),12); self.assertTrue(bought_after)
        self.assertTrue(all(n==12 for n in bought_after))
        self.assertEqual(len(self.a.paper.state['positions']),3)

    def test_bear_blocks_main_but_reference_keeps_old_signals(self):
        calls,bought_after=self.run_sample_loop(3)
        self.assertEqual(bought_after,[])
        self.assertEqual(self.a.paper.state['positions'],{})
        self.assertTrue(self.a.reference.state['positions'])

if __name__=='__main__': unittest.main()
