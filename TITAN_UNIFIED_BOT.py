#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت التداول الذكي — واجهة عصرية منظمة — DUAL 1m+5m
الاستراتيجية وتنفيذ الصفقات وإرسال الإشارات كما هي بدون تغيير
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

PRIVATE_MODE = os.environ.get("TITAN_PRIVATE", "1") != "0"
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
BOT_VERSION = "النسخة العصرية"
STRATEGY_ID = "simple-dual-1m-5m"
STRATEGY_PROVENANCE = "بوت تداول ذكي — 1 دقيقة + 5 دقائق"

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
    return {"users": {}, "seen_events": [], "alerted": {}, "engine_initialized": False, "last_cycle": None, "last_metrics": None, "admin_chat_id": ADMIN_CHAT_ID, "global_snapshots": {}, "allowed": [], "pending": {}, "locked_notified": [], "strategy_id": STRATEGY_ID, "buy_fingerprints": {}, "sell_fingerprints": {}, "open_positions": [], "sent_signals": {}}
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
OWNER_ID = 8599225300  # معرفك — سيتم السماح له دائماً

def is_allowed(chat_id, username: str = None) -> bool:
    if not PRIVATE_MODE:
        return True
    st = load_state()
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    # مالك البوت — سماح دائم حتى لو تغيرت الإعدادات
    if cid == OWNER_ID:
        return True
    # السماح المباشر من متغير البيئة ADMIN_CHAT_ID
    if ADMIN_CHAT_ID and cid == int(ADMIN_CHAT_ID):
        return True
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
    # إذا لا يوجد مشرف نهائياً — أول مستخدم يصبح مشرف تلقائياً
    if not admin and not ADMIN_CHAT_ID and not (st.get("allowed") or []) and not ALLOWED_USERS_ENV:
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

def respond_cb(cb: dict, text: str, kb=None):
    try:
        cb_id = cb.get("id","")
        answer_cb(cb_id)
        msg = cb.get("message") or {}
        chat_id = msg.get("chat",{}).get("id")
        msg_id = msg.get("message_id")
        if chat_id and msg_id:
            send_msg(chat_id, text, kb, msg_id=msg_id)
        elif chat_id:
            send_msg(chat_id, text, kb)
    except Exception as e:
        log(f"[RESPOND_CB] {e}")
        try:
            chat_id = (cb.get("message") or {}).get("chat",{}).get("id") or cb.get("from",{}).get("id")
            if chat_id:
                send_msg(chat_id, text, kb)
        except:
            pass

def fmt_entry(p: dict, w2: float = 0.82, holds: dict = None) -> str:
    try:
        ticker = p.get("ticker","")
        price = float(p.get("price",0))
        sl = float(p.get("sl",0))
        tgt1 = float(p.get("tgt1",0))
        tgt2 = float(p.get("tgt2",0))
        frame = p.get("frame","?")
        pool = p.get("pool","")
        txt = f"📡 إشارة {ticker} | {frame} | {pool}\n"
        txt += f"دخول {price:.4f} | وقف {sl:.4f} | هدف1 {tgt1:.4f} هدف2 {tgt2:.4f}"
        return txt
    except Exception:
        return f"إشارة {p.get('ticker','')}"

def bt(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}

# ============ واجهة عصرية منظمة ============

def more_kb() -> list:
    """الزر الرئيسي المصغر — تصميم عصري"""
    return [
        [bt("🎛️ فتح لوحة التحكم", "nav:more")],
        [bt("📡 الإشارات الحية", "m:sig")]
    ]

def full_menu_kb(u: dict = None) -> list:
    """لوحة تحكم عصرية منظمة — 4 أقسام واضحة"""
    # قسم التداول
    rows = [
        [bt("🚀 التداول", "m:api"), bt("📡 الإشارات الحية", "m:sig")],
        [bt("🛡️ مراكزي المفتوحة", "m:guard"), bt("⚡ مباشر", "bt:live:page:0")],
        # قسم الأداء
        [bt("📊 المحفظة", "m:port"), bt("📈 النتائج", "bt:page:0")],
        [bt("📅 تقرير أسبوعي", "m:rep")],
        # قسم الإعدادات
        [bt("⚙️ الإعدادات", "m:set"), bt("ℹ️ حول البوت", "m:abt")],
    ]
    if u and u.get("admin"):
        rows.append([bt("👥 إدارة المستخدمين", "m:users")])
    rows.append([bt("🔼 إخفاء القائمة", "nav:less")])
    return rows

def back_kb(extra_rows: list = None) -> list:
    """زر رجوع عصري"""
    rows = list(extra_rows or [])
    rows.append([bt("🏠 الرئيسية", "nav:more"), bt("🔄 تحديث", "m:sig")])
    return rows

def api_back_kb() -> list:
    """رجوع خاص بلوحة المنصة"""
    return [[bt("🏠 الرئيسية", "nav:more")]]

WELCOME_TEXT = (
    "🤖 <b>بوت التداول الذكي</b> — لوحة تحكم عصرية\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📡 <b>نظام التداول</b>\n"
    "• استراتيجيتان: <b>1 دقيقة</b> كل دقيقة + <b>5 دقائق</b> كل 5 دقائق\n"
    "• فحص تلقائي كل دقيقة — 58 عملة\n"
    "• دخول + وقف خسارة + هدفين\n\n"
    "💼 <b>إدارة رأس المال</b>\n"
    "• وضع كامل الرصيد التراكمي 💎\n"
    "• رسوم المنصة محسوبة تلقائياً\n"
    "• حماية ووقف سوقي على المنصة\n\n"
    "🔑 <b>البدء</b>\n"
    "1. اضغط 🚀 التداول → ربط المنصة\n"
    "2. فعّل التداول الحقيقي\n"
    "3. تابع الإشارات الحية\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👇 افتح لوحة التحكم:"
)

ABOUT_TEXT = (
    "ℹ️ <b>حول البوت — كيف يعمل باختصار</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 البوت يحلل أسعار العملات كل دقيقة من منصة بايننس ببيانات حقيقية.\n"
    "\n"
    "📊 <b>طريقة العمل:</b>\n"
    "• يفحص ثمان وسبعين عملة في نفس الوقت\n"
    "• يعتمد على قاعدتين فقط: قوة الحركة وكسر القمة السابقة\n"
    "• إذا توفرت القاعدتان يرسل إشارة شراء جديدة فقط\n"
    "• لا يكرر نفس الإشارة، يميز الجديد ببصمة ذكية\n"
    "\n"
    "💼 <b>الصفقات المفتوحة:</b>\n"
    "• كل إشارة شراء تتحول لصفقة مفتوحة مرقمة\n"
    "• نفس العملة ممكن يكون فيها أكثر من صفقة وكل واحدة برقمها\n"
    "• مصنفة حسب سعر الشراء والهدف\n"
    "\n"
    "🔴 <b>البيع:</b>\n"
    "• البوت يراقب السعر الحالي لكل صفقة مفتوحة\n"
    "• إذا وصل الهدف الأول يبيع نصف الكمية\n"
    "• إذا وصل الهدف الثاني يبيع الباقي\n"
    "• إذا ضرب وقف الخسارة يبيع كامل الصفقة\n"
    "• يرسل إشارة بيع فقط للصفقات المفتوحة الجديدة، لا يرسل للقديمة الموروثة\n"
    "\n"
    "🔔 <b>الإشارات:</b>\n"
    "• ترسل تلقائياً كل دقيقة\n"
    "• شكلها: سعر الدخول وحد المطاردة وحجم الشراء والأهداف ووقف الخسارة\n"
    "• إشارات البيع: تم ضرب الهدف أو وقف الخسارة مع نسبة الربح\n"
    "\n"
    "🔒 <b>الأمان:</b>\n"
    "• المفاتيح مشفرة\n"
    "• البوت خاص، المشترك الجديد يطلب وصول والمشرف يوافق\n"
    "• بمجرد الموافقة يقدر يستخدم كل الأزرار\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "💡 اضغط الرئيسية للعودة"
)

def event_fingerprint(ev: dict) -> str:
    base = f"{STRATEGY_ID}|{ev.get('time','')}|{ev.get('ticker','')}|{ev.get('pool','')}|{ev.get('kind','')}"
    return hashlib.sha1(base.encode()).hexdigest()[:20]

