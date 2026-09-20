"""Public Binance ingestion — يدعم 1m + 5m — استراتيجيتين
الاستراتيجية الأولى: فريم 1 دقيقة — إشارات كل دقيقة
الاستراتيجية الثانية: فريم 5 دقائق — إشارات كل 5 دقائق
Caches are generated locally, never load a pickle received from another party.
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
        # للـ 5m: 48 شمعة 5m = 4h
        # للـ 1m: 240 شمعة 1m = 4h — نحسب بشكل عام
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

def _load_store(symbols, cache_dir, state, days, api_get, log, workers, interval, step_ms, cache_name, min_bars, age_check_min):
    if not 10 <= days <= 1460:
        raise ValueError("TITAN_GATE_DAYS must be between 10 and 1460")
    now_ms = int(time.time()*1000)
    now = pd.Timestamp(now_ms, unit="ms", tz="UTC")
    path = Path(cache_dir)/cache_name
    anchor_key = f"data_anchor_{interval}"
    anchor = state.get(anchor_key) or state.get("data_anchor")
    if anchor is None:
        anchor = (now.floor("4h") - pd.Timedelta(days=days)).isoformat()
    start_ms = int(pd.Timestamp(anchor).timestamp()*1000)
    cache = {}
    if path.exists():
        try:
            obj = pd.read_pickle(path)
            if obj.get("anchor") == anchor and obj.get("schema") == 1:
                cache = obj["data"]
        except: pass
    end_ms = now_ms - 1

    def fetch(sym):
        old = cache.get(sym)
        start = int(old.index[-1].timestamp()*1000) + step_ms if old is not None and len(old) else start_ms
        frames = [old] if old is not None and len(old) else []
        # تقليل الضغط لتجنب -1003
        sleep_base = 0.35 if interval == "1m" else 0.20
        retry = 0
        while start + step_ms <= now_ms:
            try:
                rows = api_get("/api/v3/klines", {"symbol":sym, "interval":interval, "startTime":start, "endTime":end_ms, "limit":1000})
            except Exception as e:
                # إذا كثرة طلبات، انتظر 60 ثانية
                if "-1003" in str(e) or "كثرة الطلبات" in str(e) or "418" in str(e) or "429" in str(e):
                    log(f"[{interval}] {sym} كثرة طلبات - انتظار 60ث")
                    time.sleep(60)
                    retry+=1
                    if retry>3:
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
            time.sleep(sleep_base)
            retry=0
        if not frames:
            return None
        d = pd.concat(frames).sort_index()
        return d[~d.index.duplicated(keep="first")]

    store, missing = {}, []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as ex:
        futures = {ex.submit(fetch,s):s for s in dict.fromkeys(symbols)}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                d = future.result()
                if d is not None and len(d) >= min_bars:
                    store[sym] = d
                else:
                    missing.append(sym)
            except Exception as exc:
                missing.append(sym)
                log(f"[{interval}] {sym}: {exc}")
                if sym in cache:
                    store[sym] = cache[sym]
    if "BTCUSDT" not in store or len(store) < 5:
        raise RuntimeError(f"لا توجد بيانات {interval} كافية: يلزم BTC وأربعة رموز أخرى")
    btc_age = now - (store["BTCUSDT"].index[-1] + pd.Timedelta(minutes=age_check_min))
    if btc_age > pd.Timedelta(minutes=age_check_min+1):
        raise RuntimeError(f"بيانات BTC {interval} قديمة؛ أُوقفت الدورة")
    # 4h check تحذير فقط
    four = aggregate_closed_4h(store)
    if "BTCUSDT" not in four or four["BTCUSDT"].index[-1] != now.floor("4h"):
        log(f"[{interval}] تحذير: شمعة BTC 4H غير مكتملة — فحص {interval} مستمر")

    saved = {**cache, **store}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pd.to_pickle({"schema":1,"anchor":anchor,"data":saved}, tmp)
    tmp.replace(path)
    state[anchor_key] = anchor
    state[f"gate_data_status_{interval}"] = {"updated":now.isoformat(), "symbols":list(store), "unavailable":missing, "anchor":anchor, "window_days":days, "interval":interval}
    if missing:
        log(f"[{interval}] رموز غير متاحة: " + ", ".join(missing))
    log(f"[{interval}] Closed candles loaded: {len(store)} symbols; fixed start {anchor}")
    return store

def load_gate_store(symbols, cache_dir, state, days, api_get, log, workers=3):
    """للتوافق — يحمل 5m"""
    return _load_store(symbols, cache_dir, state, days, api_get, log, workers, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5)

def load_gate_store_1m(symbols, cache_dir, state, days, api_get, log, workers=3):
    """الاستراتيجية الأولى — فريم 1 دقيقة"""
    return _load_store(symbols, cache_dir, state, days, api_get, log, workers, "1m", STEP_MS_1M, "gate1m_v102.pkl", 20000, 1)

def load_gate_store_5m(symbols, cache_dir, state, days, api_get, log, workers=3):
    """الاستراتيجية الثانية — فريم 5 دقائق"""
    return _load_store(symbols, cache_dir, state, days, api_get, log, workers, "5m", STEP_MS_5M, "gate5m_v102.pkl", 4800, 5)

def load_dual_stores(symbols, cache_dir, state, days, api_get, log, workers=3):
    """يحمل الاثنين معاً — 1m + 5m — للاستراتيجيتين — يقلل الضغط لتجنب -1003"""
    # تقليل الأيام لتجنب كثرة الطلبات التي تسبب -1003 عند إضافة API
    days_5m = min(days, 20)  # 5m: 20 يوم كافي للإشارات
    days_1m = min(10, max(7, days//6))  # 1m: 7-10 أيام فقط لتجنب -1003
    workers_5m = max(1, min(workers, 3))
    workers_1m = max(1, min(workers, 2))  # عاملان فقط لـ 1m
    try:
        store_5m = load_gate_store_5m(symbols, cache_dir, state, days_5m, api_get, log, workers_5m)
    except Exception as e:
        log(f"[DUAL] 5m failed {e}")
        store_5m = {}
    # فاصل 5 ثواني بين الفريمين لتخفيف وزن الطلبات
    try:
        import time as _t
        _t.sleep(5)
    except: pass
    try:
        store_1m = load_gate_store_1m(symbols, cache_dir, state, days_1m, api_get, log, workers_1m)
    except Exception as e:
        log(f"[DUAL] 1m failed {e}")
        store_1m = {}
    return {"1m": store_1m, "5m": store_5m}
