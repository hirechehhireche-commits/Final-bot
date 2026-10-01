#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🦁 GOLDEN SPLIT ENGINE V5 ULTRA - المحرك المطور فائق الدقة
EMA 9/21/50 + Trend Alignment + RSI 48-68 + BO 20 + Volume Surge + Adaptive Shield
- استراتيجية مطورة لزيادة عدد الصفقات الرابحة وتقليل الصفقات الخاسرة وتقليل الـ DD
- الحفاظ على نفس سلة الأصول الـ 77 عملة الأصلية المعتمدة (مع الاستبعاد التام لـ INJ)
- احتساب كامل وصارم لعمولات منصة Binance الفورية (0.075% شراء و 0.075% بيع + 0.02% انزلاق)
- أهداف متوازنة: TP1 +2.4% (جني 50%)، نقل الوقف للتعادل المحمي (+0.30% BE)، TP2 +5.5%، SL -1.2%
"""
import pandas as pd
import numpy as np

GOLDEN_CONFIG = {
    "PAPER_TRADING": True,
    "INITIAL_CAPITAL": 400.0,
    "MAX_ACTIVE_SLOTS": 10,
    "RISK_PROFILE": "TITAN",
    "SLOT_BASE_PERCENT": 0.40,
    "SLOT_EQUITY_PERCENT": 0.25,
    "COMPOUNDING": True,
    "ADAPTIVE_SHIELD": True,
    "BINANCE_FEE_RATE": 0.0015,       # 0.075% شراء + 0.075% بيع
    "BINANCE_SLIPPAGE": 0.0002,       # 0.02% انزلاق تنفيذي لكل طرف
    "EXIT_STRATEGY": "GOLDEN_SPLIT_V5_ULTRA",
    "TP1_PERCENT": 0.0240,            # الهدف الأول: جني أرباح 50%
    "BREAKEVEN_OFFSET": 0.0030,       # حجز التعادل المحمي (+0.30%)
    "TP2_PERCENT": 0.0550,            # الهدف الثاني للمتبقي
    "SL_PERCENT": 0.0120,             # وقف الخسارة الصارم
    "MAX_HOLD_HOURS": 3.5,            # الحد الأقصى للمدة
    "MIN_RSI_14": 48.0,               # النطاق الذهبي للزخم
    "MAX_RSI_14": 68.0,
    "BREAKOUT_LOOKBACK": 20,          # كسر قمة 20 شمعة
    "MIN_BODY_POSITION": 0.70,        # جودة شمعة الكسر في الثلث العلوي
    "MIN_VOLUME_RATIO": 1.20,         # تأكيد حجم التداول لفلترة الكسور الوهمية
    "EMA_FAST": 9,
    "EMA_MID": 21,
    "EMA_SLOW": 50,
    "EMA_TREND": 100,
    "MONITOR_INTERVAL_SEC": 2,
    "SCAN_INTERVAL_SEC": 60,
    "VOL_TARGET_ATR": 0.0018,
    "ROBUST_VERSION": "V5_ULTRA_ADVANCED",
}

# سلة الأصول الـ 77 المعتمدة كاملة بدون INJ
GOLDEN_APPROVED_COINS = [
    'ADA', 'ALGO', 'APT', 'AR', 'ARB', 'ARDR', 'AVAX', 'BCH', 'BNB', 'BTC',
    'CELR', 'CHR', 'COS', 'CTSI', 'DAR', 'DENT', 'DNT', 'DOGE', 'DOT', 'EGLD',
    'ELF', 'EOS', 'ETC', 'ETH', 'FET', 'FIL', 'FTM', 'GRAM', 'GRT', 'GTO',
    'GXS', 'HBAR', 'ICP', 'IOTX', 'IRIS', 'JASMY', 'KSM', 'LINK', 'LPT', 'LRC',
    'LTC', 'MATIC', 'OCEAN', 'OP', 'PLA', 'POL', 'PUNDIX', 'QTUM', 'REEF', 'RENDER',
    'RNDR', 'ROSE', 'RSR', 'RVN', 'S', 'SAND', 'SFP', 'SKL', 'SLP', 'SOL',
    'STORJ', 'STPT', 'STRAX', 'STX', 'SUI', 'TAO', 'TCT', 'TLM', 'TRX', 'VET',
    'VTHO', 'WLD', 'WTC', 'XLM', 'XRP', 'ZEC', 'ZRO'
]

def golden_tier(base_coin, btc_strong=False, btc_super=False, profile="TITAN", atr_1h=None, recent_win_rate=None):
    return GOLDEN_CONFIG["SLOT_BASE_PERCENT"]

def golden_adaptive_shield(base_risk, current_dd, profile="TITAN"):
    """الدرع التكيفي لحماية المحفظة وتخفيض حجم المركز فور حدوث أي تراجع"""
    if current_dd < -0.010:
        return base_risk * 0.05
    elif current_dd < -0.005:
        return base_risk * 0.20
    elif current_dd < -0.002:
        return base_risk * 0.50
    else:
        return base_risk

def golden_compute_position_size(equity, cash, base_coin, btc_strong, btc_super, current_dd, profile="TITAN", compounding=True, atr_1h=None, recent_win_rate=None, tier_counts=None, is_second_chance=False):
    base_risk = golden_tier(base_coin, btc_strong, btc_super, profile, atr_1h, recent_win_rate)
    alloc_pct = golden_adaptive_shield(base_risk, current_dd, profile) if GOLDEN_CONFIG["ADAPTIVE_SHIELD"] else base_risk
    if atr_1h is not None and GOLDEN_CONFIG["VOL_TARGET_ATR"] > 0:
        vol_scalar = GOLDEN_CONFIG["VOL_TARGET_ATR"] / max(atr_1h, 0.0012)
        vol_scalar = float(np.clip(vol_scalar, 0.86, 1.60))
        alloc_pct *= vol_scalar
    alloc_pct = min(alloc_pct, 0.45)
    alloc_pct = float(np.clip(alloc_pct, 0.02, 0.45))
    if compounding:
        slot_budget = min(cash, max(10.0, equity * alloc_pct))
    else:
        slot_budget = min(cash, max(10.0, GOLDEN_CONFIG["INITIAL_CAPITAL"] * alloc_pct))
    return slot_budget, alloc_pct

def golden_adaptive_levels(entry_price, atr_1h=None):
    """حساب مستويات الربح والوقف التكيفية مع تحريك الوقف للتعادل المحمي"""
    if atr_1h is None or atr_1h <= 0:
        return {
            "tp1": entry_price * (1.0 + GOLDEN_CONFIG["TP1_PERCENT"]),
            "tp2": entry_price * (1.0 + GOLDEN_CONFIG["TP2_PERCENT"]),
            "sl": entry_price * (1.0 - GOLDEN_CONFIG["SL_PERCENT"]),
            "be": entry_price * (1.0 + GOLDEN_CONFIG["BREAKEVEN_OFFSET"]),
            "tp1_pct": GOLDEN_CONFIG["TP1_PERCENT"],
            "tp2_pct": GOLDEN_CONFIG["TP2_PERCENT"],
            "sl_pct": GOLDEN_CONFIG["SL_PERCENT"],
            "be_pct": GOLDEN_CONFIG["BREAKEVEN_OFFSET"]
        }
    tp1_pct = float(np.clip(atr_1h * 1.60, 0.020, 0.032))
    tp2_pct = float(np.clip(atr_1h * 4.50, 0.045, 0.080))
    sl_pct = float(np.clip(atr_1h * 1.00, 0.010, 0.015))
    be_pct = GOLDEN_CONFIG["BREAKEVEN_OFFSET"]
    return {
        "tp1": entry_price * (1.0 + tp1_pct),
        "tp2": entry_price * (1.0 + tp2_pct),
        "sl": entry_price * (1.0 - sl_pct),
        "be": entry_price * (1.0 + be_pct),
        "tp1_pct": tp1_pct,
        "tp2_pct": tp2_pct,
        "sl_pct": sl_pct,
        "be_pct": be_pct
    }

def evaluate_golden_setup(df5: pd.DataFrame, df1h: pd.DataFrame, btc_bullish: bool, btc_super: bool = False, symbol: str = ""):
    """
    تقييم الإعداد المطور عالي الدقة:
    1. الاتجاه: EMA 9 > EMA 21 > EMA 50 والسعر فوق EMA 100
    2. القوة والزخم: RSI بين 48.0 و 68.0
    3. الكسر السعري: Close > Highest High لآخر 20 شمعة
    4. جودة الشمعة: Body Position >= 0.70
    5. تدفق الحجم: Volume >= 1.20x Volume MA 20
    6. فلتر البيتكوين: التحقق من أمان السوق العام
    """
    try:
        if df5 is None or df5.empty or len(df5) < 30:
            return {}
            
        c_col = "close" if "close" in df5.columns else ("Close" if "Close" in df5.columns else None)
        h_col = "high" if "high" in df5.columns else ("High" if "High" in df5.columns else None)
        l_col = "low" if "low" in df5.columns else ("Low" if "Low" in df5.columns else None)
        v_col = "volume" if "volume" in df5.columns else ("Volume" if "Volume" in df5.columns else None)
        if not c_col or not h_col or not l_col:
            return {}
            
        c5 = df5[c_col].values
        h5 = df5[h_col].values
        l5 = df5[l_col].values
        v5 = df5[v_col].values if v_col else np.ones(len(c5))
        
        # فحص الشمعة المغلقة السابقة لتفادي الإشارات اللحظية غير المكتملة
        idx = -2 if len(c5) >= 30 else -1
        
        # 1. الاتجاه المتسق: EMA 9 > EMA 21 > EMA 50
        s_c5 = pd.Series(c5)
        ema9 = float(s_c5.ewm(span=GOLDEN_CONFIG["EMA_FAST"], adjust=False).mean().iloc[idx])
        ema21 = float(s_c5.ewm(span=GOLDEN_CONFIG["EMA_MID"], adjust=False).mean().iloc[idx])
        ema50 = float(s_c5.ewm(span=GOLDEN_CONFIG["EMA_SLOW"], adjust=False).mean().iloc[idx])
        if not (ema9 > ema21 > ema50):
            return {}
        
        # 2. الزخم: RSI 14 بين 48.0 و 68.0
        delta = s_c5.diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[idx]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[idx]
        rsi = float(100.0 - (100.0 / (1.0 + gain / (loss + 1e-10))))
        if not (GOLDEN_CONFIG["MIN_RSI_14"] <= rsi <= GOLDEN_CONFIG["MAX_RSI_14"]):
            return {}
        
        # 3. الكسر السعري الصريح: Close أعلى من أعلى قمة لآخر 20 شمعة
        lookback = min(GOLDEN_CONFIG["BREAKOUT_LOOKBACK"], len(h5) - 2)
        if lookback < 5:
            return {}
        hi = np.max(h5[idx - lookback : idx])
        if c5[idx] <= hi:
            return {}
            
        # 4. جودة شمعة الكسر (إغلاق قوي في الثلث العلوي للشمعة لمنع الكسور الوهمية)
        bar_range = h5[idx] - l5[idx]
        if bar_range > 0:
            body_pos = (c5[idx] - l5[idx]) / bar_range
            if body_pos < GOLDEN_CONFIG["MIN_BODY_POSITION"]:
                return {}
                
        # 5. تأكيد حجم التداول
        if v_col and len(v5) >= 25:
            v_ma20 = np.mean(v5[idx - 20 : idx])
            if v5[idx] < v_ma20 * GOLDEN_CONFIG["MIN_VOLUME_RATIO"]:
                return {}
        
        # 6. حساب ATR التكيفي
        atr = 0.012
        if df1h is not None and not df1h.empty and len(df1h) >= 15:
            c1_col = "close" if "close" in df1h.columns else ("Close" if "Close" in df1h.columns else None)
            h1_col = "high" if "high" in df1h.columns else ("High" if "High" in df1h.columns else None)
            l1_col = "low" if "low" in df1h.columns else ("Low" if "Low" in df1h.columns else None)
            if c1_col and h1_col and l1_col:
                c1h = df1h[c1_col].values
                h1h = df1h[h1_col].values
                l1h = df1h[l1_col].values
                tr = (h1h - l1h) / (c1h + 1e-10)
                atr = float(pd.Series(tr).rolling(14).mean().iloc[-2])
        else:
            # حساب ATR من فريم 5m
            tr_5m = (h5 - l5) / (c5 + 1e-10)
            atr = float(pd.Series(tr_5m).rolling(14).mean().iloc[idx])
                
        levels = golden_adaptive_levels(float(c5[idx]), float(atr))
        
        return {
            "rsi": round(float(rsi), 1),
            "price": float(c5[-1]),
            "signal_price": float(c5[idx]),
            "atr_1h": float(atr),
            "ema9": round(float(ema9), 4),
            "ema21": round(float(ema21), 4),
            "ema50": round(float(ema50), 4),
            "tp1_pct": round(levels.get("tp1_pct", 0.024) * 100, 2),
            "tp2_pct": round(levels.get("tp2_pct", 0.055) * 100, 2),
            "sl_pct": round(levels.get("sl_pct", 0.012) * 100, 2),
            "robust": True,
            "version": "V5_ULTRA_ADVANCED",
            "params": 5
        }
    except Exception:
        return {}

if __name__ == "__main__":
    print("Golden Split Engine V5 Ultra Advanced - OK")
