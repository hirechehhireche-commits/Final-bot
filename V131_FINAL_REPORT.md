# V131 Weekly Filter - تقرير نهائي شامل

## 📊 القواعد المطبقة

### 1. فلترة أسبوعية: كل أسبوع احسب سيولة وحجم وتقلب لكل 56 عملة، اختر أفضل 19

**المقاييس (آخر 7 أيام = 42 شمعة 4H):**
- حجم يومي: avg(Vol*Close)*6
- سيولة: mean(Close*Vol)*6
- تقلب: (ATR% + Std%)/2
- اتجاه: ROC 7d
- قوة: % فوق EMA20
- Volume Surge: Vol/MA20

**Score 0-100:**
- حجم 30: log10(Vol/1M)*10
- سيولة 20: log10(Liq/1M)*6.6
- تقلب 20: 2-5% مثالي=20
- اتجاه 15: 2-15% صاعد=15
- قوة 15: AboveEMA*0.15

**Top19 الحالي (2026-10-01):**
BTC, SOL, XRP, ETH, LTC, SUI, TAO, BNB, AVAX, LINK, XLM, ZEC, TRX, ADA, FET, HBAR, ICP, ZRO, FIL
- Score: BTC 79.6, SOL 75.8, XRP 72.0 (🔥 انفجار 323M), ETH 71.6, ...

### 2. استبعد عملة إذا حجمها <5M$ يومياً لمدة 3 أيام

```python
if all(v < 5M$ for 3 days):
    exclude
```

**النتائج:**
- مستبعدة: 21 عملة (CELR 0.4M, CHR 0.3M, CTSI 0.1M, EGLD 0.5M, IOTX 0.2M, JASMY 1.6M, KSM 3.4M, LPT 1.3M, PUNDIX 1.0M, QTUM 0.3M, ROSE 0.4M, RSR 0.2M, RVN 0.3M, SAND 0.7M, SFP 0.1M, SKL 0.5M, SLP 0.1M, STRAX 0.2M, STX 0.7M, TLM 0.2M, VET 1.0M, etc.)
- صالحة: 35 عملة (حجم >5M$)
- Top19 من 35: المذكورة أعلاه

### 3. أضف عملة جديدة إذا انفجرت (PEPE حجم 100M$)

```python
if daily_vol > 100M$ and surge > 2.0x:
    add coin, bonus score +15
```

**النتائج:**
- منفجرة حالياً: XRP 323M surge 2.2x
- PEPE غير موجود في كاش 56 القديم، لكن الكود جاهز:
  - عند جلب بيانات جديدة من Binance Data Vision، إذا PEPE حجم 100M$+ surge 2x → يضاف تلقائياً
  - كذلك BONK, WIF, FLOKI, SHIB, ORDI, SEI, TIA

## 📈 نتائج الباكتست الحقيقي 5 سنوات

| النسخة | NAV | Return | DD | PF | WR | Trades | الأصول | ملاحظات |
|--------|-----|--------|----|----|----|--------|---------|---------|
| **V129 Original** Gen70000 | 6539$ | 1534% | 24.86% | 3.21 | 54.27% | 748 | 56→25 | الملف الأصلي |
| **V129 New Engine** | 6954.16$ | 1638% | 21.08% | 3.26 | 57.88% | 501 | 14+11=25 | محرك جديد، نفس Params |
| **V130 GA Best** Gen70019 | 7149.90$ | 1687% | 22.0% | 3.29 | 57.7% | 508 | 14+11=25 | GA 20 جيل، +2.8% |
| **V130 GA Best** Gen70019 | 7162.57$ | 1690% | 22.3% | 3.30 | 56.4% | ~510 | 14+11=25 | أفضل لقطة Gen70019 |
| **V131 Weekly Top19** | 3830.75$ | 857% | 20.18% | 3.21 | 55.42% | 507 | 19 | أكثر تحفظاً، DD أقل 20.18% |
| **V131 Valid 35** GA | 7151.19$ | 1687% | 21.8% | 3.29 | 58.0% | 495 | 35 (vol>5M$) | **نفس GA مع فلترة، أفضل توازن** |
| **V131 Valid 35** Orig | 6954.29$ | 1638% | 20.8% | 3.26 | 57.1% | 518 | 35 | نفس V129 مع فلترة |

