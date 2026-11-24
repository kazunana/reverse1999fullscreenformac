#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
app="${PC_APP:-${PLAYCOVER_HOME:-$HOME/Library/Containers/io.playcover.PlayCover}/Applications/${BUNDLE_ID:-com.bluepoch.m.reverse1999}.app}"

if [[ ! -f "$app/Info.plist" ]]; then
    original="${ORIG_APP:-/Applications/重返未来：1999.app}/Wrapper/1999.app"
    if [[ ! -f "$original/Info.plist" ]]; then
        echo "请先在 Mac App Store 安装国服 iPad 版《重返未来：1999》，或把自己的兼容 IPA 导入 PlayCover，再重新打开本程序。"
        exit 1
    fi
    version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$original/Info.plist")
    if [[ "$version" != 210 ]]; then
        echo "当前本机打包流程适配国服 build 210，检测到 build $version。请先查看仓库是否已有适配版本。"
        exit 1
    fi
    echo "将从你的 App Store 游戏副本准备本机导入包，请预留两份游戏安装包的空间。"
    read -r -p "按回车开始，按 Ctrl+C 取消。"
    (
        if [[ ! -d "${PLAYTOOLS_FW_DIR:-$HOME/Library/Frameworks}/PlayTools.framework" ]]; then
            for directory in "/Applications/PlayCover.app" "$HOME/Applications/PlayCover.app"; do
                if [[ -d "$directory/Contents/Frameworks/PlayTools.framework" ]]; then
                    export PLAYTOOLS_FW_DIR="$directory/Contents/Frameworks"
                    break
                fi
            done
        fi
        ./build.sh --build-only
    )
    mkdir -p build
    work=$(mktemp -d "$PWD/build/.prepare.XXXXXX")
    trap 'rm -rf -- "$work"' EXIT
    mkdir "$work/Payload"
    /usr/bin/ditto "$original" "$work/Payload/1999.app"
    python3 patch_ipa.py "$work/Payload/1999.app" --shell "${OUT_EXEC:-${BUILD_DIR:-build}/1999}"
    /usr/bin/ditto -c -k --norsrc --keepParent "$work/Payload" "$work/国服-本机导入.ipa"
    mv -f "$work/国服-本机导入.ipa" build/
    echo "已生成 build/国服-本机导入.ipa。将它拖入 PlayCover，等游戏图标出现后，再双击一次「安装.command」。"
    open -R "$PWD/build/国服-本机导入.ipa"
    exit 0
fi

echo "已经找到 PlayCover 中的游戏。请完全退出游戏。"
read -r -p "准备好后按回车部署，按 Ctrl+C 取消。"
./r1999 deploy
./r1999 install
settings="${PLAYCOVER_HOME:-$HOME/Library/Containers/io.playcover.PlayCover}/App Settings/${BUNDLE_ID:-com.bluepoch.m.reverse1999}.plist"
if [[ -f "$settings" ]]; then
    ./r1999 controls native
else
    echo "如登录框点不进去，请按使用指南的「登录与更新」保存游戏设置并切换输入模式。"
fi
echo "安装完成。在 Finder 的「应用程序」中打开「重返未来：1999（PlayCover）」。"
