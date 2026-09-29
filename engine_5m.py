# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  ENGINE 5M — محرك الدخول والخروج الدقيق بفريم 5 دقائق (محرك منفصل كلياً)
  ═════════════════════════════════════════════════════════════════════════════
  محرك مستقل للباكتست والتداول الورقي على شموع 5m، فيه:
    1) طبقة بيانات 5m: كاش محلي + جلب (Binance ثم Yahoo — ‎60 يوماً كحد أقصى 5m).
    2) استراتيجية 5m كاملة: دخولان (trend اختراق / dip تراجع في اتجاه)
       + مُحيّز إطار أعلى (EMA-21 على 4h) أو بوابة نظام 4h (EMA-9 > EMA-21).
       ⚖️ قانون أرضية الاحتكاك (مُقاس على 60 يوماً حقيقية): احتكاك 0.3% ذهاب/إياب
          يلتهم أي هدف < 2.5×ATR(5m) — العائلة القابلة للبحث: hh_w≥48 + هدف ≥3.5×ATR.
       ⚙️ تنفيذ maker (v1.3 / H60): الدخول بأمر limit تحت سعر الإشارة (يُملأ عند
          اللمس خلال مدة الصلاحية وإلا يُلغى) + رسوم maker على الدخول وهدف T1 —
          درس المسح: سقف ربحية الذراع هو تكلفة التنفيذ (الانقلاب عند 0.10%/جهة).
       🛡️ H65 (v1.3.3): قطع خلفي على مسافات الوقف/الهدف/الترايل — التشخيص أثبت
          أن المسافات الفعلية تتضخم تفاوتياً بين الرموز (خسائر TIME حتى −12.5%).
          max/min_sl_frac تقيد النسبة النهائية دون تغيير أي شيء حين تكون None
          (تطابق بتّي مع شهادة v1.3.2 — مُتحقق منه آلياً).
       🤝 الانسجام (v1.2): الذراع 5m تقرأ نفس دماغ البوت 4h — مؤشر الاتساع GMRI
          (نسبة الرموز فوق EMA-21 على 4h) بعتبات البوت نفسها: تحت RISK_OFF_GMRI=0.35
          لا دخولات، وفوق BOOST_GMRI=0.65 دفعة ×1.25 — وعلى --combined تشغيل موحّد
          لرأس مال مشترك (البوت + الذراع) بتقرير واحد للربح وعدد الصفقات.
    3) إدارة خروج دقيقة 5m: وقف ATR + هدف جزئي T1 + قفل تعادل + ترايل ATR
       + خروج RSI تشبع + وقف زمني — كلها على فريم 5m حرفياً.
    4) محاكي محفظة (نقدية مشتركة، سقف مراكز، احتكاك 0.15%، حد أدنى 5$).
    5) ★ محرك التدريب والتطوير ★ (Lab5M): شبكة IS (60%) → هضبة → طيات (2/3
       مع قاعدة المرشح الحدي 3/3) → شهادة وحيدة ببوابة 5m (DD ≤ 18 مطلقاً).

  █ التشغيل:
      python3 engine_5m.py                     # باكتست 5m بالإعدادات المعتمدة
      python3 engine_5m.py --train             # دورة تدريب كاملة (شبكة + طيات + شهادة)
      python3 engine_5m.py --refresh           # جلب شموع 5m جديدة قبل التشغيل
      python3 engine_5m.py --live              # فحص حي: قرارات دخول/خروج على آخر شمعة 5m مغلقة
      python3 engine_5m.py --days 45           # نافذة أقصر

  ⚠️ القرار المعتمد يُحفظ في results/engine5m_config.json ويُحمَّل تلقائياً في كل تشغيل.
     ملاحظة: Sharpe في تقارير هذا المحرك معاير سنوياً لفريم 5m (×√48 على تقدير 4H).
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import math
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

try:
    import titan_juggernaut_bot as T        # الأولوية دائماً للبوت الحقيقي (سلوك بتّي)
    _BOT_AVAILABLE = True
except Exception:
    T = None
    _BOT_AVAILABLE = False

