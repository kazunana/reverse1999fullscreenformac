/*
 * shell.m —— 重返未来:1999 (macCatalyst / PlayCover) 自定义启动壳
 *
 * 这一层壳替换掉 Wrapper/1999.app/1999（原始 71632 字节的 Unity iOS 引导壳，
 * FairPlay 加密，不能改也不能重签），在 PlayCover 环境里做四件事：
 *
 *   1) hook  CADisplayLink -setPreferredFramesPerSecond:  把帧率上限放到 120
 *   2) patch UnityFramework 里 ZProj.ScreenAdaption.WHRateThreshold
 *      0x54daafc: movk w9,#0x3c23,lsl#16 (0.01f)  ->  movk w9,#0x3f40,lsl#16 (0.7537f)
 *      → _AutoAdapterMask() 永不激活黑边遮罩
 *   3) patch UnityFramework 里的设计分辨率常量（0x6e07a30 = 1920.0f / 0x6e07a34 = 1080.0f）
 *      → 默认改成 1440x1080，让 UI 直接按 4:3 排布（可用环境变量关掉）
 *   4) 把 PlayTools（鼠标/键盘映射）准备好，然后按标准 Unity iOS API 拉起 UnityFramework
 *
 * 关键点：**不要**调用 setDataBundleId:。
 *   一旦设置 bundle id，Unity 会去 UnityFramework.framework/Data/ 下找
 *   global-metadata.dat，而这个 App 的元数据在 1999.app/Data/Managed/Metadata/ 下，
 *   结果就是启动即黑屏/秒退。原壳不做这件事，我们也不做。
 *
 * 编译方式见 build.sh（本质：）
 *   clang -c shell.m -o shell.o -target arm64-apple-ios18.0-macabi -fobjc-arc -fblocks
 *   clang entry.o shell.o -o 1999 -target arm64-apple-ios18.0-macabi \
 *         -framework Foundation \
 *         -F "$HOME/Library/Frameworks" \
 *         -Wl,-weak_framework,PlayTools -Wl,-rpath,"$HOME/Library/Frameworks"
 *
 * 返回值约定（和实测一致，方便看崩溃日志区分阶段）：
 *   0  = 已经把控制权交给 Unity（正常情况下 Unity 不再返回）
 *   11 = UnityFramework 里找不到 UnityFramework 类
 *   12 = UnityFramework.framework 加载失败 / getInstance 返回 nil
 */

#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <dlfcn.h>
#import <mach/mach.h>
#import <mach/vm_map.h>
#import <mach/vm_prot.h>
#import <mach-o/dyld.h>
#import <mach-o/loader.h>
#import <mach-o/ldsyms.h>     /* _mh_execute_header */
#import <stdio.h>
#import <stdlib.h>
#import <stdarg.h>
#import <string.h>

/* ============================ 偏移与常量 ============================ */

/* ZProj.ScreenAdaption 静态字段在 UnityFramework 里的文件偏移
 * （UnityFramework 是 cryptid=0 明文，偏移即磁盘偏移，vm 里用 image_base + 同偏移） */
#define R1999_OFF_THRESHOLD      0x54daafcULL   /* movk w9,#0x3c23,lsl#16 ; str w9,[x8,#8] 紧跟其后 */
#define R1999_OFF_DESIGN         0x6e07a30ULL   /* float DesignWidth ; float DesignHeight */

/* 阈值补丁前/后的 4 字节机器码 */
static const unsigned char kThreshOrig[4] = { 0x69, 0x84, 0xa7, 0x72 }; /* 0x3c23d70a = 0.01f   */
static const unsigned char kThreshNew [4] = { 0x09, 0xe8, 0xa7, 0x72 }; /* 0x3f40d70a ~ 0.7537f */

/* 设计分辨率：只有当前值仍是原版 1920 附近才改，避免二进制品已被改过时重复写 */
#define R1999_DESIGN_MIN         1900.0f
#define R1999_DESIGN_MAX         1940.0f
#define R1999_DESIGN_W_DEFAULT   1440.0f
#define R1999_DESIGN_H_DEFAULT   1080.0f

