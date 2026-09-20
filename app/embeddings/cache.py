"""Bounded, process-local history cache. No resident query texts are retained."""
from collections import OrderedDict
from hashlib import sha256
from threading import Lock

from .base import EmbeddingError, EmbeddingProvider, validate_vectors

CACHE_CAPACITY = 128


class HistoryEmbeddingCache:
    def __init__(self, capacity=CACHE_CAPACITY):
        self.capacity = capacity
        self._values = OrderedDict()
        self._lock = Lock()

    def clear(self):
        with self._lock:
            self._values.clear()

    def vectors(self, provider: EmbeddingProvider, text: str, reports):
        namespace = (provider.name, provider.model)
        keys = [(*namespace, r.id, sha256(r.text.encode()).hexdigest()) for r in reports]
        # Serialise cold fills: concurrent requests do not re-embed the same history.
        with self._lock:
            missing = [i for i, key in enumerate(keys) if key not in self._values]
            inputs = [text] + [reports[i].text for i in missing]
            fresh = validate_vectors(provider.embed(inputs), len(inputs))
            new_history = {keys[i]: vector for i, vector in zip(missing, fresh[1:])}
            history = [new_history[key] if key in new_history else self._values[key] for key in keys]
            try:
                validate_vectors([fresh[0], *history], 1 + len(history))
            except EmbeddingError:
                # A model changing dimensions must not poison the cache indefinitely.
                for key in list(self._values):
                    if key[:2] == namespace:
                        del self._values[key]
                raise
            for key, vector in zip(keys, history):
                self._values[key] = vector
                self._values.move_to_end(key)
            while len(self._values) > self.capacity:
                self._values.popitem(last=False)
            return fresh[0], history


history_cache = HistoryEmbeddingCache()
