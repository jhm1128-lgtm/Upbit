import csv
import tempfile
import unittest
from pathlib import Path
from paper import Records,Paper
from trade_history import read_history,write_history,net_return_pct,normalize_market,history_markets
from log_view import read_logs,validate_range
from ui_widgets import shift_month

TIME='2026-10-29T10:00:00+09:00'
CONFIG=dict(order_krw=150000,max_positions=3,max_losses=7)

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.records=Records(self.base/'test.sqlite3'); self.paper=Paper(self.records)
    def tearDown(self): self.tmp.cleanup()

    def test_net_return_matches_allocated_cost_for_partial_and_final_sale(self):
        entry=self.paper.buy('KRW-XRP',100,CONFIG,TIME)
        first=self.paper.sell('KRW-XRP',104,entry['qty']/2,'1차 익절',TIME)
        final=self.paper.sell('KRW-XRP',99,entry['qty']/2,'트레일링',TIME)
        for event in (first,final):
            allocated_cost=(entry['funds']+entry['fee'])*event['qty']/entry['qty']
            expected=(event['funds']-event['fee']-allocated_cost)/allocated_cost*100
            self.assertAlmostEqual(net_return_pct(event),expected,places=9)
        self.assertGreater(net_return_pct(first),0); self.assertLess(net_return_pct(final),0)
        self.assertIsNone(net_return_pct(entry))

    def test_invalid_cost_is_blank_instead_of_division_error(self):
        self.assertIsNone(net_return_pct(dict(side='SELL',funds=1,fee=1,pnl=0)))
        self.assertIsNone(net_return_pct(dict(side='SELL',funds=float('nan'),fee=0,pnl=1)))

    def test_symbol_filter_is_exact_and_accepts_short_ticker(self):
        self.paper.buy('KRW-XRP',100,CONFIG,TIME); self.paper.buy('KRW-XRPL',100,CONFIG,TIME)
        rows,summary=read_history(self.records,market=' xrp ')
        self.assertEqual([r['market'] for r in rows],['KRW-XRP']); self.assertEqual(summary['count'],1)
        self.assertEqual(normalize_market('전체'),'')
        self.assertEqual(history_markets(self.records),['KRW-XRP','KRW-XRPL'])

    def test_end_date_includes_last_second_and_excludes_next_day(self):
        self.paper.buy('KRW-XRP',100,CONFIG,'2026-10-29T23:59:59+09:00')
        self.paper.buy('KRW-ETH',100,CONFIG,'2026-10-30T00:00:00+09:00')
        rows,s=read_history(self.records,date_from='2026-10-29',date_to='2026-10-29')
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['market'],'KRW-XRP')

    def test_read_history_and_csv_include_net_return_without_mutating_pnl(self):
        entry=self.paper.buy('KRW-XRP',100,CONFIG,TIME)
        sale=self.paper.sell('KRW-XRP',104,entry['qty'],'트레일링',TIME)
        before=self.records.load()
        rows,s=read_history(self.records); self.assertAlmostEqual(rows[0]['return_pct'],net_return_pct(sale))
        out=self.base/'out.csv'; write_history(self.records,out)
        with out.open(encoding='utf-8-sig',newline='') as f: exported=list(csv.DictReader(f))
        self.assertEqual(exported[0]['return_pct'],'')
        self.assertAlmostEqual(float(exported[1]['return_pct']),net_return_pct(sale))
        self.assertEqual(self.records.load(),before)

class LogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.records=Records(Path(self.tmp.name)/'logs.sqlite3')
        with self.records.db() as db:
            db.executemany('INSERT INTO logs(stamp,kind,message) VALUES(?,?,?)',
                [('2026-10-29T23:59:59+09:00' if i<225 else '2026-10-30T00:00:00+09:00',
                  'error' if i%3==0 else 'info',f'기록 {i}'+(' literal %_' if i==449 else '')) for i in range(450)])
    def tearDown(self): self.tmp.cleanup()

    def test_paging_reaches_all_saved_rows_without_duplicates(self):
        ids=[]; before=None
        while True:
            rows,more=read_logs(self.records,before=before)
            self.assertLessEqual(len(rows),200); ids.extend(r[0] for r in rows)
            if not more: break
            before=rows[-1][0]
        self.assertEqual(len(ids),450); self.assertEqual(len(set(ids)),450)
        self.assertEqual(ids,sorted(ids,reverse=True))

    def test_kind_date_and_literal_keyword_filters(self):
        rows,_=read_logs(self.records,keyword='%_'); self.assertEqual(len(rows),1)
        rows,_=read_logs(self.records,kind='error',start='2026-10-30',end='2026-10-30')
        self.assertEqual(len(rows),75)
        self.assertTrue(all(r[2]=='error' and r[1].startswith('2026-10-30') for r in rows))

    def test_restart_keeps_old_logs(self):
        restored=Records(self.records.path)
        rows,more=read_logs(restored,before=226)
        self.assertTrue(more); self.assertEqual(rows[0][0],225)

    def test_invalid_date_range_is_rejected(self):
        for start,end in [('2026-10-31','2026-10-01'),('2026-02-30','')]:
            with self.assertRaises(ValueError): validate_range(start,end)

class CalendarTests(unittest.TestCase):
    def test_month_and_year_boundary_moves(self):
        self.assertEqual(shift_month(2026,1,-1),(2025,12))
        self.assertEqual(shift_month(2026,12,1),(2027,1))
        self.assertEqual(shift_month(2024,2,12),(2025,2))
        self.assertEqual(shift_month(1,1,-1),(1,1))

if __name__=='__main__': unittest.main()