if T is None:
    # ══ وضع الاستقلال الذاتي: نفس الواجهة بديلاً داخلياً — الملف يعمل وحده ══
    class _MetricsEngine:
        """نسخة مطابقة المنطق لـ MetricsEngine.compute في البوت (للاستقلال فقط)."""
        @staticmethod
        def compute(nav_df, trades, initial_capital=None):
            initial_nav = float(initial_capital if initial_capital is not None else 100.0)
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
            n_wins, n_losses = len(wins), len(losses)
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
            split_idx = int(len(nav_df) * 0.60)
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

    class _SystemConfig:
        INITIAL_CAPITAL = 100.0
        MIN_ORDER_USDT = 5.0
        FEE_RATE = 0.0010
        SLIPPAGE_RATE = 0.0005
        TOTAL_FRICTION = FEE_RATE + SLIPPAGE_RATE
        IS_RATIO = 0.60
        _HERE = os.path.dirname(os.path.abspath(__file__))
        CACHE_DIR = os.path.join(_HERE, "cache")
        M5_CACHE_FILE = "titans_5m_cache.pkl"
        RESULTS_DIR = os.path.join(_HERE, "results")

    class _StandaloneBot:
        """واجهة بديلة بنفس ثوابت البوت + محمّل yfinance ذاتي لشموع 5m."""
        SystemConfig = _SystemConfig
        MetricsEngine = _MetricsEngine
        RISK_OFF_GMRI = 0.35
        BOOST_GMRI = 0.65
        TOTAL_CAPITAL = 400.0
        _YF_MAP = {"BTCUSDT": "BTC-USD", "SOLUSDT": "SOL-USD", "BNBUSDT": "BNB-USD",
                   "XRPUSDT": "XRP-USD", "DOTUSDT": "DOT-USD", "FETUSDT": "FET-USD",
                   "ETHUSDT": "ETH-USD", "XLMUSDT": "XLM-USD", "HBARUSDT": "HBAR-USD",
                   "TRXUSDT": "TRX-USD", "LINKUSDT": "LINK-USD", "ADAUSDT": "ADA-USD",
                   "LTCUSDT": "LTC-USD", "DOGEUSDT": "DOGE-USD", "ARBUSDT": "ARB-USD",
                   "BCHUSDT": "BCH-USD", "ETCUSDT": "ETC-USD", "EOSUSDT": "EOS-USD",
                   "VETUSDT": "VET-USD", "ZECUSDT": "ZEC-USD"}

        @staticmethod
        def _fmt_px(x):
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

        @staticmethod
        def load_5m_data(force_refresh=False, days=60, source="auto"):
            import yfinance as _yf
            days = int(days)
            os.makedirs(_SystemConfig.CACHE_DIR, exist_ok=True)
            cache_path = os.path.join(_SystemConfig.CACHE_DIR, _SystemConfig.M5_CACHE_FILE)
            store, need = {}, max(500, days * 50)
            if not force_refresh and os.path.exists(cache_path):
                try:
                    obj = pd.read_pickle(cache_path)
                    if isinstance(obj, dict) and obj.get("days") == days and isinstance(obj.get("data"), dict):
                        store = obj["data"]
                        print(f"[CACHE-5m] ✅ تحميل كاش ({len(store)} رمزاً) — وضع مستقل")
                except Exception as e:
                    print(f"[WARN] تعذر قراءة كاش 5m ({e}).")
            missing = [s for s in _StandaloneBot._YF_MAP
                       if s not in store or not isinstance(store[s], pd.DataFrame) or len(store[s]) < need]
            if not force_refresh and not missing:
                return store
            print(f"📥 [مستقل] جلب شموع 5m لآخر {min(days, 60)} يوماً ({len(missing)} رمزاً) عبر yfinance ...")
            for usdt, ysym in _StandaloneBot._YF_MAP.items():
                if usdt in store and isinstance(store[usdt], pd.DataFrame) and len(store[usdt]) >= need:
                    continue
                try:
                    df = _yf.download(ysym, period=f"{min(days, 60)}d", interval="5m",
                                      progress=False, auto_adjust=False, threads=False)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df = df.dropna(subset=["Open", "High", "Low", "Close"])
                    if len(df) >= need:
                        df.index = pd.DatetimeIndex(df.index).tz_localize("UTC") \
                            if df.index.tz is None else pd.DatetimeIndex(df.index).tz_convert("UTC")
                        store[usdt] = df[["Open", "High", "Low", "Close", "Volume"]]
                        print(f"  ✅ {usdt:12s} -> {len(df):,d} شمعة 5m")
                    else:
                        print(f"  ❌ {usdt:12s} -> بيانات غير كافية")
                except Exception as e:
                    print(f"  ⚠️ {usdt:12s}: {e}")
            if store:
                try:
                    tmp = cache_path + ".tmp"
                    pd.to_pickle({"days": days, "data": store}, tmp)
                    os.replace(tmp, cache_path)
                    print(f"[CACHE-5m] 💾 حُفظت في: {cache_path}")
                except Exception as e:
                    print(f"[WARN] تعذر حفظ كاش 5m: {e}")
            return store

    T = _StandaloneBot()
    print("[ENGINE-5m] 🛡️ وضع الاستقلال الذاتي — يعمل دون titan_juggernaut_bot.py")

ENGINE5M_VERSION = "1.3.3"
RESULT_DIR = T.SystemConfig.RESULTS_DIR
CONFIG_FILE = os.path.join(RESULT_DIR, "engine5m_config.json")
POS_FILE = os.path.join(RESULT_DIR, "engine5m_positions.json")

FRICTION = T.SystemConfig.TOTAL_FRICTION
MIN_ORDER = T.SystemConfig.MIN_ORDER_USDT
ANNUAL_5M = math.sqrt(48.0)   # تصحيح معايرة الشارب من فريم 4H إلى 5m

# ─── المعاملات الأساسية للمحرك (تُستبدل بمعتمدات التدريب من engine5m_config.json إن وُجدت)
BASE5M = dict(
    mode="trend",            # trend: اختراق في اتجاه | dip: تراجع في اتجاه صاعد
    ema_fast=9, ema_slow=21,
    hh_w=96,                 # نافذة الاختراق بالشموع (96×5m = 8 ساعات) — قانون أرضية الاحتكاك
    regime4h=True,           # بوابة نظام 4h: السعر > EMA-21 و EMA-9 > EMA-21
    rsi_lo=46.0, rsi_hi=72.0, rsi_exit=78.0,
    sl_atr=3.0, tgt1_atr=4.5, t1_frac=0.4, trail_atr=2.5,   # ترايل v1.1 المعتمد شهادياً
    time_stop_bars=576,      # 48 ساعة من شموع 5m
    maker=False,             # ⚙️ H60: تنفيذ maker (أمر limit + رسوم مخفضة) — شهادياً
    fee_maker=0.0005,        # رسوم maker/جهة (متحفظ؛ المتفائل 0.0002 يُفصح عنه)
    limit_off=0.0010,        # مسافة أمر الحد تحت سعر الإشارة
    limit_exp=12,            # صلاحية أمر الحد بالشموع (12×5m = ساعة)
    max_sl_frac=None,        # 🛡️ H65: أقصى مسافة وقف فعلية كسورة (None = معطل)
    min_sl_frac=None,        # 🛡️ H65: أدنى مسافة وقف فعلية كسورة (None = معطل)
    risk_pct=0.012, alloc=0.30, max_total=4,
    harmony=True,            # 🤝 الانسجام: بوابة GMRI — نفس دماغ البوت (عتباته نفسها)
    h_off=float(T.RISK_OFF_GMRI), h_boost=float(T.BOOST_GMRI),
    bias4h=True,             # لا شراء تحت EMA-21 على إطار 4h (فعّالة مع regime4h معاً)
    gap_fill=False,          # ملء الوقف عبر الفجوة min(افتتاح, وقف)
    prox=0.004,              # قرب التراجع من EMA البطيئة (نمط dip)
    warmup=200,
)


