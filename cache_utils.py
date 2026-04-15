import time
import logging
from functools import wraps
from typing import Any, Dict, Optional, Callable
import threading

logger = logging.getLogger(__name__)

class TTLCache:
    """Thread-safe TTL cache for expensive operations"""
    
    def __init__(self, default_ttl: int = 300):
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.RLock()
        self.default_ttl = default_ttl
        self.stats = {'hits': 0, 'misses': 0}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self.stats['hits'] += 1
                    return value
                else:
                    del self._cache[key]
            self.stats['misses'] += 1
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL"""
        with self._lock:
            expiry = time.time() + (ttl or self.default_ttl)
            self._cache[key] = (value, expiry)
    
    def delete(self, key: str) -> None:
        """Delete key from cache"""
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
    
    def cleanup(self) -> int:
        """Remove expired entries, return count removed"""
        removed = 0
        with self._lock:
            now = time.time()
            expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
            for key in expired_keys:
                del self._cache[key]
                removed += 1
        return removed
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0
            return {
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'hit_rate': f"{hit_rate:.1f}%",
                'size': len(self._cache)
            }


blockchain_cache = TTLCache(default_ttl=300)
supabase_cache = TTLCache(default_ttl=120)
api_cache = TTLCache(default_ttl=60)


def cached(cache: TTLCache, key_func: Optional[Callable] = None, ttl: Optional[int] = None):
    """Decorator for caching function results"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache HIT: {cache_key[:50]}...")
                return cached_result
            
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            logger.debug(f"Cache MISS: {cache_key[:50]}... (stored)")
            return result
        return wrapper
    return decorator


def cache_ubi_claim_key(wallet_address: str) -> str:
    """Generate cache key for UBI claim check"""
    return f"ubi_claim:{wallet_address.lower()}"


def cache_task_eligibility_key(wallet_address: str, task_type: str) -> str:
    """Generate cache key for task eligibility"""
    return f"task_eligibility:{task_type}:{wallet_address.lower()}"


_preloaded_data = {}
_preload_lock = threading.Lock()

def preload_data(key: str, loader_func: Callable, force: bool = False) -> Any:
    """Preload data at startup instead of per-request"""
    global _preloaded_data
    with _preload_lock:
        if key not in _preloaded_data or force:
            try:
                logger.info(f"Preloading data: {key}")
                _preloaded_data[key] = loader_func()
                logger.info(f"Preloaded {key} successfully")
            except Exception as e:
                logger.error(f"Failed to preload {key}: {e}")
                _preloaded_data[key] = None
        return _preloaded_data.get(key)


def get_preloaded(key: str) -> Optional[Any]:
    """Get preloaded data"""
    return _preloaded_data.get(key)


def invalidate_cache(cache: TTLCache, pattern: Optional[str] = None) -> int:
    """Invalidate cache entries matching pattern"""
    if pattern is None:
        cache.clear()
        return -1
    
    removed = 0
    with cache._lock:
        keys_to_remove = [k for k in cache._cache.keys() if pattern in k]
        for key in keys_to_remove:
            del cache._cache[key]
            removed += 1
    return removed


def log_cache_stats():
    """Log all cache statistics"""
    logger.info("=== Cache Statistics ===")
    logger.info(f"Blockchain cache: {blockchain_cache.get_stats()}")
    logger.info(f"Supabase cache: {supabase_cache.get_stats()}")
    logger.info(f"API cache: {api_cache.get_stats()}")
