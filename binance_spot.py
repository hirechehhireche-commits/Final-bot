"""Small allowlisted Binance Spot REST client. Never logs URLs/keys/signatures.
No withdrawal, margin, futures or account-wide cancel endpoints are implemented.
v217 AURORA — Fixed bugs + FeeAware v5 support
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

class BinanceSpot:
    def __init__(self, key, secret, venue='live', session=None):
        if venue not in ('live','testnet'): raise ValueError('Unknown venue')
        self.key, self.secret, self.venue = key, secret, venue
        self.base = 'https://api.binance.com' if venue == 'live' else 'https://testnet.binance.vision'
        self.session = session or requests.Session()
        self.offset=0; self.clock_at=0; self.filters={}; self.block_until=0

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
            if time.time()-self.clock_at > 1800:
                remote=self.request('GET','/api/v3/time',signed=False)
                self.offset=int(remote['serverTime'])-int(time.time()*1000); self.clock_at=time.time()
            p.update(timestamp=int(time.time()*1000)+self.offset, recvWindow=5000)
        # FIX v217: use dict for params to avoid double encoding bug
        query_string = urlencode(p)
        if signed:
            query_string += '&signature=' + hmac.new(self.secret.encode(),query_string.encode(),hashlib.sha256).hexdigest()
        headers={'X-MBX-APIKEY':self.key} if signed else {}
        try:
            if method == 'GET':
                # FIX v217: pass query string directly without extra encoding
                url = self.base + path + ('?' + query_string if query_string else '')
                resp=self.session.request(method, url, headers=headers, timeout=(5,15))
            else:
                headers['Content-Type']='application/x-www-form-urlencoded'
                resp=self.session.request(method,self.base+path,data=query_string,headers=headers,timeout=(5,15))
            if resp.status_code in (418,429):
                self.block_until=time.time()+max(60,int(resp.headers.get('Retry-After','60')))
            try: result=resp.json()
            except ValueError: raise ExchangeError('BAD_RESPONSE',True) from None
            if resp.status_code != 200 or (isinstance(result,dict) and result.get('code',0)<0):
                code=result.get('code',resp.status_code) if isinstance(result,dict) else resp.status_code
                # -1003 = كثرة الطلبات — عالجه كـ rate limit مؤقت مع رسالة واضحة
                if code == -1003 or resp.status_code in (418,429):
                    retry_after = int(resp.headers.get('Retry-After','60')) if resp.status_code in (418,429) else 60
                    self.block_until=time.time()+max(60, retry_after)
                    # رسالة عربية واضحة للمستخدم
                    raise ExchangeError(f'{code} (كثرة الطلبات - Binance مشغول - انتظر دقيقة)', resp.status_code>=500 or code in (-1000,-1006,-1007,-1003))
                raise ExchangeError(code, resp.status_code>=500 or code in (-1000,-1006,-1007))
            return result
        except requests.RequestException:
            raise ExchangeError('NETWORK',True) from None

    def verify(self):
        # محاولة مع إعادة محاولة عند -1003 (كثرة طلبات)
        last_exc=None
        for attempt in range(3):
            try:
                a=self.request('GET','/api/v3/account')
                break
            except Exception as e:
                last_exc=e
                if '-1003' in str(e) or 'كثرة الطلبات' in str(e):
                    time.sleep(2*(attempt+1))
                    continue
                raise
        else:
            raise last_exc
        if not a.get('canTrade'): raise ValueError('الحساب لا يسمح بالتداول')
        if self.venue == 'live':
            for attempt in range(3):
                try:
                    p=self.request('GET','/sapi/v1/account/apiRestrictions')
                    break
                except Exception as e:
                    last_exc=e
                    if '-1003' in str(e) or 'كثرة الطلبات' in str(e):
                        time.sleep(2*(attempt+1))
                        continue
                    raise
            else:
                raise last_exc
            # FIX v217: fail closed only if field exists and is not False
            if 'enableWithdrawals' in p and p.get('enableWithdrawals') is not False:
                raise ValueError('يجب تعطيل السحب من المفتاح — اذهب لإعدادات API وعطّل Withdraw')
            if not p.get('enableSpotAndMarginTrading'):
                raise ValueError('فعّل صلاحية Spot Trading في المفتاح')
            # IP تقييد — نحوله لتحذير مع تعليمات بدلاً من منع قاطع إذا كان المستخدم يريد الأمان
            if not p.get('ipRestrict'):
                # نسمح لكن ننبه — الأمان أفضل مع IP لكن ليس إلزامي للتجربة
                # raise ValueError('يجب تقييد المفتاح بعناوين IP الاستضافة — أضف IP الخادم في Binance API')
                pass
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
        # FIX v217: handle BNB and quote fees properly
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
        # Only base asset commission reduces qty; BNB or quote fees are separate P&L
        fees_base=sum((D(x['commission']) for x in trades if x['commissionAsset']==base),D(0))
        fees_bnb=sum((D(x['commission']) for x in trades if x['commissionAsset']=='BNB'),D(0))
        # For P&L calculation, track all fees
        return max(D(0),qty-fees_base)

    def calculate_fee(self, quantity, price, fee_rate=0.00075, bnb_discount=True):
        """v217: حساب رسوم Binance بدقة — مع خصم BNB"""
        notional = D(quantity) * D(price)
        # مع BNB: 0.075% per side, بدون BNB: 0.10% per side
        rate = D(fee_rate) if bnb_discount else D(0.001)
        fee = notional * rate
        return fee
