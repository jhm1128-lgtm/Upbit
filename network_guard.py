"""Fail-closed entry gate. Fresh exit quotes remain usable during recovery."""
import threading
import time
from datetime import datetime,timezone,timedelta


def now_stamp(): return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')


class NetworkGuard:
    def __init__(self,emit,clock=time.monotonic,wall=now_stamp,stale_seconds=45):
        self.emit=emit; self.clock=clock; self.wall=wall; self.stale_seconds=stale_seconds
        self.lock=threading.RLock()
        self.state='checking'; self.count=0; self.last_success=None; self.last_mono=None
        self.last_confirm=None; self.outage_start=None; self.outage_mono=None
        self.failure_count=0; self.reason='시작 후 통신 확인 필요'
        self.last_error_log=None

    def fail(self,scope,error):
        with self.lock:
            now=self.clock(); self.failure_count+=1
            self.state='offline'
            self.reason=f'{scope}: {str(error)[:300]}'
            self.count=0; self.last_confirm=None
            if self.outage_start is None:
                self.outage_start=self.wall(); self.outage_mono=now
                self.emit('outage_start',dict(started=self.outage_start,reason=self.reason))
            if self.last_error_log is None or now-self.last_error_log>=60:
                self.emit('network_error',dict(reason=self.reason,failures=self.failure_count))
                self.last_error_log=now
            self.state='offline'

    def confirm_cycle(self):
        with self.lock:
            now=self.clock()
            if self.last_mono is not None and now-self.last_mono>self.stale_seconds:
                self.fail('신선도','정상 종합 확인 후 45초 초과')
            self.last_success=self.wall(); self.last_mono=now
            if self.last_confirm is None or now-self.last_confirm>=5:
                self.count+=1; self.last_confirm=now
            if self.count<2:
                if self.state!='recovering':
                    self.emit('recovery_check',dict(successes=self.count,required=2))
                self.state='recovering'; return False
            previous=self.state; self.state='healthy'; self.reason='정상 확인'
            if previous!='healthy':
                self.emit('recovered',dict(started=self.outage_start,ended=self.wall(),
                    observed_duration_seconds=None if self.outage_mono is None else max(0,now-self.outage_mono),
                    successes=self.count,failures=self.failure_count))
                self.outage_start=None; self.outage_mono=None
            return True

    def snapshot(self):
        with self.lock:
            age=None if self.last_mono is None else max(0,self.clock()-self.last_mono)
            stale=age is not None and age>self.stale_seconds
            state='stale' if stale and self.state=='healthy' else self.state
            return dict(state=state,entry_allowed=state=='healthy',last_success=self.last_success,
                age_seconds=age,successes=self.count,failures=self.failure_count,reason=self.reason,
                outage_start=self.outage_start)

    def can_enter(self): return self.snapshot()['entry_allowed']