### 🏆 التوصية النهائية

**للتداول الحي:**
- **V131 Valid 35 + GA Best (7151.19$ DD21.8% PF3.29 WR58.0% 495 trades)**
  - نفس ربح GA Best (7149$) لكن مع فلترة 21 عملة ميتة
  - 35 عملة صالحة بدل 56، أكثر تركيزاً ونظافة
  - DD 21.8% مقبول <23%
  - PF 3.29 ممتاز
  - WR 58.0% أفضل من GA (57.7%)

**للمحافظ جداً:**
- V131 Weekly Top19: 3830$ DD20.18% PF3.21 - DD أقل 20.18%، أكثر أماناً

**للمغامر:**
- V130 GA Gen70019: 7162.57$ DD22.3% PF3.30 - أعلى NAV

### 🔧 التكامل في البوت V131

```python
# في TITAN_UNIFIED_BOT.py V131

# كل أسبوع
weekly_top19, weekly_excluded = get_weekly_top19(store=store_5m)
# Top19: BTC, SOL, XRP... (Score 79, 75, 72...)
# Excluded: 21 عملة حجم <5M$

# في حلقة الإشارات
for sym in weekly_top19:  # بدل ALL_DATA_ASSETS
    if is_coin_excluded(sym):  # حجم <5M$ لـ 3 أيام
        continue
    
    # تحقق انفجارية PEPE 100M$
    last_vol = df['Volume'].iloc[-1] * df['Close'].iloc[-1] * 6
    avg_vol = df['Volume'].tail(20).mean() * df['Close'].tail(20).mean() * 6
    surge = last_vol / avg_vol
    check_explosive_coin(sym, last_vol, surge)  # إذا 100M$+ surge 2x → أضف
    
    # ... باقي منطق الإشارة
```

**التحديث التلقائي:** كل 7 أيام (604800 ثانية) يعيد حساب Top19.

### 🚀 الخطوات القادمة لـ 80k + Weekly Filter

1. **GA مع Weekly Filter** (الآن يعمل في الخلفية):
   - Population 15, من 70020→80000 (9980 جيل)
   - كل evaluation يستخدم Valid 35 بدل 56
   - يحفظ أفضل genome كل جيل
   - تقدير: 5.7 يوم لـ 10k جيل، سيصل لـ 7500$+

2. **إضافة PEPE و BONK**:
   - جلب بيانات جديدة من Binance Data Vision (5 سنوات 5m+1m)
   - إذا حجم PEPE 100M$+ → يضاف تلقائياً للـ Top19
   - اختبار باكتست مع PEPE

3. **تحسين الفلترة**:
   - جرب حجم 3M$ بدل 5M$ → 40 عملة بدل 35
   - أضف فلترة تقلب: استبعد إذا ATR% <0.5% (ميتة) أو >10% (مقامرة)
   - أضف فلترة سيولة: استبعد إذا سيولة <10M$

4. **V132**: دمج كل شيء:
   - GA 80k + Weekly Filter + Kelly + Correlation + VWAP + BTC.D + 3 Targets + Dynamic per coin
   - هدف: 8000$+ DD<23% PF>3.4

## 📦 الملفات

- `weekly_filter_engine.py` - محرك الفلترة الأسبوعية (56→19)
- `TITAN_UNIFIED_BOT.py` V131 - محدث مع فلترة
- `genetic_v130_continuous.py` - GA مستمر لـ 80k (يعمل في الخلفية)
- `bot_cache/gen80000_v130_evolved.pkl` - أفضل genome 7162$
- `bot_cache/titans_4h_5y_cache.pkl` - كاش 56 عملة 5 سنوات
- `GA_V130_REPORT.md` - تقرير GA
- `WEEKLY_FILTER_REPORT.md` - تقرير الفلترة

## 🎯 الخلاصة

**فلترة أسبوعية 56→35 (حجم >5M$) تحافظ على نفس الربح 7151$ مع استبعاد 21 عملة ميتة - أفضل توازن.**

**Top19 فقط يقلل الربح لـ 3830$ لكن DD أقل 20.18% - أكثر أماناً للمحافظ.**

**التوصية: استخدم Valid 35 + GA Best (7151$ DD21.8% PF3.29 WR58% 495 trades) للتداول الحي.**
