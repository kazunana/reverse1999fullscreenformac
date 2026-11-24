# reverse1999fullscreenformac

让《重返未来：1999》(Reverse: 1999) 的 **iPad 版** 在 Apple Silicon Mac 上以「可自由缩放的普通窗口」运行，并去掉 letterbox 黑边。

**版本**：`v0.1.400` — 补丁版本 `0.1` × 上游游戏 `4.0.0 (build 210)`

**本仓库只包含补丁代码与工具，不含任何游戏文件。** 游戏本体在 App Store **免费下载**，你只需要用自己的 Apple ID 安装一份。

[English](README.en.md) · [日本語](README.ja.md)

---

## 1. 它解决了什么问题

App Store 的 iPad 版装到 Mac 上，跑的是「iOS app on Mac」：

| 现状 | 原因 |
|---|---|
| 窗口锁死 1366×1024（4:3），拖不动 | `UIRequiresFullScreen=true` + 只允许横屏 |
| 上下大片黑边 | 游戏按 1920×1080(16:9) 设计，4:3 窗口必然 letterbox |
| 全屏又出现左右黑边 | 窗口比例固定 4:3，屏幕是 16:10 |

改完之后：窗口可任意缩放、可全屏，**16:9 下零黑边**。

---

## 2. 原理（四层）

### ① 关键观测：FairPlay 只锁了 32 KB

```
Wrapper/1999.app/1999          71,632 B   __TEXT 32 KB   cryptid=1 → 加密
  └ 只是个标准 Unity iOS 引导壳，负责加载 UnityFramework 再调 runUIApplicationMain

Frameworks/UnityFramework.framework/UnityFramework
                              143,858,752 B              cryptid=0 → 明文
  └ il2cpp 全部逻辑：18,279 类型 / 167,004 方法
```

游戏的真正代码是明文，加密的只有那个几十 KB 的引导壳。

### ② 自写引导壳（绕过 FairPlay）

用 objc runtime 复刻标准 Unity iOS 引导流程，编译成 macCatalyst 二进制后顶替 `1999`：

```objc
NSBundle *b = [NSBundle bundleWithPath:@".../Frameworks/UnityFramework.framework"];
[b load];
id ufw = [b.principalClass getInstance];
if (![ufw appController]) [ufw setExecuteHeader:&_mh_execute_header];
[ufw runUIApplicationMainWithArgc:argc argv:argv];
```

加密的那个 `1999` 从此不参与执行。

**坑**：`setDataBundleId:` 千万别调。调了 Unity 会去 `UnityFramework.framework/Data/` 找 `global-metadata.dat`，直接 IL2CPP 初始化失败退出。

### ③ PlayCover 做平台转换

PlayCover 3.x 导入 app 时会：

- 把 app 内所有 Mach-O 的 `LC_BUILD_VERSION platform` 从 `IOS` 改成 `MACCATALYST`
- 注入 `PlayTools.framework`（鼠标→`UITouch` 映射、窗口管理）
- 用 ad-hoc 签名重签

改完就是个普通 Mac app，窗口可自由缩放。

**坑 1**：PlayCover 注入 dylib 路径字符串时写在 `main` 附近。壳的 `main` 太靠前会被覆盖成乱码（`EXC_BAD_INSTRUCTION`，`subcode` 里能看到 ASCII）。所以 `entry.s` 里 `_main` 前面有 `.space 0x1200` 护栏。

**坑 2**：必须链接 `PlayTools`，否则游戏能跑但**鼠标点击完全没反应**（没有 UITouch 转换）。

### ④ 内存补丁（壳里，Unity 初始化前）

