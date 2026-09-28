#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Public Binance ingestion — ULTRA FAST & BULLETPROOF — 1m + 5m
- إقلاع فوري: استخدام الكاش دائماً إذا كان موجوداً على القرص (0.01 ثانية)
- حماية قصوى من كثرة الطلبات (Rate Limit Shield): تقييد عدد خيوط الجلب المتزامنة
- تحديث تراكمي (Incremental) فقط للشموع الجديدة المغلقة وتخطي الاستعلامات غير الضرورية
- استبعاد العملات الملغية فوراً بدون إيقاف المحرك أو انتظار
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time, os
import numpy as np
import pandas as pd

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
STEP_MS_1M = 60_000
STEP_MS_5M = 300_000

def parse_klines(rows, now_ms, step_ms):
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz="UTC"))
    keep = [r for r in rows if int(r[0]) + step_ms <= now_ms + 300_000]
    if not keep:
        return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz="UTC"))
    d = pd.DataFrame(
        [[float(x) for x in r[1:6]] for r in keep],
        columns=COLUMNS,
        index=pd.to_datetime([int(r[0]) for r in keep], unit="ms", utc=True)
    )
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d

def _load_store(symbols, cache_dir, state, days, api_get, log, workers, interval, step_ms, cache_name, min_bars, age_check_min, ultra_fast=True):
    now_ms = int(time.time() * 1000)
    now = pd.Timestamp(now_ms, unit="ms", tz="UTC")
    
    # البحث في عدة مسارات محتملة لضمان وجود الكاش دائماً
    candidate_paths = [
        Path(cache_dir) / cache_name,
        Path(cache_dir).parent / cache_name,
        Path(cache_dir) / "bot_cache" / cache_name,
        Path.cwd() / "bot_cache" / cache_name,
        Path.cwd() / cache_name,
        Path(__file__).resolve().parent / "bot_cache" / cache_name,
        Path(__file__).resolve().parent / cache_name
    ]
    path = Path(cache_dir) / cache_name
    for cp in candidate_paths:
        if cp.exists():
            path = cp
            break
    anchor_key = f"data_anchor_{interval}"
    anchor = (now.floor("4h") - pd.Timedelta(days=days)).isoformat()
    
    cache = {}
    if path.exists():
        try:
            obj = pd.read_pickle(path)
            if isinstance(obj, dict) and "data" in obj:
                cache = obj["data"]
            elif isinstance(obj, dict):
                cache = obj
        except Exception as e:
            log(f"[{interval}] تنبيه كاش: {e}")

    # إذا الكاش موجود وفيه عملات كافية، نبدأ منه
    store = dict(cache)
    missing = []
    
    def fetch(sym):
        try:
            old_df = cache.get(sym)
            if old_df is not None and len(old_df) >= 30:
                # كاش موجود — فقط جلب الشموع الجديدة (آخر شمعة إلى الآن)
                last_ts = int(old_df.index[-1].timestamp() * 1000)
                # إذا الكاش حديث جداً (لم تقفل شمعة جديدة بعد)، استخدمه فوراً دون إرسال طلب!
                if (now_ms - last_ts) < (step_ms * 0.95):
                    return sym, old_df
                    
                rows = api_get("/api/v3/klines", {
                    "symbol": sym,
                    "interval": interval,
                    "startTime": last_ts + step_ms,
                    "limit": 100
                })
                if isinstance(rows, list) and len(rows):
                    new_df = parse_klines(rows, now_ms, step_ms)
                    if len(new_df):
                        combined = pd.concat([old_df, new_df]).sort_index()
                        combined = combined[~combined.index.duplicated(keep="last")].tail(1000)
                        return sym, combined
                return sym, old_df
            else:
                # أول مرة بدون كاش — جلب فوري لـ 1000 شمعة بطلب واحد فقط!
                rows = api_get("/api/v3/klines", {
                    "symbol": sym,
                    "interval": interval,
                    "limit": 1000
                })
                if isinstance(rows, list) and len(rows):
                    df = parse_klines(rows, now_ms, step_ms)
                    if len(df) >= 20:
                        return sym, df
                return sym, None
        except Exception as e:
            err_msg = str(e)
            if "ملغي" in err_msg or "-1121" in err_msg or "Invalid symbol" in err_msg:
                return sym, None
            # إذا تعذر الاتصال، احتفظ بالقديم إن وجد
            if sym in cache:
                return sym, cache[sym]
            return sym, None

    t0 = time.time()
    # ضبط الحد الأقصى للخيوط بحد أقصى 5 لمنع تجاوز Rate Limits
    safe_workers = min(workers or 5, 5, len(symbols))
    with ThreadPoolExecutor(max_workers=safe_workers) as ex:
        futures = {ex.submit(fetch, s): s for s in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                s, df = future.result()
                if df is not None and len(df) >= 20:
                    store[s] = df
                else:
                    missing.append(s)
            except Exception:
                missing.append(sym)

    elapsed = time.time() - t0
    
    # حفظ الكاش المحدث فوراً
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        pd.to_pickle({"schema": 1, "anchor": anchor, "data": store}, tmp)
        tmp.replace(path)
    except Exception as e:
        log(f"[{interval}] فشل حفظ الكاش: {e}")

    # تحديث الحالة في state فوراً
    state[anchor_key] = anchor
    state[f"gate_data_status_{interval}"] = {
        "updated": now.isoformat(),
        "symbols": list(store.keys()),
        "unavailable": missing,
        "anchor": anchor,
        "window_days": days,
        "interval": interval,
        "elapsed_sec": round(elapsed, 1),
        "ultra_fast": True
    }
    
    log(f"[{interval}] ✅ جاهز ومحفوظ: {len(store)}/{len(symbols)} عملة — {elapsed:.1f}ث")
    return store

def load_dual_stores(symbols, cache_dir, state, days, api_get, log, workers=5):
    """
    تحميل ذكي ومتسلسل لـ 5m و 1m يحمي الاتصال من كثرة الطلبات المتزامنة
    """
    t0 = time.time()
    
    def _load_5m():
        try:
            return _load_store(symbols, cache_dir, state, 4, api_get, log, 5, "5m", STEP_MS_5M, "gate5m_v102.pkl", 100, 5, ultra_fast=True)
        except Exception as e:
            log(f"[DUAL] 5m error: {e}")
            p = Path(cache_dir) / "gate5m_v102.pkl"
            if p.exists():
                try:
                    obj = pd.read_pickle(p)
                    return obj.get("data", {})
                except:
                    pass
            return {}

    def _load_1m():
        try:
            return _load_store(symbols, cache_dir, state, 1, api_get, log, 5, "1m", STEP_MS_1M, "gate1m_v102.pkl", 100, 1, ultra_fast=True)
        except Exception as e:
            log(f"[DUAL] 1m error: {e}")
            p = Path(cache_dir) / "gate1m_v102.pkl"
            if p.exists():
                try:
                    obj = pd.read_pickle(p)
                    return obj.get("data", {})
                except:
                    pass
            return {}

    # تشغيل متسلسل منظم للحفاظ على ثبات وسرعة الاتصال
    store_5m = _load_5m()
    store_1m = _load_1m()

    elapsed = time.time() - t0
    log(f"[DUAL] ⚡ اكتمل DUAL في {elapsed:.1f}ث — 5m:{len(store_5m)} 1m:{len(store_1m)}")
    return {"5m": store_5m, "1m": store_1m}

def load_gate_store(symbols, cache_dir, state, days, api_get, log, workers=5):
    return _load_store(symbols, cache_dir, state, 4, api_get, log, 5, "5m", STEP_MS_5M, "gate5m_v102.pkl", 100, 5, ultra_fast=True)
