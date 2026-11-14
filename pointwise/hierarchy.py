# -*- coding: utf-8 -*-
"""hierarchy.Hierarchy —— 单根树子树金额汇总 / 改挂。

索引（数据结构）
----------------
把每棵层级树表示成一条"先序 + 出节点"序列：每个节点产生两个序列位置
    entry(x), exit(x)
且先序中子树 x 的所有位置恰好构成连续闭区间 [entry(x), exit(x)]。
该序列用隐式 Treap（按序列下标分裂/合并的随机优先级 BST）维护，
Treap 每个节点附加子树节点数 size 与子树金额和 sum。
entry/exit 各自持有半个金额：entry.value = amount, exit.value = 0，因此
    total(x) = 区间和(entry..exit)
移动整棵子树 = 把一段连续区间切下、整体插入到新父节点 exit 之前，
即 Treap 的 split / merge，不需要扫描任何后代，也不逐级修改祖先；
祖先的 total 会随 Treap 旋转路径上的 O(log N) 个 sum 自动维护。

不变量（详见 README.md）：
  I1 先序区间不变量；
  I2 每个 Treap 节点 size/sum 与子树一致；
  I3 父指针与 Treap 实际左右孩子一致；
  I4 _ent/_ext 双向映射不变。
"""

from __future__ import annotations

import random
import sys

# 随机优先级 Treap 的期望深度为 O(log N)；提高上限仅为极端运气下兜底。
sys.setrecursionlimit(1_000_000)

MAX_NODES = 200_000

# 一次操作中 Treap 节点的累计"索引访问"计数（基准测试用）：
# 每次 split / merge / rank / prefix_sum 触达一个真实 Treap 节点计 1。
_ACCESS_COUNT = 0


def reset_access_count() -> None:
    global _ACCESS_COUNT
    _ACCESS_COUNT = 0


def get_access_count() -> int:
    return _ACCESS_COUNT


def _visit() -> None:
    global _ACCESS_COUNT
    _ACCESS_COUNT += 1


class _Node:
    __slots__ = ("prio", "left", "right", "parent", "size", "value", "sum", "owner")

    def __init__(self, value: int, owner: str, prio: int):
        self.prio = prio
        self.left = None
        self.right = None
        self.parent = None
        self.size = 1
        self.value = value
        self.sum = value
        self.owner = owner


def _sz(t):
    return t.size if t is not None else 0


def _sm(t):
    return t.sum if t is not None else 0


def _pull(t: _Node) -> None:
    """由左右孩子重算 size/sum（不修改 parent，由 split/merge 维护）。"""
    t.size = 1 + _sz(t.left) + _sz(t.right)
    t.sum = t.value + _sm(t.left) + _sm(t.right)


def _split(t: _Node, k: int):
    """按前 k 个序列位置分裂：左树含位置 0..k-1，右树含 k..。

    契约：入参 t 须为一棵根（t.parent is None）；返回的两棵树根 parent
    均为 None，树内所有 parent 指针与实际孩子一致。
    """
    if t is None:
        return None, None
    t.parent = None  # 入口兜底：确保入参确实是无父根，阻断向旧树回溯
    _visit()
    left_size = _sz(t.left)
    if k <= left_size:
        a, b = _split(t.left, k)
        t.left = b
        if b is not None:
            b.parent = t
        _pull(t)
        t.parent = None  # t 现在是右返回树的根
        # a 已由递归保证 a.parent is None
        return a, t
    else:
        a, b = _split(t.right, k - left_size - 1)
        t.right = a
        if a is not None:
            a.parent = t
        _pull(t)
        t.parent = None  # t 现在是左返回树的根
        # b 已由递归保证 b.parent is None
        return t, b


def _merge(a: _Node, b: _Node):
    """合并两棵序列树，契约同 _split：入参为根，返回树根 parent 为 None。"""
    if a is None:
        if b is not None:
            b.parent = None
        return b
    if b is None:
        a.parent = None
        return a
    # 入口兜底：递归合并的子树可能仍带着被切分前的旧父指针。
    a.parent = None
    b.parent = None
    _visit()
    if a.prio > b.prio:
        child = _merge(a.right, b)
        a.right = child
        if child is not None:
            child.parent = a
        _pull(a)
        a.parent = None
        return a
    else:
        child = _merge(a, b.left)
        b.left = child
        if child is not None:
            child.parent = b
        _pull(b)
        b.parent = None
        return b


