#!/usr/bin/env python3
"""
extract.py — 从本机已安装的正版 app 读取信息并自检（只读）

不会复制、导出、打包任何游戏文件。只在本地读元信息 + 定位补丁偏移，输出 report.json
给 build.sh 用。

用法:
    python3 extract.py                          # 自动找 /Applications 里的 app
    python3 extract.py --app "/Applications/重返未来：1999.app"
    python3 extract.py --app <path> --json report.json

支持两种布局:
    macOS App Store 包装:  <app>/Wrapper/1999.app/
    PlayCover 拍平布局:    <app>/
"""
import argparse
import hashlib
import json
import plistlib
import struct
import sys
from pathlib import Path

KNOWN_RATIO = {400: {"bundle_versions": ["210"], "server": "国服", "sid": "com.bluepoch.m.reverse1999"}}


# ---------------------------------------------------------------- Mach-O

def parse_macho(data: bytes):
    """返回 dict: magic / cputype / ncmds / segments[{name,vmaddr,vmsize,fileoff,filesize}] / cryptid 列表"""
    if len(data) < 32:
        return None
    magic = struct.unpack("<I", data[:4])[0]
    if magic not in (0xFEEDFACF, 0xFEEDFACE):
        return None
    is64 = magic == 0xFEEDFACF
    cpu, sub, ftype, ncmds, sizeofcmds, flags, _res = struct.unpack("<7I", data[4:32])
    off = 32
    segs, cryptids = [], []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack("<2I", data[off:off + 8])
        if cmd == 0x19 and is64:                       # LC_SEGMENT_64
            name = data[off + 8:off + 24].rstrip(b"\0").decode("latin1")
            vmaddr, vmsize, fileoff, filesize = struct.unpack("<4Q", data[off + 24:off + 56])
            segs.append({"name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                         "fileoff": fileoff, "filesize": filesize})
        elif cmd == 0x21:                              # LC_ENCRYPTION_INFO_64
            cryptoff, cryptsize, cryptid = struct.unpack("<3I", data[off + 8:off + 20])
            cryptids.append({"cryptoff": cryptoff, "cryptsize": cryptsize, "cryptid": cryptid})
        elif cmd == 0x2C:                              # LC_ENCRYPTION_INFO
            cryptoff, cryptsize, cryptid = struct.unpack("<3I", data[off + 8:off + 20])
            cryptids.append({"cryptoff": cryptoff, "cryptsize": cryptsize, "cryptid": cryptid})
        off += cmdsize
    return {"is64": is64, "cputype": cpu, "filetype": ftype,
            "segments": segs, "cryptids": cryptids}


# ---------------------------------------------------------------- 定位

THRESHOLD_SEQ = bytes.fromhex("49e19a526984a772090900b9")
OLD_THRESHOLD = bytes.fromhex("6984a772")
NEW_THRESHOLD = bytes.fromhex("09e8a772")
DESIGN_SEQ = struct.pack("<2f", 1920.0, 1080.0)


def find_all(data, pat):
    hits, i = [], 0
    while True:
        j = data.find(pat, i)
        if j < 0:
            return hits
        hits.append(j)
        i = j + 1


def locate(data):
    out = {}
    hits = find_all(data, THRESHOLD_SEQ)
    out["threshold_hits"] = [f"0x{x:x}" for x in hits]
    if len(hits) == 1:
        off = hits[0] + 4
        cur = data[off:off + 4]
        out["threshold_offset"] = f"0x{off:x}"
        out["threshold_bytes"] = cur.hex()
        out["threshold_state"] = ("original" if cur == OLD_THRESHOLD
                                  else "patched" if cur == NEW_THRESHOLD else "unknown")
    else:
        out["threshold_offset"] = None
        out["threshold_state"] = "not-found" if not hits else "ambiguous"

    dh = find_all(data, DESIGN_SEQ)
    out["design_hits"] = [f"0x{x:x}" for x in dh]
    if dh:
        off = dh[-1]
        w, h = struct.unpack("<2f", data[off:off + 8])
        out["design_offset"] = f"0x{off:x}"
        out["design_value"] = [w, h]
    return out


# ---------------------------------------------------------------- 主流程

def resolve(app: Path):
    """返回 (app_bundle_dir, unityframework_path, metadata_path)"""
    candidates = [app / "Wrapper" / "1999.app", app]
    for c in candidates:
        if (c / "Frameworks" / "UnityFramework.framework" / "UnityFramework").exists():
            return c
    # 拍平布局：目录本身就是 app（PlayCover）
    if (app / "Frameworks" / "UnityFramework.framework" / "UnityFramework").exists():
        return app
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", type=Path, default=Path("/Applications/重返未来：1999.app"))
    ap.add_argument("--json", type=Path, default=Path("report.json"))
    args = ap.parse_args()

    app = args.app
    if not app.exists():
        print(f"[!] 找不到 {app}\n    用 --app 指定你的安装路径", file=sys.stderr)
        return 1

    bundle = resolve(app)
    if not bundle:
        print(f"[!] {app} 里没有 UnityFramework，可能不是这个游戏或布局不认识", file=sys.stderr)
        return 1

    report = {"app": str(app), "bundle": str(bundle)}

    # Info.plist
    plist_path = bundle / "Info.plist"
    if plist_path.exists():
        with open(plist_path, "rb") as f:
            pl = plistlib.load(f)
        report["bundle_id"] = pl.get("CFBundleIdentifier")
        report["short_version"] = pl.get("CFBundleShortVersionString")
        report["build"] = pl.get("CFBundleVersion")
        report["supported_platforms"] = pl.get("CFBundleSupportedPlatforms")
        report["requires_iphoneos"] = pl.get("LSRequiresIPhoneOS")
        report["requires_fullscreen"] = pl.get("UIRequiresFullScreen")
        print(f"bundle id  : {report['bundle_id']}")
        print(f"version    : {report['short_version']} (build {report['build']})")
        print(f"platform   : {report['supported_platforms']}  LSRequiresIPhoneOS={report['requires_iphoneos']}")

    # 主可执行（加密状态）
    main_bin = bundle / "1999"
    if main_bin.exists():
        d = main_bin.read_bytes()
        m = parse_macho(d)
        crypts = m["cryptids"] if m else []
        report["main_exec"] = {
            "path": str(main_bin), "size": len(d),
            "sha256": hashlib.sha256(d).hexdigest(),
            "cryptid": [c["cryptid"] for c in crypts],
        }
        print(f"\n主可执行    : {len(d):,} B  cryptid={[c['cryptid'] for c in crypts] or 'none'}")
        if crypts and any(c["cryptid"] == 1 for c in crypts):
            print("             → FairPlay 加密（本项目不执行它，用自写壳顶替）")

    # UnityFramework
    uf = bundle / "Frameworks" / "UnityFramework.framework" / "UnityFramework"
    ud = uf.read_bytes()
    m = parse_macho(ud)
    crypts = m["cryptids"] if m else []
    report["unityframework"] = {
        "path": str(uf), "size": len(ud),
        "sha256": hashlib.sha256(ud).hexdigest(),
        "cryptid": [c["cryptid"] for c in crypts],
        "segments": m["segments"] if m else [],
    }
    print(f"\nUnityFramework: {len(ud):,} B  cryptid={[c['cryptid'] for c in crypts] or 'none'}")
    if not crypts or all(c["cryptid"] == 0 for c in crypts):
        print("             → 明文，可静态分析、可在运行时加载")
    for s in (m["segments"] if m else []):
        if s["name"] in ("__TEXT", "__DATA", "__LINKEDIT"):
            print(f"    {s['name']:<12} vmaddr=0x{s['vmaddr']:x}  fileoff=0x{s['fileoff']:x}  size={s['filesize']:,}")

    # global-metadata
    md = bundle / "Data" / "Managed" / "Metadata" / "global-metadata.dat"
    if md.exists():
        head = md.read_bytes()[:8]
        magic = struct.unpack("<I", head[:4])[0]
        version = struct.unpack("<i", head[4:8])[0]
        report["global_metadata"] = {
            "path": str(md), "size": md.stat().st_size,
            "sha256": hashlib.sha256(md.read_bytes()).hexdigest(),
            "magic": f"0x{magic:08x}", "version": version,
        }
        print(f"\nglobal-metadata: {md.stat().st_size:,} B  version={version}  magic=0x{magic:08x}")
        if version != 31:
            print(f"    [!] 本项目在 v31 上验证过，当前是 v{version} —— 方法地址解析方式可能不同")

    # 补丁偏移
    print("\n[补丁点定位]")
    loc = locate(ud)
    report["patch"] = loc
    print(f"    阈值特征码命中 : {loc['threshold_hits']}  → {loc.get('threshold_state')}")
    if loc.get("threshold_offset"):
        print(f"    阈值偏移       : {loc['threshold_offset']}  bytes={loc['threshold_bytes']}")
    print(f"    设计分辨率命中 : {loc['design_hits']}  → {loc.get('design_value')}")

    ok = loc.get("threshold_state") in ("original", "patched")
    print("\n[结论]")
    if loc.get("threshold_state") == "original":
        print("    偏移与已知版本一致，可以直接 ./build.sh --all")
    elif loc.get("threshold_state") == "patched":
        print("    已经是打过补丁的副本")
    else:
        print("    偏移与已知版本不同 —— 跑 locate_offset.py 人工确认，或等待本项目更新")

    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n报告已写入 {args.json}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
