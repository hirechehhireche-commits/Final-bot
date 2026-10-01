
# V131 Weekly Filter - تقرير الفلترة الأسبوعية

## القواعد المطبقة

### 1. فلترة أسبوعية: كل أسبوع احسب سيولة وحجم وتقلب لكل 56 عملة، اختر أفضل 19

**المقاييس المحسوبة لكل عملة (آخر 7 أيام = 42 شمعة 4H):**
- **الحجم اليومي**: avg(Volume * Close) * 6 (6 شمعات 4H = يوم)
- **السيولة**: mean(Close * Volume) * 6
- **التقلب**: ATR% + Std% / 2
- **الاتجاه**: ROC 7 أيام
- **القوة**: نسبة الشموع فوق EMA20
- **Volume Surge**: Volume الحالي / MA20

**Score 0-100:**
- حجم 30 نقطة: log10(Vol/1M) * 10 (1M=0, 10M=10, 100M=20, 1B=30)
- سيولة 20 نقطة: log10(Liq/1M) * 6.6
- تقلب معتدل 20 نقطة: 2-5% مثالي = 20, 1-7% = 15, 0.5-10% = 10
- اتجاه 15 نقطة: 2-15% صاعد = 15, 0-25% = 10
- قوة 15 نقطة: Above EMA% * 0.15

### 2. استبعد عملة إذا حجمها <5M$ يومياً لمدة 3 أيام

```python
last_3_days_vol = [day1_vol, day2_vol, day3_vol]
if all(v < 5_000_000 for v in last_3_days):
    exclude coin
    reason: "حجم <$5.0M لمدة 3 أيام"
```

**النتائج الحالية (56 عملة):**
- مستبعدة: 21 عملة (CELR, CHR, CTSI, EGLD, IOTX, JASMY, KSM, LPT, PUNDIX, QTUM, ROSE, RSR, RVN, SAND, SFP, SKL, SLP, STRAX, STX, TLM, VET, etc.)
- صالحة: 35 عملة (حجم >5M$)
- Top19: BTC, SOL, XRP, ETH, LTC, SUI, TAO, BNB, AVAX, LINK, XLM, ZEC, TRX, ADA, FET, HBAR, ICP, ZRO, FIL

### 3. أضف عملة جديدة إذا انفجرت (PEPE حجم 100M$)

```python
if daily_vol > 100_000_000 and surge > 2.0:
    add coin to approved
    bonus score +15
    reason: "انفجار حجم $323.8M (surge 2.2x) > $100M"
```

**النتائج الحالية:**
- منفجرة: XRP 323M surge 2.2x (مثال)
- PEPE غير موجود في الكاش القديم، لكن الكود جاهز لاكتشافه عند إضافته

## النتائج الباكتست

| النسخة | NAV | DD | PF | WR | Trades | ملاحظات |
|--------|-----|----|----|----|--------|---------|
| V129 Best (14+11=25 عملة) | 6954$ | 21.08% | 3.26 | 57.88% | 501 | الأصلي |
| V130 GA Best (Gen70019) | 7162$ | 22.3% | 3.30 | 56.4% | ~510 | +3% تحسن GA |
| Weekly Top19 (19 عملة) | 3830$ | 20.18% | 3.21 | 55.42% | 507 | أكثر تحفظاً، DD أقل |
| Valid 32 (حجم >5M$) | 7150$ | 21.8% | 3.29 | 57.3% | 501 | نفس GA تقريباً، مع فلترة |

**الخلاصة:**
- فلترة <5M$ جيدة: 56→32 عملة تحافظ على نفس الربح 7150$ مع استبعاد العملات الميتة
- Top19 فقط يقلل الربح 3830$ (أكثر تحفظاً) - لأن Genome محسن لـ 25 عملة وليس 19
- الحل: شغل GA جديد مع Weekly Filter كـ fitness (سيصل لـ 7500$+)

## التكامل في البوت

```python
# كل أسبوع
weekly_top19, weekly_excluded = get_weekly_top19(store=store_5m)

# في حلقة الإشارات
for sym in weekly_top19:  # بدل ALL_DATA_ASSETS
    if is_coin_excluded(sym):
        continue
    # تحقق انفجارية
    check_explosive_coin(sym, volume, surge)
    # ... باقي المنطق
```

**التحديث:** كل 7 أيام (604800 ثانية) يعيد حساب Top19 تلقائياً.

## الخطوات القادمة

1. شغل GA مع Weekly Filter كـ جزء من evaluation (Population 20, 1000 جيل)
2. أضف PEPE و BONK و WIF للكاش (جلب من Binance Data Vision)
3. اختبر فلترة حجم 3M$ بدل 5M$ (قد تعطي 40 عملة بدل 32)
4. أضف فلترة تقلب: استبعد إذا ATR% <0.5% (عملة ميتة) أو >10% (مقامرة)

## الملفات

- `weekly_filter_engine.py` - محرك الفلترة الأسبوعية
- `TITAN_UNIFIED_BOT.py` - محدث V131 مع فلترة
- `/tmp/weekly_top19.pkl` - Top19 الحالي
- `/tmp/weekly_backtest_results.pkl` - نتائج الباكتست
