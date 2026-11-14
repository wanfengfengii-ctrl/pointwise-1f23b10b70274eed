# -*- coding: utf-8 -*-
"""调度器：读取 .pointwise-runtime.json 并依次执行 argv 数组。

  python3 -I run_pointwise.py [setup|verify|demo|bench|all]

仅使用标准库；子进程以 -I 隔离模式启动，相对路径相对仓库根解析。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

RUNTIME = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       ".pointwise-runtime.json")
PHASES = ("setup", "verify", "demo", "bench")


def main(phase="all") -> int:
    with open(RUNTIME, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    if cfg.get("version") != 1 or cfg.get("kind") != "cli":
        raise SystemExit("不支持的 runtime 描述: version/kind 不匹配")

    phases = PHASES if phase == "all" else (phase,)
    root = os.path.dirname(RUNTIME)
    for name in phases:
        for argv in cfg.get(name, []):
            print("\n$ %s" % " ".join(argv), flush=True)
            proc = subprocess.run(argv, cwd=root)
            if proc.returncode != 0:
                print("阶段 %s 失败，退出码 %d" % (name, proc.returncode),
                      file=sys.stderr)
                return proc.returncode
    print("\n全部阶段完成 ✓")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target not in PHASES + ("all",):
        raise SystemExit("未知阶段: %s（可选 %s/all）" % (target, "/".join(PHASES)))
    raise SystemExit(main(target))
