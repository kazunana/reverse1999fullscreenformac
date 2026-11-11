#!/usr/bin/env python3
"""
Reverse:1999 (重返未来：1999) iPad 版 —— 画面黑边 / 分辨率适配补丁

分析结论（基于 App Store 版 v4.0.0 build 210，Unity 2022.3.62f2 + il2cpp v31）：

  ZProj.ScreenAdaption（纯代码静态类，不在任何 AssetBundle 里）
      static float DesignWidth  = 1920.0f     // 文件偏移 0x6e07a30
      static float DesignHeight = 1080.0f     // 文件偏移 0x6e07a34
      static float WHRateThreshold = 0.01f    // cctor 立即数，文件偏移 0x54daafc

  _GetHeightScaleRate()  0x54da6ac
      |screenAspect - DesignWidth/DesignHeight| <= WHRateThreshold  -> 返回 1.0
      否则返回 (screenW/DesignW * DesignH) / screenH

  _AutoAdapterMask()     0x54da7dc  （Start 0x54da7d8 直接 b 到这里）
      (scaleRate - 1) > WHRateThreshold  ->  SetActive(maskRoot, true)  并撑开黑边遮罩
      否则                                ->  SetActive(maskRoot, false)

  LateUpdate()           0x54daa74  （窗口变化时重跑 _AutoAdapterMask）

  iPad Pro 12.9 窗口内容 = 1366x1024pt (2732x2048px) => 4:3 = 1.3339
  设计比例 = 1920/1080 = 1.7778，差值 0.4439 >> 阈值 0.01
  => 必定触发 letterbox（上下黑边）。这就是“iPad 客户端上下大黑边、全屏左右再补黑边”的根因。

用法（对象必须是「能被重签并运行」的副本，例如解密后的 IPA / PlayCover 包；
      App Store 正版受 FairPlay + amfid bundle 校验限制，改完无法启动）：

    python3 patch_r1999.py <UnityFramework 或 .app 路径> [--mode kill-letterbox|design-4x3]
                                               [--design 1440 1080] [--dry-run]

  --mode kill-letterbox  只把 WHRateThreshold 0.01 -> 0.7537（≈0x3f40d70a）
                          效果：黑边遮罩永不激活，宽高比偏差不再补偿
  --mode design-4x3      同时把设计分辨率改成指定值（默认 1440x1080），
                          让 UI 按 4:3 排布，配合上面的阈值改动铺满 4:3 窗口

改完务必重签：
    codesign --force --sign - <UnityFramework.framework>
    （PlayCover 里直接重装 IPA 即可）
"""
import argparse
import struct
import sys
from pathlib import Path

OFF_DESIGN_W = 0x6E07A30          # 1920.0f / 1080.0f 相邻 8 字节
OFF_THRESHOLD = 0x54DAAFC         # movk w9, #0x3c23, lsl #16  (0x3c23d70a = 0.01f)

ORIG_THRESHOLD_BYTES = bytes.fromhex("6984a772")   # movk w9, #0x3c23, lsl #16
NEW_THRESHOLD_BYTES = bytes.fromhex("09e8a772")    # movk w9, #0x3f40, lsl #16 -> 0.7537f


def resolve_binary(path: Path) -> Path:
    if path.is_dir():
        cand = path / "Frameworks/UnityFramework.framework/UnityFramework"
        if not cand.exists():
            cand = path / "Wrapper/1999.app/Frameworks/UnityFramework.framework/UnityFramework"
        if not cand.exists():
            sys.exit(f"未在 {path} 下找到 UnityFramework")
        return cand
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path)
    ap.add_argument("--mode", choices=["kill-letterbox", "design-4x3"], default="kill-letterbox")
    ap.add_argument("--design", nargs=2, type=float, default=[1440.0, 1080.0],
                    metavar=("W", "H"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    binary = resolve_binary(args.target)
    data = bytearray(binary.read_bytes())
    print(f"target : {binary}")
    print(f"size   : {len(data)}")

    dw, dh = struct.unpack("<2f", data[OFF_DESIGN_W:OFF_DESIGN_W + 8])
    cur_th = struct.unpack("<f", bytes(ORIG_THRESHOLD_BYTES)[:4])[0] if False else 0.01
    print(f"当前设计分辨率 : {dw} x {dh}  (ratio {dw/dh:.4f})")
    print(f"当前阈值       : 0x3c23d70a = 0.01f")

    # 1) 阈值
    if data[OFF_THRESHOLD:OFF_THRESHOLD + 4] == ORIG_THRESHOLD_BYTES:
        data[OFF_THRESHOLD:OFF_THRESHOLD + 4] = NEW_THRESHOLD_BYTES
        print("阈值 patch     : movk #0x3c23 -> #0x3f40  (0.01f -> 0.7537f)")
    elif data[OFF_THRESHOLD:OFF_THRESHOLD + 4] == NEW_THRESHOLD_BYTES:
        print("阈值 patch     : 已是 0.7537f，跳过")
    else:
        got = data[OFF_THRESHOLD:OFF_THRESHOLD + 4].hex()
        sys.exit(f"阈值处字节不符预期：{got}（版本可能已更新，请重新定位）")

    # 2) 设计分辨率
    if args.mode == "design-4x3":
        nw, nh = args.design
        data[OFF_DESIGN_W:OFF_DESIGN_W + 8] = struct.pack("<2f", nw, nh)
        print(f"设计分辨率 patch: {dw}x{dh} -> {nw}x{nh} (ratio {nw/nh:.4f})")

    if args.dry_run:
        print("\n[dry-run] 未写入")
        return

    backup = binary.with_suffix(binary.suffix + ".orig")
    if not backup.exists():
        backup.write_bytes(binary.read_bytes())
        print(f"备份           : {backup}")
    binary.write_bytes(data)
    print("写入完成。记得重签：codesign --force --sign - <UnityFramework.framework>")


if __name__ == "__main__":
    main()