def load_config():
    """المعتمدات المحفوظة من آخر تدريب (تسود على BASE5M)."""
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
            if cfg.get("engine_version") != ENGINE5M_VERSION:
                print(f"[CONFIG] ⚠️ معتمدات v{cfg.get('engine_version', '?')} من إصدار أقدم — "
                      f"تُتجاهل (v{ENGINE5M_VERSION} يتطلب إعادة تدريب).")
                return dict(BASE5M)
            print(f"[CONFIG] ✅ معتمدات التدريب المحفوظة v{cfg.get('engine_version', '?')} "
                  f"({cfg.get('adopted_date', '?')})")
            return {**BASE5M, **cfg["params"]}
        except Exception as e:
            print(f"[WARN] تعذر قراءة engine5m_config.json ({e}) — الأساس.")
    return dict(BASE5M)


# ════════════════════════════════════════════════════════════════
# 1) تجهيز المصفوفات (لكل رمز: مؤشرات 5m + مُحيّز 4h)
# ════════════════════════════════════════════════════════════════


def _h65_clamp(entry, level, tgt_mult_cap=1.5, max_frac=None, min_frac=None):
    """🛡️ H65: يقصّ مسافة مستوى عن الدخول إلى [min_frac, max_frac] كسورة.
    يعيد المستوى نفسه إن لم يُقصّ (تطابق بتّي مع السلوك المعتمد)."""
    frac = (entry - level) / entry
    nf = frac
    if max_frac is not None and nf > float(max_frac):
        nf = float(max_frac)
    if min_frac is not None and nf < float(min_frac):
        nf = float(min_frac)
    if nf == frac:
        return level
    return entry * (1.0 - nf)


def _h65_cap_up(entry, level, max_frac=None):
    """🛡️ H65 للأهداف (فوق الدخول): سقف النسبة فقط."""
    frac = (level - entry) / entry
    if max_frac is not None and frac > float(max_frac):
        return entry * (1.0 + float(max_frac))
    return level