```
ZProj.ScreenAdaption（纯代码静态类，不在任何 AssetBundle 里）
    DesignWidth       = 1920.0f      UnityFramework 偏移 0x6e07a30
    DesignHeight      = 1080.0f      偏移 0x6e07a34
    WHRateThreshold   = 0.01f        偏移 0x54daafc   movk w9,#0x3c23

    _GetHeightScaleRate()  0x54da6ac   |screenAspect − 16:9| <= 0.01 ? 1.0 : 补偿系数
    _AutoAdapterMask()     0x54da7dc   (rate−1) > 0.01 ? 激活 maskRoots 黑边遮罩 : 关闭
    LateUpdate()           0x54daa74   窗口变化时重跑
```

屏 4:3 = 1.3339 vs 设计 16:9 = 1.7778，差 **0.4439 ≫ 0.01** → 遮罩必然激活。

壳里 `vm_protect` 拿到写权限后改 4 个字节：

```
0x54daafc:  69 84 a7 72  →  09 e8 a7 72
            movk w9,#0x3c23  →  movk w9,#0x3f40   (0.01f → 0.7537f)
```

阈值放大后 `(rate − 1) > threshold` 恒为假 → 黑边遮罩永不激活。

### 另外修的三个 Mac 移植坑

| 症状 | 原因 | 修法 |
|---|---|---|
| 热更新卡在 629 KB 死循环，日志刷 `Network is unreachable!` | 游戏用 `NSURLSession` **background session** 下载，macCatalyst 下后台传输不回 delegate，超时后被 Unity 包装成 unreachable | 壳里 swizzle `backgroundSessionConfigurationWithIdentifier:` → `defaultSessionConfiguration` |
| 部分环境同样报 unreachable | 本机无 IPv6 出口路由 | interpose `getaddrinfo` 强制 `AF_INET` |
| 鼠标点不动 | PlayTools 未加载 | 编译时 `-Wl,-weak_framework,PlayTools -Wl,-rpath,$HOME/Library/Frameworks` |

---

## 3. 兼容性

| 项 | 状态 |
|---|---|
| 区服 | 国服 `com.bluepoch.m.reverse1999` **v4.0.0 (build 210)** — 已实测 |
| 国际服 | `com.bluepoch.m.en.reverse1999.ios` — 结构相同，未实测（偏移需自行确认） |
| 日服 | 未验证 |
| macOS | 26.x（Apple Silicon，M 系列） |
| PlayCover | 3.1.0 |
| 游戏引擎 | Unity 2022.3.62f2 + il2cpp（metadata v31） |

---

## 4. 快速开始

先装好 PlayCover 和 Xcode Command Line Tools，在 PlayCover 中导入游戏一次。已经导入的副本可直接复用。以下命令在仓库目录运行，仅部署到 PlayCover 容器。

```bash
./r1999 deploy          # 编译、检查游戏版本、补齐输入插件并签名部署
./r1999 start           # 启动现有游戏
./r1999 verify          # 检查组件、签名和链接
./r1999 update          # 快进更新当前 Git 分支，然后重新部署
```

**登录框点不进去时**，先完全退出游戏，执行 `./r1999 controls native`，再执行 `./r1999 start`。点击账号框，观察是否出现光标，再切换到密码框。这个模式关闭该游戏的 PlayCover 按键映射，让 Mac Catalyst 直接处理点击和键盘事件。要恢复游戏键位，退出游戏后执行 `./r1999 controls mapped` 并重新启动。

游戏本体升级后，先在 PlayCover 导入新版本，再执行 `./r1999 deploy`。部署会检查现有窗口补丁对应的字节，在同一卷的临时副本中签名，校验成功后替换游戏包。

---

## 5. 已知问题

| # | 问题 | 影响 | 状态 |
|---|---|---|---|
| 1 | 登录时账号或密码框无法获得焦点 | 鼠标点击后无法输入 | 本机 PlayCover 3.1.0 切换到第 4 节的原生点击模式后，已确认手机号框能获得焦点并输入 |
| 2 | 16:10 全屏仍有约 5% 上下黑边 | 屏幕 3024×1964 (1.539) ≠ 设计 16:9 (1.778) | 窗口拖成 16:9 即零黑边；16:10 满屏需改 Camera aspect（v0.2） |
| 3 | 120Hz 未验证 | 屏幕支持 ProMotion，但游戏可能自设 `Application.targetFrameRate=60` 覆盖掉 hook | v0.2 |
| 4 | 首次启动要全量下载 ~22 GB | PlayCover 的 app 是独立容器 | 正常。原版已下的资源受 TCC 隔离，无法直接复用 |
| 5 | 游戏不做沙盒，直接往 `~/Documents/` 写 | `ResLib/`、`logicLog`、`XfPayReport.sqlite` 散在 Documents | 可手动清理 |

