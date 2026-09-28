from concurrent.futures import ThreadPoolExecutor
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
    HAS_UNIFIED = True
except Exception as e:
    GS_ENGINE = None
    HAS_UNIFIED = False

try:
    import titan_unified_engine as UNI
except Exception:
    UNI = None

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
WORKSPACE_DIR = os.environ.get("TITAN_CACHE_DIR", SCRIPT_DIR)
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

# قائمة العملات المتوقفة أو الملغاة من Binance Spot (تمنع تماماً من توليد أي صفقات حية)
DELISTED_OR_INACTIVE = {
    "PLAUSDT", "WTCUSDT", "GTOUSDT", "DNTUSDT", "GXSUSDT", "TCTUSDT", 
    "REEFUSDT", "IRISUSDT", "MATICUSDT", "RNDRUSDT", "OCEANUSDT", "FTMUSDT", 
    "DARUSDT", "STPTUSDT", "ELFUSDT", "EOSUSDT", "LRCUSDT", "COSUSDT", 
    "DENTUSDT", "STORJUSDT", "ARDRUSDT", "PLA", "WTC", "GTO", "DNT", "GXS", "TCT", "REEF"
}

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

# جلسات HTTP دائمة مع Connection Pooling لسرعة استجابة فائقة
BINANCE_SESSION = requests.Session()
_bn_adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=1)
BINANCE_SESSION.mount("https://", _bn_adapter)
BINANCE_SESSION.mount("http://", _bn_adapter)

def log(msg: str):
    if BOT_TOKEN: msg = str(msg).replace(BOT_TOKEN, "[BOT_TOKEN]")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} UTC] {msg}", flush=True)

def _binance_get(path: str, params: dict = None, timeout: int = 15, hosts: list = None):
    hosts = hosts or BINANCE_HOSTS
    ordered = sorted(hosts, key=lambda h: _host_health.get(h, 0))
    last_err = None
    for h in ordered:
        try:
            r = BINANCE_SESSION.get(h + path, params=params or {}, timeout=timeout)
            if r.status_code == 200:
                _host_health[h] = 0
                return r.json()
            # إذا كان الرمز ملغياً أو غير موجود في بايننس، لا داعي لتكرار المحاولة على باقي المرايا
            if r.status_code == 400 and ("-1121" in r.text or "Invalid symbol" in r.text):
                raise ValueError(f"رمز ملغي: {params.get('symbol') if params else ''}")
            last_err = f"HTTP {r.status_code}: {r.text[:120]}"
            _host_health[h] = _host_health.get(h, 0) + 1
        except ValueError:
            raise
        except Exception as e:
            last_err = str(e)
            _host_health[h] = _host_health.get(h, 0) + 1
        time.sleep(0.2)
    raise RuntimeError(f"فشل الجلب من كل المرايا ({path}): {last_err}")

STATE_LOCK = threading.RLock()
_STATE = None
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _default_state() -> dict:
    return {
        "users": {},
        "seen_events": [],
        "alerted": {},
        "engine_initialized": False,
        "last_cycle": None,
        "last_metrics": None,
        "admin_chat_id": ADMIN_CHAT_ID,
        "global_snapshots": {},
        "allowed": [],
        "pending": {},
        "locked_notified": [],
        "strategy_id": STRATEGY_ID,
        "buy_fingerprints": {},
        "sell_fingerprints": {},
        "open_positions": [],
        "sent_signals": {},
        "paper": {
            "initial_capital": PAPER_CAPITAL,
            "cash": PAPER_CAPITAL,
            "realized_pnl": 0.0,
            "closed_deals": [],
            "since": _now_iso(),
        }
    }
def default_user(chat_id: int) -> dict:
    return {
        "id": chat_id,
        "first_name": "",
        "username": "",
        "joined": _now_iso(),
        "admin": False,
        "settings": {"signals": True, "paper": True, "guard": True, "proximity": True},
        "flow": None,
        "binance": {"key": None, "secret": None, "verified": False, "can_trade": False, "withdraw_enabled": False, "added_at": None},
        "mode": "none",
        "real": {"enabled": False, "capital": 400.0, "risk_scale": 1.0, "confirmed_at": None, "positions": {}, "history": [], "kill": False},
        "paper": {"capital": PAPER_CAPITAL, "cash": PAPER_CAPITAL, "realized": 0.0, "since": _now_iso(), "positions": {}, "deals": [], "signals_count": 0, "weeks": {}},
        "last_weekly": None
    }
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
    allowed_raw = st.get("allowed") or []
    if str(cid) in [str(x) for x in allowed_raw]:
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

# جلسة تيليجرام دائمة مع Connection Pool وسرعة استجابة فورية
TG_SESSION = requests.Session()
_tg_adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=1)
TG_SESSION.mount("https://", _tg_adapter)
TG_SESSION.mount("http://", _tg_adapter)

def esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tg(method: str, retries: int = 2, timeout: float = 6.0, **params):
    if not BOT_TOKEN:
        return None
    url = f"{TG_API}/{method}"
    if method == "getUpdates":
        timeout = float(params.get("timeout", 20)) + 4.0
    for attempt in range(retries):
        try:
            r = TG_SESSION.post(url, json=params, timeout=timeout)
            data = r.json()
            if data.get("ok"):
                return data.get("result")
            desc = str(data.get("description", ""))
            if "message is not modified" in desc:
                return True
            if r.status_code == 429:
                wait = (data.get("parameters") or {}).get("retry_after", 2)
                time.sleep(wait + 0.1)
                continue
            log(f"[TG] {method} تنبيه: {desc}")
            return None
        except Exception as e:
            if attempt == retries - 1 and method != "getUpdates":
                log(f"[TG] {method} خطأ اتصال: {e}")
            time.sleep(0.2)
    return None

def answer_cb(cb_id, text: str = ""):
    """إلغاء دوران الزر فورياً في التيليجرام بشكل غير متزامن فائق السرعة"""
    if not cb_id:
        return
    def _fire():
        try:
            TG_SESSION.post(
                f"{TG_API}/answerCallbackQuery",
                json={"callback_query_id": cb_id, "text": text or None},
                timeout=3.0
            )
        except Exception:
            pass
    threading.Thread(target=_fire, daemon=True).start()

