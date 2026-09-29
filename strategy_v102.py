# -*- coding: utf-8 -*-
# v102 source engine + journal-only instrumentation and opt-in strict data gate.
import os
import sys
import json
import math
import time
import argparse
import itertools
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# الهوية والثوابت
# ══════════════════════════════════════════════════════════════════════════════
BOT_NAME = "TITAN_JUGGERNAUT_APEX_OMNI_SYSTEM"
BOT_VERSION = "v127.0.0"   # [v127 مزامنة كاملة 2026-09-12] الإصدار المعتمد (أمر المالك).   # التاريخ: v102: تخصيص 240/160 (+16.9، ‏OOS أخضر حتى بالبوابة الصارمة)   # v101: كومبو H19 بوابة-تخفيف (P3-trl 50 + كون P2 + ‏BTC/AVAX) ‏+4.78pp/‏n+53 — OOS ‏−1.60 مُفصح   # v100: S2-trl 52 (H20) +9.12pp-IS — المرجع نافذة 4Y-vision   # v99: خيار موحد تجريبي (--unified، ‏OOS ‏-55% مرفوض) — الافتراضي = ثنائي v98 المربح   # v98: P1-t2frac 0.05 (H16) — المرجع نافذة 4Y-vision   # v97: S2-boost 1.4 (H15) — المرجع نافذة 4Y-vision   # v96: P1-trail 0.025 (H14) — المرجع نافذة 4Y-vision   # v95: P1-rsi 85 (H13) — المرجع نافذة 4Y-vision   # v94: S2-T1 4.0 (H12) — المرجع نافذة 4Y-vision   # v93: بوابة 5m ضحلة (V4) — المرجع 4Y-vision + بوابة 2Y-5m   # v92: هدف T1 الأبعد (H10) — المرجع نافذة 4Y-vision   # v91: بنك انجراف P1 (H9) — المرجع نافذة 4Y-vision   # v90: ميزانيات 85/8/7 (H8) — المرجع نافذة 4Y-vision   # v89: كون S2 بلا VET (H6) — المرجع نافذة 4Y-vision   # v88: سقف S2 0.25 (H4) — المرجع نافذة 4Y-vision   # v87: فيتو 5m واعٍ بالسياق — الافتراضي مطابق لـ v83   # v86: بوابة 5m داخل الباكتست — الافتراضي مطابق لـ v83   # v85: محرك 5m الدقيق (S/R + نقاط 0-100 + اختبار حقيقي) — الافتراضي مطابق لـ v83   # v84: + محرك الدخول الدقيق 5m (الباكتست الافتراضي مطابق لـ v83)

BENCHMARK_ASSET = "BTCUSDT"

# [v60] المحافظ الثلاث المتخصصة على 14 أصلاً (Spot USDT فقط)
ELITE_TRADEABLE_ASSETS = [
    "SOLUSDT", "FETUSDT", "DOTUSDT", "XRPUSDT", "BNBUSDT",
    "ETHUSDT", "XLMUSDT", "HBARUSDT", "TRXUSDT", "LINKUSDT",
    "ADAUSDT", "LTCUSDT", "DOGEUSDT", "ARBUSDT",
]

# [v71] الاستراتيجية الثانية: متابعة اتجاه انتقائية على 10 عملاً [v89: بلا VET — نزيف مزمن −20.6$]
STRATEGY2_ASSETS = [
    "XRPUSDT", "ADAUSDT", "LTCUSDT", "BCHUSDT", "ETCUSDT", "XLMUSDT",
    "TRXUSDT", "EOSUSDT", "HBARUSDT", "ZECUSDT",
]

ALL_DATA_ASSETS = ([BENCHMARK_ASSET] + ELITE_TRADEABLE_ASSETS
                   + [s for s in STRATEGY2_ASSETS if s not in ELITE_TRADEABLE_ASSETS])

# رأس المال (الحساب الموحّد 400$ = 200$ + 200$)
TOTAL_CAPITAL = 400.0
STRATEGY1_CAPITAL = 380.0  # [v116→v127] تخصيص 95/5 المعتمد
STRATEGY2_CAPITAL = 20.0   # [v116→v127]

# [v78] رأس المال الديناميكي: إعادة توزيع كل 30 يوماً حسب فرق العائد (90 يوماً) بين الاستراتيجيتين
# [v88] قانون DD المعاد معايرته لنافذة 4Y (تشمل دباً كاملاً + فتائل حقيقية): DD ≤ 23%
# بصمة v83-2Y-ياهو محفوظة في results/v83_yahoo_fingerprint.json للمرجع فقط.
DYNAMIC_CAPITAL = {"enabled": False, "rebalance_days": 30, "gamma": 8.0,   # [v127] إطفاء إعادة التوازن — كل جانب يتركّب بحريته (شهادة 4Y +3279.64)
                   "lookback_days": 90, "w_s2_min": 0.25, "w_s2_max": 0.25}  # [v89] ثابت 75/25 صريح (الديناميكي خسر على 4Y)

# السلة الخماسية (وضع --legacy الاحتياطي)
LEGACY_CORE5 = ["SOLUSDT", "FETUSDT", "DOTUSDT", "XRPUSDT", "BNBUSDT"]

# رموز Yahoo (تُستخدم فقط عند fallback)
YAHOO_TICKER_RESOLVER = {
    "BTCUSDT": "BTC-USD", "SOLUSDT": "SOL-USD", "BNBUSDT": "BNB-USD",
    "XRPUSDT": "XRP-USD", "DOTUSDT": "DOT-USD", "FETUSDT": "FET-USD",
    "ETHUSDT": "ETH-USD", "XLMUSDT": "XLM-USD", "HBARUSDT": "HBAR-USD",
    "TRXUSDT": "TRX-USD", "LINKUSDT": "LINK-USD", "ADAUSDT": "ADA-USD",
    "LTCUSDT": "LTC-USD", "DOGEUSDT": "DOGE-USD", "ARBUSDT": "ARB-USD",
    "BCHUSDT": "BCH-USD", "ETCUSDT": "ETC-USD", "EOSUSDT": "EOS-USD",
    "VETUSDT": "VET-USD", "ZECUSDT": "ZEC-USD",
}

# ══════════════════════════════════════════════════════════════════════════════
# إعدادات النظام (احتكاك حقيقي: عمولة 0.10% + انزلاق 0.05% = 0.15%)
# ══════════════════════════════════════════════════════════════════════════════
class SystemConfig:
    INITIAL_CAPITAL = 100.0
    MIN_ORDER_USDT = 5.0
    FEE_RATE = 0.0010
    SLIPPAGE_RATE = 0.0005
    TOTAL_FRICTION = FEE_RATE + SLIPPAGE_RATE
    DATA_DAYS = 730
    IS_RATIO = 0.60                       # 60% تدريب / 40% اختبار أعمى

    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    CACHE_DIR = os.path.join(_SCRIPT_DIR, "cache")
    CACHE_FILE = "titans_basket_4h_cache.pkl"
    M5_CACHE_FILE = "titans_5m_cache.pkl"
    RESULTS_DIR = os.path.join(_SCRIPT_DIR, "results")

# ثوابت الحوكمة الدفاعية (خارج فضاء التحسين)
EXECUTION_MODE = "close"                 # شراء بإغلاق شمعة الإشارة
RISK_OFF_GMRI = 0.35                     # ما دونها = بيئة هابطة
BOOST_GMRI = 0.65                        # ما فوقها = صاعدة قوية
EXHAUSTION_QUANTILE = 0.90
ATR_QUANTILE_WINDOW = 240
POSITION_RISK_PCT = 0.05
COOLDOWN_NORMAL = 12
COOLDOWN_SL = 30

# [v84] محرك الدخول الدقيق — نمذجة الباكتست (أمر حد بدل الشراء السوقي)
MICRO_DEPTH_CAP = 0.0025     # أقصى عمق لمنطقة الدخول تحت سعر الإشارة (0.25%)
MICRO_DEPTH_ATR = 0.35       # عمق المنطقة = 0.35 × ATR المعياري (مغطى بالسقف أعلاه)
MICRO_TIMEOUT_BARS = 3       # مهلة الملء = 3 شموع 4H (12 ساعة) ثم مطاردة بسعر السوق

# المعاملات الافتراضية (الأساس لكل الاستراتيجيات)
BASELINE_PARAMS = {
    "ema_p": 21, "slope_lag": 4, "rsi_p": 14,
    "rsi_lo": 40.0, "rsi_hi": 56.0, "rsi_trig": 48.0,
    "prox": 0.020,
    "min_confluence": 0.38,
    "sl_atr_mult": 2.30, "t1_atr_mult": 5.20, "t2_atr_mult": 9.80,
    "trail_atr_mult": 1.90, "t2_lock_atr_mult": 1.80,
    "t1_frac": 0.30, "t2_frac_of_rest": 0.50,
    "t1_gain_lock": 0.0,
    "rsi_exit": 82.0,
    "max_risk": 3, "max_total": 3,
    "alpha_weights": [0.65, 0.25, 0.10],
    "risk_off_mult": 0.75,
    # [v83] رافعة التعافي بعد كساد الاتساع (GMRI<0.30 لـ18 شمعة → دفعة ×1.30 لمدة 48 شمعة)
    "bear_gmri": 0.30, "bear_persist": 18, "rec_boost": 1.30, "rec_bars": 48,
    "vol_filter": False,
    "cooldown_on": True,
    "risk_pct": 0.05,
    "boost": 1.35,
    "dd_freezer": 0.0,
}

