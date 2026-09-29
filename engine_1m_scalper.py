#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  1-MINUTE HIGH-MOMENTUM SCALPER ENGINE (محرك سكالبينغ فريم 1 دقيقة)
  ═════════════════════════════════════════════════════════════════════════════
  • استراتيجية سكالبينغ فائقة السرعة على فريم 1 دقيقة.
  • تعتمد على نفس مبادئ استراتيجية TITAN:
    1. فلترة الاتجاه الصاعد عبر تقارب المتوسطات (EMA 20 > EMA 50).
    2. كسر القمم السعرية مع تدفق سيولة حقيقية (Volume Surge >= 1.8x).
    3. فلترة التذبذب (ATR >= 0.20%) لضمان تغطية رسوم بايننس والانزلاق.
    4. أهداف سريعة: T1 = +1.20% مع رفع الوقف للتعادل المحمي (+0.25%)، و T2 = +2.50%.
    5. خروج زمني واقٍ (Time Stop = 25 دقيقة) لمنع تجميد السيولة في النطاق العرضي.
    6. احتساب صارم لرسوم بايننس (0.25% ذهاباً وإياباً).
═══════════════════════════════════════════════════════════════════════════════
"""

import numpy as np
import pandas as pd

class ScalperConfig:
    EMA_FAST = 20
    EMA_SLOW = 50
    RSI_PERIOD = 9
    MIN_RSI = 50.0
    MAX_RSI = 75.0
    BREAKOUT_BARS = 15
    MIN_VOL_SURGE = 1.80
    MIN_ATR_RATIO = 0.0020        # تذبذب أدنى 0.20% لتغطية العمولات
    
    TP1_PCT = 0.0120              # الهدف الأول +1.20%
    TP2_PCT = 0.0250              # الهدف الثاني +2.50%
    SL_PCT = 0.0100               # وقف الخسارة -1.00%
    BREAKEVEN_LOCK_PCT = 0.0025   # تعادل محمي +0.25% (فوق سعر الدخول لتغطية العمولات)
    MAX_HOLD_BARS = 25            # خروج زمني بعد 25 دقيقة
    
    BINANCE_FRICTION = 0.0025     # 0.25% عمولة كاملة وانزلاق سعري


def evaluate_1m_scalp(df_1m: pd.DataFrame, symbol: str) -> dict:
    """
    تقييم شمعة 1m الأخيرة لعملة معينة وإرجاع خطة تداول سكالبينغ فورية إذا توفرت الشروط
    """
    if df_1m is None or len(df_1m) < 60:
        return None

    c = df_1m['Close'].values
    h = df_1m['High'].values
    l = df_1m['Low'].values
    v = df_1m['Volume'].values
    
    i = len(c) - 1
    curr_px = float(c[i])
    if curr_px <= 0:
        return None

    # EMA 20, 50
    ema20 = pd.Series(c).ewm(span=ScalperConfig.EMA_FAST, adjust=False).mean().values
    ema50 = pd.Series(c).ewm(span=ScalperConfig.EMA_SLOW, adjust=False).mean().values

    # Volume Surge
    vol_ma = pd.Series(v).rolling(20).mean().values
    if np.isnan(vol_ma[i]) or vol_ma[i] <= 0:
        return None
    vol_ratio = v[i] / vol_ma[i]

    # ATR 14
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    atr_val = pd.Series(tr).rolling(14).mean().values[i]
    if np.isnan(atr_val) or (atr_val / curr_px) < ScalperConfig.MIN_ATR_RATIO:
        return None  # تذبذب ضعيف لا يكفي لتغطية عمولة بايننس

    # RSI 9
    delta = pd.Series(c).diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/ScalperConfig.RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/ScalperConfig.RSI_PERIOD, adjust=False).mean()
    rs = gain / (loss + 1e-9)
    rsi_val = float((100 - (100 / (1 + rs))).values[i])

    # فحص شروط الدخول السكالبينغ
    trend_ok = (curr_px > ema20[i] > ema50[i]) and (ema20[i] > ema20[i-1])
    breakout_high = np.max(h[max(0, i - ScalperConfig.BREAKOUT_BARS):i])
    breakout_ok = curr_px >= breakout_high
    volume_ok = vol_ratio >= ScalperConfig.MIN_VOL_SURGE
    rsi_ok = ScalperConfig.MIN_RSI <= rsi_val <= ScalperConfig.MAX_RSI

    if trend_ok and breakout_ok and volume_ok and rsi_ok:
        entry_px = curr_px
        plan = {
            "strategy": "SCALP_1M",
            "ticker": symbol if symbol.endswith("USDT") else f"{symbol}USDT",
            "timeframe": "1m",
            "signal_price": entry_px,
            "sl": round(entry_px * (1.0 - ScalperConfig.SL_PCT), 6),
            "tgt1": round(entry_px * (1.0 + ScalperConfig.TP1_PCT), 6),
            "tgt2": round(entry_px * (1.0 + ScalperConfig.TP2_PCT), 6),
            "be_price": round(entry_px * (1.0 + ScalperConfig.BREAKEVEN_LOCK_PCT), 6),
            "size_pct": 5.0,  # تخصيص سريع 5% للصفقة
            "vol_ratio": round(vol_ratio, 2),
            "rsi": round(rsi_val, 1),
            "time_stop_bars": ScalperConfig.MAX_HOLD_BARS,
            "est_friction_pct": round(ScalperConfig.BINANCE_FRICTION * 100, 2),
            "chase_limit_pct": 0.30
        }
        return plan

    return None


def run_1m_scalper_batch(cache_1m_dict: dict) -> list:
    """مسح سلة الكاش الحقيقية لفريم 1 دقيقة واستخراج أفضل إشارات السكالبينغ النشطة"""
    plans = []
    for sym, df in cache_1m_dict.items():
        try:
            p = evaluate_1m_scalp(df, sym)
            if p:
                plans.append(p)
        except Exception:
            continue
    # ترتيب الإشارات حسب قوة زخم السيولة
    plans.sort(key=lambda x: x.get("vol_ratio", 1.0), reverse=True)
    return plans
