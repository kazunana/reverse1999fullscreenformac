#!/bin/bash
#
# build.sh —— 一键编译自定义启动壳，部署进 PlayCover 的 app 目录并重签
#
#   用法:
#     ./build.sh                 # 编译 + 部署 + 重签（默认动作）
#     ./build.sh --build-only    # 只编译到 build/，不动 PlayCover 里的东西
#     ./build.sh --deploy-only   # 跳过编译，把 build/1999 部署过去
#     ./build.sh --verify        # 只做自检（结构 / 偏移 / 签名）
#
#   前置:
#     - Xcode Command Line Tools（clang / codesign / otool）
#     - PlayCover 3.1.0 已导入本 App（见 README「路线 A」第 1~2 步）
#     - PlayTools.framework 已装到 ~/Library/Frameworks（PlayCover 首次启动会放）
#
#   原件只读：本脚本永远不写 /Applications/重返未来：1999.app
#

set -euo pipefail

# ============================== 可调变量 ==============================

BUNDLE_ID="${BUNDLE_ID:-com.bluepoch.m.reverse1999}"
APP_NAME="${APP_NAME:-重返未来：1999}"

# 只读参照原件（仅用来对比/查偏移，脚本不写入）
ORIG_APP="${ORIG_APP:-/Applications/${APP_NAME}.app}"
ORIG_EXEC="${ORIG_EXEC:-${ORIG_APP}/Wrapper/1999.app/1999}"

# PlayCover 3.1.0 安装后的 app 落地目录（PlayCover 会把 iOS 壳结构拍平到这里）
PLAYCOVER_HOME="${PLAYCOVER_HOME:-${HOME}/Library/Containers/io.playcover.PlayCover}"
PC_APP="${PC_APP:-${PLAYCOVER_HOME}/Applications/${BUNDLE_ID}.app}"

# PlayTools 所在位置（build.sh 会链弱依赖，运行时靠 rpath 找）
PLAYTOOLS_FW_DIR="${PLAYTOOLS_FW_DIR:-${HOME}/Library/Frameworks}"

# macCatalyst 编译目标：必须带 -macabi，否则出来的是 iOS 二进制，macOS 上跑不了
TARGET_TRIPLE="${TARGET_TRIPLE:-arm64-apple-ios18.0-macabi}"

# 产物
BUILD_DIR="${BUILD_DIR:-$(cd "$(dirname "$0")" && pwd)/build}"
OUT_EXEC="${OUT_EXEC:-${BUILD_DIR}/1999}"

# 备份后缀
BAK_SUFFIX=".bak.$(date +%Y%m%d-%H%M%S)"

# ============================== 小工具 ==============================

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_rst=$'\033[0m'
say()  { printf "%s==>%s %s\n" "$c_grn" "$c_rst" "$*"; }
warn() { printf "%s[!]%s %s\n" "$c_ylw" "$c_rst" "$*"; }
die()  { printf "%s[x]%s %s\n" "$c_red" "$c_rst" "$*" >&2; exit 1; }

need_file() { [ -e "$1" ] || die "缺少: $1"; }

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRY_S="${SRC_DIR}/shell/entry.s"
SHELL_M="${SRC_DIR}/shell/shell.m"

# UnityFramework 关键偏移（用于自检，和 shell.m 里的宏保持一致）
OFF_THRESHOLD=0x54daafc
OFF_DESIGN=0x6e07a30
THRESH_ORIG="6984a772"
THRESH_NEW="09e8a772"

# ============================== 编译 ==============================