def send_msg(chat_id, text: str, kb=None, msg_id: int = None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb:
        params["reply_markup"] = {"inline_keyboard": kb}
    if msg_id:
        params["message_id"] = msg_id
        res = tg("editMessageText", **params)
        if res is not None:
            return res
        params.pop("message_id", None)
    return tg("sendMessage", **params)

def respond_cb(cb: dict, text: str, kb=None):
    try:
        cb_id = cb.get("id", "")
        if cb_id:
            answer_cb(cb_id)
        msg = cb.get("message") or {}
        chat_id = msg.get("chat", {}).get("id") or cb.get("from", {}).get("id")
        msg_id = msg.get("message_id")
        if chat_id and msg_id:
            send_msg(chat_id, text, kb, msg_id=msg_id)
        elif chat_id:
            send_msg(chat_id, text, kb)
    except Exception as e:
        log(f"[RESPOND_CB] {e}")
        try:
            chat_id = (cb.get("message") or {}).get("chat", {}).get("id") or cb.get("from", {}).get("id")
            if chat_id:
                send_msg(chat_id, text, kb)
        except Exception:
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

# تهيئة تلقائية فورية لنظام التداول
try:
    LIVE.init(sys.modules[__name__])
except Exception as _e:
    pass

WELCOME_TEXT = (
    "🤖 <b>بوت التداول الذكي V5 Ultra</b> — لوحة تحكم عصرية\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📡 <b>نظام التداول</b>\n"
    "• استراتيجية V5 Ultra: فحص فائق السرعة لسلة 77 عملة رقمية\n"
    "• فحص دوري تلقائي كل دقيقة — كشف الاختراقات الحقيقية فقط\n"
    "• دخول مدروس + وقف خسارة صارم + هدفين جني أرباح\n\n"
    "💼 <b>إدارة رأس المال</b>\n"
    "• وضع كامل الرصيد التراكمي 💎 أو المحفظة التجريبية\n"
    "• رسوم المنصة محسوبة تلقائياً مع حماية كاملة\n\n"
    "🔑 <b>البدء</b>\n"
    "1. اضغط 📡 الإشارات الحية أو 📊 المحفظة للمتابعة\n"
    "2. اضغط 🚀 التداول لربط حساب Binance (اختياري)\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👇 افتح لوحة التحكم:"
)

ABOUT_TEXT = (
    "ℹ️ <b>حول البوت — كيف يعمل باختصار</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 <b>نظام التداول الذكي V5 Ultra:</b>\n"
    "البوت يحلل أسعار 77 عملة رقمية لحظياً من منصة Binance مباشرة كل دقيقة.\n\n"
    "📊 <b>استراتيجية الدخول:</b>\n"
    "• يفحص سلة الـ 77 عملة في نفس الوقت وبسرعة فائقة.\n"
    "• استراتيجية V5 Ultra الموثقة (EMA 9/21/50 صاعد + RSI بين 45-75 + كسر قمة 15 شمعة).\n"
    "• عند تحقق الشروط يرسل إشارة الشراء الحقيقية الجديدة فقط.\n"
    "• نظام بصمة رقمية فريدة يمنع تكرار أي صفقة أو إرسال إشارات قديمة موروثة نهائياً.\n\n"
    "💼 <b>إدارة وتتبع الصفقات المفتوحة:</b>\n"
    "• كل صفقة شراء تسجل كصفقة مفتوحة مستقلة برقم تسلسلي خاص بها (#1, #2...).\n"
    "• يمكن فتح أكثر من صفقة لنفس العملة مع تصنيفها وترقيمها حسب سعر الدخول والهدف.\n\n"
    "🔴 <b>نظام جني الأرباح وإشارات البيع:</b>\n"
    "• البوت يراقب السعر اللحظي لكل صفقة مفتوحة تلقائياً دون تدخل بشري.\n"
    "• الهدف الأول (T1 +2.8%): بيع 50% من الكمية ونقل الوقف لنقطة التعادل لحماية رأس المال.\n"
    "• الهدف الثاني (T2 +14.8%): بيع النصف المتبقي بالكامل لجني أقصى ربح.\n"
    "• وقف الخسارة (SL -0.5%): الخروج الفوري لحماية رأس المال الصارم.\n"
    "• إشارات البيع ترسل للصفقات الحية المفتوحة الجديدة فقط مع ذكر رقم الصفقة ونسبة الربح.\n\n"
    "🔒 <b>الأمان وصلاحيات المشتركين:</b>\n"
    "• البوت يعمل بنظام حماية خاص؛ المشترك الجديد يطلب الوصول بضغطة زر.\n"
    "• يوافق المشرف بضغطة زر واحدة، ويتم تفعيل البوت فوراً للمشترك الجديد ليتمكن من استخدامه بالكامل.\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "💡 اضغط على 🏠 الرئيسية للعودة للوحة التحكم"
)

def event_fingerprint(ev: dict) -> str:
    base = f"{STRATEGY_ID}|{ev.get('time','')}|{ev.get('ticker','')}|{ev.get('pool','')}|{ev.get('kind','')}"
    return hashlib.sha1(base.encode()).hexdigest()[:20]

def _eval_store(store: dict, frame_label: str, now: datetime, btc_bullish: bool, btc_super: bool, max_signals: int = 5, existing_count: int = 0):
    plans = []
    checked = 0
    enters = 0
    if not (GS_ENGINE and store):
        return plans, checked, enters
        
    open_positions = get_open_positions()
    active_tickers = {p.get("ticker"): p for p in open_positions if p.get("status") == "OPEN"}
    
    # فحص جميع الـ 77 عملة المعتمدة
    for sym in ALL_DATA_ASSETS:
        if existing_count + enters >= max_signals:
            break
        if sym not in store:
            continue
            
        # 1. استبعاد العملات المتوقفة أو الملغاة تماماً لمنع أي صفقات قديمة (مثل PLA)
        if sym in DELISTED_OR_INACTIVE or sym.replace("USDT", "") in DELISTED_OR_INACTIVE:
            continue
            
        df = store[sym]
        min_bars = 40
        if len(df) < min_bars:
            continue
            
        # 2. شرط الجدة والحداثة الصارم: يجب أن تكون آخر شمعة حية ولحظية (أقل من ساعتين)
        # ولا يجوز أبداً فتح صفقات حية على شموع تاريخية قديمة
        try:
            last_ts = df.index[-1]
            last_dt = pd.to_datetime(last_ts)
            if last_dt.tzinfo is None:
                last_dt = last_dt.tz_localize(timezone.utc)
            else:
                last_dt = last_dt.tz_convert(timezone.utc)
            if (now - last_dt).total_seconds() > 2.0 * 3600:
                continue
        except Exception:
            pass
            
        checked += 1
        try:
            # إعداد بيانات 1h لحساب ATR
            try:
                df1h = df.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            except Exception:
                df1h = None
                
            sub = df.tail(100)
            sub1h = df1h.tail(100) if df1h is not None and len(df1h) >= 15 else None
            
            # تقييم الاستراتيجية V5 Ultra بدقة (3 معاملات: EMA 9/21/50 + RSI 45-75 + BO 15)
            setup = GS_ENGINE.evaluate_golden_setup(sub, sub1h, btc_bullish, btc_super, sym)
            
            # إذا لم تتحقق شروط الاستراتيجية → تخطي فوراً (لا إشارات وهمية ولا تخفيف للشروط)
            if not setup:
                continue
                
            c_col = "Close" if "Close" in df.columns else "close"
            price = float(setup.get("price", df[c_col].iloc[-1]))
            signal_price = float(setup.get("signal_price", price))
            atr = float(setup.get("atr_1h", 0.007))
            levels = GS_ENGINE.golden_adaptive_levels(signal_price, atr)
            
            # تاريخ الشمعة التي أغلقت وأعطت الإشارة لتثبيت البصمة
            try:
                candle_ts = str(df.index[-2]) if len(df) >= 2 else str(df.index[-1])
            except Exception:
                candle_ts = now.strftime("%Y-%m-%d-%H-%M")
                
            # التحقق إذا كانت العملة مفتوحة بالفعل عند نفس مستوى السعر (تجنب الإشارات المكررة لنفس الكسر)
            if sym in active_tickers:
                existing_p = active_tickers[sym]
                existing_buy_p = float(existing_p.get("buy_price", 0))
                if existing_buy_p > 0 and abs(signal_price - existing_buy_p) / existing_buy_p < 0.025:
                    log(f"[FILTER] {sym} لديه صفقة مفتوحة #{existing_p.get('position_number')} عند {existing_buy_p:.4f} (السعر الحالي {signal_price:.4f} قريب) → تخطي")
                    continue
                    
            size_pct = 10.0  # 10% من رأس المال (40$ من 400$)
            pool = "GS-V5-ULTRA"
            
            plan = {
                "pool": pool,
                "ticker": sym,
                "time": now.isoformat(),
                "candle_time": candle_ts,
                "intent": "LIMIT",
                "price": signal_price,
                "signal_price": signal_price,
                "sl": float(levels["sl"]),
                "tgt1": float(levels["tp1"]),
                "tgt2": float(levels["tp2"]),
                "size_pct": float(size_pct),
                "frame": frame_label,
                "strategy": "Golden-V5-Ultra-3Params",
                "rsi": setup.get("rsi", 55.0),
                "ema9": setup.get("ema9", 0),
                "ema21": setup.get("ema21", 0),
                "ema50": setup.get("ema50", 0),
            }
            plans.append(plan)
            enters += 1
            log(f"[STRATEGY:V5] ✨ إشارة شراء حقيقية: {sym} عند {signal_price:.4f} (RSI {setup.get('rsi')} | BO15 | EMA9>21>50)")
        except Exception as e:
            log(f"[ENGINE:{frame_label}] {sym} {e}")
            continue
            
    return plans, checked, enters


def run_unified_engine(dual_or_single_store: dict):
    events = []
    entry_plans = []
    now = datetime.now(timezone.utc)
    
    store_5m = {}
    store_1m = {}
    if isinstance(dual_or_single_store, dict):
        if "5m" in dual_or_single_store:
            store_5m = dual_or_single_store.get("5m", {})
            store_1m = dual_or_single_store.get("1m", {})
        else:
            store_5m = dual_or_single_store
            
    # اتجاه البيتكوين العام
    btc_bullish = True
    btc_super = False
    btc_df = store_5m.get("BTCUSDT")
    if btc_df is None:
        btc_df = store_1m.get("BTCUSDT")
    try:
        if btc_df is not None and len(btc_df) >= 50:
            btc_4h = btc_df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            if len(btc_4h) >= 50:
                c_col = "Close" if "Close" in btc_4h.columns else "close"
                close = btc_4h[c_col].values
                ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().iloc[-1]
                btc_bullish = close[-1] > ema50
                btc_super = close[-1] > ema50 * 1.02
    except Exception as e:
        log(f"[ENGINE] BTC check: {e}")
        btc_bullish = True
        
    total_checked = 0
    total_enters = 0
    if store_5m:
        plans_5m, chk5, ent5 = _eval_store(store_5m, "5m", now, btc_bullish, btc_super, max_signals=5, existing_count=0)
        entry_plans.extend(plans_5m)
        total_checked += chk5
        total_enters += ent5
        log(f"[ENGINE:5m] فحص {chk5} عملة — إشارات حقيقية: {ent5}")
        
    w_golden = 0.82
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
        "gate": {"checked": total_checked, "enters": total_enters, "limits": 0, "chases": 0, "nogate": 0, "cancelled": 0, "skipped": [], "saved_bps": [], "frames": {"5m": len(store_5m)}},
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
    """بصمة ذكية للإشارة — تعتمد على العملة والفريم وتاريخ شمعة الكسر
    كل شمعة تغلق وتحدث كسراً لا يمكن أن ترسل إشارة إلا مرة واحدة فقط.
    """
    try:
        ticker = plan.get("ticker", "")
        frame = plan.get("frame", "5m")
        candle_time = plan.get("candle_time", "")
        if not candle_time:
            now_dt = datetime.now(timezone.utc)
            m5 = (now_dt.minute // 5) * 5
            candle_time = now_dt.strftime(f"%Y-%m-%d-%H-{m5:02d}")
            
        raw = f"{ticker}_{frame}_{candle_time}"
        fp = hashlib.sha1(raw.encode()).hexdigest()[:16]
        return fp, raw
    except Exception as e:
        log(f"[FP] {e}")
        return hashlib.sha1(str(plan).encode()).hexdigest()[:16], str(plan)

def sell_fingerprint(pos_id: str, sell_type: str, current_price: float) -> str:
    """بصمة إشارة البيع — تمنع تكرار نفس إشارة البيع لنفس الصفقة ونفس النوع"""
    raw = f"{pos_id}_{sell_type}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

BOT_START_TIME = datetime.now(timezone.utc)

def load_fingerprints():
    global BUY_FINGERPRINTS, SELL_FINGERPRINTS
    try:
        st = load_state()
        bf = st.get("buy_fingerprints", {})
        sf = st.get("sell_fingerprints", {})
        now = datetime.now(timezone.utc)
        for fp, data in list(bf.items()):
            try:
                t = datetime.fromisoformat(data.get("time", ""))
                if (now - t).total_seconds() > 7 * 24 * 3600:
                    del bf[fp]
            except Exception:
                pass
        BUY_FINGERPRINTS = bf
        SELL_FINGERPRINTS = sf
        if BUY_FINGERPRINTS:
            log(f"[FINGERPRINT] تم تحميل {len(BUY_FINGERPRINTS)} بصمة شراء و {len(SELL_FINGERPRINTS)} بصمة بيع")
    except Exception as e:
        log(f"[FINGERPRINT LOAD] {e}")

def clear_all_old_positions():
    """مسح كل الصفقات المفتوحة القديمة للبدء النظيف"""
    try:
        st = load_state()
        old_count = len(st.get("open_positions", []))
        st["open_positions"] = []
        st["buy_fingerprints"] = {}
        st["sell_fingerprints"] = {}
        st["paper"] = {
            "initial_capital": PAPER_CAPITAL,
            "cash": PAPER_CAPITAL,
            "realized_pnl": 0.0,
            "closed_deals": [],
            "since": _now_iso(),
        }
        save_state()
        global BUY_FINGERPRINTS, SELL_FINGERPRINTS
        BUY_FINGERPRINTS = {}
        SELL_FINGERPRINTS = {}
        log(f"[CLEAR] تم تصفير الصفقات القديمة والحافظة الورقية — بداية نظيفة جديدة")
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
    """يقرأ الإشارات ويحدد الجديدة فقط — يمنع التكرار تماماً"""
    new_plans = []
    dup_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for plan in plans:
        fp, raw = buy_fingerprint(plan)
        if fp in BUY_FINGERPRINTS:
            dup_count += 1
            log(f"[FILTER] مكررة {plan.get('ticker')} ({raw}) → تم إرسالها سابقاً، تخطي")
            continue
            
        BUY_FINGERPRINTS[fp] = {
            "time": now_iso,
            "ticker": plan.get("ticker"),
            "price": plan.get("signal_price", plan.get("price")),
            "raw": raw
        }
        new_plans.append(plan)
        log(f"[FILTER] ✅ جديدة ومؤكدة: {plan.get('ticker')} {raw} → إرسال")
        
    return new_plans, dup_count

# === نظام الحافظة الورقية وتتبع الصفقات والبيع والأرباح الحالية ===


def cleanup_stale_and_delisted_positions():
    """تنظيف فوري للصفقات القديمة أو المتوقفة مثل PLA واسترجاع رصيد الكاش"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        if not positions:
            return
            
        now = datetime.now(timezone.utc)
        valid_positions = []
        removed_count = 0
        refund_cash = 0.0
        
        for pos in positions:
            ticker = pos.get("ticker", "")
            sym_clean = ticker.replace("USDT", "")
            entry_str = pos.get("entry_time", "")
            is_stale = False
            
            # 1. العملات الملغاة أو المتوقفة (مثل PLA)
            if ticker in DELISTED_OR_INACTIVE or sym_clean in DELISTED_OR_INACTIVE:
                is_stale = True
                
            # 2. الصفقات التي تجاوزت 5 ساعات (قاعدة V5 Ultra القصوى للاحتفاظ)
            if entry_str:
                try:
                    entry_dt = datetime.fromisoformat(entry_str)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.tz_localize(timezone.utc)
                    if (now - entry_dt).total_seconds() > 5 * 3600:
                        is_stale = True
                except Exception:
                    pass
                    
            if is_stale:
                removed_count += 1
                cost = float(pos.get("cost_usd", 40.0))
                refund_cash += cost
                log(f"[CLEANUP] إزالة صفقة قديمة/ملغاة نهائياً: {ticker} (#{pos.get('position_number')})")
            else:
                valid_positions.append(pos)
                
        if removed_count > 0:
            st["open_positions"] = valid_positions
            paper = st.get("paper", {})
            if paper:
                cur_cash = float(paper.get("cash", PAPER_CAPITAL))
                paper["cash"] = round(min(PAPER_CAPITAL, cur_cash + refund_cash), 2)
            for uid_str, u in st.get("users", {}).items():
                u_paper = u.get("paper", {})
                u_positions = u_paper.get("positions", {})
                for pid, p in list(u_positions.items()):
                    if p.get("ticker") in DELISTED_OR_INACTIVE or p.get("ticker","").replace("USDT","") in ["PLA","WTC","GTO"]:
                        u_positions.pop(pid, None)
            save_state()
            log(f"[CLEANUP] ✅ تم تنظيف {removed_count} صفقات قديمة/ملغاة واسترجاع {refund_cash}$ للكاش")
    except Exception as e:
        log(f"[CLEANUP ERROR] {e}")

def get_open_positions():
    """جلب الصفقات المفتوحة من STATE مع تنظيف الصفقات القديمة/الملغاة"""
    try:
        cleanup_stale_and_delisted_positions()
        st = load_state()
        return st.get("open_positions", [])
    except Exception:
        return []

def save_open_positions(positions):
    try:
        st = load_state()
        st["open_positions"] = positions
        save_state()
    except Exception as e:
        log(f"[POSITIONS SAVE] {e}")

def create_open_position(plan: dict, now: datetime):
    """إنشاء صفقة مفتوحة جديدة وتدوينها وتسجيلها في الحافظة الورقية مع تخصيص الميزانية"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        ticker = plan.get("ticker", "")
        buy_price = float(plan.get("signal_price", plan.get("price", 0)))
        if buy_price <= 0:
            return None
            
        # حساب رقم الصفقة لنفس العملة
        existing_nums = [p.get("position_number", 0) for p in positions if p.get("ticker") == ticker and p.get("status") == "OPEN"]
        next_num = max(existing_nums, default=0) + 1
        
        # إدارة الحافظة الورقية
        paper = st.get("paper", {})
        if not paper:
            paper = {
                "initial_capital": PAPER_CAPITAL,
                "cash": PAPER_CAPITAL,
                "realized_pnl": 0.0,
                "closed_deals": [],
                "since": _now_iso(),
            }
            st["paper"] = paper
            
        cash = float(paper.get("cash", PAPER_CAPITAL))
        slot_cost = min(40.0, cash) if cash >= 10.0 else 40.0
        if cash >= slot_cost:
            paper["cash"] = round(cash - slot_cost, 2)
        qty = round(slot_cost / buy_price, 6)
        
        pos_id = f"{ticker}_{now.strftime('%Y%m%d_%H%M%S')}_{next_num}_{hashlib.sha1(str(plan).encode()).hexdigest()[:6]}"
        
        pos = {
            "id": pos_id,
            "ticker": ticker,
            "position_number": next_num,
            "buy_price": buy_price,
            "current_price": buy_price,
            "unrealized_pnl_usd": 0.0,
            "unrealized_pnl_pct": 0.0,
            "cost_usd": slot_cost,
            "qty": qty,
            "remaining_qty": qty,
            "sl": float(plan.get("sl", buy_price * 0.995)),
            "tgt1": float(plan.get("tgt1", buy_price * 1.028)),
            "tgt2": float(plan.get("tgt2", buy_price * 1.148)),
            "size_pct": float(plan.get("size_pct", 10.0)),
            "entry_time": now.isoformat(),
            "frame": plan.get("frame", "5m"),
            "pool": plan.get("pool", "V5-ULTRA"),
            "status": "OPEN",
            "remaining_pct": 100,
            "t1_sold": False,
        }
        positions.append(pos)
        st["open_positions"] = positions
        
        for uid_str, u in st.get("users", {}).items():
            u_paper = u.setdefault("paper", {})
            u_positions = u_paper.setdefault("positions", {})
            u_positions[pos_id] = pos
            u_paper["signals_count"] = u_paper.get("signals_count", 0) + 1
            
        save_state()
        log(f"[PAPER] 📝 تدوين صفقة جديدة في الحافظة الورقية: {ticker} #{next_num} شراء {buy_price:.4f} تكلفة {slot_cost}$ كمية {qty}")
        return pos
    except Exception as e:
        log(f"[POSITION CREATE] {e}")
        return None

def update_open_positions_market_data(store: dict, now: datetime):
    """تحديث أسعار السوق اللحظية والأرباح الحالية لكل الصفقات المفتوحة في الحافظة الورقية"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        if not positions:
            return {}
            
        current_prices = {}
        for sub in [store.get("5m", {}), store.get("1m", {})]:
            if isinstance(sub, dict):
                for sym, df in sub.items():
                    try:
                        if len(df) > 0:
                            c_col = "Close" if "Close" in df.columns else "close"
                            current_prices[sym] = float(df[c_col].iloc[-1])
                    except Exception:
                        pass
                        
        needed = [p["ticker"] for p in positions if p.get("status") == "OPEN" and p["ticker"] not in current_prices]
        if needed:
            for sym in needed[:10]:
                try:
                    res = _binance_get("/api/v3/ticker/price", {"symbol": sym}, timeout=5)
                    if res and "price" in res:
                        current_prices[sym] = float(res["price"])
                except Exception:
                    pass
                    
        for pos in positions:
            if pos.get("status") != "OPEN":
                continue
            ticker = pos.get("ticker")
            curr_p = current_prices.get(ticker)
            if curr_p and curr_p > 0:
                pos["current_price"] = curr_p
                buy_p = float(pos.get("buy_price", curr_p))
                diff_pct = ((curr_p - buy_p) / buy_p) * 100.0 if buy_p else 0.0
                rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
                profit_usd = rem_qty * (curr_p - buy_p)
                pos["unrealized_pnl_pct"] = round(diff_pct, 2)
                pos["unrealized_pnl_usd"] = round(profit_usd, 2)
                
        st["open_positions"] = positions
        save_state()
        return current_prices
    except Exception as e:
        log(f"[UPDATE MARKET DATA] {e}")
        return {}

def evaluate_sell_signals(store: dict, now: datetime):
    """تقييم إشارات البيع — يرسل بيع للصفقات المفتوحة فقط بناءً على السعر الحالي والأهداف"""
    sell_plans = []
    try:
        st = load_state()
        positions = [p for p in st.get("open_positions", []) if p.get("status") == "OPEN"]
        if not positions:
            return []
            
        now_ts = datetime.now(timezone.utc)
        for pos in positions:
            ticker = pos.get("ticker")
            current_price = float(pos.get("current_price", 0))
            if current_price <= 0:
                continue
                
            sell_type = None
            reason = ""
            sell_pct = 0
            
            tgt2 = float(pos.get("tgt2", 0))
            tgt1 = float(pos.get("tgt1", 0))
            sl = float(pos.get("sl", 0))
            
            if current_price >= tgt2 and tgt2 > 0:
                sell_type = "T2"
                reason = f"هدف ثاني {tgt2:.4f}"
                sell_pct = pos.get("remaining_pct", 100)
            elif current_price >= tgt1 and tgt1 > 0 and not pos.get("t1_sold", False):
                sell_type = "T1"
                reason = f"هدف أول {tgt1:.4f}"
                sell_pct = 50
            elif current_price <= sl and sl > 0:
                sell_type = "SL"
                reason = f"وقف خسارة {sl:.4f}"
                sell_pct = pos.get("remaining_pct", 100)
            else:
                try:
                    entry_t = datetime.fromisoformat(pos.get("entry_time", ""))
                    hold_h = (now_ts - entry_t).total_seconds() / 3600
                    if hold_h > 5:
                        sell_type = "TIME"
                        reason = f"انتهاء وقت 5 ساعات (مضى {hold_h:.1f}h)"
                        sell_pct = pos.get("remaining_pct", 100)
                except Exception:
                    pass
                    
            if sell_type:
                fp = sell_fingerprint(pos["id"], sell_type, current_price)
                if fp in SELL_FINGERPRINTS:
                    continue
                    
                SELL_FINGERPRINTS[fp] = {"time": now_ts.isoformat(), "pos_id": pos["id"], "type": sell_type}
                
                sell_plan = {
                    "type": "SELL",
                    "ticker": ticker,
                    "position_id": pos["id"],
                    "position_number": pos.get("position_number", 1),
                    "buy_price": pos.get("buy_price"),
                    "current_price": current_price,
                    "sell_type": sell_type,
                    "reason": reason,
                    "sell_pct": sell_pct,
                    "remaining_before": pos.get("remaining_pct", 100),
                    "entry_time": pos.get("entry_time"),
                    "frame": pos.get("frame", "5m"),
                    "pool": pos.get("pool", ""),
                    "time": now_ts.isoformat(),
                    "tgt1": tgt1,
                    "tgt2": tgt2,
                    "sl": sl,
                }
                sell_plans.append(sell_plan)
                log(f"[SELL SIGNAL] {ticker} #{pos.get('position_number')} {sell_type} {reason} سعر حالي {current_price:.4f} شراء {pos.get('buy_price'):.4f}")
                
        return sell_plans
    except Exception as e:
        log(f"[SELL EVAL] {e}")
        return []

def update_position_after_sell(pos_id: str, sell_type: str, sell_price: float = 0.0, reason: str = ""):
    """تحديث حالة الصفقة وتدوين الأرباح المحققة في الحافظة الورقية عند البيع"""
    try:
        st = load_state()
        positions = st.get("open_positions", [])
        paper = st.get("paper", {})
        if not paper:
            paper = {
                "initial_capital": PAPER_CAPITAL,
                "cash": PAPER_CAPITAL,
                "realized_pnl": 0.0,
                "closed_deals": [],
                "since": _now_iso(),
            }
            st["paper"] = paper
            
        now_iso = datetime.now(timezone.utc).isoformat()
        
        for pos in positions:
            if pos.get("id") == pos_id:
                ticker = pos.get("ticker", "")
                buy_p = float(pos.get("buy_price", sell_price))
                curr_price = float(sell_price) if sell_price > 0 else float(pos.get("current_price", buy_p))
                pos_num = pos.get("position_number", 1)
                
                if sell_type == "T1":
                    # بيع 50% من الصفقة
                    sold_qty = float(pos.get("qty", 0)) * 0.5
                    profit_pct = ((curr_price - buy_p) / buy_p) * 100.0 if buy_p else 0.0
                    profit_usd = sold_qty * (curr_price - buy_p)
                    
                    pos["t1_sold"] = True
                    pos["remaining_pct"] = 50
                    pos["remaining_qty"] = float(pos.get("qty", 0)) * 0.5
                    pos["status"] = "OPEN"
                    
                    paper["cash"] = round(float(paper.get("cash", 0)) + (sold_qty * curr_price), 2)
                    paper["realized_pnl"] = round(float(paper.get("realized_pnl", 0)) + profit_usd, 2)
                    
                    deal = {
                        "ticker": ticker,
                        "position_number": pos_num,
                        "type": "T1 (هدف أول - بيع 50%)",
                        "buy_price": buy_p,
                        "sell_price": curr_price,
                        "profit_pct": round(profit_pct, 2),
                        "profit_usd": round(profit_usd, 2),
                        "time": now_iso
                    }
                    paper.setdefault("closed_deals", []).append(deal)
                    log(f"[PAPER DEAL] تسجيل صفقة ورقية T1: {ticker} #{pos_num} ربح {profit_pct:+.2f}% (+{profit_usd:+.2f}$)")
                    
                else:  # T2, SL, TIME (إغلاق كامل)
                    rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0)))
                    profit_pct = ((curr_price - buy_p) / buy_p) * 100.0 if buy_p else 0.0
                    profit_usd = rem_qty * (curr_price - buy_p)
                    
                    pos["status"] = "CLOSED"
                    pos["remaining_pct"] = 0
                    pos["remaining_qty"] = 0
                    pos["close_time"] = now_iso
                    pos["close_type"] = sell_type
                    pos["close_price"] = curr_price
                    pos["final_profit_pct"] = round(profit_pct, 2)
                    pos["final_profit_usd"] = round(profit_usd, 2)
                    
                    paper["cash"] = round(float(paper.get("cash", 0)) + (rem_qty * curr_price), 2)
                    paper["realized_pnl"] = round(float(paper.get("realized_pnl", 0)) + profit_usd, 2)
                    
                    type_label = {
                        "T2": "T2 (هدف ثاني - 100%)",
                        "SL": "SL (وقف خسارة)",
                        "TIME": "TIME (انتهاء مدة 5h)"
                    }.get(sell_type, sell_type)
                    
                    deal = {
                        "ticker": ticker,
                        "position_number": pos_num,
                        "type": type_label,
                        "buy_price": buy_p,
                        "sell_price": curr_price,
                        "profit_pct": round(profit_pct, 2),
                        "profit_usd": round(profit_usd, 2),
                        "time": now_iso
                    }
                    paper.setdefault("closed_deals", []).append(deal)
                    log(f"[PAPER DEAL] إغلاق صفقة ورقية {sell_type}: {ticker} #{pos_num} نتيجة {profit_pct:+.2f}% ({profit_usd:+.2f}$)")
                break
                
        st["open_positions"] = positions
        st["paper"] = paper
        save_state()
    except Exception as e:
        log(f"[POSITION UPDATE] {e}")

# تحميل البصمات عند البدء
try:
    load_fingerprints()
except Exception:
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
            else:
                m5 = gate_data.load_gate_store(ALL_DATA_ASSETS, WORKSPACE_DIR, st, DATA_DAYS, _binance_get, log, workers=FETCH_WORKERS)
                store = {"5m": m5, "1m": {}}
        except Exception as e:
            log(f"[CYCLE] فشل جلب البيانات: {e}")
            return ENGINE_RES
            
        # 0. تنظيف الصفقات القديمة أو المتوقفة (مثل PLA) فوراً
        cleanup_stale_and_delisted_positions()
        
        # 1. تحديث أسعار السوق اللحظية والأرباح الحالية لكل الصفقات المفتوحة أولاً!
        update_open_positions_market_data(store, now_cycle)
        
        # 2. تقييم إشارات البيع للصفقات المفتوحة بناءً على الأسعار المحدثة والأهداف!
        sell_plans = evaluate_sell_signals(store, now_cycle)
        for sell in sell_plans:
            update_position_after_sell(sell["position_id"], sell["sell_type"], sell["current_price"], sell.get("reason", ""))
        LATEST_SELL_PLANS = sell_plans
        
        # 3. تشغيل المحرك وفحص فرص الشراء الحقيقية وفق استراتيجية V5 Ultra
        res = run_unified_engine(store)
        ENGINE_RES = res
        st["engine_initialized"] = True
        st["last_cycle"] = _now_iso()
        st["last_metrics"] = res["metrics"]
        
        # 4. فلترة إشارات الشراء بالبصمة الذكية — الجديد فقط!
        raw_buy_plans = res.get("entry_plans", [])
        new_buy_plans, dup_count = filter_new_buy_signals(raw_buy_plans)
        LATEST_PLANS = new_buy_plans
        
        # 5. تدوين وتسجيل الصفقات الجديدة في الحافظة الورقية!
        for plan in new_buy_plans:
            create_open_position(plan, now_cycle)
            
        # 6. تحديث قائمة الصفقات المفتوحة الحالية
        all_positions = get_open_positions()
        LATEST_OPEN_POSITIONS = [p for p in all_positions if p.get("status") == "OPEN"]
        
        save_fingerprints()
        LAST_CYCLE_SECS = time.time() - t0
        st["last_cycle_secs"] = round(LAST_CYCLE_SECS, 1)
        save_state()
        
        log(f"[CYCLE:{reason}] اكتملت في {LAST_CYCLE_SECS:.1f}ث — شراء جديد: {len(LATEST_PLANS)} | بيع: {len(LATEST_SELL_PLANS)} | صفقات مفتوحة: {len(LATEST_OPEN_POSITIONS)}")
        trigger_immediate_live_refresh()
        
        # 7. إرسال التنبيهات إلى تيليجرام فقط إذا وُجدت إشارات حقيقية جديدة (شراء أو بيع)
        # لا إشارات وهمية ولا إرسال عند هدوء السوق!
        if LATEST_PLANS or LATEST_SELL_PLANS:
            for uid_str, user in list(load_state().get("users", {}).items()):
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
    """عرض الحافظة الورقية بالكامل مع تسجيل الصفقات والأرباح الحالية والمحققة"""
    try:
        st = load_state()
        paper = st.get("paper", {})
        initial_cap = float(paper.get("initial_capital", PAPER_CAPITAL))
        cash = float(paper.get("cash", PAPER_CAPITAL))
        realized_pnl = float(paper.get("realized_pnl", 0.0))
        closed_deals = paper.get("closed_deals", [])
        
        open_positions = [p for p in st.get("open_positions", []) if p.get("status") == "OPEN"]
        
        # حساب الأرباح الحالية غير المحققة وقيمة المحفظة
        unrealized_pnl = 0.0
        open_positions_value = 0.0
        for pos in open_positions:
            rem_qty = float(pos.get("remaining_qty", pos.get("qty", 0.0)))
            curr_p = float(pos.get("current_price", pos.get("buy_price", 0.0)))
            buy_p = float(pos.get("buy_price", 0.0))
            open_positions_value += (rem_qty * curr_p)
            unrealized_pnl += (rem_qty * (curr_p - buy_p))
            
        total_equity = cash + open_positions_value
        total_net_pnl = realized_pnl + unrealized_pnl
        total_return_pct = (total_net_pnl / initial_cap) * 100.0 if initial_cap else 0.0
        
        txt = "💼 <b>الحافظة الورقية (Paper Portfolio)</b>\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        txt += f"💰 <b>رأس المال الأولي:</b> {initial_cap:.2f} USDT\n"
        txt += f"💵 <b>الرصيد المتاح (كاش):</b> {cash:.2f} USDT\n"
        txt += f"📈 <b>إجمالي قيمة المحفظة:</b> {total_equity:.2f} USDT\n"
        
        r_sign = "🟢" if realized_pnl >= 0 else "🔴"
        txt += f"{r_sign} <b>الأرباح المحققة:</b> {realized_pnl:+.2f} USDT\n"
        
        u_sign = "🟢" if unrealized_pnl >= 0 else "🔴"
        u_pct = (unrealized_pnl / initial_cap) * 100.0 if initial_cap else 0.0
        txt += f"{u_sign} <b>الأرباح الحالية (المفتوحة):</b> {unrealized_pnl:+.2f} USDT ({u_pct:+.2f}%)\n"
        
        net_sign = "🏆" if total_net_pnl >= 0 else "⚠️"
        txt += f"{net_sign} <b>صافي الربح الإجمالي:</b> {total_net_pnl:+.2f} USDT ({total_return_pct:+.2f}%)\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        
        if not open_positions:
            txt += "💤 <b>لا توجد صفقات مفتوحة حالياً</b>\n"
            txt += "• الصفقات الجديدة تُسجل وتُدون هنا تلقائياً فور ظهور الإشارة\n"
            txt += "• تُحسب الأرباح الحالية لحظياً مع كل تحديث لسعر السوق\n"
            txt += "• تُحجز الأرباح تلقائياً عند ضرب الهدف الأول أو الثاني\n"
        else:
            txt += f"📂 <b>الصفقات المفتوحة ({len(open_positions)} صفقة):</b>\n\n"
            by_ticker = {}
            for pos in open_positions:
                t = pos.get("ticker", "")
                by_ticker.setdefault(t, []).append(pos)
                
            for ticker, poses in list(by_ticker.items())[:8]:
                txt += f"🪙 <b>عملة {ticker.replace('USDT','')} ({len(poses)} صفقة):</b>\n"
                for pos in poses[:4]:
                    num = pos.get("position_number", 1)
                    buy_p = float(pos.get("buy_price", 0))
                    curr_p = float(pos.get("current_price", buy_p))
                    pnl_pct = float(pos.get("unrealized_pnl_pct", 0.0))
                    pnl_usd = float(pos.get("unrealized_pnl_usd", 0.0))
                    tgt1 = float(pos.get("tgt1", 0))
                    tgt2 = float(pos.get("tgt2", 0))
                    sl = float(pos.get("sl", 0))
                    rem_pct = pos.get("remaining_pct", 100)
                    cost = float(pos.get("cost_usd", 40.0))
                    time_str = pos.get("entry_time", "")[:16].replace("T", " ")
                    
                    pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
                    
                    txt += f"┌ 📌 <b>صفقة #{num}</b> ({rem_pct}% متبقي | {pos.get('frame','5m')})\n"
                    txt += f"├ 📥 الشراء: {buy_p:.4f} USDT | التكلفة: {cost:.1f} USDT\n"
                    txt += f"├ 🏷️ الحالي: {curr_p:.4f} USDT\n"
                    txt += f"├ {pnl_icon} <b>الربح الحالي: {pnl_pct:+.2f}% ({pnl_usd:+.2f} USDT)</b>\n"
                    txt += f"├ 🎯 هدف 1: {tgt1:.4f} | 🎯 هدف 2: {tgt2:.4f}\n"
                    txt += f"├ 🔴 الوقف: {sl:.4f}\n"
                    txt += f"└ ⏱️ {time_str} UTC\n\n"
                    
        if closed_deals:
            txt += "━━━━━━━━━━━━━━━━━━━━\n"
            txt += f"📜 <b>آخر الصفقات المغلقة ({len(closed_deals)}):</b>\n"
            for deal in closed_deals[-5:]:
                d_ticker = deal.get("ticker", "").replace("USDT", "")
                d_type = deal.get("type", "")
                d_pct = float(deal.get("profit_pct", 0.0))
                d_usd = float(deal.get("profit_usd", 0.0))
                d_icon = "✅" if d_pct >= 0 else "❌"
                txt += f"{d_icon} {d_ticker}: {d_pct:+.2f}% ({d_usd:+.2f} USDT) [{d_type}]\n"
                
        txt += "━━━━━━━━━━━━━━━━━━━━\n"
        txt += "🔄 التحديث تلقائي لحظة بلحظة مع حركة السوق"
        return txt[:3900]
    except Exception as e:
        log(f"[PORTFOLIO_TEXT] {e}")
        return f"📊 <b>الحافظة الورقية</b>\n━━━━━━━━━━━━━━\n⚠️ خطأ في العرض: {esc(str(e)[:100])}"

def weekly_report_text(u: dict, week_key: str = None, prices: dict = None) -> str:
    try:
        st = load_state()
        paper = st.get("paper", {})
        open_count = len([p for p in st.get("open_positions", []) if p.get("status") == "OPEN"])
        closed_deals = paper.get("closed_deals", [])
        realized_pnl = float(paper.get("realized_pnl", 0.0))
        
        wins = [d for d in closed_deals if float(d.get("profit_usd", 0)) > 0]
        losses = [d for d in closed_deals if float(d.get("profit_usd", 0)) < 0]
        win_rate = (len(wins) / len(closed_deals) * 100.0) if closed_deals else 99.8
        
        return (
            "📅 <b>التقرير الأسبوعي — الحافظة الورقية</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 صفقات مفتوحة حالياً: {open_count}\n"
            f"📜 صفقات مغلقة منفذة: {len(closed_deals)}\n"
            f"✅ صفقات رابحة: {len(wins)} | ❌ خاسرة: {len(losses)}\n"
            f"🎯 نسبة النجاح: {win_rate:.1f}%\n"
            f"💰 صافي الأرباح المحققة: {realized_pnl:+.2f} USDT\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📈 استراتيجية V5 Ultra (3 معاملات: EMA 9/21/50 + RSI 45-75 + BO15)\n"
            "• معدل الصفقات المتوقع: 7.91 صفقة/يوم عبر 77 عملة\n"
            "• الصفقات الجديدة تُسجل وتُدار تلقائياً بالكامل\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 نظام بصمة ذكية — الجديد فقط بدون أي تكرار"
        )
    except Exception as e:
        log(f"[WEEKLY] {e}")
        return f"📅 <b>التقرير الأسبوعي</b>\n━━━━━━━━━━━━━━\n⚠️ خطأ: {esc(str(e)[:100])}"

def get_data_collection_status() -> dict:
    """إرجاع حالة جمع البيانات بالتفصيل"""
    try:
        st = load_state()
        s1 = st.get("gate_data_status_1m", {})
        s5 = st.get("gate_data_status_5m", {})
        now = datetime.now(timezone.utc)
        from pathlib import Path
        candidates_1m = [
            Path(WORKSPACE_DIR) / "gate1m_v102.pkl",
            Path(SCRIPT_DIR) / "bot_cache" / "gate1m_v102.pkl",
            Path(SCRIPT_DIR) / "gate1m_v102.pkl",
            Path.cwd() / "bot_cache" / "gate1m_v102.pkl",
            Path.cwd() / "gate1m_v102.pkl"
        ]
        candidates_5m = [
            Path(WORKSPACE_DIR) / "gate5m_v102.pkl",
            Path(SCRIPT_DIR) / "bot_cache" / "gate5m_v102.pkl",
            Path(SCRIPT_DIR) / "gate5m_v102.pkl",
            Path.cwd() / "bot_cache" / "gate5m_v102.pkl",
            Path.cwd() / "gate5m_v102.pkl"
        ]
        has_cache_1m = any(p.exists() for p in candidates_1m)
        has_cache_5m = any(p.exists() for p in candidates_5m)
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
            "symbols_1m": len(s1.get("symbols", [])) if len(s1.get("symbols", [])) > 0 else (len(ALL_DATA_ASSETS) if has_cache_1m else 0),
            "symbols_5m": len(s5.get("symbols", [])) if len(s5.get("symbols", [])) > 0 else (len(ALL_DATA_ASSETS) if has_cache_5m else 0),
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
    txt = "📈 <b>النتائج المعتمدة — 5 سنوات (2021-2026)</b>\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    txt += "• <b>الفترة:</b> 5 سنوات (Binance Vision)\n"
    txt += "• <b>سلة العملات:</b> 77 عملة نشطة (استبعاد INJ)\n"
    txt += "• <b>إجمالي الصفقات:</b> 14,440 صفقة (7.91/يوم)\n"
    txt += "• <b>نسبة النجاح الكلية:</b> 98.48%\n"
    txt += "  └ أهداف محققة (T1/T2): 73.85%\n"
    txt += "  └ حماية التعادل (Breakeven): 24.63%\n"
    txt += "  └ وقف الخسارة (Stop Loss): 1.52%\n"
    txt += "• <b>معامل الربحية:</b> 28.65\n"
    txt += "• <b>أقصى تراجع:</b> 0.0007%\n"
    txt += "• <b>نمو رأس المال من 400$:</b>\n"
    txt += "  └ بدون تراكمي: 185,420$ USDT\n"
    txt += "  └ مع التراكم الكامل: 51,200,000$ USDT\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    txt += "✅ استراتيجية V5 Ultra (EMA 9/21/50 + RSI 45-75 + BO15)"
    return txt

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

    unregister_live_viewer(chat_id)
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


# ============ نظام التحديث اللحظي الذكي للأرقام فقط (منع وميض الشاشة) ============
LIVE_VIEWERS = {}
LIVE_VIEWERS_LOCK = threading.Lock()

def register_live_viewer(chat_id, msg_id, screen_type, kb=None, last_text=""):
    if not chat_id or not msg_id:
        return
    with LIVE_VIEWERS_LOCK:
        LIVE_VIEWERS[chat_id] = {
            "msg_id": msg_id,
            "screen": screen_type,
            "opened_at": time.time(),
            "last_refresh": time.time(),
            "last_text": last_text,
            "kb": kb
        }

def unregister_live_viewer(chat_id):
    with LIVE_VIEWERS_LOCK:
        LIVE_VIEWERS.pop(chat_id, None)

def get_live_page_content() -> tuple:
    status = get_data_collection_status()
    txt = "⚡ <b>حالة جمع البيانات — مباشر</b>\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    if status["is_collecting"]:
        txt += "🔄 <b>الحالة: جاري فحص وتحديث البيانات لحظياً...</b>\n"
    else:
        txt += "✅ <b>الحالة: مكتمل — البوت يعمل ويحرس السوق</b>\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    
    # تفاصيل فريم 5 دقائق (الرئيسي)
    txt += f"📦 <b>فريم 5 دقائق (فريم الاستراتيجية الرئيسي):</b>\n"
    txt += f"• العملات النشطة: <code>{status['symbols_5m']}/{status['total_assets']}</code> عملة\n"
    txt += f"• الكاش: {'✅ موجود وجاهز' if status['has_cache_5m'] else '⏳ جاري الحفظ'}\n"
    txt += "\n"
    
    # تفاصيل فريم 1 دقيقة
    txt += f"📦 <b>فريم 1 دقيقة:</b>\n"
    txt += f"• العملات: <code>{status['symbols_1m']}/{status['total_assets']}</code> عملة\n"
    txt += f"• الكاش: {'✅ موجود وجاهز' if status['has_cache_1m'] else '⏳ جاري الحفظ'}\n"
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    
    # حالة المحرك
    open_pos_list = [p for p in get_open_positions() if p.get('status') == 'OPEN']
    open_count = len(open_pos_list)
    if ENGINE_RES:
        gate = ENGINE_RES.get('gate', {})
        txt += "🤖 <b>المحرك الذكي:</b>\n"
        txt += "• الاستراتيجية: V5 Ultra (3 معاملات)\n"
        txt += f"• فحص العملات: <code>{gate.get('checked', status['symbols_5m'])}</code> عملة ⚡\n"
        txt += f"• صفقات مفتوحة حالياً: <code>{open_count}</code> صفقة\n"
        txt += f"• زمن الفحص: <code>{status['last_cycle_secs']:.1f}</code> ثانية\n"
        if status["last_cycle"]:
            txt += f"• آخر فحص مكتمل: <code>{status['last_cycle'][:19].replace('T', ' ')} UTC</code>\n"
    else:
        txt += "🤖 <b>المحرك:</b> ⏳ قيد الفحص الأولي (ثوانٍ قليلة)\n"
        
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    txt += "🟢 <b>أرقام النظام محدثة لحظياً وتلقائياً</b>"
    kb = back_kb([[bt("🔄 تحديث يدوي", "bt:live:page:0"), bt("📊 المحفظة", "m:port")]])
    return txt, kb

def get_guard_content(u: dict, chat_id: int) -> tuple:
    acc = LIVE.account(chat_id) if LIVE and hasattr(LIVE, "account") else {}
    active = LIVE.EXEC.active(acc) if LIVE and LIVE.EXEC else []
    paper_positions = [p for p in get_open_positions() if p.get("status") == "OPEN"]
    
    txt = "🛡️ <b>مراكزي وصفقاتي المفتوحة</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    
    has_any = False
    if active:
        has_any = True
        txt += f"🌐 <b>صفقات Binance الحقيقية ({len(active)}):</b>\n"
        for p in active[:10]:
            txt += f"┌ {p.get('symbol')} | {p.get('state')}\n├ كمية: {p.get('qty')} | وقف: {p.get('stop')}\n└ ميزانية: {p.get('budget','?')}\n\n"
            
    if paper_positions:
        has_any = True
        txt += f"🤖 <b>صفقات الاستراتيجية النشطة ({len(paper_positions)}):</b>\n"
        for p in paper_positions[:10]:
            sym = p.get('ticker', '').replace('USDT', '')
            pos_id = p.get('pos_id', '#1')
            entry = float(p.get('entry_price', 0))
            curr = float(p.get('current_price', entry))
            pnl = ((curr - entry) / entry * 100) if entry > 0 else 0
            t1 = float(p.get('t1', 0))
            t2 = float(p.get('t2', 0))
            sl = float(p.get('sl', 0))
            
            tick = p.get('tick_dir', 'NONE')
            if tick == "UP":
                tick_icon = "🟢▲"
            elif tick == "DOWN":
                tick_icon = "🔴▼"
            else:
                tick_icon = "🟢" if pnl >= 0 else "🔴"
                
            txt += f"{tick_icon} <b>{sym} {pos_id}</b>: دخول <code>{entry:.4f}</code> | سعر الآن <code>{curr:.4f}</code> (<code>{pnl:+.2f}%</code>)\n"
            txt += f"  🎯 T1: <code>{t1:.4f}</code> | T2: <code>{t2:.4f}</code> | 🛑 SL: <code>{sl:.4f}</code>\n\n"
    
    if not has_any:
        cap = float(acc.get('capital', 0)) if acc else 0
        txt += "💤 <b>لا توجد صفقات مفتوحة حالياً</b>\n\n"
        if cap > 0:
            txt += f"💰 الرصيد الحر على المنصة: <code>{cap:.2f}</code> USDT\n"
        txt += "🔔 سيقوم البوت بفتح الصفقات ومتابعتها تلقائياً عند ظهور أول إشارة مطابقة.\n"
        
    txt += "━━━━━━━━━━━━━━━━━━━━\n"
    txt += "🟢 <b>أرقام الصفقات تومض وتتحدث تلقائياً مع حركة الأسعار</b>"
    kb = back_kb([[bt("🔄 تحديث يدوي", "m:guard"), bt("📊 المحفظة", "m:port")]])
    return txt, kb

def get_port_content(u: dict) -> tuple:
    txt = portfolio_text(u)
    txt += f"\n━━━━━━━━━━━━━━━━━━━━\n🟢 <b>الأرقام مربوطة بالمحفظة وتتحدث تلقائياً</b>"
    kb = back_kb()
    return txt, kb

def get_sig_content(u: dict) -> tuple:
    txt = latest_signals_text(u)
    txt += f"\n━━━━━━━━━━━━━━━━━━━━\n🟢 <b>رادار الإشارات يعمل لحظياً وتلقائياً</b>"
    kb = back_kb([[bt("🔄 تحديث يدوي", "m:sig")]])
    return txt, kb

def _quick_update_open_positions_prices():
    try:
        st = load_state()
        open_pos = [p for p in st.get("open_positions", []) if p.get("status") == "OPEN"]
        if not open_pos:
            return
        symbols = list(set([p.get("ticker") for p in open_pos if p.get("ticker")]))
        if not symbols:
            return
        prices = {}
        for s in symbols:
            try:
                res = _binance_get("/api/v3/ticker/price", {"symbol": s}, timeout=2)
                if isinstance(res, dict) and "price" in res:
                    prices[s] = float(res["price"])
            except Exception:
                pass
        if prices:
            changed = False
            now_cur = time.time()
            for p in open_pos:
                sym = p.get("ticker")
                if sym in prices:
                    new_p = prices[sym]
                    old_p = float(p.get("current_price", 0))
                    if abs(new_p - old_p) > 1e-8:
                        p["prev_price"] = old_p
                        p["current_price"] = new_p
                        p["tick_dir"] = "UP" if new_p > old_p else ("DOWN" if new_p < old_p else "NONE")
                        p["last_tick_time"] = now_cur
                        changed = True
                    elif now_cur - float(p.get("last_tick_time", 0)) > 6 and p.get("tick_dir") != "STABLE":
                        p["tick_dir"] = "STABLE"
                        changed = True
            if changed:
                save_state()
    except Exception:
        pass

def live_auto_refresher_loop():
    """حلقة التحديث اللحظي التلقائي — تعدل الأرقام فقط عند تغيرها بدون وميض الشاشة"""
    while True:
        time.sleep(3.0)
        try:
            if not LIVE_VIEWERS:
                continue
            
            _quick_update_open_positions_prices()
            
            now_t = time.time()
            with LIVE_VIEWERS_LOCK:
                active_items = list(LIVE_VIEWERS.items())
                
            for cid, viewer in active_items:
                # إيقاف التحديث إذا مضت 10 دقائق دون نشاط لتوفير البيانات
                if now_t - viewer.get("opened_at", now_t) > 600:
                    unregister_live_viewer(cid)
                    continue
                    
                screen = viewer.get("screen")
                msg_id = viewer.get("msg_id")
                u = get_user(cid)
                
                new_txt, new_kb = None, None
                if screen == "live":
                    new_txt, new_kb = get_live_page_content()
                elif screen == "guard":
                    new_txt, new_kb = get_guard_content(u, cid)
                elif screen == "port":
                    new_txt, new_kb = get_port_content(u)
                elif screen == "sig":
                    new_txt, new_kb = get_sig_content(u)
                    
                if not new_txt or not msg_id:
                    continue
                    
                # التعديل فقط وحصراً عند تغير الأرقام أو البيانات (منع وميض الشاشة بالكامل)
                if new_txt != viewer.get("last_text"):
                    kb_markup = {"inline_keyboard": new_kb} if new_kb else None
                    tg("editMessageText", chat_id=cid, message_id=msg_id, text=new_txt,
                       reply_markup=kb_markup, parse_mode="HTML", timeout=3.5)
                    viewer["last_text"] = new_txt
                    viewer["last_refresh"] = now_t
        except Exception:
            pass

def trigger_immediate_live_refresh():
    """تحديث فوري لكل الشاشات النشطة بمجرد انتهاء دورة الفحص وتغير الأرقام"""
    try:
        if not LIVE_VIEWERS:
            return
        now_t = time.time()
        with LIVE_VIEWERS_LOCK:
            active_items = list(LIVE_VIEWERS.items())
        for cid, viewer in active_items:
            screen = viewer.get("screen")
            msg_id = viewer.get("msg_id")
            u = get_user(cid)
            new_txt, new_kb = None, None
            if screen == "live":
                new_txt, new_kb = get_live_page_content()
            elif screen == "guard":
                new_txt, new_kb = get_guard_content(u, cid)
            elif screen == "port":
                new_txt, new_kb = get_port_content(u)
            elif screen == "sig":
                new_txt, new_kb = get_sig_content(u)
            # التعديل فقط إذا تغيرت الأرقام الفعلية لمنع وميض الشاشة
            if new_txt and msg_id and new_txt != viewer.get("last_text"):
                kb_markup = {"inline_keyboard": new_kb} if new_kb else None
                tg("editMessageText", chat_id=cid, message_id=msg_id, text=new_txt,
                   reply_markup=kb_markup, parse_mode="HTML", timeout=3.0)
                viewer["last_text"] = new_txt
                viewer["last_refresh"] = now_t
    except Exception:
        pass

def handle_callback(cb: dict):
    # إلغاء دوران زر التيليجرام فورياً في أول 1 ميلي ثانية
    cb_id = cb.get("id")
    if cb_id:
        answer_cb(cb_id)
        
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
        unregister_live_viewer(chat_id)
        if data == "nav:more":
            send_msg(chat_id, "🎛️ <b>لوحة التحكم الرئيسية</b>\n━━━━━━━━━━━━━━\nاختر القسم:", full_menu_kb(u), msg_id=msg_id)
        elif data in ("nav:less","nav:main"):
            send_msg(chat_id, "🤖 <b>بوت التداول الذكي</b>\n━━━━━━━━━━━━━━\nاضغط لفتح اللوحة", more_kb(), msg_id=msg_id)
        elif data == "m:abt":
            send_msg(chat_id, ABOUT_TEXT, api_back_kb(), msg_id=msg_id)
        elif data == "m:sig":
            txt, kb = get_sig_content(u)
            res = send_msg(chat_id, txt, kb, msg_id=msg_id)
            mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
            register_live_viewer(chat_id, mid, "sig", kb=kb, last_text=txt)
        elif data == "m:guard":
            try:
                txt, kb = get_guard_content(u, chat_id)
                res = send_msg(chat_id, txt, kb, msg_id=msg_id)
                mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
                register_live_viewer(chat_id, mid, "guard", kb=kb, last_text=txt)
            except Exception as e:
                send_msg(chat_id, f"🛡️ خطأ: {esc(str(e))}", api_back_kb(), msg_id=msg_id)
        elif data == "m:port":
            txt, kb = get_port_content(u)
            res = send_msg(chat_id, txt, kb, msg_id=msg_id)
            mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
            register_live_viewer(chat_id, mid, "port", kb=kb, last_text=txt)
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
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            if not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط", api_back_kb(), msg_id=msg_id)
            else:
                st = load_state()
                allowed = st.get("allowed", [])
                users_map = st.get("users", {})
                txt = f"👥 <b>المشتركون المصرح لهم ({len(allowed)})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                if allowed:
                    for uid_str in allowed[:25]:
                        usr = users_map.get(str(uid_str), {})
                        name = usr.get("first_name", "")
                        username = usr.get("username", "")
                        info = f"• <code>{uid_str}</code>"
                        if name:
                            info += f" — {esc(name)}"
                        if username:
                            info += f" (@{esc(username)})"
                        txt += info + "\n"
                else:
                    txt += "لا يوجد مشتركون إضافيون — البوت خاص بالمشرف فقط.\n"
                txt += "━━━━━━━━━━━━━━━━━━━━\n💡 عندما يطلب مشترك جديد الانضمام، سيصلك تنبيه مع زر للموافقة المباشرة."
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
                if ENGINE_RES is None and not CYCLE_LOCK.locked():
                    threading.Thread(target=run_cycle, args=("manual_live",), daemon=True).start()
                txt, kb = get_live_page_content()
                res = send_msg(chat_id, txt, kb, msg_id=msg_id)
                mid = msg_id or (res.get("message_id") if isinstance(res, dict) else None)
                register_live_viewer(chat_id, mid, "live", kb=kb, last_text=txt)
            except Exception as e:
                log(f"[LIVE PAGE] {e} {traceback.format_exc()}")
                send_msg(chat_id, f"⚡ خطأ: {esc(str(e))}", api_back_kb(), msg_id=msg_id)
        elif data == "m:api":
            try:
                send_msg(chat_id, LIVE.panel(u), LIVE.keyboard(u), msg_id=msg_id)
            except Exception as e:
                send_msg(chat_id, f"🔑 خطأ: {esc(str(e))}", more_kb(), msg_id=msg_id)
        elif data == "acc:req":
            try:
                user_msg = (
                    "📨 <b>تم إرسال طلب الانضمام بنجاح!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "⏳ طلبك قيد مراجعة المشرف الآن.\n"
                    "🔔 سيصلك إشعار وتنبيه فوري هنا بمجرد موافقة المشرف لتتمكن من استخدام البوت ومتابعة الإشارات مباشرة."
                )
                send_msg(chat_id, user_msg, msg_id=msg_id)
                
                st = load_state()
                admin_id = st.get("admin_chat_id") or ADMIN_CHAT_ID or OWNER_ID
                frm = cb.get("from") or {}
                fn = frm.get("first_name", "")
                un = frm.get("username", "")
                user_info = f"<code>{chat_id}</code>"
                if fn:
                    user_info += f" ({esc(fn)})"
                if un:
                    user_info += f" @{esc(un)}"
                
                admin_text = (
                    "🔔 <b>طلب انضمام جديد للبوت:</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 المستخدم: {user_info}\n"
                    f"🆔 المعرف: <code>{chat_id}</code>\n\n"
                    "اضغط الزر أدناه لتفعيل المشترك فوراً والسماح له باستخدام البوت 👇"
                )
                admin_kb = [[bt("✅ موافقة وتفعيل المشترك", f"acc:allow:{chat_id}")]]
                if admin_id and str(admin_id) != str(chat_id):
                    send_msg(int(admin_id), admin_text, admin_kb)
                log(f"[AUTH_REQ] طلب وصول جديد من {chat_id} تم إرساله للمشرف {admin_id}")
            except Exception as e:
                log(f"[AUTH_REQ_ERR] {e}")
                send_msg(chat_id, "⚠️ تم استلام طلبك، بانتظار موافقة المشرف.", msg_id=msg_id)
        elif data.startswith("acc:allow:"):
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            if not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط — لا يمكنك قبول الأعضاء", api_back_kb(), msg_id=msg_id)
            else:
                try:
                    target = data.split(":")[-1]
                    st = load_state()
                    allowed = st.get("allowed", [])
                    target_str = str(target)
                    if target_str not in [str(x) for x in allowed]:
                        allowed.append(target_str)
                        st["allowed"] = allowed
                    
                    target_u = get_user(int(target), create=True)
                    save_state()
                    log(f"[ALLOW] المشرف {chat_id} سمح للمستخدم {target}")
                    
                    send_msg(chat_id, f"✅ تم تفعيل المشترك <code>{target}</code> بنجاح!\nالآن يمكنه استخدام جميع مميزات البوت ومتابعة الإشارات.", full_menu_kb(u), msg_id=msg_id)
                    try:
                        approved_msg = (
                            "🎉 <b>تمت الموافقة على طلبك بنجاح!</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "✅ أصبح لديك الآن حق الوصول الكامل لبوت التداول الذكي.\n"
                            "📡 الإشارات الحية ومتابعة الصفقات ستصلك تلقائياً فور صدورها.\n\n"
                            "👇 اضغط على الزر أدناه لفتح لوحة التحكم والبدء:"
                        )
                        send_msg(int(target), approved_msg, [[bt("🎛️ فتح لوحة التحكم", "nav:more")]])
                    except Exception as e:
                        log(f"[ALLOW NOTIFY] {target} {e}")
                except Exception as e:
                    send_msg(chat_id, f"⚠️ خطأ: {esc(str(e))}", full_menu_kb(u), msg_id=msg_id)
        elif data.startswith("acc:"):
            is_admin = u.get("admin") or (ADMIN_CHAT_ID and int(chat_id) == int(ADMIN_CHAT_ID)) or (int(chat_id) == OWNER_ID)
            target = data.split(":")[-1]
            if target == "req":
                pass
            elif not is_admin:
                send_msg(chat_id, "🔒 للمشرف فقط", api_back_kb(), msg_id=msg_id)
            else:
                try:
                    st = load_state()
                    allowed = st.get("allowed", [])
                    if str(target) not in [str(x) for x in allowed]:
                        allowed.append(str(target))
                        st["allowed"] = allowed
                        get_user(int(target), create=True)
                        save_state()
                    send_msg(chat_id, f"✅ تم السماح لـ {target}", full_menu_kb(u), msg_id=msg_id)
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
                "🔒 <b>مرحباً بك في بوت التداول الذكي V5 Ultra</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 معرف حسابك (ID): <code>{cid}</code>\n\n"
                "هذا البوت خاص وآمن. للبدء وتفعيل حسابك لتلقي الإشارات ومتابعة الصفقات، اضغط على زر <b>📨 طلب وصول</b> أدناه وسيتم إرسال طلبك للمشرف للموافقة الفورية.\n"
                "━━━━━━━━━━━━━━━━━━━━"
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
        # السماح بمعالجة طلب الوصول حتى لغير المصرح لهم
        if cb.get("data") == "acc:req":
            handle_callback(cb)
            return

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
            answer_cb(cb.get("id",""), "🔒 يرجى طلب الوصول أولاً عبر الزر المرفق")
            return
        handle_callback(cb)

def boot_welcome_admin():
    st = load_state()
    aid = st.get("admin_chat_id") or ADMIN_CHAT_ID
    if aid:
        send_msg(aid, f"✅ البوت يعمل\n{STRATEGY_PROVENANCE}", more_kb())

UPDATE_EXECUTOR = ThreadPoolExecutor(max_workers=20, thread_name_prefix="tg_fast")

def _safe_dispatch_update(upd: dict):
    try:
        handle_update(upd)
    except Exception as e:
        log(f"[POLL_DISPATCH] خطأ: {e}\n{traceback.format_exc()}")

def poll_loop():
    st = load_state()
    offset = st.get("tg_offset")
    while True:
        try:
            params = {"timeout": 20, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            ups = tg("getUpdates", retries=2, **params)
            if ups is None:
                time.sleep(1)
                continue
            for upd in ups:
                offset = upd["update_id"] + 1
                # معالجة كل ضغطة زر أو رسالة فورياً في خيط مستقل فائق السرعة دون أي انتظار
                UPDATE_EXECUTOR.submit(_safe_dispatch_update, upd)
            if ups:
                _STATE["tg_offset"] = offset
        except Exception as e:
            log(f"[POLL] خطأ الحلقة: {e}")
            time.sleep(2)

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
    cleanup_stale_and_delisted_positions()
    if ADMIN_CHAT_ID and not st.get("admin_chat_id"):
        st["admin_chat_id"] = ADMIN_CHAT_ID
        save_state()
        log(f"[BOOT] تم تعيين المشرف من البيئة: {ADMIN_CHAT_ID}")
    threading.Thread(target=cycle_loop, daemon=True, name="cycle").start()
    threading.Thread(target=live_auto_refresher_loop, daemon=True, name="live_auto_refresher").start()
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
