"""Algorithms and data structures used by Harara (M269).

Everything here is pure Python and unit-tested; complexities are noted per function.
"""
import heapq
from bisect import bisect_left, bisect_right
from collections import deque


# ----------------------------------------------------------------- sliding window
class RollingWindow:
    """Readings from the last `span_s` seconds with O(1) amortised push, mean, max and rise.

    - mean: a running sum, updated when values enter or leave.
    - max:  a *monotonic deque* whose values decrease from front to back, so the
            front is always the window maximum. Each value is added and removed at
            most once, so n pushes cost O(n) in total.
    """

    def __init__(self, span_s: float):
        self.span = span_s
        self.items = deque()      # (ts, value) in time order
        self.maxq = deque()       # (ts, value), values strictly decreasing
        self.total = 0.0

    def push(self, ts: float, value) -> None:
        if value is None:
            return
        self.items.append((ts, value))
        self.total += value
        while self.maxq and self.maxq[-1][1] <= value:
            self.maxq.pop()
        self.maxq.append((ts, value))
        self._evict(ts)

    def _evict(self, now: float) -> None:
        limit = now - self.span
        while self.items and self.items[0][0] < limit:
            ts, v = self.items.popleft()
            self.total -= v
            if self.maxq and self.maxq[0][0] == ts:
                self.maxq.popleft()

    def __len__(self):
        return len(self.items)

    def mean(self):
        return self.total / len(self.items) if self.items else None

    def max(self):
        return self.maxq[0][1] if self.maxq else None

    def rise(self):
        """Newest value minus oldest value in the window (None if < 2 values)."""
        if len(self.items) < 2:
            return None
        return self.items[-1][1] - self.items[0][1]


def window_max_naive(values, k):
    """Max of every window of k consecutive values — O(n·k), for comparison."""
    return [max(values[i - k + 1:i + 1]) for i in range(k - 1, len(values))]


def window_max_deque(values, k):
    """Max of every window of k consecutive values — O(n) with a monotonic deque."""
    q, out = deque(), []
    for i, v in enumerate(values):
        while q and values[q[-1]] <= v:
            q.pop()
        q.append(i)
        if q[0] <= i - k:
            q.popleft()
        if i >= k - 1:
            out.append(values[q[0]])
    return out


# ----------------------------------------------------------------- searching
def find_range(sorted_ts, t0, t1):
    """Indices [lo, hi) of timestamps with t0 <= ts < t1 — O(log n) binary search."""
    return bisect_left(sorted_ts, t0), bisect_left(sorted_ts, t1)


def find_range_linear(ts_list, t0, t1):
    """Same result with a linear scan — O(n), for comparison."""
    lo = next((i for i, t in enumerate(ts_list) if t >= t0), len(ts_list))
    hi = next((i for i, t in enumerate(ts_list) if t >= t1), len(ts_list))
    return lo, hi


def count_at_or_below(sorted_values, x):
    return bisect_right(sorted_values, x)


# ----------------------------------------------------------------- top-k
def top_k(items, k, key=lambda x: x):
    """k largest items, largest first — O(n log k) with a min-heap of size k."""
    heap = []
    for i, item in enumerate(items):
        entry = (key(item), i, item)          # i breaks ties without comparing items
        if len(heap) < k:
            heapq.heappush(heap, entry)
        elif entry[0] > heap[0][0]:
            heapq.heapreplace(heap, entry)
    return [e[2] for e in sorted(heap, key=lambda e: (-e[0], e[1]))]


# ----------------------------------------------------------------- episodes
def hot_episodes(readings, threshold=40.0, max_gap_s=180):
    """Group consecutive hot readings into episodes — one linear scan, O(n).

    readings: iterable of (ts, temp) sorted by ts. A gap longer than max_gap_s
    or a reading below the threshold ends the current episode.
    """
    episodes, cur = [], None
    for ts, temp in readings:
        if temp is None:
            continue
        if temp >= threshold:
            if cur and ts - cur["end"] <= max_gap_s:
                cur["end"] = ts
                cur["peak"] = max(cur["peak"], temp)
                cur["n"] += 1
            else:
                cur = {"start": ts, "end": ts, "peak": temp, "n": 1}
                episodes.append(cur)
        else:
            cur = None
    return episodes