/* 帧率上限 */
#define R1999_MAX_FPS            120L

/* vm_protect 的保护位（和实测二进制里用的立即数一致，别改成 VM_PROT_DEFAULT）
 *   0x17 = READ|WRITE|EXECUTE|COPY   0x13 = READ|WRITE|COPY */
#define R1999_PROT_RWX           0x17
#define R1999_PROT_RW            0x13
#define R1999_PATCH_REGION       0x4000ULL      /* 一个页，覆盖两个热点里的任一个 */

/* 注入后的 UnityFramework 位于 <app>/Frameworks/UnityFramework.framework */
static NSString *const kUnityFrameworkDirName = @"/Frameworks/UnityFramework.framework";

/* ============================== 日志 ============================== */

static void r1999_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fflush(stderr);
}

/* ====================== 1) CADisplayLink 帧率 hook ====================== */

/* 把 setPreferredFramesPerSecond: 夹到 [1, 120]。
 * 原实现（Unity 2022 LTS）在某些分辨率下会请求 30/60，macCatalyst 下
 * ProMotion 屏其实能跑 120，夹一下即可，不需要自己造 CVDisplayLink。 */
static void r1999_hook_displaylink(void)
{
    Class cls = NSClassFromString(@"CADisplayLink");
    if (cls == Nil) {
        r1999_log("[r1999shell] CADisplayLink 不存在，跳过帧率 hook\n");
        return;
    }

    SEL sel = sel_registerName("setPreferredFramesPerSecond:");
    Method m = class_getInstanceMethod(cls, sel);
    if (m == NULL) {
        r1999_log("[r1999shell] 找不到 setPreferredFramesPerSecond:，跳过帧率 hook\n");
        return;
    }

    IMP orig = method_getImplementation(m);

    /* 注意：block 里不要再 method_getImplementation 递归取自己 */
    id block = ^(id self, NSInteger fps) {
        NSInteger clamped = fps;
        if (clamped < 1) {
            clamped = 1;
        }
        if (clamped > R1999_MAX_FPS) {
            clamped = R1999_MAX_FPS;
        }
        SEL s = sel_registerName("setPreferredFramesPerSecond:");
        ((void (*)(id, SEL, NSInteger))orig)(self, s, clamped);
    };

    IMP replacement = imp_implementationWithBlock(block);
    method_setImplementation(m, replacement);
    r1999_log("[r1999shell] CADisplayLink 帧率上限 -> %ld\n", (long)R1999_MAX_FPS);
}

/* =================== 2/3) UnityFramework 内存补丁 =================== */

/* 把 [addr, addr+len) 所在页改成 prot（必要时加 COPY 做私有映射） */
static BOOL r1999_make_writable(uintptr_t addr, vm_prot_t prot)
{
    vm_address_t page = (vm_address_t)(addr & ~(uintptr_t)0x3fff);
    kern_return_t kr = vm_protect(mach_task_self(),
                                  page,
                                  (vm_size_t)R1999_PATCH_REGION,
                                  FALSE,          /* set_maximum = false */
                                  prot);
    if (kr != KERN_SUCCESS) {
        r1999_log("[r1999shell] vm_protect(0x%lx) 失败 kr=%d\n",
                  (unsigned long)page, (int)kr);
        return NO;
    }
    return YES;
}