---

## 6. 游戏版本更新后要做什么

**壳不用改，偏移要重新定位 —— 用特征码可以做到近乎零维护。**

`locate_offset.py` 用 12 字节特征码在 `UnityFramework` 里搜索：

```
49 e1 9a 52    mov  w9, #0xd70a
69 84 a7 72    movk w9, #0x3c23, lsl #16      ← 0x3c23 就是 0.01f
09 09 00 b9    str  w9, [x8, #8]
```

实测 v4.0.0：原版与 PlayCover 转换后的二进制里都**只有 1 处命中**，唯一性没问题。

| 变化 | 需要做的事 |
|---|---|
| 小版本更新（4.0.x → 4.1.x） | 跑 `locate_offset.py` 拿新偏移，壳逻辑不动 |
| 官方重写适配系统 | 重新逆向 `ScreenAdaption` |
| Unity 大版本升级（2022.3 → 6.x） | il2cpp 元数据格式变，重新 dump 方法地址 |

---

## 7. 游戏本体从哪来（提取方式）

**全部来自你自己机器上已安装的正版 app**，不需要解密 IPA、不需要越狱：

```
/Applications/重返未来：1999.app/
└── Wrapper/1999.app/
    ├── 1999                                       ← 加密壳，本项目不执行它
    ├── Frameworks/UnityFramework.framework/       ← 明文，运行时由我们的壳加载
    ├── Data/Managed/Metadata/global-metadata.dat  ← 类型/方法表，用于定位偏移
    └── Data/                                      ← 资源，原样使用
```

`extract.py` 做的事（**只读**，不产出可分发的游戏文件）：

1. 读出 `UnityFramework` 的 sha256 / 段布局 / 加密状态
2. 读出 `global-metadata.dat` 的版本与类型/方法计数
3. 用特征码定位阈值与设计分辨率的偏移，打印报告
4. 可选：解析 metadata，列出 `ZProj.ScreenAdaption` 各方法的 RVA

它**不会**把 UnityFramework 或任何游戏资源复制进仓库，只生成一份 `report.json` 给 `build.sh` 用。

> 这也是为什么本项目不需要「解密 IPA」——PlayCover 只是平台转换器，壳由我们自己提供，加密的主二进制自始至终不参与。

---

## 8. 仓库结构

```
reverse1999fullscreenformac/
├── README.md / README.en.md / README.ja.md
├── shell/
│   ├── entry.s          .space 0x1200 护栏 + b _r1999_main
│   └── shell.m          壳本体：PlayTools 弱链 / CADisplayLink hook /
│                        阈值补丁 / background session 修复 / IPv4 强制
├── build.sh             编译 → 部署 → 重签 → 自检
├── locate_offset.py     特征码搜索，输出偏移报告
├── extract.py           从本机正版读取信息并自检（只读）
├── patch_ipa.py         把壳塞进解包后的 IPA
└── docs/
    ├── ANATOMY.md       为什么正版装不上补丁（FairPlay / amfid / TCC 三条实测）
    └── IPA-SOURCES.md   解密 IPA 渠道调研结论
```

---

## 9. 免责

- 本项目**不含**任何游戏文件、资源或密钥；游戏本体在 App Store 免费下载。
- 仅用于让你在 Mac 上以合适的窗口尺寸游玩**你自己安装**的副本。
- 修改后的应用由你自己在本机签名运行，不影响服务器端校验。
- 请勿分发修改后的 `.ipa`。
