# pointwise —— 层级金额汇总与子树改挂

仅使用 Python 标准库实现的 `hierarchy.Hierarchy(nodes, root)`，支持：

| 操作 | 语义 | 复杂度（期望/摊还） |
| --- | --- | --- |
| `set_amount(id, value)` | 替换直属金额 | O(log N) |
| `move(id, parent)` | 整棵子树改挂（成为 parent 最后一个孩子） | O(log N) |
| `total(id)` | 含自身的子树金额和 | O(log N) |

空间 O(N)，固定容量上限 200 000 节点。**不扫描任何后代，也不逐级更新祖先。**

## 1. 索引设计：entry/exit 欧拉序列 + 隐式 Treap

把层级树用一次 DFS 展平成序列：下行时发 `entry(x)`（持有 x 的直属金额），
回溯时发 `exit(x)`（金额恒为 0）。例如

```
r(0)
├─ a(2)
│  └─ c(3)
└─ b(5)
```

展开为 `r入 a入 c入 c出 a出 b入 b出 r出`。该序列由一棵**隐式 Treap**
（按序列位置 split/merge 的随机优先级 BST）维护，每个 Treap 节点附加
`size`（子树位置数）与 `sum`（子树金额和）。

### 索引不变量

- **I1 区间不变量**：任意逻辑节点 x 的子树，恰好对应序列上的连续闭区间
  `[entry(x), exit(x)]`；entry 持金额、exit 为 0，所以
  `total(x) = 区间和(entry..exit)`。
- **I2 聚合不变量**：每个 Treap 节点满足
  `size = 1 + size(L) + size(R)`、`sum = value + sum(L) + sum(R)`，
  在每次 `pull`（沿旋转/分裂路径）后重建。
- **I3 父指针不变量**：Treap 的 `parent` 与实际左右孩子互为一致，树根
  `parent is None`；`rank` 沿此链 O(树高) 求序列下标。
- **I4 映射不变量**：`_ent[x]/_ext[x]` 永远指向 x 当前的 entry/exit 节点，
  改挂只整体搬动区间，不新建/删除 Treap 节点，映射无需修改。

### 三个操作如何维持不变量

- `total`：在完整树上取 `rank(entry)`、`rank(exit)`，用两次前缀和之差得区间和。
- `set_amount`：改 entry 的 value，沿 Treap 父链 `pull` 重算 sum
  （只走 O(log N) 个 Treap 节点，与逻辑祖先链无关）。
- `move(x, p)`：所有下标在**任何分裂之前**于完整树上取齐，然后
  1. `split` 出 `A | [entry(x)..exit(x)] | C`；
  2. 推导 `exit(p)` 在 `A+C` 中的相对位置（若原位置在被切区间之后则减去区间长度）；
  3. 在 `exit(p)` 前切开并把整段区间 `merge` 回去。

  区间连续搬动，I1 自动保持；split/merge 路径上的 pull 保持 I2；
  契约保证返回树根 `parent=None`、树内指针一致，保持 I3；只改一个逻辑父指针。

### 为什么是 O(log N)

随机 64 位优先级（固定种子，构造期笛卡尔树 O(N) 建堆）使 Treap 期望树高
O(log N)。split/merge/rank/前缀和都只走根到叶路径；`move` 含常数次
split/merge，故三操作期望且摊还 O(log N)，与被移动子树的大小无关。

## 2. 错误语义（全部先校验、后改状态，失败不产生任何变更）

- 构造：ID 非互异/非非空字符串、金额为布尔或非整数、根 parent 非 None、
  父节点不存在、多根/成环/不可达、超过 20 万节点 → `ValueError`。
- `set_amount`：未知 ID、布尔或非整数金额 → `ValueError`。
- `move`：未知 ID、移动根、挂到自身、挂到自己后代（成环）→ `ValueError`；
  同父改挂为空操作，结构与合计均不变。

## 3. 调度与运行时配置

`.pointwise-runtime.json`（`version=1, kind="cli"`）描述各阶段 argv：

```jsonc
{
  "version": 1, "kind": "cli",
  "setup":  [["python3", "-I", "pointwise/pointwise_cli.py", "demo"]],
  "verify": [["python3", "-I", "pointwise/pointwise_cli.py", "verify", ...]],
  "demo":   [["python3", "-I", "pointwise/pointwise_cli.py", "demo"]],
  "bench":  [["python3", "-I", "pointwise/pointwise_cli.py", "bench", ...]]
}
```

```bash
python3 -I run_pointwise.py          # setup→verify→demo→bench
python3 -I run_pointwise.py verify   # 单阶段
```

- `demo`：题目给定示例的完整改挂过程；
- `verify`：固定种子，随机生成树并交错执行三种操作，与**朴素遍历参照**
  （`total` 真实 DFS 扫后代、`move` 只改父指针）逐步差分，含全量 total、
  父指针对照及全部非法输入族；
- `bench`：深链与 10 万节点大子树改挂的索引访问数、耗时、峰值内存（`tracemalloc`）。

"索引访问数"定义为一次操作中 split/merge/rank/前缀和实际触达的 Treap
节点数（模块级计数器），用于量化 O(log N) 与"不扫后代"。

## 4. 实测结果（N = 200 000，CPython，Linux 容器）

```
[深链 N=200000]
  初始化耗时约 6.0 s，峰值内存约 140 MiB
  末端 total    ：索引访问 111 次（log2 N ≈ 17），约 50 µs
  中段 set_amount：索引访问 22 次，约 20 µs
  朴素 total 对照：每次触达 200 000 个节点（O(N)），与 Treap 的 111 次
                  （O(log N)）形成本质差异；微秒级 wall time 受 CPython
                  C 级列表操作影响，故以访问节点数为准

[大子树改挂] 子树 100 000、整体 200 000，200 次往返改挂
  单次平均约 45 µs，索引访问平均约 180 次
  访问数只随 log N 增长，与被搬动的 10 万节点子树大小无关
  改挂后 total 与朴素遍历完全一致
```

每个逻辑节点对应 entry+exit 两个 `_Node`（`__slots__`），共 2N 个
Treap 节点；20 万逻辑节点实测峰值约 140 MiB。

## 5. 文件清单

| 文件 | 作用 |
| --- | --- |
| `pointwise/hierarchy.py` | `Hierarchy` 与隐式 Treap（仅标准库） |
| `pointwise/pointwise_cli.py` | demo / verify / bench 子命令及朴素参照 |
| `pointwise/_stress.py` | 随机压力 + 结构不变量校验 + 20 万冒烟 |
| `run_pointwise.py` | 读取 runtime JSON 的调度器 |
| `.pointwise-runtime.json` | 调度描述 |
