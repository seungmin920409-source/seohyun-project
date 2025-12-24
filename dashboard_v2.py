# =========================================================
# 이서현 시스템 v2 — Seohyun RSI Dashboard v2 (with ChartEngine)
# 큰 덩어리: 차트가 보이고 RSI 숫자가 움직이는 화면 하나 만들기
# 오늘은 이것에 직접 도움 되는 것만 만진다
# 큰 덩어리: 차트가 보이고 RSI 숫자가 움직이는 화면 하나 만들기
# 오늘은 이것에 직접 도움 되는 것만 만진다
# 큰 덩어리: 차트가 보이고 RSI 숫자가 움직이는 화면 하나 만들기
# 오늘은 이것에 직접 도움 되는 것만 만진다
# =========================================================
# 1.SEC:IMPORTS       기본 import + matplotlib
# 2.SEC:CONSTANTS     버전/폰트/기본값
# 3.SEC:CONFIG        DashboardConfig
# 4.SEC:RUNCONTEXT    DashboardContext
# 5.SEC:HEALTHCHECK   HealthChecker
# 6.SEC:SNAPSHOT      SnapshotManager
# 7.SEC:DATA_PIPELINE DataEngine / IndicatorEngine
# 8.SEC:CHART_ENGINE  ChartEngine (NEW)
# 9.SEC:UI_MAIN       SeohyunDashboard (3패널 + 탭 + 차트탭)
# 10.SEC:ENTRYPOINT   main()

# 큰 덩어리: 차트가 보이고 RSI 숫자가 움직이는 화면 하나 만들기
# 오늘은 이것에 직접 도움 되는 것만 만진다

# =========================================================
# [SEC:IMPORTS] 📦 기본 Import
# =========================================================
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Literal
from datetime import datetime
import time
import matplotlib.ticker as mticker
import requests

import tkinter as tk
from tkinter import ttk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

def is_dev() -> bool:
    # DEV 모드 여부를 반환 (환경변수/설정 등으로 확장 가능)
    import os
    return os.environ.get("SEOHYUN_DEV", "0") == "1"
# =========================================================
# [SEC:CONSTANTS] ⚙️ 상수 / 기본값
# =========================================================
APP_NAME = "Seohyun RSI Dashboard"
APP_VERSION = "2.0.1-chartengine"

DEFAULT_CONFIG_PATH = Path("config_dashboard_v2.json")
DEFAULT_SNAPSHOT_DIR = Path("snapshots")

FONT_NAME = "맑은 고딕"
BACKGROUND_COLOR = "#202020"

DEFAULT_SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
DEFAULT_TIMEFRAMES = ["1", "3", "5", "15", "60"]
DEFAULT_MODE: Literal["DEV_LOCAL", "PAPER", "LIVE"] = "DEV_LOCAL"


# =========================================================
# [SEC:CONFIG] ⚙️ DashboardConfig
# =========================================================
@dataclass
class DashboardConfig:
    """대시보드 기본 설정값 모음."""

    symbols: list[str] = field(default_factory=lambda: DEFAULT_SYMBOLS.copy())
    timeframes: list[str] = field(default_factory=lambda: DEFAULT_TIMEFRAMES.copy())
    mode: str = DEFAULT_MODE

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "DashboardConfig":
        if not path.exists():
            return cls()

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.error("config 로드 실패: %s", e)
            return cls()

        return cls(
            symbols=data.get("symbols", DEFAULT_SYMBOLS),
            timeframes=data.get("timeframes", DEFAULT_TIMEFRAMES),
            mode=data.get("mode", DEFAULT_MODE),
        )


def load_dashboard_config() -> DashboardConfig:
    return DashboardConfig.load()


# =========================================================
# [SEC:RUNCONTEXT] 🧠 DashboardContext
# =========================================================
@dataclass
class DashboardContext:
    """대시보드 전체에서 공유하는 현재 선택 상태."""

    market: str       # 예: "KRW-BTC"
    tf: str           # 예: "1", "5", "60"
    mode: str         # 예: "DEV_LOCAL", "PAPER", "LIVE"
    strategy: str     # 예: "SCALPING", "SWING" 등


# =========================================================
# [SEC:HEALTHCHECK] 🩺 헬스체크 스켈레톤
# =========================================================
class HealthChecker:
    """v2 헬스체크 객체 (뼈대)."""

    def __init__(self, cfg: DashboardConfig) -> None:
        self.cfg = cfg
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def check_config_files(self) -> None:
        """config / snapshot / log 폴더 등 기본 구조 체크."""
        self.infos.append("config 파일 구조 OK (skeleton).")

    def check_api_connectivity(self) -> None:
        """업비트 API 연결, latency 체크."""
        self.infos.append("Upbit API connectivity OK (mock).")

    def run_all(self) -> str:
        """모든 헬스체크를 실행하고 요약 문자열을 반환."""
        self.errors.clear()
        self.warnings.clear()
        self.infos.clear()

        self.check_config_files()
        self.check_api_connectivity()

        if self.errors:
            status = "ERROR"
        elif self.warnings:
            status = "WARN"
        else:
            status = "OK"

        detail = "; ".join(self.infos + self.warnings + self.errors)
        return f"[{status}] {detail or 'no details'}"


