#!/usr/bin/env python3
"""
patch_ipa.py —— 把自定义启动壳塞进已解包的 IPA 目录，并修好 Info.plist

做的事（只改你指定的那个目录，原件一律不碰）：

  1. 找到 .app（`Payload/*.app` 或直接给定的 .app / 解包根目录）
  2. 读出 CFBundleExecutable，把原可执行备份成 `<exec>.orig`，替换成你自己编译的壳
  3. patch Info.plist：
       CADisableMinimumFrameDurationOnPhone = true
       CADisableMinimumFrameDuration        = true
     —— macCatalyst / PlayCover 下这两个键是 ProMotion 120Hz 的开关；
        只 hook CADisplayLink 但不设这个键，系统仍会按 60Hz 压制。
  4. （可选）递归 ad-hoc 重签所有 Mach-O 与 .app

  注意：本脚本**不**改 LC_BUILD_VERSION 的 platform。
    IOS -> MACCATALYST 的转换由 PlayCover 导入时完成；如果你走的是
    「解包 IPA + 直接塞壳 + 自己签名侧载」的路线，需要另行处理这一步。

用法：

    # 最常见：先手动解包，然后
    python3 patch_ipa.py unpacked_root --shell build/1999 --sign

    # 直接喂 .ipa 也行（会自动解到临时目录并回打包成 <name>.patched.ipa）
    python3 patch_ipa.py game.ipa --shell build/1999 --sign --repack

    # 只看会做什么
    python3 patch_ipa.py unpacked_root --shell build/1999 --dry-run

    # 额外写 plist 键
    python3 patch_ipa.py unpacked_root --shell build/1999 \
            --set UIFileSharingEnabled=true --set CADisableMinimumFrameDurationOnPhone=true
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# 必设的 plist 键（ProMotion / 120Hz）
FORCED_PLIST_KEYS: dict[str, object] = {
    "CADisableMinimumFrameDurationOnPhone": True,
    "CADisableMinimumFrameDuration": True,
}

# 递归重签时先签里面的，再签外层
MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64 LE
    b"\xce\xfa\xed\xfe",  # MH_MAGIC LE
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64 BE
    b"\xfe\xed\xfa\xce",  # MH_MAGIC BE
    b"\xca\xfe\xba\xbe",  # FAT
}


def log(msg: str) -> None:
    print(f"==> {msg}")


def warn(msg: str) -> None:
    print(f"[!] {msg}", file=sys.stderr)


def die(msg: str) -> None:
    print(f"[x] {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# 目录 / 产物定位
# --------------------------------------------------------------------------- #

def find_app_bundle(root: Path) -> Path:
    """在解包根目录里找那个 .app（IPA 结构是 Payload/xxx.app）。"""
    if root.suffix == ".app" and (root / "Info.plist").exists():
        return root

    payload = root / "Payload"
    search_root = payload if payload.is_dir() else root

    apps = sorted(p for p in search_root.iterdir()
                  if p.suffix == ".app" and p.is_dir() and (p / "Info.plist").exists())
    if not apps:
        die(f"{root} 下没找到含 Info.plist 的 .app（期望 Payload/*.app）")
    if len(apps) > 1:
        warn(f"发现多个 .app，取第一个: {apps[0].name}")
    return apps[0]


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) in MACHO_MAGICS
    except OSError:
        return False


def read_plist(app: Path) -> tuple[dict, bool]:
    plist_path = app / "Info.plist"
    raw = plist_path.read_bytes()
    was_binary = raw.startswith(b"bplist")
    with plist_path.open("rb") as fh:
        data = plistlib.load(fh)
    return data, was_binary


def write_plist(app: Path, data: dict, binary: bool) -> None:
    plist_path = app / "Info.plist"
    fmt = plistlib.FMT_BINARY if binary else plistlib.FMT_XML
    tmp = plist_path.with_suffix(".plist.new")
    with tmp.open("wb") as fh:
        plistlib.dump(data, fh, fmt=fmt, sort_keys=False)
    os.replace(tmp, plist_path)


# --------------------------------------------------------------------------- #
# 塞壳
# --------------------------------------------------------------------------- #

def install_shell(app: Path, shell: Path, plist: dict, dry_run: bool) -> Path:
    exec_name = plist.get("CFBundleExecutable")
    if not exec_name:
        die("Info.plist 里没有 CFBundleExecutable")

    dest = app / exec_name
    log(f"目标可执行: {dest}")

    if dest.exists() and not dry_run:
        backup = dest.with_name(dest.name + ".orig")
        if backup.exists():
            warn(f"备份已存在，保留: {backup.name}")
        else:
            shutil.copy2(dest, backup)
            log(f"原壳已备份 -> {backup.name} ({backup.stat().st_size} 字节)")

    if dry_run:
        log(f"[dry-run] 将用 {shell} 替换 {dest.name}")
        return dest

    tmp = app / f".{dest.name}.new"
    shutil.copy2(shell, tmp)
    mode = tmp.stat().st_mode
    tmp.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, dest)
    log(f"已替换为自定义壳 ({dest.stat().st_size} 字节)")
    return dest


def patch_plist(app: Path, extra: dict[str, object], dry_run: bool,
                allow_resize: bool = False) -> None:
    data, was_binary = read_plist(app)

    changed: list[str] = []
    for k, v in {**FORCED_PLIST_KEYS, **extra}.items():
        if data.get(k) != v:
            data[k] = v
            changed.append(f"{k}={v!r}")

    # UIRequiresFullScreen 默认**不动**：已验证能跑的 PlayCover 包里它是 true 也没问题。
    # 想让它可为 False（部分场景下窗口更自由）请显式 --allow-resize。
    if allow_resize and data.get("UIRequiresFullScreen") is True:
        data["UIRequiresFullScreen"] = False
        changed.append("UIRequiresFullScreen=False（--allow-resize 显式要求）")

    # iPad 横屏要全留，否则部分关卡 UI 会被裁
    ipad_key = "UISupportedInterfaceOrientations~ipad"
    want = ["UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"]
    cur = data.get(ipad_key)
    if isinstance(cur, list) and cur and not set(want).issubset(cur):
        merged = list(dict.fromkeys(list(cur) + want))
        data[ipad_key] = merged
        changed.append(f"{ipad_key} += 双横屏")

    if not changed:
        log("Info.plist 无需改动")
        return

    for c in changed:
        log(f"plist: {c}")

    if dry_run:
        log("[dry-run] 未写 Info.plist")
        return

    write_plist(app, data, was_binary)
    log(f"Info.plist 已写入（{'binary' if was_binary else 'XML'} 格式）")


# --------------------------------------------------------------------------- #
# 重签
# --------------------------------------------------------------------------- #

def adhoc_sign(app: Path, dry_run: bool) -> None:
    if dry_run:
        log(f"[dry-run] 将 ad-hoc 重签 {app}")
        return

    # 1) 先签所有嵌套 Mach-O 与 framework / appex（由内到外）
    targets: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(app):
        d = Path(dirpath)
        # 跳过顶层 .app 自己，最后单独签
        for name in list(dirnames):
            p = d / name
            if p.suffix in (".framework", ".appex", ".app", ".dylib"):
                targets.append(p)
        for name in filenames:
            p = d / name
            if p.is_symlink():
                continue
            if is_macho(p):
                targets.append(p)

    # 深度大的（更靠内的）先签
    targets.sort(key=lambda p: len(p.parts), reverse=True)
    seen: set[Path] = set()
    for t in targets:
        if t in seen or t == app:
            continue
        seen.add(t)
        subprocess.run(["codesign", "--force", "--sign", "-", str(t)],
                       check=False, capture_output=True)
    log(f"已 ad-hoc 重签 {len(seen)} 个内部组件")

    # 2) 最后签 .app
    r = subprocess.run(["codesign", "--force", "--sign", "-", str(app)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        warn(f"app 重签失败: {r.stderr.strip()}")
    else:
        log("app bundle 已 ad-hoc 重签")


# --------------------------------------------------------------------------- #
# IPA 打包
# --------------------------------------------------------------------------- #

def repack(root: Path, out: Path, dry_run: bool) -> None:
    if dry_run:
        log(f"[dry-run] 将打包 -> {out}")
        return
    if out.exists():
        die(f"输出已存在: {out}")
    log(f"打包 -> {out}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                full = Path(dirpath) / name
                arc = full.relative_to(root)
                zf.write(full, arc.as_posix())
    log(f"完成: {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def parse_set(pairs: list[str] | None) -> dict[str, object]:
    out: dict[str, object] = {}
    for item in pairs or []:
        if "=" not in item:
            die(f"--set 需要 key=value，收到: {item}")
        k, v = item.split("=", 1)
        low = v.strip().lower()
        if low in ("true", "yes", "1"):
            out[k.strip()] = True
        elif low in ("false", "no", "0"):
            out[k.strip()] = False
        elif v.strip().isdigit():
            out[k.strip()] = int(v.strip())
        else:
            out[k.strip()] = v
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="把自定义启动壳塞进解包后的 IPA 并修 Info.plist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("target", type=Path, help="解包根目录 / .app / .ipa 文件")
    ap.add_argument("--shell", type=Path, required=True, help="build.sh 产出的 1999 壳")
    ap.add_argument("--set", dest="sets", action="append", metavar="KEY=VALUE",
                    help="额外写入 Info.plist 的键，可重复")
    ap.add_argument("--sign", action="store_true", help="递归 ad-hoc 重签（codesign --sign -）")
    ap.add_argument("--allow-resize", action="store_true",
                    help="把 UIRequiresFullScreen 改成 false（默认不动，已验证的配置里它是 true）")
    ap.add_argument("--repack", action="store_true", help="target 是 .ipa 时，处理后回打包")
    ap.add_argument("--out", type=Path, help="回打包输出路径（默认 <name>.patched.ipa）")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不落盘")
    args = ap.parse_args()

    target: Path = args.target.expanduser().resolve()
    shell: Path = args.shell.expanduser().resolve()

    if not target.exists():
        die(f"target 不存在: {target}")
    if not shell.exists():
        die(f"shell 不存在: {shell}（先跑 ./build.sh --build-only）")
    if not shell.is_file():
        die(f"--shell 必须是文件: {shell}")

    log(f"shell : {shell} ({shell.stat().st_size} 字节)")
    log(f"target: {target}")

    tmpdir: str | None = None
    try:
        # .ipa 输入：解到临时目录
        if target.suffix.lower() == ".ipa" or zipfile.is_zipfile(target):
            if not args.repack:
                warn("输入是 zip/.ipa；本次会解包到临时目录处理，但不会回打包（加 --repack）")
            tmpdir = tempfile.mkdtemp(prefix="r1999-patch-")
            log(f"解包 -> {tmpdir}")
            with zipfile.ZipFile(target) as zf:
                zf.extractall(tmpdir)
            root = Path(tmpdir)
        else:
            root = target

        app = find_app_bundle(root)
        log(f"app bundle: {app}")

        plist, _ = read_plist(app)
        log(f"CFBundleIdentifier = {plist.get('CFBundleIdentifier')}")
        log(f"CFBundleShortVersionString = {plist.get('CFBundleShortVersionString')} "
            f"({plist.get('CFBundleVersion')})")

        # 提示原件是 FairPlay 壳的情况（我们替换掉它即可，不用管 cryptid）
        exec_name = plist.get("CFBundleExecutable", "")
        orig = app / exec_name
        if orig.exists():
            log(f"原可执行体积 {orig.stat().st_size} 字节"
                + ("（典型的 Unity FairPlay 引导壳）" if orig.stat().st_size < 100_000 else ""))

        install_shell(app, shell, plist, args.dry_run)
        patch_plist(app, parse_set(args.sets), args.dry_run, args.allow_resize)
        if args.sign:
            adhoc_sign(app, args.dry_run)

        if args.repack and tmpdir is not None:
            out = (args.out.expanduser().resolve() if args.out
                   else target.with_name(target.stem + ".patched.ipa"))
            repack(root, out, args.dry_run)

        print()
        log("完成。后续：")
        print("    PlayCover 路线：把 .patched.ipa（或解包目录）用 PlayCover 导入，")
        print("                    PlayCover 会自己做 IOS->MACCATALYST 与 PlayTools 注入。")
        print("    手动侧载路线：注意本脚本未改 LC_BUILD_VERSION platform，需自行转换。")
    finally:
        if tmpdir and not args.repack:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