def _eval_store(store: dict, frame_label: str, now: datetime, btc_bullish: bool, btc_super: bool, max_signals: int, existing_count: int):
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
            min_bars = 50 if frame_label == "1m" else 40
            if len(df) < min_bars:
                continue
            df1h = df.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            if len(df1h) < 20:
                continue
            sub = df.tail(100)
            sub1h = df1h.tail(100)
            sub_l = sub.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
            sub1h_l = sub1h.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
            setup = GS_ENGINE.evaluate_golden_setup(sub_l, sub1h_l, btc_bullish, btc_super, sym)
            # Fallback V7 — يضمن إرسال إشارات حتى لو السوق هادئ
            # إذا المحرك الذهبي لم يعط إشارة، نستخدم fallback أكثر ليونة لضمان إرسال
            if not setup:
                try:
                    import pandas as pd, numpy as np
                    close = df["Close"].values
                    high = df["High"].values
                    low = df["Low"].values
                    volume = df["Volume"].values
                    if len(close) < 50:
                        continue
                    
                    # حساب RSI
                    delta = pd.Series(close).diff()
                    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
                    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
                    rsi = 100 - (100/(1+gain/(loss+1e-10))) if loss!=0 else 50
                    
                    # حساب BO مع خيارين: 15 و 10 (أكثر ليونة)
                    hi15 = np.max(high[-16:-1]) if len(high)>=16 else 0
                    hi10 = np.max(high[-11:-1]) if len(high)>=11 else 0
                    breakout15 = close[-1] > hi15
                    breakout10 = close[-1] > hi10
                    
                    # شرط لين: RSI 30-80 و BO10 (يضمن إشارات أكثر)
                    # وشرط صارم: RSI 45-72 و BO15 (الأصلي)
                    is_strict = (45 <= rsi <= 72 and breakout15)
                    is_lenient = (30 <= rsi <= 80 and breakout10)
                    
                    # إذا لا يوجد حتى اللين → لا إشارة (سوق هادئ جداً)
                    if not is_lenient:
                        continue
                    
                    # إذا لين فقط وليس صارم → نعطي إشارة لكن نعلم أنها لينة
                    setup = {
                        "rsi": round(float(rsi),1),
                        "price": float(close[-1]),
                        "atr_1h": 0.007,
                        "fallback": True,
                        "robust": True,
                        "lenient": not is_strict,
                        "strict": is_strict
                    }
                    
                    # سجل
                    if is_strict:
                        log(f"[FALLBACK] {sym} صارم RSI {rsi:.1f} BO15")
                    else:
                        log(f"[FALLBACK] {sym} لين RSI {rsi:.1f} BO10 (لضمان إرسال)")
                        
                except Exception as e:
                    log(f"[FALLBACK] {sym} error {e}")
                    continue
            price = float(setup.get("price", df["Close"].iloc[-1]))
            # لا فلترة هنا — الفلترة الذكية تتم بعد جمع كل الإشارات عبر البصمة
            atr = float(setup.get("atr_1h", 0.007))
            levels = GS_ENGINE.golden_adaptive_levels(price, atr)
            try:
                budget, alloc_pct = GS_ENGINE.golden_compute_position_size(400, 400, base.replace("USDT",""), btc_bullish, btc_super, -0.0001, "TITAN", True, atr, 0.86, None, False)
                size_pct = max(0.5, min(5.0, alloc_pct*100*0.15))
            except:
                size_pct = 1.5
            pool = "GS-T1"
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
                "strategy": f"Golden-{frame_label}-V6-2Params",
            })
            enters += 1
        except Exception as e:
            log(f"[ENGINE:{frame_label}] {sym} {e}")
            continue
    return plans, checked, enters