# =========================================================
# [SEC:SNAPSHOT] 💾 스냅샷/백업 스켈레톤
# =========================================================
class SnapshotManager:
    """간단한 스냅샷/백업 관리자 (v2 스켈레톤)."""

    def __init__(self, snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> None:
        self.snapshot_dir = snapshot_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def make_snapshot(self, cfg: DashboardConfig, ctx: DashboardContext) -> Path:
        """현재 설정/컨텍스트를 json 으로 덤프."""
        data = {
            "config": {
                "symbols": cfg.symbols,
                "timeframes": cfg.timeframes,
                "mode": cfg.mode,
            },
            "context": {
                "market": ctx.market,
                "tf": ctx.tf,
                "mode": ctx.mode,
                "strategy": ctx.strategy,
            },
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.snapshot_dir / f"snapshot_{ts}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path


# =========================================================
# [SEC:DATA_PIPELINE] 🔗 DataEngine / IndicatorEngine
# =========================================================
class DataEngine:
    """업비트 시세/캔들 데이터를 가져오는 캐시 엔진."""

    def __init__(self, cfg: DashboardConfig) -> None:
        self.cfg = cfg
        self._cache: dict[tuple[str, str], dict] = {}

    def _fetch_candles_from_api(self, market: str, tf: str, count: int = 200) -> list[dict]:
        """
        업비트 실제 캔들 API 호출.
        - 분봉(tf: "1","3","5","10","15","30","60","240")은 /v1/candles/minutes/{tf}
        - 그 외는 일봉(/days)으로 fallback
        - 최신 → 과거 순서로 내려오는 리스트를, 차트용으로는 과거 → 최신 순으로 reverse
        - 오류 발생 시: 기존 캐시가 있으면 그것을 반환, 없으면 빈 리스트
        """
        base_url = "https://api.upbit.com/v1/candles"

        tf_str = str(tf).upper().strip()
        if tf_str in {"1", "3", "5", "10", "15", "30", "60", "240"}:
            url = f"{base_url}/minutes/{int(tf_str)}"
            params = {"market": market, "count": count}
        else:
            url = f"{base_url}/days"
            params = {"market": market, "count": count}

        try:
            resp = requests.get(url, params=params, timeout=3.0)
        except Exception as e:
            logging.error("캔들 요청 실패(네트워크): market=%s tf=%s err=%s", market, tf, e)
            return self._cache.get((market, tf), {}).get("candles", [])

        if resp.status_code != 200:
            logging.error(
                "캔들 요청 실패[HTTP %s]: url=%s params=%s body=%s",
                resp.status_code,
                url,
                params,
                resp.text[:200],
            )
            return self._cache.get((market, tf), {}).get("candles", [])

        try:
            data = resp.json()
        except Exception as e:
            logging.error("캔들 응답 JSON 파싱 실패: %s", e)
            return self._cache.get((market, tf), {}).get("candles", [])

        if not isinstance(data, list):
            logging.error("캔들 응답 형식 이상: %r", data)
            return self._cache.get((market, tf), {}).get("candles", [])

        # 최신 → 과거 → reverse 해서 과거 → 최신
        candles: list[dict] = list(reversed(data))
        return candles

    def refresh_all(self, market: str, tfs: list[str]) -> None:
        """주기적으로 현재 선택 심볼에 대해 여러 타임프레임 캔들 갱신.
        - 캐시에 fetch_ok / fetch_error를 반드시 기록해서
        UI에서 NO DATA 원인 3분리(CACHE MISS / HTTP FAIL / BAD VALUES)가 가능해진다.
        """
        for tf in tfs:
            fetch_ok = False
            fetch_error: str | None = None
            candles: list[dict] = []

            try:
                candles = self._fetch_candles_from_api(market, tf)
                fetch_ok = True
            except Exception as e:
                fetch_ok = False
                fetch_error = f"{type(e).__name__}: {e}"
                logging.error("캔들 조회 오류: market=%s tf=%s err=%s", market, tf, fetch_error)

            # ✅ 항상 캐시 엔트리를 남긴다 (MISS/FAIL/OK 모두 추적)
            self._cache[(market, tf)] = {
                "candles": candles,
                "last_refresh": datetime.now(),
                "fetch_ok": fetch_ok,
                "fetch_error": fetch_error,
            }


    def get(self, market: str, tf: str) -> dict | None:
        """특정 심볼/타임프레임의 캐시된 데이터 반환."""
        return self._cache.get((market, tf))


def calc_rsi(closes: list[float], period: int = 14) -> float | None:
    """단순 RSI 계산 (Wilder 방식 근사)."""
    if len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)


class IndicatorEngine:
    """DataEngine으로부터 지표(RSI/MACD/Trend)를 계산하는 엔진."""

    def __init__(self, data_engine: "DataEngine") -> None:
        self._data_engine = data_engine

    # ---------- 안전 float 변환 ----------
    def _to_float(self, val):
        """
        float 변환을 시도하고, 실패하면 None을 반환한다.
        Upbit API의 None, '', '0E-8' 같은 값도 안전하게 처리.
        """
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _get_closes(self, market: str, tf: str) -> list[float] | None:
        data = self._data_engine.get(market, tf)
        if not data or "candles" not in data:
            return None

        candles: list[dict] = data["candles"]  # type: ignore[assignment]
        closes: list[float] = []

        for c in candles:
            v = self._to_float(c.get("trade_price"))
            if v is None:
                # 깨진 값(None, '', 이상한 문자열)은 스킵
                continue
            closes.append(v)

        return closes or None

    def rsi(self, market: str, tf: str, period: int = 14) -> float | None:
        closes = self._get_closes(market, tf)
        if closes is None:
            return None
        return calc_rsi(closes, period=period)

    def macd(
        self,
        market: str,
        tf: str,
        short: int = 12,
        long: int = 26,
        signal: int = 9,
    ) -> tuple[float, float, float] | None:
        closes = self._get_closes(market, tf)
        if closes is None:
            return None

        def ema(vals: list[float], period: int) -> list[float]:
            k = 2 / (period + 1)
            ema_vals: list[float] = []
            prev: float | None = None
            for v in vals:
                if prev is None:
                    prev = v
                else:
                    prev = v * k + prev * (1 - k)
                ema_vals.append(prev)
            return ema_vals

        ema_short = ema(closes, short)
        ema_long = ema(closes, long)
        macd_line = [s - lg for s, lg in zip(ema_short, ema_long)]
        signal_line = ema(macd_line, signal)
        hist = macd_line[-1] - signal_line[-1]
        return macd_line[-1], signal_line[-1], hist

    def trend_score(self, market: str, tf: str) -> float | None:
        closes = self._get_closes(market, tf)
        if closes is None or len(closes) < 10:
            return None

        xs = list(range(len(closes)))
        ys = closes
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs) or 1.0
        slope = num / den

        raw_score = 50 + slope * 1000
        return max(0.0, min(100.0, raw_score))


