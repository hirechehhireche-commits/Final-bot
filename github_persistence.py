"""
GitHub Persistence - يجعل ملف titan-data في GitHub يعمل كـ Disk حقيقي
يحفظ كل شيء يمكن أن يحذف عند Deploy ويسترجعه تلقائياً
"""
import os
import base64
import json
import time
import threading
import hashlib
import requests

GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
GITHUB_REPO = (os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY") or "hirechehhireche-commits/Final-bot").strip()
GITHUB_BRANCH = (os.environ.get("GITHUB_BRANCH") or "main").strip()
# المسارات المحتملة لملف titan-data داخل المستودع (يجربها بالترتيب)
POSSIBLE_PATHS = ["titan-data", "FINAL_WITH_COINS/titan-data", "TITAN_RENDER_2VARS_FINAL/titan-data"]

_last_backup_hash = None
_last_backup_time = 0
_lock = threading.Lock()

def log(msg):
    try:
        print(f"[GITHUB-DISK] {msg}", flush=True)
    except:
        pass

def is_enabled():
    # قراءة ديناميكية لتجنب مشكلة الاستيراد المبكر
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or GITHUB_TOKEN).strip()
    repo = (os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY") or GITHUB_REPO).strip()
    return bool(token and repo and "/" in repo)

def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Titan-Bot-Persistence"
    }

def _api_url(path):
    # path without leading /
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

def get_file_from_github(path="titan-data"):
    """يجلب ملف titan-data من GitHub - يعيد (content_str, sha) أو (None, None)"""
    if not is_enabled():
        return None, None
    # جرب المسارات المحتملة
    paths_to_try = [path] + [p for p in POSSIBLE_PATHS if p != path]
    for try_path in paths_to_try:
        try:
            url = _api_url(try_path)
            params = {"ref": GITHUB_BRANCH}
            r = requests.get(url, headers=_headers(), params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("type") == "file" and data.get("content"):
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
                    sha = data.get("sha")
                    log(f"✅ تم جلب {try_path} من GitHub ({len(content)} bytes)")
                    return content, sha, try_path
            elif r.status_code == 404:
                continue
            else:
                log(f"⚠️ جلب {try_path} فشل: {r.status_code} {r.text[:100]}")
        except Exception as e:
            log(f"⚠️ خطأ جلب {try_path}: {e}")
            continue
    return None, None, None

def put_file_to_github(path, content_str, message="Auto backup titan-data", sha=None):
    """يرفع ملف titan-data إلى GitHub"""
    if not is_enabled():
        return False
    try:
        # إذا لم يكن لدينا sha، نجلبه أولاً
        if not sha:
            _, existing_sha, _ = get_file_from_github(path)
            if existing_sha:
                sha = existing_sha
        
        url = _api_url(path)
        b64_content = base64.b64encode(content_str.encode("utf-8")).decode("ascii")
        payload = {
            "message": message,
            "content": b64_content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
        
        r = requests.put(url, headers=_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201):
            log(f"✅ تم حفظ {path} في GitHub ({len(content_str)} bytes)")
            return True
        else:
            log(f"❌ فشل حفظ {path}: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        log(f"❌ خطأ حفظ {path}: {e}")
        return False

def restore_if_needed(local_path):
    """عند الإقلاع: إذا كان الملف المحلي فارغ أو {}، استرجعه من GitHub"""
    if not is_enabled():
        log("⚠️ GITHUB_TOKEN أو GITHUB_REPO غير مضبوط - يعمل محلياً فقط (سيفقد البيانات عند Deploy)")
        return False
    
    try:
        # إذا الملف المحلي موجود ومحتواه كبير (>10 bytes وليس {}), لا نستبدله
        if os.path.exists(local_path):
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    local_content = f.read().strip()
                if len(local_content) > 10 and local_content not in ("{}", "null", ""):
                    # تحقق إذا كان JSON صالح وفيه users أو allowed
                    try:
                        j = json.loads(local_content)
                        if isinstance(j, dict) and (j.get("users") or j.get("allowed") or j.get("open_positions")):
                            log(f"✅ الملف المحلي موجود وبه بيانات ({len(local_content)} bytes) - لا حاجة للاسترجاع")
                            return False
                    except:
                        pass
            except:
                pass
        
        # جلب من GitHub
        log(f"🔄 محاولة استرجاع {local_path} من GitHub...")
        content, sha, found_path = get_file_from_github("titan-data")
        if content and len(content.strip()) > 10:
            try:
                # تحقق أنه JSON صالح
                json.loads(content)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content)
                try:
                    os.chmod(local_path, 0o600)
                except:
                    pass
                log(f"✅ تم استرجاع البيانات من GitHub {found_path} -> {local_path} ({len(content)} bytes)")
                return True
            except json.JSONDecodeError:
                log(f"⚠️ محتوى GitHub ليس JSON صالح")
                return False
        else:
            log(f"ℹ️ لا يوجد بيانات في GitHub للاسترجاع أو الملف فارغ")
            return False
    except Exception as e:
        log(f"❌ خطأ استرجاع: {e}")
        return False

def backup_async(local_path, force=False):
    """يحفظ الملف في GitHub بشكل غير متزامن مع debounce"""
    if not is_enabled():
        return
    
    def _do_backup():
        global _last_backup_hash, _last_backup_time
        try:
            if not os.path.exists(local_path):
                return
            
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if not content or content.strip() in ("{}", "", "null"):
                return
            
            # حساب hash لتجنب رفع نفس المحتوى
            h = hashlib.sha256(content.encode()).hexdigest()
            with _lock:
                if not force and h == _last_backup_hash:
                    return
                # debounce 30 ثانية إلا إذا force
                now = time.time()
                if not force and (now - _last_backup_time) < 30:
                    return
                _last_backup_hash = h
                _last_backup_time = now
            
            # جلب sha الحالي
            _, sha, found_path = get_file_from_github("titan-data")
            target_path = found_path or "titan-data"
            
            # رسالة commit
            try:
                j = json.loads(content)
                users_count = len(j.get("users", {}))
                allowed_count = len(j.get("allowed", []))
                msg = f"Auto backup: {users_count} users, {allowed_count} allowed - {time.strftime('%Y-%m-%d %H:%M UTC')}"
            except:
                msg = f"Auto backup titan-data {time.strftime('%Y-%m-%d %H:%M UTC')}"
            
            put_file_to_github(target_path, content, message=msg, sha=sha)
        except Exception as e:
            log(f"❌ خطأ backup async: {e}")
    
    threading.Thread(target=_do_backup, daemon=True).start()

def backup_all_important_files(workspace_dir):
    """يحفظ كل الملفات المهمة التي قد تحذف عند Deploy"""
    if not is_enabled():
        return
    # حالياً نركز على titan-data فقط لأنه الأهم
    # يمكن توسيعه لاحقاً لحفظ live_execution.sqlite3 وغيره
    titan_file = os.path.join(workspace_dir, "titan-data")
    if os.path.exists(titan_file):
        backup_async(titan_file)
