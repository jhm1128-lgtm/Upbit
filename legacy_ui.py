import os
import json
import time
import threading
from datetime import datetime, date
from zoneinfo import ZoneInfo
import tkinter as tk
from tkinter import ttk, messagebox

import pandas as pd
import pyupbit
from dotenv import load_dotenv

load_dotenv(override=False)
KST = ZoneInfo("Asia/Seoul")
STATE_FILE = "state.json"
LOG_FILE = "trades.csv"

# Strategy defaults
ORDER_KRW = 150_000
MAX_POSITIONS = 3
STOP_LOSS = -0.03
FIRST_TARGET = 0.05
TRAILING_DROP = 0.02
FIRST_SELL_FRACTION = 0.50
MAX_CONSECUTIVE_LOSSES = 3
TOP_MARKETS_TO_SCAN = 15
POLL_SECONDS = 15
FEE_ESTIMATE = 0.0005  # illustrative only; check your actual Upbit fee rate


def now_kst():
    return datetime.now(KST)


def fmt_num(value, digits=2):
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


class UpbitAutoTrader:
    def __init__(self, root):
        self.root = root
        self.root.title("Upbit Auto Trading v1.1")
        self.root.geometry("1280x850")
        self.root.minsize(1050, 700)

        self.access_key = os.getenv("UPBIT_ACCESS_KEY", "").strip()
        self.secret_key = os.getenv("UPBIT_SECRET_KEY", "").strip()
        self.upbit = None
        if self.access_key and self.secret_key:
            try:
                self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)
            except Exception:
                self.upbit = None

        self.running = False
        self.worker = None
        self.live_enabled = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="대기 중 · 실전 주문 잠금")
        self.krw_balance = tk.StringVar(value="조회 전")
        self.loss_streak_var = tk.StringVar(value="0 / 3")
        self.mode_var = tk.StringVar(value="관찰 모드")
        self.last_scan_var = tk.StringVar(value="-")
        self.positions = {}
        self.loss_streak = 0
        self.paused_for_day = False
        self.last_reset_date = now_kst().date().isoformat()
        self.last_entry_time = {}
        self.log_queue = []
        self.candidates = []
        self.candidate_values = {}
        self.trade_rows = []
        self.daily_rows = []
        self.load_state()
        self.build_ui()
        self.refresh_tables()
        self.root.after(1000, self.drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)


    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="UPBIT AUTO TRADING", font=("맑은 고딕", 18, "bold")).pack(side="left")
        ttk.Label(header, text="거래대금 상위 + 추세 + RSI", font=("맑은 고딕", 10)).pack(side="left", padx=20)

        summary = ttk.LabelFrame(self.root, text="계좌 / 위험 관리", padding=10)
        summary.pack(fill="x", padx=12, pady=5)
        for i in range(4):
            summary.columnconfigure(i, weight=1)
        ttk.Label(summary, text="원화 잔고").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.krw_balance, font=("맑은 고딕", 12, "bold")).grid(row=1, column=0, sticky="w")
        ttk.Label(summary, text="연속 손절").grid(row=0, column=1, sticky="w")
        ttk.Label(summary, textvariable=self.loss_streak_var, font=("맑은 고딕", 12, "bold")).grid(row=1, column=1, sticky="w")
        ttk.Label(summary, text="모드").grid(row=0, column=2, sticky="w")
        ttk.Label(summary, textvariable=self.mode_var, font=("맑은 고딕", 12, "bold")).grid(row=1, column=2, sticky="w")
        ttk.Label(summary, text="마지막 스캔").grid(row=0, column=3, sticky="w")
        ttk.Label(summary, textvariable=self.last_scan_var).grid(row=1, column=3, sticky="w")

        controls = ttk.LabelFrame(self.root, text="실행 제어", padding=10)
        controls.pack(fill="x", padx=12, pady=5)
        ttk.Checkbutton(controls, text="실전 주문 활성화 (실제 자금 사용)", variable=self.live_enabled,
                        command=self.on_live_toggle).pack(side="left")
        ttk.Button(controls, text="시작", command=self.start).pack(side="left", padx=8)
        ttk.Button(controls, text="중지", command=self.stop).pack(side="left")
        ttk.Button(controls, text="잔고 새로고침", command=self.refresh_balance).pack(side="left", padx=8)
        ttk.Label(controls, text="1회 150,000원 · 최대 3종목 · 손절 -3% · 1차 +5% · 이후 고점 대비 -2%",
                  foreground="#2457a7").pack(side="left", padx=15)

        ttk.Label(self.root, textvariable=self.status, padding=(14, 6)).pack(fill="x")

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=5)

        # Positions tab
        pos_tab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(pos_tab, text="보유종목")
        cols = ("market", "avg", "price", "pnl", "qty", "target", "peak")
        self.position_tree = ttk.Treeview(pos_tab, columns=cols, show="headings", height=12)
        headings = {"market":"종목", "avg":"평균 매수가", "price":"현재가", "pnl":"수익률(추정)",
                    "qty":"보유 수량", "target":"1차 익절", "peak":"진입 후 최고가"}
        widths = {"market":130, "avg":140, "price":140, "pnl":120, "qty":170, "target":110, "peak":140}
        for c in cols:
            self.position_tree.heading(c, text=headings[c])
            self.position_tree.column(c, width=widths[c], anchor="center")
        self.position_tree.pack(fill="both", expand=True)

        # Trade history tab
        trade_tab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(trade_tab, text="거래내역")
        ttk.Label(trade_tab, text="매수·매도 이벤트가 CSV에 누적 저장됩니다. 손익은 주문 직전 시세 기반 추정치이며 실제 체결 내역과 차이가 날 수 있습니다.",
                  foreground="#8a4b08").pack(anchor="w", pady=(0, 6))
        trade_cols = ("time", "side", "market", "price", "qty", "amount", "pnl", "rate", "reason")
        self.trade_tree = ttk.Treeview(trade_tab, columns=trade_cols, show="headings")
        trade_heads = {"time":"일시", "side":"구분", "market":"종목명", "price":"거래단가",
                       "qty":"수량", "amount":"거래금액", "pnl":"실현손익(추정)", "rate":"수익률", "reason":"사유"}
        trade_widths = {"time":150, "side":65, "market":110, "price":110, "qty":120,
                        "amount":120, "pnl":125, "rate":90, "reason":150}
        for c in trade_cols:
            self.trade_tree.heading(c, text=trade_heads[c])
            self.trade_tree.column(c, width=trade_widths[c], anchor="center")
        self.trade_tree.pack(fill="both", expand=True)

        # Profit summary tab
        pnl_tab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(pnl_tab, text="손익현황")
        filters = ttk.Frame(pnl_tab)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="연도").pack(side="left")
        self.year_filter = tk.StringVar(value="전체")
        self.year_combo = ttk.Combobox(filters, textvariable=self.year_filter, width=8, state="readonly")
        self.year_combo.pack(side="left", padx=(4, 12))
        ttk.Label(filters, text="월").pack(side="left")
        self.month_filter = tk.StringVar(value="전체")
        self.month_combo = ttk.Combobox(filters, textvariable=self.month_filter, width=6, state="readonly")
        self.month_combo.pack(side="left", padx=(4, 12))
        ttk.Label(filters, text="일").pack(side="left")
        self.day_filter = tk.StringVar(value="전체")
        self.day_combo = ttk.Combobox(filters, textvariable=self.day_filter, width=6, state="readonly")
        self.day_combo.pack(side="left", padx=(4, 12))
        ttk.Button(filters, text="조회", command=self.refresh_profit_view).pack(side="left")
        ttk.Button(filters, text="전체 보기", command=self.reset_profit_filters).pack(side="left", padx=6)

        self.pnl_summary_label = ttk.Label(pnl_tab, text="실현손익: 0원   |   거래횟수: 0   |   승률: 0.0%")
        self.pnl_summary_label.pack(anchor="w", pady=(0, 6))
        daily_cols = ("date", "pnl", "rate", "assets", "count", "winrate")
        self.daily_tree = ttk.Treeview(pnl_tab, columns=daily_cols, show="headings", height=10)
        daily_heads = {"date":"일자", "pnl":"당일 실현손익", "rate":"당일 수익률", "assets":"마감자산",
                       "count":"매매횟수", "winrate":"승률"}
        daily_widths = {"date":130, "pnl":160, "rate":130, "assets":160, "count":100, "winrate":100}
        for c in daily_cols:
            self.daily_tree.heading(c, text=daily_heads[c])
            self.daily_tree.column(c, width=daily_widths[c], anchor="center")
        self.daily_tree.pack(fill="both", expand=True)
        ttk.Label(pnl_tab, text="일자별 실현손익 데이터는 daily_pnl.csv에 누적 저장됩니다. 마감자산은 해당 날짜에 조회한 계좌 자산 스냅샷입니다.",
                  foreground="#666").pack(anchor="w", pady=6)

        # Buy candidates tab
        candidate_tab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(candidate_tab, text="매수후보")
        ttk.Label(candidate_tab, text="거래대금 상위 후보 중 5분봉 추세·RSI 조건을 확인합니다. 후보 표시만으로 매수 신호가 확정되는 것은 아닙니다.").pack(anchor="w", pady=(0, 6))
        candidate_cols = ("rank", "market", "value", "price", "signal", "reason")
        self.candidate_tree = ttk.Treeview(candidate_tab, columns=candidate_cols, show="headings")
        candidate_heads = {"rank":"순위", "market":"마켓", "value":"24시간 거래대금", "price":"현재가", "signal":"신호", "reason":"조건"}
        candidate_widths = {"rank":60, "market":130, "value":170, "price":140, "signal":100, "reason":350}
        for c in candidate_cols:
            self.candidate_tree.heading(c, text=candidate_heads[c])
            self.candidate_tree.column(c, width=candidate_widths[c], anchor="center")
        self.candidate_tree.pack(fill="both", expand=True)

        # Logs tab
        log_tab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(log_tab, text="로그")
        self.log_text = tk.Text(log_tab, height=15, wrap="word", state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        footer = ttk.Label(self.root,
            text="주의: 프로그램이 꺼지거나 인터넷이 끊기면 손절/익절 감시가 중단됩니다. 수익은 보장되지 않습니다.",
            foreground="#a33", padding=10)
        footer.pack(fill="x")
        self.refresh_history_views()


    def refresh_history_views(self):
        import csv
        if not hasattr(self, "trade_tree"):
            return
        for tree in (self.trade_tree, self.daily_tree):
            for item in tree.get_children():
                tree.delete(item)
        transactions = []
        if os.path.exists("transactions.csv"):
            try:
                with open("transactions.csv", "r", newline="", encoding="utf-8-sig") as f:
                    transactions = list(csv.DictReader(f))
            except Exception as e:
                self.log(f"거래내역 불러오기 실패: {e}")
        self.trade_rows = transactions
        for r in reversed(transactions[-2000:]):
            self.trade_tree.insert("", "end", values=(
                r.get("time",""), r.get("side",""), r.get("market",""),
                fmt_num(r.get("price", 0), 4), fmt_num(r.get("qty", 0), 8),
                fmt_num(r.get("amount", 0), 0), fmt_num(r.get("realized_pnl_est", 0), 0),
                (fmt_num(r.get("return_pct_est", 0), 2) + "%") if r.get("side") == "매도" else "-",
                r.get("reason","")
            ))
        daily = []
        if os.path.exists("daily_pnl.csv"):
            try:
                with open("daily_pnl.csv", "r", newline="", encoding="utf-8-sig") as f:
                    daily = list(csv.DictReader(f))
            except Exception as e:
                self.log(f"일별 손익 불러오기 실패: {e}")
        self.daily_rows = daily
        years = sorted({r.get("date","")[:4] for r in daily if len(r.get("date","")) >= 4}, reverse=True)
        if hasattr(self, "year_combo"):
            self.year_combo["values"] = ["전체"] + years
            if self.year_filter.get() not in self.year_combo["values"]:
                self.year_filter.set("전체")
            self.month_combo["values"] = ["전체"] + [f"{i:02d}" for i in range(1, 13)]
            self.day_combo["values"] = ["전체"] + [f"{i:02d}" for i in range(1, 32)]
        self.refresh_profit_view()


    def refresh_profit_view(self):
        if not hasattr(self, "daily_tree"):
            return
        for item in self.daily_tree.get_children():
            self.daily_tree.delete(item)
        selected = []
        for r in self.daily_rows:
            d = r.get("date", "")
            if len(d) < 10:
                continue
            if self.year_filter.get() != "전체" and d[:4] != self.year_filter.get():
                continue
            if self.month_filter.get() != "전체" and d[5:7] != self.month_filter.get():
                continue
            if self.day_filter.get() != "전체" and d[8:10] != self.day_filter.get():
                continue
            selected.append(r)
        for r in reversed(selected):
            rate = r.get("return_pct", "")
            rate_text = (fmt_num(rate, 2) + "%") if str(rate).strip() else "기준자산 없음"
            self.daily_tree.insert("", "end", values=(
                r.get("date",""), fmt_num(r.get("realized_pnl", 0), 0) + "원", rate_text,
                fmt_num(r.get("closing_assets", 0), 0) + "원",
                r.get("trade_count", 0), fmt_num(r.get("win_rate_pct", 0), 1) + "%"
            ))
        total = sum(float(r.get("realized_pnl", 0) or 0) for r in selected)
        count = sum(int(float(r.get("trade_count", 0) or 0)) for r in selected)
        wins = sum(float(r.get("win_rate_pct", 0) or 0) * int(float(r.get("trade_count", 0) or 0)) / 100 for r in selected)
        winrate = wins / count * 100 if count else 0
        self.pnl_summary_label.config(text=f"실현손익 합계(추정): {total:,.0f}원   |   매도 거래횟수: {count}   |   승률: {winrate:.1f}%")


    def reset_profit_filters(self):
        self.year_filter.set("전체")
        self.month_filter.set("전체")
        self.day_filter.set("전체")
        self.refresh_profit_view()


