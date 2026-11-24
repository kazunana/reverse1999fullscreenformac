"""Stage and sign a PlayCover installation before atomically replacing it on macOS."""
import ctypes
import fcntl
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


def deploy(app, binary, bundle_id):
    with (app / "Info.plist").open("rb") as source:
        info = plistlib.load(source)
    executable = info["CFBundleExecutable"]
    if (info["CFBundleIdentifier"] != bundle_id or Path(executable).name != executable
            or not (app / executable).is_file() or (app / "Wrapper").exists()):
        raise ValueError("目标必须是 PlayCover 导入的游戏包")
    framework = app / "Frameworks/UnityFramework.framework/UnityFramework"
    with framework.open("rb") as source:
        source.seek(0x54DAAFC)
        if source.read(4).hex() not in ("6984a772", "09e8a772"):
            raise ValueError("游戏版本与当前窗口补丁不兼容，请先更新补丁")
        source.seek(0x6E07A30)
        if source.read(8).hex() not in ("0000f04400008744", "0000b44400008744"):
            raise ValueError("游戏设计分辨率与当前补丁不兼容")

    with tempfile.TemporaryDirectory(dir=app.parent, prefix=".r1999-") as folder:
        stage = Path(folder) / app.name
        subprocess.run(["/bin/cp", "-cRp", app, stage], check=True)
        plugin = Path("PlugIns/AKInterface.bundle")
        if not (stage / plugin / "Contents/MacOS/AKInterface").is_file():
            framework_dir = Path(os.environ.get("PLAYTOOLS_FW_DIR", Path.home() / "Library/Frameworks"))
            source = framework_dir / "PlayTools.framework" / plugin
            if not (source / "Contents/MacOS/AKInterface").is_file():
                raise ValueError("PlayTools 缺少 AKInterface，请先重新安装 PlayTools")
            subprocess.run(["/usr/bin/ditto", source, stage / plugin], check=True)
        entitlements = subprocess.check_output(["codesign", "-d", "--entitlements", "-", "--xml", app])
        signing = ["codesign", "--force", "--sign", "-"]
        if entitlements:
            plistlib.loads(entitlements)
            path = Path(folder) / "entitlements.plist"
            path.write_bytes(entitlements)
            signing.extend(["--entitlements", path])
        shutil.copy2(binary, stage / executable)
        subprocess.run([*signing, stage], check=True)
        subprocess.run(["codesign", "--verify", "--strict", stage], check=True)
        # Darwin RENAME_SWAP keeps the installed bundle available throughout.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.renamex_np(os.fsencode(stage), os.fsencode(app), 2):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    print(f"部署完成 {app}")


if __name__ == "__main__":
    app, binary = map(Path, sys.argv[1:3])
    try:
        directory = os.open(app.parent, os.O_RDONLY)
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deploy(app, binary, sys.argv[3])
        finally:
            os.close(directory)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"部署失败 {exc}")
