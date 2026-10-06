"""
Simple in-memory cache with TTL for RolloForge.

Provides file-based caching to reduce repeated disk I/O operations.
Cache invalidates automatically on writes and expires after TTL.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry:
    """Single cache entry with value and metadata."""
    value: Any
    cached_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)


class FileCache:
    """
    Thread-safe in-memory cache for file-based data.
    
    Features:
    - TTL-based expiration
    - Automatic invalidation on writes
    - Access statistics for monitoring
    - Thread-safe operations
    """
    
    def __init__(self, default_ttl: float = 60.0) -> None:
        """
        Initialize cache.
        
        Args:
            default_ttl: Default time-to-live in seconds (default: 60s)
        """
        self._cache: dict[str, CacheEntry] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()
        self._default_ttl = default_ttl
        self._stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "invalidations": 0,
            "expirations": 0,
        }
    
    def _get_lock(self, key: str) -> threading.RLock:
        """Get or create lock for a key."""
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]
    
    def _is_expired(self, entry: CacheEntry, ttl: float | None = None) -> bool:
        """Check if cache entry has expired."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        return (time.time() - entry.cached_at) > effective_ttl
    
    def get(self, key: str, loader: Callable[[], T], ttl: float | None = None) -> T:
        """
        Get value from cache or load it.
        
        Args:
            key: Cache key (typically file path)
            loader: Function to call if cache miss
            ttl: Optional override for TTL
            
        Returns:
            Cached or loaded value
        """
        lock = self._get_lock(key)
        
        with lock:
            # Check cache
            if key in self._cache:
                entry = self._cache[key]
                
                if not self._is_expired(entry, ttl):
                    # Cache hit
                    entry.access_count += 1
                    entry.last_accessed = time.time()
                    self._stats["hits"] += 1
                    return entry.value
                else:
                    # Expired
                    del self._cache[key]
                    self._stats["expirations"] += 1
            
            # Cache miss - load and store
            self._stats["misses"] += 1
            value = loader()
            self._cache[key] = CacheEntry(value=value)
            return value
    
    def get_if_cached(self, key: str) -> Any | None:
        """
        Get value only if it exists and is not expired.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None
        """
        lock = self._get_lock(key)
        
        with lock:
            if key in self._cache:
                entry = self._cache[key]
                
                if not self._is_expired(entry):
                    entry.access_count += 1
                    entry.last_accessed = time.time()
                    self._stats["hits"] += 1
                    return entry.value
                else:
                    del self._cache[key]
                    self._stats["expirations"] += 1
            
            return None
    
    def set(self, key: str, value: Any) -> None:
        """
        Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        lock = self._get_lock(key)
        
        with lock:
            self._cache[key] = CacheEntry(value=value)
            self._stats["writes"] += 1
    
    def invalidate(self, key: str) -> bool:
        """
        Invalidate a specific cache entry.
        
        Args:
            key: Cache key to invalidate
            
        Returns:
            True if entry was found and removed
        """
        lock = self._get_lock(key)
        
        with lock:
            if key in self._cache:
                del self._cache[key]
                self._stats["invalidations"] += 1
                return True
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern substring.
        
        Args:
            pattern: Substring to match in keys
            
        Returns:
            Number of entries invalidated
        """
        with self._global_lock:
            keys_to_remove = [k for k in self._cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self._cache[key]
            self._stats["invalidations"] += len(keys_to_remove)
            return len(keys_to_remove)
    
    def invalidate_all(self) -> int:
        """
        Clear entire cache.
        
        Returns:
            Number of entries cleared
        """
        with self._global_lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats["invalidations"] += count
            return count
    
    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with hit/miss stats and memory usage
        """
        with self._global_lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0
            
            # Estimate memory usage
            import sys
            memory_usage = sum(
                sys.getsizeof(entry.value) + sys.getsizeof(entry)
                for entry in self._cache.values()
            )
            
            return {
                **self._stats,
                "hit_rate": round(hit_rate, 2),
                "total_requests": total_requests,
                "entries": len(self._cache),
                "memory_bytes": memory_usage,
                "memory_mb": round(memory_usage / (1024 * 1024), 4),
            }
    
    def get_entry_info(self, key: str) -> dict[str, Any] | None:
        """
        Get detailed info about a cache entry.
        
        Args:
            key: Cache key
            
        Returns:
            Entry info dict or None if not found
        """
        lock = self._get_lock(key)
        
        with lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            return {
                "key": key,
                "cached_at": entry.cached_at,
                "age_seconds": round(time.time() - entry.cached_at, 2),
                "access_count": entry.access_count,
                "last_accessed": entry.last_accessed,
                "size_bytes": len(str(entry.value)) if entry.value else 0,
            }


# Global cache instance for rolloforge
_file_cache: FileCache | None = None


def get_cache() -> FileCache:
    """Get or create global file cache instance."""
    global _file_cache
    if _file_cache is None:
        _file_cache = FileCache(default_ttl=60.0)
    return _file_cache


def reset_cache() -> None:
    """Reset global cache (useful for testing)."""
    global _file_cache
    _file_cache = None


def cached_load(path: Path, loader: Callable[[], T], ttl: float | None = None) -> T:
    """
    Load data with caching.
    
    Args:
        path: File path (used as cache key)
        loader: Function to load data if not cached
        ttl: Optional TTL override
        
    Returns:
        Loaded or cached data
    """
    cache = get_cache()
    return cache.get(str(path), loader, ttl)


def invalidate_path(path: Path) -> bool:
    """Invalidate cache for a specific file path."""
    cache = get_cache()
    return cache.invalidate(str(path))