# =========================================================
# [SEC:CHART_ENGINE] 📈 ChartEngine (NEW)
# =========================================================
class ChartEngine:
    """
    캔들 + MACD + RSI 3분할 차트를 전담하는 엔진.
    - Figure, Axes, Canvas 내부에서 관리
    - Dashboard는 update()에 캔들/심볼/TF만 넘겨주면 됨
    """

    def __init__(self) -> None:
        self.fig: Figure | None = None
        self.ax_price = None
        self.ax_macd = None
        self.ax_rsi = None
        self.canvas: FigureCanvasTkAgg | None = None
        self._status_artist = None

        # ↙ 차트 안 상태 텍스트(한 줄)를 관리하는 핸들
        self._status_artist = None

    # ---------- 숫자 단위 축약 포맷 ----------
    def _shorten_number(self, value, pos=None):
        abs_value = abs(value)

        if abs_value >= 1_000_000_000:
            return f"{value/1_000_000_000:.2f}B"
        elif abs_value >= 1_000_000:
            return f"{value/1_000_000:.2f}M"
        elif abs_value >= 1_000:
            return f"{value/1_000:.2f}K"
        else:
            return f"{value:.0f}"

    # ---------- 안전 float 변환 ----------
    def _to_float(self, val):
        """
        float 변환을 시도하고, 실패하면 None을 반환한다.
        Upbit API의 None, '', '0E-8' 같은 값도 안전하게 처리.
        """
        try:
            if val is None:
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    # ---------- 초기화 / 부착 ----------
    def init_figure(self) -> None:
        if self.fig is not None:
            return

        # Figure & 3분할 레이아웃 생성
        fig = Figure(figsize=(6, 4), dpi=100)
        fig.patch.set_facecolor("#151515")  # 🔥 이 줄 추가 (figure 전체 배경
        gs = fig.add_gridspec(3, 1, height_ratios=[5, 2, 2], hspace=0.05)

        ax_price = fig.add_subplot(gs[0])
        ax_macd = fig.add_subplot(gs[1], sharex=ax_price)
        ax_rsi = fig.add_subplot(gs[2], sharex=ax_price)

        self.fig = fig
        self.ax_price = ax_price
        self.ax_macd = ax_macd
        self.ax_rsi = ax_rsi


        # 🔹아래쪽 여백 확보 (RSI 시간 라벨 안 잘리게)
        self.fig.subplots_adjust(
            left=0.01,
            right=0.90,
            top=0.96,
            bottom=0.25,   # 너무 작으면 0.25까지 올려도 됨
        )

    def attach(self, master: ttk.Frame) -> None:
        """Tk Frame에 Canvas를 부착."""
        if self.fig is None:
            self.init_figure()
        if self.canvas is not None:
            return

        self.canvas = FigureCanvasTkAgg(self.fig, master=master)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------- 스타일 ----------
    def _style_axes(self) -> None:
        if self.ax_price is None or self.ax_macd is None or self.ax_rsi is None:
            return

        # 공통 스타일
        for ax in (self.ax_price, self.ax_macd, self.ax_rsi):
            ax.set_facecolor("#151515")
            ax.grid(True, color="white", alpha=0.15, linewidth=0.5)
            ax.tick_params(colors="white", labelsize=8)

        # 상단 두 축은 x축 라벨 숨김
        self.ax_price.tick_params(axis="x", which="both", labelbottom=False)
        self.ax_macd.tick_params(axis="x", which="both", labelbottom=False)

        # RSI y축 라벨
        self.ax_rsi.set_ylabel("RSI", color="white", fontsize=8)

        # RSI 축에는 x축 라벨 표시 (공유 x축이기 때문에 여기만 켬)
        self.ax_rsi.tick_params(axis="x", which="both", labelbottom=True)
        for lbl in self.ax_rsi.get_xticklabels():
            lbl.set_visible(True)

        # 🔥 마지막에 y축을 모두 오른쪽으로 고정
        self._fix_axes_y_right()

    # ---------- Y축을 항상 오른쪽에 두는 설정 ----------
    def _fix_axes_y_right(self) -> None:
        # 가격 차트
        if self.ax_price is not None:
            self.ax_price.yaxis.tick_right()
            self.ax_price.yaxis.set_label_position("right")

        # MACD
        if self.ax_macd is not None:
            self.ax_macd.yaxis.tick_right()
            self.ax_macd.yaxis.set_label_position("right")

        # RSI
        if self.ax_rsi is not None:
            self.ax_rsi.yaxis.tick_right()
            self.ax_rsi.yaxis.set_label_position("right")

    # ---------- 업데이트 ----------
    def update(
        self,
        candles: list[dict],
        market: str,
        tf: str,
        last_refresh: datetime | None,
    ) -> str:
        """
        캔들 리스트로부터 캔들+MACD+RSI를 모두 그린 뒤
        상태 문자열을 반환한다.
        """
        if self.fig is None or self.ax_price is None:
            self.init_figure()

        # 축이 아직 제대로 준비 안 되어 있으면 안전하게 종료
        if self.ax_price is None or self.ax_macd is None or self.ax_rsi is None:
            return "차트: 축 초기화 실패"

        if not candles:
            return "차트: 캔들 데이터 없음"

        # 최근 N개만 사용
        N = 120
        candles_slice = candles[-N:]

        xs = list(range(len(candles_slice)))
        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []

        # 시간 라벨용
        times: list[str] = []

        for c in candles_slice:
            o = self._to_float(c.get("opening_price"))
            h = self._to_float(c.get("high_price"))
            low = self._to_float(c.get("low_price"))
            p = self._to_float(c.get("trade_price"))

            # 하나라도 깨지면 그 캔들은 스킵
            if o is None or h is None or low is None or p is None:
                continue

            opens.append(o)
            highs.append(h)
            lows.append(low)
            closes.append(p)

            # KST 기준 시간 문자열 (HH:MM)
            t_raw = c.get("candle_date_time_kst") or c.get("candle_date_time_utc")
            if isinstance(t_raw, str) and len(t_raw) >= 16:
                times.append(t_raw[11:16])  # "YYYY-MM-DDTHH:MM:SS" -> "HH:MM"
            else:
                times.append("")

        # 🔹 유효한 캔들이 하나도 없으면 종료
        if not closes:
            return "차트: 유효한 캔들 데이터 없음"

        # Axes 초기화 및 스타일 재적용
        self.ax_price.clear()
        self.ax_macd.clear()
        self.ax_rsi.clear()
        self._style_axes()

        # ----- 가격(캔들) -----
        num_candles = len(closes)

        # 캔들 개수에 따라 몸통/심지 굵기 자동 조절
        body_width = min(6.0, max(1.0, 240 / max(1, num_candles)))
        wick_width = max(0.5, body_width * 0.35)

        for i, (o, h, low, c) in enumerate(zip(opens, highs, lows, closes)):
            color = "#4DFF88" if c >= o else "#FF4D4D"

            # 심지
            self.ax_price.vlines(i, low, h, color=color, linewidth=wick_width)
            # 몸통
            self.ax_price.vlines(i, o, c, color=color, linewidth=body_width)

        # 루프 밖에서 한 번만
        self.ax_price.set_title(f"{market} / TF {tf}", color="white", fontsize=9)
        self.ax_price.margins(x=0.01, y=0.08)

        # ----- x축 라벨 (RSI 축에만) -----
        if times:
            step = max(1, len(times) // 8)
            tick_idx = list(range(0, len(times), step))

            tick_labels = [
                (times[i] if times[i] else "-")
                for i in tick_idx
            ]

            self.ax_rsi.set_xticks(tick_idx)
            self.ax_rsi.set_xticklabels(
                tick_labels,
                rotation=0,
                fontsize=7,
                color="white",
            )
            # 혹시라도 비활성화 되어 있으면 다시 한 번 강제
            self.ax_rsi.tick_params(axis="x", which="both", labelbottom=True, pad=10)

        # ----- MACD -----
        def ema(vals: list[float], period: int) -> list[float]:
            k = 2 / (period + 1)
            ema_vals: list[float] = []
            prev: float | None = None
            for v in vals:
                if prev is None:
                    prev = v
                else:
                    prev = v * k + prev * (1 - k)
                ema_vals.append(prev)
            return ema_vals

        macd_line = []
        signal_line = []
        hist_vals = []
        xs_macd: list[int] = []

        if len(closes) >= 35:
            ema_short = ema(closes, 12)
            ema_long = ema(closes, 26)
            macd_raw = [s - lg for s, lg in zip(ema_short, ema_long)]
            signal_raw = ema(macd_raw, 9)

            min_len = min(len(macd_raw), len(signal_raw), len(xs))
            macd_line = macd_raw[-min_len:]
            signal_line = signal_raw[-min_len:]
            hist_vals = [m - s for m, s in zip(macd_line, signal_line)]
            xs_macd = xs[-min_len:]

            # MACD 라인
            self.ax_macd.plot(
                xs_macd,
                macd_line,
                linewidth=1.0,
                color="#4DA6FF",   # 밝은 파랑
                label="MACD",
            )

            # Signal 라인
            self.ax_macd.plot(
                xs_macd,
                signal_line,
                linewidth=1.0,
                color="#FFD166",   # 연한 노랑
                label="Signal",
            )

            # ---------- MACD 히스토그램 양/음 분리 ----------
            colors = [
                "#4DA6FF" if h >= 0 else "#FF6B6B"
                for h in hist_vals
            ]

            self.ax_macd.bar(
                xs_macd,
                hist_vals,
                width=0.6,
                color=colors,
                alpha=0.8,
            )

            # 🔹 MACD 축: 0을 기준으로 위·아래 대칭 범위 잡기
            all_macd_vals = macd_line + signal_line + hist_vals
            if all_macd_vals:
                max_abs = max(abs(v) for v in all_macd_vals) or 1.0
                self.ax_macd.set_ylim(-max_abs * 1.1, max_abs * 1.1)

            # 0 기준선
            self.ax_macd.axhline(0, linewidth=0.5, color="#777777", alpha=0.7)

            # y축 눈금 개수 5개 정도로 정리
            self.ax_macd.yaxis.set_major_locator(mticker.MaxNLocator(5))

            # 작은 범례
            self.ax_macd.legend(loc="upper left", fontsize=7)


        # ----- RSI -----
        rsi_vals: list[float] = []
        if len(closes) >= 15:
            gains: list[float] = []
            losses: list[float] = []
            for i in range(1, len(closes)):
                diff = closes[i] - closes[i - 1]
                if diff >= 0:
                    gains.append(diff)
                    losses.append(0.0)
                else:
                    gains.append(0.0)
                    losses.append(-diff)

            period = 14
            if len(gains) >= period:
                avg_gain = sum(gains[:period]) / period
                avg_loss = sum(losses[:period]) / period
                rsis: list[float] = []
                if avg_loss == 0:
                    rsis.append(100.0)
                else:
                    rs = avg_gain / avg_loss
                    rsis.append(100 - (100 / (1 + rs)))

                for i in range(period, len(gains)):
                    avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                    avg_loss = (avg_loss * (period - 1) + losses[i]) / period
                    if avg_loss == 0:
                        rsis.append(100.0)
                    else:
                        rs = avg_gain / avg_loss
                        rsis.append(100 - (100 / (1 + rs)))

                rsi_vals = rsis

        if rsi_vals:
            min_len_rsi = min(len(rsi_vals), len(xs))
            rsi_to_plot = rsi_vals[-min_len_rsi:]
            xs_rsi = xs[-min_len_rsi:]

            # RSI 라인
            self.ax_rsi.plot(
                xs_rsi,
                rsi_to_plot,
                linewidth=1.0,
                color="#C792EA",   # 은은한 연보라
            )
            # 기준선
            self.ax_rsi.axhline(30, linestyle="--", linewidth=0.5)
            self.ax_rsi.axhline(50, linestyle=":", linewidth=0.5, alpha=0.7)
            self.ax_rsi.axhline(70, linestyle="--", linewidth=0.5)
            self.ax_rsi.set_ylim(0, 100)

            # 🔥 RSI 존 음영: 과매도(0~30), 과매수(70~100)
            self.ax_rsi.axhspan(0, 30, color="#4DFF88", alpha=0.05)
            self.ax_rsi.axhspan(70, 100, color="#FF6B6B", alpha=0.05)

            # 🔹 y축 눈금 고정: 0 / 30 / 50 / 70 / 100
            self.ax_rsi.set_yticks([0, 30, 50, 70, 100])

        # 🔎 디버그용으로 한 번은 라벨이 살아있는지 확인하고 싶으면:
        # self.ax_rsi.set_xlabel("TIME", color="yellow")

        # 🔹 last_refresh 텍스트 만들기
        if isinstance(last_refresh, datetime):
            ts_text = last_refresh.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_text = str(last_refresh)

        # ---------- 차트 안 하단 상태 텍스트 표시 ----------
        status_text = f"{market} / TF {tf} | {len(candles_slice)} candles | last={ts_text}"

        if self.ax_price is not None:
            # 이전에 그려진 텍스트가 있으면 지우기
            if self._status_artist is not None:
                try:
                    self._status_artist.remove()
                except Exception:
                    pass

            # 새 텍스트 추가 (가격 축 기준, 아래쪽 바깥 여백에 살짝)
            self._status_artist = self.ax_price.text(
                0.01, -0.12,
                status_text,
                transform=self.ax_price.transAxes,
                fontsize=7,
                color="#BBBBBB",
                alpha=0.8,
                va="top",
            )

        # 실제 그리기
        if self.canvas is not None:
            self.canvas.draw_idle()

        return f"차트 OK — {market} / TF {tf} / 캔들 {len(candles_slice)}개 / last_refresh={ts_text}"


# =========================================================
# [SEC:UI_MAIN] 🖥️ 메인 대시보드
# =========================================================
class SeohyunDashboard(tk.Tk):
    """이서현 시스템 v2 메인 대시보드."""

    def __init__(
        self,
        cfg: Optional[DashboardConfig] = None,
        ctx: Optional[DashboardContext] = None,
    ) -> None:
        super().__init__()

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1200x700")
        self.configure(bg=BACKGROUND_COLOR)

        if cfg is None:
            cfg = load_dashboard_config()
        self.cfg = cfg

        if ctx is None:
            ctx = DashboardContext(
                market=self.cfg.symbols[0],
                tf=self.cfg.timeframes[0],
                mode=self.cfg.mode,
                strategy="SCALPING",
            )
        self.ctx = ctx

        # 백엔드
        self.health_checker = HealthChecker(self.cfg)
        self.snapshot_manager = SnapshotManager()
        self.data_engine = DataEngine(self.cfg)
        self.indicator_engine = IndicatorEngine(self.data_engine)

        # Tk 변수들
        self.var_symbol = tk.StringVar(value=self.ctx.market)
        self.var_tf     = tk.StringVar(value=self.ctx.tf)
        self.var_mode   = tk.StringVar(value=self.ctx.mode)
        self.var_strategy = tk.StringVar(value=self.ctx.strategy)

        # RSI 상태
        self.var_rsi_value  = tk.StringVar(value="-")
        self.var_rsi_status = tk.StringVar(value="차트 준비 중...")

        # 🔹 실시간 상태 박스에서 쓰는 상태 변수들
        self.var_chart_status = tk.StringVar(value="차트 준비 중...")
        self.var_data_status  = tk.StringVar(value="데이터 상태: -")

        # 🔹 게이지 탭용 RSI 변수
        self.var_gauge_rsi = tk.DoubleVar(value=0.0)     # 0~100 값
        self.var_gauge_rsi_text = tk.StringVar(value="-")  # "51.7 (중립)" 같은 텍스트

        # 헬스체크 결과 표시용
        self.var_health = tk.StringVar(value="헬스체크 준비 중...")

        # Score 탭 변수(필요시 사용)
        self.var_score_rsi = tk.StringVar(value="-")
        self.var_score_macd = tk.StringVar(value="-")
        self.var_score_trend = tk.StringVar(value="-")

        # 🔹 실시간 데이터 상태 텍스트 (UI 왼쪽 '실시간 상태' 박스에서 사용)
        self.var_data_status = tk.StringVar(value="데이터 상태: -")

        # ChartEngine
        self.chart_engine = ChartEngine()
        self._last_chart_redraw_ts: float | None = None

        # UI 구성
        self._build_menu()
        self._build_layout()
        self._build_tabs()

        # 초기 헬스체크
        self._run_initial_healthcheck()

        # 루프 시작
        self._start_data_refresh_loop()
        self._start_ui_refresh_loop()


    # ---------- 메뉴 ----------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="스냅샷 저장", command=self._on_save_snapshot)
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self.destroy)
        menubar.add_cascade(label="파일", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="정보", command=self._on_show_about)
        menubar.add_cascade(label="도움말", menu=help_menu)

        self.config(menu=menubar)

    # ---------- 레이아웃 ----------
    def _build_layout(self) -> None:
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=6, pady=6)

        root.columnconfigure(0, weight=2)
        root.columnconfigure(1, weight=5)
        root.columnconfigure(2, weight=3)
        root.rowconfigure(0, weight=1)

        self.left_panel = ttk.Frame(root)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self.center_panel = ttk.Frame(root)
        self.center_panel.grid(row=0, column=1, sticky="nsew", padx=4)

        self.right_panel = ttk.Frame(root)
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        self._build_left_panel()
        self._build_right_panel()

    def _build_left_panel(self) -> None:
        frame = self.left_panel

        ttk.Label(frame, text="심볼", font=(FONT_NAME, 10, "bold")).pack(
            anchor="w", padx=4, pady=(4, 2)
        )
        ttk.Combobox(
            frame,
            textvariable=self.var_symbol,
            values=self.cfg.symbols,
            state="readonly",
            width=15,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        ttk.Label(frame, text="타임프레임", font=(FONT_NAME, 10, "bold")).pack(
            anchor="w", padx=4, pady=(8, 2)
        )
        ttk.Combobox(
            frame,
            textvariable=self.var_tf,
            values=self.cfg.timeframes,
            state="readonly",
            width=15,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        ttk.Label(frame, text="모드", font=(FONT_NAME, 10, "bold")).pack(
            anchor="w", padx=4, pady=(8, 2)
        )
        ttk.Combobox(
            frame,
            textvariable=self.var_mode,
            values=["DEV_LOCAL", "PAPER", "LIVE"],
            state="readonly",
            width=15,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        ttk.Label(frame, text="전략", font=(FONT_NAME, 10, "bold")).pack(
            anchor="w", padx=4, pady=(8, 2)
        )
        ttk.Entry(frame, textvariable=self.var_strategy, width=18).pack(
            anchor="w", padx=4, pady=(0, 4)
        )

        ttk.Separator(frame).pack(fill="x", padx=4, pady=8)

        ttk.Label(frame, text="헬스체크 결과", font=(FONT_NAME, 10, "bold")).pack(
            anchor="w", padx=4, pady=(4, 2)
        )
        ttk.Label(frame, textvariable=self.var_health, wraplength=160).pack(
            anchor="w", padx=4, pady=(0, 4)
        )

        # =====================================================
        # [SEC:LEFT_STATUS] 실시간 상태 모니터 박스
        #   - DataEngine / Indicator / Chart 상태 한눈에 보기
        # =====================================================
        status_box = ttk.Labelframe(frame, text="실시간 상태", padding=4)
        status_box.pack(fill="x", padx=4, pady=(4, 0))

        row = 0

        # 데이터 상태 (DataEngine)
        ttk.Label(status_box, text="데이터", width=7, anchor="w").grid(
            row=row, column=0, sticky="w"
        )
        ttk.Label(
            status_box,
            textvariable=self.var_data_status,
            font=(FONT_NAME, 9),
            wraplength=160,
            justify="left",
        ).grid(row=row, column=1, sticky="w")
        row += 1

        # RSI 값 (IndicatorEngine)
        ttk.Label(status_box, text="RSI", width=7, anchor="w").grid(
            row=row, column=0, sticky="w", pady=(2, 0)
        )
        ttk.Label(
            status_box,
            textvariable=self.var_rsi_value,
            font=(FONT_NAME, 10, "bold"),
        ).grid(row=row, column=1, sticky="w", pady=(2, 0))
        row += 1

        # 차트 상태 (ChartEngine)
        ttk.Label(status_box, text="차트", width=7, anchor="w").grid(
            row=row, column=0, sticky="w", pady=(2, 0)
        )
        ttk.Label(
            status_box,
            textvariable=self.var_chart_status,
            font=(FONT_NAME, 9),
            wraplength=160,
            justify="left",
        ).grid(row=row, column=1, sticky="w", pady=(2, 0))


    def _build_right_panel(self) -> None:
        frame = self.right_panel

        ttk.Label(frame, text="Auto-Trading Zone", font=(FONT_NAME, 11, "bold")).pack(
            anchor="w", padx=4, pady=(4, 6)
        )

        self.var_auto_trading = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Auto Trading ON/OFF (v2 skeleton)",
            variable=self.var_auto_trading,
            command=self._on_toggle_auto_trading,
        ).pack(anchor="w", padx=4, pady=(0, 8))

        ttk.Label(
            frame,
            text="※ v2에서는 UI만 구성\n※ v3에서 실제 매매 로직 연결 예정",
            justify="left",
        ).pack(anchor="w", padx=4, pady=(0, 4))

    # ---------- Tabs ----------
    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self.center_panel)
        self.tabs.pack(fill="both", expand=True)

        # 차트
        self.tab_chart = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_chart, text="차트")
        self._build_tab_chart(self.tab_chart)

        # 게이지
        self.tab_gauge = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_gauge, text="게이지")
        self._build_tab_gauge(self.tab_gauge)

        # 스코어
        self.tab_score = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_score, text="스코어")
        self._build_tab_score(self.tab_score)

        # 신호
        self.tab_signal = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_signal, text="신호")
        self._build_tab_signal(self.tab_signal)

        # 리스크
        self.tab_risk = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_risk, text="리스크")
        self._build_tab_risk(self.tab_risk)

        # 로그
        self.tab_log = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_log, text="로그")
        self._build_tab_log(self.tab_log)

    # ---- 차트 탭 ----
    def _build_tab_chart(self, frame: ttk.Frame) -> None:

        wrapper = ttk.Frame(frame)
        wrapper.pack(fill="both", expand=True, padx=4, pady=4)

        chart_container = ttk.Frame(wrapper)
        chart_container.pack(fill="both", expand=True)

        status_frame = ttk.Frame(wrapper)
        status_frame.pack(fill="x", side="bottom", pady=(6, 0))

        ttk.Label(
            status_frame,
            textvariable=self.var_chart_status,
            font=(FONT_NAME, 9),
            anchor="w",
        ).pack(fill="x")

        # 🔥 이 줄이 반드시 있어야 차트가 붙음!!
        self.chart_engine.attach(chart_container)

    # ---- 게이지 탭 ----
    def _build_tab_gauge(self, frame: ttk.Frame) -> None:
        wrapper = ttk.Frame(frame)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(
            wrapper,
            text="RSI 게이지 (v2 단계1 — 수치 표시)",
            font=(FONT_NAME, 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(wrapper)
        row.pack(anchor="w")

        ttk.Label(
            row,
            text="RSI(14)",
            font=(FONT_NAME, 10, "bold"),
            width=10,
        ).pack(side="left")

        ttk.Label(
            row,
            textvariable=self.var_rsi_value,
            font=(FONT_NAME, 12, "bold"),
            width=8,
        ).pack(side="left", padx=(8, 8))

        ttk.Label(
            row,
            textvariable=self.var_rsi_status,
            font=(FONT_NAME, 10),
        ).pack(side="left")

        gauge_row = ttk.Frame(wrapper)
        gauge_row.pack(anchor="w", pady=(10, 0))

        style = ttk.Style(self)
        style.configure("RSI.Neutral.Horizontal.TProgressbar")
        style.configure("RSI.Hot.Horizontal.TProgressbar")
        style.configure("RSI.Cold.Horizontal.TProgressbar")

        self.rsi_bar = ttk.Progressbar(
            gauge_row,
            orient="horizontal",
            mode="determinate",
            length=220,
            maximum=100,
            style="RSI.Neutral.Horizontal.TProgressbar",
        )
        self.rsi_bar.pack(side="left", padx=(18, 0))

    # ---- 스코어 탭 ----
    def _build_tab_score(self, frame: ttk.Frame) -> None:
        wrapper = ttk.Frame(frame)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(
            wrapper,
            text="지표 스코어 요약 (v2 1단계)",
            font=(FONT_NAME, 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        grid = ttk.Frame(wrapper)
        grid.pack(anchor="w")

        def add_row(row_idx: int, name: str, var: tk.StringVar) -> None:
            ttk.Label(
                grid,
                text=name,
                font=(FONT_NAME, 10, "bold"),
                width=10,
            ).grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=2)

            ttk.Label(
                grid,
                textvariable=var,
                font=(FONT_NAME, 10),
                width=10,
            ).grid(row=row_idx, column=1, sticky="w", padx=(8, 8))

        add_row(0, "RSI", self.var_score_rsi)
        add_row(1, "MACD", self.var_score_macd)
        add_row(2, "Trend", self.var_score_trend)

        ttk.Label(
            wrapper,
            text="※ 점수 계산 공식은 v2에서 점진적으로 정교화 예정.",
            font=(FONT_NAME, 9),
        ).pack(anchor="w", pady=(12, 0))

    # ---- 신호 탭 ----
    def _build_tab_signal(self, frame: ttk.Frame) -> None:
        wrapper = ttk.Frame(frame)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(
            wrapper,
            text="신호 로그 (v2 1단계 - 스켈레톤)",
            font=(FONT_NAME, 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            wrapper,
            text="※ 실제 신호 엔진/로그는 v2에서 점진적으로 연결 예정.",
            font=(FONT_NAME, 9),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    # ---- 리스크 탭 ----
    def _build_tab_risk(self, frame: ttk.Frame) -> None:
        wrapper = ttk.Frame(frame)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(
            wrapper,
            text="리스크 관리 (v2 스켈레톤)",
            font=(FONT_NAME, 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            wrapper,
            text="※ 계좌/포지션/1회 리스크/데일리 손실한도 등은\n   v2 리스크 엔진에서 단계적으로 구현 예정.",
            font=(FONT_NAME, 9),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    # ---- 로그 탭 ----
    def _build_tab_log(self, frame: ttk.Frame) -> None:
        wrapper = ttk.Frame(frame)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(
            wrapper,
            text="로그 / 이벤트 (v2 스켈레톤)",
            font=(FONT_NAME, 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            wrapper,
            text="※ 실제 로그 스트림/필터링은 v2 이후 단계에서 구현 예정.",
            font=(FONT_NAME, 9),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    # ---------- 헬스체크 ----------
    def _run_initial_healthcheck(self) -> None:
        """앱 시작 시 한 번만 헬스체크를 돌리고 라벨에 표시."""
        try:
            summary = self.health_checker.run_all()
        except Exception as e:
            logging.error("초기 헬스체크 실패: %s", e)
            summary = "[ERROR] 헬스체크 중 예외 발생"

        self.var_health.set(summary)

    # =====================================================
    # [SEC:UI_LOOP] 주기적 UI / 차트 리프레시 루프
    # =====================================================
    def _start_ui_refresh_loop(self) -> None:
        """
        v2: DataEngine / IndicatorEngine / ChartEngine를
        주기적으로 동기화하는 메인 루프.
        """
        REFRESH_MS = 1000  # 1초 간격 (원하면 나중에 설정값으로 뺄 수 있음)

        def _tick() -> None:
            try:
                market = self.var_symbol.get()
                tf = self.var_tf.get()

                # -------------------------------------------------
                # 1) DataEngine 캐시 갱신 + 상태 문자열 (NO DATA 3분리)
                #   - CACHE MISS: 캐시에 엔트리 자체가 없음
                #   - HTTP FAIL : fetch_ok=False 이면서 fetch_error 존재
                #   - BAD VALUES: candles는 있는데 trade_price 유효값이 0개
                # -------------------------------------------------
                data = None
                candles: list[dict] = []
                last_refresh = None

                fetch_ok = None
                fetch_error = None

                try:
                    if hasattr(self, "data_engine"):
                        data = self.data_engine.get(market, tf)
                    else:
                        data = None
                except Exception as exc:
                    data = None
                    fetch_ok = False
                    fetch_error = f"{type(exc).__name__}: {exc}"

                # 캐시 파싱
                if isinstance(data, dict):
                    raw_candles = data.get("candles")
                    if isinstance(raw_candles, list):
                        candles = raw_candles
                    last_refresh = data.get("last_refresh")
                    fetch_ok = data.get("fetch_ok")
                    fetch_error = data.get("fetch_error")

                # 상태 문구 계산 (3분리 + OK)
                if data is None:
                    # ✅ 엔트리 자체가 없음
                    data_status_text = f"CACHE MISS — {market} / TF {tf}"
                else:
                    if fetch_ok is False and fetch_error:
                        # ✅ HTTP/네트워크/429 등 실패가 기록된 케이스
                        data_status_text = f"HTTP FAIL — {fetch_error}"
                    elif not candles:
                        # ✅ 요청은 됐는데 비어있음(또는 fallback 결과 비어있음)
                        data_status_text = f"NO DATA — EMPTY ({market} / TF {tf})"
                    else:
                        # ✅ 값 깨짐 검출
                        valid_prices = 0
                        for c in candles:
                            if not isinstance(c, dict):
                                continue
                            v = c.get("trade_price")
                            if isinstance(v, (int, float, str)):
                                try:
                                    float(v)
                                    valid_prices += 1
                                except (ValueError, TypeError):
                                    pass

                        if valid_prices == 0:
                            data_status_text = f"BAD VALUES — 유효 price 0 ({market} / TF {tf})"
                        else:
                            if isinstance(last_refresh, datetime):
                                ts = last_refresh.strftime("%H:%M:%S")
                            else:
                                ts = "-"
                            data_status_text = f"DATA OK — {valid_prices}/{len(candles)} candles / last {ts}"

                # UI 라벨 반영
                if hasattr(self, "var_data_status"):
                    try:
                        self.var_data_status.set(data_status_text)
                    except Exception:
                        pass

                # -------------------------------------------------
                # 2) IndicatorEngine 계산 (예: RSI 값)
                # -------------------------------------------------
                try:
                    if hasattr(self, "indicator_engine"):
                        rsi_val = self.indicator_engine.rsi(market, tf, period=14)

                        if rsi_val is not None:
                            # 왼쪽/게이지 숫자 라벨
                            if hasattr(self, "var_rsi_value"):
                                self.var_rsi_value.set(f"{rsi_val:5.2f}")

                            # 🔹 게이지용 값 (0~100으로 클램프)
                            rsi_clamped = max(0.0, min(100.0, float(rsi_val)))

                            # 존 / 스타일 결정
                            zone_text = "중립"
                            style_name = "RSI.Neutral.Horizontal.TProgressbar"
                            if rsi_clamped <= 30:
                                zone_text = "과매도"
                                style_name = "RSI.Cold.Horizontal.TProgressbar"
                            elif rsi_clamped >= 70:
                                zone_text = "과매수"
                                style_name = "RSI.Hot.Horizontal.TProgressbar"

                            # 상태 텍스트 (게이지 오른쪽)
                            if hasattr(self, "var_rsi_status"):
                                try:
                                    self.var_rsi_status.set(zone_text)
                                except Exception:
                                    pass

                            # 실제 Progressbar 값/스타일 반영
                            if hasattr(self, "rsi_bar") and self.rsi_bar is not None:
                                try:
                                    self.rsi_bar["value"] = rsi_clamped
                                    self.rsi_bar.configure(style=style_name)
                                except Exception:
                                    pass

                except Exception:
                    # RSI 계산 에러 시, 라벨이 있으면 에러 표시
                    if hasattr(self, "var_rsi_value"):
                        try:
                            self.var_rsi_value.set("RSI 오류")
                        except Exception:
                            pass

                # -------------------------------------------------
                # 3) ChartEngine 업데이트
                # -------------------------------------------------
                try:
                    if hasattr(self, "chart_engine") and candles:
                        chart_status_msg = self.chart_engine.update(
                            candles=candles,
                            market=market,
                            tf=tf,
                            last_refresh=last_refresh,
                        )
                        if hasattr(self, "var_chart_status") and isinstance(
                            chart_status_msg,
                            str,
                        ):
                            self.var_chart_status.set(chart_status_msg)
                    else:
                        # 차트 엔진이 없거나 캔들이 비어 있으면 상태 간단 표시
                        if hasattr(self, "var_chart_status") and not candles:
                            self.var_chart_status.set("차트: 캔들 데이터 없음")
                except Exception as exc:
                    if hasattr(self, "var_chart_status"):
                        try:
                            self.var_chart_status.set(f"차트 오류: {exc}")
                        except Exception:
                            pass

            finally:
                # -------------------------------------------------
                # 4) 다음 틱 예약 (루프가 끊기지 않게 무조건 실행)
                # -------------------------------------------------
                try:
                    self.after(REFRESH_MS, _tick)
                except Exception:
                    # 위젯이 이미 파괴된 경우 등은 그냥 조용히 무시
                    pass
        # 최초 1회 즉시 실행
        _tick()


    def _refresh_ui_safe(self) -> None:
        try:
            self._update_rsi_block()
            self._update_chart_block()
        except Exception as e:
            logging.error(f"UI refresh error: {e!r}")
        finally:
            self.after(1000, self._refresh_ui_safe)

    # ---- 차트 갱신 ----
    def _update_chart_block(self) -> None:
        """현재 심볼/TF에 대한 차트 갱신 (ChartEngine 호출)."""
        now_ts = time.time()
        if self._last_chart_redraw_ts is not None:
            if now_ts - self._last_chart_redraw_ts < 2.0:
                return
        self._last_chart_redraw_ts = now_ts

        try:
            market = self.var_symbol.get().strip()
        except Exception:
            market = ""

        try:
            tf = self.var_tf.get().strip()
        except Exception:
            tf = ""

        if not market or not tf:
            self.var_chart_status.set("차트: 심볼/TF 선택 필요")
            return

        data = self.data_engine.get(market, tf)
        if not data or "candles" not in data:
            self.var_chart_status.set("차트: 데이터 없음 (캐시 미존재)")
            return

        candles: list[dict] = data["candles"]
        if not candles:
            self.var_chart_status.set("차트: 캔들 데이터 비어 있음")
            return

        last_refresh = data.get("last_refresh")
        status_text = self.chart_engine.update(candles, market, tf, last_refresh)
        self.var_chart_status.set(status_text)

    # ---- RSI 갱신 ----
    def _update_rsi_block(self) -> None:
        try:
            market = self.var_symbol.get().strip()
        except Exception:
            market = ""

        try:
            tf = self.var_tf.get().strip()
        except Exception:
            tf = ""

        if not market or not tf:
            self.var_rsi_value.set("---")
            self.var_rsi_status.set("심볼/TF 선택 필요")
            return

        rsi_value = self.indicator_engine.rsi(market, tf, period=14)
        if rsi_value is None:
            self.var_rsi_value.set("---")
            self.var_rsi_status.set("데이터 부족")
            return

        self.var_rsi_value.set(f"{rsi_value:5.2f}")

        try:
            value = float(rsi_value)
        except Exception:
            value = 50.0

        self.rsi_bar["value"] = value

        if value >= 70:
            self.var_rsi_status.set("과열 구간(매도 관찰)")
        elif value <= 30:
            self.var_rsi_status.set("과매도 구간(매수 관찰)")
        else:
            self.var_rsi_status.set("중립")

    # ---------- Data Refresh Loop ----------
    def _start_data_refresh_loop(self) -> None:
        try:
            self.data_engine.refresh_all(
                self.var_symbol.get(),
                self.cfg.timeframes,
            )
        except Exception as e:
            logging.error("데이터 갱신 오류: %s", e)

        self.after(3000, self._start_data_refresh_loop)

    # ---------- 이벤트 ----------
    def _on_toggle_auto_trading(self) -> None:
        state = self.var_auto_trading.get()
        logging.info("Auto trading toggled: %s", state)

    def _on_save_snapshot(self) -> None:
        path = self.snapshot_manager.make_snapshot(self.cfg, self.ctx)
        logging.info("스냅샷 저장: %s", path)

    def _on_show_about(self) -> None:
        from tkinter import messagebox

        messagebox.showinfo(
            "정보",
            f"{APP_NAME} v{APP_VERSION}\n\n이서현 시스템 v2 chartengine 빌드",
        )


# =========================================================
# [SEC:ENTRYPOINT] ▶️ 진입점
# =========================================================
def _dev_check_data_status() -> None:
    """
    DEV 전용: 데이터/폴더 상태 점검 (안전: 읽기만 함)
    """
    from pathlib import Path
    import time

    root = Path(".").resolve()

    targets = [
        root / "data",
        root / "data" / "asset",
        root / "data" / "observe",
        root / "logs",
    ]

    print("=" * 60)
    print("[DEV] 데이터 상태 점검")
    print(f"[DEV] root = {root}")
    now = time.time()

    for p in targets:
        if p.exists():
            if p.is_dir():
                # 최근 수정 시간(폴더는 OS에 따라 부정확할 수 있으니 참고용)
                mtime = p.stat().st_mtime
                age_min = int((now - mtime) / 60)
                print(f"[DEV] OK   dir  {p} (age~{age_min}m)")
            else:
                st = p.stat()
                age_min = int((now - st.st_mtime) / 60)
                print(f"[DEV] OK   file {p} size={st.st_size} age={age_min}m")
        else:
            print(f"[DEV] MISS     {p}")

    print("=" * 60)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    cfg = load_dashboard_config()
    ctx = DashboardContext(
        market=cfg.symbols[0],
        tf=cfg.timeframes[0],
        mode=cfg.mode,
        strategy="SCALPING",
    )

    app = SeohyunDashboard(cfg=cfg, ctx=ctx)
    app.mainloop()

    # =========================================================
    # [DEV] 실험 버튼 (DEV 모드에서만 표시)
    # =========================================================
    if is_dev():
        try:
            import tkinter as tk

            def _on_click():
                _dev_check_data_status()

            btn = tk.Button(
                app,
                text="DEV: 데이터 상태 점검",
                command=_on_click
            )
            # 항상 보이게 상단 고정
            btn.pack(side="top", fill="x")
            logging.info("[DEV] 실험 버튼 활성화: 데이터 상태 점검")
        except Exception as e:
            logging.exception("[DEV] 실험 버튼 구성 실패: %s", e)



if __name__ == "__main__":
    main()