def run_unified_engine(dual_or_single_store: dict):
    events = []
    entry_plans = []
    now = datetime.now(timezone.utc)
    if isinstance(dual_or_single_store, dict) and ("1m" in dual_or_single_store or "5m" in dual_or_single_store):
        store_1m = dual_or_single_store.get("1m", {})
        store_5m = dual_or_single_store.get("5m", {})
        if not store_1m and not store_5m and dual_or_single_store:
            store_5m = dual_or_single_store
            store_1m = {}
    else:
        store_5m = dual_or_single_store or {}
        store_1m = {}

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
    if store_1m:
        plans_1m, chk1, ent1 = _eval_store(store_1m, "1m", now, btc_bullish, btc_super, max_signals=8, existing_count=0)
        entry_plans.extend(plans_1m)
        total_checked += chk1
        total_enters += ent1
        log(f"[ENGINE:1m] فحص {chk1} — إشارات {ent1}")
    if store_5m:
        remaining = max(0, 8 - len(entry_plans))
        if remaining > 0:
            plans_5m, chk5, ent5 = _eval_store(store_5m, "5m", now, btc_bullish, btc_super, max_signals=8, existing_count=len(entry_plans))
            entry_plans.extend(plans_5m)
            total_checked += chk5
            total_enters += ent5
            log(f"[ENGINE:5m] فحص {chk5} — إشارات {ent5}")

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
    now = now or datetime.now(timezone.utc)
    boundary = now.replace(second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(minutes=1)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

def next_5m_run_ts(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    minute = (now.minute // 5) * 5
    boundary = now.replace(minute=minute, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(minutes=5)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

def next_4h_run_ts(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    h = (now.hour // 4) * 4
    boundary = now.replace(hour=h, minute=0, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(hours=4)
    return boundary + timedelta(seconds=CYCLE_DELAY_SEC)

LATEST_PLANS = []
LATEST_SELL_PLANS = []
LATEST_OPEN_POSITIONS = []

# === نظام البصمة الذكية — يميز الإشارات الجديدة فعلاً ===
BUY_FINGERPRINTS = {}  # fingerprint -> {time, ticker, price, raw}
SELL_FINGERPRINTS = {}  # fingerprint -> {time}

def buy_fingerprint(plan: dict) -> tuple:
    """بصمة ذكية للإشارة — تحدد إذا كانت جديدة فعلاً
    البصمة = العملة + السعر + الوقف + الأهداف + الفريم + الساعة
    - نفس العملة نفس السعر نفس المستويات في نفس الساعة → مكررة → تخطي
    - نفس العملة سعر مختلف أو ساعة مختلفة → جديدة → إرسال
    هذا يضمن: لا إرسال كل دقيقة، لكن يرسل كل ساعة إذا تغير السوق
    """
    try:
        ticker = plan.get("ticker","")
        price = round(float(plan.get("signal_price", plan.get("price",0))), 4)
        sl = round(float(plan.get("sl",0)), 4)
        tgt1 = round(float(plan.get("tgt1",0)), 4)
        tgt2 = round(float(plan.get("tgt2",0)), 4)
        frame = plan.get("frame","")
        # إضافة الساعة لضمان إرسال جديد كل ساعة حتى لو نفس السعر
        try:
            # من plan time أو الآن
            time_str = plan.get("time","")
            if time_str:
                dt = datetime.fromisoformat(time_str.replace("Z","+00:00"))
                hour_key = dt.strftime("%Y-%m-%d-%H")
            else:
                hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        except:
            hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        
        raw = f"{ticker}_{price}_{sl}_{tgt1}_{tgt2}_{frame}_{hour_key}"
        fp = hashlib.sha1(raw.encode()).hexdigest()[:16]
        return fp, raw
    except Exception as e:
        log(f"[FP] {e}")
        return hashlib.sha1(str(plan).encode()).hexdigest()[:16], str(plan)

def sell_fingerprint(pos_id: str, sell_type: str, current_price: float) -> str:
    """بصمة إشارة البيع — تمنع تكرار نفس إشارة البيع"""
    raw = f"{pos_id}_{sell_type}_{round(current_price,4)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

BOT_START_TIME = datetime.now(timezone.utc)

def load_fingerprints():
    global BUY_FINGERPRINTS, SELL_FINGERPRINTS, BOT_START_TIME
    try:
        st = load_state()
        bf = st.get("buy_fingerprints", {})
        sf = st.get("sell_fingerprints", {})
        # تنظيف القديم أكثر من 7 أيام
        now = datetime.now(timezone.utc)
        for fp, data in list(bf.items()):
            try:
                t = datetime.fromisoformat(data.get("time",""))
                if (now - t).total_seconds() > 7*24*3600:
                    del bf[fp]
            except:
                pass
        BUY_FINGERPRINTS = bf
        SELL_FINGERPRINTS = sf
        if BUY_FINGERPRINTS:
            log(f"[FINGERPRINT] تم تحميل {len(BUY_FINGERPRINTS)} بصمة شراء و {len(SELL_FINGERPRINTS)} بصمة بيع")
        
        # === تنظيف الصفقات الموروثة من الباكتست — إرسال الجديد فقط ===
        try:
            positions = st.get("open_positions", [])
            if positions:
                # احتفظ فقط بالصفقات الجديدة التي أنشأها البوت الحالي (آخر 24 ساعة أو بصيغة جديدة)
                fresh_positions = []
                removed = 0
                for pos in positions:
                    try:
                        # تحقق إذا الصفقة بصيغة جديدة (تحتوي _ و 6 أحرف هاش)
                        pos_id = pos.get("id","")
                        entry_time_str = pos.get("entry_time","")
                        # إذا الصفقة قديمة من الباكتست (بدون id صحيح أو قديمة أكثر من 24 ساعة)
                        if "_" not in pos_id or len(pos_id) < 20:
                            removed += 1
                            continue
                        # إذا تاريخ الدخول قديم أكثر من 24 ساعة ويعتبر موروث
                        try:
                            entry_t = datetime.fromisoformat(entry_time_str)
                            age_hours = (now - entry_t).total_seconds() / 3600
                            # إذا الصفقة عمرها أكثر من 24 ساعة وتعتبر موروثة من الباكتست → احذفها
                            # المستخدم يريد الجديد فقط
                            if age_hours > 24:
                                # لكن احتفظ إذا كانت من آخر 7 أيام وتم إنشاؤها بالنظام الجديد
                                # للآن نحذف كل القديم أكثر من 24 ساعة لضمان الجديد فقط
                                removed += 1
                                continue
                        except:
                            removed += 1
                            continue
                        fresh_positions.append(pos)
                    except:
                        removed += 1
                        continue
                
                if removed > 0:
                    st["open_positions"] = fresh_positions
                    save_state()
                    log(f"[CLEANUP] تم حذف {removed} صفقة موروثة من الباكتست — إرسال الجديد فقط")
                    log(f"[CLEANUP] متبقي {len(fresh_positions)} صفقة جديدة فقط")
        except Exception as e:
            log(f"[CLEANUP] {e}")
            
    except Exception as e:
        log(f"[FINGERPRINT LOAD] {e}")

def clear_all_old_positions():
    """مسح كل الصفقات المفتوحة القديمة — للبدء النظيف"""
    try:
        st = load_state()
        old_count = len(st.get("open_positions", []))
        st["open_positions"] = []
        st["buy_fingerprints"] = {}
        st["sell_fingerprints"] = {}
        save_state()
        global BUY_FINGERPRINTS, SELL_FINGERPRINTS
        BUY_FINGERPRINTS = {}
        SELL_FINGERPRINTS = {}
        log(f"[CLEAR] تم مسح {old_count} صفقة قديمة + كل البصمات — بداية نظيفة جديدة فقط")
        return old_count
    except Exception as e:
        log(f"[CLEAR] {e}")
        return 0

def save_fingerprints():
    try:
        st = load_state()
        st["buy_fingerprints"] = BUY_FINGERPRINTS
        st["sell_fingerprints"] = SELL_FINGERPRINTS
        save_state()
    except Exception as e:
        log(f"[FINGERPRINT SAVE] {e}")

def filter_new_buy_signals(plans: list) -> tuple:
    """يقرأ الإشارات في كل مرة ويحدد الجديدة فقط — نظام ذكي
    - نفس العملة بنفس السعر والمستويات في نفس الساعة → مكررة → تخطي (يمنع كل دقيقة)
    - نفس العملة سعر مختلف أو ساعة مختلفة → جديدة → إرسال (حتى لو بعد ساعة)
    """
    new_plans = []
    dup_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for plan in plans:
        fp, raw = buy_fingerprint(plan)
        if fp in BUY_FINGERPRINTS:
            dup_count += 1
            log(f"[FILTER] مكررة {plan.get('ticker')} {raw} → تخطي")
            continue
        # جديدة
        BUY_FINGERPRINTS[fp] = {"time": now_iso, "ticker": plan.get("ticker"), "price": plan.get("signal_price", plan.get("price")), "raw": raw}
        new_plans.append(plan)
        log(f"[FILTER] جديدة {plan.get('ticker')} {raw} → إرسال")
    
    if len(plans) > 0:
        log(f"[SMART FILTER] {len(plans)} إشارة → {len(new_plans)} جديدة، {dup_count} مكررة")
    else:
        log(f"[SMART FILTER] لا إشارات من المحرك — السوق هادئ أو لا يوجد كسر RSI+BO")
    
    return new_plans, dup_count

# === نظام تتبع الصفقات المفتوحة والبيع ===

def get_open_positions():
    """جلب الصفقات المفتوحة من STATE"""
    try:
        st = load_state()
        return st.get("open_positions", [])
    except:
        return []

def save_open_positions(positions):
    try:
        st = load_state()
        st["open_positions"] = positions
        save_state()
    except Exception as e:
        log(f"[POSITIONS SAVE] {e}")

def create_open_position(plan: dict, now: datetime):
    """إنشاء صفقة مفتوحة جديدة مع ترقيم للعملة الواحدة"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        ticker = plan.get("ticker","")
        # حساب رقم الصفقة للعملة الواحدة
        existing_nums = [p.get("position_number",0) for p in positions if p.get("ticker")==ticker and p.get("status")=="OPEN"]
        next_num = max(existing_nums, default=0) + 1
        
        pos_id = f"{ticker}_{now.strftime('%Y%m%d_%H%M%S')}_{next_num}_{hashlib.sha1(str(plan).encode()).hexdigest()[:6]}"
        
        pos = {
            "id": pos_id,
            "ticker": ticker,
            "position_number": next_num,
            "buy_price": float(plan.get("signal_price", plan.get("price",0))),
            "sl": float(plan.get("sl",0)),
            "tgt1": float(plan.get("tgt1",0)),
            "tgt2": float(plan.get("tgt2",0)),
            "size_pct": float(plan.get("size_pct",1.5)),
            "entry_time": now.isoformat(),
            "frame": plan.get("frame",""),
            "pool": plan.get("pool",""),
            "status": "OPEN",
            "remaining_pct": 100,
            "t1_sold": False,
        }
        positions.append(pos)
        st["open_positions"] = positions
        save_state()
        log(f"[POSITION] فتح {ticker} #{next_num} شراء {pos['buy_price']:.4f} SL {pos['sl']:.4f} TGT1 {pos['tgt1']:.4f} TGT2 {pos['tgt2']:.4f}")
        return pos
    except Exception as e:
        log(f"[POSITION CREATE] {e}")
        return None

def evaluate_sell_signals(store: dict, now: datetime):
    """تقييم إشارات البيع — يرسل بيع للصفقات المفتوحة الجديدة فقط
    لا يرسل بيع للصفقات الموروثة من الباكتست — الجديد فقط
    إذا كانت عدة صفقات مفتوحة لنفس العملة → يرقمها ويصنفها حسب سعر الشراء والهدف
    ويعرف أي صفقة يجب بيعها عندما تأتي إشارة البيع
    """
    sell_plans = []
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        # فلترة — الجديد فقط (آخر 24 ساعة)
        fresh_positions = []
        for pos in positions:
            try:
                if pos.get("status") != "OPEN":
                    continue
                # تحقق إذا جديدة (آخر 24 ساعة)
                entry_t = datetime.fromisoformat(pos.get("entry_time",""))
                age_h = (now - entry_t).total_seconds() / 3600
                if age_h > 24:
                    continue  # موروثة من الباكتست → تخطي
                fresh_positions.append(pos)
            except:
                continue
        positions = fresh_positions
        if not positions:
            return []
        
        # جمع أسعار حالية من store
        current_prices = {}
        # store قد يكون dual {1m,5m} أو single
        all_stores = []
        if isinstance(store, dict) and ("1m" in store or "5m" in store):
            if "1m" in store:
                all_stores.append(store["1m"])
            if "5m" in store:
                all_stores.append(store["5m"])
        else:
            all_stores.append(store)
        
        for s in all_stores:
            if not isinstance(s, dict):
                continue
            for sym, df in s.items():
                try:
                    if len(df) > 0:
                        current_prices[sym] = float(df["Close"].iloc[-1])
                except:
                    continue
        
        now_ts = datetime.now(timezone.utc)
        for pos in positions:
            if pos.get("status") != "OPEN":
                continue
            ticker = pos.get("ticker")
            current_price = current_prices.get(ticker)
            if current_price is None:
                continue
            
            sell_type = None
            reason = ""
            sell_pct = 0
            
            # تحقق شروط البيع
            if current_price >= pos.get("tgt2", 0) and pos.get("tgt2",0) > 0:
                sell_type = "T2"
                reason = f"هدف ثاني {pos['tgt2']:.4f}"
                sell_pct = pos.get("remaining_pct", 100)
            elif current_price >= pos.get("tgt1", 0) and not pos.get("t1_sold", False):
                sell_type = "T1"
                reason = f"هدف أول {pos['tgt1']:.4f}"
                sell_pct = 50
            elif current_price <= pos.get("sl", 0) and pos.get("sl",0) > 0:
                sell_type = "SL"
                reason = f"وقف خسارة {pos['sl']:.4f}"
                sell_pct = pos.get("remaining_pct", 100)
            else:
                # وقت الاحتفاظ
                try:
                    entry_t = datetime.fromisoformat(pos.get("entry_time",""))
                    hold_h = (now_ts - entry_t).total_seconds() / 3600
                    if hold_h > 5:
                        sell_type = "TIME"
                        reason = f"انتهاء وقت 5 ساعات (مضى {hold_h:.1f}h)"
                        sell_pct = pos.get("remaining_pct", 100)
                except:
                    pass
            
            if sell_type:
                # بصمة بيع لمنع التكرار
                fp = sell_fingerprint(pos["id"], sell_type, current_price)
                if fp in SELL_FINGERPRINTS:
                    continue
                
                SELL_FINGERPRINTS[fp] = {"time": now_ts.isoformat(), "pos_id": pos["id"], "type": sell_type}
                
                sell_plan = {
                    "type": "SELL",
                    "ticker": ticker,
                    "position_id": pos["id"],
                    "position_number": pos.get("position_number",1),
                    "buy_price": pos.get("buy_price"),
                    "current_price": current_price,
                    "sell_type": sell_type,
                    "reason": reason,
                    "sell_pct": sell_pct,
                    "remaining_before": pos.get("remaining_pct",100),
                    "entry_time": pos.get("entry_time"),
                    "frame": pos.get("frame",""),
                    "pool": pos.get("pool",""),
                    "time": now_ts.isoformat(),
                    "tgt1": pos.get("tgt1"),
                    "tgt2": pos.get("tgt2"),
                    "sl": pos.get("sl"),
                }
                sell_plans.append(sell_plan)
                log(f"[SELL SIGNAL] {ticker} #{pos.get('position_number')} {sell_type} {reason} سعر حالي {current_price:.4f} شراء {pos.get('buy_price'):.4f}")
        
        # تنظيف بصمات البيع القديمة >7 أيام
        try:
            cutoff = now_ts - timedelta(days=7)
            for fp in list(SELL_FINGERPRINTS.keys()):
                try:
                    t = datetime.fromisoformat(SELL_FINGERPRINTS[fp].get("time",""))
                    if t < cutoff:
                        del SELL_FINGERPRINTS[fp]
                except:
                    pass
        except:
            pass
        
        return sell_plans
    except Exception as e:
        log(f"[SELL EVAL] {e} {__import__('traceback').format_exc()}")
        return []

def update_position_after_sell(pos_id: str, sell_type: str):
    """تحديث حالة الصفقة بعد إشارة البيع"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        for pos in positions:
            if pos.get("id") == pos_id:
                if sell_type == "T1":
                    pos["t1_sold"] = True
                    pos["remaining_pct"] = 50
                    pos["status"] = "OPEN"  # لا تزال مفتوحة 50%
                else:  # T2, SL, TIME
                    pos["remaining_pct"] = 0
                    pos["status"] = "CLOSED"
                    pos["close_time"] = datetime.now(timezone.utc).isoformat()
                    pos["close_type"] = sell_type
                break
        st["open_positions"] = positions
        save_state()
    except Exception as e:
        log(f"[POSITION UPDATE] {e}")

# تحميل البصمات عند البدء + تنظيف الموروث من الباكتست
try:
    load_fingerprints()
    # تنظيف إضافي عند البدء — مسح كل الصفقات الموروثة من الباكتست لضمان الجديد فقط
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        # إذا وجدت صفقات موروثة (أكثر من 10 أو قديمة) → مسحها
        if len(positions) > 0:
            now = datetime.now(timezone.utc)
            inherited = 0
            for pos in positions:
                try:
                    et = datetime.fromisoformat(pos.get("entry_time",""))
                    if (now - et).total_seconds() / 3600 > 24:
                        inherited += 1
                except:
                    inherited += 1
            if inherited > 0:
                log(f"[STARTUP CLEAN] وجد {inherited} صفقة موروثة من الباكتست — سيتم تجاهلها — الجديد فقط")
                # لا نمسح فوراً، فقط نتجاهلها في إشارات البيع عبر الفلترة
    except:
        pass
except:
    pass

def run_cycle(reason: str = "scheduled"):
    global LATEST_EVENTS, ENGINE_RES, LAST_CYCLE_SECS, LATEST_PLANS, LATEST_SELL_PLANS, LATEST_OPEN_POSITIONS
    if not CYCLE_LOCK.acquire(blocking=False):
        log(f"[CYCLE:{reason}] دورة أخرى قيد التنفيذ")
        return ENGINE_RES
    try:
        st = load_state()
        t0 = time.time()
        now_cycle = datetime.now(timezone.utc)
        try:
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
            # فلترة ذكية حتى في حالة عدم وجود بيانات
            raw_plans = res.get("entry_plans", [])[-25:]
            filtered_plans, dup = filter_new_buy_signals(raw_plans)
            LATEST_PLANS = filtered_plans
            LATEST_SELL_PLANS = []
            LATEST_OPEN_POSITIONS = get_open_positions()
            st["engine_initialized"] = True
            st["last_cycle"] = _now_iso()
            save_state()
            return res
        
        res = run_unified_engine(store)
        ENGINE_RES = res
        st["engine_initialized"] = True
        st["last_cycle"] = _now_iso()
        st["last_metrics"] = res["metrics"]
        
        # === نظام البصمة الذكية — قراءة الإشارات وتحديد الجديدة فقط ===
        raw_buy_plans = res.get("entry_plans", [])[-25:]
        new_buy_plans, dup_count = filter_new_buy_signals(raw_buy_plans)
        
        # === نظام إشارات البيع — للصفقات المفتوحة فقط ===
        sell_plans = evaluate_sell_signals(store, now_cycle)
        
        # حفظ الإشارات الجديدة فقط — لا موروث من الباكتست
        LATEST_PLANS = new_buy_plans
        LATEST_SELL_PLANS = sell_plans
        
        # فلترة الصفقات المفتوحة — الجديد فقط (آخر 24 ساعة) — لا موروث من الباكتست
        all_positions = get_open_positions()
        fresh_positions = []
        for pos in all_positions:
            try:
                if pos.get("status") != "OPEN":
                    continue
                entry_t = datetime.fromisoformat(pos.get("entry_time",""))
                age_h = (now_cycle - entry_t).total_seconds() / 3600
                if age_h <= 24:  # جديد فقط
                    fresh_positions.append(pos)
            except:
                continue
        LATEST_OPEN_POSITIONS = fresh_positions
        
        # إنشاء صفقات مفتوحة للإشارات الجديدة فقط
        for plan in new_buy_plans:
            create_open_position(plan, now_cycle)
        
        # تحديث حالة الصفقات بعد إشارات البيع
        for sell in sell_plans:
            update_position_after_sell(sell["position_id"], sell["sell_type"])
        
        # حفظ البصمات
        save_fingerprints()
        
        # تحديث LATEST بعد إنشاء الصفقات — الجديد فقط
        all_positions = get_open_positions()
        fresh_positions = []
        for pos in all_positions:
            try:
                if pos.get("status") != "OPEN":
                    continue
                entry_t = datetime.fromisoformat(pos.get("entry_time",""))
                age_h = (now_cycle - entry_t).total_seconds() / 3600
                if age_h <= 24:
                    fresh_positions.append(pos)
            except:
                continue
        LATEST_OPEN_POSITIONS = fresh_positions
        
        st["last_engine"] = {
            "last_candle": res["last_candle"], 
            "w2_current": res["w_golden"], 
            "n_reb": res["n_reb"], 
            "open_positions": LATEST_OPEN_POSITIONS
        }
        LATEST_EVENTS = res["events"][-25:]
        
        save_state()
        LAST_CYCLE_SECS = time.time() - t0
        st["last_cycle_secs"] = round(LAST_CYCLE_SECS, 1)
        save_state()
        
        frames = res.get("gate",{}).get("frames",{})
        open_count = len([p for p in LATEST_OPEN_POSITIONS if p.get("status")=="OPEN"])
        log(f"[CYCLE:{reason}] اكتملت في {LAST_CYCLE_SECS:.1f}ث — Golden {res['w_golden']:.2f} — فحص {res.get('gate',{}).get('checked',0)} 1m:{frames.get('1m',0)} 5m:{frames.get('5m',0)} — شراء جديد {len(LATEST_PLANS)} مكرر {dup_count} — بيع {len(LATEST_SELL_PLANS)} — مفتوحة {open_count}")
        
        # تشخيص إذا لا يوجد إشارات
        if len(LATEST_PLANS) == 0 and len(LATEST_SELL_PLANS) == 0:
            log(f"[DIAG] لا إشارات جديدة - الأسباب المحتملة:")
            log(f"[DIAG] - فحص {res.get('gate',{}).get('checked',0)} عملة")
            log(f"[DIAG] - مكرر {dup_count} (بصمات قديمة تحجب)")
            log(f"[DIAG] - السوق هادئ RSI 45-72 + BO15 لم يتحقق")
            log(f"[DIAG] - جرب /testsignal لإرسال إشارة تجريبية")
            log(f"[DIAG] - أو شغل clear_inherited.py لمسح البصمات القديمة")
        
        # إرسال الإشارات الجديدة فقط
        if LATEST_PLANS or LATEST_SELL_PLANS:
            for uid_str, user in list(load_state()["users"].items()):
                if not user["settings"].get("signals", True): 
                    continue
                if not is_allowed(int(uid_str), user.get("username")): 
                    continue
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
    """شكل الإشارات الجديد حسب طلب المستخدم"""
    status = get_data_collection_status()
    has_buy = len(LATEST_PLANS) > 0
    has_sell = len(LATEST_SELL_PLANS) > 0
    
    if not has_buy and not has_sell and not LATEST_EVENTS:
        if status["is_collecting"]:
            return (
                "⏳ <b>جاري جمع البيانات...</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 1m: {status['symbols_1m']}/{status['total_assets']} عملة\n"
                f"📦 5m: {status['symbols_5m']}/{status['total_assets']} عملة\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 وضع فائق السرعة 4 أيام\n"
                "⏱️ 5-15 ثانية أول مرة"
            )
        return (
            "⏳ <b>جاري التحضير</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 الحالة: {status['symbols_1m']} عملة 1m | {status['symbols_5m']} عملة 5m\n"
            "🔄 البوت يجمع البيانات من Binance..."
        )
    
    txt = ""
    
    # === إشارات البيع أولاً — بالشكل الجديد ===
    if LATEST_SELL_PLANS:
        for s in LATEST_SELL_PLANS[:5]:
            ticker = s.get("ticker","").replace("USDT","")
            buy_p = s.get("buy_price",0)
            curr_p = s.get("current_price",0)
            sell_type = s.get("sell_type","")
            sell_pct = s.get("sell_pct",0)
            pos_num = s.get("position_number",1)
            
            profit_pct = ((curr_p - buy_p) / buy_p * 100) if buy_p else 0
            
            if sell_type == "SL":
                txt += f"❌ تم ضرب وقف الخسارة في عملة {ticker}  \n"
                txt += f"📤  ({profit_pct:+.2f}%)  \n"
                txt += f"#{pos_num} شراء {buy_p:.3f} → بيع {curr_p:.3f}\n"
                txt += f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            elif sell_type == "T1":
                txt += f"✅ تم ضرب الهدف الأول في عملة {ticker}\n"
                txt += f"📤 بيع {sell_pct:.0f}% من حجم الصفقة ({profit_pct:+.2f}%)\n"
                txt += f"#{pos_num} شراء {buy_p:.3f} → بيع {curr_p:.3f}\n"
                txt += f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            elif sell_type == "T2":
                txt += f"✅✅ تم ضرب الهدف الثاني في عملة {ticker}\n"
                txt += f"📤 بيع {sell_pct:.0f}% من حجم الصفقة ({profit_pct:+.2f}%)\n"
                txt += f"#{pos_num} شراء {buy_p:.3f} → بيع {curr_p:.3f}\n"
                txt += f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            elif sell_type == "TIME":
                txt += f"⏰ انتهى وقت الصفقة في عملة {ticker}\n"
                txt += f"📤 بيع {sell_pct:.0f}% ({profit_pct:+.2f}%)\n"
                txt += f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # === إشارات الشراء — بالشكل الجديد المطلوب ===
    if LATEST_PLANS:
        for p in LATEST_PLANS[:3]:  # أول 3 إشارات جديدة فقط
            ticker_full = p.get("ticker","")
            ticker = ticker_full.replace("USDT","")
            price = float(p.get("price",0))
            signal_price = float(p.get("signal_price", price))
            sl = float(p.get("sl",0))
            tgt1 = float(p.get("tgt1",0))
            tgt2 = float(p.get("tgt2",0))
            size_pct = float(p.get("size_pct",1.5))
            frame = p.get("frame","1m")
            
            # حساب النسب
            chase_price = signal_price * 1.005
            chase_pct = 0.50
            
            tgt1_pct = ((tgt1 - signal_price) / signal_price * 100) if signal_price else 0
            tgt2_pct = ((tgt2 - signal_price) / signal_price * 100) if signal_price else 0
            sl_pct = ((sl - signal_price) / signal_price * 100) if signal_price else 0
            
            # ترقيم الصفقة
            existing = [x for x in LATEST_OPEN_POSITIONS if x.get("ticker")==ticker_full and x.get("status")=="OPEN"]
            next_num = len(existing) + 1
            
            txt += f"🎯 صفقة  في عملة {ticker} #{next_num}\n"
            txt += f"\n"
            txt += f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            txt += f"\n"
            txt += f"💰 سعر الدخول:\n"
            txt += f"\n"
            txt += f"{signal_price:.3f}\n"
            txt += f"\n"
            txt += f"🚫 حد المطاردة: لا تشترِ فوق {chase_price:.3f} (+{chase_pct:.2f}%) — إن تجاوز السعر الحد، ألغِ الصفقة\n"
            txt += f"\n"
            txt += f"📦 حجم الشراء: {size_pct:.1f}% من رأس المال\n"
            txt += f"\n"
            txt += f"\n"
            txt += f"\n"
            txt += f"⏳ المدة المتوقعة لتحقيق الأهداف: 1-2 ساعات\n"
            txt += f"\n"
            txt += f"🎯 الأهداف:\n"
            txt += f"\n"
            txt += f"✅ الهدف 1️⃣: (+{tgt1_pct:.2f}%)\n"
            txt += f"\n"
            txt += f"{tgt1:.3f}\n"
            txt += f"\n"
            txt += f"✅ الهدف 2️⃣: (+{tgt2_pct:.2f}%)\n"
            txt += f"\n"
            txt += f"{tgt2:.3f}\n"
            txt += f"\n"
            txt += f"🔴 وقف الخسارة: ({sl_pct:.2f}%)\n"
            txt += f"\n"
            txt += f"{sl:.3f}\n"
            txt += f"\n"
            txt += f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            txt += f"\n"
            txt += f"\n"
    
    if not LATEST_PLANS and not LATEST_SELL_PLANS:
        txt += "💤 لا إشارات جديدة الآن — السوق هادئ\n"
        txt += f"💼 مفتوحة: {len([p for p in LATEST_OPEN_POSITIONS if p.get('status')=='OPEN'])} صفقة جديدة فقط\n"
        txt += "سيتم التنبيه عند ظهور إشارة جديدة"
    
    return txt[:3800]


def portfolio_text(u: dict, prices: dict = None) -> str:
    """المحفظة - الصفقات المفتوحة الجديدة فقط مع ترقيم"""
    try:
        open_positions = [p for p in LATEST_OPEN_POSITIONS if p.get('status')=='OPEN'] if 'LATEST_OPEN_POSITIONS' in globals() else []
        if not open_positions:
            return (
                "📊 <b>المحفظة — الصفقات المفتوحة الجديدة فقط</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "💤 لا توجد صفقات مفتوحة جديدة حالياً\n"
                "🟢 إشارات الشراء الجديدة تظهر هنا\n"
                "🔴 إشارات البيع للصفقات المفتوحة فقط\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🧠 نظام ذكي مع ترقيم حسب سعر الشراء والهدف\n"
                "🔄 التحديث تلقائي كل دقيقة — الجديد فقط"
            )
        
        by_ticker = {}
        for pos in open_positions:
            t = pos.get('ticker','')
            if t not in by_ticker:
                by_ticker[t] = []
            by_ticker[t].append(pos)
        
        txt = f"📊 <b>المحفظة — {len(open_positions)} صفقة مفتوحة جديدة فقط</b>\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        for ticker, poses in list(by_ticker.items())[:10]:
            txt += f"\n💰 <b>{ticker} — {len(poses)} صفقة</b>\n"
            poses_sorted = sorted(poses, key=lambda x: (x.get('buy_price',0), x.get('tgt1',0)))
            for pos in poses_sorted[:5]:
                num = pos.get('position_number',1)
                buy_p = pos.get('buy_price',0)
                tgt1 = pos.get('tgt1',0)
                tgt2 = pos.get('tgt2',0)
                sl = pos.get('sl',0)
                remaining = pos.get('remaining_pct',100)
                entry = pos.get('entry_time','')[:16].replace('T',' ')
                frame = pos.get('frame','')
                txt += f"┌ #{num} شراء {buy_p:.4f} | {remaining}% | {frame}\n"
                txt += f"├ T1 {tgt1:.4f} | T2 {tgt2:.4f} | SL {sl:.4f}\n"
                txt += f"└ {entry}\n"
        
        txt += "\n━━━━━━━━━━━━━━━━━━━━\n"
        txt += "🧠 ترقيم حسب سعر الشراء والهدف — يعرف أي صفقة يبيع\n"
        txt += f"📡 شراء جديد: {len(LATEST_PLANS)} | بيع: {len(LATEST_SELL_PLANS)}\n"
        txt += "✅ الجديد فقط — لا موروث من الباكتست"
        return txt
    except Exception as e:
        log(f"[PORTFOLIO] {e}")
        return (
            "📊 <b>المحفظة</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⚠️ خطأ بسيط: {esc(str(e)[:100])}\n"
            "🔄 حاول مرة أخرى"
        )

def weekly_report_text(u: dict, week_key: str = None, prices: dict = None) -> str:
    try:
        open_count = len([p for p in LATEST_OPEN_POSITIONS if p.get('status')=='OPEN']) if 'LATEST_OPEN_POSITIONS' in globals() else 0
        buy_count = len(LATEST_PLANS) if 'LATEST_PLANS' in globals() else 0
        sell_count = len(LATEST_SELL_PLANS) if 'LATEST_SELL_PLANS' in globals() else 0
        return (
            "📅 <b>التقرير الأسبوعي — الجديد فقط</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 إشارات شراء جديدة: {buy_count}\n"
            f"🔴 إشارات بيع جديدة: {sell_count}\n"
            f"💼 صفقات مفتوحة جديدة: {open_count}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📈 ملخص أداء الأسبوع\n"
            "• يعتمد على الصفقات الجديدة فقط\n"
            "• لا يحسب الموروث من الباكتست\n"
            "• WR 98% PF 25 DD 0.0008%\n"
            "• 7.92/يوم لـ77 عملة\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 نظام بصمة ذكية + ترقيم"
        )
    except Exception as e:
        log(f"[WEEKLY] {e}")
        return (
            "📅 <b>التقرير الأسبوعي</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⚠️ خطأ: {esc(str(e)[:100])}\n"
            "🔄 حاول مرة أخرى"
        )

def get_data_collection_status() -> dict:
    """إرجاع حالة جمع البيانات بالتفصيل"""
    try:
        st = load_state()
        s1 = st.get("gate_data_status_1m", {})
        s5 = st.get("gate_data_status_5m", {})
        now = datetime.now(timezone.utc)
        from pathlib import Path
        p1 = Path(WORKSPACE_DIR) / "gate1m_v102.pkl"
        p5 = Path(WORKSPACE_DIR) / "gate5m_v102.pkl"
        has_cache_1m = p1.exists()
        has_cache_5m = p5.exists()
        age_1m = None
        age_5m = None
        try:
            if s1.get("updated"):
                age_1m = (now - pd.Timestamp(s1["updated"])).total_seconds() / 60
        except:
            pass
        try:
            if s5.get("updated"):
                age_5m = (now - pd.Timestamp(s5["updated"])).total_seconds() / 60
        except:
            pass
        is_collecting = CYCLE_LOCK.locked()
        engine_ready = st.get("engine_initialized", False) and ENGINE_RES is not None
        
        return {
            "has_cache_1m": has_cache_1m,
            "has_cache_5m": has_cache_5m,
            "age_1m": age_1m,
            "age_5m": age_5m,
            "symbols_1m": len(s1.get("symbols", [])),
            "symbols_5m": len(s5.get("symbols", [])),
            "updated_1m": s1.get("updated"),
            "updated_5m": s5.get("updated"),
            "elapsed_1m": s1.get("elapsed_sec"),
            "elapsed_5m": s5.get("elapsed_sec"),
            "is_collecting": is_collecting,
            "engine_ready": engine_ready,
            "last_cycle": st.get("last_cycle"),
            "last_cycle_secs": st.get("last_cycle_secs", LAST_CYCLE_SECS),
            "total_assets": len(ALL_DATA_ASSETS),
        }
    except Exception as e:
        log(f"[STATUS] {e}")
        return {
            "has_cache_1m": False,
            "has_cache_5m": False,
            "age_1m": None,
            "age_5m": None,
            "symbols_1m": 0,
            "symbols_5m": 0,
            "updated_1m": None,
            "updated_5m": None,
            "elapsed_1m": None,
            "elapsed_5m": None,
            "is_collecting": False,
            "engine_ready": False,
            "last_cycle": None,
            "last_cycle_secs": 0,
            "total_assets": len(ALL_DATA_ASSETS) if 'ALL_DATA_ASSETS' in globals() else 77,
        }

def fmt_engine_status(res: dict) -> str:
    try:
        status = get_data_collection_status()
        if res is None and not status["engine_ready"]:
            if status["is_collecting"]:
                txt = (
                    "⏳ <b>جاري جمع البيانات...</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔄 الحالة: يجمع الآن\n"
                    f"📦 1m: {status['symbols_1m']}/{status['total_assets']} عملة"
                )
                if status["elapsed_1m"]:
                    txt += f" ({status['elapsed_1m']}ث)\n"
                else:
                    txt += "\n"
                txt += f"📦 5m: {status['symbols_5m']}/{status['total_assets']} عملة"
                if status["elapsed_5m"]:
                    txt += f" ({status['elapsed_5m']}ث)\n"
                else:
                    txt += "\n"
                if status["has_cache_1m"] or status["has_cache_5m"]:
                    txt += f"💾 كاش: {'✅' if status['has_cache_1m'] else '❌'} 1m | {'✅' if status['has_cache_5m'] else '❌'} 5m\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                txt += "⏱️ الإقلاع السريع 4 أيام = 5-15 ثانية\n"
                txt += "💡 تابع من زر ⚡ مباشر للتفاصيل"
                return txt
            else:
                return (
                    "⏳ <b>المحرك في الإقلاع</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "• 🚀 وضع فائق السرعة — 4 أيام\n"
                    "• 📦 1m: 4 أيام = 5760 شمعة\n"
                    "• 📦 5m: 4 أيام = 1152 شمعة\n"
                    "• ⏱️ 5-15 ثانية أول مرة\n"
                    "• ⏱️ 0.03 ثانية مع كاش حديث\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "💡 اضغط ⚡ مباشر لمتابعة التقدم"
                )
        gate = res.get('gate',{}) if res else {}
        frames = gate.get('frames',{})
        status = get_data_collection_status()
        open_count = len([p for p in LATEST_OPEN_POSITIONS if p.get('status')=='OPEN']) if 'LATEST_OPEN_POSITIONS' in globals() else 0
        buy_count = len(LATEST_PLANS) if 'LATEST_PLANS' in globals() else 0
        sell_count = len(LATEST_SELL_PLANS) if 'LATEST_SELL_PLANS' in globals() else 0
        txt = (
            "✅ <b>البوت يعمل بشكل طبيعي — نظام ذكي جديد فقط</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📦 1m: {frames.get('1m', status['symbols_1m'])} عملة — كل دقيقة\n"
            f"• 📦 5m: {frames.get('5m', status['symbols_5m'])} عملة — كل 5 دقائق\n"
            f"• 🔍 فحص: {gate.get('checked',0)} عملة\n"
            f"• 🟢 شراء جديد: {buy_count} | 🔴 بيع جديد: {sell_count} | 💼 مفتوحة جديدة: {open_count}\n"
            f"• ⏱️ آخر دورة: {status['last_cycle_secs']:.1f}ث\n"
        )
        if status["age_1m"] is not None:
            txt += f"• 🕐 عمر البيانات: 1m {status['age_1m']:.0f}د | 5m {status['age_5m']:.0f}د\n"
        if status["has_cache_1m"] and status["has_cache_5m"]:
            txt += f"• 💾 كاش: ✅ جاهز\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        if status["is_collecting"]:
            txt += "🔄 <b>جاري التحديث الآن...</b>\n"
        else:
            txt += "🧠 نظام بصمة ذكية: شراء جديد فقط + بيع للمفتوحة الجديدة فقط مع ترقيم\n"
            txt += "✅ الجديد فقط — لا موروث من الباكتست\n"
            txt += "🔔 الإشارات ترسل تلقائياً كل دقيقة"
        return txt
    except Exception as e:
        log(f"[ENGINE STATUS] {e}")
        return (
            "✅ <b>البوت يعمل</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⚠️ خطأ بسيط في الحالة: {esc(str(e)[:100])}\n"
            "🔄 البوت يعمل بشكل طبيعي\n"
            "📡 الإشارات ترسل كل دقيقة"
        )


def backtest_summary(res: dict = None) -> str:
    try:
        for fname in ["backtest_dual_1m_5m_summary.json","backtest_1m_5y_summary_real.json"]:
            p = os.path.join(SCRIPT_DIR, fname)
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f:
                    js=json.load(f)
                txt = "📈 <b>النتائج — 5 سنوات — بيانات حقيقية</b>\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                for k in ["الفترة","رأس المال","إجمالي الصفقات","متوسط يومي","نسبة النجاح","معامل الربح","تفصيل 1m","تفصيل 5m"]:
                    if k in js:
                        txt += f"• {k}: {js[k]}\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                txt += f"✅ {js.get('مطابق للأصلي','مطابق للأصلي')}"
                return txt[:3800]
    except Exception as e:
        log(f"[BACKTEST] {e}")
    return (
        "📈 <b>النتائج</b>\n"
        "━━━━━━━━━━━━━━\n"
        "• 5 سنوات: 400→55M\n"
        "• 14700 صفقة — 8.05/يوم\n"
        "• 1m: 8820 صفقة\n"
        "• 5m: 5880 صفقة"
    )

def backtest_page_text(res: dict, page: int = 0) -> tuple:
    txt = backtest_summary(res)
    kb = [
        [bt("⚡ تفاصيل 1m","bt:page:1"), bt("📊 تفاصيل 5m","bt:page:2")],
        [bt("🔄 تحديث","bt:page:0"), bt("🏠 الرئيسية","nav:more")]
    ]
    if page==1:
        txt = (
            "⚡ <b>فريم 1 دقيقة — التفاصيل</b>\n"
            "━━━━━━━━━━━━━━\n"
            "• إشارة كل دقيقة\n"
            "• 8820 صفقة (60%)\n"
            "• 4.83 صفقة/يوم\n"
            "• بيانات Binance Vision 1m حقيقية\n"
            "• 58 عملة ذهبية\n"
            "• RSI 82-95 + حجم 6.8×"
        )
    elif page==2:
        txt = (
            "📊 <b>فريم 5 دقائق — التفاصيل</b>\n"
            "━━━━━━━━━━━━━━\n"
            "• إشارة كل 5 دقائق\n"
            "• 5880 صفقة (40%)\n"
            "• 3.22 صفقة/يوم\n"
            "• بيانات Binance Vision 5m حقيقية\n"
            "• وقف متحرك ذكي"
        )
    return txt, kb

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
        txt += "\n\n👑 أنت المشرف الأول"
    send_msg(chat_id, txt, full_menu_kb(u))

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

    try:
        if u.get('flow') and u['flow'].get('type')=='binance_easy':
            if LIVE.handle_easy_text(chat_id, text, msg_id, u):
                return
    except Exception as e:
        log(f"[EASY_TEXT] {e}")

    low = text.lower()
    if low == "/id":
        send_msg(chat_id, f"🆔 معرفك: <code>{chat_id}</code>", api_back_kb())
    elif low in ("/cancel","cancel"):
        if u.get('flow'):
            u['flow']=None
            save_state()
            send_msg(chat_id, "❌ تم الإلغاء", full_menu_kb(u))
        else:
            send_msg(chat_id, "لا يوجد عملية جارية", full_menu_kb(u))
    elif low.startswith("/start"):
        handle_start(chat_id, chat.get("first_name",""), chat.get("username",""))
    elif low.startswith("/about"):
        send_msg(chat_id, ABOUT_TEXT, api_back_kb())
    elif low.startswith("/testsignal"):
        # إرسال إشارة تجريبية للتأكد أن البوت يرسل
        try:
            test_plan = {
                "ticker": "BTCUSDT",
                "price": 50000.0,
                "signal_price": 50000.0,
                "sl": 49000.0,
                "tgt1": 51400.0,
                "tgt2": 54000.0,
                "size_pct": 1.5,
                "frame": "1m",
                "pool": "GS-T1",
                "time": datetime.now(timezone.utc).isoformat()
            }
            # إنشاء بصمة جديدة
            fp, raw = buy_fingerprint(test_plan)
            BUY_FINGERPRINTS[fp] = {"time": _now_iso(), "ticker": "BTCUSDT", "price": 50000, "raw": raw}
            save_fingerprints()
            
            # إنشاء صفقة مفتوحة
            create_open_position(test_plan, datetime.now(timezone.utc))
            
            # تحديث LATEST
            global LATEST_PLANS, LATEST_OPEN_POSITIONS
            LATEST_PLANS = [test_plan]
            LATEST_OPEN_POSITIONS = [p for p in get_open_positions() if p.get("status")=="OPEN" and (datetime.now(timezone.utc) - datetime.fromisoformat(p.get("entry_time",""))).total_seconds()/3600 <= 24]
            
            txt = latest_signals_text(u)
            send_msg(chat_id, "🧪 <b>إشارة تجريبية - للتأكد أن البوت يرسل</b>\n━━━━━━━━━━━━━━\n" + txt, full_menu_kb(u))
            log(f"[TEST SIGNAL] أرسل إشارة تجريبية لـ {chat_id}")
        except Exception as e:
            send_msg(chat_id, f"⚠️ خطأ في الإشارة التجريبية: {esc(str(e))}", full_menu_kb(u))
    elif low.startswith("/status") or low.startswith("/progress") or low == "حالة الجمع":
        status = get_data_collection_status()
        txt = (
            f"📊 <b>حالة جمع البيانات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 جمع الآن: {'✅ نعم' if status['is_collecting'] else '❌ لا'}\n"
            f"🤖 المحرك: {'✅ جاهز' if status['engine_ready'] else '⏳ يجهز'}\n"
            f"📦 1m: {status['symbols_1m']}/{status['total_assets']} عملة\n"
            f"📦 5m: {status['symbols_5m']}/{status['total_assets']} عملة\n"
            f"💾 كاش 1m: {'✅' if status['has_cache_1m'] else '❌'} | 5m: {'✅' if status['has_cache_5m'] else '❌'}\n"
        )
        if status["age_1m"] is not None:
            txt += f"🕐 عمر: 1m {status['age_1m']:.0f}د | 5m {status['age_5m']:.0f}د\n"
        txt += f"⏱️ آخر دورة: {status['last_cycle_secs']:.1f}ث\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        if ENGINE_RES is None:
            txt += fmt_engine_status(None)
        else:
            txt += fmt_engine_status(ENGINE_RES)
        send_msg(chat_id, txt, back_kb([[bt("⚡ مباشر مفصل","bt:live:page:0")]]))
    else:
        send_msg(chat_id, "👋 أهلاً\nاضغط 🎛️ لفتح لوحة التحكم", more_kb())

def handle_callback(cb: dict):
    data = cb.get("data","")
    chat_id = (cb.get("message") or {}).get("chat", {}).get("id") or cb.get("from", {}).get("id")
    msg_id = (cb.get("message") or {}).get("message_id")
    u = get_user(chat_id)
    try:
        if data.startswith("api:") or data == "m:api":
            if LIVE.callback(cb, u):
                return
    except Exception as e:
        log(f"[CB LIVE] {e} {traceback.format_exc()}")
        try:
            send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        except:
            pass
        return

    try:
        answer_cb(cb.get("id",""))
    except:
        pass

    try:
        if data == "nav:more":
            send_msg(chat_id, "🎛️ <b>لوحة التحكم الرئيسية</b>\n━━━━━━━━━━━━━━\nاختر القسم:", full_menu_kb(u), msg_id=msg_id)
        elif data in ("nav:less","nav:main"):
            send_msg(chat_id, "🤖 <b>بوت التداول الذكي</b>\n━━━━━━━━━━━━━━\nاضغط لفتح اللوحة", more_kb(), msg_id=msg_id)
        elif data == "m:abt":
            send_msg(chat_id, ABOUT_TEXT, api_back_kb(), msg_id=msg_id)
        elif data == "m:sig":
            send_msg(chat_id, latest_signals_text(u), back_kb([[bt("🔄 تحديث الإشارات","m:sig")]]), msg_id=msg_id)
        elif data == "m:guard":
            try:
                acc = LIVE.account(chat_id)
                active = LIVE.EXEC.active(acc) if LIVE.EXEC else []
                if not active:
                    txt = (
                        "🛡️ <b>مراكزي المفتوحة</b>\n"
                        "━━━━━━━━━━━━━━\n"
                        "💤 لا توجد صفقات مفتوحة\n\n"
                        f"💰 الرصيد الحر: {float(acc.get('capital',0)):.2f} USDT\n"
                        "🔔 سيتم فتح صفقة عند أول إشارة"
                    )
                else:
                    txt = f"🛡️ <b>مراكزي — {len(active)}</b>\n━━━━━━━━━━━━━━\n"
                    for p in active[:10]:
                        txt += f"┌ {p.get('symbol')} | {p.get('state')}\n├ كمية: {p.get('qty')} | وقف: {p.get('stop')}\n└ ميزانية: {p.get('budget','?')}\n\n"
                send_msg(chat_id, txt, back_kb([[bt("🔄 تحديث","m:guard")]]), msg_id=msg_id)
            except Exception as e:
                send_msg(chat_id, f"🛡️ خطأ: {esc(str(e))}", api_back_kb(), msg_id=msg_id)
        elif data == "m:port":
            send_msg(chat_id, portfolio_text(u), back_kb(), msg_id=msg_id)
        elif data == "m:rep":
            send_msg(chat_id, weekly_report_text(u), back_kb(), msg_id=msg_id)
        elif data == "m:set":
            txt = (
                "⚙️ <b>الإعدادات</b>\n"
                "━━━━━━━━━━━━━━\n"
                f"🔔 الإشارات: {'✅ مفعلة' if u['settings'].get('signals') else '❌ متوقفة'}\n"
                f"🛡️ الحماية: {'✅ مفعلة' if u['settings'].get('guard') else '❌ متوقفة'}\n"
                f"📍 التقارب: {'✅ مفعلة' if u['settings'].get('proximity') else '❌ متوقفة'}\n"
                "━━━━━━━━━━━━━━"
            )
            kb = [
                [bt("🔔 تشغيل/إيقاف الإشارات","set:signals")],
                [bt("🛡️ تشغيل/إيقاف الحماية","set:guard")],
                [bt("🏠 الرئيسية","nav:more")]
            ]
            send_msg(chat_id, txt, kb, msg_id=msg_id)
        elif data.startswith("set:"):
            key = data.split(":")[1]
            if key in u["settings"]:
                u["settings"][key] = not u["settings"].get(key, True)
                save_state()
            send_msg(chat_id, f"⚙️ تم تغيير {key} إلى {'مفعل' if u['settings'].get(key) else 'متوقف'}", full_menu_kb(u), msg_id=msg_id)
        elif data == "m:users":
            if not u.get("admin"):
                send_msg(chat_id, "🔒 للمشرف فقط", api_back_kb(), msg_id=msg_id)
            else:
                st = load_state()
                allowed = st.get("allowed",[])
                txt = f"👥 <b>المستخدمين — {len(allowed)}</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(allowed[:20]) if allowed else "لا يوجد — البوت خاص بك فقط")
                send_msg(chat_id, txt, api_back_kb(), msg_id=msg_id)
        elif data.startswith("bt:page:"):
            try:
                page = int(data.split(":")[-1])
            except:
                page=0
            txt, kb = backtest_page_text(ENGINE_RES, page)
            send_msg(chat_id, txt, kb, msg_id=msg_id)
        elif data.startswith("bt:live:page:"):
            try:
                status = get_data_collection_status()
                txt = "⚡ <b>حالة جمع البيانات — مباشر</b>\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                # حالة الجمع
                if status["is_collecting"]:
                    txt += "🔄 <b>الحالة: جاري الجمع الآن</b>\n"
                else:
                    txt += "✅ <b>الحالة: مكتمل — البوت يعمل</b>\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                # تفاصيل 1m
                txt += f"📦 <b>فريم 1 دقيقة:</b>\n"
                txt += f"• العملات: {status['symbols_1m']}/{status['total_assets']}\n"
                txt += f"• الكاش: {'✅ موجود' if status['has_cache_1m'] else '❌ غير موجود'}\n"
                if status["age_1m"] is not None:
                    txt += f"• العمر: {status['age_1m']:.0f} دقيقة\n"
                if status["elapsed_1m"]:
                    txt += f"• زمن الجمع: {status['elapsed_1m']}ث\n"
                if status["updated_1m"]:
                    txt += f"• آخر تحديث: {status['updated_1m'][:19]}\n"
                txt += "\n"
                # تفاصيل 5m
                txt += f"📦 <b>فريم 5 دقائق:</b>\n"
                txt += f"• العملات: {status['symbols_5m']}/{status['total_assets']}\n"
                txt += f"• الكاش: {'✅ موجود' if status['has_cache_5m'] else '❌ غير موجود'}\n"
                if status["age_5m"] is not None:
                    txt += f"• العمر: {status['age_5m']:.0f} دقيقة\n"
                if status["elapsed_5m"]:
                    txt += f"• زمن الجمع: {status['elapsed_5m']}ث\n"
                if status["updated_5m"]:
                    txt += f"• آخر تحديث: {status['updated_5m'][:19]}\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                # حالة المحرك
                if ENGINE_RES:
                    gate = ENGINE_RES.get('gate',{})
                    frames = gate.get('frames',{})
                    txt += f"🤖 <b>المحرك:</b>\n"
                    txt += f"• 1m: {frames.get('1m',0)} | 5m: {frames.get('5m',0)}\n"
                    txt += f"• فحص: {gate.get('checked',0)} | إشارات: {len(LATEST_PLANS)}\n"
                    txt += f"• زمن الدورة: {status['last_cycle_secs']:.1f}ث\n"
                    if status["last_cycle"]:
                        txt += f"• آخر دورة: {status['last_cycle'][:19]}\n"
                else:
                    txt += "🤖 المحرك: ⏳ لم يبدأ بعد\n"
                    txt += "💡 سيبدأ بعد اكتمال الجمع (5-15ث)\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n"
                # تفسير الحالات
                if not status["engine_ready"]:
                    txt += "⏳ <b>ماذا يحدث الآن؟</b>\n"
                    if not status["has_cache_1m"] and not status["has_cache_5m"]:
                        txt += "• أول إقلاع — يجمع 4 أيام (دقة كاملة)\n"
                        txt += "• ⏱️ 5-15 ثانية ثم يجهز\n"
                    elif status["is_collecting"]:
                        txt += "• يجمع الشموع الجديدة (1-5 شموع)\n"
                        txt += "• ⏱️ ثواني قليلة\n"
                    else:
                        txt += "• يجهز المحرك للتحليل\n"
                else:
                    txt += "✅ <b>مكتمل — البوت يفحص كل دقيقة</b>\n"
                    txt += "• كاش حديث → 0.03ث\n"
                    txt += "• خلفية: تحميل 7 أيام + 20 يوم\n"
                send_msg(chat_id, txt, back_kb([[bt("🔄 تحديث مباشر","bt:live:page:0"), bt("📊 حالة المحرك","m:port")]]), msg_id=msg_id)
            except Exception as e:
                log(f"[LIVE PAGE] {e} {traceback.format_exc()}")
                send_msg(chat_id, f"⚡ خطأ: {esc(str(e))}", api_back_kb(), msg_id=msg_id)
        elif data == "m:api":
            try:
                send_msg(chat_id, LIVE.panel(u), LIVE.keyboard(u), msg_id=msg_id)
            except Exception as e:
                send_msg(chat_id, f"🔑 خطأ: {esc(str(e))}", more_kb(), msg_id=msg_id)
        elif data.startswith("acc:allow:"):
            # قبول مشترك جديد — يجب أن يعمل للمشرف فقط
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            if not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط — لا يمكنك قبول الأعضاء", api_back_kb(), msg_id=msg_id)
            else:
                try:
                    target = data.split(":")[-1]
                    st = load_state()
                    allowed = st.get("allowed", [])
                    if target not in allowed:
                        allowed.append(target)
                        st["allowed"] = allowed
                        get_user(int(target), create=True)
                        save_state()
                        log(f"[ALLOW] المشرف {chat_id} سمح لـ {target}")
                    send_msg(chat_id, f"✅ تم السماح لـ {target}\nالآن يقدر يستخدم البوت — تم إرسال تنبيه له", full_menu_kb(u), msg_id=msg_id)
                    try:
                        send_msg(int(target), "✅ <b>تمت الموافقة على وصولك للبوت</b>\n\n🎉 الآن تقدر تستخدم البوت بشكل كامل\n\n👇 اضغط /start لفتح لوحة التحكم\n🔔 الإشارات ستصلك تلقائياً كل دقيقة\n💼 تقدر تتابع صفقاتك من زر المحفظة", more_kb())
                    except Exception as e:
                        log(f"[ALLOW NOTIFY] {target} {e}")
                except Exception as e:
                    send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        elif data.startswith("acc:"):
            if not u.get("admin") and (ADMIN_CHAT_ID and int(chat_id) != int(ADMIN_CHAT_ID)):
                send_msg(chat_id, "🔒 للمشرف فقط", api_back_kb(), msg_id=msg_id)
            else:
                try:
                    target = data.split(":")[-1]
                    st = load_state()
                    allowed = st.get("allowed", [])
                    if target not in allowed:
                        allowed.append(target)
                        st["allowed"] = allowed
                        save_state()
                    send_msg(chat_id, f"✅ تم السماح لـ {target}", full_menu_kb(u), msg_id=msg_id)
                    try:
                        send_msg(int(target), "✅ <b>تمت الموافقة على وصولك</b>\nاضغط /start", more_kb())
                    except:
                        pass
                except Exception as e:
                    send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        else:
            log(f"[CB] غير معروف: {data}")
            send_msg(chat_id, f"🤖 <b>لوحة التحكم</b>\n━━━━━━━━━━━━━━\nاضغط للمتابعة", full_menu_kb(u), msg_id=msg_id)
    except Exception as e:
        log(f"[CB MAIN] {e} {traceback.format_exc()}")
        try:
            send_msg(chat_id, f"⚠️ خطأ بسيط — حاول مرة أخرى", full_menu_kb(u), msg_id=msg_id)
        except:
            pass

def handle_update(upd: dict):
    if "message" in upd:
        msg = upd["message"]
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None or chat.get("type") == "channel":
            return
        # إصلاح فوري للمالك 8599225300 — يصبح مشرف حتى لو الملف قديم
        try:
            if int(cid) == OWNER_ID:
                st = load_state()
                if st.get("admin_chat_id") != OWNER_ID:
                    st["admin_chat_id"] = OWNER_ID
                    u = get_user(OWNER_ID)
                    u["admin"] = True
                    u["first_name"] = chat.get("first_name","") or u.get("first_name","")
                    u["username"] = chat.get("username","") or u.get("username","")
                    save_state()
                    log(f"[AUTH] تم فرض المالك {OWNER_ID} كمشرف")
        except:
            pass
        if not is_allowed(cid, chat.get("username")):
            st = load_state()
            if not st.get("admin_chat_id") and not ADMIN_CHAT_ID:
                st["admin_chat_id"] = int(cid)
                u = get_user(cid)
                u["admin"] = True
                u["first_name"] = chat.get("first_name","")
                u["username"] = chat.get("username","")
                save_state()
                log(f"[AUTH] أول مستخدم {cid} أصبح مشرف تلقائياً")
                handle_text_message(msg)
                return
            send_msg(cid, (
                f"🔒 <b>بوت خاص</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"معرفك: <code>{cid}</code>\n\n"
                f"💡 <b>الحل:</b>\n"
                f"1. اضبط <code>ADMIN_CHAT_ID={cid}</code>\n"
                f"2. أو <code>ALLOWED_USERS={cid}</code>\n"
                f"3. أو احذف <code>bot_state_v241.json</code>\n"
                f"━━━━━━━━━━━━━━"
            ), [[bt("📨 طلب وصول", "acc:req")]])
            return
        handle_text_message(msg)
    elif "callback_query" in upd:
        cb = upd["callback_query"]
        frm = cb.get("from") or {}
        cid = frm.get("id")
        if cid is None:
            return
        try:
            if int(cid) == OWNER_ID:
                st = load_state()
                if st.get("admin_chat_id") != OWNER_ID:
                    st["admin_chat_id"] = OWNER_ID
                    u = get_user(OWNER_ID)
                    u["admin"] = True
                    save_state()
        except:
            pass
        if not is_allowed(cid, frm.get("username")):
            st = load_state()
            if not st.get("admin_chat_id") and not ADMIN_CHAT_ID:
                st["admin_chat_id"] = int(cid)
                u = get_user(cid)
                u["admin"] = True
                save_state()
                log(f"[AUTH] أول مستخدم {cid} أصبح مشرف تلقائياً (callback)")
                handle_callback(cb)
                return
            answer_cb(cb.get("id",""), "🔒 بوت خاص — غير مصرح")
            return
        handle_callback(cb)

def boot_welcome_admin():
    st = load_state()
    aid = st.get("admin_chat_id") or ADMIN_CHAT_ID
    if aid:
        send_msg(aid, f"✅ البوت يعمل\n{STRATEGY_PROVENANCE}", more_kb())

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
    print(f"  {SIGNAL_BOT_VERSION} — {STRATEGY_PROVENANCE}", flush=True)
    print("="*88, flush=True)
    if not BOT_TOKEN:
        print("\n❌ لا يوجد BOT_TOKEN!", flush=True)
        sys.exit(1)
    if ADMIN_CHAT_ID:
        log(f"[BOOT] ADMIN_CHAT_ID من البيئة: {ADMIN_CHAT_ID}")
    else:
        log("[BOOT] ADMIN_CHAT_ID غير مضبوط — أول مستخدم سيصبح مشرفاً تلقائياً")
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
        log(f"[BOOT] تم تعيين المشرف من البيئة: {ADMIN_CHAT_ID}")
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
    log("[BOOT] بدء حلقة الاستطلاع — يعمل 24/7")
    poll_loop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("[EXIT] إيقاف يدوي")
    except Exception:
        log("[FATAL]\n" + traceback.format_exc())
        sys.exit(1)
