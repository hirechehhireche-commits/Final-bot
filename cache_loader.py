"""
Cache Loader V2 - GitHub Friendly - يدعم ملفات مضغوطة <25MB
يحمل من:
- titan_cache_bundle.pkl.gz (13MB) - كل شيء في ملف واحد مضغوط
- titan_cache_core.pkl.gz (11.5MB) + titan_cache_gates.pkl.gz (1.9MB) - مقسم
- titan_cache_bundle.pkl (32MB) - قديم غير مضغوط
- bot_cache/*.pkl - fallback قديم
"""
import pickle
import gzip
from pathlib import Path

# مسارات البحث - المضغوط أولاً (GitHub Friendly)
BUNDLE_PATHS = [
    # Gzipped single bundle - 13MB <25MB ✅
    Path("titan_cache_bundle.pkl.gz"),
    Path("bot_cache/titan_cache_bundle.pkl.gz"),
    Path(__file__).parent / "titan_cache_bundle.pkl.gz",
    Path(__file__).parent / "bot_cache" / "titan_cache_bundle.pkl.gz",
    Path.cwd() / "titan_cache_bundle.pkl.gz",
    
    # Split gzipped - 11.5MB + 1.9MB ✅
    Path("titan_cache_core.pkl.gz"),
    Path("titan_cache_gates.pkl.gz"),
    
    # Uncompressed fallback - 32MB >25MB ❌ لا يعمل على GitHub web
    Path("titan_cache_bundle.pkl"),
    Path("bot_cache/titan_cache_bundle.pkl"),
    Path(__file__).parent / "titan_cache_bundle.pkl",
    Path.cwd() / "titan_cache_bundle.pkl",
]

_bundle_cache = None
_split_cache = {}  # For split files

def _load_pickle_file(path: Path):
    """حمل pickle سواء مضغوط أو لا"""
    try:
        if path.suffix == '.gz' or str(path).endswith('.gz'):
            with gzip.open(path, 'rb') as f:
                data = pickle.load(f)
        else:
            with open(path, 'rb') as f:
                data = pickle.load(f)
        return data
    except Exception as e:
        print(f"[CacheLoader] Error loading {path}: {e}")
        return None

def get_bundle():
    global _bundle_cache, _split_cache
    
    if _bundle_cache is not None:
        return _bundle_cache
    
    # Try single bundle first (gzipped or not)
    for bundle_path in BUNDLE_PATHS:
        if bundle_path.exists() and "core" not in bundle_path.name and "gates" not in bundle_path.name:
            data = _load_pickle_file(bundle_path)
            if data:
                _bundle_cache = data
                size_mb = bundle_path.stat().st_size / 1024 / 1024
                print(f"[CacheLoader] ✅ Loaded bundle from {bundle_path} - {len(data)} files - {size_mb:.1f}MB")
                return _bundle_cache
    
    # Try split bundles
    core_paths = [Path("titan_cache_core.pkl.gz"), Path(__file__).parent / "titan_cache_core.pkl.gz"]
    gates_paths = [Path("titan_cache_gates.pkl.gz"), Path(__file__).parent / "titan_cache_gates.pkl.gz"]
    
    merged = {}
    for cp in core_paths:
        if cp.exists():
            data = _load_pickle_file(cp)
            if data:
                merged.update(data)
                print(f"[CacheLoader] ✅ Loaded core from {cp} - {len(data)} files")
                break
    
    for gp in gates_paths:
        if gp.exists():
            data = _load_pickle_file(gp)
            if data:
                merged.update(data)
                print(f"[CacheLoader] ✅ Loaded gates from {gp} - {len(data)} files")
                break
    
    if merged:
        _bundle_cache = merged
        print(f"[CacheLoader] ✅ Merged split bundles - {len(merged)} files total")
        return _bundle_cache
    
    print(f"[CacheLoader] ❌ No bundle found")
    print(f"[CacheLoader] Tip: Upload titan_cache_bundle.pkl.gz (13MB) not .pkl (32MB) to GitHub - limit 25MB")
    return None

def load_from_bundle(key: str):
    """حمل ملف محدد من الباندل"""
    bundle = get_bundle()
    if bundle and key in bundle:
        print(f"[CacheLoader] ✅ Loaded {key} from bundle")
        return bundle[key]
    
    # Fallback to original file paths (including gz)
    fallback_paths = [
        Path(f"bot_cache/{key}.pkl.gz"),
        Path(f"bot_cache/{key}.pkl"),
        Path(f"{key}.pkl.gz"),
        Path(f"{key}.pkl"),
        Path(__file__).parent / "bot_cache" / f"{key}.pkl.gz",
        Path(__file__).parent / "bot_cache" / f"{key}.pkl",
        Path(__file__).parent / f"{key}.pkl.gz",
        Path(__file__).parent / f"{key}.pkl",
    ]
    
    for fp in fallback_paths:
        if fp.exists():
            data = _load_pickle_file(fp)
            if data is not None:
                print(f"[CacheLoader] ✅ Loaded {key} from fallback {fp}")
                return data
    
    print(f"[CacheLoader] ❌ {key} not found")
    return None

def load_titans_cache():
    return load_from_bundle("titans_4h_5y_cache")

def load_gate5m():
    return load_from_bundle("gate5m_v102")

def load_gate1m():
    return load_from_bundle("gate1m_v102")

def load_bt5y_result():
    return load_from_bundle("bt5y_static_result")

def load_genome(name: str):
    return load_from_bundle(name)
