"""
GitHub Disk V5 - قرص حقيقي عبر GitHub
الملف titan-data في جذر المستودع يعمل كـ Disk
"""
import os, json, base64, requests, time
from pathlib import Path

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
DISK_FILE = "titan-data"

class GitHubDiskV5:
    def __init__(self):
        self.local_path = Path(DISK_FILE)
        self.cache = {}
        self.load()
    
    def load(self):
        try:
            if self.local_path.exists():
                data = self.local_path.read_text()
                self.cache = json.loads(base64.b64decode(data).decode()) if data else {}
            else:
                self.cache = {}
        except:
            self.cache = {}
    
    def save(self):
        try:
            encoded = base64.b64encode(json.dumps(self.cache).encode()).decode()
            self.local_path.write_text(encoded)
            # Try GitHub push if token available
            if GITHUB_TOKEN and GITHUB_REPO:
                self._push_to_github(encoded)
        except Exception as e:
            print(f"[GitHubDisk] Save error: {e}")
    
    def _push_to_github(self, content):
        try:
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DISK_FILE}"
            # Get sha if exists
            r = requests.get(url, headers=headers, timeout=10)
            sha = r.json().get("sha") if r.status_code == 200 else None
            
            data = {
                "message": f"Update titan-data {time.time()}",
                "content": base64.b64encode(json.dumps(self.cache).encode()).decode(),
                "sha": sha
            } if sha else {
                "message": f"Create titan-data {time.time()}",
                "content": base64.b64encode(json.dumps(self.cache).encode()).decode()
            }
            requests.put(url, headers=headers, json=data, timeout=10)
        except:
            pass
    
    def get(self, key, default=None):
        return self.cache.get(key, default)
    
    def set(self, key, value):
        self.cache[key] = value
        self.save()
    
    def delete(self, key):
        if key in self.cache:
            del self.cache[key]
            self.save()

# Global instance
disk = GitHubDiskV5()

def get_disk():
    return disk
