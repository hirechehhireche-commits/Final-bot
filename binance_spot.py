"""Small allowlisted Binance Spot REST client. Never logs URLs/keys/signatures.
No withdrawal, margin, futures or account-wide cancel endpoints are implemented.
v242 — Multi-Mirror Failover + Smart Rate Limit Shield + Robust Verify
"""
import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode
import requests

D = lambda x: Decimal(str(x))

def dec(x):
    return format(D(x), 'f')

def floor_step(value, step):
    value, step = D(value), D(step)
    if step <= 0: raise ValueError('Invalid exchange step')
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

class ExchangeError(Exception):
    def __init__(self, code, uncertain=False):
        self.code, self.uncertain = code, uncertain
        super().__init__(f'Binance code={code}; ' + ('نتيجة غير مؤكدة — يلزم الاستعلام' if uncertain else 'رُفض الطلب'))

BINANCE_LIVE_MIRRORS = [
    'https://api.binance.com',
    'https://api1.binance.com',
    'https://api2.binance.com',
    'https://api3.binance.com'
]

class BinanceSpot:
    def __init__(self, key, secret, venue='live', session=None):
        if venue not in ('live','testnet'): raise ValueError('Unknown venue')
        self.key, self.secret, self.venue = key, secret, venue
        if venue == 'live':
            self.bases = list(BINANCE_LIVE_MIRRORS)
        else:
            self.bases = ['https://testnet.binance.vision']
        self.base_idx = 0
        self.session = session or requests.Session()
        self.offset = 0
        self.clock_at = 0
        self.filters = {}
        self.mirror_blocks = {b: 0.0 for b in self.bases}

    @property
    def base(self):
        return self.bases[self.base_idx]

    @base.setter
    def base(self, val):
        if val and val not in self.bases:
            self.bases.insert(0, val)
        if val in self.bases:
            self.base_idx = self.bases.index(val)

    def request(self, method, path, params=None, signed=True):
        allowed = {
            ('GET','/api/v3/time'), ('GET','/api/v3/exchangeInfo'), ('GET','/api/v3/ticker/price'),
            ('GET','/api/v3/account'), ('GET','/sapi/v1/account/apiRestrictions'),
            ('POST','/api/v3/order'), ('GET','/api/v3/order'), ('DELETE','/api/v3/order'),
            ('GET','/api/v3/myTrades')
        }
        if (method,path) not in allowed: raise ValueError('Endpoint not permitted')
        
        p = dict(params or {})
        if signed:
            if not self.key or not self.secret: raise ValueError('Missing credentials')
            if time.time() - self.clock_at > 1800:
                try:
                    remote = self.request('GET', '/api/v3/time', signed=False)
                    self.offset = int(remote['serverTime']) - int(time.time() * 1000)
                    self.clock_at = time.time()
                except Exception:
                    pass
            p.update(timestamp=int(time.time() * 1000) + self.offset, recvWindow=60000)

        query_string = urlencode(p)
        if signed:
            query_string += '&signature=' + hmac.new(self.secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
        
        headers = {'X-MBX-APIKEY': self.key} if signed else {}
        if method != 'GET':
            headers['Content-Type'] = 'application/x-www-form-urlencoded'

        now = time.time()
        # ترتيب المرايا: نبدأ بالمرآة الحالية ثم باقي المرايا المتاحة غير المحظورة
        candidate_mirrors = []
        for i in range(len(self.bases)):
            m = self.bases[(self.base_idx + i) % len(self.bases)]
            if now >= self.mirror_blocks.get(m, 0.0):
                candidate_mirrors.append(m)

        # إذا كانت كل المرايا معاقبة مؤقتاً، نختار أقلها وقتاً للانتظار
        if not candidate_mirrors:
            fastest = min(self.bases, key=lambda m: self.mirror_blocks.get(m, 0.0))
            wait_s = self.mirror_blocks.get(fastest, 0.0) - now
            if wait_s > 10.0:
                raise ExchangeError('-1003 (كثرة الطلبات - جميع سيرفرات Binance مشغولة مؤقتاً)', True)
            if wait_s > 0:
                time.sleep(wait_s)
            candidate_mirrors = [fastest]

        last_err = None
        for mirror in candidate_mirrors:
            try:
                if method == 'GET':
                    url = mirror + path + ('?' + query_string if query_string else '')
                    resp = self.session.request(method, url, headers=headers, timeout=(4, 12))
                else:
                    resp = self.session.request(method, mirror + path, data=query_string, headers=headers, timeout=(4, 12))
            except requests.RequestException as e:
                self.mirror_blocks[mirror] = time.time() + 10.0
                last_err = ExchangeError('NETWORK', True)
                continue

            # استجابة ضغط أو حظر معدل الطلبات 429 أو 418
            if resp.status_code in (418, 429):
                retry_after = max(30, int(resp.headers.get('Retry-After', '30')))
                self.mirror_blocks[mirror] = time.time() + retry_after
                last_err = ExchangeError(f'{resp.status_code} (كثرة الطلبات)', True)
                continue

            try:
                result = resp.json()
            except ValueError:
                last_err = ExchangeError('BAD_RESPONSE', True)
                continue

            # فحص أكواد بايننس في الـ JSON
            if isinstance(result, dict) and result.get('code', 0) < 0:
                code = result.get('code')
                if code == -1003:  # Too many requests
                    self.mirror_blocks[mirror] = time.time() + 45.0
                    last_err = ExchangeError(f'{code} (كثرة الطلبات - سيرفر مشغول)', True)
                    continue
                if code == -1021:  # Timestamp outside recvWindow
                    self.clock_at = 0
                    continue
                # خطأ حقيقي في المعاملات أو الصلاحيات
                raise ExchangeError(code, resp.status_code >= 500 or code in (-1000, -1006, -1007))

            if resp.status_code == 200:
                # نجاح تام! تثبيت المرآة الحالية
                self.base_idx = self.bases.index(mirror)
                return result
            else:
                last_err = ExchangeError(resp.status_code, False)

        if last_err:
            raise last_err
        raise ExchangeError('NO_RESPONSE', True)

    def verify(self):
        """فحص مرن ومحمي لمفتاح وتصاريح الحساب عبر المرايا المتعددة"""
        last_exc = None
        a = None
        # فحص الحساب عبر /api/v3/account مع محاولات ذكية
        for attempt in range(4):
            try:
                a = self.request('GET', '/api/v3/account')
                if isinstance(a, dict) and 'canTrade' in a:
                    break
            except Exception as e:
                last_exc = e
                err_s = str(e)
                # إذا كانت المفاتيح خاطئة صراحة لا نكرر بلا جدوى
                if any(bad in err_s for bad in ('-2014', '-2015', 'credentials')):
                    raise ValueError('مفتاح API أو Secret غير صحيح، أو تم تقييد الـ IP في Binance.')
                if '-1003' in err_s or 'كثرة الطلبات' in err_s or 'RATE_LIMIT' in err_s or 'NETWORK' in err_s:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise
        else:
            if last_exc:
                raise last_exc
            raise ValueError('تعذر استلام رد من Binance')

        if not a.get('canTrade'):
            raise ValueError('الحساب لا يسمح بالتداول الفوري (Spot)')

        # فحص الصلاحيات المتقدمة في نمط live
        if self.venue == 'live':
            p = None
            for attempt in range(3):
                try:
                    p = self.request('GET', '/sapi/v1/account/apiRestrictions')
                    if isinstance(p, dict):
                        break
                except Exception as e:
                    err_s = str(e)
                    if '-1003' in err_s or 'كثرة الطلبات' in err_s or 'RATE_LIMIT' in err_s:
                        time.sleep(1.0)
                        continue
                    # إذا تعذر sapi ولكن account أكد canTrade، نسمح بالمرور
                    break

            if isinstance(p, dict):
                if 'enableWithdrawals' in p and p.get('enableWithdrawals') is not False:
                    raise ValueError('يجب تعطيل السحب من المفتاح — اذهب لإعدادات API وعطّل Withdraw')
                if not p.get('enableSpotAndMarginTrading', True):
                    raise ValueError('فعّل صلاحية Spot Trading في المفتاح')
                for capability in ('enableFutures','enableInternalTransfer','permitsUniversalTransfer','enableVanillaOptions','enablePortfolioMarginTrading'):
                    if p.get(capability):
                        raise ValueError('عطّل العقود والتحويلات؛ استخدم مفتاحًا مخصصًا للفوري فقط (Spot فقط)')

        return a

    def balances(self):
        return {x['asset']:D(x['free']) for x in self.request('GET','/api/v3/account')['balances']}

    def price(self,symbol):
        return D(self.request('GET','/api/v3/ticker/price',{'symbol':symbol},False)['price'])

    def rules(self,symbol):
        if symbol not in self.filters or time.time()-self.filters[symbol][0]>3600:
            info=self.request('GET','/api/v3/exchangeInfo',{'symbol':symbol},False)['symbols'][0]
            if info.get('status') != 'TRADING' or not info.get('isSpotTradingAllowed',False):
                raise ValueError('الزوج غير متاح للتداول الفوري')
            if 'STOP_LOSS' not in info.get('orderTypes',[]):
                raise ValueError('الزوج لا يدعم STOP_LOSS السوقي؛ تم منع الدخول')
            fs={f['filterType']:f for f in info['filters']}
            self.filters[symbol]=(time.time(),dict(info=info, filters=fs))
        return self.filters[symbol][1]

    def quantity(self,symbol,quantity,price,market=False,require_min=True):
        rule=self.rules(symbol); fs=rule['filters']; lot=fs['LOT_SIZE']
        q=floor_step(quantity,lot['stepSize'])
        if market:
            ml=fs.get('MARKET_LOT_SIZE',{})
            if D(ml.get('stepSize',0))>0: q=floor_step(q,ml['stepSize'])
            if D(ml.get('maxQty',0))>0 and q>D(ml['maxQty']): raise ValueError('حجم أكبر من حد المنصة')
            if require_min and q<D(ml.get('minQty',0)): raise ValueError('الكمية أقل من الحد الأدنى السوقي')
        if q>D(lot['maxQty']) or (require_min and (q<D(lot['minQty']) or q<=0)):
            raise ValueError('الكمية خارج حدود Binance')
        notional=q*D(price)
        for key in ('MIN_NOTIONAL','NOTIONAL'):
            f=fs.get(key)
            if not f: continue
            applies=not market or f.get('applyToMarket',f.get('applyMinToMarket',True))
            if require_min and applies and notional<D(f['minNotional']): raise ValueError('قيمة الأمر أقل من الحد الأدنى')
            if D(f.get('maxNotional',0))>0 and (not market or f.get('applyMaxToMarket',True)) and notional>D(f['maxNotional']):
                raise ValueError('قيمة الأمر أعلى من الحد الأقصى')
        return q

    def price_tick(self,symbol,value):
        f=self.rules(symbol)['filters']['PRICE_FILTER']
        p=floor_step(value,f['tickSize'])
        if p<D(f['minPrice']) or (D(f['maxPrice'])>0 and p>D(f['maxPrice'])): raise ValueError('سعر خارج حدود Binance')
        return p

    def query(self,symbol,cid):
        try: return self.request('GET','/api/v3/order',{'symbol':symbol,'origClientOrderId':cid})
        except ExchangeError as e:
            if e.code == -2013: return None
            raise

    def cancel(self,symbol,cid):
        try: return self.request('DELETE','/api/v3/order',{'symbol':symbol,'origClientOrderId':cid})
        except ExchangeError:
            r=self.query(symbol,cid)
            if r is not None and r.get('status') in ('FILLED','CANCELED','EXPIRED','REJECTED','EXPIRED_IN_MATCH'):
                return r
            raise ExchangeError('CANCEL_UNCONFIRMED',True) from None

    def net_filled(self,symbol,order):
        qty=D(order['executedQty'])
        if qty<=0:return D(0)
        base=self.rules(symbol)['info']['baseAsset']
        quote=self.rules(symbol)['info']['quoteAsset']
        trades=[]; start=None
        while True:
            p={'symbol':symbol,'orderId':order['orderId'],'limit':1000}
            if start is not None:p['fromId']=start
            batch=self.request('GET','/api/v3/myTrades',p)
            trades.extend(x for x in batch if x['orderId']==order['orderId'])
            if len(batch)<1000:break
            start=batch[-1]['id']+1
        if sum((D(x['qty']) for x in trades),D(0)) < qty:
            raise ExchangeError('FILLS_NOT_YET_VISIBLE',True)
        fees_base=sum((D(x['commission']) for x in trades if x['commissionAsset']==base),D(0))
        fees_bnb=sum((D(x['commission']) for x in trades if x['commissionAsset']=='BNB'),D(0))
        return max(D(0),qty-fees_base)

    def calculate_fee(self, quantity, price, fee_rate=0.00075, bnb_discount=True):
        notional = D(quantity) * D(price)
        rate = D(fee_rate) if bnb_discount else D(0.001)
        fee = notional * rate
        return fee
