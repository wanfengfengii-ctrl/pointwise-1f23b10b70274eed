# -*- coding: utf-8 -*-
"""随机压力测试：每步后校验 Treap 结构不变量与全量 total（含 20 万规模冒烟）。"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hierarchy import Hierarchy
from pointwise_cli import NaiveHierarchy, _random_tree


def check_treap(h):
    root = h._root
    assert root.parent is None
    stack = [root]
    count = 0
    while stack:
        t = stack.pop()
        count += 1
        if t.left is not None:
            assert t.left.parent is t, ("left parent", t.owner)
            stack.append(t.left)
        if t.right is not None:
            assert t.right.parent is t, ("right parent", t.owner)
            stack.append(t.right)
        exp_sz = 1 + (t.left.size if t.left else 0) + (t.right.size if t.right else 0)
        exp_sm = t.value + (t.left.sum if t.left else 0) + (t.right.sum if t.right else 0)
        assert t.size == exp_sz and t.sum == exp_sm, ("agg", t.owner)
    assert count == 2 * len(h), (count, len(h))


def stress(seed, n, ops):
    rng = random.Random(seed)
    nodes, root, ids = _random_tree(rng, n)
    fast = Hierarchy(nodes, root)
    slow = NaiveHierarchy(nodes, root)
    check_treap(fast)
    for step in range(ops):
        nid = ids[rng.randrange(n)]
        roll = rng.random()
        if roll < 0.3:
            v = rng.randint(-50, 50)
            fast.set_amount(nid, v)
            slow.set_amount(nid, v)
        elif roll < 0.8:
            p = ids[rng.randrange(n)]
            try:
                fast.move(nid, p)
                slow.move(nid, p)
            except ValueError:
                pass
        else:
            assert fast.total(nid) == slow.total(nid)
        if step % 97 == 0:
            check_treap(fast)
            for x in ids:
                assert fast.total(x) == slow.total(x), (step, x)
            assert fast._parents == slow.parents
    check_treap(fast)
    for x in ids:
        assert fast.total(x) == slow.total(x)
    print("seed=%d n=%d ops=%d OK" % (seed, n, ops))


if __name__ == "__main__":
    for seed in (1, 7, 42, 99):
        stress(seed, 500, 3000)
    # 退化形态：深链上的反复改挂
    rng = random.Random(123)
    n = 3000
    nodes = [["n0", None, 1]]
    for i in range(1, n):
        nodes.append(["n%d" % i, "n%d" % (i - 1), rng.randint(-5, 5)])
    h = Hierarchy(nodes, "n0")
    s = NaiveHierarchy(nodes, "n0")
    ids = ["n%d" % i for i in range(n)]
    for _ in range(2000):
        i = rng.randrange(1, n)
        j = rng.randrange(n)
        try:
            h.move(ids[i], ids[j])
            s.move(ids[i], ids[j])
        except ValueError:
            pass
    check_treap(h)
    for x in ids:
        assert h.total(x) == s.total(x)
    print("deep-chain reshuffle OK")
    # 20 万节点构造冒烟（题目上限）
    big, br, _ids = _random_tree(random.Random(5), 200000)
    hb = Hierarchy(big, br)
    check_treap(hb)
    print("200k build OK, total(root) =", hb.total(br))
