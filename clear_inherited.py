"""مسح كل الصفقات الموروثة من الباكتست — بداية نظيفة جديدة فقط"""
import json, os
STATE_FILE = "bot_state_v241.json"

if os.path.exists(STATE_FILE):
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    
    old_open = len(st.get("open_positions", []))
    old_buy = len(st.get("buy_fingerprints", {}))
    old_sell = len(st.get("sell_fingerprints", {}))
    
    st["open_positions"] = []
    st["buy_fingerprints"] = {}
    st["sell_fingerprints"] = {}
    st["sent_signals"] = {}
    
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    
    print(f"تم مسح {old_open} صفقة موروثة + {old_buy} بصمة شراء + {old_sell} بصمة بيع")
    print("البوت الآن يبدأ نظيف — سيرسل الإشارات الجديدة فقط")
else:
    print("لا يوجد ملف حالة — البوت سيبدأ نظيف تلقائياً")

# Also check live_execution.sqlite3
import pathlib
db_path = pathlib.Path("live_execution.sqlite3")
if db_path.exists():
    print(f"يوجد قاعدة بيانات تنفيذ حية: {db_path} — قد تحتوي صفقات موروثة")
    print("احذفها إذا أردت بداية نظيفة: rm live_execution.sqlite3 live_execution.sqlite3-wal live_execution.sqlite3-shm")
