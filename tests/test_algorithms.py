import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.algorithms import (RollingWindow, SegmentTree, bfs_distances, bfs_path, dfs_reachable, find_range,
                             find_range_linear, hot_episodes, plan_actions_brute, plan_actions_dp,
                             plan_actions_greedy, top_k, window_max_deque, window_max_naive)


def test_rolling_window_mean_max_rise_and_eviction():
    w = RollingWindow(span_s=600)
    for ts, v in [(0, 30), (60, 33), (120, 31), (180, None), (240, 36)]:
        w.push(ts, v)
    assert len(w) == 4 and w.max() == 36 and w.rise() == 6
    assert abs(w.mean() - 32.5) < 1e-9
    w.push(700, 34)                      # 0 and 60 leave the window (ts < 100)
    assert w.max() == 36 and w.rise() == 3 and len(w) == 3


def test_rolling_max_matches_brute_force():
    rng = random.Random(1)
    w = RollingWindow(span_s=10)
    seen = []
    for ts in range(500):
        v = rng.randint(20, 50)
        w.push(ts, v)
        seen.append((ts, v))
        assert w.max() == max(x for t, x in seen if t >= ts - 10)


def test_window_max_deque_equals_naive():
    rng = random.Random(2)
    vals = [rng.random() for _ in range(300)]
    for k in (1, 2, 7, 60):
        assert window_max_deque(vals, k) == window_max_naive(vals, k)


def test_find_range_binary_equals_linear():
    ts = list(range(0, 10000, 60))
    for t0, t1 in [(0, 60), (125, 3600), (9999, 20000), (-5, 0)]:
        assert find_range(ts, t0, t1) == find_range_linear(ts, t0, t1)


def test_top_k_order_and_ties():
    assert top_k([3, 9, 1, 9, 7], 3) == [9, 9, 7]
    data = [("a", 40.1), ("b", 52.2), ("c", 44.0)]
    assert [n for n, _ in top_k(data, 2, key=lambda x: x[1])] == ["b", "c"]


def test_hot_episodes_split_on_cool_and_gap():
    r = [(0, 39), (60, 41), (120, 43), (180, 39), (240, 42), (600, 41)]
    eps = hot_episodes(r, threshold=40, max_gap_s=180)
    assert [(e["start"], e["end"], e["peak"]) for e in eps] == [(60, 120, 43), (240, 240, 42), (600, 600, 41)]


def test_segment_tree_matches_slices_and_updates():
    rng = random.Random(3)
    vals = [rng.uniform(25, 50) for _ in range(257)]
    st = SegmentTree(vals)
    for _ in range(200):
        a = rng.randrange(0, 257)
        b = rng.randrange(a + 1, 258)
        assert st.query(a, b) == max(vals[a:b])
    st.update(10, 99.0)
    vals[10] = 99.0
    assert st.query(0, 257) == 99.0
    assert SegmentTree([None, None]).query(0, 2) is None


ACTIONS = [("unplug", 30, 4), ("brightness", 12, 1), ("power_saver", 15, 2), ("close_game", 40, 6)]


def test_dp_is_optimal_and_greedy_can_fail():
    assert plan_actions_dp(ACTIONS, 30)[0] == plan_actions_brute(ACTIONS, 30)[0]
    # counter-example: greedy takes the best ratio first and overshoots in cost
    acts = [("a", 10, 1), ("b", 30, 5), ("c", 30, 5)]
    assert plan_actions_dp(acts, 40) == (6, ["a", "b"])
    assert plan_actions_greedy(acts, 40)[0] == 6
    acts2 = [("x", 6, 1), ("y", 10, 2), ("z", 10, 2)]
    assert plan_actions_dp(acts2, 20)[0] == 4 and plan_actions_greedy(acts2, 20)[0] == 5
    assert plan_actions_dp(ACTIONS, 10_000) == (None, [])


def test_dp_matches_brute_force_on_random_inputs():
    rng = random.Random(4)
    for _ in range(60):
        acts = [(f"a{i}", rng.randint(1, 30), rng.randint(1, 9)) for i in range(rng.randint(1, 7))]
        need = rng.randint(1, 80)
        assert plan_actions_dp(acts, need)[0] == plan_actions_brute(acts, need)[0]


def test_graph_search():
    g = {"welcome": ["home"], "home": ["actions", "log", "apps", "settings"], "alert": ["actions", "home"],
         "actions": ["home"], "log": ["home"], "apps": ["home"], "settings": ["home"]}
    assert bfs_distances(g, "welcome")["actions"] == 2
    assert bfs_path(g, "log", "actions") == ["log", "home", "actions"]
    assert "alert" not in dfs_reachable(g, "welcome")
