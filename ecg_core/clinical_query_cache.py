"""Bounded, process-local reuse for read-only clinical projections.

No files, persisted diagnoses, or client responses are cached here. Callers must
bind keys to the current source/build and review revision, validate builds before
publishing, and validate the identity again after projection. The owned index
never leaves this cache; only a defensive copy of the small query result does.
"""
from collections import OrderedDict
from concurrent.futures import Future, TimeoutError
from copy import deepcopy
import threading


class ClinicalQueryBusy(RuntimeError):
    pass


class ClinicalQueryCache:
    busy_message = '当前事件索引仍在读取，请稍后重新读取；未返回旧数据。'

    def __init__(self, max_entries=2, max_units=300_000, wait_seconds=30):
        if max_entries < 1 or max_units < 1 or wait_seconds <= 0:
            raise ValueError('Invalid query-cache limits')
        self.max_entries = max_entries
        self.max_units = max_units
        self.wait_seconds = wait_seconds
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._pending = {}
        self._units = 0

    @staticmethod
    def _weight(index):
        # Structural retention bound, not a claim of exact Python/RSS bytes.
        return (len(index['rows']) + len(index['events'])
                + sum(len(e['target_samples']) for e in index['events']))

    def _get(self, key, build):
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key][0]
            pending = self._pending.get(key)
            owner = pending is None
            if owner:
                pending = self._pending[key] = Future()
        if not owner:
            try:
                return pending.result(timeout=self.wait_seconds)
            except TimeoutError as error:
                if pending.done():
                    # A completed builder may itself have raised TimeoutError.
                    # Preserve that failure, rather than reporting a busy cache.
                    return pending.result()
                # Do not cancel the original build or start duplicate work.
                raise ClinicalQueryBusy(self.busy_message) from error
        try:
            index = build()  # Identity must be checked by build before returning.
            weight = self._weight(index)
            with self._lock:
                # A new successful revision supersedes retained older versions
                # of this case; in-flight consumers retain their own reference.
                for old in [k for k in self._entries if k[0] == key[0]]:
                    self._units -= self._entries.pop(old)[1]
                if weight <= self.max_units:
                    while self._entries and (len(self._entries) >= self.max_entries
                                             or self._units + weight > self.max_units):
                        _, (_, size) = self._entries.popitem(last=False)
                        self._units -= size
                    self._entries[key] = (index, weight)
                    self._units += weight
                pending.set_result(index)
            return index
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._lock:
                if self._pending.get(key) is pending:
                    del self._pending[key]

    def project(self, key, build, project):
        """project is a trusted read-only function; never hand the index to UI."""
        return deepcopy(project(self._get(key, build)))

    def retention(self):
        """Diagnostics with no case IDs, source digests, or patient information."""
        with self._lock:
            return dict(entries=len(self._entries), units=self._units,
                        pending=len(self._pending), max_entries=self.max_entries,
                        max_units=self.max_units)


class WaveformBeatCache(ClinicalQueryCache):
    """Private EditedRecords for waveform labels only, never for mutable analyses.

    Reuse the proven single-flight/LRU machinery, but count all retained feed
    collections. The limit is structural units, not a measured byte/RSS bound.
    Callers must only project small label windows, not return the owned feed.
    """
    busy_message = '当前波形心搏索引仍在读取，请稍后重新读取；未返回旧数据。'

    def __init__(self, max_entries=2, max_units=600_000, wait_seconds=30):
        super().__init__(max_entries, max_units, wait_seconds)

    @staticmethod
    def _weight(feed):
        return (len(feed.beats) + len(feed.markers) + len(feed.records)
                + len(feed.record_samples) + len(feed.by_sample)
                + len(feed.document['changes'])
                + len(getattr(feed, 'excluded_rhythm_intervals', ())))
