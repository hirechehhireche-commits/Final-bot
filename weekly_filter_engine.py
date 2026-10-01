"""
Weekly Filter Engine - فلترة أسبوعية: اختيار أفضل 19 من 56 عملة

القواعد:
1. كل أسبوع احسب: سيولة + حجم + تقلب لكل 56 عملة
2. اختر أفضل 19 حسب Score
3. استبعد عملة إذا حجمها <5M$ يومياً لمدة 3 أيام
4. أضف عملة جديدة إذا انفجرت (مثلاً PEPE حجم 100M$)
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# العملات الـ 56 الأصلية
ORIGINAL_56 = [
    'ADAUSDT', 'ALGOUSDT', 'APTUSDT', 'ARBUSDT', 'ARUSDT', 'AVAXUSDT', 
    'BCHUSDT', 'BNBUSDT', 'BTCUSDT', 'CELRUSDT', 'CHRUSDT', 'CTSIUSDT', 
    'DOGEUSDT', 'DOTUSDT', 'EGLDUSDT', 'EOSUSDT', 'ETCUSDT', 'ETHUSDT', 
    'FETUSDT', 'FILUSDT', 'GRTUSDT', 'HBARUSDT', 'ICPUSDT', 'IOTXUSDT', 
    'JASMYUSDT', 'KSMUSDT', 'LINKUSDT', 'LPTUSDT', 'LTCUSDT', 'OPUSDT', 
    'POLUSDT', 'PUNDIXUSDT', 'QTUMUSDT', 'RENDERUSDT', 'ROSEUSDT', 'RSRUSDT', 
    'RVNUSDT', 'SANDUSDT', 'SFPUSDT', 'SKLUSDT', 'SLPUSDT', 'SOLUSDT', 
    'STRAXUSDT', 'STXUSDT', 'SUIUSDT', 'SUSDT', 'TAOUSDT', 'TLMUSDT', 
    'TRXUSDT', 'VETUSDT', 'VTHOUSDT', 'WLDUSDT', 'XLMUSDT', 'XRPUSDT', 
    'ZECUSDT', 'ZROUSDT'
]

# عملات جديدة محتملة للانفجار
EXPLOSIVE_CANDIDATES = [
    'PEPEUSDT', 'BONKUSDT', 'WIFUSDT', 'FLOKIUSDT', 'SHIBUSDT',
    '1000PEPEUSDT', '1000BONKUSDT', 'ORDIUSDT', 'SEIUSDT', 'TIAUSDT'
]

class WeeklyFilterEngine:
    def __init__(self, store: Dict, min_daily_volume: float = 5_000_000, explosive_volume: float = 100_000_000):
        """
        store: dict of {symbol: DataFrame with OHLCV}
        min_daily_volume: 5M$ - استبعاد إذا أقل لمدة 3 أيام
        explosive_volume: 100M$ - إضافة إذا انفجر
        """
        self.store = store
        self.min_daily_volume = min_daily_volume
        self.explosive_volume = explosive_volume
        self.weekly_selection_history = []  # [(week_start, selected_19, scores)]
        self.excluded_coins = set()
        self.exclusion_reasons = {}  # {symbol: reason}
        self.volume_history = {sym: [] for sym in store.keys()}  # last 3 days volume
        
    def calculate_weekly_metrics(self, symbol: str, end_idx: int = -1, lookback_days: int = 7) -> Dict:
        """
        احسب مقاييس أسبوعية لعملة واحدة
        """
        if symbol not in self.store:
            return None
        
        df = self.store[symbol]
        if len(df) < lookback_days * 6:  # 6 bars per day (4H)
            return None
        
        # آخر 7 أيام = 42 شمعة 4H
        lookback_bars = lookback_days * 6
        recent = df.iloc[end_idx - lookback_bars + 1:end_idx + 1] if end_idx != -1 else df.tail(lookback_bars)
        
        if len(recent) < lookback_bars * 0.8:
            return None
        
        try:
            # 1. الحجم اليومي المتوسط
            # Volume في DataFrame هو volume بالعملة، نحتاج تحويل لـ USDT
            avg_close = recent['Close'].mean()
            avg_vol_coin = recent['Volume'].mean()
            daily_vol_usdt = avg_vol_coin * avg_close * 6  # 6 شمعات 4H = يوم
            
            # حجم آخر 3 أيام منفصلة
            last_3_days_vol = []
            for i in range(3):
                day_bars = recent.iloc[-(i+1)*6 : -i*6 if i>0 else None]
                if len(day_bars) > 0:
                    day_vol = day_bars['Volume'].mean() * day_bars['Close'].mean() * 6
                    last_3_days_vol.append(day_vol)
            
            # 2. السيولة (Liquidity) = متوسط (Close * Volume) * 6
            liquidity = (recent['Close'] * recent['Volume']).mean() * 6
            
            # 3. التقلب (Volatility) = ATR% + Std%
            high = recent['High'].values
            low = recent['Low'].values
            close = recent['Close'].values
            
            # ATR%
            tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
            tr = np.concatenate([[high[0]-low[0]], tr])
            atr = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
            atr_pct = (atr / close[-1] * 100) if close[-1] > 0 else 0
            
            # Std% (تقلب سعري)
            returns = np.diff(close) / close[:-1]
            std_pct = np.std(returns) * 100 * np.sqrt(6*24)  # annualized approx
            
            # 4. الاتجاه (Trend) = ROC 7 أيام
            roc_7d = (close[-1] / close[0] - 1) * 100 if close[0] > 0 else 0
            
            # 5. قوة الاتجاه = نسبة الشموع فوق EMA20
            ema20 = pd.Series(close).ewm(span=20).mean().values
            above_ema_pct = np.mean(close > ema20) * 100
            
            # 6. حجم التداول النسبي (Volume surge)
            vol_ma = recent['Volume'].rolling(20).mean().iloc[-1] if len(recent) >= 20 else recent['Volume'].mean()
            vol_surge = recent['Volume'].iloc[-1] / vol_ma if vol_ma > 0 else 1.0
            
            return {
                'symbol': symbol,
                'daily_vol_usdt': daily_vol_usdt,
                'last_3_days_vol': last_3_days_vol,
                'liquidity': liquidity,
                'atr_pct': atr_pct,
                'std_pct': std_pct,
                'volatility_score': (atr_pct + std_pct) / 2,  # متوسط التقلب
                'roc_7d': roc_7d,
                'above_ema_pct': above_ema_pct,
                'vol_surge': vol_surge,
                'close': close[-1],
                'avg_close': avg_close
            }
        except Exception as e:
            print(f"Error calculating metrics for {symbol}: {e}")
            return None
    
    def calculate_score(self, metrics: Dict) -> float:
        """
        احسب Score 0-100 لكل عملة
        - حجم 30 نقطة
        - سيولة 20 نقطة
        - تقلب معتدل 20 نقطة (لا عالي جداً ولا منخفض)
        - اتجاه 15 نقطة
        - قوة 15 نقطة
        """
        if not metrics:
            return 0
        
        # 1. حجم (30 نقطة) - أعلى حجم = أعلى نقاط
        # نحول الحجم لـ log scale لأن BTC 1B و ADA 40M فرق كبير
        vol = metrics['daily_vol_usdt']
        vol_score = min(30, np.log10(max(vol, 1e6) / 1e6) * 10)  # 1M=0, 10M=10, 100M=20, 1B=30
        
        # 2. سيولة (20 نقطة)
        liq = metrics['liquidity']
        liq_score = min(20, np.log10(max(liq, 1e6) / 1e6) * 6.6)
        
        # 3. تقلب معتدل (20 نقطة) - نريد تقلب 2-5% مثالي، لا 0.5% ولا 10%
        vol_pct = metrics['volatility_score']
        if 2.0 <= vol_pct <= 5.0:
            volatility_score = 20
        elif 1.0 <= vol_pct <= 7.0:
            volatility_score = 15
        elif 0.5 <= vol_pct <= 10.0:
            volatility_score = 10
        else:
            volatility_score = 5
        
        # 4. اتجاه (15 نقطة) - نريد صاعد 2-15%
        roc = metrics['roc_7d']
        if 2 <= roc <= 15:
            trend_score = 15
        elif 0 <= roc <= 25:
            trend_score = 10
        elif -5 <= roc <= 30:
            trend_score = 5
        else:
            trend_score = 0
        
        # 5. قوة (15 نقطة) - نسبة فوق EMA20
        above_ema = metrics['above_ema_pct']
        strength_score = above_ema * 0.15  # 100% = 15 نقطة
        
        total = vol_score + liq_score + volatility_score + trend_score + strength_score
        return total
    
    def check_exclusion(self, symbol: str, metrics: Dict) -> Tuple[bool, str]:
        """
        تحقق هل يجب استبعاد العملة؟
        القاعدة: حجم <5M$ يومياً لمدة 3 أيام
        """
        if not metrics or not metrics['last_3_days_vol']:
            return False, ""
        
        last_3 = metrics['last_3_days_vol']
        if len(last_3) < 3:
            return False, ""
        
        # إذا كل 3 أيام <5M$
        if all(v < self.min_daily_volume for v in last_3):
            return True, f"حجم <${self.min_daily_volume/1e6:.1f}M لمدة 3 أيام: {[f'${v/1e6:.1f}M' for v in last_3]}"
        
        return False, ""
    
    def check_explosive(self, symbol: str, metrics: Dict) -> Tuple[bool, str]:
        """
        تحقق هل العملة انفجرت ويجب إضافتها؟
        القاعدة: حجم >100M$ (انفجار)
        """
        if not metrics:
            return False, ""
        
        daily_vol = metrics['daily_vol_usdt']
        vol_surge = metrics['vol_surge']
        
        # حجم >100M$ و surge >2x
        if daily_vol > self.explosive_volume and vol_surge > 2.0:
            return True, f"انفجار حجم ${daily_vol/1e6:.1f}M (surge {vol_surge:.1f}x) > ${self.explosive_volume/1e6:.0f}M"
        
        return False, ""
    
    def select_weekly_top19(self, week_end_idx: int = -1) -> List[Dict]:
        """
        كل أسبوع: اختر أفضل 19 عملة
        """
        all_metrics = []
        excluded_this_week = []
        explosive_this_week = []
        
        for symbol in self.store.keys():
            metrics = self.calculate_weekly_metrics(symbol, end_idx=week_end_idx)
            if not metrics:
                continue
            
            # تحقق استبعاد
            should_exclude, reason = self.check_exclusion(symbol, metrics)
            if should_exclude:
                self.excluded_coins.add(symbol)
                self.exclusion_reasons[symbol] = reason
                excluded_this_week.append((symbol, reason, metrics['daily_vol_usdt']))
                continue
            
            # إذا كانت مستبعدة سابقاً لكن حجمها تحسن، أعدها
            if symbol in self.excluded_coins:
                if metrics['daily_vol_usdt'] > self.min_daily_volume * 1.5:
                    self.excluded_coins.remove(symbol)
                    if symbol in self.exclusion_reasons:
                        del self.exclusion_reasons[symbol]
                else:
                    continue
            
            # احسب Score
            score = self.calculate_score(metrics)
            metrics['score'] = score
            
            # تحقق انفجار
            is_explosive, exp_reason = self.check_explosive(symbol, metrics)
            if is_explosive:
                explosive_this_week.append((symbol, exp_reason, metrics['daily_vol_usdt']))
                # Bonus score للانفجارية
                metrics['score'] += 15
                metrics['is_explosive'] = True
            else:
                metrics['is_explosive'] = False
            
            all_metrics.append(metrics)
        
        # رتب حسب Score
        all_metrics.sort(key=lambda x: x['score'], reverse=True)
        
        # اختر أفضل 19
        top19 = all_metrics[:19]
        rest = all_metrics[19:]
        
        # احفظ التاريخ
        week_start = datetime.now() - timedelta(days=7)  # placeholder
        self.weekly_selection_history.append({
            'week_end_idx': week_end_idx,
            'top19': top19,
            'rest': rest,
            'excluded': excluded_this_week,
            'explosive': explosive_this_week,
            'timestamp': datetime.now()
        })
        
        return top19, rest, excluded_this_week, explosive_this_week
    
    def get_current_19(self) -> List[str]:
        """احصل على أفضل 19 حالياً"""
        if not self.weekly_selection_history:
            top19, _, _, _ = self.select_weekly_top19()
        else:
            top19 = self.weekly_selection_history[-1]['top19']
        
        return [m['symbol'] for m in top19]
    
    def print_weekly_report(self, top19: List[Dict], rest: List[Dict], excluded: List, explosive: List):
        """اطبع تقرير أسبوعي"""
        print("\n" + "="*100)
        print(f"📊 تقرير الفلترة الأسبوعية - {datetime.now().strftime('%Y-%m-%d')}")
        print("="*100)
        
        print(f"\n🏆 أفضل 19 عملة (من {len(top19)+len(rest)} عملة):")
        print(f"{'Rank':<4} {'Symbol':<12} {'Score':<6} {'Vol/Day':<10} {'Liquidity':<12} {'ATR%':<6} {'ROC7d':<7} {'Explosive':<10}")
        print("-"*100)
        for i, m in enumerate(top19, 1):
            exp_flag = "🔥" if m.get('is_explosive') else ""
            print(f"{i:<4} {m['symbol']:<12} {m['score']:<6.1f} ${m['daily_vol_usdt']/1e6:<8.1f}M ${m['liquidity']/1e6:<10.1f}M {m['atr_pct']:<6.2f} {m['roc_7d']:<6.1f}% {exp_flag:<10}")
        
        print(f"\n📉 باقي العملات (37 عملة):")
        for i, m in enumerate(rest[:10], 20):  # أول 10 من الباقي
            print(f"{i:<4} {m['symbol']:<12} {m['score']:<6.1f} ${m['daily_vol_usdt']/1e6:<8.1f}M")
        if len(rest) > 10:
            print(f"... و {len(rest)-10} عملة أخرى")
        
        if excluded:
            print(f"\n❌ عملات مستبعدة (حجم <${self.min_daily_volume/1e6:.0f}M لـ 3 أيام): {len(excluded)}")
            for sym, reason, vol in excluded[:10]:
                print(f"  - {sym}: {reason}")
        
        if explosive:
            print(f"\n🔥 عملات انفجرت (حجم >${self.explosive_volume/1e6:.0f}M): {len(explosive)}")
            for sym, reason, vol in explosive:
                print(f"  - {sym}: {reason}")
        
        print(f"\n📊 الإحصائيات:")
        print(f"  - إجمالي العملات المحللة: {len(top19)+len(rest)+len(excluded)}")
        print(f"  - مختارة: {len(top19)}")
        print(f"  - مستبعدة: {len(excluded)}")
        print(f"  - منفجرة: {len(explosive)}")
        print("="*100)


def test_weekly_filter():
    """اختبار الفلترة الأسبوعية"""
    import pickle
    print("📦 تحميل بيانات 56 عملة...")
    with open('/home/user/clean_titan_bot/titans_4h_5y_cache.pkl','rb') as f:
        store = pickle.load(f)
    
    print(f"✅ {len(store)} عملة محملة")
    
    engine = WeeklyFilterEngine(store, min_daily_volume=5_000_000, explosive_volume=100_000_000)
    
    print("\n🔍 تشغيل الفلترة الأسبوعية...")
    top19, rest, excluded, explosive = engine.select_weekly_top19()
    
    engine.print_weekly_report(top19, rest, excluded, explosive)
    
    # حفظ النتائج
    result = {
        'top19_symbols': [m['symbol'] for m in top19],
        'top19_metrics': top19,
        'excluded': excluded,
        'explosive': explosive,
        'timestamp': datetime.now().isoformat()
    }
    
    with open('/tmp/weekly_top19.pkl','wb') as f:
        pickle.dump(result, f)
    
    with open('/tmp/weekly_top19.json','w') as f:
        import json
        json.dump({
            'top19': [m['symbol'] for m in top19],
            'top19_with_scores': [{k: v for k,v in m.items() if k in ['symbol','score','daily_vol_usdt','liquidity','atr_pct','roc_7d','is_explosive']} for m in top19],
            'excluded': [{'symbol': sym, 'reason': reason} for sym, reason, vol in excluded],
            'explosive': [{'symbol': sym, 'reason': reason} for sym, reason, vol in explosive]
        }, f, indent=2, default=str)
    
    print(f"\n💾 تم حفظ النتائج:")
    print(f"  - /tmp/weekly_top19.pkl")
    print(f"  - /tmp/weekly_top19.json")
    print(f"\n🏆 أفضل 19: {[m['symbol'] for m in top19]}")
    
    return top19, rest, excluded, explosive

if __name__ == "__main__":
    test_weekly_filter()
