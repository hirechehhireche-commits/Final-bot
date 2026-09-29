#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  BT5Y STATIC — باكتست الخمس سنوات الثابت لـ v127 (4H) لزر «باكتست الاستراتيجية»
  ═════════════════════════════════════════════════════════════════════════════
  • يُبنى مرة واحدة فقط عند أول إقلاع (خيط خلفي) ثم يبقى نصاً ثابتاً لا يتجدد.
  • يُخزَّن محسوباً على القرص الدائم (TITAN_CACHE_DIR على Render) — بعد أي إعادة
    نشر يُحمَّل فوراً بلا إعادة بناء.
  • البيانات: كاش 5 سنوات 4H يُبنى من KuCoin (تجزئة ≤100 شمعة) — وإن وُجد كاش
    جاهز بنفس الاسم يُستخدم مباشرة.
  • المحرك: v127 المعتمد نفسه (run_dual_strategies للمقاييس + مجلات المجمعات
    للصفقات الكاملة: العملة/التواريخ/المدة/النسبة).
  • بأي فشل: يعيد حالة خطأ — زر البوت يرجع للعرض الحي تلقائياً (لا انهيار).
═══════════════════════════════════════════════════════════════════════════════
"""
import io, os, sys, json, time, threading, traceback
import csv as _csv

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

LOCK = threading.Lock()
STATE = dict(status="idle", text=None, rows=None, csv=None, built_at=None, error=None)

CACHE_DIR = os.environ.get("TITAN_CACHE_DIR", os.path.join(HERE, "bot_cache"))
STORE_5Y = os.path.join(CACHE_DIR, "titans_4h_5y_cache.pkl")
RESULT_5Y = os.path.join(CACHE_DIR, "bt5y_static_result.pkl")
KC = "https://api.kucoin.com/api/v1/market/candles"


# ─────────────────────────── جلب KuCoin متجزئ ───────────────────────────
def _kc_4h(symbol, max_bars=11500):
    """تاريخ 4h كامل عبر نوافذ متراجعة — مع startAt يعيد KuCoin حتى 1500 شمعة/طلب
    (بلا limit؛ limit=100 يخنق الطلب) — 5 سنوات ≈ 8-10 طلبات."""
    import urllib.request
    sym = symbol.replace("USDT", "-USDT")
    rows = []
    end = int(time.time())
    start = end - 5 * 366 * 24 * 3600          # أرضية 5 سنوات — يوقف الجلب عندها
    seen_oldest = None
    while len(rows) < max_bars and end > start:
        url = (f"{KC}?type=4hour&symbol={sym}&startAt={start}&endAt={end}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            chunk = json.load(r).get("data") or []
        if not chunk:                           # وصلنا لأقدم تاريخ متاح
            break
        oldest = int(chunk[-1][0])
        if seen_oldest is not None and oldest >= seen_oldest:
            break                               # لا تقدّم → توقف بأمان (حماية من حلقة لا نهائية)
        seen_oldest = oldest
        rows = chunk + rows
        end = oldest - 1
        time.sleep(0.15)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "open", "close", "high", "low", "vol", "turn"]).drop_duplicates("ts")
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="s", utc=True)
    for c in ("open", "close", "high", "low", "vol"):
        df[c] = df[c].astype(float)
    df = df.rename(columns={"open": "Open", "close": "Close", "high": "High",
                            "low": "Low", "vol": "Volume"})
    return df.set_index("ts").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def _build_store_5y(log=print):
    import titan_juggernaut_bot as T
    univ = list(dict.fromkeys(T.POOL1_ASSETS + T.POOL2_ASSETS + T.POOL3_ASSETS + T.STRATEGY2_ASSETS))
    store = {}
    for i, sym in enumerate(univ, 1):
        try:
            df = _kc_4h(sym)
            if df is not None and len(df) > 1000:
                store[sym] = df.iloc[:-1]                     # أسقط الشمعة غير المغلقة
                log(f"[BT5Y] [{i:2d}/{len(univ)}] {sym}: {len(df)} شمعة 4h")
            else:
                log(f"[BT5Y] [{i:2d}/{len(univ)}] ⚠️ {sym}: بيانات غير كافية — تجاوز")
        except Exception as e:
            log(f"[BT5Y] [{i:2d}/{len(univ)}] ⚠️ {sym}: {e}")
    return store


# ─────────────────────────── الصفقات الكاملة ───────────────────────────
def _dur_str(entry, exit_):
    """مدة الصفقة: أيام/ساعات/دقائق بشكل مختصر عربي."""
    try:
        d = pd.Timestamp(exit_) - pd.Timestamp(entry)
        h = d.total_seconds() / 3600.0
        if h >= 48:
            return f"{int(h // 24)}ي {int(h % 24)}س"
        if h >= 1:
            return f"{int(h)}س"
        return f"{max(int(d.total_seconds() // 60), 1)}د"
    except Exception:
        return "—"


def _deals_from_pools(store, log=print):
    """صفقات v127 كاملة (بمجلات المجمعات — نفس قلب الواجهة) على كاش 5 سنوات."""
    import titan_juggernaut_bot as T
    assets = list(T.ELITE_TRADEABLE_ASSETS) + [s for s in T.STRATEGY2_ASSETS
                                               if s not in T.ELITE_TRADEABLE_ASSETS]
    union, proc, _ = T.FastSimulator.prepare_arrays(store, assets=assets)
    s1s = T.STRATEGY1_CAPITAL / 100.0
    cfgs = [("P1", T.POOL1_ASSETS, T.POOL1_PARAMS, T.POOL_BUDGETS[0] * s1s),
            ("P2", T.POOL2_ASSETS, T.POOL2_PARAMS, T.POOL_BUDGETS[1] * s1s),
            ("P3", T.POOL3_ASSETS, T.POOL3_PARAMS, T.POOL_BUDGETS[2] * s1s),
            ("S2", T.STRATEGY2_ASSETS, T.STRATEGY2_PARAMS, T.STRATEGY2_CAPITAL)]
    groups = {}
    for tag, syms, params, budget in cfgs:
        j = {}
        _, tr, _, _ = T.FastSimulator.simulate_prepared(proc, union, syms, params,
                                                        initial_capital=budget, journal=j)
        reg = {}
        for e in j.get("entries", []):
            reg.setdefault(e["ticker"], []).append(e)
        for x in tr:
            # الدخول المرجعي: أقرب دخول مسجّل قبل وقت الخروج
            cands = [e for e in reg.get(x["ticker"], [])
                     if pd.Timestamp(e["time"]) <= pd.Timestamp(x["time"])]
            e0 = cands[-1] if cands else {}
            key = (tag, x["ticker"], str(e0.get("time", x["time"])))
            g = groups.setdefault(key, dict(pool=tag, ticker=x["ticker"],
                                            entry_time=e0.get("time"), entry_price=e0.get("price"),
                                            spend=float(e0.get("spend", 0) or 0),
                                            pnl_usdt=0.0, exit_time=x["time"],
                                            exit_price=x.get("exit_price"), exit_type=x["type"],
                                            wins=0, closed=False))
            g["pnl_usdt"] += float(x.get("pnl_usdt", 0) or 0)
            g["exit_time"] = x["time"]; g["exit_price"] = x.get("exit_price"); g["exit_type"] = x["type"]
            g["wins"] += 1 if x.get("is_win") else 0
            if x["type"] in ("SL", "RSI_PEAK", "TIME_STOP", "TRAIL_STOP"):
                g["closed"] = True
    deals = []
    for g in groups.values():
        spend = g["spend"] if g["spend"] > 0 else 1e-9
        g["pnl_pct"] = g["pnl_usdt"] / spend * 100.0
        g["is_win"] = g["pnl_usdt"] > 0
        g["dur"] = _dur_str(g["entry_time"], g["exit_time"])
        deals.append(g)
    deals.sort(key=lambda d: pd.Timestamp(d["entry_time"]) if d["entry_time"] is not None
               else pd.Timestamp(0, tz="UTC"))
    return deals, union, proc, cfgs


def _metrics_5y(store, union, proc, cfgs):
    """مقاييس v127 على 5 سنوات (نفس بنية الشهادة: ميزانيات + dyn OFF)."""
    import titan_juggernaut_bot as T
    navs, trades = [], []
    for tag, syms, params, budget in cfgs:
        nv, tr, _, _ = T.FastSimulator.simulate_prepared(proc, union, syms, params,
                                                         initial_capital=budget)
        navs.append(nv["nav"].to_numpy(float)); trades.extend(tr)
    nav1 = np.sum(navs, axis=0)
    nv2, tr2, _, _ = T.FastSimulator.simulate_prepared(
        proc, union, T.STRATEGY2_ASSETS, T.STRATEGY2_PARAMS, initial_capital=T.STRATEGY2_CAPITAL)
    comb, _, _ = T.combine_dynamic_capital(nav1, nv2["nav"].to_numpy(float), union, cfg=T.DYNAMIC_CAPITAL)
    return T.MetricsEngine.compute(pd.DataFrame({"nav": comb}, index=union), trades + list(tr2),
                                   initial_capital=T.TOTAL_CAPITAL)


# ─────────────────────────── التجميع الثابت ───────────────────────────
def _fmt_price(p):
    try:
        p = float(p)
        if p >= 100: return f"{p:,.1f}"
        if p >= 1:   return f"{p:,.3f}"
        return f"{p:.6g}"
    except Exception:
        return "—"


def _render(art):
    """يبني النص الثابت (ملخّص + أول صفحة) وصفوف الجدول وCSV من ناتج البناء."""
    m, deals = art["metrics"], art["deals"]
    wins = [d for d in deals if d["is_win"]]
    wr = len(wins) / len(deals) * 100 if deals else 0
    y0, y1 = art["period"]
    s = (f"📋 <b>باكتست v127.0.0 — آخر 5 سنوات (4H)</b> 🔒 ثابت\n"
         f"━" * 1 + "━" * 21 + "\n"
         f"📅 الفترة: {y0} ← {y1}\n"
         f"💰 العائد الكلي: <b>{m['total_ret']:+.2f}%</b> | مضاعفة ×{m['final_nav'] / 400.0:.2f}\n"
         f"🧾 الصفقات: {len(deals)} | ✅ رابحة {len(wins)} ({wr:.1f}%)\n"
         f"📉 أقصى تراجع {m['max_dd']:.2f}% | ⚖️ Sharpe {m['sharpe']:.2f} | PF {m['pf']:.2f}\n"
         f"🛡️ محرك v127 المعتمد (إطفاء إعادة التوازن) — ثابت 🔒 محسوب {art['built_at']}\n"
         f"<i>(نتيجة بيانات هذه النسخة — تُبنى من KuCoin لسلة v127 عند أول إقلاع وقد تختلف "
         f"عن الشهادة الرسمية +2382.29% المحسوبة على كاش البيانات الأصلي)</i>\n"
         + "━" * 22)
    art["summary"] = s
    art["rows"] = [dict(n=i, coin=str(d["ticker"]).replace("USDT", ""), pool=d["pool"],
                        entry=pd.Timestamp(d["entry_time"]).strftime("%y-%m-%d") if d["entry_time"] is not None else "—",
                        exit=pd.Timestamp(d["exit_time"]).strftime("%y-%m-%d %H:%M") if d["exit_time"] is not None else "—",
                        dur=d["dur"], pnl=d["pnl_pct"], win=bool(d["is_win"]),
                        closed=bool(d.get("closed")))
                   for i, d in enumerate(deals, 1)]
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["#", "العملة", "المجمع", "تاريخ الدخول", "تاريخ الخروج", "المدة",
                "النتيجة %", "رابحة؟", "مغلقة؟"])
    for r in art["rows"]:
        w.writerow([r["n"], r["coin"], r["pool"], r["entry"], r["exit"], r["dur"],
                    f"{r['pnl']:.2f}", "نعم" if r["win"] else "لا", "نعم" if r["closed"] else "لا"])
    art["csv"] = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return art


def ensure(workspace_dir=None, log=print):
    """نقطة الدخول: يبني مرة واحدة (أو يحمّل المحفوظ) ويعيد dict الحالة الثابتة."""
    global CACHE_DIR, STORE_5Y, RESULT_5Y
    if workspace_dir:
        CACHE_DIR = workspace_dir
        STORE_5Y = os.path.join(CACHE_DIR, "titans_4h_5y_cache.pkl")
        RESULT_5Y = os.path.join(CACHE_DIR, "bt5y_static_result.pkl")
    with LOCK:
        if STATE["status"] == "ready":
            return STATE
        if STATE["status"] == "building":
            return STATE
        STATE["status"] = "building"
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        # 1) ناتج محسوب محفوظ (بقاء عبر إعادة النشر على القرص الدائم)
        if os.path.exists(RESULT_5Y):
            art = pd.read_pickle(RESULT_5Y)
            STATE.update(status="ready", text=art["summary"], rows=art["rows"],
                         csv=art["csv"], built_at=art.get("built_at"))
            log("[BT5Y] ✅ حُمّل الباكتست الثابت المحفوظ (بلا إعادة حساب)")
            return STATE
        # 2) البناء: كاش 5Y (موجود؟ وإلا KuCoin) ثم تشغيل v127
        if not os.path.exists(STORE_5Y):
            log("[BT5Y] أول مرة: بناء كاش 5 سنوات من KuCoin (~8 دقائق، مرة واحدة)...")
            store = _build_store_5y(log)
            if len(store) < 15:
                raise RuntimeError(f"بيانات غير كافية ({len(store)} رمزاً)")
            pd.to_pickle(store, STORE_5Y)
        else:
            store = pd.read_pickle(STORE_5Y)
            log(f"[BT5Y] كاش 5Y موجود ({len(store)} رمزاً) — تخطي التنزيل")
        deals, union, proc, cfgs = _deals_from_pools(store, log)
        m = _metrics_5y(store, union, proc, cfgs)
        idx = union
        art = dict(metrics=m, deals=deals,
                   period=(f"{idx[0]:%Y-%m-%d}", f"{idx[-1]:%Y-%m-%d}"),
                   built_at=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
        art = _render(art)
        pd.to_pickle(dict(summary=art["summary"], rows=art["rows"], csv=art["csv"],
                          built_at=art["built_at"], period=art["period"]), RESULT_5Y)
        STATE.update(status="ready", text=art["summary"], rows=art["rows"],
                     csv=art["csv"], built_at=art["built_at"])
        log(f"[BT5Y] ✅ الباكتست الثابت جاهز: {m['total_ret']:+.2f}% | {len(deals)} صفقة")
    except Exception as e:
        STATE.update(status="error", error=f"{e}")
        log("[BT5Y] ❌ " + traceback.format_exc()[-300:])
    return STATE


def table_page(page=0, per=14):
    """صفحة جدول ثابتة (نفس أسلوب الواجهة) مع مدة الصفقة."""
    if STATE["status"] != "ready" or not STATE["rows"]:
        return None
    import math
    rows = STATE["rows"]
    total = max(1, math.ceil(len(rows) / per))
    page = max(0, min(page, total - 1))
    chunk = rows[page * per:(page + 1) * per]
    head = f"{'#':>4} {'COIN':<6}{'ENTRY':<9}{'EXIT':<15}{'DUR':<8}{'RESULT':>8}"
    body = [head, "-" * len(head)]
    for r in chunk:
        res = f"{'+' if r['win'] else ''}{r['pnl']:.2f}%"
        body.append(f"{r['n']:>4} {r['coin']:<6}{r['entry']:<9}{r['exit']:<15}"
                    f"{r['dur']:<8}{res:>8}")
    txt = ("<pre>" + "\n".join(body) + "</pre>\n"
           f"<i>العملة | دخول | خروج | المدة | النسبة — صفحة {page + 1}/{total} | "
           f"محسوب {STATE.get('built_at', '—')} (ثابت 🔒)</i>")
    return txt, page, total


if __name__ == "__main__":
    print(json.dumps({k: (v if k != "rows" else f"{len(v)} صف") for k, v in ensure().items()
                      if k in ("status", "built_at", "error", "rows")}, ensure_ascii=False))
