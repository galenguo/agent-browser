"""Shared state store abstraction.

Two implementations:
1. K8sSharedState — backs state in a K8s ConfigMap with optimistic
   concurrency control (CAS via resourceVersion). Zero new dependencies.
2. InMemoryStateStore — plain Python dicts (default / fallback when no
   K8s ConfigMap available).

Both expose the same async interface so KeyManager, K8sBrowserPool, and
SessionPoolManager can switch between backends without code changes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Redis key constants (shared naming convention) ───────────────────

KEY_ALLOCATIONS = "allocations"
KEY_KEY_TO_POD = "key_to_pod"
KEY_POD_IDLE_SINCE = "pod_idle_since"
KEY_POOL_ALLOCATED = "allocated_pods"
KEY_SESSION_COUNTER = "session_counter"
KEY_SESSION_META = "session_meta"

# CAS retry config
MAX_CAS_RETRIES = 10
CAS_BACKOFF_BASE = 0.05  # 50 ms


# ═══════════════════════════════════════════════════════════════════════
# Abstract interface
# ═══════════════════════════════════════════════════════════════════════


class StateStore(ABC):
    """Abstract base class for shared state storage."""

    @abstractmethod
    async def hget(self, key: str, field: str) -> str | None: ...

    @abstractmethod
    async def hset(self, key: str, field: str, value: str) -> None: ...

    @abstractmethod
    async def hdel(self, key: str, *fields: str) -> None: ...

    @abstractmethod
    async def hexists(self, key: str, field: str) -> bool: ...

    @abstractmethod
    async def hgetall(self, key: str) -> dict[str, str]: ...

    @abstractmethod
    async def allocate_key(
        self, api_key: str, session_id: str, pod_name: str = ""
    ) -> None:
        """Atomically bind key → session (+ optional pod). Raises on conflict."""

    @abstractmethod
    async def release_key(self, api_key: str) -> str | None:
        """Atomically release key, mark pod idle. Returns released pod or None."""

    @abstractmethod
    async def get_key_for_session(self, session_id: str) -> str | None: ...

    @abstractmethod
    async def allocate_pod(self, session_id: str, pod_name: str) -> None: ...

    @abstractmethod
    async def release_pod(self, session_id: str) -> str | None: ...

    @abstractmethod
    async def get_allocated_pods(self) -> dict[str, str]: ...

    @abstractmethod
    async def incr_session_count(self) -> int: ...

    @abstractmethod
    async def decr_session_count(self) -> int: ...

    @abstractmethod
    async def get_session_count(self) -> int: ...

    @abstractmethod
    async def try_acquire_session_slot(self, max_concurrent: int) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...

    # ── Convenience helpers (built on primitives above) ──────────────

    async def get_all_pod_idle_since(self) -> dict[str, float]:
        raw = await self.hgetall(KEY_POD_IDLE_SINCE)
        return {k: float(v) for k, v in raw.items()}

    async def get_pod_for_key(self, key: str) -> str | None:
        return await self.hget(KEY_KEY_TO_POD, key)


# ═══════════════════════════════════════════════════════════════════════
# In-memory implementation (fallback / single-replica / local dev)
# ═══════════════════════════════════════════════════════════════════════


class InMemoryStateStore(StateStore):
    """In-memory state store wrapping plain Python dicts.

    Uses the same logical key naming as K8sSharedState so calling code
    is identical regardless of backend. Fully synchronous internally but
    exposes an async interface for compatibility.
    """

    def __init__(self):
        self._hashes: dict[str, dict[str, str]] = {}
        self._counter: int = 0

    def _hash(self, key: str) -> dict[str, str]:
        if key not in self._hashes:
            self._hashes[key] = {}
        return self._hashes[key]

    # ── Hash primitives ─────────────────────────────────────────────

    async def hget(self, key: str, field: str) -> str | None:
        return self._hash(key).get(field)

    async def hset(self, key: str, field: str, value: str) -> None:
        self._hash(key)[field] = value

    async def hdel(self, key: str, *fields: str) -> None:
        h = self._hash(key)
        for f in fields:
            h.pop(f, None)

    async def hexists(self, key: str, field: str) -> bool:
        return field in self._hash(key)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hash(key))

    # ── KeyManager operations ───────────────────────────────────────

    async def allocate_key(
        self, api_key: str, session_id: str, pod_name: str = ""
    ) -> None:
        alloc = self._hash(KEY_ALLOCATIONS)
        if api_key in alloc and alloc[api_key] != session_id:
            raise KeyError(f"CONFLICT: key bound to {alloc[api_key]}")
        alloc[api_key] = session_id
        if pod_name:
            self._hash(KEY_KEY_TO_POD)[api_key] = pod_name
            self._hash(KEY_POD_IDLE_SINCE).pop(pod_name, None)

    async def release_key(self, api_key: str) -> str | None:
        k2p = self._hash(KEY_KEY_TO_POD)
        pod = k2p.pop(api_key, None)
        self._hash(KEY_ALLOCATIONS).pop(api_key, None)
        if pod:
            self._hash(KEY_POD_IDLE_SINCE)[pod] = str(time.time())
        return pod

    async def get_key_for_session(self, session_id: str) -> str | None:
        for k, v in self._hash(KEY_ALLOCATIONS).items():
            if v == session_id:
                return k
        return None

    # ── K8sBrowserPool operations ───────────────────────────────────

    async def allocate_pod(self, session_id: str, pod_name: str) -> None:
        ap = self._hash(KEY_POOL_ALLOCATED)
        for sid, pn in ap.items():
            if pn == pod_name and sid != session_id:
                raise RuntimeError(
                    f"Pod {pod_name} already allocated to session {sid}"
                )
        ap[session_id] = pod_name

    async def release_pod(self, session_id: str) -> str | None:
        return self._hash(KEY_POOL_ALLOCATED).pop(session_id, None)

    async def get_allocated_pods(self) -> dict[str, str]:
        return dict(self._hash(KEY_POOL_ALLOCATED))

    # ── Session counter ─────────────────────────────────────────────

    async def incr_session_count(self) -> int:
        self._counter += 1
        return self._counter

    async def decr_session_count(self) -> int:
        self._counter = max(0, self._counter - 1)
        return self._counter

    async def get_session_count(self) -> int:
        return self._counter

    async def try_acquire_session_slot(self, max_concurrent: int) -> bool:
        if self._counter >= max_concurrent:
            return False
        self._counter += 1
        return True

    async def close(self) -> None:
        self._hashes.clear()
        self._counter = 0


# ═══════════════════════════════════════════════════════════════════════
# K8s ConfigMap-backed implementation (CAS via resourceVersion)
# ═══════════════════════════════════════════════════════════════════════


class K8sSharedState(StateStore):
    """K8s ConfigMap-backed shared state with optimistic concurrency control.

    Stores all allocation metadata in a single ConfigMap's ``state.json``
    data key as a JSON blob. Every mutating operation uses Compare-And-Swap:
    read the current state + resourceVersion, compute the new state locally,
    then REPLACE the ConfigMap — the API server rejects with 409 if another
    replica wrote first, triggering a retry with exponential backoff.

    Read operations are served from a local cache that is refreshed after
    every successful write, keeping the fast path cheap.
    """

    CONFIGMAP_NAME = "agent-browser-state"

    def __init__(
        self,
        namespace: str = "agent-browser",
        configmap_name: str | None = None,
    ):
        self.namespace = namespace
        self.configmap_name = configmap_name or self.CONFIGMAP_NAME
        self._v1 = None
        self._local_cache: dict | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = float(os.getenv("STATE_CACHE_TTL", "5"))

    # ── Low-level K8s I/O (sync client in executor) ────────────────

    def _get_v1(self):
        if self._v1 is None:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()
            self._v1 = client.CoreV1Api()
        return self._v1

    async def _read_state(self) -> tuple[dict, str]:
        """Read current state from ConfigMap. Returns (state_dict, resourceVersion).
        Auto-creates the ConfigMap if it doesn't exist yet."""
        v1 = self._get_v1()
        loop = __import__("asyncio").get_event_loop()

        def _do_read():
            try:
                cm = v1.read_namespaced_config_map(
                    self.configmap_name, self.namespace
                )
                raw = cm.data.get("state.json", "{}")
                return json.loads(raw), cm.metadata.resource_version
            except Exception as e:
                # Auto-create on 404
                status = getattr(e, "status", None)
                if status == 404:
                    from kubernetes import client as k8s_client
                    body = k8s_client.V1ConfigMap(
                        api_version="v1",
                        kind="ConfigMap",
                        metadata=k8s_client.V1ObjectMeta(
                            name=self.configmap_name,
                            namespace=self.namespace,
                        ),
                        data={"state.json": "{}"},
                    )
                    cm = v1.create_namespaced_config_map(self.namespace, body)
                    logger.info("Created state ConfigMap %s", self.configmap_name)
                    return {}, cm.metadata.resource_version
                raise

        return await loop.run_in_executor(None, _do_read)

    async def _replace_state(self, state: dict, resource_version: str):
        """Replace ConfigMap data. Raises 409 on conflict."""
        v1 = self._get_v1()
        loop = __import__("asyncio").get_event_loop()

        def _do_replace():
            from kubernetes import client

            body = client.V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                metadata=client.V1ObjectMeta(
                    name=self.configmap_name,
                    namespace=self.namespace,
                    resource_version=resource_version,
                ),
                data={"state.json": json.dumps(state)},
            )
            result = v1.replace_namespaced_config_map(
                name=self.configmap_name,
                namespace=self.namespace,
                body=body,
            )
            logger.debug(
                "ConfigMap replaced: rv=%s → %s",
                resource_version,
                result.metadata.resource_version,
            )
            return result

        return await loop.run_in_executor(None, _do_replace)

    # ── CAS core ─────────────────────────────────────────────────────

    async def cas_update(self, mutate_fn: Callable[[dict], dict | None]) -> dict:
        """Perform a Compare-And-Swap update.

        Args:
            mutate_fn: Pure function ``current_state -> new_state``.
                       Return ``None`` to abort (precondition failed).

        Returns:
            The committed state dict.

        Raises:
            kubernetes.client.exceptions.ApiException: On non-409 errors or
            exhausted retries.
        """
        for attempt in range(MAX_CAS_RETRIES):
            try:
                state, rv = await self._read_state()
                mutated = mutate_fn(state)
                if mutated is None:
                    return state  # Caller aborted
                await self._replace_state(mutated, rv)
                self._local_cache = mutated
                logger.debug("CAS update succeeded (attempt %d)", attempt + 1)
                return mutated

            except Exception as e:
                status = getattr(e, "status", None)
                if status == 409 and attempt < MAX_CAS_RETRIES - 1:
                    backoff = CAS_BACKOFF_BASE * (2 ** attempt)
                    logger.debug(
                        "CAS conflict attempt %d/%d, retry in %.0fms",
                        attempt + 1,
                        MAX_CAS_RETRIES,
                        backoff * 1000,
                    )
                    await __import__("asyncio").sleep(backoff)
                    continue
                raise

        raise RuntimeError(
            f"CAS update failed after {MAX_CAS_RETRIES} retries"
        )

    # ── Fast reads (local cache) ────────────────────────────────────

    async def _ensure_cache(self) -> dict:
        import time
        now = time.monotonic()
        if self._local_cache is None or (now - self._cache_time) > self._cache_ttl:
            self._local_cache, _ = await self._read_state()
            self._cache_time = now
        return self._local_cache

    async def read_cache(self) -> dict:
        """Return cached state (fast path for reads)."""
        return await self._ensure_cache()

    # ── Hash primitives (delegate to cache / CAS) ────────────────────

    async def hget(self, key: str, field: str) -> str | None:
        cache = await self._ensure_cache()
        return cache.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: str) -> None:
        def mutate(s):
            s.setdefault(key, {})[field] = value
            return s
        await self.cas_update(mutate)

    async def hdel(self, key: str, *fields: str) -> None:
        if not fields:
            return

        def mutate(s):
            h = s.get(key, {})
            for f in fields:
                h.pop(f, None)
            return s
        await self.cas_update(mutate)

    async def hexists(self, key: str, field: str) -> bool:
        return field in (await self._ensure_cache()).get(key, {})

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict((await self._ensure_cache()).get(key, {}))

    # ── KeyManager operations (atomic via CAS) ──────────────────────

    async def allocate_key(
        self, api_key: str, session_id: str, pod_name: str = ""
    ) -> None:
        _pn = pod_name  # capture for closure

        def mutate(s):
            allocations = s.setdefault(KEY_ALLOCATIONS, {})
            existing = allocations.get(api_key)
            if existing and existing != session_id:
                raise KeyError(
                    f"CONFLICT: key bound to {existing}"
                )
            allocations[api_key] = session_id
            if _pn:
                s.setdefault(KEY_KEY_TO_POD, {})[api_key] = _pn
                s.setdefault(KEY_POD_IDLE_SINCE, {}).pop(_pn, None)
            return s

        try:
            await self.cas_update(mutate)
        except KeyError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(e)) from e

    async def release_key(self, api_key: str) -> str | None:
        result_holder = [None]

        def mutate(s):
            k2p = s.setdefault(KEY_KEY_TO_POD, {})
            pod = k2p.pop(api_key, None)
            s.setdefault(KEY_ALLOCATIONS, {}).pop(api_key, None)
            if pod:
                s.setdefault(KEY_POD_IDLE_SINCE, {})[pod] = str(time.time())
            result_holder[0] = pod
            return s

        await self.cas_update(mutate)
        return result_holder[0]

    async def get_key_for_session(self, session_id: str) -> str | None:
        cache = await self._ensure_cache()
        for k, sid in cache.get(KEY_ALLOCATIONS, {}).items():
            if sid == session_id:
                return k
        return None

    # ── K8sBrowserPool operations ───────────────────────────────────

    async def allocate_pod(self, session_id: str, pod_name: str) -> None:
        def mutate(s):
            ap = s.setdefault(KEY_POOL_ALLOCATED, {})
            # Prevent double allocation of the same pod
            for sid, pn in ap.items():
                if pn == pod_name and sid != session_id:
                    raise RuntimeError(
                        f"Pod {pod_name} already allocated to session {sid}"
                    )
            ap[session_id] = pod_name
            return s
        await self.cas_update(mutate)

    async def release_pod(self, session_id: str) -> str | None:
        holder = [None]

        def mutate(s):
            ap = s.setdefault(KEY_POOL_ALLOCATED, {})
            holder[0] = ap.pop(session_id, None)
            return s
        result = await self.cas_update(mutate)
        logger.info("release_pod(%s): removed=%s, allocated_pods now=%s",
                     session_id, holder[0], list(result.get(KEY_POOL_ALLOCATED, {}).keys()))
        return holder[0]

    async def get_allocated_pods(self) -> dict[str, str]:
        return dict((await self._ensure_cache()).get(KEY_POOL_ALLOCATED, {}))

    # ── Session metadata (for cross-replica recovery) ────────────────

    async def save_session_meta(
        self, session_id: str, user_id: str, profile_dir: str
    ) -> None:
        """Persist session metadata for cross-replica recovery."""
        import time

        def mutate(s):
            meta = s.setdefault(KEY_SESSION_META, {})
            meta[session_id] = {
                "user_id": user_id,
                "profile_dir": profile_dir,
                "created_at": time.time(),
            }
            return s
        await self.cas_update(mutate)

    async def get_session_meta(self, session_id: str) -> dict | None:
        """Retrieve session metadata (read from cache)."""
        cache = await self._ensure_cache()
        meta = cache.get(KEY_SESSION_META, {})
        return meta.get(session_id)

    async def remove_session_meta(self, session_id: str) -> None:
        """Remove session metadata on close."""
        def mutate(s):
            meta = s.get(KEY_SESSION_META, {})
            meta.pop(session_id, None)
            return s
        await self.cas_update(mutate)

    async def incr_session_count(self) -> int:
        def mutate(s):
            c = int(s.get(KEY_SESSION_COUNTER, 0)) + 1
            s[KEY_SESSION_COUNTER] = c
            return s
        await self.cas_update(mutate)
        cache = await self._ensure_cache()
        return int(cache.get(KEY_SESSION_COUNTER, 0))

    async def decr_session_count(self) -> int:
        def mutate(s):
            c = max(0, int(s.get(KEY_SESSION_COUNTER, 0)) - 1)
            s[KEY_SESSION_COUNTER] = c
            return s
        result = await self.cas_update(mutate)
        new_count = int(result.get(KEY_SESSION_COUNTER, 0))
        logger.info("decr_session_count: now=%d", new_count)
        return new_count

    async def get_session_count(self) -> int:
        cache = await self._ensure_cache()
        return int(cache.get(KEY_SESSION_COUNTER, 0))

    async def try_acquire_session_slot(self, max_concurrent: int) -> bool:
        ok = [False]

        def mutate(s):
            count = int(s.get(KEY_SESSION_COUNTER, 0))
            if count >= max_concurrent:
                return None  # Abort CAS — at capacity
            s[KEY_SESSION_COUNTER] = count + 1
            ok[0] = True
            return s

        await self.cas_update(mutate)
        return ok[0]

    async def close(self) -> None:
        self._local_cache = None


# ═══════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════


def create_state_store() -> StateStore:
    """Create appropriate StateStore based on environment.

    Priority:
    1. If ``KUBERNETES_SERVICE_HOST`` is set (running inside K8s) and the
       state ConfigMap is readable → ``K8sSharedState``
    2. Otherwise → ``InMemoryStateStore`` (backward-compatible default)
    """
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        ns = os.getenv("KUBERNETES_NAMESPACE", "agent-browser")
        logger.info(
            "Detected K8s environment (ns=%s), using K8sSharedState", ns
        )
        return K8sSharedState(namespace=ns)

    logger.info("Not running in K8s, using InMemoryStateStore")
    return InMemoryStateStore()
