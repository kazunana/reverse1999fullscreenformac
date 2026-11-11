/*
 * entry.s —— 重返未来:1999 (macCatalyst / PlayCover) 自定义启动壳的入口汇编
 *
 * 为什么需要这个文件（血泪教训，别删 padding）：
 *   PlayCover 3.x 在导入 IPA 时会把 `@rpath/PlayTools.framework/PlayTools`
 *   这个 dylib 路径字符串直接写进 __TEXT 段的代码区（它靠“占用”可执行文件
 *   入口附近的字节来注入 load command，不会为你保留空间）。
 *   如果 _main 的机器码紧贴 __TEXT 段开头，这段字符串就会把 _main 前几十字节
 *   覆盖成 ASCII —— 表现是“点了没反应 / 启动即崩 / SIGILL”，而且 codesign
 *   还能过（因为覆盖发生在运行前的注入阶段之后、签名校验之前）。
 *
 *   所以：在 _main 之前保留 0x1200 字节的 .space 填充，_main 本体缩成一条
 *   绝对跳转（b _r1999_main），真正逻辑放 shell.m 里的 r1999_main()。
 *   这样无论 PlayCover 往入口附近写多少字符串，都落在填充里。
 *
 * 编译（必须显式给 macabi target，否则产出 iOS 二进制、macOS 上跑不起来）：
 *   clang -c entry.s -o entry.o -target arm64-apple-ios18.0-macabi
 *
 * 自检：
 *   otool -l 1999 | grep -A3 LC_MAIN     # entryoff 应指向 _main（填充之后）
 *   otool -tvV 1999 | grep -A1 '^_main:' # 只应看到  b _r1999_main
 */

    .section __TEXT,__text,regular,pure_instructions
    .globl  _main
    .p2align 2

/* ------------------------------------------------------------------ *
 * 0x1200 字节护栏：给 PlayCover 注入的 dylib 路径字符串留的落点。
 * 实测字符串约 36 字节，0x1200 = 4608 字节余量非常充足；
 * 且 0x1200 是按页（0x4000）内偏移取的，不会把 _main 顶到别的页。
 * ------------------------------------------------------------------ */
    .space  0x1200

_main:
    b       _r1999_main
    /* 理论上永不返回；若返回则走 brk 让崩溃可诊断 */
    brk     #0

/* 让链接器把入口点固定在本节的这一位置，避免被其它 .o 的 __text 抢先 */
    .subsections_via_symbols