do_build() {
    need_file "$ENTRY_S"
    need_file "$SHELL_M"
    command -v clang >/dev/null || die "没有 clang，请先装 Command Line Tools: xcode-select --install"

    mkdir -p "$BUILD_DIR"
    say "编译目标: ${TARGET_TRIPLE}"

    # 1) 汇编入口（含 0x1200 padding，别动）
    clang -c "$ENTRY_S" -o "${BUILD_DIR}/entry.o" -target "$TARGET_TRIPLE"
    say "entry.o  ✅"

    # 2) 壳本体
    clang -c "$SHELL_M" -o "${BUILD_DIR}/shell.o" \
        -target "$TARGET_TRIPLE" \
        -fobjc-arc -fblocks -O2 -Wall -Wno-unused-parameter
    say "shell.o  ✅"

    # 3) 链接
    #    -weak_framework PlayTools : 少了它游戏能起但鼠标点不动
    #    -rpath ~/Library/Frameworks: 让 @rpath/PlayTools.framework/PlayTools 解析得到
    local pt_args=()
    if [ -d "${PLAYTOOLS_FW_DIR}/PlayTools.framework" ]; then
        pt_args=(
            -F "${PLAYTOOLS_FW_DIR}"
            -Wl,-weak_framework,PlayTools
            -Wl,-rpath,"${PLAYTOOLS_FW_DIR}"
        )
    else
        warn "没找到 ${PLAYTOOLS_FW_DIR}/PlayTools.framework —— 先跑一次 PlayCover 让它落盘，"
        warn "否则产物缺少 PlayTools 弱链接（鼠标点击会失效，shell.m 的 dlopen 兜底可救急）。"
    fi

    clang "${BUILD_DIR}/entry.o" "${BUILD_DIR}/shell.o" -o "$OUT_EXEC" \
        -target "$TARGET_TRIPLE" \
        -framework Foundation \
        "${pt_args[@]}"
    say "产物: ${OUT_EXEC}"

    [ -f "$OUT_EXEC" ] || die "链接失败，产物不存在"
    chmod +x "$OUT_EXEC"

    # 4) 结构自检
    say "自检:"
    otool -L "$OUT_EXEC" | sed 's/^/    /'
    local entryoff
    entryoff=$(otool -l "$OUT_EXEC" | awk '/LC_MAIN/{f=1} f&&/entryoff/{print $2; exit}')
    printf "    LC_MAIN entryoff = %s (0x%x)\n" "$entryoff" "$((entryoff))"
    printf "    _main 反汇编: "; otool -tvV "$OUT_EXEC" | awk '/^_main:/{getline; print; exit}'
    printf "    体积: "; ls -l "$OUT_EXEC" | awk '{print $5" 字节"}'

    local plat
    plat=$(otool -l "$OUT_EXEC" | awk '/LC_BUILD_VERSION/{f=1} f&&/platform/{print $2; exit}')
    [ "$plat" = "6" ] && say "platform=6 (MACCATALYST) ✅" \
                      || warn "platform=${plat}，期望 6 (MACCATALYST)；PlayCover 导入时会自己改，但直接跑需确认"
}

# ============================== 部署 ==============================

do_deploy() {
    [ -d "$PC_APP" ] || die "PlayCover app 目录不存在: ${PC_APP}（先用 PlayCover 导入 IPA）"
    need_file "$OUT_EXEC"

    local exec_name
    exec_name=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "${PC_APP}/Info.plist" 2>/dev/null || echo "1999")
    local dest="${PC_APP}/${exec_name}"
    say "部署目标: ${dest}"

    # 备份旧可执行（第一次部署时是 PlayCover 注入过的原生壳）
    if [ -f "$dest" ] && [ ! -f "${dest}${BAK_SUFFIX}" ]; then
        cp -p "$dest" "${dest}${BAK_SUFFIX}"
        say "已备份原壳 -> ${dest}${BAK_SUFFIX}"
    fi

    # 先写到临时文件再 mv：TCC / LaunchServices 下直接覆盖容易 EPERM
    local tmp="${PC_APP}/.${exec_name}.new.$$"
    cp "$OUT_EXEC" "$tmp"
    chmod 755 "$tmp"
    mv -f "$tmp" "$dest"
    say "已替换可执行文件"

    say "重签可执行"
    codesign --force --sign - "$dest"

    # 框架层也顺手补签（PlayCover 通常已签；这一步是幂等的保险）
    find "${PC_APP}/Frameworks" -maxdepth 2 -name "*.framework" -type d 2>/dev/null | while read -r fw; do
        codesign --force --sign - "$fw" >/dev/null 2>&1 || true
    done

    say "重签 app bundle"
    codesign --force --sign - "$PC_APP"

    say "签名校验"
    codesign -vv "$PC_APP" 2>&1 | sed 's/^/    /' || warn "codesign -vv 有告警（ad-hoc 签名常见，能跑就行）"

    cat <<EOF