/* 返回值：1 = 本 image 的补丁全部生效；0 = 不是目标 / 补丁失败 */
static int r1999_patch_unity_image(const struct mach_header_64 *hdr)
{
    uintptr_t base = (uintptr_t)hdr;
    int ok = 0;

    /* --- 3.1 黑边阈值 --- */
    uintptr_t thresh = base + (uintptr_t)R1999_OFF_THRESHOLD;
    if (r1999_make_writable(thresh, R1999_PROT_RWX)) {
        unsigned char *p = (unsigned char *)thresh;
        if (memcmp(p, kThreshOrig, sizeof(kThreshOrig)) == 0) {
            /* 等价于  movk w9,#0x3f40,lsl#16
             * 前两条指令是 mov w9,#0xd70a / movk w9,#0x3c23，这里只改 movk 的立即数 */
            memcpy(p, kThreshNew, sizeof(kThreshNew));
            ok = 1;
            r1999_log("[r1999shell] 黑边阈值 0.01f -> 0.7537f @ 0x%lx\n",
                      (unsigned long)R1999_OFF_THRESHOLD);
        } else if (memcmp(p, kThreshNew, sizeof(kThreshNew)) == 0) {
            ok = 1; /* 已经是补过的（例如用 patch_r1999.py 预打过） */
            r1999_log("[r1999shell] 黑边阈值已是 0.7537f，跳过\n");
        } else {
            r1999_log("[r1999shell] 阈值处字节不符：%02x%02x%02x%02x（版本可能已更新）\n",
                      p[0], p[1], p[2], p[3]);
        }
    }

    /* --- 3.2 设计分辨率 --- */
    uintptr_t design = base + (uintptr_t)R1999_OFF_DESIGN;
    if (r1999_make_writable(design, R1999_PROT_RW)) {
        float *f = (float *)design;
        float dw = f[0];
        float dh = f[1];
        if (dw > R1999_DESIGN_MIN && dw < R1999_DESIGN_MAX) {
            f[0] = R1999_DESIGN_W_DEFAULT;
            f[1] = R1999_DESIGN_H_DEFAULT;
            r1999_log("[r1999shell] 设计分辨率 %.1fx%.1f -> %.1fx%.1f\n",
                      dw, dh, R1999_DESIGN_W_DEFAULT, R1999_DESIGN_H_DEFAULT);
        } else {
            r1999_log("[r1999shell] 设计分辨率已是 %.1fx%.1f，跳过\n", dw, dh);
        }
    }

    return ok;
}

/* 在已加载的 image 里找 UnityFramework（按路径名匹配，比按 image 序号稳） */
static int r1999_patch_unityframework(void)
{
    uint32_t count = _dyld_image_count();
    for (uint32_t i = 0; i < count; i++) {
        const char *name = _dyld_get_image_name(i);
        if (name == NULL) {
            continue;
        }
        if (strstr(name, "UnityFramework") == NULL) {
            continue;
        }
        const struct mach_header *h = _dyld_get_image_header(i);
        if (h == NULL) {
            continue;
        }
        r1999_log("[r1999shell] 命中 image: %s\n", name);
        return r1999_patch_unity_image((const struct mach_header_64 *)h);
    }
    r1999_log("[r1999shell] 未找到已加载的 UnityFramework（跳过内存补丁）\n");
    return 0;
}

/* ======================== 4) PlayTools 兜底 ======================== */

/* 正常情况下 PlayTools 由 LC_LOAD_WEAK_DYLIB + @rpath 自动加载（build.sh 里链的）。
 * 这里做兜底：万一启动环境没带上 rpath（比如从 Finder 直接双击、或换机器），
 * 手动 dlopen 一次，保证鼠标点击/键盘映射有效。
 *   —— 忘记链 PlayTools 的典型症状：游戏能进，但鼠标点哪儿都没反应。 */
