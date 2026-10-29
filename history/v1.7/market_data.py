"""Public REST only: bounded requests, fresh timestamps, no order credentials."""
import math
import time
import threading
import requests
import pandas as pd


class MarketDataError(RuntimeError): pass
class CandleHistoryError(ValueError): pass


class MarketData:
    def __init__(self,get=requests.get,clock=time.time,mono=time.monotonic,sleep=time.sleep):
        self.get=get; self.clock=clock; self.mono=mono; self.sleep=sleep
        self.lock=threading.Lock(); self.previous=None

    def fetch(self,path,params):
        # Serialize strategy/portfolio public requests. Display charts are independent.
        with self.lock:
            if self.previous is not None:
                delay=.16-(self.mono()-self.previous)
                if delay>0: self.sleep(delay)
            self.previous=self.mono()
            try:
                response=self.get('https://api.upbit.com/v1/'+path,params=params,timeout=(4,8))
                response.raise_for_status(); data=response.json()
            except Exception as e: raise MarketDataError(f'{type(e).__name__}: {str(e)[:240]}') from e
        if not isinstance(data,list) or not data: raise MarketDataError('빈 응답/응답 형식 오류')
        return data

    def validate_quote(self,row):
        try:
            price=float(row['trade_price']); source=float(row['timestamp'])/1000
            if not math.isfinite(price) or price<=0 or not math.isfinite(source): raise ValueError('수치 오류')
            age=self.clock()-source
            if age>90 or age < -10: raise ValueError(f'시세 시각 불일치 ({age:.1f}초)')
            return price
        except (KeyError,TypeError,ValueError) as e: raise MarketDataError(str(e)) from e

    def universe(self): return self.fetch('ticker/all',{'quote_currencies':'KRW'})

    def quotes(self,markets):
        result,errors=self.holding_quotes(markets)
        if errors: raise MarketDataError('; '.join(errors))
        return result

    def holding_quotes(self,markets):
        if not markets:return {},[]
        rows=self.fetch('ticker',{'markets':','.join(markets)})
        result={}; errors=[]
        for row in rows:
            if row.get('market') in markets:
                try: result[row['market']]=self.validate_quote(row)
                except MarketDataError as e: errors.append(f"{row['market']}: {e}")
        missing=set(markets)-set(result)
        if missing: errors.append('요청 시세 누락: '+','.join(sorted(missing)))
        return result,errors

    def candles(self,market,count=80):
        rows=self.fetch('candles/minutes/5',{'market':market,'count':count})
        try:
            frame=pd.DataFrame([dict(stamp=r['candle_date_time_kst'],open=float(r['opening_price']),
                high=float(r['high_price']),low=float(r['low_price']),close=float(r['trade_price']),
                volume=float(r['candle_acc_trade_volume'])) for r in rows])
            frame.index=pd.to_datetime(frame.pop('stamp'))
            return frame.sort_index()
        except Exception as e: raise MarketDataError('캔들 응답 형식 오류') from e
