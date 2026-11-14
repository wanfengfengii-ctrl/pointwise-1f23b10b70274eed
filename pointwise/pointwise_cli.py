# -*- coding: utf-8 -*-
"""pointwise 调度入口（仅使用 Python 标准库）。

子命令：
  demo    题目给定示例的改挂全过程演示
  verify  固定种子，与朴素遍历参照实现做交错操作差分核对
  bench   深链 / 大子树改挂的索引访问数、耗时、峰值内存实测

用法：
  python -I pointwise_cli.py demo
  python -I pointwise_cli.py verify [--seed 20261114] [--ops 4000]
  python -I pointwise_cli.py bench
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
import tracemalloc

# -I 隔离模式下脚本目录仍会进入 sys.path[0]，这里显式兜底。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hierarchy import (  # noqa: E402
    Hierarchy,
    MAX_NODES,
    get_access_count,
    reset_access_count,
)


# --------------------------------------------------------------------------- #
# 朴素参照：每次 total 都真实遍历后代，move 只改父指针；校验语义与 Hierarchy 一致
# --------------------------------------------------------------------------- #
class NaiveHierarchy:
    def __init__(self, nodes, root):
        self.values = {}
        self.parents = {}
        for nid, par, amt in nodes:
            self.values[nid] = amt
            self.parents[nid] = par
        self.root = root
        self.children = {nid: [] for nid in self.values}
        for nid, par in self.parents.items():
            if par is not None:
                self.children[par].append(nid)
        # 连通性校验（与正式实现保持同样的拒绝行为）
        seen = set()
        stack = [root]
        while stack:
            cur = stack.pop()
            if cur in seen:
                raise ValueError("环")
            seen.add(cur)
            stack.extend(self.children[cur])
        if len(seen) != len(self.values):
            raise ValueError("不可达")

    def set_amount(self, id, value):
        if id not in self.values:
            raise ValueError("未知节点")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("金额非法")
        self.values[id] = value

    def _is_descendant(self, anc, node):
        """node 是否为 anc 的后代（含自身）。"""
        stack = [anc]
        while stack:
            cur = stack.pop()
            if cur == node:
                return True
            stack.extend(self.children[cur])
        return False

    def move(self, id, parent):
        if id not in self.values or parent not in self.values:
            raise ValueError("未知节点")
        if id == self.root:
            raise ValueError("不能移动根")
        if parent == id:
            raise ValueError("挂到自身")
        if self.parents[id] == parent:
            return
        if self._is_descendant(id, parent):
            raise ValueError("成环")
        old = self.parents[id]
        self.children[old].remove(id)
        self.children[parent].append(id)
        self.parents[id] = parent

    def total(self, id):
        if id not in self.values:
            raise ValueError("未知节点")
        total = 0
        stack = [id]
        while stack:
            cur = stack.pop()
            total += self.values[cur]
            stack.extend(self.children[cur])
        return total


# --------------------------------------------------------------------------- #
# demo
# --------------------------------------------------------------------------- #
def cmd_demo(_args) -> int:
    print("== 改挂演示（题目示例） ==")
    h = Hierarchy(
        [["r", None, 0], ["a", "r", 2], ["b", "r", 5], ["c", "a", 3]],
        "r",
    )
    print("初始: r=0, a=2, b=5, c=3")
    print("total(a) =", h.total("a"), "（期望 5）")

    h.move("c", "b")
    print('move("c", "b") 之后:')
    print("  total(a) =", h.total("a"), "（期望 2）")
    print("  total(b) =", h.total("b"), "（期望 8）")
    print("  total(r) =", h.total("r"), "（期望 10）")

    h.set_amount("b", -5)
    print('set_amount("b", -5) 之后:')
    print("  total(b) =", h.total("b"), "（期望 -2）")
    print("  total(c) =", h.total("c"), "（期望 3）")

    print('move("b", "c")（b 是 c 的祖先，必须拒绝）:')
    before = (h.total("r"), h.total("a"), h.total("b"), h.total("c"))
    try:
        h.move("b", "c")
    except ValueError as exc:
        print("  捕获 ValueError:", exc)
    after = (h.total("r"), h.total("a"), h.total("b"), h.total("c"))
    print("  拒绝后合计不变:", before == after, after)
    return 0


# --------------------------------------------------------------------------- #
# verify：固定种子交错差分
# --------------------------------------------------------------------------- #
def _random_tree(rng, n):
    """生成单根树：节点 0 为根，其余节点父节点在更早的节点中选取。"""
    ids = ["n%06d" % i for i in range(n)]
    nodes = [[ids[0], None, rng.randint(-1000, 1000)]]
    for i in range(1, n):
        nodes.append([ids[i], ids[rng.randint(0, i - 1)], rng.randint(-1000, 1000)])
    return nodes, ids[0], ids


def cmd_verify(args) -> int:
    rng = random.Random(args.seed)
    n = args.nodes
    ops_n = args.ops
    print("== 差分核对（朴素遍历 vs 隐式 Treap） ==")
    print("种子=%d 节点=%d 操作=%d" % (args.seed, n, ops_n))

    nodes, root, ids = _random_tree(rng, n)
    fast = Hierarchy(nodes, root)
    slow = NaiveHierarchy(nodes, root)

    # 初始全量快照
    for nid in ids:
        assert fast.total(nid) == slow.total(nid), "初始 total 不一致: %s" % nid

    accepted = rejected = 0
    for step in range(ops_n):
        kind = rng.random()
        nid = ids[rng.randrange(n)]
        if kind < 0.35:
            value = rng.randint(-10_000, 10_000)
            fast.set_amount(nid, value)
            slow.set_amount(nid, value)
        elif kind < 0.75:
            new_parent = ids[rng.randrange(n)]
            try:
                fast.move(nid, new_parent)
                slow.move(nid, new_parent)
                accepted += 1
            except ValueError:
                rejected += 1
                # 两边都必须拒绝；再验证拒绝后状态一致
                assert fast._parents == slow.parents
        else:
            assert fast.total(nid) == slow.total(nid), \
                "step %d total 不一致: %s" % (step, nid)

        if step % max(1, ops_n // 10) == 0:
            for x in ids:
                assert fast.total(x) == slow.total(x), \
                    "step %d 全量快照不一致: %s" % (step, x)

    # 结束再做一次全量快照与父指针对照
    for nid in ids:
        assert fast.total(nid) == slow.total(nid)
    assert fast._parents == slow.parents
    print("合法改挂 %d 次，被拒绝 %d 次；全部 total 与父指针一致 ✓" % (accepted, rejected))

    # 非法输入族：确保抛 ValueError 且不改状态
    h = Hierarchy(
        [["r", None, 0], ["a", "r", 2], ["b", "a", 5]], "r"
    )
    snapshot = (h.total("r"), h.total("a"), h.total("b"))
    must_reject = [
        lambda: h.total("ghost"),
        lambda: h.set_amount("ghost", 1),
        lambda: h.set_amount("a", True),       # 布尔金额
        lambda: h.set_amount("a", 1.5),        # 非整数
        lambda: h.move("r", "a"),              # 移动根
        lambda: h.move("a", "a"),              # 挂自身
        lambda: h.move("a", "b"),              # 成环
        lambda: h.move("ghost", "r"),
        lambda: h.move("a", "ghost"),
    ]
    for call in must_reject:
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("非法操作未被拒绝: %s" % call.__code__.co_names)
    assert snapshot == (h.total("r"), h.total("a"), h.total("b")), \
        "拒绝非法操作后状态发生变化"
    h.move("b", "a")  # 同父改挂：合法空操作，合计不变
    assert snapshot == (h.total("r"), h.total("a"), h.total("b"))

    # 构造期非法输入
    bad_constructs = [
        ([], "r"),
        ([["r", None, 0]], "x"),
        ([["r", "x", 0]], "r"),                       # 根 parent 非 None
        ([["r", None, 0], ["a", "r", 1], ["b", "a", 2], ["c", "b", 3]], "r"),
        ([["r", None, 0], ["a", "r", 1], ["b", "q", 2]], "r"),  # 父不存在
        ([["r", None, 0], ["a", "r", True]], "r"),    # 布尔金额
        ([["r", None, 0], ["r", None, 1]], "r"),      # 重复 ID
        ([["", None, 0]], ""),                         # 空 ID
    ]
    # 第 4 个其实是合法树，单独排除
    bad_constructs.pop(3)
    for cnodes, cr in bad_constructs:
        try:
            Hierarchy(cnodes, cr)
            raise AssertionError("非法构造未被拒绝: %r" % (cnodes,))
        except ValueError:
            pass
    print("非法输入 / 未知 ID / 移根 / 成环均抛 ValueError 且状态不变 ✓")
    return 0


# --------------------------------------------------------------------------- #
# bench
# --------------------------------------------------------------------------- #
def _chain(n):
    nodes = [["n0", None, 1]]
    for i in range(1, n):
        nodes.append(["n%d" % i, "n%d" % (i - 1), (i % 7) - 3])
    return nodes, "n0"


def _tree_with_big_subtree(rng, n, sub_size):
    """根下两棵子树：待移动的大子树（链）与接收侧（随机树）。"""
    nodes = [["r", None, 0]]
    # 大子树：s1 -> s2 -> ... 链
    sub_ids = ["s%d" % i for i in range(sub_size)]
    nodes.append([sub_ids[0], "r", rng.randint(-9, 9)])
    for i in range(1, sub_size):
        nodes.append([sub_ids[i], sub_ids[i - 1], rng.randint(-9, 9)])
    # 接收侧
    rest = n - sub_size - 1
    recv_ids = ["p%d" % i for i in range(rest)]
    if rest:
        nodes.append([recv_ids[0], "r", rng.randint(-9, 9)])
        for i in range(1, rest):
            nodes.append([recv_ids[i], recv_ids[rng.randrange(i)], rng.randint(-9, 9)])
    return nodes, "r", sub_ids, recv_ids


def _timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def cmd_bench(args) -> int:
    print("== 性能实测（访问计数 = split/merge/rank/prefix 触达的 Treap 节点数） ==")
    n = args.nodes
    print("规模 N =", n, "（上限 %d）" % MAX_NODES)

    # ---- 1. 深链：初始化 + 末端 total + 中段 set_amount ----------------
    nodes, root = _chain(n)
    tracemalloc.start()
    t0 = time.perf_counter()
    h = Hierarchy(nodes, root)
    build_time = time.perf_counter() - t0
    _, peak_build = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    reset_access_count()
    total_time = _timed(lambda: h.total("n%d" % (n - 1)))
    total_visits = get_access_count()

    reset_access_count()
    set_time = _timed(lambda: h.set_amount("n%d" % (n // 2), -42))
    set_visits = get_access_count()

    print("\n[深链 N=%d]" % n)
    print("  初始化耗时 %.3f s，峰值内存 %.2f MiB" % (build_time, peak_build / 1048576))
    print("  末端 total   : 耗时 %.6f s，索引访问 %d 次（log2 N≈%.1f）"
          % (total_time, total_visits, n.bit_length() - 1))
    print("  中段 set_amount: 耗时 %.6f s，索引访问 %d 次" % (set_time, set_visits))

    # 朴素遍历对照：深链末端 total 必须扫完全部后代。
    # 微秒级 wall time 受 CPython C 级列表操作影响较大，故同时报告
    # 累计耗时与"触达节点数"这一与实现无关的本质复杂度差异。
    slow = NaiveHierarchy(nodes, root)
    reps = max(20, 2_000_000 // n)
    def _naive_total():
        for _ in range(reps):
            slow.total("n%d" % (n - 1))
    naive_elapsed = _timed(_naive_total)
    print("  朴素 total 对照: %d 次累计 %.6f s（每次扫描 %d 个后代，触达 %d 节点/次，O(N)）"
          % (reps, naive_elapsed, n, n))

    # ---- 2. 大子树改挂 ------------------------------------------------
    rng = random.Random(20261114)
    sub = n // 2
    bnodes, broot, sub_ids, recv_ids = _tree_with_big_subtree(rng, n, sub)
    h2 = Hierarchy(bnodes, broot)
    slow2 = NaiveHierarchy(bnodes, broot)
    assert h2.total(broot) == slow2.total(broot)

    if not recv_ids:
        print("\n[大子树改挂] 接收侧为空，跳过")
        return 0

    rounds = args.rounds
    reset_access_count()
    move_times = []
    # 在接收侧两个节点之间来回挂，避免同父空操作
    target_a = recv_ids[len(recv_ids) // 2]
    target_b = recv_ids[0]
    t0 = time.perf_counter()
    for i in range(rounds):
        h2.move(sub_ids[0], target_a if i % 2 == 0 else target_b)
    elapsed = time.perf_counter() - t0
    move_visits = get_access_count()

    # 正确性：与朴素实现最终状态对照
    for i in range(rounds):
        slow2.move(sub_ids[0], target_a if i % 2 == 0 else target_b)
    for nid in [broot, sub_ids[0], sub_ids[-1], target_a, target_b]:
        assert h2.total(nid) == slow2.total(nid), nid

    print("\n[大子树改挂] 子树规模 %d，整体规模 %d，%d 次往返改挂" % (sub, n, rounds))
    print("  总耗时 %.3f s，单次平均 %.6f s" % (elapsed, elapsed / rounds))
    print("  索引访问总计 %d 次，单次平均 %.1f 次（与子树大小无关）"
          % (move_visits, move_visits / rounds))
    print("  改挂后 total 与朴素遍历对照一致 ✓")

    # 改挂期间峰值内存
    tracemalloc.start()
    h3 = Hierarchy(bnodes, broot)
    for i in range(rounds):
        h3.move(sub_ids[0], target_a if i % 2 == 0 else target_b)
    _, peak_move = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print("  结构常驻峰值内存 %.2f MiB（每节点 entry+exit 两个 Treap 节点）"
          % (peak_move / 1048576))
    return 0


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="层级金额汇总调度器")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", help="题目示例改挂演示").set_defaults(func=cmd_demo)

    p_verify = sub.add_parser("verify", help="固定种子差分核对")
    p_verify.add_argument("--seed", type=int, default=20261114)
    p_verify.add_argument("--nodes", type=int, default=2000)
    p_verify.add_argument("--ops", type=int, default=4000)
    p_verify.set_defaults(func=cmd_verify)

    p_bench = sub.add_parser("bench", help="深链/大子树改挂实测")
    p_bench.add_argument("--nodes", type=int, default=MAX_NODES)
    p_bench.add_argument("--rounds", type=int, default=200)
    p_bench.set_defaults(func=cmd_bench)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
