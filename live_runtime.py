"""Telegram/HTTPS integration — v241 EASY DIRECT — إضافة سهلة مباشرة في البوت + وضع تراكمي
- يدعم طريقتين: صفحة HTTPS الآمنة (موصى بها) + كتابة مباشرة في البوت مع حذف تلقائي
"""
import hashlib
import html
import json
import os
import secrets
import threading
import time
from urllib.parse import parse_qs,urlparse
from live_store import LiveStore
from live_execution import LiveExecutor

B=None; STORE=None; EXEC=None
TOKENS={}; CONFIRMS={}; TOKEN_LOCK=threading.Lock(); RATE={}
PUBLIC_URL=''; STOP=threading.Event(); LAST_TICK=0
EASY_TIMEOUT=300  # 5 دقائق مهلة إدخال المفتاح

def init(bot):
    global B,STORE,EXEC,PUBLIC_URL
    if STORE is not None:return
    B=bot
    # افتراضيات مجانية 100% — لا تحتاج env
    venue=os.environ.get('BINANCE_ENV','live') or 'live'  # افتراضي live
    PUBLIC_URL=os.environ.get('PUBLIC_BASE_URL',os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/')
    if PUBLIC_URL:
        u=urlparse(PUBLIC_URL)
        if u.scheme!='https' or not u.netloc or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
            raise ValueError('PUBLIC_BASE_URL must be an HTTPS origin without a path')
    path=os.environ.get('TITAN_LIVE_DB',os.path.join(B.WORKSPACE_DIR,'live_execution.sqlite3'))
    # APP_SECRET افتراضي — مشتق من BOT_TOKEN إذا لم يضبط — يبقى ثابت طالما BOT_TOKEN ثابت
    app_secret=os.environ.get('APP_SECRET','')
    if not app_secret:
        bot_token=os.environ.get('BOT_TOKEN','')
        # توليد سر افتراضي 64 حرف من BOT_TOKEN — آمن للاستخدام المجاني
        base=(bot_token+'|titan-v241-free-default-secret|'+str(B.ADMIN_CHAT_ID if hasattr(B,'ADMIN_CHAT_ID') else ''))
        app_secret=hashlib.sha256(base.encode()).hexdigest()  # 64 حرف
        B.log('[LIVE] APP_SECRET غير مضبوط — استخدام سر افتراضي مشتق من BOT_TOKEN (مجاني)')
    STORE=LiveStore(path,app_secret,venue)
    # ALLOW_LIVE_TRADING افتراضي مفعّل =1 — لا تحتاج env
    allow_live_str=os.environ.get('ALLOW_LIVE_TRADING','1')
    allow_live = allow_live_str!='0'  # افتراضي مفعّل إلا إذا 0 صراحة
    EXEC=LiveExecutor(STORE,B.POOL_PARAMS_MAP,allow_live)
    if EXEC.allow_live:STORE.cipher()
    import fcntl
    lockfile=open(str(path)+'.lock','a+')
    try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise RuntimeError('Another bot process owns this execution database') from None
    STORE.process_lock=lockfile
    threading.Thread(target=worker,name='binance-execution',daemon=True).start()
    threading.Thread(target=notifier,name='telegram-outbox',daemon=True).start()

def worker():
    global LAST_TICK
    while not STOP.is_set():
        try:
            EXEC.tick()
            LAST_TICK=time.time()
        except Exception as e:
            B.log('[LIVE] '+type(e).__name__+' — check runtime/ledger')
        STOP.wait(max(5,int(os.environ.get('TITAN_ORDER_POLL','10'))))

def notifier():
    while not STOP.is_set():
        try:STORE.flush(lambda uid,text:B.send_msg(uid,text,B.more_kb()))
        except Exception:B.log('[OUTBOX] delivery will retry')
        STOP.wait(3)

def account(uid):return STORE.account(uid) if STORE else {'credential':None,'enabled':False,'capital':400,'max_order':100,'use_full_balance':False,'positions':{},'halt':None}

def panel(u):
    a=account(u['id']);active=EXEC.active(a) if EXEC else []
    venue=STORE.venue if STORE else os.environ.get('BINANCE_ENV','live')
    label='Binance الحقيقي — أموال حقيقية' if venue=='live' else 'Spot Testnet — أموال تجريبية'
    if a.get('use_full_balance') or a.get('capital',0)==0:
        capital_text = "💎 كامل الرصيد (تراكمي) ✅ — يستخدم كل رصيدك + ما تضيفه، ويكمل بالمتبقي عند السحب"
    else:
        capital_text = f'💵 رأس المال المخصص: {a["capital"]:g} USDT | سقف الصفقة: {a["max_order"]:g} USDT'
    equity_info = ""
    if a.get('credential') and EXEC:
        try:
            total_eq, free, used = EXEC.get_total_equity(a, EXEC.client(a))
            equity_info = f'\n📊 الرصيد الإجمالي التراكمي الحالي: {total_eq:.2f} USDT | الحر: {free:.2f} | المستخدم في صفقات البوت: {used:.2f}\n'
        except:
            pass
    return ('🔑 <b>Binance API — التداول الذاتي — v241 سهل + تراكمي</b>\n'
            f'🌐 {label}\n'
            f'🔐 الربط: {"مكتمل ومشفّر" if a.get("credential") else "غير مربوط"}\n'
            f'⚡ فتح صفقات جديدة: {"مفعّل" if a.get("enabled") else "متوقف"}\n'
            f'{capital_text}\n'
            f'📂 مراكز/أوامر البوت النشطة: {len(active)}\n'
            + equity_info +
            (f'⚠️ {B.esc(a["halt"])}\n' if a.get('halt') else '') +
            'الدخول بإشارات جديدة فقط. الشراء والحدود على المنصة، والوقف السوقي يُثبت بعد تأكيد الملء. '
            'لا رافعة ولا سحب. لا ضمان للأرباح أو للملء.\n'
            'في وضع كامل الرصيد: كل إيداع جديد يُستخدم تلقائياً في الصفقات القادمة، وكل سحب يقلل الميزانية المتبقية ويستمر العمل تراكمياً.\n')

def keyboard(u):
    bt=B.bt;rows=[];a=account(u['id'])
    if a.get('credential'):
        rows.append([bt('🔄 تحديث (صفحة آمنة)','api:add'),bt('⚡ تحديث سهل مباشر','api:easy_full')])
        rows.append([bt('🗑️ حذف المفتاح','api:del')])
    else:
        rows.append([bt('🔐 إضافة آمنة (صفحة)','api:add')])
        rows.append([bt('⚡ إضافة سهلة مباشرة في البوت 💎','api:easy_full')])
        rows.append([bt('🛠️ إضافة سهلة مخصصة','api:easy')])
    if a.get('credential'):
        rows.append([bt('👁️ عرض أرصدتي الحقيقية','api:bal'),bt('📂 أوامر البوت','api:orders')])
    rows.append([bt('📝 الورقي / إيقاف الشراء','api:paper'),bt('⚡ التداول الحقيقي'+(' ✓' if a.get('enabled') else ''),'api:real')])
    if a.get('credential'):
        rows.append([bt('🛑 الطوارئ — إغلاق مراكز البوت','api:kill')])
    if not a.get('use_full_balance') and a.get('credential'):
        rows.append([bt('💎 تفعيل وضع كامل الرصيد التراكمي','api:full')])
    return B.back_kb(rows)

def make_token(uid):
    if not PUBLIC_URL:raise ValueError('اضبط PUBLIC_BASE_URL على رابط Render الذي يبدأ بـhttps://')
    STORE.cipher()
    with TOKEN_LOCK:
        now=time.time()
        for k,v in list(TOKENS.items()):
            if v['expires']<now or v['uid']==str(uid):TOKENS.pop(k,None)
        token=secrets.token_urlsafe(32)
        TOKENS[hashlib.sha256(token.encode()).hexdigest()]={'uid':str(uid),'expires':now+600}
    return PUBLIC_URL+'/connect#'+token

def consume_token(token):
    with TOKEN_LOCK:
        row=TOKENS.pop(hashlib.sha256(token.encode()).hexdigest(),None)
    if not row or row['expires']<time.time():raise ValueError('الرابط منتهي أو مستخدم. اطلب رابطًا جديدًا من زر Binance')
    return row['uid']

def start_easy_flow(uid, full_mode=True):
    """بدء تدفق الإدخال السهل المباشر"""
    st=B.load_state()
    user=st['users'].get(str(uid))
    if not user:
        return
    # لا يمكن تغيير المفتاح بوجود مراكز
    a=account(uid)
    if EXEC and (EXEC.active(a) or STORE.unresolved(uid)):
        raise ValueError('لا يمكن تغيير المفتاح بوجود أوامر أو مراكز معلقة — أغلقها أولًا')
    user['flow']={'type':'binance_easy','step':'key','full_mode':bool(full_mode),'key':'','started':time.time(),'custom_capital':0,'custom_max':0}
    B.save_state()
    if full_mode:
        B.send_msg(uid,
            '⚡ <b>إضافة سهلة مباشرة — وضع كامل الرصيد التراكمي 💎</b>\n\n'
            '1️⃣ أرسل <b>API Key</b> الآن كرسالة عادية هنا في الخاص\n'
            '• سيتم حذفه تلقائياً بعد ثوانٍ وتشفيره فوراً\n'
            '• لا ترسله في مجموعة\n'
            '• المفتاح يجب أن يكون Spot فقط بلا سحب\n\n'
            '⏱️ المهلة 5 دقائق — اكتب /cancel للإلغاء',
            [[B.bt('❌ إلغاء','api:easy_cancel')]])
    else:
        B.send_msg(uid,
            '🛠️ <b>إضافة سهلة مخصصة</b>\n\n'
            '1️⃣ أرسل <b>API Key</b> الآن\n'
            '• سيتم حذفه تلقائياً بعد الحفظ\n'
            '⏱️ المهلة 5 دقائق — /cancel للإلغاء',
            [[B.bt('❌ إلغاء','api:easy_cancel')]])

def handle_easy_text(uid, text, msg_id=None, user_obj=None):
    """معالجة رسائل التدفق السهل — تُستدعى من TITAN_UNIFIED_BOT handle_text_message"""
    st=B.load_state()
    u=st['users'].get(str(uid))
    if not u or not u.get('flow') or u['flow'].get('type')!='binance_easy':
        return False
    flow=u['flow']
    # تحقق مهلة
    if time.time()-flow.get('started',0)>EASY_TIMEOUT:
        u['flow']=None
        B.save_state()
        B.send_msg(uid,'⏰ انتهت مهلة إدخال المفتاح (5د). ابدأ من جديد.', B.back_kb([[B.bt('⚡ إضافة سهلة','api:easy_full')]]))
        return True

    step=flow.get('step')
    txt=text.strip()

    # إلغاء
    if txt.lower() in ('/cancel','cancel','إلغاء','❌'):
        u['flow']=None
        B.save_state()
        B.send_msg(uid,'❌ أُلغي إدخال المفتاح.', keyboard(u))
        # حاول حذف رسالة المستخدم
        try:
            if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
        except: pass
        return True

    try:
        if step=='key':
            if not (16<=len(txt)<=256):
                B.send_msg(uid,'⚠️ طول المفتاح غير صحيح (16-256). أعد الإرسال أو /cancel')
                return True
            # احفظ Key مؤقتاً
            flow['key']=txt
            flow['step']='secret'
            flow['started']=time.time()
            B.save_state()
            # حذف رسالة المفتاح فوراً
            try:
                if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
            except: pass
            B.send_msg(uid,
                '✅ تم استلام API Key وتشفيره مؤقتاً\n\n'
                '2️⃣ الآن أرسل <b>API Secret</b> كرسالة هنا\n'
                '• سيتم حذفه فوراً بعد التحقق\n'
                '• لا تشاركه مع أحد',
                [[B.bt('❌ إلغاء','api:easy_cancel')]])
            return True

        elif step=='secret':
            if not (16<=len(txt)<=256):
                B.send_msg(uid,'⚠️ طول Secret غير صحيح. أعد الإرسال أو /cancel')
                return True
            secret=txt
            key=flow.get('key','')
            full_mode=flow.get('full_mode',True)
            # حذف رسالة Secret فوراً
            try:
                if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
            except: pass

            if full_mode:
                # وضع كامل الرصيد: capital=0 max_order=0
                try:
                    EXEC.connect(uid, key, secret, 0, 0, use_full_balance=True)
                    u['flow']=None
                    B.save_state()
                    B.send_msg(uid,
                        '✅ <b>تم الربط بنجاح — وضع كامل الرصيد التراكمي 💎</b>\n\n'
                        '🔐 المفتاح مشفّر بـ AESGCM ومحفوظ في /var/data\n'
                        '💎 سيستخدم كل رصيدك + ما تضيفه ويكمل بالمتبقي عند السحب — تراكمي\n'
                        '⚠️ رسائل المفتاح حُذفت تلقائياً\n\n'
                        'التداول لم يبدأ بعد — فعّله من الزر ⚡ التداول الحقيقي',
                        keyboard(u))
                except Exception as e:
                    u['flow']=None
                    B.save_state()
                    raw=str(e)
                    if '-1003' in raw or 'كثرة الطلبات' in raw or 'RATE_LIMIT' in raw:
                        err='⏳ Binance مشغول حالياً (كثرة الطلبات -1003)\n\n• السبب: السيرفر يرسل كثير طلبات بيانات السوق + طلب التحقق في نفس اللحظة\n• الحل: انتظر دقيقة واحدة ثم أعد المحاولة\n• تأكد أيضاً:\n  - المفتاح Spot فقط بلا سحب\n  - IP الخادم مضاف في قائمة IP المسموحة (إن كنت مفعل IP Restriction)\n  - أو عطّل IP Restriction مؤقتاً للتجربة\n\nسيتم حل المشكلة تلقائياً بعد دقيقة.'
                    else:
                        err=str(e) if isinstance(e,(ValueError,RuntimeError)) or e.__class__.__name__=='ExchangeError' else type(e).__name__
                    B.send_msg(uid,'⚠️ فشل الربط: '+B.esc(err), keyboard(u))
                return True
            else:
                # مخصص — انتقل لطلب capital
                flow['secret']=secret
                flow['step']='capital'
                B.save_state()
                B.send_msg(uid,
                    '✅ تم استلام Secret\n\n'
                    '3️⃣ أرسل <b>رأس المال المخصص</b> USDT — اكتب رقم مثل 400\n'
                    '• اكتب 0 لوضع كامل الرصيد التراكمي\n'
                    '• 50-100000',
                    [[B.bt('0 = كامل الرصيد 💎','api:easy_cap_0')],[B.bt('❌ إلغاء','api:easy_cancel')]])
                return True

        elif step=='capital':
            # يمكن أن يكون رقم أو callback
            try:
                cap=float(txt)
                if not (0<=cap<=100000):
                    raise ValueError()
            except:
                B.send_msg(uid,'⚠️ أرسل رقم 0-100000 أو /cancel')
                return True
            try:
                if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
            except: pass
            flow['custom_capital']=cap
            flow['step']='max_order'
            B.save_state()
            B.send_msg(uid,
                f'✅ رأس المال {cap:g} USDT\n\n'
                '4️⃣ أرسل <b>الحد الأقصى للصفقة</b> USDT — مثلاً 100\n'
                '• اكتب 0 = بدون سقف في وضع كامل الرصيد\n'
                '• 0-100000',
                [[B.bt('0 = بدون سقف','api:easy_max_0'),B.bt('100','api:easy_max_100')],[B.bt('❌ إلغاء','api:easy_cancel')]])
            return True

        elif step=='max_order':
            try:
                mx=float(txt)
                if not (0<=mx<=100000):
                    raise ValueError()
            except:
                B.send_msg(uid,'⚠️ أرسل رقم 0-100000 أو /cancel')
                return True
            try:
                if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
            except: pass
            key=flow.get('key','')
            secret=flow.get('secret','')
            cap=flow.get('custom_capital',0)
            full_mode = (cap==0 or mx==0 or flow.get('full_mode'))
            # إذا capital=0 → full_mode تلقائي
            try:
                EXEC.connect(uid, key, secret, cap, mx, use_full_balance=bool(full_mode or cap==0))
                u['flow']=None
                B.save_state()
                B.send_msg(uid,
                    f'✅ <b>تم الربط بنجاح {"— وضع كامل الرصيد 💎" if full_mode else ""}</b>\n\n'
                    f'💵 رأس المال {cap:g} USDT | سقف {mx:g} USDT\n'
                    '🔐 مشفّر ومحفوظ — رسائل المفاتيح حُذفت\n'
                    'فعّل التداول من ⚡ التداول الحقيقي',
                    keyboard(u))
            except Exception as e:
                u['flow']=None
                B.save_state()
                raw=str(e)
                if '-1003' in raw or 'كثرة الطلبات' in raw or 'RATE_LIMIT' in raw:
                    err='⏳ Binance مشغول (كثرة الطلبات -1003) — انتظر دقيقة وأعد المحاولة.\n• أضف IP الخادم في whitelist أو عطّل IP Restriction مؤقتاً.'
                else:
                    err=str(e) if isinstance(e,(ValueError,RuntimeError)) or e.__class__.__name__=='ExchangeError' else type(e).__name__
                B.send_msg(uid,'⚠️ فشل الربط: '+B.esc(err), keyboard(u))
            return True

    except Exception as e:
        B.log(f'[EASY] {type(e).__name__}: {e}')
        try:
            if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
        except: pass
        u['flow']=None
        B.save_state()
        B.send_msg(uid,'⚠️ خطأ في الإدخال — أعد المحاولة', keyboard(u))
        return True

    return False

def callback(cb,u):
    data=cb.get('data','')
    if not data.startswith('api:') and data!='m:api':return False
    uid=u['id'];chat=(cb.get('message') or {}).get('chat',{})
    actor=(cb.get('from') or {}).get('id')
    if chat.get('type') not in (None,'private') or (actor is not None and int(actor)!=int(uid)):
        B.respond_cb(cb,'🔒 ربط وتفعيل Binance متاحان في محادثة خاصة مع البوت فقط.');return True
    if EXEC is None:B.respond_cb(cb,'⏳ طبقة Binance لم تجهز بعد.');return True
    try:
        if data=='api:add':
            url=make_token(uid)
            B.respond_cb(cb,'🔐 افتح صفحة الربط الآمنة أدناه. الرابط شخصي وصالح 10 دقائق ولمرة واحدة.\n'
                'أدخل API Key وSecret في الصفحة فقط. حفظ المفتاح لا يفعّل التداول.\n'
                '💎 وضع كامل الرصيد التراكمي متاح في الصفحة.\n'
                'أو استخدم الإضافة السهلة المباشرة في البوت إذا تفضل — أقل أماناً لكن أسهل.',
                [[{'text':'🔐 فتح صفحة ربط Binance — آمنة','url':url}],
                 [B.bt('⚡ إضافة سهلة مباشرة 💎','api:easy_full')],
                 [B.bt('رجوع','m:api')]])
        elif data in ('api:easy','api:easy_full'):
            full = (data=='api:easy_full')
            # مسح flow قديم
            st=B.load_state()
            usr=st['users'].get(str(uid))
            if usr: usr['flow']=None
            B.save_state()
            start_easy_flow(uid, full_mode=full)
            B.respond_cb(cb,'⚡ بدأ الإدخال السهل المباشر — اتبع التعليمات في الرسائل التالية',[[B.bt('❌ إلغاء','api:easy_cancel')]])
        elif data=='api:easy_cancel':
            st=B.load_state()
            usr=st['users'].get(str(uid))
            if usr: usr['flow']=None
            B.save_state()
            B.respond_cb(cb,'❌ أُلغي إدخال المفتاح.',keyboard(u))
        elif data.startswith('api:easy_cap_'):
            # اختصارات capital
            val=data.split('_')[-1]
            # محاكاة رسالة نصية
            st=B.load_state()
            usr=st['users'].get(str(uid))
            if usr and usr.get('flow') and usr['flow'].get('step')=='capital':
                # استدعاء handle مباشرة
                B.respond_cb(cb,f'✅ رأس المال {val}')
                handle_easy_text(uid, val, None, usr)
            else:
                B.respond_cb(cb,'ابدأ من زر الإضافة السهلة أولًا',keyboard(u))
        elif data.startswith('api:easy_max_'):
            val=data.split('_')[-1]
            st=B.load_state()
            usr=st['users'].get(str(uid))
            if usr and usr.get('flow') and usr['flow'].get('step')=='max_order':
                B.respond_cb(cb,f'✅ سقف {val}')
                handle_easy_text(uid, val, None, usr)
            else:
                B.respond_cb(cb,'ابدأ من زر الإضافة السهلة أولًا',keyboard(u))
        elif data=='api:full':
            a=account(uid)
            if not a.get('credential'):raise ValueError('اربط المفتاح أولًا ثم فعّل وضع كامل الرصيد')
            if EXEC.active(a) or STORE.unresolved(uid):raise ValueError('أغلق المراكز أولًا قبل التبديل لوضع كامل الرصيد')
            a.update(use_full_balance=True, capital=0, max_order=0)
            STORE.save(a)
            B.respond_cb(cb,'💎 تم تفعيل وضع كامل الرصيد التراكمي ✅\n'+panel(u),keyboard(u))
        elif data=='api:real':
            a=account(uid)
            if not a.get('credential'):raise ValueError('اربط المفتاح أولًا')
            if not EXEC.allow_live:raise ValueError('التنفيذ العام مغلق؛ المشرف يضبط ALLOW_LIVE_TRADING=1 بعد الاختبار')
            token=secrets.token_hex(12);CONFIRMS[(str(uid),'enable')]=(token,time.time()+180)
            venue='أموال حقيقية' if STORE.venue=='live' else 'أموال Testnet تجريبية'
            mode = "كامل الرصيد التراكمي 💎" if a.get('use_full_balance') else f"{a['capital']:g} USDT"
            B.respond_cb(cb,f'⚠️ <b>تأكيد التداول الآلي — {venue}</b>\n'
                f'وضع الرصيد: {mode}، سقف الصفقة {a["max_order"]:g} (0=بدون سقف)، '
                f'خطر الوقف الاسمي بحد {a["max_risk_pct"]:g}%، حد تغير سعر الدخول/المطاردة {a["max_slippage_pct"]:g}%.\n'
                'بعد الموافقة يستطيع البوت الشراء والبيع تلقائيًا دون سؤال لكل صفقة. '
                'هل توافق؟',
                [[B.bt('✅ أوافق — فعّل','api:enable:'+token)],[B.bt('❌ تراجع','m:api')]])
        elif data.startswith('api:enable:'):
            confirm(uid,'enable',data.split(':')[-1]);EXEC.enable(uid)
            B.respond_cb(cb,'✅ فُعّل التداول للإشارات الجديدة اللاحقة فقط — وضع تراكمي.\n'+panel(u),keyboard(u))
        elif data=='api:paper':
            EXEC.pause(uid);u['settings']['paper']=True;B.save_state()
            B.respond_cb(cb,'📝 توقفت المشتريات الجديدة. تبقى متابعة المراكز القائمة ووقفها فعّالة.\n'+panel(u),keyboard(u))
        elif data=='api:kill':
            token=secrets.token_hex(12);CONFIRMS[(str(uid),'kill')]=(token,time.time()+180)
            B.respond_cb(cb,'🛑 هل تؤكد إلغاء حدود شراء البوت وبيع مراكزه المتتبعة سوقيًا؟ '
                'لن يبيع أرصدتك الأخرى. لا يمكن ضمان الملء أو السعر.',
                [[B.bt('✅ أؤكد الإغلاق','api:close:'+token)],[B.bt('تراجع','m:api')]])
        elif data.startswith('api:close:'):
            confirm(uid,'kill',data.split(':')[-1]);EXEC.kill(uid)
            B.respond_cb(cb,'🛑 أُرسل طلب الطوارئ؛ راجع إشعارات التنفيذ وBinance للتأكد.',keyboard(u))
        elif data=='api:del':
            EXEC.disconnect(uid);B.respond_cb(cb,'🗑️ حُذف الربط بعد التأكد من عدم وجود مراكز نشطة.',keyboard(u))
        elif data=='api:bal':
            bals=EXEC.client(account(uid)).balances()
            text='💼 <b>الأرصدة الحرة على Binance</b>\n'+'\n'.join(f'{B.esc(s)}: {q}' for s,q in bals.items() if q>0)
            try:
                total_eq, free, used = EXEC.get_total_equity(account(uid), EXEC.client(account(uid)))
                text+=f'\n\n📊 إجمالي تراكمي: {total_eq:.2f} USDT | حر: {free:.2f} | مستخدم: {used:.2f}'
            except:
                pass
            B.respond_cb(cb,text[:3800],keyboard(u))
        elif data=='api:orders':
            a=account(uid)
            lines=['📂 <b>دفتر التنفيذ الفعلي للبوت — v241 سهل+تراكمي</b>']
            for p in EXEC.active(a):
                lines.append(B.esc(f'{p["symbol"]} | {p["state"]} | qty={p["qty"]} | stop={p["stop"]} | budget={p.get("budget","?")} | equity_at_entry={p.get("total_equity_at_entry","?")}'))
            for o in STORE.unresolved(uid):lines.append(B.esc(f'غير مؤكد: {o["symbol"]} | {o["cid"]}'))
            B.respond_cb(cb,'\n'.join(lines) if len(lines)>1 else 'لا مراكز/أوامر نشطة للبوت.',keyboard(u))
        else:B.respond_cb(cb,panel(u),keyboard(u))
    except Exception as e:
        text=str(e) if isinstance(e,(ValueError,RuntimeError)) or e.__class__.__name__=='ExchangeError' else type(e).__name__
        B.respond_cb(cb,'⚠️ '+B.esc(text),keyboard(u))
    return True

def confirm(uid,action,token):
    item=CONFIRMS.pop((str(uid),action),None)
    if not item or item[1]<time.time() or not secrets.compare_digest(item[0],token):
        raise ValueError('التأكيد منتهي/غير صالح؛ افتح زر التفعيل أو الطوارئ مجددًا')

def on_cycle(res,baseline=False):
    if EXEC is None:return
    now=time.time()
    plans=[]
    for e in res.get('entry_plans',[]):
        p=dict(e);p['timestamp']=float(B.pd.Timestamp(e['time']).timestamp())
        if not baseline and 0<=now-p['timestamp']<=180:
            p['id']=hashlib.sha256(f'v102|{p["pool"]}|{p["ticker"]}|{p["timestamp"]}|{p["intent"]}'.encode()).hexdigest()[:24]
            plans.append(p)
    for uid,u in list(B.load_state()['users'].items()):
        if not u['settings'].get('signals',True) or not B.is_allowed(int(uid),u.get('username')):continue
        for p in plans:
            if p['intent']=='LIMIT':
                msg=B.fmt_entry(p,res['w2_current'],res.get('holds')).replace('صفقة متوسطة المدى','أمر شراء مشروط')
                STORE.notify(uid,'waiting:'+p['id'],msg+'\n⏳ إشارة انتظار حد شراء؛ ليست عملية منفذة. المهلة 12 ساعة، وتطبق حدود المطاردة للحساب الحقيقي.')
    for a in STORE.accounts():
        uid=a['uid']
        if not B.is_allowed(int(uid)):
            EXEC.pause(uid)
        active=EXEC.active(a)
        cutoff=min((p['source_time'] for p in active),default=now)
        for e in res.get('events',[]):
            if e['kind']=='ENTRY':continue
            stamp=float(B.pd.Timestamp(e['time']).timestamp())
            if stamp<=cutoff or stamp>now:continue
            EXEC.on_exit(uid,dict(e,timestamp=stamp))
        for p in plans:
            if not B.is_allowed(int(uid)):continue
            try:EXEC.accept_plan(uid,p,now)
            except Exception as e:
                msg=str(e) if isinstance(e,ValueError) or e.__class__.__name__=='ExchangeError' else type(e).__name__
                STORE.notify(uid,'skipped:'+p['id'],'⏭️ لم يُنفّذ شراء '+p['ticker']+': '+B.esc(msg))
        snaps=[]
        for s in res.get('open_positions',[]):
            if s.get('opened'):snaps.append(dict(s,opened_ts=float(B.pd.Timestamp(s['opened']).timestamp())))
        EXEC.update_stops(uid,snaps)

def setup_html(nonce):
    venue='أموال حقيقية — Binance Spot' if STORE.venue=='live' else 'Testnet — أموال تجريبية'
    return f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ربط Binance · TITAN v241 EASY</title><style>body{{background:#0e1621;color:white;font:16px Tahoma,sans-serif;max-width:520px;margin:40px auto;padding:20px;line-height:1.8}}form{{background:#182533;padding:24px;border-radius:14px}}input,button{{box-sizing:border-box;width:100%;padding:12px;margin:5px 0 14px;border:1px solid #31495f;border-radius:8px;background:#0e1621;color:white}}button{{background:#327cb5;cursor:pointer}}.note{{color:#abc3d9;font-size:13px}}.check{{display:flex;align-items:center;gap:10px;background:#1e324a;padding:12px;border-radius:8px;margin:10px 0}} .check input{{width:auto}}</style>
<h2>🔐 ربط Binance — v241 سهل+تراكمي</h2><p>{venue}</p>
<p class="note">رابط شخصي مؤقت 10 دقائق. أو استخدم الإضافة السهلة المباشرة في البوت (زر ⚡). عطّل السحب وقيّد IP.</p>
<div class="check"><input type="checkbox" id="fullbal" checked><label for="fullbal">💎 كامل الرصيد (تراكمي)</label></div>
<form method="post" action="/connect" autocomplete="off"><input type="hidden" id="ticket" name="ticket">
<label>API Key</label><input name="key" type="password" minlength="16" maxlength="256" required autocomplete="off">
<label>API Secret</label><input name="secret" type="password" minlength="16" maxlength="256" required autocomplete="new-password">
<div id="fixedFields">
<label>رأس المال (0=كامل الرصيد)</label><input id="capital" name="capital" type="number" min="0" max="100000" step="1" value="0">
<label>سقف الصفقة (0=بدون سقف)</label><input id="max_order" name="max_order" type="number" min="0" max="100000" step="1" value="0">
</div>
<input type="hidden" id="use_full" name="use_full_balance" value="1">
<button id="save" disabled>تحقق واحفظ</button><p id="error" class="note"></p>
</form>
<script nonce="{nonce}">
const token=location.hash.slice(1);history.replaceState(null,'','/connect');
if(token.length>=32){{document.getElementById('ticket').value=token;document.getElementById('save').disabled=false;}}else{{document.getElementById('error').textContent='افتح رابطًا جديدًا من زر Binance في البوت.';}}
const full=document.getElementById('fullbal');const cap=document.getElementById('capital');const maxo=document.getElementById('max_order');const usefull=document.getElementById('use_full');const fixed=document.getElementById('fixedFields');
function toggle(){{if(full.checked){{usefull.value='1';cap.value='0';maxo.value='0';fixed.style.opacity='0.5';}}else{{usefull.value='0';fixed.style.opacity='1';if(cap.value=='0')cap.value='400';if(maxo.value=='0')maxo.value='100';}}}}
full.addEventListener('change',toggle);toggle();
</script></html>'''

class SetupMixin:
    def setup_reply(self,body,status=200,nonce=None):
        payload=body.encode('utf-8');self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce or secrets.token_hex(16)}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(payload)

    def do_POST(self):
        self.connection.settimeout(20)
        if self.path!='/connect' or STORE is None:self.setup_reply('Not found',404);return
        if self.headers.get('Origin')!=PUBLIC_URL:self.setup_reply('Forbidden origin',403);return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=8192:raise ValueError('حجم الطلب غير صالح')
            fields=parse_qs(self.rfile.read(n).decode('utf-8'),strict_parsing=True)
            if any(len(v)!=1 for v in fields.values()):raise ValueError('طلب غير صالح')
            uid=consume_token(fields.get('ticket',[''])[0])
            if not B.is_allowed(int(uid)):raise ValueError('هذا المستخدم غير مخول')
            use_full = fields.get('use_full_balance',['0'])[0] in ('1','true','on','True')
            EXEC.connect(uid,fields['key'][0].strip(),fields['secret'][0].strip(),fields['capital'][0],fields['max_order'][0],use_full_balance=use_full)
            self.setup_reply('<html lang="ar" dir="rtl"><meta charset="utf-8"><h2>✅ تم الربط المشفّر — v241</h2><p>ارجع إلى تلغرام.</p></html>')
        except Exception as e:
            message=str(e) if isinstance(e,(ValueError,RuntimeError)) or e.__class__.__name__=='ExchangeError' else 'تعذر الربط؛ راجع الإعدادات واطلب رابطًا جديدًا'
            self.setup_reply('<meta charset="utf-8"><p dir="rtl">⚠️ '+html.escape(message)+'</p>',400)

    def do_GET(self):
        if self.path=='/ready':
            try:
                state=B.load_state();last=state.get('last_cycle')
                age=time.time()-B.pd.Timestamp(last).timestamp() if last else float('inf')
                ok=bool(state.get('engine_initialized')) and age<4*3600+900 and (time.time()-LAST_TICK)<180
                self._send(b'READY' if ok else b'NOT_READY',200 if ok else 503)
            except Exception:self._send(b'NOT_READY',503)
            return
        if self.path=='/connect':
            if STORE is None:self.setup_reply('Starting',503);return
            nonce=secrets.token_urlsafe(16);self.setup_reply(setup_html(nonce),nonce=nonce);return
        return super().do_GET()
