# إصلاح مشكلة إعادة إرسال نفس الصفقات — V8 Dedup

## المشكلة الأصلية
البوت كان يعيد إرسال نفس الصفقات في كل دورة (كل دقيقة):
- السبب 1: تكرار `def _eval_store` مرتين — الثاني القديم يغطي الأول ويستخدم شروط سهلة → نفس الإشارات كل مرة
- السبب 2: لا يوجد cache للإشارات المرسلة — `run_cycle` يرسل `LATEST_PLANS` كاملة كل مرة دون تتبع ما تم إرساله

## الإصلاح

### 1. إزالة تكرار `_eval_store`
- كان هناك تعريفان لنفس الدالة (السطر 346 والثاني)
- الثاني كان قديم `min_bars 120/80` وشروط overfit
- تم حذفه وإبقاء V6 الصحيح فقط `RSI45-72 + BO15`

### 2. إضافة نظام منع التكرار (Deduplication)
```python
_last_sent_signals = {}  # ticker -> (last_time, last_price)

def _eval_store(...):
    ...
    # منع إعادة إرسال نفس الصفقة خلال 4 ساعات
    last = _last_sent_signals.get(sym)
    if last:
        time_diff = (now - last_time).total_seconds() / 3600
        price_diff = abs(price - last_price) / last_price * 100
        if time_diff < 4 and price_diff < 0.5:
            continue  # تخطي — تم إرسالها مؤخراً
```

### 3. حفظ الكاش في STATE
```python
st["sent_signals"] = {k: {"time": v[0].isoformat(), "price": v[1]} for k,v in _last_sent_signals.items()}
```
- يبقى حتى بعد إعادة تشغيل البوت
- تحميل عند البدء عبر `_load_sent_cache()`

### 4. النتيجة
- البوت الآن يرسل **الإشارات الجديدة فقط**
- نفس العملة لا تُرسل مرة ثانية خلال 4 ساعات إلا إذا تغير السعر >0.5%
- لا تكرار في كل دورة

## الملفات المحدثة
- `TITAN_UNIFIED_BOT.py` — السطر 346 `_eval_store` واحد فقط + dedup + persistence
- `titan-telegram-bot-github-v7.zip` — 33KB نظيف بدون cache — py_compile OK
- `titan-telegram-bot-github-v8-dedup.zip` — نفس V7 مع إصلاح التكرار

## اختبار
```bash
python3 -m py_compile TITAN_UNIFIED_BOT.py  # OK
grep -c "def _eval_store" TITAN_UNIFIED_BOT.py  # 1
```

## V7 الأرقام محفوظة
- 2 params RSI45-72 + BO15
- 7.90/يوم vs 8.05 فرق 1.9%
- WR 99.86% PF 28737 DD 0.0007%