# ----------------------------------------------------------------- segment tree
class SegmentTree:
    """Range-maximum queries in O(log n) after an O(n) build (iterative, array-based)."""

    NEG = float("-inf")

    def __init__(self, values):
        self.n = len(values)
        self.t = [self.NEG] * (2 * self.n)
        for i, v in enumerate(values):
            self.t[self.n + i] = self.NEG if v is None else v
        for i in range(self.n - 1, 0, -1):
            self.t[i] = max(self.t[2 * i], self.t[2 * i + 1])

    def update(self, i, value):
        i += self.n
        self.t[i] = value
        while i > 1:
            i //= 2
            self.t[i] = max(self.t[2 * i], self.t[2 * i + 1])

    def query(self, lo, hi):
        """max(values[lo:hi]); None if the range has no values."""
        res = self.NEG
        lo += self.n
        hi += self.n
        while lo < hi:
            if lo & 1:
                res = max(res, self.t[lo])
                lo += 1
            if hi & 1:
                hi -= 1
                res = max(res, self.t[hi])
            lo //= 2
            hi //= 2
        return None if res == self.NEG else res


# ----------------------------------------------------------------- action planning
def plan_actions_dp(actions, need):
    """Cheapest set of actions whose cooling adds up to at least `need`.

    actions: list of (name, cooling, cost) with integer cooling (e.g. tenths of °C)
    and integer cost (how much the action disturbs the user). 0/1 knapsack variant,
    dynamic programming in O(n · need) time — pseudo-polynomial.
    Returns (total_cost, [names]) or (None, []) if `need` cannot be reached.
    """
    INF = float("inf")
    best = [0] + [INF] * need               # best[c] = min cost to reach cooling c (capped)
    choice = [[] for _ in range(need + 1)]
    for name, cool, cost in actions:
        for c in range(need, -1, -1):       # backwards: each action used at most once
            if best[c] == INF:
                continue
            nc = min(need, c + cool)
            if best[c] + cost < best[nc]:
                best[nc] = best[c] + cost
                choice[nc] = choice[c] + [name]
    return (None, []) if best[need] == INF else (best[need], choice[need])


def plan_actions_greedy(actions, need):
    """Take actions by best cooling-per-cost ratio until `need` is met — O(n log n), not always optimal."""
    total_cool, total_cost, names = 0, 0, []
    for name, cool, cost in sorted(actions, key=lambda a: a[1] / a[2], reverse=True):
        if total_cool >= need:
            break
        total_cool += cool
        total_cost += cost
        names.append(name)
    return (total_cost, names) if total_cool >= need else (None, [])


def plan_actions_brute(actions, need):
    """Try all 2^n subsets — O(2^n · n); only to check the DP on small inputs."""
    from itertools import combinations
    best = (None, [])
    for r in range(len(actions) + 1):
        for combo in combinations(actions, r):
            if sum(a[1] for a in combo) >= need:
                cost = sum(a[2] for a in combo)
                if best[0] is None or cost < best[0]:
                    best = (cost, [a[0] for a in combo])
    return best


# ----------------------------------------------------------------- graphs
def bfs_distances(graph, start):
    """Fewest edges from start to every reachable node — O(V + E)."""
    dist = {start: 0}
    q = deque([start])
    while q:
        u = q.popleft()
        for v in graph.get(u, ()):
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def bfs_path(graph, start, goal):
    prev, q, seen = {}, deque([start]), {start}
    while q:
        u = q.popleft()
        if u == goal:
            path = [u]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return path[::-1]
        for v in graph.get(u, ()):
            if v not in seen:
                seen.add(v)
                prev[v] = u
                q.append(v)
    return None


def dfs_reachable(graph, start):
    """Nodes reachable from start, iterative depth-first search — O(V + E)."""
    seen, stack = set(), [start]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(v for v in graph.get(u, ()) if v not in seen)
    return seen