def _rank(t: _Node) -> int:
    """节点 t 在序列中的 0 基下标，沿 parent 指针上行，深度 O(log N)。"""
    r = _sz(t.left)
    cur = t
    _visit()
    while cur.parent is not None:
        p = cur.parent
        if p.right is cur:
            r += _sz(p.left) + 1
        cur = p
        _visit()
    return r


def _prefix_sum(root: _Node, k: int) -> int:
    """序列前 k 个元素（位置 0..k-1）之和。"""
    total = 0
    cur = root
    while cur is not None:
        _visit()
        ls = _sz(cur.left)
        if k <= ls:
            cur = cur.left
        elif k == ls + 1:
            total += _sm(cur.left) + cur.value
            return total
        else:
            total += _sm(cur.left) + cur.value
            k -= ls + 1
            cur = cur.right
    return total


class Hierarchy:
    """固定容量上限 MAX_NODES 的单根树，支持 set_amount / move / total。

    三操作均为 O(树高)，随机优先级下期望且摊还 O(log N)，空间 O(N)。
    任何非法输入均抛 ValueError，且状态保持不变（全部校验先于结构修改）。
    """

    def __init__(self, nodes, root):
        if not isinstance(root, str) or not root:
            raise ValueError("root 必须是非空字符串")
        if not isinstance(nodes, (list, tuple)):
            raise ValueError("nodes 必须是列表/元组")
        if len(nodes) > MAX_NODES:
            raise ValueError("节点数超过上限 %d" % MAX_NODES)

        values = {}
        parents = {}
        for item in nodes:
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                raise ValueError("每个节点须为 [id, parent, 直属金额] 三元组")
            nid, par, amt = item
            if not isinstance(nid, str) or not nid:
                raise ValueError("节点 ID 必须是非空字符串")
            if nid in values:
                raise ValueError("节点 ID 重复: %r" % nid)
            if par is not None and (not isinstance(par, str) or not par):
                raise ValueError("parent 必须为 None 或非空字符串")
            # bool 是 int 的子类，须显式排除。
            if not isinstance(amt, int) or isinstance(amt, bool):
                raise ValueError("金额必须是非布尔整数")
            values[nid] = amt
            parents[nid] = par

        if root not in values:
            raise ValueError("未知根 ID: %r" % root)
        if parents[root] is not None:
            raise ValueError("根节点的 parent 必须为 None")

        children = {nid: [] for nid in values}
        for nid, par in parents.items():
            if nid == root:
                continue
            if par not in values:
                raise ValueError("节点 %r 的父节点 %r 不存在" % (nid, par))
            children[par].append(nid)

        # 从根出发的迭代式 DFS：必须覆盖全部节点，否则为多根/成环（非单根树）。
        seen = set()
        stack = [root]
        while stack:
            cur = stack.pop()
            if cur in seen:
                raise ValueError("层级结构存在环，不是单根树")
            seen.add(cur)
            stack.extend(children[cur])
        if len(seen) != len(values):
            raise ValueError("存在从根不可达的节点，不是单根树")

        rng = random.Random(0xC0FFEE)
        # DFS 展开为 entry/exit 序列：下行发 entry（持有金额），
        # 回溯发 exit（金额 0）。子树 x 的 entry..exit 恰好覆盖其全部后代。
        seq = []  # (value, owner)
        stack = [(root, False)]
        while stack:
            cur, exiting = stack.pop()
            if exiting:
                seq.append((0, cur))
            else:
                seq.append((values[cur], cur))
                stack.append((cur, True))
                # 逆序压栈，使孩子按 children 中的顺序展开
                for ch in reversed(children[cur]):
                    stack.append((ch, False))

        self._ent = {}
        self._ext = {}
        cart_root = None
        cart_stack = []  # 笛卡尔树右脊
        for value, owner in seq:
            node = _Node(value, owner, rng.getrandbits(64))
            if owner not in self._ent:
                self._ent[owner] = node
            else:
                self._ext[owner] = node
            last = None
            while cart_stack and cart_stack[-1].prio < node.prio:
                last = cart_stack.pop()
            node.left = last
            if cart_stack:
                cart_stack[-1].right = node
            else:
                cart_root = node
            cart_stack.append(node)

        # 自顶向下补 parent，再按逆先序 pull 出全部 size/sum。
        cart_root.parent = None
        post = []
        work = [cart_root]
        while work:
            cur = work.pop()
            post.append(cur)
            if cur.left is not None:
                cur.left.parent = cur
                work.append(cur.left)
            if cur.right is not None:
                cur.right.parent = cur
                work.append(cur.right)
        for cur in reversed(post):
            _pull(cur)

        self._root = cart_root
        self._values = values    # 直属金额（逻辑视图）
        self._parents = parents  # 逻辑父指针
        self._root_id_str = root
        self._n = len(values)

    # ------------------------------------------------------------------ #
    # 校验
    # ------------------------------------------------------------------ #
    def _require(self, nid):
        if not isinstance(nid, str) or not nid or nid not in self._values:
            raise ValueError("未知节点 ID: %r" % (nid,))

    # ------------------------------------------------------------------ #
    # 对外操作
    # ------------------------------------------------------------------ #
    def set_amount(self, id, value) -> None:
        """替换节点直属金额。非法时抛 ValueError 且不改状态。"""
        self._require(id)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("金额必须是非布尔整数")
        self._values[id] = value
        t = self._ent[id]
        t.value = value
        # 沿 Treap 父链重算聚合值：O(log N)，不触碰逻辑祖先的独立字段。
        cur = t
        while cur is not None:
            _visit()
            _pull(cur)
            cur = cur.parent

    def move(self, id, parent) -> None:
        """把 id 的整棵子树改挂到 parent 之下（成为其最后一个孩子）。

        - 未知 ID / 移动根 / 挂到自身或自己的后代（成环）→ ValueError
        - parent == 当前父节点：空操作（结构与合计均不变）
        - 全部合法性检查在任何结构修改之前完成，失败不改状态。
        """
        self._require(id)
        self._require(parent)
        if id == self._root_id_str:
            raise ValueError("不能移动根节点")
        if parent == id:
            raise ValueError("不能把节点挂到自身之下")
        if self._parents[id] == parent:
            return  # 同父改挂：不变

        # 所有下标都在完整树上、任何分裂之前取得；之后不再对中间子树调 _rank，
        # 因为分裂返回的子树内部可能残留指向被切走节点的 parent 链。
        ent = self._ent[id]
        ext = self._ext[id]
        pos_ent = _rank(ent)
        pos_ext = _rank(ext)
        pos_parent = _rank(self._ent[parent])
        pos_parent_exit = _rank(self._ext[parent])

        # 成环判定：parent 落在子树 id 的先序闭区间内即说明是其后代。
        if pos_ent <= pos_parent <= pos_ext:
            raise ValueError("改挂会形成环：%r 是 %r 的后代" % (parent, id))

        subtree_len = pos_ext - pos_ent + 1  # = 2 * 逻辑子树大小

        # 1) 切出 A | [ent..ext] | C
        a, rest = _split(self._root, pos_ent)
        mid, c = _split(rest, subtree_len)

        # 2) 父节点 exit 不可能位于 mid 内（后代检查已保证），推导它在 A+C 中的
        #    相对下标：原下标若在 mid 之后，需减去被切走的 subtree_len。
        exit_pos = pos_parent_exit
        if exit_pos > pos_ext:
            exit_pos -= subtree_len
        left, right = _split(_merge(a, c), exit_pos)
        self._root = _merge(_merge(left, mid), right)

        # 仅修改一个逻辑父指针；子树内部所有父子关系原样保留。
        self._parents[id] = parent

    def total(self, id) -> int:
        """返回含自身在内的子树金额和（先序闭区间和）。"""
        self._require(id)
        ent = self._ent[id]
        ext = self._ext[id]
        lo = _rank(ent)
        hi = _rank(ext)
        # sum(0..hi) - sum(0..lo-1)
        return _prefix_sum(self._root, hi + 1) - _prefix_sum(self._root, lo)

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #
    def __len__(self):
        return self._n

    def __contains__(self, id):
        return isinstance(id, str) and id in self._values
