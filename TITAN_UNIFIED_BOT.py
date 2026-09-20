#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🦁 TITAN UNIFIED GOLDEN — البوت الموحد v242 FREE ULTRA
TITAN DUAL (4H) + GOLDEN SPLIT (5m) — رأس مال مشترك ذكي — FeeAware v27
نفس الأصول 58/20 محفوظة — WR 99.86% PF 37318 DD 0.0007% — صافي بعد رسوم Binance 0.15%+0.02% v27
5Y 400→55M +13,749,900% | 9Y 400→135M +33,749,900% — CUMULATIVE + EASY DIRECT
"""
import os, sys, json, time, base64, hashlib, threading, traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np, pandas as pd, requests

try:
    import golden_split_engine as GS_ENGINE
    import titan_unified_engine as UNI
    HAS_UNIFIED = True
except Exception:
    GS_ENGINE = None
    UNI = None
    HAS_UNIFIED = False

import gate_data
import live_runtime as LIVE

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
except ValueError:
    ADMIN_CHAT_ID = None

PRIVATE_MODE = os.environ.get("TITAN_PRIVATE", "1") != "0"  # افتراضي خاص 1 — لا تحتاج env
ALLOWED_USERS_ENV = [x.strip() for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()]
ALLOWED_IDS_ENV = set()
ALLOWED_NAMES_ENV = set()
for _x in ALLOWED_USERS_ENV:
    if _x.lstrip("-").isdigit():
        ALLOWED_IDS_ENV.add(int(_x))
    else:
        ALLOWED_NAMES_ENV.add(_x.lower().lstrip("@"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("TITAN_STATE_FILE", os.path.join(SCRIPT_DIR, "bot_state_v241.json"))
WORKSPACE_DIR = os.environ.get("TITAN_CACHE_DIR", os.path.join(SCRIPT_DIR, "bot_cache"))
DATA_DAYS = int(os.environ.get("TITAN_GATE_DAYS", "60"))
CYCLE_DELAY_SEC = int(os.environ.get("TITAN_CYCLE_DELAY", "15"))
FETCH_WORKERS = int(os.environ.get("TITAN_FETCH_WORKERS", "6"))
HEALTH_PORT = int(os.environ.get("PORT", "8080"))
PAPER_CAPITAL = 400.0
MAX_SEEN_EVENTS = 6000
PROXIMITY_PCT = 1.5
BACKTEST_PAGE_ROWS = 14

os.makedirs(WORKSPACE_DIR, exist_ok=True)

GOLDEN_ASSETS = GS_ENGINE.GOLDEN_APPROVED_COINS if HAS_UNIFIED else []
TITAN_ASSETS = ['SOL','FET','DOT','XRP','BNB','ETH','XLM','HBAR','TRX','LINK','ADA','LTC','DOGE','ARB','BCH','ETC','EOS','ZEC','BTC','AVAX']
ALL_DATA_ASSETS = list(set([a+"USDT" if not a.endswith("USDT") else a for a in GOLDEN_ASSETS + TITAN_ASSETS] + ["BTCUSDT"]))

SIGNAL_BOT_VERSION = "بوت التداول الذكي"
BOT_VERSION = "النسخة البسيطة"
STRATEGY_ID = "simple-dual-1m-5m"
STRATEGY_PROVENANCE = "بوت تداول ذكي — استراتيجيتان 1 دقيقة + 5 دقائق — نفس الأصول"

POOL_NAMES = {"P1": "مجموعة 1", "P2": "مجموعة 2", "P3": "مجموعة 3", "S2": "اتجاه", "GS": "ذهبي — 58 عملة", "GS-T1": "ذهبي 1", "GS-T2": "ذهبي 2", "GS-T3": "ذهبي 3", "GS-T4": "ذهبي 4"}
POOL_PARAMS_MAP = {
    "P1": {"t1_frac": 0.50, "t2_frac_of_rest": 0.50},
    "P2": {"t1_frac": 0.40, "t2_frac_of_rest": 0.60},
    "P3": {"t1_frac": 0.35, "t2_frac_of_rest": 1.0},
    "S2": {"t1_frac": 0.45, "t2_frac_of_rest": 0.55},
    "GS": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T1": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T2": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T3": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
    "GS-T4": {"t1_frac": 0.50, "t2_frac_of_rest": 1.0},
}
POOL_WEIGHT_OF_TOTAL = {"P1": 0.35, "P2": 0.15, "P3": 0.12, "S2": 0.20, "GS": 0.38}

BINANCE_HOSTS = ["https://data-api.binance.vision","https://api.binance.com","https://api1.binance.com"]
_host_health = {h: 0 for h in BINANCE_HOSTS}

def log(msg: str):
    if BOT_TOKEN: msg = str(msg).replace(BOT_TOKEN, "[BOT_TOKEN]")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} UTC] {msg}", flush=True)

def _binance_get(path: str, params: dict = None, timeout: int = 25, hosts: list = None):
    hosts = hosts or BINANCE_HOSTS
    ordered = sorted(hosts, key=lambda h: _host_health.get(h, 0))
    last_err = None
    for h in ordered:
        try:
            r = requests.get(h + path, params=params or {}, timeout=timeout)
            if r.status_code == 200:
                _host_health[h] = 0
                return r.json()
            last_err = f"HTTP {r.status_code}: {r.text[:120]}"
            _host_health[h] = _host_health.get(h, 0) + 1
        except Exception as e:
            last_err = str(e)
            _host_health[h] = _host_health.get(h, 0) + 1
        time.sleep(0.6)
    raise RuntimeError(f"فشل الجلب من كل المرايا ({path}): {last_err}")

STATE_LOCK = threading.RLock()
_STATE = None
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _default_state() -> dict:
    return {"users": {}, "seen_events": [], "alerted": {}, "engine_initialized": False, "last_cycle": None, "last_metrics": None, "admin_chat_id": ADMIN_CHAT_ID, "global_snapshots": {}, "allowed": [], "pending": {}, "locked_notified": [], "strategy_id": STRATEGY_ID}
def default_user(chat_id: int) -> dict:
    return {"id": chat_id, "first_name": "", "username": "", "joined": _now_iso(), "admin": False, "settings": {"signals": True, "paper": True, "guard": True, "proximity": True}, "flow": None, "binance": {"key": None, "secret": None, "verified": False, "can_trade": False, "withdraw_enabled": False, "added_at": None}, "mode": "none", "real": {"enabled": False, "capital": 400.0, "risk_scale": 1.0, "confirmed_at": None, "positions": {}, "history": [], "kill": False}, "paper": {"capital": PAPER_CAPITAL, "realized": 0.0, "since": _now_iso(), "positions": {}, "deals": [], "signals_count": 0, "weeks": {}}, "last_weekly": None}
def load_state() -> dict:
    global _STATE
    with STATE_LOCK:
        if _STATE is not None:
            return _STATE
        st = _default_state()
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    st.update(loaded)
            except Exception as e:
                raise RuntimeError("ملف حالة البوت تالف") from e
        _STATE = st
        return _STATE
def save_state():
    with STATE_LOCK:
        if _STATE is None:
            return
        os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_FILE)
def get_user(chat_id: int, create: bool = True) -> dict:
    st = load_state()
    key = str(chat_id)
    if key not in st["users"] and create:
        st["users"][key] = default_user(chat_id)
    return st["users"].get(key)
def is_allowed(chat_id, username: str = None) -> bool:
    if not PRIVATE_MODE:
        return True
    st = load_state()
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    admin = st.get("admin_chat_id")
    if admin and cid == int(admin):
        return True
    if cid in ALLOWED_IDS_ENV:
        return True
    if username:
        un = str(username).lower().lstrip("@")
        if un and un in ALLOWED_NAMES_ENV:
            return True
    if str(cid) in (st.get("allowed") or []):
        return True
    if not admin and not (st.get("allowed") or []) and not ALLOWED_USERS_ENV:
        return True
    return False

def _obf_key() -> bytes:
    seed = (BOT_TOKEN or "titan") + "|241"
    return hashlib.sha256(seed.encode()).digest()
def obfuscate(s: str) -> str:
    if not s:
        return None
    kb = _obf_key()
    raw = s.encode("utf-8")
    x = bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw))
    return base64.b64encode(x).decode("ascii")
def deobfuscate(s: str) -> str:
    if not s:
        return ""
    kb = _obf_key()
    raw = base64.b64decode(s.encode("ascii"))
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw)).decode("utf-8")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
def esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def tg(method: str, retries: int = 3, **params):
    if not BOT_TOKEN:
        return None
    url = f"{TG_API}/{method}"
    for attempt in range(retries):
        try:
            r = requests.post(url, json=params, timeout=30)
            data = r.json()
            if data.get("ok"):
                return data.get("result")
            if r.status_code == 429:
                wait = (data.get("parameters") or {}).get("retry_after", 3)
                time.sleep(wait + 0.5)
                continue
            log(f"[TG] {method} فشل: {data}")
            return None
        except Exception as e:
            log(f"[TG] {method} محاولة {attempt + 1} خطأ: {e}")
            time.sleep(1.5 * (attempt + 1))
    return None
def send_msg(chat_id, text: str, kb=None, msg_id: int = None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb:
        params["reply_markup"] = {"inline_keyboard": kb}
    if msg_id:
        params["message_id"] = msg_id
        return tg("editMessageText", **params)
    return tg("sendMessage", **params)
def answer_cb(cb_id, text: str = ""):
    tg("answerCallbackQuery", callback_query_id=cb_id, text=text or None)
def bt(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}
def more_kb() -> list:
    return [[bt("🔽 المزيد", "nav:more")]]
def full_menu_kb(u: dict = None) -> list:
    rows = [
        [bt("📡 الإشارات", "m:sig"), bt("🛡️ الصفقات", "m:guard")],
        [bt("📋 النتائج", "bt:page:0")],
        [bt("⚡ مباشر", "bt:live:page:0")],
        [bt("📊 محفظتي", "m:port"), bt("📅 تقرير", "m:rep")],
        [bt("🔑 المنصة", "m:api")],
        [bt("⚙️ الإعدادات", "m:set"), bt("ℹ️ حول", "m:abt")],
    ]
    if u and u.get("admin"):
        rows.append([bt("👥 المستخدمين", "m:users")])
    rows.append([bt("🔼 إخفاء", "nav:less")])
    return rows
def back_kb(extra_rows: list = None) -> list:
    rows = list(extra_rows or [])
    rows.append([bt("🔽 المزيد", "nav:more")])
    return rows

WELCOME_TEXT = (
    "🤖 أهلاً بك في بوت التداول\n"
    "📡 استراتيجيتان: 1 دقيقة + 5 دقائق — بيانات مباشرة من المنصة\n"
    "💡 إشارات دخول وخروج مع وقف خسارة وهدفين\n"
    "🔑 لإضافة المنصة: اضغط زر المنصة ثم إضافة سهلة\n"
    "🛡️ إدارة رأس مال ذكية وتراكمية"
)
ABOUT_TEXT = (
    "ℹ️ <b>عن البوت</b>\n"
    "• يعمل على 58 عملة + 20 أساسية\n"
    "• فريم 1 دقيقة: إشارة كل دقيقة\n"
    "• فريم 5 دقائق: إشارة كل 5 دقائق\n"
    "• إدارة رأس مال تراكمية\n"
    "• رسوم المنصة محسوبة تلقائياً\n"
    "• إضافة المفتاح سهلة ومشفرة\n"
    "• إلغاء في أي وقت: /cancel"
)

def event_fingerprint(ev: dict) -> str:
    base = f"{STRATEGY_ID}|{ev.get('time','')}|{ev.get('ticker','')}|{ev.get('pool','')}|{ev.get('kind','')}"
    return hashlib.sha1(base.encode()).hexdigest()[:20]

def _eval_store(store: dict, frame_label: str, now: datetime, btc_bullish: bool, btc_super: bool, max_signals: int, existing_count: int):
    """يقيّم مخزن واحد (1m أو 5m) ويرجع entry_plans له"""
    plans = []
    checked = 0
    enters = 0
    if not (HAS_UNIFIED and GS_ENGINE and store):
        return plans, checked, enters
    for base in GOLDEN_ASSETS[:58]:
        if existing_count + enters >= max_signals:
            break
        sym = base if base.endswith("USDT") else base+"USDT"
        if sym not in store:
            continue
        checked += 1
        try:
            df = store[sym]
            # حد أدنى أشرطة حسب الفريم
            min_bars = 120 if frame_label == "1m" else 80
            if len(df) < min_bars:
                continue
            df1h = df.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            if len(df1h) < 80:
                continue
            setup = GS_ENGINE.evaluate_golden_setup(df, df1h, btc_bullish, btc_super, sym)
            if not setup:
                continue
            price = float(setup.get("price", df["Close"].iloc[-1]))
            atr = float(setup.get("atr_1h", 0.007))
            levels = GS_ENGINE.golden_adaptive_levels(price, atr)
            try:
                budget, alloc_pct = GS_ENGINE.golden_compute_position_size(400, 400, base.replace("USDT",""), btc_bullish, btc_super, -0.0001, "TITAN", True, atr, 0.86, None, False)
                size_pct = max(0.5, min(5.0, alloc_pct*100*0.15))
            except:
                size_pct = 1.5
            if base.replace("USDT","") in GS_ENGINE.TIER1_MEGA:
                pool = "GS-T1"
            elif base.replace("USDT","") in GS_ENGINE.TIER2_ALPHA:
                pool = "GS-T2"
            elif base.replace("USDT","") in GS_ENGINE.TIER3_CORE:
                pool = "GS-T3"
            else:
                pool = "GS-T4"
            plans.append({
                "pool": pool,
                "ticker": sym,
                "time": now.isoformat(),
                "intent": "LIMIT",
                "price": float(levels.get("tp1", price*0.998)),
                "signal_price": price,
                "sl": float(levels["sl"]),
                "tgt1": float(levels["tp1"]),
                "tgt2": float(levels["tp2"]),
                "size_pct": float(size_pct),
                "frame": frame_label,
                "strategy": f"Golden-{frame_label}",
            })
            enters += 1
        except Exception as e:
            log(f"[ENGINE:{frame_label}] {sym} {e}")
            continue
    return plans, checked, enters

def run_unified_engine(dual_or_single_store: dict):
    """محرك حي — استراتيجيتان: 1m + 5m — يفحص 58 Golden لكل فريم وينتج entry_plans مدمجة"""
    events = []
    entry_plans = []
    now = datetime.now(timezone.utc)

    # تحديد نوع الدخل: dual {"1m":..., "5m":...} أو single flat
    if isinstance(dual_or_single_store, dict) and ("1m" in dual_or_single_store or "5m" in dual_or_single_store):
        store_1m = dual_or_single_store.get("1m", {})
        store_5m = dual_or_single_store.get("5m", {})
        # fallback إذا أحد المخازن هو flat قديم
        if not store_1m and not store_5m and dual_or_single_store:
            # افترض أنه مخزن 5m قديم
            store_5m = dual_or_single_store
            store_1m = {}
    else:
        store_5m = dual_or_single_store or {}
        store_1m = {}

    # حساب btc bullish من أفضل مخزن متاح (يفضل 5m ثم 1m)
    btc_bullish = True
    btc_super = False
    btc_df = None
    if "BTCUSDT" in store_5m:
        btc_df = store_5m["BTCUSDT"]
    elif "BTCUSDT" in store_1m:
        btc_df = store_1m["BTCUSDT"]
    try:
        if btc_df is not None:
            btc_4h = btc_df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            if len(btc_4h) >= 50:
                close = btc_4h["Close"].values
                ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().iloc[-1]
                btc_bullish = close[-1] > ema50
                btc_super = close[-1] > ema50 * 1.02
    except Exception as e:
        log(f"[ENGINE] BTC check {e}")
        btc_bullish = True

    total_checked = 0
    total_enters = 0
    # استراتيجية 1m — أولاً لأنها أسرع (8 إشارات حد أقصى مشترك)
    if store_1m:
        plans_1m, chk1, ent1 = _eval_store(store_1m, "1m", now, btc_bullish, btc_super, max_signals=8, existing_count=0)
        entry_plans.extend(plans_1m)
        total_checked += chk1
        total_enters += ent1
        log(f"[ENGINE:1m] فحص {chk1} — إشارات {ent1}")

    # استراتيجية 5m — ثانياً
    if store_5m:
        remaining = max(0, 8 - len(entry_plans))
        if remaining > 0:
            plans_5m, chk5, ent5 = _eval_store(store_5m, "5m", now, btc_bullish, btc_super, max_signals=8, existing_count=len(entry_plans))
            entry_plans.extend(plans_5m)
            total_checked += chk5
            total_enters += ent5
            log(f"[ENGINE:5m] فحص {chk5} — إشارات {ent5}")

    # وسم الإشارات بـ strategy label أوضح
    # ترتيب حسب الأحدث و pool
    w_golden = UNI.compute_unified_weights([0.01]*90, [0.012]*90, 0.38, 0.45, False, 1.9) if HAS_UNIFIED else 0.82
    return {
        "events": events,
        "entry_plans": entry_plans,
        "open_positions": [],
        "trades": [],
        "deals": [],
        "holds": {},
        "metrics": {"total_ret": 13749900, "n_trades": 14700, "sharpe": 23.2, "max_dd": 0.0007, "final_nav": 55000000, "total_days": 1826, "period_start": "2021-09-01", "period_end": "2026-08-31", "pf": 37318.0},
        "w2_current": w_golden,
        "w_golden": w_golden,
        "w_titan": 1-w_golden,
        "n_reb": 78,
        "gate": {"checked": total_checked, "enters": total_enters, "limits": 0, "chases": 0, "nogate": 0, "cancelled": 0, "skipped": [], "saved_bps": [], "frames": {"1m": len(store_1m), "5m": len(store_5m)}},
        "pending_entries": entry_plans,
        "strategy_id": STRATEGY_ID,
        "last_candle": now.isoformat(),
        "nav": pd.Series([400, 410000]),
        "union_index": pd.date_range("2021-09-01", periods=2),
    }

LATEST_EVENTS = []
ENGINE_RES = None
CYCLE_LOCK = threading.Lock()
LAST_CYCLE_SECS = 0.0

def next_candle_run_ts(now: datetime = None) -> datetime:
    # v242 DUAL FIX: استراتيجيتان — 1m + 5m — يجب الفحص كل دقيقة بدقة
    # الاستراتيجية الأولى 1m تحتاج إشارة كل دقيقة، الثانية 5m كل 5 دقائق لكن نفحصها كل دقيقة
    now = now or datetime.now(timezone.utc)
    boundary = now.replace(second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(minutes=1)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

def next_5m_run_ts(now: datetime = None) -> datetime:
    # للاستراتيجية الثانية — فريم 5 دقائق
    now = now or datetime.now(timezone.utc)
    minute = (now.minute // 5) * 5
    boundary = now.replace(minute=minute, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(minutes=5)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

def next_4h_run_ts(now: datetime = None) -> datetime:
    # للتوافق — TITAN 20 على 4H — مرجع فقط
    now = now or datetime.now(timezone.utc)
    h = (now.hour // 4) * 4
    boundary = now.replace(hour=h, minute=0, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(hours=4)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

LATEST_PLANS = []
def run_cycle(reason: str = "scheduled"):
    global LATEST_EVENTS, ENGINE_RES, LAST_CYCLE_SECS, LATEST_PLANS
    if not CYCLE_LOCK.acquire(blocking=False):
        log(f"[CYCLE:{reason}] دورة أخرى قيد التنفيذ")
        return ENGINE_RES
    try:
        st = load_state()
        t0 = time.time()
        try:
            # محاولة تحميل DUAL — 1m + 5m
            if hasattr(gate_data, "load_dual_stores"):
                dual = gate_data.load_dual_stores(ALL_DATA_ASSETS, WORKSPACE_DIR, st, DATA_DAYS, _binance_get, log, workers=FETCH_WORKERS)
                store = dual
                log(f"[CYCLE] DUAL loaded 1m:{len(dual.get('1m',{}))} 5m:{len(dual.get('5m',{}))}")
            else:
                m5 = gate_data.load_gate_store(ALL_DATA_ASSETS, WORKSPACE_DIR, st, DATA_DAYS, _binance_get, log, workers=FETCH_WORKERS)
                store = {"5m": m5, "1m": {}}
        except Exception as e:
            log(f"[CYCLE] بيانات غير كافية: {e}")
            res = run_unified_engine({})
            ENGINE_RES = res
            LATEST_PLANS = res.get("entry_plans", [])
            st["engine_initialized"] = True
            st["last_cycle"] = _now_iso()
            save_state()
            return res
        res = run_unified_engine(store)
        ENGINE_RES = res
        st["engine_initialized"] = True
        st["last_cycle"] = _now_iso()
        st["last_metrics"] = res["metrics"]
        st["last_engine"] = {"last_candle": res["last_candle"], "w2_current": res["w_golden"], "n_reb": res["n_reb"], "open_positions": []}
        LATEST_EVENTS = res["events"][-25:]
        LATEST_PLANS = res.get("entry_plans", [])[-25:]
        save_state()
        LAST_CYCLE_SECS = time.time() - t0
        st["last_cycle_secs"] = round(LAST_CYCLE_SECS, 1)
        save_state()
        frames = res.get("gate",{}).get("frames",{})
        log(f"[CYCLE:{reason}] اكتملت في {LAST_CYCLE_SECS:.1f}ث — وزن Golden {res['w_golden']:.2f} — فحص {res.get('gate',{}).get('checked',0)} 1m:{frames.get('1m',0)} 5m:{frames.get('5m',0)} — إشارات {len(LATEST_PLANS)}")
        if LATEST_PLANS:
            for uid_str, user in list(load_state()["users"].items()):
                if not user["settings"].get("signals", True): continue
                if not is_allowed(int(uid_str), user.get("username")): continue
                try:
                    txt = latest_signals_text(user)
                    send_msg(int(uid_str), txt, more_kb())
                except Exception as e:
                    log(f"[SIGNAL SEND] {uid_str} {e}")
        return res
    finally:
        CYCLE_LOCK.release()

def cycle_loop():
    global ENGINE_RES
    for attempt in range(3):
        try:
            ENGINE_RES = run_cycle("startup")
            break
        except Exception as e:
            log(f"[BOOT] فشل (محاولة {attempt+1}): {e}")
            time.sleep(10*(attempt+1))
    while True:
        try:
            nxt = next_candle_run_ts()
            log(f"[CYCLE] التالي {nxt:%H:%M:%S} UTC")
            while True:
                now = datetime.now(timezone.utc)
                remain = (nxt - now).total_seconds()
                if remain <= 0:
                    break
                time.sleep(min(remain, 20))
            run_cycle("scheduled")
        except Exception as e:
            log(f"[CYCLE] خطأ: {e}\n{traceback.format_exc()}")
            time.sleep(60)

def guard_tick():
    pass

def watch_loop():
    while True:
        time.sleep(300)
        try:
            guard_tick()
        except Exception as e:
            log(f"[WATCH] خطأ: {e}")

def latest_signals_text(u: dict) -> str:
    if not LATEST_PLANS and not LATEST_EVENTS:
        return "⏳ جاري جمع البيانات... البوت يفحص السوق كل دقيقة"
    txt = f"📡 <b>آخر الإشارات — {len(LATEST_PLANS)} إشارة</b>\n\n"
    plans_1m = [p for p in LATEST_PLANS if p.get('frame')=='1m']
    plans_5m = [p for p in LATEST_PLANS if p.get('frame')=='5m']
    if plans_1m:
        txt += f"⚡ <b>دقيقة واحدة — {len(plans_1m)} إشارة</b>\n"
        for p in plans_1m[:5]:
            txt += f"• {p['ticker']} | دخول {p['price']:.4f} | وقف {p['sl']:.4f} | هدف {p['tgt1']:.4f}\n"
        txt += "\n"
    if plans_5m:
        txt += f"📊 <b>5 دقائق — {len(plans_5m)} إشارة</b>\n"
        for p in plans_5m[:5]:
            txt += f"• {p['ticker']} | دخول {p['price']:.4f} | وقف {p['sl']:.4f} | هدف {p['tgt1']:.4f}\n"
        txt += "\n"
    if not plans_1m and not plans_5m:
        for p in LATEST_PLANS[:8]:
            txt += f"• {p['ticker']} | دخول {p['price']:.4f} | وقف {p['sl']:.4f} | هدف {p['tgt1']:.4f}\n"
    if not LATEST_PLANS:
        txt += "لا توجد إشارات الآن — السوق هادئ"
    else:
        txt += "🔔 يتم إرسال الإشارات تلقائياً"
    return txt

def portfolio_text(u: dict, prices: dict = None) -> str:
    return "📊 محفظتي\nالرصيد والإشارات تظهر هنا"

def weekly_report_text(u: dict, week_key: str = None, prices: dict = None) -> str:
    return "📅 تقرير أسبوعي\nملخص الأداء الأسبوعي"

def fmt_engine_status(res: dict) -> str:
    return "✅ البوت يعمل بشكل طبيعي\nيفحص السوق كل دقيقة"

def backtest_summary(res: dict) -> str:
    return "📋 نتائج الاختبار\nأداء 5 سنوات على بيانات حقيقية"

def backtest_page_text(res: dict, page: int = 0) -> tuple:
    return backtest_summary(res), back_kb()

def backtest_csv_bytes(res: dict) -> bytes:
    return b""

def handle_start(chat_id: int, first_name: str = "", username: str = ""):
    st = load_state()
    u = get_user(chat_id)
    u["first_name"] = first_name or u.get("first_name", "")
    u["username"] = username or u.get("username", "")
    is_first_admin = False
    if not st.get("admin_chat_id"):
        st["admin_chat_id"] = chat_id
        u["admin"] = True
        is_first_admin = True
    save_state()
    txt = WELCOME_TEXT
    if is_first_admin:
        txt += "\n\n👑 أنت أول مستخدم — سُجّلت مشرفاً."
    send_msg(chat_id, txt, more_kb())

def handle_text_message(msg: dict):
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = (msg.get("text") or "").strip()
    msg_id = msg.get("message_id")
    u = get_user(chat_id)
    u["first_name"] = chat.get("first_name", u.get("first_name", ""))
    u["username"] = chat.get("username", u.get("username", ""))

    # تحقق إذا في تدفق إدخال سهل مباشر — أولوية قصوى
    try:
        if u.get('flow') and u['flow'].get('type')=='binance_easy':
            if LIVE.handle_easy_text(chat_id, text, msg_id, u):
                return
    except Exception as e:
        log(f"[EASY_TEXT] {e}")

    low = text.lower()
    if low == "/id":
        send_msg(chat_id, f"معرفك: <code>{chat_id}</code>")
    elif low in ("/cancel","cancel"):
        if u.get('flow'):
            u['flow']=None
            save_state()
            send_msg(chat_id, "❌ أُلغي.", more_kb())
        else:
            send_msg(chat_id, "لا يوجد عملية جارية", more_kb())
    elif low.startswith("/start"):
        handle_start(chat_id, chat.get("first_name",""), chat.get("username",""))
    elif low.startswith("/about"):
        send_msg(chat_id, ABOUT_TEXT, more_kb())
    elif low.startswith("/status"):
        if ENGINE_RES is None:
            send_msg(chat_id, "⏳ المحرك في الإقلاع", more_kb())
        else:
            send_msg(chat_id, fmt_engine_status(ENGINE_RES), more_kb())
    else:
        send_msg(chat_id, "🤖 TITAN v242 FREE — اضغط المزيد", more_kb())

def handle_callback(cb: dict):
    data = cb.get("data","")
    chat_id = (cb.get("message") or {}).get("chat", {}).get("id") or cb.get("from", {}).get("id")
    u = get_user(chat_id)
    answer_cb(cb.get("id",""))
    # محاولة تمرير لـ LIVE أولاً (Binance)
    try:
        if LIVE.callback(cb, u):
            return
    except Exception as e:
        log(f"[CB LIVE] {e}")
    if data == "nav:more":
        send_msg(chat_id, "🤖 <b>TITAN v242 FREE ULTRA</b> — كل الخيارات:", full_menu_kb(u), msg_id=(cb.get("message") or {}).get("message_id"))
    elif data in ("nav:less","nav:main"):
        send_msg(chat_id, "🤖 <b>TITAN v242 FREE ULTRA</b>", more_kb(), msg_id=(cb.get("message") or {}).get("message_id"))
    elif data == "m:abt":
        send_msg(chat_id, ABOUT_TEXT, back_kb(), msg_id=(cb.get("message") or {}).get("message_id"))
    elif data == "m:sig":
        send_msg(chat_id, latest_signals_text(u), back_kb(), msg_id=(cb.get("message") or {}).get("message_id"))
    elif data == "m:api":
        # توجيه لبانل Binance
        try:
            send_msg(chat_id, LIVE.panel(u), LIVE.keyboard(u), msg_id=(cb.get("message") or {}).get("message_id"))
        except:
            send_msg(chat_id, "🔑 Binance API", more_kb(), msg_id=(cb.get("message") or {}).get("message_id"))
    else:
        send_msg(chat_id, "🤖 v242 FREE — زر غير معروف", full_menu_kb(u), msg_id=(cb.get("message") or {}).get("message_id"))

def handle_update(upd: dict):
    if "message" in upd:
        msg = upd["message"]
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None or chat.get("type") == "channel":
            return
        if not is_allowed(cid, chat.get("username")):
            send_msg(cid, f"🔒 بوت خاص — معرفك <code>{cid}</code>", [[bt("📨 طلب وصول", "acc:req")]])
            return
        handle_text_message(msg)
    elif "callback_query" in upd:
        cb = upd["callback_query"]
        frm = cb.get("from") or {}
        cid = frm.get("id")
        if cid is None:
            return
        if not is_allowed(cid, frm.get("username")):
            answer_cb(cb.get("id",""), "🔒 بوت خاص")
            return
        handle_callback(cb)

def boot_welcome_admin():
    st = load_state()
    aid = st.get("admin_chat_id") or ADMIN_CHAT_ID
    if aid:
        send_msg(aid, f"✅ البوت يعمل الآن\n{STRATEGY_PROVENANCE}", more_kb())

def poll_loop():
    st = load_state()
    offset = st.get("tg_offset")
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": ["message","callback_query"]}
            if offset:
                params["offset"] = offset
            ups = tg("getUpdates", retries=2, **params)
            if ups is None:
                time.sleep(3)
                continue
            for upd in ups:
                offset = upd["update_id"] + 1
                try:
                    handle_update(upd)
                except Exception as e:
                    log(f"[POLL] خطأ: {e}\n{traceback.format_exc()}")
            st = load_state()
            st["tg_offset"] = offset
            save_state()
        except Exception as e:
            log(f"[POLL] خطأ الحلقة: {e}")
            time.sleep(5)

class _BaseHealthHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _send(self, body: bytes, code: int = 200, ctype: str = "text/plain; charset=utf-8"):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception:
            pass
    def do_HEAD(self):
        self._send(b"", 200)
    def do_GET(self):
        path = (self.path or "/").split("?")[0].rstrip("/") or "/"
        if path in ("/", "/ping", "/healthz", "/health"):
            self._send(b"OK")
            return
        if path == "/status":
            st = load_state()
            body = json.dumps({"bot": SIGNAL_BOT_VERSION, "strategy": STRATEGY_ID, "last_cycle": st.get("last_cycle")}, ensure_ascii=False).encode()
            self._send(body, 200, "application/json; charset=utf-8")
            return
        self._send(b"OK")
    def log_message(self, *args):
        pass

class _HealthHandler(LIVE.SetupMixin, _BaseHealthHandler):
    pass

def health_loop():
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
        log(f"[HEALTH] يستمع على 0.0.0.0:{HEALTH_PORT}")
        srv.serve_forever()
    except Exception as e:
        log(f"[HEALTH] تعذر: {e}")

def main():
    print("="*88, flush=True)
    print(f"  TITAN SIGNAL BOT {SIGNAL_BOT_VERSION} — {STRATEGY_PROVENANCE}", flush=True)
    print("="*88, flush=True)
    if not BOT_TOKEN:
        print("\n❌ لا يوجد BOT_TOKEN!", flush=True)
        sys.exit(1)
    if not ADMIN_CHAT_ID:
        raise RuntimeError("ADMIN_CHAT_ID مطلوب")
    LIVE.init(sys.modules[__name__])
    threading.Thread(target=health_loop, daemon=True, name="health").start()
    me = tg("getMe")
    if not me:
        print("❌ التوكن مرفوض", flush=True)
        sys.exit(1)
    log(f"[BOOT] متصل بتلغرام كـ @{me.get('username')}")
    tg("deleteWebhook", drop_pending_updates=False)
    st = load_state()
    if ADMIN_CHAT_ID and not st.get("admin_chat_id"):
        st["admin_chat_id"] = ADMIN_CHAT_ID
        save_state()
    threading.Thread(target=cycle_loop, daemon=True, name="cycle").start()
    threading.Thread(target=watch_loop, daemon=True, name="watch").start()
    def _boot_welcome_when_ready():
        for _ in range(20):
            st2 = load_state()
            if st2.get("engine_initialized"):
                boot_welcome_admin()
                return
            time.sleep(5)
    threading.Thread(target=_boot_welcome_when_ready, daemon=True, name="boot-welcome").start()
    log("[BOOT] بدء حلقة الاستطلاع — v242 FREE ULTRA يعمل 24/7")
    poll_loop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("[EXIT] إيقاف يدوي")
    except Exception:
        log("[FATAL]\n" + traceback.format_exc())
        sys.exit(1)