$(say "完成")
    启动方式: 打开 PlayCover，双击「${APP_NAME}」
    观察日志: log stream --predicate 'process == "${exec_name}"' --level debug
              或直接看 stderr: PlayCover 里设置「Open Terminal on Launch」
    回滚:     cp -p "${dest}${BAK_SUFFIX}" "${dest}" && codesign --force --sign - "$PC_APP"

EOF
}

# ============================== 自检 ==============================

do_verify() {
    say "原件（只读参照）"
    if [ -f "$ORIG_EXEC" ]; then
        printf "    体积 %s 字节 （cryptid=1 FairPlay 壳，正常）\n" "$(stat -f%z "$ORIG_EXEC")"
    else
        warn "原件不在 ${ORIG_EXEC}"
    fi

    local uf="${PC_APP}/Frameworks/UnityFramework.framework/UnityFramework"
    if [ -f "$uf" ]; then
        say "PlayCover 包里的 UnityFramework"
        printf "    flags  : "; otool -hv "$uf" | awk 'NR==4{for(i=7;i<=NF;i++) printf "%s ", $i; print ""}'
        if otool -hv "$uf" | grep -q CRYPTID; then printf "    cryptid: 非 0（被加密，异常）\\n"; else printf "    cryptid: 0（明文，正常）\\n"; fi
        printf "    阈值处字节 (@%s): " "$OFF_THRESHOLD"
        xxd -s $((OFF_THRESHOLD)) -l 4 -p "$uf"
        printf "      说明: %s = 原版 0.01f；%s = 已改 0.7537f（壳在运行时改，磁盘上应保持原版）\n" \
               "$THRESH_ORIG" "$THRESH_NEW"
        printf "    设计分辨率 (@%s): " "$OFF_DESIGN"
        xxd -s $((OFF_DESIGN)) -l 8 "$uf" | awk '{print $2" "$3}'
    else
        warn "找不到 ${uf}"
    fi

    say "已部署的壳"
    local exec_name
    exec_name=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "${PC_APP}/Info.plist" 2>/dev/null || echo "1999")
    if [ -f "${PC_APP}/${exec_name}" ]; then
        otool -L "${PC_APP}/${exec_name}" | sed 's/^/    /'
        codesign -dv "${PC_APP}/${exec_name}" 2>&1 | sed 's/^/    /'
    fi

    say "Info.plist 关键键"
    for k in CADisableMinimumFrameDurationOnPhone CADisableMinimumFrameDuration UIRequiresFullScreen; do
        printf "    %-38s = %s\n" "$k" \
            "$(/usr/libexec/PlistBuddy -c "Print :$k" "${PC_APP}/Info.plist" 2>/dev/null || echo '(缺失)')"
    done
}

# ============================== 入口 ==============================

MODE="all"
case "${1:-}" in
    --build-only)  MODE="build" ;;
    --deploy-only) MODE="deploy" ;;
    --verify)      MODE="verify" ;;
    ""|--all)      MODE="all" ;;
    -h|--help)     sed -n '2,30p' "$0"; exit 0 ;;
    *)             die "未知参数: $1（用 --help）" ;;
esac

case "$MODE" in
    build)  do_build ;;
    deploy) do_deploy ;;
    verify) do_verify ;;
    all)    do_build; do_deploy; do_verify ;;
esac
