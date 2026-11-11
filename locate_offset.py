#!/usr/bin/env python3
"""
locate_offset.py — 用特征码定位 UnityFramework 里的补丁点

不依赖硬编码偏移：在二进制里搜「ScreenAdaption.cctor 里给 WHRateThreshold 赋值」的指令序列。
游戏版本更新导致偏移变化时，跑这个脚本就能拿到新偏移。

用法:
    python3 locate_offset.py <UnityFramework 路径>
    python3 locate_offset.py <UnityFramework 路径> --json report.json

已验证：重返未来：1999 v4.0.0 (build 210) / Unity 2022.3.62f2
        原版与 PlayCover 转换后的二进制均只有 1 处命中。
"""
import argparse
import json
import struct
import sys
from pathlib import Path

# mov  w9, #0xd70a        (0x0000d70a → 低半字)
# movk w9, #0x3c23, lsl #16   → 0x3c23d70a == 0.01f  ← 这就是 WHRateThreshold
# str  w9, [x8, #8]
THRESHOLD_SEQ = bytes.fromhex("49e19a526984a772090900b9")

# movk 指令里嵌入的 float 半字（小端 4 字节里的后两个字节）
OLD_THRESHOLD = bytes.fromhex("6984a772")   # movk w9, #0x3c23, lsl #16
NEW_THRESHOLD = bytes.fromhex("09e8a772")   # movk w9, #0x3f40, lsl #16 → 0.7537f

# DesignWidth / DesignHeight = 1920.0f / 1080.0f（相邻两个 float）
DESIGN_SEQ = struct.pack("<2f", 1920.0, 1080.0)

# 已知的 ZProj.ScreenAdaption 方法（v4.0.0），仅供报告参考
KNOWN_METHODS = {
    "_GetHeightScaleRate": 0x54da6ac,
    "Start":                0x54da7d8,
    "OnWindowsChanged":     0x54daa50,
    "_AutoAdapterMask":     0x54da7dc,
    "LateUpdate":           0x54daa74,
    "OnDestroy":            0x54daaa4,
}


def find_all(data: bytes, pat: bytes):
    hits, i = [], 0
    while True:
        j = data.find(pat, i)
        if j < 0:
            return hits
        hits.append(j)
        i = j + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("binary", type=Path, help="UnityFramework 二进制路径")
    ap.add_argument("--json", type=Path, help="把结果写成 JSON")
    args = ap.parse_args()

    if not args.binary.exists():
        print(f"[!] 找不到 {args.binary}", file=sys.stderr)
        return 1

    data = args.binary.read_bytes()
    print(f"file : {args.binary}")
    print(f"size : {len(data):,} B")

    result = {"file": str(args.binary), "size": len(data), "unityframework_sha256": None}

    # ---- 阈值 ----
    seq_hits = find_all(data, THRESHOLD_SEQ)
    print(f"\n[1] 阈值特征码命中: {len(seq_hits)} 处  {[hex(x) for x in seq_hits]}")
    if len(seq_hits) == 1:
        base = seq_hits[0]
        patch_off = base + 4                      # movk 指令在序列里的位置
        cur = data[patch_off:patch_off + 4]
        f = struct.unpack("<f", OLD_THRESHOLD)[0] if cur == OLD_THRESHOLD else None
        print(f"    movk 位于         : 0x{patch_off:x}")
        print(f"    当前字节          : {cur.hex()}")
        print(f"    当前阈值          : {'0.01f（原始）' if cur == OLD_THRESHOLD else ('0.7537f（已打过补丁）' if cur == NEW_THRESHOLD else '未知')}")
        result["threshold_offset"] = f"0x{patch_off:x}"
        result["threshold_bytes"] = cur.hex()
        result["threshold_state"] = ("original" if cur == OLD_THRESHOLD
                                     else "patched" if cur == NEW_THRESHOLD else "unknown")
    elif len(seq_hits) == 0:
        print("    [!] 没找到特征码 —— 官方可能重写了适配逻辑，需要重新逆向")
        result["threshold_offset"] = None
    else:
        print("    [!] 命中多处，无法唯一定位 —— 需要人工确认")
        result["threshold_offset"] = None

    # ---- 设计分辨率 ----
    design_hits = find_all(data, DESIGN_SEQ)
    print(f"\n[2] 设计分辨率 1920x1080 命中: {len(design_hits)} 处  {[hex(x) for x in design_hits]}")
    if design_hits:
        off = design_hits[-1]
        w, h = struct.unpack("<2f", data[off:off + 8])
        print(f"    位置              : 0x{off:x}  →  {w} x {h}  (ratio {w/h:.4f})")
        result["design_offset"] = f"0x{off:x}"
        result["design_value"] = [w, h]

    # ---- 参考方法表 ----
    print("\n[3] 已知 ZProj.ScreenAdaption 方法（v4.0.0，仅供对照）")
    for name, addr in KNOWN_METHODS.items():
        print(f"    0x{addr:x}  {name}")
    result["known_methods"] = {k: f"0x{v:x}" for k, v in KNOWN_METHODS.items()}

    # ---- 建议 ----
    print("\n[建议]")
    if result.get("threshold_state") == "original":
        print("    直接跑 ./build.sh --all 即可")
    elif result.get("threshold_state") == "patched":
        print("    已经打过补丁，无需重复")
    else:
        print("    偏移与已知版本不同，请把上面的命中位置更新进 shell.m 的硬编码偏移")

    if args.json:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\n报告已写入 {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
