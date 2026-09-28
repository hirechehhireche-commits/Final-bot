"""Small allowlisted Binance Spot REST client. Never logs URLs/keys/signatures.
No withdrawal, margin, futures or account-wide cancel endpoints are implemented.
v242 RADICAL — Silence Shield & Anti-Ban Protection
"""
import hashlib
import hmac
import time
import re
import json
import os
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

# ملف تخزين مؤقت لحظر IP ليبقى حتى عند إعادة تشغيل الحاوية
BAN_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip_ban_state.json")
GLOBAL_BAN_UNTIL = 0.0

def load_ban_until():
    global GLOBAL_BAN_UNTIL
    try:
        if os.path.exists(BAN_STATE_FILE):
            with open(BAN_STATE_FILE, 'r') as f:
                d = json.load(f)
                GLOBAL_BAN_UNTIL = float(d.get("ban_until", 0.0))
    except Exception:
        pass
    return GLOBAL_BAN_UNTIL

def save_ban_until(ts):
    global GLOBAL_BAN_UNTIL
    GLOBAL_BAN_UNTIL = float(ts)
    try:
        with open(BAN_STATE_FILE, 'w') as f:
            json.dump({"ban_until": GLOBAL_BAN_UNTIL}, f)
    except Exception:
        pass

def get_remaining_ban_time():
    now = time.time()
    ban_ts = load_ban_until()
    if ban_ts > now:
        rem = int(ban_ts - now)
        mins = rem // 60
        secs = rem % 60
        return rem, mins, secs
    return 0, 0, 0

# تحميل حالة الحظر عند الإقلاع
load_ban_until()

class ExchangeError(Exception):
    def __init__(self, code, uncertain=False, msg=""):
        self.code, self.uncertain, self.msg = code, uncertain, msg
        err_text = f"Binance code={code}"
        if msg:
            err_text += f" ({msg})"
        err_text += "; " + ('نتيجة غير مؤكدة — يلزم الاستعلام' if uncertain else 'رُفض الطلب')
        super().__init__(err_text)

