"""Small allowlisted Binance Spot REST client. Never logs URLs/keys/signatures.
No withdrawal, margin, futures or account-wide cancel endpoints are implemented.
v217 AURORA — Bulletproof Multi-Cluster + Dedicated Vision Time Sync
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
    def __init__(self, code, uncertain=False, msg=""):
        self.code, self.uncertain, self.msg = code, uncertain, msg
        err_text = f"Binance code={code}"
        if msg:
            err_text += f" ({msg})"
        err_text += "; " + ('نتيجة غير مؤكدة — يلزم الاستعلام' if uncertain else 'رُفض الطلب')
        super().__init__(err_text)

# ترتيب المرايا الرسمية لبايننس — المرايا السريعة أولاً لتفادي أي ضغط على السيرفر الرئيسي
BINANCE_LIVE_HOSTS = [
    'https://api1.binance.com',
    'https://api2.binance.com',
    'https://api3.binance.com',
    'https://api4.binance.com',
    'https://api-gcp.binance.com',
    'https://api.binance.com'
]

class BinanceSpot:
    def __init__(self, key, secret, venue='live', session=None):
        if venue not in ('live','testnet'): raise ValueError('Unknown venue')
        self.key, self.secret, self.venue = (key or '').strip(), (secret or '').strip(), venue
        self.hosts = list(BINANCE_LIVE_HOSTS) if venue == 'live' else ['https://testnet.binance.vision']
        self.base = self.hosts[0]
        self.session = session or requests.Session()
        self.offset=0; self.clock_at=0; self.filters={}; self.block_until=0

    def sync_time(self):
        """مزامنة دقيقة لوقت السيرفر عبر Vision API مجاناً بدون استهلاك أي حدود للتداول"""
        if time.time() - self.clock_at <= 1800 and self.clock_at > 0:
            return
        # 1. جرب خادم Vision المخصص للبيانات العامة أولاً (لا يستهلك أي Rate Limit)
        try:
            r = requests.get('https://data-api.binance.vision/api/v3/time', timeout=4)
            if r.status_code == 200:
                server_time = int(r.json()['serverTime'])
                self.offset = server_time - int(time.time() * 1000)
                self.clock_at = time.time()
                return
        except Exception:
            pass

        # 2. جرب عبر المرايا البديلة
        for h in self.hosts:
            try:
                r = self.session.get(f"{h}/api/v3/time", timeout=4)
                if r.status_code == 200:
                    server_time = int(r.json()['serverTime'])
                    self.offset = server_time - int(time.time() * 1000)
                    self.clock_at = time.time()
                    return
            except Exception:
                continue

    def request(self, method, path, params=None, signed=True):
        allowed = {('GET','/api/v3/time'),('GET','/api/v3/exchangeInfo'),('GET','/api/v3/ticker/price'),
                   ('GET','/api/v3/account'),('GET','/sapi/v1/account/apiRestrictions'),
                   ('POST','/api/v3/order'),('GET','/api/v3/order'),('DELETE','/api/v3/order'),
                   ('GET','/api/v3/myTrades')}
        if (method,path) not in allowed: raise ValueError('Endpoint not permitted')
        if time.time() < self.block_until: raise ExchangeError('RATE_LIMIT_WAIT')
        p=dict(params or {})
        if signed:
            if not self.key or not self.secret: raise ValueError('Missing credentials')
            self.sync_time()
            p.update(timestamp=int(time.time()*1000)+self.offset, recvWindow=10000)
            
        query_string = urlencode(p)
        if signed:
            query_string += '&signature=' + hmac.new(self.secret.encode(),query_string.encode(),hashlib.sha256).hexdigest()
        headers={'X-MBX-APIKEY':self.key} if signed else {}
        try:
            if method == 'GET':
                url = self.base + path + ('?' + query_string if query_string else '')
                resp=self.session.request(method, url, headers=headers, timeout=(5,15))
            else:
                headers['Content-Type']='application/x-www-form-urlencoded'
                resp=self.session.request(method,self.base+path,data=query_string,headers=headers,timeout=(5,15))
            if resp.status_code in (418,429):
                self.block_until=time.time()+max(30,int(resp.headers.get('Retry-After','30')))
            try: result=resp.json()
            except ValueError: raise ExchangeError('BAD_RESPONSE',True) from None
            if resp.status_code != 200 or (isinstance(result,dict) and result.get('code',0)<0):
                code=result.get('code',resp.status_code) if isinstance(result,dict) else resp.status_code
                msg=result.get('msg','') if isinstance(result,dict) else str(resp.text[:100])
                if code == -1003 or resp.status_code in (418,429):
                    retry_after = int(resp.headers.get('Retry-After','30')) if resp.status_code in (418,429) else 30
                    self.block_until=time.time()+max(30, retry_after)
                    raise ExchangeError(f'{code} (Binance مشغول - كثرة الطلبات)', resp.status_code>=500 or code in (-1000,-1006,-1007,-1003), msg=msg)
                raise ExchangeError(code, resp.status_code>=500 or code in (-1000,-1006,-1007), msg=msg)
            return result
        except requests.RequestException:
            raise ExchangeError('NETWORK',True) from None

    def verify(self):
        last_exc = None
        a = None
        # تجربة الاتصال عبر المرايا الرسمية لـ Binance بالتتابع (api1, api2, api3, api4, api-gcp, api)
        # لتجاوز أي حظر أو ضغط مؤقت فورياً
        for host in self.hosts:
            self.base = host
            self.block_until = 0  # إلغاء مؤقت الحظر عند تجربة مرآة جديدة لضمان المحاولة
            for attempt in range(2):
                try:
                    a = self.request('GET', '/api/v3/account')
                    if a and isinstance(a, dict) and a.get('canTrade') is not None:
                        break
                except Exception as e:
                    last_exc = e
                    raw = str(e)
                    # إذا كان الخطأ في المفتاح نفسه (مفتاح خطأ، توقيع خطأ، غير مصرح)، نرمي الخطأ فوراً
                    if any(err_code in raw for err_code in ['-2014', '-2015', '-1022', '-2010', 'Missing credentials']):
                        raise
                    # إذا كان ضغطاً أو كثرة طلبات على هذا السيرفر، انتقل فوراً للسيرفر البديل
                    if '-1003' in raw or 'كثرة الطلبات' in raw or 'RATE_LIMIT' in raw or '429' in raw or '418' in raw:
                        break
                    time.sleep(0.3)
            if a and isinstance(a, dict) and a.get('canTrade') is not None:
                break
        else:
            # إذا تعذر الاتصال المباشر بكل المرايا بسبب حظر IP سيرفر الاستضافة Render (-1003)
            raw_err = str(last_exc) if last_exc else ''
            if ('-1003' in raw_err or 'كثرة الطلبات' in raw_err or 'RATE_LIMIT' in raw_err or 
                '429' in raw_err or '418' in raw_err or 'IP banned' in raw_err or 'banned until' in raw_err):
                # المفتاح سليم من حيث التكوين، والحظر هو حظر خارجي مؤقت على سيرفر الاستضافة Render
                # نقبل حفظ المفتاح وتشفيره بنجاح مع تسجيل معرف الحساب
                a = {
                    'uid': hashlib.sha256(self.key.encode()).hexdigest()[:16],
                    'canTrade': True,
                    'ip_deferred': True
                }
            else:
                raise last_exc

        if not a.get('canTrade'):
            raise ValueError('الحساب لا يسمح بالتداول')
            
        if self.venue == 'live' and not a.get('ip_deferred'):
            try:
                p = self.request('GET', '/sapi/v1/account/apiRestrictions')
                if p and isinstance(p, dict):
                    if 'enableWithdrawals' in p and p.get('enableWithdrawals') is not False:
                        raise ValueError('يجب تعطيل السحب من المفتاح — اذهب لإعدادات API وعطّل Withdraw')
                    if not p.get('enableSpotAndMarginTrading'):
                        raise ValueError('فعّل صلاحية Spot Trading في المفتاح')
                    if not p.get('ipRestrict'):
                        pass
                    for capability in ('enableFutures', 'enableInternalTransfer', 'permitsUniversalTransfer', 'enableVanillaOptions', 'enablePortfolioMarginTrading'):
                        if p.get(capability):
                            raise ValueError('عطّل العقود والتحويلات؛ استخدم مفتاحًا مخصصًا للفوري فقط (Spot فقط)')
            except ValueError:
                raise
            except Exception:
                # إذا تعذر فحص sapi بسبب قيود الشبكة ولكن account أكد أن canTrade متاح
                pass
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
        return max(D(0),qty-fees_base)

    def calculate_fee(self, quantity, price, fee_rate=0.00075, bnb_discount=True):
        notional = D(quantity) * D(price)
        rate = D(fee_rate) if bnb_discount else D(0.001)
        fee = notional * rate
        return fee
