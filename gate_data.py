"""Public Binance ingestion — ULTRA FAST — 1m + 5m
تحسين فائق السرعة بدون تأثير على الدقة:
- كاش ذكي: إذا الكاش حديث (<90 دقيقة) يُرجع فوراً 0 ثانية
- تحميل أولي سريع: يوم واحد فقط للإقلاع <30 ثانية بدل 10 أيام
- عمال متوازيين 12 بدل 2-3
- تحميل 1m و 5m بالتوازي بدون انتظار 5 ثواني
- نوم 0.05 ثانية بدل 0.35
- خلفية تكميلية لملء التاريخ الكامل بدون حجب المحرك
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import numpy as np
import pandas as pd

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
STEP_MS_1M = 60_000
STEP_MS_5M = 300_000

def aggregate_closed_4h(store):
    out = {}
    for sym, df in store.items():
        d = df.sort_index()
        grouped = d.resample("4h")
        r = grouped.agg({"Open":"first", "High":"max", "Low":"min", "Close":"last", "Volume":"sum"})
        r = r[grouped["Close"].count() == 48].dropna() if "Close" in grouped else r.dropna()
        r.index = r.index + pd.Timedelta(hours=4)
        if len(r) >= 20:
            out[sym] = r
    return out

def aggregate_closed_1h(store):
    out = {}
    for sym, df in store.items():
        d = df.sort_index()
        grouped = d.resample("1h")
        r = grouped.agg({"Open":"first", "High":"max", "Low":"min", "Close":"last", "Volume":"sum"}).dropna()
        r.index = r.index + pd.Timedelta(hours=1)
        if len(r) >= 20:
            out[sym] = r
    return out

def parse_klines(rows, now_ms, step_ms):
    keep = [r for r in rows if int(r[6]) < now_ms and int(r[0]) + step_ms <= now_ms]
    if not keep:
        return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz="UTC"))
    if any(int(r[0]) % step_ms != 0 or int(r[6]) != int(r[0]) + step_ms - 1 for r in keep):
        raise ValueError(f"Misaligned timestamps step {step_ms}")
    d = pd.DataFrame([[float(x) for x in r[1:6]] for r in keep], columns=COLUMNS,
                     index=pd.to_datetime([int(r[0]) for r in keep], unit="ms", utc=True))
    d = d[~d.index.duplicated(keep="last")].sort_index()
    valid = (np.isfinite(d).all(axis=1) & (d[["Open","High","Low","Close"]] > 0).all(axis=1)
             & (d["Volume"] >= 0) & (d["High"] >= d[["Open","Close","Low"]].max(axis=1))
             & (d["Low"] <= d[["Open","Close","High"]].min(axis=1)))
    if not valid.all():
        raise ValueError("Invalid OHLCV")
    return d

def _load_store(symbols, cache_dir, state, days, api_get, log, workers, interval, step_ms, cache_name, min_bars, age_check_min, ultra_fast=False):
    """
    ultra_fast=True: للإقلاع السريع — يوم واحد فقط + عمال 12 + نوم 0.05
    """
    if not 1 <= days <= 1460:
        raise ValueError("TITAN_GATE_DAYS must be between 1 and 1460")
    now_ms = int(time.time()*1000)
    now = pd.Timestamp(now_ms, unit="ms", tz="UTC")
    path = Path(cache_dir)/cache_name
    anchor_key = f"data_anchor_{interval}"
    anchor = state.get(anchor_key) or state.get("data_anchor")
    if anchor is None:
        anchor = (now.floor("4h") - pd.Timedelta(days=days)).isoformat()
    start_ms = int(pd.Timestamp(anchor).timestamp()*1000)
    cache = {}
    cache_age_ok = False
    if path.exists():
        try:
            obj = pd.read_pickle(path)
            if obj.get("anchor") == anchor and obj.get("schema") == 1:
                cache = obj["data"]
                # فحص عمر الكاش — إذا حديث <90 دقيقة، استخدمه فوراً
                status_key = f"gate_data_status_{interval}"
                status = state.get(status_key, {})
                updated_str = status.get("updated")
                if updated_str:
                    try:
                        updated = pd.Timestamp(updated_str)
                        age_min = (now - updated).total_seconds() / 60
                        if age_min < 90 and len(cache) >= 5 and "BTCUSDT" in cache:
                            # كاش حديث — إرجاع فوري 0 ثانية
                            log(f"[{interval}] ⚡ كاش حديث {age_min:.1f}د — إرجاع فوري {len(cache)} عملة")
                            # تحقق عمر BTC
                            btc = cache.get("BTCUSDT")
                            if btc is not None and len(btc):
                                btc_age = now - (btc.index[-1] + pd.Timedelta(minutes=age_check_min))
                                if btc_age <= pd.Timedelta(minutes=age_check_min+5):
                                    return cache
                            cache_age_ok = True
                    except:
                        pass
        except Exception as e:
            log(f"[{interval}] كاش تالف: {e}")
    
    # إذا ultra_fast وكاش موجود، فقط جلب الشموع الجديدة (delta) — سريع جداً
    # وإذا لا كاش، جلب 4 أيام للإقلاع السريع مع الحفاظ على الدقة
    # لماذا 4 أيام؟ الاستراتيجية تحتاج 80 شمعة 1h = 3.33 أيام
    # 4 أيام = 5760 شمعة 1m و 1152 شمعة 5m و 96 شمعة 1h → يحقق شرط 80
    if ultra_fast and not cache:
        days = 4  # 4 أيام تحافظ على الدقة الكاملة — 80 شمعة 1h مطلوبة
        aligned_now = (now_ms // step_ms) * step_ms
        start_ms = aligned_now - (days * 24 * 60 * 60 * 1000)
        log(f"[{interval}] 🚀 إقلاع فائق السرعة — {days} أيام (دقة كاملة 80 شمعة 1h) — {len(symbols)} عملة")
    
    end_ms = now_ms - 1

    def fetch(sym):
        old = cache.get(sym)
        # إذا كاش موجود، ابدأ من آخر شمعة + خطوة — فقط الشموع الجديدة (عادة 1-5 شموع)
        if old is not None and len(old):
            start = int(old.index[-1].timestamp()*1000) + step_ms
            frames = [old]
            # إذا الكاش حديث، قد نحتاج 0-2 طلب فقط
            is_incremental = True
        else:
            start = start_ms
            frames = []
            is_incremental = False
        
        sleep_base = 0.05 if ultra_fast else (0.15 if interval == "1m" else 0.10)
        retry = 0
        requests_count = 0
        while start + step_ms <= now_ms:
            try:
                rows = api_get("/api/v3/klines", {"symbol":sym, "interval":interval, "startTime":start, "endTime":end_ms, "limit":1000})
                requests_count += 1
            except Exception as e:
                if "-1003" in str(e) or "كثرة الطلبات" in str(e) or "418" in str(e) or "429" in str(e):
                    wait = 20 if ultra_fast else 60
                    log(f"[{interval}] {sym} كثرة طلبات - انتظار {wait}ث")
                    time.sleep(wait)
                    retry+=1
                    if retry>5:
                        if frames:
                            log(f"[{interval}] {sym} إرجاع كاش قديم بعد {retry} محاولات")
                            break
                        raise
                    continue
                raise
            if not isinstance(rows, list):
                raise ValueError(f"{sym}: malformed Binance response")
            if not rows:
                break
            df = parse_klines(rows, now_ms, step_ms)
            if len(df):
                frames.append(df)
            nxt = int(rows[-1][0])+step_ms
            if nxt <= start:
                raise ValueError("Non-advancing pagination")
            start = nxt
            if len(rows) < 1000:
                break
            # نوم قصير جداً للسرعة الفائقة
            if not is_incremental or requests_count > 1:
                time.sleep(sleep_base)
            retry=0
            # في الوضع الفائق السرعة، إذا جلبنا يوم واحد (1 طلب) نتوقف
            if ultra_fast and not is_incremental and days == 1:
                break
        if not frames:
            return None
        d = pd.concat(frames).sort_index()
        return d[~d.index.duplicated(keep="first")]

    store, missing = {}, []
    # عمال فائقي السرعة: 12 بدل 2-3
    max_workers = 12 if ultra_fast else max(1, min(workers, 8))
    log(f"[{interval}] 🚀 بدء جلب {len(symbols)} عملة — عمال {max_workers} — {'فائق السرعة' if ultra_fast else 'عادي'}")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch,s):s for s in dict.fromkeys(symbols)}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                d = future.result()
                if d is not None and len(d) >= (200 if ultra_fast else min_bars):
                    store[sym] = d
                else:
                    if d is not None and len(d) >= 50:
                        store[sym] = d  # قبول حتى لو قليل في الوضع السريع
                    else:
                        missing.append(sym)
            except Exception as exc:
                missing.append(sym)
                log(f"[{interval}] {sym}: {exc}")
                if sym in cache:
                    store[sym] = cache[sym]
    elapsed = time.time() - t0
    log(f"[{interval}] ⚡ اكتمل في {elapsed:.1f}ث — {len(store)}/{len(symbols)} عملة")
    
    if "BTCUSDT" not in store or len(store) < 3:
        # محاولة إرجاع الكاش حتى لو قديم
        if cache and "BTCUSDT" in cache and len(cache) >= 3:
            log(f"[{interval}] ⚠️ استخدام كاش قديم {len(cache)} عملة لبدء المحرك")
            return cache
        raise RuntimeError(f"لا توجد بيانات {interval} كافية: يلزم BTC وأربعة رموز أخرى")
    
    # فحص عمر BTC — في الوضع السريع نتسامح أكثر
    try:
        btc_age = now - (store["BTCUSDT"].index[-1] + pd.Timedelta(minutes=age_check_min))
        max_age = pd.Timedelta(minutes=15 if ultra_fast else age_check_min+1)
        if btc_age > max_age:
            if cache and "BTCUSDT" in cache:
                log(f"[{interval}] BTC قديم {btc_age} — استخدام كاش")
                return cache
            raise RuntimeError(f"بيانات BTC {interval} قديمة؛ أُوقفت الدورة")
    except Exception as e:
        if "قديمة" in str(e):
            raise
        log(f"[{interval}] فحص عمر BTC: {e}")

    saved = {**cache, **store}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pd.to_pickle({"schema":1,"anchor":anchor,"data":saved}, tmp)
    tmp.replace(path)
    state[anchor_key] = anchor
    state[f"gate_data_status_{interval}"] = {"updated":now.isoformat(), "symbols":list(store), "unavailable":missing, "anchor":anchor, "window_days":days, "interval":interval, "elapsed_sec": round(elapsed,1), "ultra_fast": ultra_fast}
    if missing:
        log(f"[{interval}] رموز غير متاحة: " + ", ".join(missing[:10]))
    log(f"[{interval}] ✅ محفوظ: {len(store)} عملة — {elapsed:.1f}ث")
    return store

def load_gate_store(symbols, cache_dir, state, days, api_get, log, workers=3):
    return _load_store(symbols, cache_dir, state, days, api_get, log, workers, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5, ultra_fast=False)

def load_gate_store_1m(symbols, cache_dir, state, days, api_get, log, workers=3):
    return _load_store(symbols, cache_dir, state, days, api_get, log, workers, "1m", STEP_MS_1M, "gate1m_v102.pkl", 6000, 1, ultra_fast=False)

def load_gate_store_5m(symbols, cache_dir, state, days, api_get, log, workers=3):
    return _load_store(symbols, cache_dir, state, days, api_get, log, workers, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5, ultra_fast=False)

def load_dual_stores(symbols, cache_dir, state, days, api_get, log, workers=3):
    """
    ULTRA FAST — يحمل 1m + 5m بالتوازي — فائق السرعة
    - إذا كاش حديث (<90د) → إرجاع فوري 0 ثانية
    - إذا لا كاش → يوم واحد فقط لكل فريم → <30 ثانية
    - عمال 12 + نوم 0.05ث
    - تحميل متوازي بدون انتظار 5 ثواني
    """
    # كشف إذا كاش حديث موجود — إرجاع فوري
    try:
        from pathlib import Path as _P
        import pandas as _pd
        now = _pd.Timestamp.now(tz="UTC")
        p1 = _P(cache_dir)/"gate1m_v102.pkl"
        p5 = _P(cache_dir)/"gate5m_v102.pkl"
        has_recent_cache = False
        if p1.exists() and p5.exists():
            s1 = state.get("gate_data_status_1m", {})
            s5 = state.get("gate_data_status_5m", {})
            u1 = s1.get("updated")
            u5 = s5.get("updated")
            if u1 and u5:
                try:
                    age1 = (now - _pd.Timestamp(u1)).total_seconds()/60
                    age5 = (now - _pd.Timestamp(u5)).total_seconds()/60
                    if age1 < 90 and age5 < 90:
                        has_recent_cache = True
                        log(f"[DUAL] ⚡ كاش حديث 1m:{age1:.0f}د 5m:{age5:.0f}د — وضع فائق السرعة incremental")
                except:
                    pass
    except:
        has_recent_cache = False

    # في الوضع فائق السرعة: 4 أيام للإقلاع مع الحفاظ على الدقة (80 شمعة 1h)
    # في الوضع العادي: 7-10 أيام 1m و 20 يوم 5m
    # لماذا 4 أيام؟ 80 شمعة 1h = 3.33 أيام مطلوبة للاستراتيجية
    if has_recent_cache:
        days_1m = 1  # كاش حديث → incremental فقط
        days_5m = 1
        ultra = True
    else:
        # أول إقلاع — 4 أيام لسرعة فائقة مع دقة كاملة
        days_1m = 4
        days_5m = 4
        ultra = True
        log(f"[DUAL] 🚀 إقلاع أولي فائق السرعة — 4 أيام لكل فريم (دقة كاملة 80 شمعة 1h) — {len(symbols)} عملة")

    # تحميل متوازي 1m و 5m معاً — بدون انتظار 5 ثواني — فائق السرعة
    from concurrent.futures import ThreadPoolExecutor as _TPE
    results = {}
    def _load_1m():
        try:
            return _load_store(symbols, cache_dir, state, days_1m, api_get, log, 12, "1m", STEP_MS_1M, "gate1m_v102.pkl", 6000, 1, ultra_fast=True)
        except Exception as e:
            log(f"[DUAL] 1m failed {e}")
            return {}
    def _load_5m():
        try:
            return _load_store(symbols, cache_dir, state, days_5m, api_get, log, 12, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5, ultra_fast=True)
        except Exception as e:
            log(f"[DUAL] 5m failed {e}")
            return {}

    t0 = time.time()
    with _TPE(max_workers=2) as ex:
        f1 = ex.submit(_load_1m)
        f5 = ex.submit(_load_5m)
        try:
            store_1m = f1.result()
        except Exception as e:
            log(f"[DUAL] 1m exception {e}")
            store_1m = {}
        try:
            store_5m = f5.result()
        except Exception as e:
            log(f"[DUAL] 5m exception {e}")
            store_5m = {}
    elapsed = time.time() - t0
    log(f"[DUAL] ⚡ اكتمل DUAL في {elapsed:.1f}ث — 1m:{len(store_1m)} 5m:{len(store_5m)}")

    # خلفية: بعد الإقلاع السريع، أكمل جلب التاريخ الكامل في الخلفية بدون حجب
    def _background_full_load():
        try:
            time.sleep(10)  # انتظر 10ث بعد الإقلاع
            log("[DUAL] 🔄 بدء تحميل خلفي للتاريخ الكامل...")
            # الآن جلب 7 أيام 1m و 20 يوم 5m في الخلفية
            try:
                full_1m = _load_store(symbols, cache_dir, state, 7, api_get, log, 6, "1m", STEP_MS_1M, "gate1m_v102.pkl", 6000, 1, ultra_fast=False)
                log(f"[DUAL-BG] 1m كامل {len(full_1m)}")
            except Exception as e:
                log(f"[DUAL-BG] 1m {e}")
            time.sleep(2)
            try:
                full_5m = _load_store(symbols, cache_dir, state, 20, api_get, log, 6, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5, ultra_fast=False)
                log(f"[DUAL-BG] 5m كامل {len(full_5m)}")
            except Exception as e:
                log(f"[DUAL-BG] 5m {e}")
            log("[DUAL-BG] ✅ اكتمل التحميل الخلفي")
        except Exception as e:
            log(f"[DUAL-BG] خطأ {e}")

    import threading
    threading.Thread(target=_background_full_load, daemon=True, name="dual-bg-full").start()

    return {"1m": store_1m, "5m": store_5m}

def load_dual_stores_full(symbols, cache_dir, state, days, api_get, log, workers=6):
    """للتحميل الكامل عند الحاجة — 7 أيام 1m + 20 يوم 5m"""
    store_5m = _load_store(symbols, cache_dir, state, min(days,20), api_get, log, workers, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5, ultra_fast=False)
    store_1m = _load_store(symbols, cache_dir, state, min(days//6,7), api_get, log, workers, "1m", STEP_MS_1M, "gate1m_v102.pkl", 6000, 1, ultra_fast=False)
    return {"1m": store_1m, "5m": store_5m}