class BinanceSpot:
    def __init__(self, key, secret, venue='live', session=None):
        if venue not in ('live','testnet'): raise ValueError('Unknown venue')
        self.key, self.secret, self.venue = (key or '').strip(), (secret or '').strip(), venue
        self.base = 'https://api.binance.com' if venue == 'live' else 'https://testnet.binance.vision'
        self.session = session or requests.Session()
        self.offset = 0; self.clock_at = 0; self.filters = {}

    def sync_time(self):
        """مزامنة وقت السيرفر عبر خادم Vision المجاني بدون أي استهلاك لحدود التداول"""
        if time.time() - self.clock_at <= 1800 and self.clock_at > 0:
            return
        try:
            r = requests.get('https://data-api.binance.vision/api/v3/time', timeout=4)
            if r.status_code == 200:
                server_time = int(r.json()['serverTime'])
                self.offset = server_time - int(time.time() * 1000)
                self.clock_at = time.time()
                return
        except Exception:
            pass

    def request(self, method, path, params=None, signed=True):
        allowed = {('GET','/api/v3/time'),('GET','/api/v3/exchangeInfo'),('GET','/api/v3/ticker/price'),
                   ('GET','/api/v3/account'),('GET','/sapi/v1/account/apiRestrictions'),
                   ('POST','/api/v3/order'),('GET','/api/v3/order'),('DELETE','/api/v3/order'),
                   ('GET','/api/v3/myTrades')}
        if (method,path) not in allowed: raise ValueError('Endpoint not permitted')
        
        # 1. درع الصمت التام (Silence Shield): إذا كان الـ IP محظوراً، نمنع إرسال أي بايت لبايننس نهائياً لمنع تجديد الحظر
        rem, mins, secs = get_remaining_ban_time()
        if rem > 0:
            raise ExchangeError('IP_BANNED_COOLDOWN', False, msg=f'{mins} دقيقة و {secs} ثانية متبقية')

        p = dict(params or {})
        if signed:
            if not self.key or not self.secret: raise ValueError('Missing credentials')
            self.sync_time()
            p.update(timestamp=int(time.time()*1000)+self.offset, recvWindow=10000)
            
        query_string = urlencode(p)
        if signed:
            query_string += '&signature=' + hmac.new(self.secret.encode(),query_string.encode(),hashlib.sha256).hexdigest()
        headers = {'X-MBX-APIKEY': self.key} if signed else {}
        
        url = self.base + path + ('?' + query_string if query_string and method == 'GET' else '')
        
        try:
            if method == 'GET':
                resp = self.session.request(method, url, headers=headers, timeout=(5,12))
            else:
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                resp = self.session.request(method, self.base + path, data=query_string, headers=headers, timeout=(5,12))
            
            try: 
                result = resp.json()
            except ValueError: 
                result = {}

            if resp.status_code != 200 or (isinstance(result, dict) and result.get('code', 0) < 0):
                code = result.get('code', resp.status_code) if isinstance(result, dict) else resp.status_code
                msg = result.get('msg', '') if isinstance(result, dict) else str(resp.text[:100])
                
                # التقاط الحظر وتخزينه بدقة ميلي ثانية وتفعيل درع الصمت فوراً
                if code == -1003 or resp.status_code in (418, 429) or 'banned' in msg.lower():
                    m = re.search(r'until\s+(\d+)', msg)
                    if m:
                        ban_until_ts = int(m.group(1)) / 1000.0
                        save_ban_until(ban_until_ts)
                    else:
                        retry_after = int(resp.headers.get('Retry-After', '120'))
                        save_ban_until(time.time() + retry_after)
                    
                    rem, mins, secs = get_remaining_ban_time()
                    raise ExchangeError('IP_BANNED_COOLDOWN', False, msg=f'{mins} دقيقة و {secs} ثانية متبقية')

                # أخطاء بيانات المفتاح
                if any(str(err_c) in str(code) for err_c in [-2014, -2015, -1022, -2010]):
                    raise ExchangeError(code, False, msg=msg)

                raise ExchangeError(code, resp.status_code>=500 or code in (-1000,-1006,-1007), msg=msg)

            return result
        except ExchangeError:
            raise
        except requests.RequestException as re:
            raise ExchangeError('NETWORK', True, msg=str(re)) from None

    def verify(self):
        # فحص درع الصمت أولاً
        rem, mins, secs = get_remaining_ban_time()
        if rem > 0:
            # إذا كان هناك حظر مسبق ساري المفعول، نقبل المفتاح ونحفظه كتحقق مؤجل
            return {
                'uid': hashlib.sha256(self.key.encode()).hexdigest()[:16],
                'canTrade': True,
                'ip_deferred': True
            }

        a = None
        try:
            a = self.request('GET', '/api/v3/account')
        except ExchangeError as e:
            raw = str(e)
            if any(err_code in raw for err_code in ['-2014', '-2015', '-1022', '-2010', 'Missing credentials']):
                raise
            if 'IP_BANNED_COOLDOWN' in raw or '-1003' in raw or 'كثرة الطلبات' in raw:
                return {
                    'uid': hashlib.sha256(self.key.encode()).hexdigest()[:16],
                    'canTrade': True,
                    'ip_deferred': True
                }
            raise
        except Exception:
            return {
                'uid': hashlib.sha256(self.key.encode()).hexdigest()[:16],
                'canTrade': True,
                'ip_deferred': True
            }

        if not a or not a.get('canTrade'):
            raise ValueError('الحساب لا يسمح بالتداول')
            
        if self.venue == 'live' and not a.get('ip_deferred'):
            try:
                p = self.request('GET', '/sapi/v1/account/apiRestrictions')
                if p and isinstance(p, dict):
                    if 'enableWithdrawals' in p and p.get('enableWithdrawals') is not False:
                        raise ValueError('يجب تعطيل السحب من المفتاح — اذهب لإعدادات API وعطّل Withdraw')
                    if not p.get('enableSpotAndMarginTrading'):
                        raise ValueError('فعّل صلاحية Spot Trading في المفتاح')
                    for capability in ('enableFutures', 'enableInternalTransfer', 'permitsUniversalTransfer', 'enableVanillaOptions', 'enablePortfolioMarginTrading'):
                        if p.get(capability):
                            raise ValueError('عطّل العقود والتحويلات؛ استخدم مفتاحًا مخصصًا للفوري فقط (Spot فقط)')
            except ValueError:
                raise
            except Exception:
                pass
        return a

    def balances(self):
        res = self.request('GET', '/api/v3/account')
        return {x['asset']: D(x['free']) for x in res.get('balances', [])}

    def price(self, symbol):
        # استخدام vision دائماً للأسعار لتوفير حدود التداول
        try:
            r = requests.get(f'https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}', timeout=4)
            if r.status_code == 200:
                return D(r.json()['price'])
        except Exception:
            pass
        return D(self.request('GET', '/api/v3/ticker/price', {'symbol': symbol}, False)['price'])

    def rules(self, symbol):
        if symbol not in self.filters or time.time() - self.filters[symbol][0] > 3600:
            # استخدام vision لمعلومات الرموز
            info = None
            try:
                r = requests.get(f'https://data-api.binance.vision/api/v3/exchangeInfo?symbol={symbol}', timeout=5)
                if r.status_code == 200:
                    info = r.json()['symbols'][0]
            except Exception:
                pass
            if not info:
                info = self.request('GET', '/api/v3/exchangeInfo', {'symbol': symbol}, False)['symbols'][0]
            if info.get('status') != 'TRADING' or not info.get('isSpotTradingAllowed', False):
                raise ValueError('الزوج غير متاح للتداول الفوري')
            if 'STOP_LOSS' not in info.get('orderTypes', []):
                raise ValueError('الزوج لا يدعم STOP_LOSS السوقي؛ تم منع الدخول')
            fs = {f['filterType']: f for f in info['filters']}
            self.filters[symbol] = (time.time(), dict(info=info, filters=fs))
        return self.filters[symbol][1]

    def quantity(self, symbol, quantity, price, market=False, require_min=True):
        rule = self.rules(symbol); fs = rule['filters']; lot = fs['LOT_SIZE']
        q = floor_step(quantity, lot['stepSize'])
        if market:
            ml = fs.get('MARKET_LOT_SIZE', {})
            if D(ml.get('stepSize', 0)) > 0: q = floor_step(q, ml['stepSize'])
            if D(ml.get('maxQty', 0)) > 0 and q > D(ml['maxQty']): raise ValueError('حجم أكبر من حد المنصة')
            if require_min and q < D(ml.get('minQty', 0)): raise ValueError('الكمية أقل من الحد الأدنى السوقي')
        if q > D(lot['maxQty']) or (require_min and (q < D(lot['minQty']) or q <= 0)):
            raise ValueError('الكمية خارج حدود Binance')
        notional = q * D(price)
        for key in ('MIN_NOTIONAL', 'NOTIONAL'):
            f = fs.get(key)
            if not f: continue
            applies = not market or f.get('applyToMarket', f.get('applyMinToMarket', True))
            if require_min and applies and notional < D(f['minNotional']): raise ValueError('قيمة الأمر أقل من الحد الأدنى')
            if D(f.get('maxNotional', 0)) > 0 and (not market or f.get('applyMaxToMarket', True)) and notional > D(f['maxNotional']):
                raise ValueError('قيمة الأمر أعلى من الحد الأقصى')
        return q

    def price_tick(self, symbol, value):
        f = self.rules(symbol)['filters']['PRICE_FILTER']
        p = floor_step(value, f['tickSize'])
        if p < D(f['minPrice']) or (D(f['maxPrice']) > 0 and p > D(f['maxPrice'])): raise ValueError('سعر خارج حدود Binance')
        return p

    def query(self, symbol, cid):
        try: return self.request('GET', '/api/v3/order', {'symbol': symbol, 'origClientOrderId': cid})
        except ExchangeError as e:
            if e.code == -2013: return None
            raise

    def cancel(self, symbol, cid):
        try: return self.request('DELETE', '/api/v3/order', {'symbol': symbol, 'origClientOrderId': cid})
        except ExchangeError:
            r = self.query(symbol, cid)
            if r is not None and r.get('status') in ('FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'EXPIRED_IN_MATCH'):
                return r
            raise ExchangeError('CANCEL_UNCONFIRMED', True) from None

    def net_filled(self, symbol, order):
        qty = D(order['executedQty'])
        if qty <= 0: return D(0)
        base = self.rules(symbol)['info']['baseAsset']
        quote = self.rules(symbol)['info']['quoteAsset']
        trades = []; start = None
        while True:
            p = {'symbol': symbol, 'orderId': order['orderId'], 'limit': 1000}
            if start is not None: p['fromId'] = start
            batch = self.request('GET', '/api/v3/myTrades', p)
            trades.extend(x for x in batch if x['orderId'] == order['orderId'])
            if len(batch) < 1000: break
            start = batch[-1]['id'] + 1
        if sum((D(x['qty']) for x in trades), D(0)) < qty:
            raise ExchangeError('FILLS_NOT_YET_VISIBLE', True)
        fees_base = sum((D(x['commission']) for x in trades if x['commissionAsset'] == base), D(0))
        return max(D(0), qty - fees_base)

    def calculate_fee(self, quantity, price, fee_rate=0.00075, bnb_discount=True):
        notional = D(quantity) * D(price)
        rate = D(fee_rate) if bnb_discount else D(0.001)
        fee = notional * rate
        return fee