static void r1999_ensure_playtools(void)
{
    if (objc_getClass("PlayLoader") != NULL) {
        return; /* 已加载 */
    }

    NSMutableArray<NSString *> *cands = [NSMutableArray array];
    NSString *home = NSHomeDirectory();
    if (home.length > 0) {
        [cands addObject:[home stringByAppendingString:
                            @"/Library/Frameworks/PlayTools.framework/PlayTools"]];
    }
    NSString *bundlePath = [[NSBundle mainBundle] bundlePath];
    if (bundlePath.length > 0) {
        [cands addObject:[bundlePath stringByAppendingString:
                            @"/Frameworks/PlayTools.framework/PlayTools"]];
    }
    [cands addObject:@"/usr/local/lib/PlayTools.framework/PlayTools"];
    [cands addObject:@"/Library/Frameworks/PlayTools.framework/PlayTools"];

    for (NSString *path in cands) {
        if (dlopen(path.fileSystemRepresentation, RTLD_NOW | RTLD_GLOBAL) != NULL) {
            r1999_log("[r1999shell] PlayTools 兜底加载: %s\n", path.fileSystemRepresentation);
            return;
        }
    }
    r1999_log("[r1999shell] PlayTools 未加载（鼠标点击可能无效），尝试路径:\n");
    for (NSString *path in cands) {
        r1999_log("             %s\n", path.fileSystemRepresentation);
    }
}

/* ======================== 5) 拉起 UnityFramework ======================== */

static int r1999_run_unity(int argc, char **argv)
{
    NSString *fwPath = [[[NSBundle mainBundle] bundlePath]
                        stringByAppendingString:kUnityFrameworkDirName];
    if (fwPath.length == 0) {
        r1999_log("[r1999shell] 拿不到 mainBundle 路径\n");
        return 12;
    }

    NSBundle *fw = [NSBundle bundleWithPath:fwPath];
    if (fw == nil) {
        r1999_log("[r1999shell] bundleWithPath 失败: %s\n", fwPath.fileSystemRepresentation);
        return 12;
    }
    if (!fw.isLoaded) {
        if (![fw load]) {
            r1999_log("[r1999shell] UnityFramework 加载失败\n");
            return 12;
        }
    }

    Class unityClass = fw.principalClass;
    if (unityClass == Nil) {
        unityClass = NSClassFromString(@"UnityFramework");
    }
    if (unityClass == Nil) {
        r1999_log("[r1999shell] 找不到 UnityFramework 类\n");
        return 11;
    }

    id instance = ((id (*)(id, SEL))objc_msgSend)(unityClass,
                                                 sel_registerName("getInstance"));
    if (instance == nil) {
        r1999_log("[r1999shell] getInstance 返回 nil\n");
        return 12;
    }

    /* 原壳逻辑：appController 还没建出来时先 setExecuteHeader:
     * 传 _mh_execute_header（本壳自己的 header），Unity 用它拿 bundle 信息。 */
    id appController = ((id (*)(id, SEL))objc_msgSend)(instance,
                                                     sel_registerName("appController"));
    if (appController == nil) {
        ((void (*)(id, SEL, const struct mach_header *))objc_msgSend)(
            instance,
            sel_registerName("setExecuteHeader:"),
            (const struct mach_header *)&_mh_execute_header);
    }

    /* 注意：这里刻意不调 setDataBundleId: —— 见文件头说明。 */
    ((void (*)(id, SEL, int, char **))objc_msgSend)(
        instance,
        sel_registerName("runUIApplicationMainWithArgc:argv:"),
        argc,
        argv);

    return 0;
}

/* ================================ main ================================ */

/* entry.s 里的 _main 直接 b 到这里 */
int r1999_main(int argc, char **argv, char **envp, char **apple)
{
    (void)envp;
    (void)apple;

    @autoreleasepool {
        /* 顺序很重要：
         *   1. PlayTools 先就位（触摸/鼠标映射要赶在 Unity 建窗口前）
         *   2. CADisplayLink hook 要赶在 Unity 创建 display link 之前
         *   3. 内存补丁要在 il2cpp 初始化 ScreenAdaption 的 cctor 之前
         *      （UnityFramework 作为依赖 dylib 已在 main 之前映射好，其
         *        cctor 尚未执行，此时改 .text 常量一定命中） */
        r1999_ensure_playtools();
        r1999_hook_displaylink();

        int patched = r1999_patch_unityframework();
        r1999_log("[r1999shell] patch=%d\n", patched);

        int rc = r1999_run_unity(argc, argv);
        return rc;
    }
}
