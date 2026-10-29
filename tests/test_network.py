import unittest
from network_guard import NetworkGuard
from market_data import MarketData,MarketDataError

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.t=0; self.events=[]
        self.g=NetworkGuard(lambda k,v:self.events.append((k,v)),clock=lambda:self.t,wall=lambda:'2026-10-22T12:00:00+09:00')
    def ready(self): self.g.confirm_cycle(); self.t+=5; self.g.confirm_cycle()
    def test_start_locked(self): self.assertFalse(self.g.can_enter())
    def test_two_spaced_confirmations(self):
        self.assertFalse(self.g.confirm_cycle()); self.assertFalse(self.g.confirm_cycle())
        self.t=5; self.assertTrue(self.g.confirm_cycle()); self.assertTrue(self.g.can_enter())
    def test_failure_resets(self):
        self.ready(); self.g.fail('DNS','unavailable'); self.assertFalse(self.g.can_enter())
        self.t+=5; self.assertFalse(self.g.confirm_cycle()); self.t+=5; self.assertTrue(self.g.confirm_cycle())
    def test_stale_blocks(self):
        self.ready(); self.t+=46; self.assertFalse(self.g.can_enter()); self.assertEqual(self.g.snapshot()['state'],'stale')
    def test_confirm_after_long_gap_restarts_recovery(self):
        self.ready(); self.t+=46; self.assertFalse(self.g.confirm_cycle())
    def test_error_throttle_and_durations(self):
        self.g.fail('DNS','bad')
        for _ in range(20): self.g.fail('DNS','bad')
        self.assertEqual(sum(k=='network_error' for k,v in self.events),1)
        self.t=61; self.g.fail('DNS','bad'); self.assertEqual(sum(k=='network_error' for k,v in self.events),2)
        self.t=70; self.g.confirm_cycle(); self.t=75; self.g.confirm_cycle()
        recovered=[v for k,v in self.events if k=='recovered'][-1]
        self.assertEqual(recovered['observed_duration_seconds'],75)
    def test_restart_needs_new_confirmation(self):
        self.ready(); newer=NetworkGuard(lambda *args:None)
        self.assertFalse(newer.can_enter())


class Response:
    def __init__(self,data,error=None): self.data=data; self.error=error
    def json(self): return self.data
    def raise_for_status(self):
        if self.error: raise self.error

class MarketTests(unittest.TestCase):
    def client(self,rows): return MarketData(get=lambda *a,**kw:Response(rows),clock=lambda:1000,sleep=lambda _:None)
    def row(self,market='KRW-X',timestamp=1000000,price=100):
        return dict(market=market,timestamp=timestamp,trade_price=price)
    def test_fresh(self): self.assertEqual(self.client([]).validate_quote(self.row()),100)
    def test_stale(self):
        with self.assertRaises(MarketDataError): self.client([]).validate_quote(self.row(timestamp=800000))
    def test_future(self):
        with self.assertRaises(MarketDataError): self.client([]).validate_quote(self.row(timestamp=1100000))
    def test_nan_and_zero(self):
        for p in (float('nan'),0,float('inf')):
            with self.assertRaises(MarketDataError): self.client([]).validate_quote(self.row(price=p))
    def test_missing_market(self):
        with self.assertRaises(MarketDataError): self.client([self.row()]).quotes(['KRW-X','KRW-Y'])
    def test_fresh_subset_for_exit(self):
        quotes,errors=self.client([self.row(),self.row('KRW-Y',timestamp=100)]).holding_quotes(['KRW-X','KRW-Y'])
        self.assertEqual(quotes,{'KRW-X':100}); self.assertTrue(errors)
    def test_empty_response(self):
        with self.assertRaises(MarketDataError): self.client([]).universe()
    def test_timeout_is_explicit(self):
        kwargs=[]
        def get(*a,**kw): kwargs.append(kw); return Response([self.row()])
        m=MarketData(get=get,clock=lambda:1000); m.quotes(['KRW-X'])
        self.assertEqual(kwargs[0]['timeout'],(4,8))
    def test_http_error_propagates(self):
        m=MarketData(get=lambda *a,**k:Response([],RuntimeError('429')))
        with self.assertRaises(MarketDataError): m.universe()

if __name__=='__main__': unittest.main()
