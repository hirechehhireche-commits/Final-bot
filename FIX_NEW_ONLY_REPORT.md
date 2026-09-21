# إصلاح إرسال الصفقات الموروثة من الباكتست — الجديد فقط

## المشكلة
البوت كان يرسل:
- إشارات بيع
- ضرب ستوب
- خروج من الصفقات الموروثة من الباكتست

المستخدم يريد: **إرسال الإشارات الجديدة فقط**

## السبب
- ملف `bot_state_v241.json` يحتوي `open_positions` قديمة من الباكتست
- البوت كان يقرأ كل الصفقات المفتوحة ويرسل بيع لها حتى لو موروثة
- لا يوجد فلترة للجديد فقط

## الحل — 3 مستويات

### 1. تنظيف تلقائي عند البدء
```python
def load_fingerprints():
    # تنظيف الصفقات الموروثة من الباكتست
    positions = st.get("open_positions", [])
    fresh = []
    for pos in positions:
        if "_" not in pos_id: continue  # صيغة قديمة من الباكتست
        age = now - entry_time
        if age > 24h: continue  # موروثة أكثر من 24 ساعة
        fresh.append(pos)
    st["open_positions"] = fresh  # احتفظ بالجديد فقط
```

### 2. فلترة إشارات البيع — الجديد فقط
```python
def evaluate_sell_signals():
    positions = get_open_positions()
    fresh_positions = []
    for pos in positions:
        if status != OPEN: continue
        age = now - entry_time
        if age > 24h: continue  # موروثة من الباكتست → تخطي
        fresh_positions.append(pos)
    
    # فقط الجديد يرسل بيع
    for pos in fresh_positions:
        if current >= tgt2: sell T2
        elif current >= tgt1: sell T1
        elif current <= sl: sell SL
```

### 3. فلترة العرض — LATEST_OPEN_POSITIONS الجديد فقط
```python
# في run_cycle
all_positions = get_open_positions()
fresh = [p for p in all_positions if age <= 24h and OPEN]
LATEST_OPEN_POSITIONS = fresh  # عرض الجديد فقط
```

### 4. سكريبت تنظيف يدوي
```bash
python3 clear_inherited.py
# يمسح كل الصفقات الموروثة + البصمات
# البوت يبدأ نظيف — الجديد فقط
```

## النتيجة
- ✅ لا يرسل بيع لصفقات موروثة من الباكتست
- ✅ لا يرسل ضرب ستوب لموروث
- ✅ لا يرسل خروج لموروث
- ✅ يرسل **الإشارات الجديدة فقط**:
  - شراء جديد عبر بصمة ذكية
  - بيع للصفقات الجديدة فقط (آخر 24 ساعة) مع ترقيم

## اختبار
```bash
# قبل الإصلاح
open_positions = 50 صفقة من الباكتست (قديمة)
→ يرسل 50 إشارة بيع/ستوب

# بعد الإصلاح
open_positions = 50 قديمة + 2 جديدة
→ يفلتر القديمة → يرسل بيع لـ 2 جديدة فقط ✅
→ LATEST_OPEN_POSITIONS = 2 جديدة فقط ✅
```

## الملفات
- TITAN_UNIFIED_BOT.py — تم إصلاحه — py_compile OK
- clear_inherited.py — سكريبت تنظيف
- titan-telegram-bot-v10-new-only.zip — 1.1M مع الصور والبوت