def prepare_5m(store5, p=None):
    p = p or {}
    hh_w = int(p.get("hh_w", 12))
    regime = bool(p.get("regime4h", False))
    syms = [s for s, d in store5.items() if isinstance(d, pd.DataFrame) and len(d) >= 3000]
    if len(syms) < 5:
        raise SystemExit(f"❌ رموز 5m كافية غير متوفرة ({len(syms)}) — شغّل --refresh.")
    uidx = sorted(set().union(*[store5[s].index for s in syms]))
    uidx = pd.DatetimeIndex(uidx)
    # 🤝 GMRI — نفس دماغ البوت: اتساع السوق = نسبة الرموز فوق EMA-21 على 4h
    c4s = {s: store5[s]["Close"].resample("4h").last().dropna() for s in syms}
    u4 = pd.DatetimeIndex(sorted(set().union(*[c4.index for c4 in c4s.values()])))
    _ab = np.zeros(len(u4)); _ac = np.zeros(len(u4))
    for c4 in c4s.values():
        _ab += (c4 > c4.ewm(span=21, adjust=False).mean()).astype(float).reindex(u4).fillna(0.0).to_numpy(float)
        _ac += pd.Series(1.0, index=c4.index).reindex(u4).fillna(0.0).to_numpy(float)
    gmri4 = pd.Series(np.where(_ac > 0, _ab / np.maximum(_ac, 1.0), 0.5), index=u4)
    gmri_arr = gmri4.reindex(uidx).ffill().bfill().to_numpy(float)
    proc = {}
    for s in syms:
        d = store5[s].sort_index()
        ok_raw = d["Close"].notna().to_numpy()
        c = d["Close"]
        d1 = c.diff()
        up = d1.where(d1 > 0, 0.0); dn = -d1.where(d1 < 0, 0.0)
        ag = up.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        al = dn.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rsi = (100 - 100 / (1 + ag / al.replace(0, np.nan))).fillna(50.0)
        prev_c = c.shift(1)
        tr = pd.concat([d["High"] - d["Low"], (d["High"] - prev_c).abs(),
                        (d["Low"] - prev_c).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        ema_f = c.ewm(span=BASE5M["ema_fast"], adjust=False).mean()
        ema_s = c.ewm(span=BASE5M["ema_slow"], adjust=False).mean()
        # مُحيّز الإطار الأعلى: EMA-21 على 4h مجمّعة من نفس بيانات 5m
        d4 = c.resample("4h").last().dropna()
        e21 = d4.ewm(span=21, adjust=False).mean()
        bias = (d4 > e21).astype(float)
        if regime:   # بوابة نظام 4h: السعر فوق EMA-21 و EMA-9 فوق EMA-21
            bias = (bias * (d4.ewm(span=9, adjust=False).mean() > e21)).astype(float)
        bias = bias.reindex(d.index).ffill().fillna(0.0)
        def _ra(sr):
            return sr.reindex(uidx).ffill().bfill().to_numpy(float)
        ok_arr = np.zeros(len(uidx), dtype=bool)
        ok_arr[uidx.get_indexer(d.index)] = ok_raw      # الشموع الحقيقية فقط
        proc[s] = dict(
            o=_ra(d["Open"]), h=_ra(d["High"]), l=_ra(d["Low"]), c=_ra(c),
            rsi=_ra(rsi), atr=_ra(atr), ema_f=_ra(ema_f), ema_s=_ra(ema_s),
            hh=_ra(d["High"].shift(1).rolling(hh_w, min_periods=3).max()),
            bias=_ra(bias), ok=ok_arr, gmri=gmri_arr,
            raw_idx=d.index,
        )
    print(f"[DATA] {len(syms)} رمزاً × {len(uidx):,} شمعة 5m "
          f"({uidx[0]:%Y-%m-%d} ← {uidx[-1]:%Y-%m-%d})")
    return uidx, proc, syms


# ════════════════════════════════════════════════════════════════
# 2) المحاكي — دخول وخروج دقيق 5m
# ════════════════════════════════════════════════════════════════
def simulate(proc, uidx, p, start_i=0, end_i=None, initial_capital=400.0, quiet=False, j5=None):
    end_i = len(uidx) if end_i is None else end_i
    syms = list(proc.keys())
    cash = float(initial_capital)
    pos = {}
    pend = {}   # أوامر limit المعلقة (حجز نقدي — يُسترد عند الإلغاء)
    nav = np.empty(end_i - start_i, dtype=float)
    trades = []
    peak_nav = cash
    warm = int(p.get("warmup", 200))

    def close_pos(s, px, i, rtype):
        nonlocal cash
        ps = pos[s]
        if ps["q"] <= 0:
            del pos[s]; return
        val = ps["q"] * px * (1 - FRICTION)
        pnl = val - ps["q"] * ps["entry"]
        cash += val
        trades.append(dict(ticker=s, pnl_pct=(px - ps["entry"]) / ps["entry"] * 100,
                           pnl_usdt=pnl, time=uidx[i], is_win=pnl > 0, type=rtype))
        del pos[s]

    for i in range(start_i, end_i):
        # ── 0) ⚙️ ملء/إلغاء أوامر الحد المعلقة (تنفيذ maker: الملء عند لمس السعر للحد)
        if pend:
            fmk = float(p.get("fee_maker", FRICTION))
            done = []
            for s, mp in pend.items():
                a = proc[s]
                if i - mp["i0"] >= int(p.get("limit_exp", 12)) or not a["ok"][i]:
                    cash += mp["spend"]            # انتهاء الصلاحية — استرداد الحجز
                    done.append(s); continue
                if a["l"][i] <= mp["limit"]:
                    px = mp["limit"]; atr_n = a["atr"][i]
                    _sl = _h65_clamp(px, px * (1 - atr_n * p["sl_atr"]),
                                     max_frac=p.get("max_sl_frac"), min_frac=p.get("min_sl_frac"))
                    _tg = _h65_cap_up(px, px * (1 + atr_n * p["tgt1_atr"]),
                                      max_frac=(float(p["max_sl_frac"]) * 1.5 if p.get("max_sl_frac") else None))
                    pos[s] = dict(entry=px, q=mp["spend"] * (1 - fmk) / px,
                                  peak=px, sl=_sl, tgt1=_tg, t1=False, i0=i)
                    if j5 is not None:   # [TITAN126-adapter] جرد إضافي
                        j5.setdefault("entries", []).append(dict(
                            ticker=s, time=uidx[i], price=px, spend=mp["spend"],
                            sl=pos[s]["sl"], tgt1=pos[s]["tgt1"], qty=pos[s]["q"], tag="MAKER"))
                    done.append(s)
            for s in done:
                pend.pop(s, None)
        # ── إدارة المخارج (دقة 5m: الوقف ← الهدف الجزئي ← الترايل ← RSI ← الزمن)
        for s in list(pos.keys()):
            a = proc[s]
            if not a["ok"][i]:
                continue
            ps = pos[s]
            hi, lo = a["h"][i], a["l"][i]
            if hi > ps["peak"]:
                ps["peak"] = hi
            # وقف صلب (مع خيار ملء الفجوة الواقعي)
            fill = min(a["o"][i], ps["sl"]) if p.get("gap_fill") else ps["sl"]
            if lo <= fill:
                close_pos(s, fill, i, "SL"); continue
            # هدف جزئي T1 + قفل تعادل
            if not ps["t1"] and hi >= ps["tgt1"]:
                q1 = ps["q"] * p["t1_frac"]
                f_t1 = float(p.get("fee_maker", FRICTION)) if p.get("maker", False) else FRICTION
                val = q1 * ps["tgt1"] * (1 - f_t1)
                cash += val
                pnl = val - q1 * ps["entry"]
                ps["q"] -= q1
                trades.append(dict(ticker=s,
                                   pnl_pct=(ps["tgt1"] - ps["entry"]) / ps["entry"] * 100,
                                   pnl_usdt=pnl, time=uidx[i], is_win=pnl > 0, type="T1_TP"))
                ps["t1"] = True
                ps["sl"] = max(ps["sl"], ps["entry"] * 1.003)
                if ps["q"] <= 0:
                    del pos[s]; continue
            # ترايل بعد T1 (🛡️ H65: سقف نسبة المسافة)
            if ps["t1"]:
                tr = _h65_cap_up(ps["peak"], ps["peak"] * (1 - a["atr"][i] * p["trail_atr"]),
                                 max_frac=(float(p["max_sl_frac"]) * 1.5 if p.get("max_sl_frac") else None))
                if tr > ps["sl"]:
                    ps["sl"] = tr
            # خروج RSI تشبع
            if a["rsi"][i] >= p["rsi_exit"]:
                close_pos(s, a["c"][i], i, "RSI_EXIT"); continue
            # وقف زمني
            if i - ps["i0"] >= p["time_stop_bars"]:
                close_pos(s, a["c"][i], i, "TIME"); continue

        # ── NAV
        cur = cash + sum(ps["q"] * proc[s]["c"][i] for s, ps in pos.items())
        if pend:
            cur += sum(mp["spend"] for mp in pend.values())
        nav[i - start_i] = cur
        if cur > peak_nav:
            peak_nav = cur

        # ── فحص الدخول
        if i - start_i < warm or len(pos) + len(pend) >= p["max_total"]:
            continue
        cands = []
        for s in syms:
            if s in pos or s in pend:
                continue
            a = proc[s]
            if not a["ok"][i] or not np.isfinite(a["atr"][i]) or a["atr"][i] <= 0:
                continue
            c, o = a["c"][i], a["o"][i]
            rsi = a["rsi"][i]
            if p.get("harmony", False) and a["gmri"][i] < float(p.get("h_off", 0.35)):
                continue   # 🤝 البوت في risk_off — الذراع 5m تنتظر معه
            if p.get("bias4h", True) and a["bias"][i] < 1.0:
                continue
            if not (p["rsi_lo"] <= rsi <= p["rsi_hi"]) or c <= o:
                continue
            ef, es = a["ema_f"][i], a["ema_s"][i]
            if not (np.isfinite(ef) and np.isfinite(es)):
                continue
            if p["mode"] == "trend":
                if not (c > es and ef > es and c > a["hh"][i]):
                    continue
                score = (c / es - 1.0) * 40 + (rsi - 50) / 50 + (c / a["c"][max(0, i - 20)] - 1) * 20
            else:  # dip
                if not (ef > es and a["l"][i] <= es * (1 + p["prox"]) and rsi > a["rsi"][i - 1]):
                    continue
                score = (es / c - 1.0) * 40 + (50 - abs(rsi - 50)) / 50
            cands.append((score, s))
        if not cands:
            continue
        cands.sort(reverse=True)
        for _sc, s in cands[: p["max_total"] - len(pos) - len(pend)]:
            a = proc[s]
            sl_frac = max(a["atr"][i] * p["sl_atr"] / a["c"][i], 1e-9)   # مسافة الوقف كسورة من السعر
            cur = cash + sum(ps["q"] * proc[s2]["c"][i] for s2, ps in pos.items())
            boost = 1.25 if a["gmri"][i] >= float(p.get("h_boost", 0.65)) else 1.0  # 🤝 نظام قوي
            spend = min(cash, cur * p["alloc"], cur * p["risk_pct"] * boost / sl_frac)
            if spend < MIN_ORDER or cash < MIN_ORDER:
                continue
            cash -= spend
            if p.get("maker", False):
                # ⚙️ H60: أمر حد تحت سعر الإشارة — يُملأ عند اللمس خلال limit_exp
                pend[s] = dict(limit=a["c"][i] * (1 - float(p.get("limit_off", 0.001))),
                               spend=spend, i0=i)
                continue
            _e = a["c"][i]
            _sl = _h65_clamp(_e, _e * (1 - a["atr"][i] * p["sl_atr"]),
                             max_frac=p.get("max_sl_frac"), min_frac=p.get("min_sl_frac"))
            _tg = _h65_cap_up(_e, _e * (1 + a["atr"][i] * p["tgt1_atr"]),
                              max_frac=(float(p["max_sl_frac"]) * 1.5 if p.get("max_sl_frac") else None))
            pos[s] = dict(entry=_e, q=spend * (1 - FRICTION) / _e,
                          peak=_e, sl=_sl, tgt1=_tg, t1=False, i0=i)
            if j5 is not None:   # [TITAN126-adapter] جرد إضافي (بلا أثر افتراضياً)
                j5.setdefault("entries", []).append(dict(
                    ticker=s, time=uidx[i], price=a["c"][i], spend=spend,
                    sl=pos[s]["sl"], tgt1=pos[s]["tgt1"], qty=pos[s]["q"], tag="TAKER"))

    nav_df = pd.DataFrame({"nav": nav}, index=uidx[start_i:end_i])
    if j5 is not None:   # [TITAN126-adapter] لقطة المراكز المفتوحة (بلا أثر افتراضياً)
        j5["final_pos"] = [
            {"ticker": s, "entry": float(ps["entry"]), "sl": float(ps["sl"]),
             "tgt1": float(ps["tgt1"]), "t1": bool(ps.get("t1")), "t2": False,
             "time": uidx[ps["i0"]], "qty": float(ps["q"]),
             "spend": float(ps["q"] * ps["entry"])}
            for s, ps in pos.items()]
        j5["pending"] = [
            {"ticker": s, "limit": float(mp["limit"]), "spend": float(mp["spend"]),
             "time": uidx[mp["i0"]]}
            for s, mp in pend.items()]
    return nav_df, trades


def metrics5m(nav_df, trades, initial_capital=400.0):
    m = T.MetricsEngine.compute(nav_df, trades, initial_capital=initial_capital)
    m["sharpe"] = m["sharpe"] * ANNUAL_5M      # معايرة 5m
    m["calmar"] = (m["cagr"] / m["max_dd"]) if m["max_dd"] > 0 else 0.0
    return m


def lab_score(m):
    return (m["total_ret"] * 0.45 + m["calmar"] * 15.0 + m["sharpe"] * 10.0
            + m["pf"] * 5.0 - max(0, (m["max_dd"] - 14.0)) * 0.25 * 25.0)


def fmt(m, n, tag):
    print(f"  {tag:26s} ret {m['total_ret']:+8.2f}% DD {m['max_dd']:5.2f} "
          f"Sh {m['sharpe']:.2f} PF {m['pf']:.2f} n={n:4d} score={lab_score(m):.1f}")


# ════════════════════════════════════════════════════════════════
# 3) ★ محرك التدريب والتطوير ★ (بروتوكول مصغر: شبكة → هضبة → طيات → شهادة)
# ════════════════════════════════════════════════════════════════
def build_grid():
    # H60 (v1.3): محور التنفيذ | H65 (v1.3.3): سقف الوقف + خلايا الهضبة 25/30 نقطة
    g = [dict()]   # الأساس: الاعتماد الحالي
    for off in (0.0005, 0.001, 0.002):
        for exp in (6, 12, 24):
            g.append(dict(maker=True, limit_off=off, limit_exp=exp))
    for off in (0.0025, 0.003):
        g.append(dict(maker=True, limit_off=off, limit_exp=6))
    for mx in (0.02, 0.025, 0.03):
        g.append(dict(maker=True, limit_off=0.002, limit_exp=6,
                      max_sl_frac=mx, min_sl_frac=0.005))
    seen, out = set(), []
    for c in g:
        key = json.dumps(c, sort_keys=True)
        if key not in seen:
            seen.add(key); out.append(c)
    return out


def train(store5, uidx, days_label=""):
    S = len(uidx)
    split = int(S * 0.60)
    base = load_config()
    proc_cache = {}
    def proc_for(p):
        key = (int(p.get("hh_w", 12)), bool(p.get("regime4h", False)))
        if key not in proc_cache:
            proc_cache[key] = prepare_5m(store5, p)[1]
        return proc_cache[key]
    print("\n" + "=" * 86)
    print(f"🎓 محرك التدريب والتطوير 5m — شبكة IS (60%: {uidx[0]:%m-%d} ← {uidx[split-1]:%m-%d}) "
          f"| OOS محجوزة ({uidx[split]:%m-%d} ← {uidx[-1]:%m-%d})")
    print("=" * 86)
    rows = []
    for gi, chg in enumerate(build_grid()):
        p = {**base, **chg}
        if p.get("maker", False):
            tag = f"maker/off{p.get('limit_off', 0.001)}/exp{p.get('limit_exp', 12)}"
        else:
            tag = "taker-الأساس"
        if p.get("max_sl_frac"):
            tag += f"/cap{int(p['max_sl_frac']*1000)}"
        nv, tr = simulate(proc_for(p), uidx, p, 0, split)
        m = metrics5m(nv, tr)
        rows.append((lab_score(m), tag, chg, m, len(tr)))
        fmt(m, len(tr), f"[{gi+1:02d}] {tag}")
    rows.sort(key=lambda r: -r[0])
    best_s, best_tag, best_chg, best_m, best_n = rows[0]
    bs, bt, bc, bm, bn = rows[0]
    for s, tag, chg, m, n in rows:
        if not chg:
            bs, bt, bc, bm, bn = s, tag, chg, m, n
            break
    print(f"\n  🏆 الأفضل IS: {best_tag} (score {best_s:.1f})")
    print(f"  ⚖️ الأساس الحالي: {bt} (score {bs:.1f})")
    if not best_chg:
        print("  ✅ الأساس هو القمة — لا مرشح للشهادة. اعتمدادات v126-with-engine تبقى.")
        return None
    # هضبة: جيران أفضل خليتين
    print("  ── فحص الهضبة (الجيران) ──")
    neigh = []
    for k, v in (("limit_off", {0.0005, 0.001, 0.002, 0.0025, 0.003}),
                 ("limit_exp", {6, 12, 24}),
                 ("max_sl_frac", {None, 0.02, 0.025, 0.03})):
        for val in v:
            if val != best_chg.get(k):
                neigh.append({**best_chg, k: val})
    for sc2, t2, c2, m2, n2 in rows:
        if c2 and json.dumps(c2, sort_keys=True) in {json.dumps(x, sort_keys=True) for x in neigh}:
            print(f"     جار: {t2:44s} score={sc2:.1f}")
    # ── الطيات (ثلثا IS) — قاعدة المرشح الحدي: 3/3
    print("  ── الطيات الثلاث داخل IS ──")
    k1, k2 = split // 3, 2 * split // 3
    ok_all = True
    for a, b, nm in ((0, k1, "طية1"), (k1, k2, "طية2"), (k2, split, "طية3")):
        nb, tb = simulate(proc_for(base), uidx, base, a, b)
        mb = metrics5m(nb, tb)
        nc, tc = simulate(proc_for({**base, **best_chg}), uidx, {**base, **best_chg}, a, b)
        mc = metrics5m(nc, tc)
        ok = mc["total_ret"] > mb["total_ret"]
        ok_all &= ok
        print(f"     {nm}: base {mb['total_ret']:+7.2f}% vs cand {mc['total_ret']:+7.2f}%  {'✅' if ok else '❌'}")
    if not ok_all:
        print("  ❌ الرفض — المرشح لا يعبر الطيات (يُوثق ولا يُعتمد).")
        json.dump(dict(engine_version=ENGINE5M_VERSION, adopted_date=str(datetime.now(timezone.utc).date()),
                       params={**base}, rejected=best_chg, reason="folds"),
                  open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return None
    # ── الشهادة الوحيدة (كامل النافذة — OOS تُقاس مرة واحدة)
    print("  ── الشهادة الوحيدة (كامل النافذة — OOS تُقاس هنا فقط) ──")
    nb, tb = simulate(proc_for(base), uidx, base)
    mb = metrics5m(nb, tb)
    nc, tc = simulate(proc_for({**base, **best_chg}), uidx, {**base, **best_chg})
    mc = metrics5m(nc, tc)
    checks = [("العائد أعلى", mc["total_ret"] > mb["total_ret"]),
              ("OOS أعلى", mc["oos_ret"] > mb["oos_ret"]),
              ("DD ≤ 18 مطلقاً", mc["max_dd"] <= 18.0),
              ("DD غير متدهور (+0.5)", mc["max_dd"] <= mb["max_dd"] + 0.5),
              ("PF غير متدهور", mc["pf"] >= mb["pf"] - 0.05),
              ("Sharpe غير متدهور", mc["sharpe"] >= mb["sharpe"] - 0.05)]
    for k, ok in checks:
        print(f"     {'✅' if ok else '❌'} {k}")
    print(f"     الأساس : {mb['total_ret']:+.2f}% | OOS {mb['oos_ret']:+.2f} | DD {mb['max_dd']:.2f} | PF {mb['pf']:.2f} | Sh {mb['sharpe']:.2f} | n={mb['n_trades']}")
    print(f"     المرشح : {mc['total_ret']:+.2f}% | OOS {mc['oos_ret']:+.2f} | DD {mc['max_dd']:.2f} | PF {mc['pf']:.2f} | Sh {mc['sharpe']:.2f} | n={mc['n_trades']}")
    if all(c for _, c in checks):
        adopted = {**base, **best_chg}
        json.dump(dict(engine_version=ENGINE5M_VERSION, adopted_date=str(datetime.now(timezone.utc).date()),
                       params=adopted, cert={k: mc[k] for k in ("total_ret", "oos_ret", "max_dd", "pf", "sharpe", "n_trades")}),
                  open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("  الحكم: ✅✅ اعتماد — حُفظ في results/engine5m_config.json (سيُحمَّل تلقائياً)")
    else:
        json.dump(dict(engine_version=ENGINE5M_VERSION, adopted_date=str(datetime.now(timezone.utc).date()),
                       params={**base}, rejected=best_chg, reason="gate"),
                  open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("  الحكم: ❌ رفض — الأساس باقٍ (وُثق في engine5m_config.json)")
    return mc if all(c for _, c in checks) else mb


# ════════════════════════════════════════════════════════════════
# 4) الفحص الحي — قرارات دخول/خروج على آخر شمعة 5m مغلقة
# ════════════════════════════════════════════════════════════════
def live(uidx, proc, p):
    i = len(uidx) - 2
    print(f"\n🛰️ الفحص الحي 5m — آخر شمعة مغلقة: {uidx[i]:%Y-%m-%d %H:%M} UTC")
    if p.get("harmony", False):
        _g = proc[next(iter(proc))]["gmri"][i]
        _st = ("🔴 risk_off — الذراع تنتظر مع البوت" if _g < float(p.get("h_off", 0.35))
               else ("🟢 قوي — دفعة ×1.25" if _g >= float(p.get("h_boost", 0.65)) else "🟡 محايد"))
        print(f"  🧠 GMRI (نفس دماغ البوت): {_g:.2f} — {_st}")
    positions = {}
    if os.path.exists(POS_FILE):
        try:
            positions = json.load(open(POS_FILE, encoding="utf-8"))
        except Exception:
            positions = {}
    # الخروج أولاً
    for s in list(positions.keys()):
        a = proc.get(s)
        if a is None:
            continue
        ps = positions[s]
        px, rsi = a["c"][i], a["rsi"][i]
        atr = a["atr"][i]
        trail = ps["peak"] * (1 - atr * p["trail_atr"]) if ps.get("t1") else None
        act = None
        if px <= ps["sl"] or a["l"][i] <= ps["sl"]:
            act = ("خروج — وقف", ps["sl"])
        elif px >= ps["tgt1"] and not ps.get("t1"):
            act = ("هدف جزئي T1 — خذ 40% واقفل التعادل", ps["tgt1"])
        elif trail and px <= trail:
            act = ("خروج — ترايل", trail)
        elif rsi >= p["rsi_exit"]:
            act = ("خروج — تشبع RSI", px)
        if act:
            print(f"  🔴 {s:10s} {act[0]} عند {T._fmt_px(act[1])} (دخول {T._fmt_px(ps['entry'])})")
            del positions[s]
        else:
            ps["peak"] = max(ps["peak"], a["h"][i])
            if not ps.get("t1") and a["h"][i] >= ps["tgt1"]:
                ps["t1"] = True
                ps["sl"] = max(ps["sl"], ps["entry"] * 1.003)
                print(f"  🟡 {s:10s} T1 مُلمس — فعّل القفل {T._fmt_px(ps['sl'])}")
    # الدخول
    open_n = len(positions)
    for s, a in proc.items():
        if s in positions or open_n >= p["max_total"] or not a["ok"][i]:
            continue
        c, o, rsi = a["c"][i], a["o"][i], a["rsi"][i]
        if p.get("harmony", False) and a["gmri"][i] < float(p.get("h_off", 0.35)):
            continue
        if p.get("bias4h", True) and a["bias"][i] < 1.0:
            continue
        if not (p["rsi_lo"] <= rsi <= p["rsi_hi"]) or c <= o or not np.isfinite(a["atr"][i]):
            continue
        if p["mode"] == "trend":
            if not (c > a["ema_s"][i] and a["ema_f"][i] > a["ema_s"][i] and c > a["hh"][i]):
                continue
        else:
            if not (a["ema_f"][i] > a["ema_s"][i] and a["l"][i] <= a["ema_s"][i] * (1 + p["prox"])
                    and rsi > a["rsi"][i - 1]):
                continue
        entry = c * (1 - float(p.get("limit_off", 0.001))) if p.get("maker", False) else c
        sl = _h65_clamp(entry, entry * (1 - a["atr"][i] * p["sl_atr"]),
                        max_frac=p.get("max_sl_frac"), min_frac=p.get("min_sl_frac"))
        tgt = _h65_cap_up(entry, entry * (1 + a["atr"][i] * p["tgt1_atr"]),
                          max_frac=(float(p["max_sl_frac"]) * 1.5 if p.get("max_sl_frac") else None))
        positions[s] = dict(entry=entry, sl=sl, tgt1=tgt, peak=entry, t1=False,
                            since=str(uidx[i]),
                            order=("LIMIT_MAKER" if p.get("maker", False) else "MARKET"))
        _w = "limit-maker" if p.get("maker", False) else "سوق"
        print(f"  🟢 {s:10s} دخول {_w} @ {T._fmt_px(entry)} | SL {T._fmt_px(sl)} "
              f"| T1 {T._fmt_px(tgt)} | شريحة {open_n + 1}/{p['max_total']}")
        open_n += 1
    json.dump(positions, open(POS_FILE, "w", encoding="utf-8"), indent=2, default=float)
    print(f"[SAVE] {POS_FILE} ({len(positions)} مركزاً مفتوحاً)")


# ════════════════════════════════════════════════════════════════
# 4.5) 🤝 التشغيل المتناغم — البوت 4h + الذراع 5m برأس مال مشترك وتقرير واحد
# ════════════════════════════════════════════════════════════════
def combined_run(proc, uidx, p5, capital=400.0, bot_share=0.85):
    if not hasattr(T, "run_dual_strategies"):
        raise SystemExit("❌ --combined يتطلب titan_juggernaut_bot.py بجوار المحرك (ذراع 4h).")
    cache4 = os.path.join(T.SystemConfig.CACHE_DIR, "titans_basket_4h_cache.pkl")
    print("\n" + "=" * 86)
    print(f"🤝 التشغيل المتناغم — البوت 4h ({bot_share:.0%} من رأس المال) + الذراع 5m ({1-bot_share:.0%}) "
          f"| رأس المال {capital:.0f}$")
    print("=" * 86)
    store4 = pd.read_pickle(cache4)
    res = T.run_dual_strategies(store4)
    nav_bot = pd.Series(np.asarray(res["comb_nav"], dtype=float),
                        index=pd.DatetimeIndex(res["union_index"]))
    w0, w1 = uidx[0], uidx[-1]
    nb = nav_bot[(nav_bot.index >= w0) & (nav_bot.index <= w1)].ffill()
    if len(nb) < 10:
        raise SystemExit("❌ كاش السلة لا يغطي نافذة 5m — حدّثه (تشغيل تحديث للبوت).")
    bot_g = nb.iloc[-1] / nb.iloc[0] - 1.0
    nv5, tr5 = simulate(proc, uidx, p5, initial_capital=capital)
    m5 = metrics5m(nv5, tr5, initial_capital=capital)
    bot_rel = (nb / nb.iloc[0]).reindex(uidx).ffill().bfill().to_numpy(float)
    sl_rel = nv5["nav"].to_numpy(float) / capital
    comb = capital * (bot_share * bot_rel + (1 - bot_share) * sl_rel)
    comb_df = pd.DataFrame({"nav": comb}, index=uidx)
    tb = [t for t in res["all_trades"]
          if w0 <= pd.Timestamp(t.get("time", w0)) <= w1]
    all_tr = list(tb) + list(tr5)
    mc = T.MetricsEngine.compute(comb_df, all_tr, initial_capital=capital)
    print(f"  البوت 4h (النافذة)  : {bot_g*100:+8.2f}% | صفقات {len(tb)}")
    print(f"  الذراع 5m (النافذة) : {m5['total_ret']:+8.2f}% | صفقات {m5['n_trades']} | DD {m5['max_dd']:.2f}")
    print(f"  ──────────────────────────────────────────────")
    print(f"  🤝 المجموع المتناغم  : {mc['total_ret']:+8.2f}% | صفقات {mc['n_trades']} "
          f"(نجاح {mc['win_rate']:.1f}% | PF {mc['pf']:.2f}) | DD {mc['max_dd']:.2f} | نهائي {mc['final_nav']:,.2f}$")
    print(f"  مرجع البوت وحده     : {bot_g*100:+8.2f}% | صفقات {len(tb)} — "
          f"مساهمة الذراع: {(mc['total_ret'] - bot_g*100):+.2f} نقطة و(+{mc['n_trades'] - len(tb)}) صفقة")
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    comb_df.to_csv(os.path.join(RESULT_DIR, f"harmony_equity_{ts}.csv"))
    nums = dict(bot_window_ret=float(bot_g * 100), bot_trades=len(tb),
                sleeve_ret=float(m5["total_ret"]), sleeve_trades=int(m5["n_trades"]),
                sleeve_dd=float(m5["max_dd"]),
                combined_ret=float(mc["total_ret"]), combined_trades=int(mc["n_trades"]),
                combined_dd=float(mc["max_dd"]), combined_pf=float(mc["pf"]),
                final_nav=float(mc["final_nav"]), bot_share=bot_share,
                params=p5, engine_version=ENGINE5M_VERSION)
    json.dump(nums, open(os.path.join(RESULT_DIR, "harmony_numbers.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print(f"[SAVE] harmony_equity_{ts}.csv | harmony_numbers.json")
    return nums


# ════════════════════════════════════════════════════════════════
# 5) نقطة التشغيل
# ════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="ENGINE 5M — محرك الدخول/الخروج الدقيق + التدريب")
    ap.add_argument("--train", action="store_true", help="دورة تدريب كاملة (شبكة + طيات + شهادة)")
    ap.add_argument("--refresh", action="store_true", help="جلب شموع 5m جديدة")
    ap.add_argument("--live", action="store_true", help="قرارات دخول/خروج على آخر شمعة 5m مغلقة")
    ap.add_argument("--combined", action="store_true", help="🤝 تشغيل متناغم موحّد: البوت 4h + الذراع 5m")
    ap.add_argument("--days", type=int, default=60, help="نافذة البيانات بالأيام (أقصى 60 لـ 5m)")
    ap.add_argument("--source", choices=["auto", "binance", "yfinance"], default="auto")
    ap.add_argument("--capital", type=float, default=400.0)
    args = ap.parse_args()

    store5 = T.load_5m_data(force_refresh=args.refresh, days=min(args.days, 60),
                            source=args.source)
    p = load_config()
    uidx, proc, syms = prepare_5m(store5, p)

    if args.live:
        live(uidx, proc, p)
        return

    if args.combined:
        combined_run(proc, uidx, p, capital=args.capital)
        return

    if args.train:
        train(store5, uidx)
        p = load_config()
        proc = prepare_5m(store5, p)[1]

    # ── التقرير الكامل بالإعدادات النهائية
    print("\n" + "=" * 86)
    print(f"⚡ ENGINE 5M v{ENGINE5M_VERSION} — باكتست كامل (نافذة كاملة) | mode={p['mode']} "
          f"| SL {p['sl_atr']}×ATR | ترايل {p['trail_atr']}×ATR | سقف مراكز {p['max_total']}")
    print("=" * 86)
    nv, tr = simulate(proc, uidx, p, initial_capital=args.capital)
    m = metrics5m(nv, tr, initial_capital=args.capital)
    print(f"  العائد الكلي : {m['total_ret']:+.2f}%  (نهائي {m['final_nav']:,.2f}$ من {args.capital:.0f}$)")
    print(f"  CAGR         : {m['cagr']:+.2f}%  | يومي مركب: {m['daily_compound']:+.4f}%")
    print(f"  MaxDD        : {m['max_dd']:.2f}%   | Sharpe(5m): {m['sharpe']:.2f} | Calmar: {m['calmar']:.2f}")
    print(f"  IS/OOS       : {m['is_ret']:+.2f}% / {m['oos_ret']:+.2f}%")
    print(f"  الصفقات      : {m['n_trades']} (نجاح {m['win_rate']:.1f}% | PF {m['pf']:.2f} | EV {m['expectancy_usdt']:+.2f}$)")
    if m["n_trades"] > 0:
        global FRICTION
        f0 = FRICTION
        FRICTION = 0.0
        nv0, tr0 = simulate(proc, uidx, p, initial_capital=args.capital, quiet=True)
        FRICTION = f0
        m0 = metrics5m(nv0, tr0, initial_capital=args.capital)
        print(f"  🔬 قبل الاحتكاك: ret {m0['total_ret']:+.2f}% | PF {m0['pf']:.2f} "
              f"— أرضية الاحتكاك تلتهم {m0['total_ret'] - m['total_ret']:.1f} نقطة مئوية")
    df = pd.DataFrame(tr)
    if len(df):
        df["day"] = pd.to_datetime(df["time"]).dt.date
        pd_day = df.groupby("day").size()
        print(f"  التردد       : {len(df)/max((df['day'].max()-df['day'].min()).days,1):.2f} صفقة/يوم "
              f"| وسيط اليوم النشط {pd_day.median():.0f} | أقصى يوم {int(pd_day.max())}")
        print("  حسب النوع    :", {k: int(v) for k, v in df.groupby("type").size().items()})
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    nv.to_csv(os.path.join(RESULT_DIR, f"engine5m_equity_{ts}.csv"))
    if len(df):
        df.drop(columns=["day"]).to_csv(os.path.join(RESULT_DIR, f"engine5m_trades_{ts}.csv"), index=False)
    json.dump(dict(engine_version=ENGINE5M_VERSION, params=p, metrics={k: v for k, v in m.items()}),
              open(os.path.join(RESULT_DIR, f"engine5m_report_{ts}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print(f"\n[SAVE] engine5m_equity_{ts}.csv | engine5m_trades_{ts}.csv | engine5m_report_{ts}.json")
    print("⚠️ نتائج 5m = سقف لا أرضية. تداول ورقي أولاً.")


if __name__ == "__main__":
    main()