# ══════════════════════════════════════════════════════════════════════════════
# معاملات المحافظ الثلاث (v83 المعتمدة)
# ══════════════════════════════════════════════════════════════════════════════
POOL1_ASSETS = LEGACY_CORE5
POOL2_ASSETS = ["XLMUSDT", "ETHUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "BTCUSDT", "AVAXUSDT"]  # [v101-H19]
POOL3_ASSETS = ["HBARUSDT", "DOGEUSDT", "ADAUSDT", "ARBUSDT"]

POOL1_PARAMS = dict(BASELINE_PARAMS)
POOL1_PARAMS.update({
    "min_confluence": 0.40, "sl_atr_mult": 2.30, "t1_atr_mult": 6.20, "t2_atr_mult": 9.80,  # [v92-H10]
    "trail_atr_mult": 0.025, "t1_frac": 0.05,  # [v96-H14] بنك فوري 0.025 (هضبة)  # [v91-H9] بنك الانجراف: T2 محفوظ، الانجراف يُبنك فوراً "alpha_weights": [0.65, 0.25, 0.10],
    "risk_pct": 0.052, "boost": 2.20, "dd_freezer": 0.0,
    "risk_off_mult": 1.0, "rsi_exit": 85.0,  # [v95-H13] P1-rsi 85
    "t2_frac_of_rest": 0.05,  # [v98-H16] P1-t2frac 0.05 (runner أولاً)
})

POOL2_PARAMS = dict(BASELINE_PARAMS)
POOL2_PARAMS.update({
    "min_confluence": 0.22, "sl_atr_mult": 2.0, "t1_atr_mult": 4.0, "t2_atr_mult": 8.5,
    "trail_atr_mult": 1.2, "t1_frac": 0.30, "alpha_weights": [0.40, 0.35, 0.25],
    "risk_pct": 0.035, "boost": 1.2, "dd_freezer": 0.0, "prox": 0.015,
    "risk_off_mult": 0.85,
    "cooldown_sl": 16,                    # [v82] كولداون P2 الخاص بعد الوقف
    "asset_params": {
        "LINKUSDT": {"mode": "trend", "min_confluence": 0.56, "tr_rsi_lo": 58.0,
                     "tr_rsi_hi": 82.0, "prox": 0.03, "tr_rm_lo": 48.0},
    },
})

POOL3_PARAMS = dict(BASELINE_PARAMS)
POOL3_PARAMS.update({
    "mode": "trend",
    "min_confluence": 0.50, "sl_atr_mult": 2.1, "t1_atr_mult": 5.0, "t2_atr_mult": 9.6,
    "trail_atr_mult": 1.3, "t1_frac": 0.05, "alpha_weights": [0.55, 0.30, 0.15],
    "max_risk": 2, "max_total": 2, "risk_pct": 0.03, "boost": 1.2,
    "dd_freezer": 0.0, "prox": 0.03, "rsi_exit": 75.0,
    "risk_off_mult": 0.85, "t1_gain_lock": 0.0,
    "min_alpha_gap": 0.10,
    "btc_filter": True, "tr_rsi_lo": 50.0, "tr_rsi_hi": 82.0, "tr_rm_lo": 48.0,  # [v101-H19] P3-trl 50 (بوابة تخفيف)
    "asset_params": {**{t: {"mode": "trend"} for t in POOL3_ASSETS},
                     "HBARUSDT": {"mode": "trend", "min_confluence": 0.60}},
})

# ══════════════════════════════════════════════════════════════════════════════
# الاستراتيجية الموحدة v99: قاعدة واحدة (P1-dip مضبوطة) لكل العملات الـ26
# ══════════════════════════════════════════════════════════════════════════════
UNIFIED_ASSETS = ['AAVEUSDT', 'ADAUSDT', 'ARBUSDT', 'ATOMUSDT', 'AVAXUSDT', 'BCHUSDT', 'BNBUSDT', 'BTCUSDT', 'DOGEUSDT', 'DOTUSDT', 'EOSUSDT', 'ETCUSDT', 'ETHUSDT', 'FETUSDT', 'HBARUSDT', 'INJUSDT', 'LINKUSDT', 'LTCUSDT', 'NEARUSDT', 'ONDOUSDT', 'SOLUSDT', 'TRXUSDT', 'VETUSDT', 'XLMUSDT', 'XRPUSDT', 'ZECUSDT']
UNIFIED_PARAMS = dict(POOL1_PARAMS)
UNIFIED_PARAMS.update({
    "risk_pct": 0.02, "btc_filter": True, "sl_atr_mult": 1.8,
    "max_risk": 3, "max_total": 3,
})  # [v99-U] risk 0.02 + فلتر BTC + وقف 1.8 (IS ‏+235.6/DD ‏14.3/n ‏132)

POOL_BUDGETS = [90.0, 5.0, 5.0]              # [v123→v127] توزيع 90/5/5 المعتمد

# ══════════════════════════════════════════════════════════════════════════════
# معاملات الاستراتيجية الثانية (متابعة الاتجاه الانتقائية — 11 عملاً)
# ══════════════════════════════════════════════════════════════════════════════
STRATEGY2_PARAMS = dict(BASELINE_PARAMS)
STRATEGY2_PARAMS.update({
    "mode": "trend",
    "min_confluence": 0.50, "sl_atr_mult": 2.1, "t1_atr_mult": 4.0, "t2_atr_mult": 9.6,
    "trail_atr_mult": 1.3, "t1_frac": 0.04, "alpha_weights": [0.55, 0.30, 0.15],  # [v94-H12] S2-T1 4.0
    "risk_pct": 0.032, "boost": 1.4, "dd_freezer": 0.0, "prox": 0.03,  # [v97-H15] S2-boost 1.4
    "max_risk": 1, "max_total": 1, "risk_off_mult": 0.85, "t1_gain_lock": 0.0,
    "btc_filter": True, "tr_rsi_lo": 52.0, "tr_rsi_hi": 82.0, "tr_rm_lo": 48.0,  # [v100-H20] S2-trl 52
    "mom_gate": {"mode": "rank", "theta": 0.22},   # [v74] بوابة الزخم المئيني
    "conf_sideways": 0.41,                          # [v75] التلاقح الديناميكي
    "cooldown_sl": 41,                              # [v77] كولداون S2 الخاص
    "asset_params": {
        "BCHUSDT": {"mode": "floor", "min_confluence": 0.50, "fl_rsi_dip": 32.0,
                    "fl_rsi_up": 26.0, "roc_free": True, "btc_free": True},
    },
})

# ══════════════════════════════════════════════════════════════════════════════
# 1) خط أنابيب البيانات: كاش دائم + جلب Binance (fallback: Yahoo)
# ══════════════════════════════════════════════════════════════════════════════
class PureTechnicalStructureEngine:
    @staticmethod
    def calculate_structure_score(df, swing_p=8):
        high, low, close = df["High"], df["Low"], df["Close"]
        swing_high = high.rolling(swing_p, min_periods=swing_p // 2).max().shift(1)
        bos_signal = (close > swing_high).astype(float).rolling(3, min_periods=1).max()
        fvg_bull = ((low > high.shift(2)) & (close > close.shift(1))).astype(float)
        body = (close - df["Open"]).abs()
        lower_wick = np.minimum(close, df["Open"]) - low
        rejection_signal = (lower_wick > (body * 1.2)).astype(float)
        tech_score = (0.45 * bos_signal + 0.30 * fvg_bull + 0.25 * rejection_signal).fillna(0.0)
        return tech_score.clip(0.0, 1.0)


class PsychologicalRangeEngine:
    @staticmethod
    def calculate_psychology_score(df, range_p=24):
        close, low, high = df["Close"], df["Low"], df["High"]
        range_low = low.rolling(range_p, min_periods=range_p // 2).min()
        range_high = high.rolling(range_p, min_periods=range_p // 2).max()
        range_span = (range_high - range_low).replace(0, np.nan)
        range_position = ((close - range_low) / range_span).fillna(0.5)
        discount_score = np.where(range_position <= 0.45, 1.0 - range_position, 0.25)
        discount_score = pd.Series(discount_score, index=df.index).clip(0.0, 1.0)
        prev_min = low.rolling(range_p // 2).min().shift(1)
        sweep_signal = ((low < prev_min) & (close > prev_min)).astype(float).rolling(2, min_periods=1).max()
        log_price = np.log10(np.maximum(close, 1e-6))
        step = 10 ** (np.floor(log_price) - 1)
        dist_to_round = np.abs(close - np.round(close / step) * step) / close
        psych_magnet = np.exp(-dist_to_round * 35.0)
        psych_score = (0.45 * discount_score + 0.35 * sweep_signal + 0.20 * psych_magnet).fillna(0.0)
        return psych_score.clip(0.0, 1.0)


class TechnicalEngine:
    @staticmethod
    def rsi(close, period=14):
        d = close.diff()
        up = d.where(d > 0, 0.0)
        dn = -d.where(d < 0, 0.0)
        ag = up.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        al = dn.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = ag / al.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50.0)

    @staticmethod
    def atr_normalized(df, period=14):
        high, low, close_prev = df["High"], df["Low"], df["Close"].shift(1)
        tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return (atr / df["Close"]).fillna(0.02).clip(0.01, 0.10)

    @classmethod
    def apply(cls, df, btc_df, ema_p=21, slope_lag=4, rsi_p=14):
        d = df.copy()
        d["EMA"] = d["Close"].ewm(span=ema_p, adjust=False).mean()
        d["SLOPE"] = d["EMA"] - d["EMA"].shift(slope_lag)
        d["RSI"] = cls.rsi(d["Close"], rsi_p)
        d["RSI_PREV"] = d["RSI"].shift(1)
        d["RSI_MIN3"] = d["RSI"].rolling(3).min()
        d["ROC_60"] = d["Close"].pct_change(60).fillna(0.0)
        d["ALPHA"] = ((d["Close"] / d["Close"].shift(42)) * (d["RSI"] / 50.0)).fillna(1.0)
        vol_ma = d["Volume"].rolling(20, min_periods=5).mean().replace(0, np.nan)
        d["RVOL"] = (d["Volume"] / vol_ma).fillna(1.0).clip(0.5, 3.5)
        asset_perf = d["Close"] / d["Close"].shift(24).replace(0, np.nan)
        btc_perf = (btc_df["Close"] / btc_df["Close"].shift(24).replace(0, np.nan)).reindex(d.index).ffill().bfill()
        d["RS_BTC"] = (asset_perf / btc_perf).fillna(1.0).clip(0.5, 3.0)
        d["TECH_STRUCT_SCORE"] = PureTechnicalStructureEngine.calculate_structure_score(d, swing_p=8)
        d["PSYCH_RANGE_SCORE"] = PsychologicalRangeEngine.calculate_psychology_score(d, range_p=24)
        mom_raw = (d["ROC_60"] * 5.0) + ((d["RSI"] - 50.0) / 25.0)
        d["MOM_SCORE"] = (1.0 / (1.0 + np.exp(-mom_raw))).clip(0.0, 1.0)
        d["ATR_NORM"] = cls.atr_normalized(d, period=14)
        return d


class SynergyFusionArbiter:
    @staticmethod
    def calculate_confluence(tech_score, psych_score, mom_score,
                             w_tech=0.35, w_psych=0.30, w_mom=0.35):
        return (w_tech * tech_score) + (w_psych * psych_score) + (w_mom * mom_score)

def _fmt_px(x):
    """تنسيق السعر حسب حجمه (BTC مقابل العملات الصغيرة)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(x):
        return "—"
    if x >= 1000:
        return f"{x:,.1f}"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6f}"


# ══════════════════════════════════════════════════════════════════════════════
# 2ب) محرك الدخول الدقيق [v84]: شموع 5m لآخر ساعتين → منطقة دخول + حكم تنفيذ
# ══════════════════════════════════════════════════════════════════════════════
class MicroEntryZoneEngine:
    """عندما تعطي استراتيجية 4H إشارة، لا نشتري سوقياً فوراً — بل نكبّر على آخر
    ساعتين (24 شمعة 5m) ونحدد منطقة دخول دقيقة: بين دعم الساعة وVWAP."""

    HOURS_DEFAULT = 2
    CANDLES_PER_HOUR = 12
    H1_WINDOW = 12               # نافذة الدعم/المقاومة = آخر ساعة
    TREND_EMA_FAST = 9
    TREND_EMA_SLOW = 21
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    EXT_ENTER = 0.75             # امتداد فوق VWAP بمضاعفات ATR → دخول فوري تحته
    EXT_WAIT = 2.00              # امتداد متوسط → انتظار تراجع | فوقه → تخطي (مطاردة)

    # ---------- الجلب ----------
    @staticmethod
    def fetch_binance_5m(symbol, hours=2):
        """أحدث شموع 5m من Binance (عامة، بلا مفاتيح). تُسقط الشمعة الجارية."""
        import urllib.request
        n = int(hours * MicroEntryZoneEngine.CANDLES_PER_HOUR) + 4
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit={n}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data or len(data) < 12:
            return None
        arr = np.array(data, dtype=float)
        df = pd.DataFrame({"Open": arr[:, 1], "High": arr[:, 2], "Low": arr[:, 3],
                           "Close": arr[:, 4], "Volume": arr[:, 5]},
                          index=pd.to_datetime(arr[:, 0].astype(int), unit="ms", utc=True))
        df = df[~df.index.duplicated(keep="first")]
        return df.iloc[:-1].tail(int(hours * MicroEntryZoneEngine.CANDLES_PER_HOUR))

    @staticmethod
    def fetch_yahoo_5m(symbol, hours=2):
        """بديل: شموع 5m من Yahoo (متاحة للأيام الأخيرة — تكفي لنافذة الساعتين)."""
        try:
            import yfinance as yf
        except ImportError:
            return None
        ysym = YAHOO_TICKER_RESOLVER.get(symbol, f"{symbol[:-4]}-USD")
        try:
            df = yf.download(ysym, period="2d", interval="5m", progress=False,
                             auto_adjust=False, threads=False)
            if df is None or df.empty or len(df) < 12:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                if "Close" in df.columns.get_level_values(0):
                    df = (df.xs(ysym, axis=1, level=1)
                          if ysym in df.columns.get_level_values(1) else df.droplevel(1, axis=1))
                else:
                    df.columns = df.columns.get_level_values(0)
            cutoff = df.index.max() - pd.Timedelta(hours=hours)
            df = df[df.index > cutoff]
            if df is None or len(df) < 12:
                return None
            if df.index.tz is not None:
                df.index = df.index.tz_convert(timezone.utc)
            else:
                df.index = df.index.tz_localize(timezone.utc)
            return df.iloc[:-1] if len(df) > 12 else df   # إسقاط الجارية إن أمكن
        except Exception:
            return None

    @staticmethod
    def fetch_yahoo_5m_hist(symbol, days=60):
        """شموع 5m تاريخية من Yahoo (حتى 60 يوماً) — لاختبار المحرك على بيانات حقيقية."""
        try:
            import yfinance as yf
        except ImportError:
            return None
        ysym = YAHOO_TICKER_RESOLVER.get(symbol, f"{symbol[:-4]}-USD")
        try:
            df = yf.download(ysym, period=f"{min(int(days), 60)}d", interval="5m",
                             progress=False, auto_adjust=False, threads=False)
            if df is None or df.empty or len(df) < 500:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                if "Close" in df.columns.get_level_values(0):
                    df = (df.xs(ysym, axis=1, level=1)
                          if ysym in df.columns.get_level_values(1) else df.droplevel(1, axis=1))
                else:
                    df.columns = df.columns.get_level_values(0)
            cols = ["Open", "High", "Low", "Close", "Volume"]
            if not set(cols).issubset(set(df.columns)):
                return None
            if df.index.tz is not None:
                df.index = df.index.tz_convert(timezone.utc)
            else:
                df.index = df.index.tz_localize(timezone.utc)
            return df if len(df) >= 500 else None
        except Exception:
            return None

    @classmethod
    def fetch_5m(cls, symbol, hours=2, warmup_hours=6):
        """يجلب شموع 5m (Binance ثم Yahoo). المنطقة من آخر `hours` والمؤشرات من `warmup_hours`."""
        for name, fn in (("Binance-5m", cls.fetch_binance_5m), ("Yahoo-5m", cls.fetch_yahoo_5m)):
            try:
                df = fn(symbol, warmup_hours)
            except Exception:
                df = None
            if df is not None and len(df) >= 12:
                return df, name
        return None, None

    # ---------- حساب المنطقة بنظام النقاط [v85] ----------
    @staticmethod
    def _pivot_levels(d, atr_abs, tol_mult=0.15, left=3, right=3):
        """مستويات دعم/مقاومة من القمم/القيعان الكسورية + دمج المتقاربة + عدّ اللمسات."""
        h = d["High"].to_numpy(float)
        l = d["Low"].to_numpy(float)
        n = len(d)
        raw_h, raw_l = [], []
        for i in range(left, n - right):
            wh = h[i - left:i + right + 1]
            wl = l[i - left:i + right + 1]
            if (h[i] > wh[:left]).all() and (h[i] > wh[left + 1:]).all():
                raw_h.append((i, float(h[i])))
            if (l[i] < wl[:left]).all() and (l[i] < wl[left + 1:]).all():
                raw_l.append((i, float(l[i])))

        def _cluster(raw):
            lvls = []
            for i, pxx in sorted(raw, key=lambda x: x[1]):
                if lvls and abs(pxx - lvls[-1]["px"]) <= atr_abs * tol_mult:
                    g = lvls[-1]
                    g["pxs"].append(pxx)
                    g["px"] = float(np.median(g["pxs"]))
                    g["touches"] += 1
                    g["last_i"] = max(g["last_i"], i)
                else:
                    lvls.append({"px": pxx, "pxs": [pxx], "touches": 1, "last_i": i})
            for g in lvls:
                g["strength"] = g["touches"] + (0.5 if g["last_i"] >= n - 12 else 0.0)
            return sorted(lvls, key=lambda g: -g["strength"])[:4]

        return _cluster(raw_l), _cluster(raw_h)

    @classmethod
    def compute_zone(cls, df5m, context=None):
        """منطقة الدخول بنظام نقاط (0-100): الموقع + الدعوم/المقاومات + المؤشرات
        (EMA/MACD/RSI/Stochastic/BB) + الشمعة + الحجم + الهيكل + سياق 4H."""
        d = df5m.dropna().copy()
        if d is None or len(d) < 24:
            return {"ok": False, "reason": "شموع 5m غير كافية (<24)"}
        context = context or {}
        w = d.tail(24)                                   # نافذة المنطقة: آخر ساعتين
        px = float(d["Close"].iloc[-1])
        tp = (w["High"] + w["Low"] + w["Close"]) / 3.0
        vol = w["Volume"].replace(0, np.nan)
        vwap = float((tp * vol).sum() / vol.sum()) if vol.notna().sum() > 0 else float(tp.mean())

        prev_c = d["Close"].shift(1)
        tr = pd.concat([d["High"] - d["Low"], (d["High"] - prev_c).abs(),
                        (d["Low"] - prev_c).abs()], axis=1).max(axis=1)
        atr_abs = float(tr.tail(cls.ATR_PERIOD).mean())
        if not np.isfinite(atr_abs) or atr_abs <= 0:
            atr_abs = px * 0.002
        atr_pct = atr_abs / px * 100.0
        atr = atr_abs

        cl = d["Close"]
        ema_f = cl.ewm(span=cls.TREND_EMA_FAST, adjust=False).mean()
        ema_s = cl.ewm(span=cls.TREND_EMA_SLOW, adjust=False).mean()
        ema_up = bool(ema_f.iloc[-1] > ema_s.iloc[-1] and px > ema_s.iloc[-1])
        ema_dn = bool(ema_f.iloc[-1] < ema_s.iloc[-1] and px < ema_s.iloc[-1])
        trend, trend_ar = ("up", "صاعد 📈") if ema_up else (("down", "هابط 📉") if ema_dn else ("flat", "أفقي ➖"))

        rsi_s = TechnicalEngine.rsi(cl, cls.RSI_PERIOD)
        rsi5 = float(rsi_s.iloc[-1])
        rsi_slope = float(rsi_s.iloc[-1] - rsi_s.iloc[-4]) if len(rsi_s) >= 4 else 0.0
        rsi_arrow = "↑" if rsi_slope > 1.0 else ("↓" if rsi_slope < -1.0 else "→")

        macd_line = cl.ewm(span=12, adjust=False).mean() - cl.ewm(span=26, adjust=False).mean()
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float(macd_line.iloc[-1] - macd_sig.iloc[-1])
        macd_hist_prev = float(macd_line.iloc[-2] - macd_sig.iloc[-2]) if len(d) > 1 else 0.0
        macd_cross_up = macd_hist > 0 >= macd_hist_prev
        macd_txt = (("➕ إيجابي" + (" (تقاطع⬆)" if macd_cross_up else ""))
                    if macd_hist > 0 else "➖ سلبي")

        ll14 = d["Low"].rolling(14).min()
        hh14 = d["High"].rolling(14).max()
        rng = (hh14 - ll14).replace(0, np.nan)
        k = (((cl - ll14) / rng) * 100.0).rolling(3).mean()
        dd = k.rolling(3).mean()
        K = float(k.iloc[-1]) if np.isfinite(k.iloc[-1]) else 50.0
        D = float(dd.iloc[-1]) if np.isfinite(dd.iloc[-1]) else 50.0
        Kp = float(k.iloc[-2]) if len(k) > 1 and np.isfinite(k.iloc[-2]) else K
        Dp = float(dd.iloc[-2]) if len(dd) > 1 and np.isfinite(dd.iloc[-2]) else D
        stoch_cross_up = (K > D) and (Kp <= Dp)
        stoch_txt = f"{K:.0f}/{D:.0f}" + (" ⬆" if stoch_cross_up else "")

        bb_mid = cl.rolling(20).mean()
        bb_std = cl.rolling(20).std()
        bb_pct = (float((px - bb_mid.iloc[-1]) / (2 * bb_std.iloc[-1]) + 0.5)
                if np.isfinite(bb_mid.iloc[-1]) and bb_std.iloc[-1] > 0 else 0.5)
        bb_txt = f"{bb_pct * 100:.0f}%"

        o, hh, ll, cc = (float(d["Open"].iloc[-1]), float(d["High"].iloc[-1]),
                        float(d["Low"].iloc[-1]), px)
        body = abs(cc - o)
        lower_wick = min(cc, o) - ll
        upper_wick = hh - max(cc, o)
        bullish = cc > o
        hammer = (lower_wick > 2.0 * body + 1e-12) and body < atr * 0.6
        po, pc = float(d["Open"].iloc[-2]), float(d["Close"].iloc[-2])
        bear_engulf = (pc > po) and (cc < o) and (o >= pc) and (cc <= po)
        candle_bits = ["صاعدة✅" if bullish else "هابطة"]
        if hammer:
            candle_bits.append("رفض سفلي🔨")
        if bear_engulf:
            candle_bits.append("ابتلاعية هابطة⚠️")
        if upper_wick > 2.0 * body + 1e-12:
            candle_bits.append("رفض علوي⚠️")
        candle_txt = "+".join(candle_bits)

        vmean = d["Volume"].tail(24).mean()
        vratio = float(d["Volume"].iloc[-3:].mean() / max(vmean, 1e-12))
        upvol = d.tail(12)
        up_share = float(upvol.loc[upvol["Close"] > upvol["Open"], "Volume"].sum()
                         / max(upvol["Volume"].sum(), 1e-12))

        lows12 = d["Low"].tail(12).to_numpy(float)
        highs12 = d["High"].tail(12).to_numpy(float)
        lows_slope = float(np.polyfit(np.arange(12), lows12, 1)[0]) / px * 1e4
        highs_slope = float(np.polyfit(np.arange(12), highs12, 1)[0]) / px * 1e4

        sups, ress = cls._pivot_levels(d, atr)
        cands_s = [g for g in sups if g["px"] <= px and (px - g["px"]) / atr <= 2.0]
        cands_r = [g for g in ress if g["px"] >= px and (g["px"] - px) / atr <= 2.0]
        nearest_support = max(cands_s, key=lambda g: g["px"]) if cands_s else None
        nearest_resistance = min(cands_r, key=lambda g: g["px"]) if cands_r else None

        hour_low = float(w["Low"].min())
        if nearest_support is not None and (px - nearest_support["px"]) / atr <= 1.5:
            zone_low = nearest_support["px"]
        else:
            zone_low = hour_low
        zone_high = min(vwap, zone_low + 1.0 * atr)
        if zone_high <= zone_low:
            zone_high = zone_low + 0.25 * atr
        in_zone_lvls = [g for g in sups if zone_low <= g["px"] <= zone_high]
        if in_zone_lvls:
            snap = max(in_zone_lvls, key=lambda g: g["strength"])
            limit, limit_snapped = snap["px"], True
        else:
            snap, limit, limit_snapped = None, (zone_low + zone_high) / 2.0, False
        invalid = limit - (0.30 if limit_snapped else 0.50) * atr
        ext_atr = (px - vwap) / atr

        # ---- نظام النقاط (يبدأ من 50) ----
        score = 50.0
        contrib = []

        def _add(pts, label):
            nonlocal score
            score += pts
            contrib.append((label, float(pts)))

        veto = None
        if px < invalid:
            veto = "SKIP"
        elif zone_low <= px <= zone_high:
            _add(15, "داخل منطقة الدخول")
        elif px <= zone_high + 0.25 * atr:
            _add(8, "قريب فوق المنطقة")
        elif ext_atr <= cls.EXT_WAIT:
            _add(3, "تراجع معقول مطلوب")
        elif ext_atr <= 2.5:
            _add(-8, "ممتد فوق المنطقة")
        else:
            veto = "SKIP_CHASE"
        if veto is None and px < zone_low:
            _add(-5, "تحت الدعم")

        if limit_snapped:
            _add(12 if snap["touches"] >= 2 else 7,
                 f"حد عند دعم ({snap['touches']} لمسات)")
        if nearest_support is not None and nearest_support["last_i"] >= len(d) - 12:
            _add(3, "دعم مُختبر حديثاً")
        if nearest_resistance is not None:
            room = (nearest_resistance["px"] - px) / atr
            if room >= 1.0:
                _add(5, "مساحة حتى المقاومة")
            elif room < 0.5:
                _add(-8, "سقف مقاومة قريب")

        if ema_up:
            _add(8, "اتجاه 5m صاعد")
        elif ema_dn:
            _add(-8, "اتجاه 5m هابط")
        if macd_hist > 0:
            _add(4, "MACD إيجابي")
            if macd_cross_up:
                _add(3, "تقاطع MACD صاعد")
        elif macd_hist < macd_hist_prev:
            _add(-4, "MACD سلبي متدهور")

        if 45.0 <= rsi5 <= 65.0:
            _add(6, f"RSI متوازن ({rsi5:.0f})")
        elif 40.0 <= rsi5 < 45.0 or 65.0 < rsi5 <= 70.0:
            _add(2, f"RSI مقبول ({rsi5:.0f})")
        elif rsi5 > 75.0:
            _add(-8, f"RSI متشبع ({rsi5:.0f})")
        elif rsi5 < 35.0:
            _add(-5, f"ضعف زخم ({rsi5:.0f})")
        if rsi_slope > 1.0:
            _add(4, "RSI صاعد")
        elif rsi_slope < -1.0:
            _add(-3, "RSI هابط")
        if stoch_cross_up and K < 40.0:
            _add(5, "تقاطع ستوكاستك صاعد")
        elif K > 80.0 and D > 80.0:
            _add(-4, "تشبع ستوكاستك")

        if bullish:
            _add(3, "شمعة صاعدة")
        if hammer and ll <= zone_low + 0.3 * atr:
            _add(5, "مطرقة عند الدعم 🔨")
        if bear_engulf:
            _add(-6, "ابتلاعية هابطة")
        if upper_wick > 2.0 * body + 1e-12:
            _add(-3, "رفض علوي")

        if vratio >= 1.2:
            _add(4, "حجم قوي")
        elif vratio < 0.6:
            _add(-3, "حجم ضعيف")
        if up_share >= 0.55:
            _add(4, "سيطرة شرائية")

        if lows_slope > 0.5:
            _add(3, "قيعان صاعدة")
        if highs_slope < -0.5:
            _add(-3, "قمم هابطة")
        if bb_pct < 0.05 and bullish:
            _add(3, "ارتداد حد بولينجر")
        elif bb_pct > 0.95:
            _add(-3, "ملامسة حد بولينجر العلوي")

        gmri = float(context.get("gmri", 0.5))
        if gmri > BOOST_GMRI:
            _add(5, "بيئة 4H صاعدة")
        elif gmri < RISK_OFF_GMRI:
            _add(-5, "بيئة 4H هابطة")

        score = float(np.clip(score, 0, 100))
        contrib.sort(key=lambda x: -x[1])

        if veto == "SKIP":
            verdict, verdict_ar, score = "SKIP", "تخطي — كسر الدعم", min(score, 25)
        elif veto == "SKIP_CHASE":
            if gmri > BOOST_GMRI:
                # [v87] ترند 4H قوي: الامتداد يستمر — مطاردة محسوبة بحد قريب بدل التخطي
                limit = max(limit, px - 0.5 * atr)
                verdict, verdict_ar = "WAIT_PULLBACK", "مطاردة محسوبة — حد قريب (ترند قوي)"
                score = float(np.clip(max(score, 50), 0, 67))
            else:
                verdict, verdict_ar, score = "SKIP_CHASE", "تخطي — ممتد (مطاردة خطرة)", min(score, 30)
        elif score >= 68:
            verdict, verdict_ar = "ENTER_NOW", "دخول فوري — إشارات مؤكدة"
        elif score >= 42:   # [v87] مركز الهضبة [40,45] — 50 هاوية (−14 نقطة)
            verdict, verdict_ar = "WAIT_PULLBACK", "انتظار تراجع — أمر حد"
        elif ext_atr > 1.0:
            verdict, verdict_ar = "SKIP_CHASE", "تخطي — نقاط ضعيفة وامتداد"
        else:
            verdict, verdict_ar = "SKIP", "تخطي — إشارات غير كافية"
        # [v93-V4] حد ضحل ×0.5 مثبت على سعر إشارة 4H (IS +6.6pp / OOS +11.7pp / كامل +31.5pp)
        _spx = float(context.get("signal_px", px))
        limit = _spx - (_spx - limit) * 0.5
        confidence = float(np.clip(score / 100.0, 0.05, 0.95))

        return {"ok": True, "price": px, "vwap": vwap,
                "support": nearest_support["px"] if nearest_support else zone_low,
                "resistance": nearest_resistance["px"] if nearest_resistance else float(w["High"].max()),
                "nearest_support": nearest_support, "nearest_resistance": nearest_resistance,
                "zone_low": zone_low, "zone_high": zone_high,
                "limit": limit, "limit_snapped": limit_snapped, "invalid": invalid,
                "atr_pct": atr_pct, "rsi5": rsi5, "rsi_arrow": rsi_arrow,
                "macd_txt": macd_txt, "stoch_txt": stoch_txt, "bb_txt": bb_txt,
                "candle_txt": candle_txt, "trend": trend, "trend_ar": trend_ar,
                "vratio": vratio, "ext_atr": ext_atr,
                "verdict": verdict, "verdict_ar": verdict_ar,
                "score": score, "confidence": confidence, "contrib": contrib,
                "reasons": [f"{p:+.0f} {lab}" for lab, p in contrib[:4]],
                "n_candles": len(w), "warmup": len(d), "last_time": d.index[-1]}


# ══════════════════════════════════════════════════════════════════════════════
# 2ج) فحص الإشارة الموحّد (مشترك بين الباكتست والفحص الحي — منطق v83 حرفياً)
# ══════════════════════════════════════════════════════════════════════════════
def _gate_verdict(gate, tkr, bar_time, gmri, signal_px=None):
    """حكم 5m لإشارة 4H: المنطقة من شموع 5m قبل شمعة الإشارة. None = لا بيانات."""
    gd = gate["m5"].get(tkr)
    if gd is None:
        return None
    ts = gd["ts"]
    if gate.get("strict", False):
        k = int(np.searchsorted(ts, int(bar_time.value), side="left"))
        if k < 24 or int(bar_time.value) - ts[k-1] > 5 * 60 * 1_000_000_000:
            return None
        if np.any(np.diff(ts[max(0, k-80):k]) != 5 * 60 * 1_000_000_000):
            return None
    j = int(__import__("numpy").searchsorted(ts, int(bar_time.value), side="left"))
    # [v103-fix] تحقق صارم من أن شمعة الإشارة داخل نافذة 5m الفعلية (منع تسرب المستقبل)
    if j >= len(ts) or ts[j] - int(bar_time.value) > 24 * 5 * 60 * 1_000_000_000:
        return None
    if j < 24:
        return None
    i = max(0, j - 80)
    sl = slice(i, j)
    df = pd.DataFrame({"Open": gd["o"][sl], "High": gd["h"][sl], "Low": gd["l"][sl],
                       "Close": gd["c"][sl], "Volume": gd["v"][sl]},
                      index=pd.to_datetime(ts[sl]))
    if len(df) < 24:
        return None
    _ctx = {"gmri": gmri}
    if signal_px is not None:
        _ctx["signal_px"] = float(signal_px)
    z = MicroEntryZoneEngine.compute_zone(df, context=_ctx)
    return z if z.get("ok") else None


def check_entry_signal(processed, tkr, t, p, gmri, median_roc, basket_rocs):
    """يفحص شروط الدخول لأصل واحد عند الشمعة t.
    يرجع: (ناجح, confluence, alpha, سعر_الإغلاق, atr, النمط, السبب)."""
    a = processed[tkr]
    _ap_ov = (p.get("asset_params") or {}).get(tkr) or {}
    if not _ap_ov.get("roc_free", False) and a["roc_60"][t] < median_roc - 0.05:
        return (False, 0.0, 0.0, np.nan, np.nan, "", "ROC_60 ضعيف")
    _mg = p.get("mom_gate", None)
    if _mg is not None and not _ap_ov.get("roc_free", False):
        _mg_mode = _mg.get("mode", "abs")
        _mg_th = float(_mg.get("theta", 0.0))
        _roc = a["roc_60"][t]
        if _mg_mode == "abs" and _roc < _mg_th:
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم")
        elif _mg_mode == "laggard" and median_roc > 0.0 and _roc < _mg_th:
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم")
        elif _mg_mode == "median" and _roc < median_roc - _mg_th:
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم")
        elif _mg_mode == "rank":
            if basket_rocs:
                _rank = sum(1.0 for _r in basket_rocs if _r < _roc) / len(basket_rocs)
                if _rank < _mg_th:
                    return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة الزخم (رتبة)")
    if bool(p.get("vol_filter", True)) and a["atr_n"][t] > a["atr_hi"][t]:
        return (False, 0.0, 0.0, np.nan, np.nan, "", "فلتر التقلب (إنهاك)")
    if not _ap_ov.get("btc_free", False) and p.get("btc_filter", False):
        _ba = processed.get("BTCUSDT")
        if _ba is not None and _ba["ok"][t] and np.isfinite(_ba["ema"][t]) \
                and np.isfinite(_ba["slope"][t]) \
                and not (_ba["c"][t] > _ba["ema"][t] and _ba["slope"][t] > 0):
            return (False, 0.0, 0.0, np.nan, np.nan, "", "بوابة BTC")

    pm = p
    _ap = p.get("asset_params")
    if _ap is not None and tkr in _ap:
        pm = dict(p)
        pm.update(_ap[tkr])

    c, o, e, s, atr_val = a["c"][t], a["o"][t], a["ema"][t], a["slope"][t], a["atr_n"][t]
    rm, rp, r = a["rsim"][t], a["rsip"][t], a["rsi"][t]
    entry_mode = pm.get("mode", "dip")
    # [H2] بوابة نظام S2: منع الدخول عندما اتساع السوق هابط (None = معطلة)
    _gm = pm.get("s2_gmri_min", None)
    if _gm is not None and gmri < float(_gm) \
            and entry_mode in pm.get("s2_gmri_modes", ("trend",)):
        return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "بوابة النظام (GMRI)")

    if entry_mode == "dip":
        if np.isnan(e) or np.isnan(s) or s <= 0 or c < e or a["l"][t] > e * (1 + pm["prox"]):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط dip: الهيكل/القرب")
        if np.isnan(rm) or np.isnan(rp) or not (pm["rsi_lo"] <= rm <= pm["rsi_hi"]):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط dip: نطاق RSI")
        if not (rp < pm["rsi_trig"] <= r) or c <= o:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط dip: زناد RSI/شمعة")
    elif entry_mode == "trend":
        if np.isnan(e) or np.isnan(s) or not np.isfinite(s) or s <= 0 or c < e:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط trend: فوق EMA صاعد")
        if np.isnan(r) or not (pm.get("tr_rsi_lo", 48.0) <= r <= pm.get("tr_rsi_hi", 82.0)):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط trend: نطاق RSI")
        hh = a["hh"][t]
        brk = (not np.isnan(hh)) and c > hh
        dip_ok = (a["l"][t] <= e * (1 + pm.get("prox", 0.03))
                  and not np.isnan(rm) and rm >= pm.get("tr_rm_lo", 48.0))
        if not (brk or dip_ok) or c <= o:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط trend: اختراق/تراجع")
    elif entry_mode == "floor":
        if np.isnan(rm) or not (rm <= pm.get("fl_rsi_dip", 32.0)):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: غطسة RSI")
        if np.isnan(r) or r < pm.get("fl_rsi_up", 28.0):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: ارتداد RSI")
        ll = a["ll"][t]
        if np.isnan(ll) or c <= o or c <= ll:
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: القاع")
        if np.isnan(e) or c > e * (1 + pm.get("fl_above_ema", 1.00)):
            return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "شرط floor: سقف EMA")
    else:
        return (False, 0.0, 0.0, np.nan, np.nan, entry_mode, "نمط مجهول")

    confluence = SynergyFusionArbiter.calculate_confluence(
        a["tech_struct"][t], a["psych_range"][t], a["mom_score"][t])
    _min_conf = pm.get("min_confluence", 0.30)
    _cs = pm.get("conf_sideways", None)
    _cg = pm.get("conf_strong", None)
    if _cs is not None and RISK_OFF_GMRI <= gmri <= BOOST_GMRI:
        _min_conf = float(_cs)
    elif _cg is not None and gmri > BOOST_GMRI:
        _min_conf = float(_cg)
    if confluence >= _min_conf:
        return (True, float(confluence), float(a["alpha"][t]), float(c),
                float(atr_val), entry_mode, "إشارة ✅")
    return (False, float(confluence), float(a["alpha"][t]), float(c),
            float(atr_val), entry_mode, f"تلاقي {confluence:.2f} < {_min_conf:.2f}")

# ══════════════════════════════════════════════════════════════════════════════
# 3) المحاكي فائق السرعة (منطق الدخول/الخروج/الحوكمة — مطابق لـ v83)
# ══════════════════════════════════════════════════════════════════════════════
class FastSimulator:
    @staticmethod
    def prepare_arrays(store, assets=None):
        asset_list = assets if assets is not None else ELITE_TRADEABLE_ASSETS
        tradeable_in_store = [sym for sym in asset_list if sym in store]
        union_index = sorted(set().union(*[store[sym].index for sym in tradeable_in_store + [BENCHMARK_ASSET]]))
        union_index = pd.DatetimeIndex(union_index)
        btc_df = store[BENCHMARK_ASSET]

        processed = {}
        for tkr in tradeable_in_store + [BENCHMARK_ASSET]:
            d_raw = TechnicalEngine.apply(store[tkr], btc_df).reindex(union_index)
            ok_tkr = ~d_raw["Close"].isna().to_numpy()  # التوافر الحقيقي قبل الملء
            d = d_raw.ffill().bfill()
            atr_hi = d["ATR_NORM"].rolling(ATR_QUANTILE_WINDOW, min_periods=120).quantile(EXHAUSTION_QUANTILE)
            prior_hh = d["High"].shift(1).rolling(8, min_periods=3).max()
            prior_ll = d["Low"].shift(1).rolling(5, min_periods=3).min()
            processed[tkr] = {
                "o": d["Open"].to_numpy(float), "h": d["High"].to_numpy(float),
                "l": d["Low"].to_numpy(float), "c": d["Close"].to_numpy(float),
                "ema": d["EMA"].to_numpy(float), "slope": d["SLOPE"].to_numpy(float),
                "rsi": d["RSI"].to_numpy(float), "rsip": d["RSI_PREV"].to_numpy(float),
                "rsim": d["RSI_MIN3"].to_numpy(float),
                "roc_60": np.nan_to_num(d["ROC_60"].to_numpy(float), nan=0.0),
                "alpha": np.nan_to_num(d["ALPHA"].to_numpy(float), nan=1.0),
                "tech_struct": d["TECH_STRUCT_SCORE"].to_numpy(float),
                "psych_range": d["PSYCH_RANGE_SCORE"].to_numpy(float),
                "mom_score": d["MOM_SCORE"].to_numpy(float),
                "atr_n": d["ATR_NORM"].to_numpy(float),
                "atr_hi": np.where(np.isnan(atr_hi.to_numpy(float)), np.inf, atr_hi.to_numpy(float)),
                "hh": prior_hh.to_numpy(float),
                "ll": prior_ll.to_numpy(float),
                "ok": ok_tkr,
            }
        return union_index, processed, tradeable_in_store

    @staticmethod
    def simulate_prepared(processed, union_index, tradeable_in_store, p,
                          start_t=0, end_t=None, initial_capital=None, quiet=False,
                          gate5m=None, journal=None, pool_tag=""):
        tradeable_in_store = [s for s in tradeable_in_store if s in processed]
        if end_t is None:
            end_t = len(union_index)

        T = end_t - start_t
        sub_index = union_index[start_t:end_t]

        friction = SystemConfig.TOTAL_FRICTION
        cash = float(initial_capital if initial_capital is not None else SystemConfig.INITIAL_CAPITAL)
        pos = {}
        peak_nav = float(cash)
        pending = []
        cooldown_until = {}
        nav_series = np.empty(T, dtype=float)
        closed_trades = []
        asset_attribution = {tkr: {"trades": 0, "wins": 0, "realized_usdt": 0.0} for tkr in tradeable_in_store}

        vol_filter_on = bool(p.get("vol_filter", True))
        cooldown_on = bool(p.get("cooldown_on", True))
        cooldown_normal = int(p.get("cooldown_normal", COOLDOWN_NORMAL))
        cooldown_sl = int(p.get("cooldown_sl", COOLDOWN_SL))
        risk_off_mult = float(p.get("risk_off_mult", 0.50))
        exec_mode = EXECUTION_MODE
        micro_on = bool(p.get("micro_entry", False))   # [v84] أوامر حد دقيقة بدل السوق
        micro_pending = []
        micro_stats = {"limits": 0, "chases": 0, "saved_bps": [], "entries": []}
        gate = gate5m if isinstance(gate5m, dict) else None   # [v86] بوابة 5m
        gate_pending = []
        gate_stats = {"checked": 0, "enters": 0, "limits": 0, "chases": 0,
                      "skipped": [], "nogate": 0, "saved_bps": []}
        cur_bar = {"idx": 0}

        def _open(tkr, price, spend, atr_val, tag="", signal_px=None):
            nonlocal cash
            if spend < SystemConfig.MIN_ORDER_USDT or cash < SystemConfig.MIN_ORDER_USDT:
                return
            spend = min(cash, spend)
            if not (price > 0 and not np.isnan(price)):
                return
            # Capture pre-entry NAV for the signal; never used in a trading decision.
            _nav_before = cash + sum(q["qty"] * processed[s]["c"][start_t + cur_bar["idx"]]
                                     for s, q in pos.items())
            cash -= spend
            net_spend = spend * (1 - friction)
            pos[tkr] = {
                "tag": tag,
                "entry": price,
                "qty": net_spend / price,
                "hi": price,
                "sl": price * (1 - atr_val * p["sl_atr_mult"]),
                "tgt1": price * (1 + atr_val * p["t1_atr_mult"]),
                "tgt2": price * (1 + atr_val * p["t2_atr_mult"]),
                "tgt1_g": atr_val * p["t1_atr_mult"],
                "tgt2_g": atr_val * p["t2_atr_mult"],
                "t1": False,
                "t2": False,
                "entry_t": cur_bar["idx"],
                "_t_open": sub_index[cur_bar["idx"]], "_spend": spend,
            }
            if journal is not None:
                ps = pos[tkr]
                journal.setdefault("entries", []).append({
                    "kind": "ENTRY", "pool": pool_tag, "ticker": tkr,
                    "time": ps["_t_open"], "price": float(price), "spend": float(spend),
                    "pool_allocation": float(spend / max(_nav_before, 1e-9)),
                    "qty": float(ps["qty"]), "sl": float(ps["sl"]),
                    "tgt1": float(ps["tgt1"]), "tgt2": float(ps["tgt2"]),
                    "atr": float(atr_val), "entry_tag": tag,
                    "signal_price": float(signal_px if signal_px else price),
                })
            micro_stats["entries"].append({
                "ticker": tkr, "time": sub_index[cur_bar["idx"]],
                "entry_px": price, "signal_px": (signal_px if signal_px else price),
                "spend": spend, "tag": tag})

        warmup = min(60, T // 10)
        bear_gmri_th = float(p.get("bear_gmri", 0.0))
        bear_persist = int(p.get("bear_persist", 30))
        rec_boost = float(p.get("rec_boost", 1.0))
        rec_bars = int(p.get("rec_bars", 48))
        bear_streak = 0
        rec_left = 0

        for idx, t in enumerate(range(start_t, end_t)):
            cur_bar["idx"] = idx
            if idx < warmup:
                nav_series[idx] = cash
                continue

            # ---- 0) تنفيذ الإشارات المؤجلة (وضع next_open فقط) ----
            if exec_mode == "next_open" and pending:
                for pen in pending:
                    a = processed[pen["tkr"]]
                    price = a["o"][t] if a["ok"][t] else a["c"][t]
                    _open(pen["tkr"], price, pen["spend"], pen["atr"])
                pending = []

            # ---- 0ب) أوامر الحد الدقيقة [v84]: لمس الحد = ملء، انتهاء المهلة = مطاردة ----
            if micro_on and micro_pending:
                still = []
                for mp in micro_pending:
                    a = processed[mp["tkr"]]
                    if not a["ok"][t] or mp["tkr"] in pos:
                        if mp["tkr"] not in pos:
                            still.append(mp)
                        continue
                    if a["l"][t] <= mp["limit"]:
                        _open(mp["tkr"], mp["limit"], mp["spend"], mp["atr"], tag="MICRO_LIMIT",
                              signal_px=mp["signal_px"])
                        micro_stats["limits"] += 1
                        micro_stats["saved_bps"].append(
                            (mp["signal_px"] - mp["limit"]) / mp["signal_px"] * 1e4)
                    elif t >= mp["timeout"]:
                        _open(mp["tkr"], a["c"][t], mp["spend"], mp["atr"], tag="MICRO_CHASE",
                              signal_px=mp["signal_px"])
                        micro_stats["chases"] += 1
                    else:
                        still.append(mp)
                micro_pending = still

            # ---- 0ج) حدود البوابة [v86]: فحص الملء على شموع 5m الحقيقية ----
            if gate is not None and gate_pending:
                gstill = []
                now_ns = int(sub_index[idx].value)
                for gp in gate_pending:
                    if gp["tkr"] in pos:
                        continue
                    gd = gate["m5"].get(gp["tkr"])
                    if gate.get("strict", False):
                        # Never infer a limit fill/chase across missing 5m observations.
                        if gd is None:
                            gate_stats["cancelled"] = gate_stats.get("cancelled", 0) + 1
                            continue
                        _lo = int(np.searchsorted(gd["ts"], gp["from_ns"], side="right"))
                        _hi = int(np.searchsorted(gd["ts"], now_ns, side="right"))
                        _step = 5 * 60 * 1_000_000_000
                        _span = gd["ts"][_lo:_hi]
                        if (not len(_span) or _span[0] != gp["from_ns"] + _step
                                or _span[-1] != now_ns or np.any(np.diff(_span) != _step)):
                            gate_stats["cancelled"] = gate_stats.get("cancelled", 0) + 1
                            continue
                    filled = False
                    if gd is not None:
                        i0 = int(np.searchsorted(gd["ts"], gp["from_ns"], side="right"))
                        i1 = int(np.searchsorted(gd["ts"], now_ns, side="right"))
                        if i1 > i0 and np.min(gd["l"][i0:i1]) <= gp["limit"]:
                            filled = True
                    if filled:
                        _open(gp["tkr"], gp["limit"], gp["spend"], gp["atr"],
                              tag="M5_LIMIT", signal_px=gp["signal_px"])
                        gate_stats["limits"] += 1
                        gate_stats["saved_bps"].append(
                            (gp["signal_px"] - gp["limit"]) / gp["signal_px"] * 1e4)
                    elif t >= gp["timeout"]:
                        if gate.get("no_chase", False):
                            gate_stats["cancelled"] = gate_stats.get("cancelled", 0) + 1
                        else:
                            a = processed[gp["tkr"]]
                            _open(gp["tkr"], a["c"][t], gp["spend"], gp["atr"],
                                  tag="M5_CHASE", signal_px=gp["signal_px"])
                            gate_stats["chases"] += 1
                    else:
                        gstill.append(gp)
                gate_pending = gstill

            # ---- مؤشر اتساع السوق GMRI ----
            total_active_assets = 0
            assets_above_ema = 0
            for tkr in tradeable_in_store:
                a = processed[tkr]
                if a["ok"][t]:
                    total_active_assets += 1
                    if a["c"][t] > a["ema"][t]:
                        assets_above_ema += 1
            gmri = (assets_above_ema / total_active_assets) if total_active_assets > 0 else 0.5

            # [v83] عدّاد الدببة المستمرة + ذراع دفعة التعافي
            if bear_gmri_th > 0:
                if gmri < bear_gmri_th:
                    bear_streak += 1
                else:
                    if bear_streak >= bear_persist:
                        rec_left = rec_bars
                    bear_streak = 0

            # ---- 1) إدارة الصفقات المفتوحة ----
            for tkr in list(pos.keys()):
                a = processed[tkr]
                if not a["ok"][t]:
                    continue
                ps = pos[tkr]
                hi, lo, cl, rsi, local_atr = a["h"][t], a["l"][t], a["c"][t], a["rsi"][t], a["atr_n"][t]

                if hi > ps["hi"]:
                    ps["hi"] = hi

                if ps["t2"]:
                    g = (ps["hi"] - ps["entry"]) / ps["entry"]
                    atr_trail = local_atr * p["trail_atr_mult"]
                    dist = atr_trail if g < 0.20 else (atr_trail * 0.70)
                    new_sl = ps["hi"] * (1 - dist)
                    if new_sl > ps["sl"]:
                        ps["sl"] = new_sl
                elif ps["t1"] and not ps["t2"]:
                    _t1_lock = float(p.get("t1_gain_lock", 0.0))
                    if _t1_lock > 0:
                        _g = (ps["hi"] - ps["entry"]) / ps["entry"]
                        _lock_level = ps["entry"] * (1.0 + 0.005 + _t1_lock * _g)
                        if _lock_level > ps["sl"]:
                            ps["sl"] = _lock_level

                # وقف الخسارة
                if lo <= ps["sl"]:
                    realized_val = ps["qty"] * ps["sl"] * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (ps["sl"] - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": pnl_usdt > 0, "type": "SL",
                                          "entry_tag": ps.get("tag", ""),
                                          "exit_price": float(ps["sl"]), "entry_price": float(ps["entry"]),
                                          "entry_time": ps["_t_open"], "spend": float(ps["_spend"]),
                                          "hold_h": (sub_index[idx] - ps["_t_open"]).total_seconds()/3600,
                                          "new_sl": float(ps["sl"]),
                                          "after_t1": bool(ps["t1"]), "after_t2": bool(ps["t2"])})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[tkr]["wins"] += 1
                    if cooldown_on:
                        cooldown_until[tkr] = t + cooldown_sl
                    del pos[tkr]
                    continue

                # الهدف الأول T1
                if not ps["t1"] and hi >= ps["tgt1"]:
                    sell_q = ps["qty"] * p["t1_frac"]
                    ps["qty"] -= sell_q
                    ps["t1"] = True
                    ps["sl"] = ps["entry"] * 1.005
                    realized_val = sell_q * ps["tgt1"] * (1 - friction)
                    pnl_usdt = realized_val - (sell_q * ps["entry"])
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": ps["tgt1_g"] * 100, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": True, "type": "T1_TP",
                                          "entry_tag": ps.get("tag", ""),
                                          "exit_price": float(ps["tgt1"]), "entry_price": float(ps["entry"]),
                                          "entry_time": ps["_t_open"], "spend": float(ps["_spend"]),
                                          "hold_h": (sub_index[idx] - ps["_t_open"]).total_seconds()/3600,
                                          "new_sl": float(ps["sl"]),
                                          "after_t1": bool(True), "after_t2": bool(False)})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["wins"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt

                # الهدف الثاني T2
                elif ps["t1"] and not ps["t2"] and hi >= ps["tgt2"]:
                    sell_q = ps["qty"] * p["t2_frac_of_rest"]
                    ps["qty"] -= sell_q
                    ps["t2"] = True
                    ps["sl"] = ps["entry"] * (1 + (local_atr * p["t2_lock_atr_mult"]))
                    realized_val = sell_q * ps["tgt2"] * (1 - friction)
                    pnl_usdt = realized_val - (sell_q * ps["entry"])
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": ps["tgt2_g"] * 100, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": True, "type": "T2_TP",
                                          "entry_tag": ps.get("tag", ""),
                                          "exit_price": float(ps["tgt2"]), "entry_price": float(ps["entry"]),
                                          "entry_time": ps["_t_open"], "spend": float(ps["_spend"]),
                                          "hold_h": (sub_index[idx] - ps["_t_open"]).total_seconds()/3600,
                                          "new_sl": float(ps["sl"]),
                                          "after_t1": bool(True), "after_t2": bool(True)})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["wins"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt

                # خروج تشبع الشراء
                adaptive_rsi_exit = p["rsi_exit"] + (4.0 if gmri > BOOST_GMRI else (-4.0 if gmri < RISK_OFF_GMRI else 0.0))
                if ps["t2"] and rsi >= adaptive_rsi_exit:
                    realized_val = ps["qty"] * cl * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (cl - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": pnl_usdt > 0, "type": "RSI_PEAK",
                                          "entry_tag": ps.get("tag", ""),
                                          "exit_price": float(cl), "entry_price": float(ps["entry"]),
                                          "entry_time": ps["_t_open"], "spend": float(ps["_spend"]),
                                          "hold_h": (sub_index[idx] - ps["_t_open"]).total_seconds()/3600,
                                          "new_sl": float(ps["sl"]),
                                          "after_t1": bool(ps["t1"]), "after_t2": bool(ps["t2"])})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[tkr]["wins"] += 1
                    if cooldown_on:
                        cooldown_until[tkr] = t + cooldown_normal
                    del pos[tkr]

                # [v101] الوقف الزمني: خروج سوقي بعد N شمعة بلا إغلاق (0 = مطفأ)
                _tsb = int(p.get("time_stop_bars", 0) or 0)
                if _tsb > 0 and tkr in pos and (idx - ps.get("entry_t", idx)) >= _tsb:
                    realized_val = ps["qty"] * cl * (1 - friction)
                    pnl_usdt = realized_val - (ps["qty"] * ps["entry"])
                    pnl_pct = (cl - ps["entry"]) / ps["entry"] * 100
                    cash += realized_val
                    closed_trades.append({"ticker": tkr, "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                                          "time": sub_index[idx], "is_win": pnl_usdt > 0, "type": "TIME_STOP",
                                          "entry_tag": ps.get("tag", ""),
                                          "exit_price": float(cl), "entry_price": float(ps["entry"]),
                                          "entry_time": ps["_t_open"], "spend": float(ps["_spend"]),
                                          "hold_h": (sub_index[idx] - ps["_t_open"]).total_seconds()/3600,
                                          "new_sl": float(ps["sl"]),
                                          "after_t1": bool(ps["t1"]), "after_t2": bool(ps["t2"])})
                    asset_attribution[tkr]["trades"] += 1
                    asset_attribution[tkr]["realized_usdt"] += pnl_usdt
                    if pnl_usdt > 0:
                        asset_attribution[tkr]["wins"] += 1
                    if cooldown_on:
                        cooldown_until[tkr] = t + cooldown_normal
                    del pos[tkr]

            # ---- صافي القيمة عند إغلاق الشمعة ----
            cur_nav = cash
            for tkr, ps in pos.items():
                cur_nav += ps["qty"] * processed[tkr]["c"][t]
            nav_series[idx] = cur_nav

            if cur_nav > peak_nav:
                peak_nav = cur_nav
            nav_dd = 1.0 - cur_nav / max(peak_nav, 1e-9)

            basket_rocs = [processed[sym]["roc_60"][t] for sym in tradeable_in_store
                           if processed[sym]["ok"][t] and not np.isnan(processed[sym]["roc_60"][t])]
            median_roc = np.median(basket_rocs) if basket_rocs else 0.0

            # ---- 2) فحص إشارات الدخول ----
            at_risk = sum(1 for x in pos.values() if not x["t1"])

            if gmri < RISK_OFF_GMRI:
                eff_risk_cap = min(1, p["max_risk"])
                eff_total_cap = min(1, p["max_total"])
                regime_multiplier = risk_off_mult
            else:
                eff_risk_cap = p["max_risk"]
                eff_total_cap = p["max_total"]
                regime_multiplier = p.get("boost", 1.35) if gmri > BOOST_GMRI else 1.00

            dd_freezer = float(p.get("dd_freezer", 0.0))
            if dd_freezer > 0 and nav_dd > dd_freezer + 0.05:
                eff_total_cap = 0
            elif dd_freezer > 0 and nav_dd > dd_freezer:
                eff_risk_cap = min(1, eff_risk_cap)
                eff_total_cap = min(1, eff_total_cap)
                regime_multiplier = min(regime_multiplier, 0.50)

            # [v83] تجميد أثناء حلقة دببة مستمرة + دفعة تعافٍ بعدها
            if bear_gmri_th > 0 and bear_streak >= bear_persist:
                eff_risk_cap = 0
                eff_total_cap = 0
            elif rec_left > 0 and rec_boost > 1.0:
                regime_multiplier = max(regime_multiplier, rec_boost)
            if rec_left > 0:
                rec_left -= 1

            if at_risk < eff_risk_cap and len(pos) < eff_total_cap:
                cands = []
                for tkr in tradeable_in_store:
                    a = processed[tkr]
                    if tkr in pos or not a["ok"][t]:
                        continue
                    if cooldown_on and cooldown_until.get(tkr, -10**9) >= t:
                        continue
                    ok, _cf, _al, _px, _at, _md, _rs = check_entry_signal(
                        processed, tkr, t, p, gmri, median_roc, basket_rocs)
                    if ok:
                        cands.append((_al, tkr, _px, _at))

                if cands:
                    cands.sort(reverse=True, key=lambda x: x[0])
                    slots = min(eff_risk_cap - at_risk, eff_total_cap - len(pos))
                    min_alpha_gap = float(p.get("min_alpha_gap", 0.0))
                    top_alpha = cands[0][0]
                    picked = []
                    for (al, tkr, price_close, atr_val) in cands:
                        if len(picked) >= slots:
                            break
                        if picked and min_alpha_gap > 0 and al < top_alpha * (1.0 - min_alpha_gap):
                            continue
                        picked.append((tkr, price_close, atr_val))

                    for rank_idx, (tkr, price_close, atr_val) in enumerate(picked):
                        w_idx = min(at_risk + rank_idx, len(p["alpha_weights"]) - 1)
                        base_allocation = cur_nav * p["alpha_weights"][w_idx]
                        _vt = float(p.get("vol_target", 0.035))
                        _vlo = float(p.get("vol_lo", 0.75))
                        _vhi = float(p.get("vol_hi", 1.40))
                        volatility_multiplier = np.clip(_vt / max(0.01, atr_val), _vlo, _vhi)
                        risk_budget = cur_nav * p.get("risk_pct", POSITION_RISK_PCT)
                        sl_dist = max(atr_val * p["sl_atr_mult"], 1e-6)
                        risk_cap_spend = risk_budget / sl_dist
                        spend = min(cash, base_allocation * regime_multiplier * volatility_multiplier,
                                    risk_cap_spend)
                        if spend < SystemConfig.MIN_ORDER_USDT:
                            break
                        _gate_tag = ""
                        if gate is not None:
                            gz = _gate_verdict(gate, tkr, union_index[t], gmri,
                                              signal_px=price_close)
                            gate_stats["checked"] += 1
                            if gz is None:
                                gate_stats["nogate"] += 1
                                if gate.get("strict", False):
                                    continue
                            elif gz["verdict"] in ("SKIP", "SKIP_CHASE"):
                                gate_stats["skipped"].append({
                                    "ticker": tkr, "time": union_index[t],
                                    "signal_px": price_close, "verdict": gz["verdict"],
                                    "score": round(gz["score"], 1)})
                                continue
                            elif gz["verdict"] == "WAIT_PULLBACK" and gz["limit"] < price_close \
                                    and not gate.get("wait_as_enter", False):
                                _dm = float(gate.get("depth_mult", 1.0))
                                _gl = price_close - (price_close - float(gz["limit"])) * _dm
                                if journal is not None:
                                    journal.setdefault("plans", []).append({
                                        "ticker": tkr, "pool": pool_tag, "time": union_index[t],
                                        "intent": "LIMIT", "price": float(_gl), "signal_price": float(price_close),
                                        "sl": float(_gl * (1-atr_val*p["sl_atr_mult"])),
                                        "tgt1": float(_gl * (1+atr_val*p["t1_atr_mult"])),
                                        "tgt2": float(_gl * (1+atr_val*p["t2_atr_mult"])),
                                        "pool_allocation": float(spend/max(cur_nav,1e-9)),
                                        "entry_tag": "M5_WAIT", "spend": float(spend)})
                                gate_pending.append({"tkr": tkr, "spend": spend, "atr": atr_val,
                                                     "limit": float(_gl),
                                                     "signal_px": price_close,
                                                     "from_ns": int(union_index[t].value),
                                                     "timeout": t + int(gate.get("timeout_bars", MICRO_TIMEOUT_BARS))})
                                continue
                            else:
                                gate_stats["enters"] += 1
                                _gate_tag = "M5_ENTER"
                        if exec_mode == "next_open":
                            pending.append({"tkr": tkr, "spend": spend, "atr": atr_val})
                        elif micro_on:
                            # [v84] أمر حد عند منتصف منطقة الدخول بدل الشراء السوقي
                            depth = min(MICRO_DEPTH_CAP, MICRO_DEPTH_ATR * atr_val)
                            micro_pending.append({"tkr": tkr, "spend": spend, "atr": atr_val,
                                                  "limit": price_close * (1.0 - depth * 0.5),
                                                  "signal_px": price_close,
                                                  "timeout": t + MICRO_TIMEOUT_BARS})
                        else:
                            _open(tkr, price_close, spend, atr_val,
                                  tag=_gate_tag, signal_px=price_close)

        if journal is not None:
            last_i = len(sub_index) - 1
            last_t = end_t - 1
            snap = []
            for tkr, ps in pos.items():
                a = processed[tkr]
                last_c = float(a["c"][last_t]) if a["ok"][last_t] else float(ps["entry"])
                snap.append({"pool": pool_tag, "ticker": tkr, "entry": float(ps["entry"]),
                             "qty": float(ps["qty"]), "sl": float(ps["sl"]),
                             "tgt1": float(ps["tgt1"]), "tgt2": float(ps["tgt2"]),
                             "t1": bool(ps["t1"]), "t2": bool(ps["t2"]),
                             "hi": float(ps["hi"]), "last_close": last_c,
                             "unrealized_usdt": float(ps["qty"] * (last_c - ps["entry"])),
                             "opened": pd.Timestamp(ps["_t_open"]).isoformat() if ps.get("_t_open") is not None else None,
                             "time": sub_index[last_i]})
            journal["final_pos"] = snap

        if journal is not None:
            journal["pending"] = [dict(x, pool=pool_tag) for x in gate_pending]
        nav_df = pd.DataFrame({"nav": nav_series}, index=sub_index)
        micro_stats["gate"] = gate_stats
        return nav_df, closed_trades, asset_attribution, micro_stats

# ══════════════════════════════════════════════════════════════════════════════
# 4) مصفوفة المقاييس الموحدة
# ══════════════════════════════════════════════════════════════════════════════
class MetricsEngine:
    @staticmethod
    def compute(nav_df, trades, initial_capital=None):
        initial_nav = float(initial_capital if initial_capital is not None else SystemConfig.INITIAL_CAPITAL)
        final_nav = float(nav_df["nav"].iloc[-1])
        total_ret = ((final_nav - initial_nav) / initial_nav) * 100
        total_days = max((nav_df.index[-1] - nav_df.index[0]).days, 1)

        daily_compounded = (((final_nav / initial_nav) ** (1.0 / total_days)) - 1.0) * 100
        daily_arithmetic = total_ret / total_days
        cagr = (((final_nav / initial_nav) ** (365.25 / total_days)) - 1.0) * 100

        peak = nav_df["nav"].cummax()
        dd = (nav_df["nav"] - peak) / np.where(peak == 0, 1e-9, peak) * 100
        max_dd = abs(float(dd.min()))

        df_tr = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["pnl_pct", "pnl_usdt", "is_win"])
        n_trades = len(df_tr)
        wins = df_tr[df_tr["is_win"] == True]
        losses = df_tr[df_tr["is_win"] == False]
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / n_trades * 100) if n_trades > 0 else 0.0
        total_gain = float(wins["pnl_usdt"].sum()) if n_wins > 0 else 0.0
        total_loss = abs(float(losses["pnl_usdt"].sum())) if n_losses > 0 else 1e-9
        pf = total_gain / total_loss if total_loss > 0 else 0.0
        avg_trade_pct = float(df_tr["pnl_pct"].mean()) if n_trades > 0 else 0.0
        avg_win = float(wins["pnl_usdt"].mean()) if n_wins > 0 else 0.0
        avg_loss = float(losses["pnl_usdt"].mean()) if n_losses > 0 else 0.0
        expectancy = float(df_tr["pnl_usdt"].mean()) if n_trades > 0 else 0.0

        returns = nav_df["nav"].pct_change().dropna()
        std_ret = float(returns.std()) if len(returns) > 0 else 0.0
        sharpe = (float(returns.mean()) / std_ret * math.sqrt(2190)) if std_ret > 0 else 0.0
        calmar = (cagr / max_dd) if max_dd > 0 else 0.0

        split_idx = int(len(nav_df) * SystemConfig.IS_RATIO)
        is_nav = nav_df.iloc[:split_idx]
        oos_nav = nav_df.iloc[split_idx:]
        is_ret = ((float(is_nav["nav"].iloc[-1]) - initial_nav) / initial_nav) * 100
        oos_start = float(is_nav["nav"].iloc[-1])
        oos_ret = ((float(oos_nav["nav"].iloc[-1]) - oos_start) / oos_start) * 100
        stability = (oos_ret / max(is_ret, 1e-9)) if is_ret > 0 else 1.0

        return {
            "period_start": nav_df.index[0].strftime("%Y-%m-%d"),
            "period_end": nav_df.index[-1].strftime("%Y-%m-%d"),
            "total_days": int(total_days),
            "final_nav": final_nav, "total_ret": total_ret,
            "daily_compound": daily_compounded, "daily_arithmetic": daily_arithmetic,
            "cagr": cagr, "max_dd": max_dd, "sharpe": sharpe, "calmar": calmar,
            "n_trades": n_trades, "n_wins": n_wins, "n_losses": n_losses,
            "win_rate": win_rate, "pf": pf, "avg_trade_pct": avg_trade_pct,
            "avg_win_usdt": avg_win, "avg_loss_usdt": avg_loss, "expectancy_usdt": expectancy,
            "is_ret": is_ret, "oos_ret": oos_ret, "stability": stability,
        }

    @staticmethod
    def compute_detailed(nav_df, trades, btc_df=None):
        nav = nav_df["nav"]
        daily = nav.resample("D").last().dropna()
        daily_ret = daily.pct_change().dropna()
        d_comp = (((daily.iloc[-1] / daily.iloc[0]) ** (1.0 / max(len(daily) - 1, 1))) - 1.0) * 100
        d_arith = ((daily.iloc[-1] - daily.iloc[0]) / daily.iloc[0]) * 100 / max(len(daily) - 1, 1)
        out = {
            "n_days": int(len(daily_ret)),
            "best_day": float(daily_ret.max()) * 100,
            "worst_day": float(daily_ret.min()) * 100,
            "avg_day": float(daily_ret.mean()) * 100,
            "median_day": float(daily_ret.median()) * 100,
            "pct_positive_days": float((daily_ret > 0).mean()) * 100,
            "daily_compound": d_comp,
            "daily_arithmetic": d_arith,
        }
        df_tr = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["pnl_pct", "pnl_usdt", "is_win"])
        if len(df_tr):
            wins = df_tr[df_tr["is_win"] == True]["pnl_usdt"]
            losses = df_tr[df_tr["is_win"] == False]["pnl_usdt"]
            out["largest_win_usdt"] = float(wins.max()) if len(wins) else 0.0
            out["largest_loss_usdt"] = float(losses.min()) if len(losses) else 0.0
            out["avg_win_usdt"] = float(wins.mean()) if len(wins) else 0.0
            out["avg_loss_usdt"] = float(losses.mean()) if len(losses) else 0.0
            out["expectancy_usdt"] = float(df_tr["pnl_usdt"].mean())
            out["avg_win_pct"] = float(df_tr[df_tr["is_win"] == True]["pnl_pct"].mean()) if len(wins) else 0.0
            out["avg_loss_pct"] = float(df_tr[df_tr["is_win"] == False]["pnl_pct"].mean()) if len(losses) else 0.0
            seq = [1 if w else 0 for w in df_tr["is_win"]]
            max_lose_streak = cur = 0
            for s in seq:
                cur = cur + 1 if s == 0 else 0
                max_lose_streak = max(max_lose_streak, cur)
            out["max_lose_streak"] = max_lose_streak
            out["max_win_streak"] = 0
            cur = 0
            for s in seq:
                cur = cur + 1 if s == 1 else 0
                out["max_win_streak"] = max(out["max_win_streak"], cur)
        else:
            for k in ("largest_win_usdt", "largest_loss_usdt", "avg_win_usdt", "avg_loss_usdt",
                      "expectancy_usdt", "avg_win_pct", "avg_loss_pct", "max_lose_streak", "max_win_streak"):
                out[k] = 0.0 if "usdt" in k or "pct" in k else 0
        peak = nav.cummax()
        dd_series = (nav - peak) / np.where(peak == 0, 1e-9, peak)
        underwater = dd_series < 0
        longest_dd_days = cur = 0
        for u in underwater:
            cur = cur + 1 if u else 0
            longest_dd_days = max(longest_dd_days, cur)
        out["longest_dd_candles"] = int(longest_dd_days)
        out["longest_dd_days"] = round(longest_dd_days / 6.0, 1)
        if btc_df is not None and len(btc_df):
            b = btc_df["Close"].reindex(nav.index).ffill().bfill()
            b0 = float(b.iloc[0]); b1 = float(b.iloc[-1])
            out["btc_bh_ret"] = ((b1 - b0) / b0) * 100
            bd = b.resample("D").last().dropna()
            bd_ret = bd.pct_change().dropna()
            out["btc_best_day"] = float(bd_ret.max()) * 100
            out["btc_worst_day"] = float(bd_ret.min()) * 100
            bpeak = b.cummax()
            bdd = (b - bpeak) / np.where(bpeak == 0, 1e-9, bpeak) * 100
            out["btc_max_dd"] = abs(float(bdd.min()))
        return out

# ══════════════════════════════════════════════════════════════════════════════
# 5) طبقة رأس المال الديناميكي (v78) — المجموع 400$ ثابت
# ══════════════════════════════════════════════════════════════════════════════
def combine_dynamic_capital(nav1, nav2, union_index, cfg=None):
    cfg = cfg or DYNAMIC_CAPITAL
    if not cfg.get("enabled", False):
        return nav1 + nav2, [], 0
    K = int(cfg.get("rebalance_days", 30))
    gamma = float(cfg.get("gamma", 8.0))
    R = int(cfg.get("lookback_days", 90))
    w_lo = float(cfg.get("w_s2_min", 0.25))
    w_hi = float(cfg.get("w_s2_max", 0.75))
    CPD = 6  # شموع 4H في اليوم
    days = union_index.normalize()
    bounds, last = set(), None
    for i in range(len(union_index)):
        if i > 0 and days[i] != days[i - 1]:
            if last is None or (days[i] - days[last]).days >= K:
                bounds.add(i)
                last = i
    a1, a2 = float(nav1[0]), float(nav2[0])
    out = np.empty(len(nav1))
    w2_hist = []
    for i in range(len(nav1)):
        if i in bounds and i > R * CPD:
            r1 = nav1[i - 1] / nav1[i - 1 - R * CPD] - 1.0
            r2 = nav2[i - 1] / nav2[i - 1 - R * CPD] - 1.0
            w2 = float(np.clip(0.5 + gamma * (r2 - r1), w_lo, w_hi))
            A = a1 + a2
            a1, a2 = A * (1.0 - w2), A * w2
            w2_hist.append(w2)
        if i > 0:
            a1 *= nav1[i] / nav1[i - 1]
            a2 *= nav2[i] / nav2[i - 1]
        out[i] = a1 + a2
    return out, w2_hist, len(w2_hist)

# ══════════════════════════════════════════════════════════════════════════════
# 6) مختبر التحسين (وضع --legacy: السلة الخماسية v59)
# ══════════════════════════════════════════════════════════════════════════════


def _pack_5m_arrays(m5store):
    """تحويل شموع 5m إلى مصفوفات numpy للبحث السريع داخل المحاكي."""
    packed = {}
    for sym, df in m5store.items():
        try:
            d = df.sort_index()
            packed[sym] = {
                "ts": d.index.values.astype("datetime64[ns]").astype("int64"),
                "o": d["Open"].to_numpy(float), "h": d["High"].to_numpy(float),
                "l": d["Low"].to_numpy(float), "c": d["Close"].to_numpy(float),
                "v": d["Volume"].to_numpy(float),
            }
        except Exception:
            continue
    return packed
