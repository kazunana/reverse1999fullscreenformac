# 重返未来：1999 — 解密 IPA 可得性调研

调研时间：2026-11-11（Asia/Shanghai）
调研方式：`curl` 实测（走 HTTP 代理 127.0.0.1:7897）+ `web_fetch`，**未使用 web_search**，**未下载任何大文件**
目标：判断是否存在可直接取得的 **FairPlay 已解密 IPA**，用于 PlayCover 3.x 安装（Apple Silicon / macOS 26）

---

## 0. 先固定事实（App Store 元数据，`itunes.apple.com/lookup`）

| 项 | 中国版 | 国际版 |
|---|---|---|
| iTunes itemId | **1611712418** | **1672933190** |
| bundle id | `com.bluepoch.m.reverse1999` | `com.bluepoch.m.en.reverse1999.ios` |
| 名称 | 重返未来：1999 | Reverse: 1999 |
| 上架方 | Bluepoch Games | BLUEPOCH GAMES CO., LIMITED |
| 最低 iOS | **13.0** | 13.0 |
| 当前版本 | 4.1.0 | — |
| 安装体积 | **3,929,501,696 B ≈ 3.93 GB** | **3,906,289,664 B ≈ 3.91 GB** |

> 注：国际版 App Store 卖家显示为 **BLUEPOCH GAMES CO., LIMITED 本体**，不是 Elex。任务背景里"国际服由 Elex 代理"与 App Store 元数据不符——至少在 iOS 上架层面是深蓝自己挂的。
>
> **体积含义**：任何"解密 IPA"都会在 **3.5–4 GB** 量级。按本次约束（>50 MB 只记录链接与大小）**一律未下载**，只做可达性验证。
>
> **关键前提**：PlayCover 只吃**未加密（FairPlay 已剥离）**的 IPA。从 App Store / ipatool / Apple Configurator 拿到的 IPA **都是加密的**，PlayCover 打开会报 `is not decrypted`。所以"能否拿到解密 IPA"是独立于"能否拿到 IPA"的问题。

---

## 1. 渠道实测总表

| # | 渠道类型 | 实测 URL | HTTP 状态 | 真能拿到该 app？ | 文件大小 | 备注 / 卡在哪 |
|---|---|---|---|---|---|---|
| 1 | decrypt.day App 页 | `https://decrypt.day/app/1611712418` | **404** | ❌ | — | 返回 `<title>Application not found - Decrypt IPA Store</title>`。**对照组**：TikTok `835599320`、另一 id `1232780281` 也是 404 —— 说明 `/app/<id>` 路由当前对**任何** id 都 404，不是"该游戏未收录"，而是整站数据不可用 |
| 2 | decrypt.day 首页 | `https://decrypt.day/` | **451**（连测 3 次 + 无 UA 均 451） | ❌ | — | 451 = Unavailable For Legal Reasons（Cloudflare 层法律封锁 / 地区阻断）。前端 SvelteKit 静态壳能出（`/_app/immutable/...`），但业务页面被拦 |
| 3 | decrypt.day API | `https://api.decrypt.day/api/app/1611712418` | **000**（TLS `SSL_ERROR_SYSCALL`，代理隧道被重置；直连亦 000）；`web_fetch` 亦 `fetch failed` | ❌ | — | 两条独立 egress 都不通。decrypt.day 的真实数据源就是这个子域，**等于整站不可查** |
| 4 | decrypt.day 站内搜索 | `https://decrypt.day/search?q=reverse%201999` | **200**（49 KB 空壳） | ❌ | — | 页面只有标题 `Search - Decrypt IPA Store`，结果由 JS 调 api 子域渲染 → 同样死在第 3 条 |
| 5 | ipa.cypwn.xyz | `https://ipa.cypwn.xyz/` | **200**（但内容为 `/error` 页面） | ❌ | — | 5.8 MB 的 HTML 里**一个 `reverse` 都没有**；`/api/apps`、`/api/app/1611712418`、`/apps`、`/search` 全部 **302 → /error** |
| 6 | Cypwn 主站 | `https://cypwn.xyz/` | 200（9.8 KB 导航页） | ❌ | — | `<title>CyPwn 2026</title>`，只链 `ipa.cypwn.xyz` / `repo.cypwn.xyz` / TG / Discord；即库入口本身已坏 |
| 7 | Cypwn API 域名 | `https://api.cypwn.xyz/` | **401**（74 B） | ❌ | — | 需 token；无公开文档，未持有凭据 → 无法查询 |
| 8 | armconverter 解密区（页面） | `https://armconverter.com/decryptedappstore` | **200**（SPA 壳 5,006 B，`/decrypted`、`/?decrypted` 同为壳） | ⚠️ 未验证 | — | 前端 `assets/index-DugM4joY.js` 里确认后端路由：`/decryptedappstore/`、`/ad/start`、`/user/info`、`/stat/au/check-batch`、`/stat/au/itunes-results` |
| 9 | armconverter 解密区（下载接口） | `https://armconverter.com/decryptedappstore/ad/start` | **401** `{"error":"Please log in!","loginRequired":true}` | ❌ | — | **硬卡在登录**。要拿到该 app 必须先有站点账号 |
| 10 | armconverter 用户态 | `https://armconverter.com/decryptedappstore/user/info` | **403** | ❌ | — | session 权限不足 |
| 11 | armconverter 元数据接口 | `/decryptedappstore/stat/au/check-batch?limit=5` | **200** | ❌（无解法） | — | 返回 `{"a":[{"c":"us","i":8674},...],"t":"<签名token>"}` —— 只有内部数字 id + 一个签名 token，**不含 bundle id / 文件名**，无法确认是否收录本作；`/api/*`、`/api/list` 全 404 |
| 12 | GitHub repo 搜索 | `search/repositories?q=reverse1999+ipa` | 200，**total_count: 0** | ❌ | — | 另一查询 `q=重返未来1999 ipa` → **0**；`q=reverse1999+decrypted` → **0** |
| 13 | GitHub code 搜索 | `search/code?q=reverse1999+extension:ipa` | **401 Requires authentication** | ❌ | — | 无 token 不可用（与预期一致） |
| 14 | GitHub 相关仓库（非 IPA） | 见 §2 | 200 | ❌（都不是 IPA） | — | 找到的全是**资源/文本解密器**与**dump 产物**，没有 IPA 包 |
| 15 | Telegram 预览 `t.me/s/ipa_hub` | 200（127 KB） | — | ❌ | — | 俄语抽奖/闲聊频道，无 IPA 内容 |
| 16 | Telegram 预览 `t.me/s/iPAStore` | 200（116 KB） | — | ❌ | — | 实为阿拉伯语安卓博客「غابة التطبيقات」，SEO 引流 |
| 17 | Telegram 预览 `t.me/s/ipadump` | 200（34 KB） | — | ❌ | — | 频道名「ios应用砸壳」但只有 `Channel created` / `Live stream` 记录，**零资源帖** |
| 18 | Telegram 预览 `t.me/s/cypwn` | 200（38 KB） | — | ❌ | — | 只有 4 条垃圾消息，频道已废弃 |
| 19 | Telegram 预览 `t.me/s/{ipaarchive, decrypted_ipas, ipacenter, ipa_library, ipasarchive, iosgods, ipadecrypt, cypwngroup}` | **302** | — | ❌ | — | 一律 302 回频道主页 = **web 预览被关闭或频道不存在**，不看登录态无法判断有无资源 |
| 20 | 52pojie 站内搜索 | `www.52pojie.cn/search.php?mod=forum&srchtxt=重返未来` | **302** | ❌ | — | 搜索强制跳登录 / 安全校验。DDG 侧可见的相关帖只有通用教程：《IOS逆向-IPA砸壳》《【免越狱】iOS任意版本号APP下载v8.4》《全平台 免iTunes下载新旧版ipa》→ 工具帖，非本作成品包 |
| 21 | 百度贴吧搜索 | `tieba.baidu.com/f/search/res?qw=重返未来1999 ipa` | **403** `<title>百度安全验证</title>` | ❌ | — | 人机校验拦截 |
| 22 | NGA 搜索 | `bbs.nga.cn/search.php?key=重返未来` | 200（14.6 KB） | ❌ | — | 页面内 `__CURRENT_UID = ''`，未登录且无 `search` 权限位 → 无结果 |
| 23 | 国际服其他渠道 | `itunes.apple.com/search?term=reverse 1999` | 200 | ❌（不是解密包） | 3.91 GB | 国际服同样只有 App Store；未见 TestFlight 公开链接/第三方 iOS 商店（appdb.to 全路径返回同一 SPA 壳 200/9,327 B，搜索与详情均为前端渲染 + 需登录，**未验证收录**） |
| 24 | Steam（旁证/替代素材） | `store.steampowered.com/api/storesearch` | 200 | ❌（不是 IPA） | — | `Reverse: 1999` **appid 3092660**，`platforms: windows:true, mac:false` → 有 Windows PC 客户端，可作资源/协议侧参考，**不能替代 iOS 二进制** |

---

## 2. GitHub 上真实存在的东西（都是资源包，不是 IPA）

| 仓库 | 说明 |
|---|---|
| `skowtcc/reverse1999-decrypt` | bundles 解密器（资源包，非二进制） |
| `gyaru/reverse-1999-decrypter` | Rust，解游戏文本资源 |
| `66hh/1999decrypt` | 重返未来1999 资源文件解密 |
| `Escartem/Reverse1999Dump` | "audio and texture dump of reverse 1999" —— **公开 dump 产物只有音频/贴图** |
| `myssal/Reverse-1999-CN-Asset` | 国服资源 |
| `MAA1999/M9A`、`akibaso/AutoReverse` | 自动化脚本 |

**判读**：社区确实有"dump 得出来"的能力（资源包都放出来了），但**没有任何人公开过整包解密 IPA**。这类 4 GB 的成品包在 GitHub 上极易被 DMCA 打，实际流通只走私有 TG/Discord/网盘。

---

## 3. 明确结论

### 3.1 有没有可用的解密 IPA？

**没有。** 本次实测的 24 条路径里，**没有一条能免登录、免付费、免设备地拿到 `com.bluepoch.m.reverse1999` 的解密 IPA**。

三类死法分布得很干净：

1. **站点整体死了 / 被法律封锁**：decrypt.day（首页 **451**，`/app/*` 对任何 id 都 404，API 子域 TLS 直接断）、ipa.cypwn.xyz（全部 302 → `/error`，主站只剩导航页，`api.cypwn.xyz` 401）。
2. **能查到门口，但卡登录/付费**：armconverter `/decryptedappstore/ad/start` **401 Please log in!**、`user/info` **403**；appdb.to 需要账号；52pojie 搜索 302、贴吧 403、NGA 未登录无权限。
3. **只有"设备侧 dump"这一条路**：没有任何网页/API 侧入口；TG 里 `ios应用砸壳` 这种频道是空壳，真正的 IPA 交换群一律 **302（预览关闭）**，必须登 Telegram 账号人工进群问。

### 3.2 最靠谱的一条路径

**路径 A（唯一确定性最高的）：自建越狱环境自己 dump。**
成本：一台可越狱的真机 + 约 1 小时；产出：4 GB 级真解密 IPA，后续 PlayCover 直接吃。

**路径 B（最省事、但需账号）：armconverter 解密商店。**
它是唯一一个**接口还活着**（`/decryptedappstore/stat/au/check-batch` 200 有效 JSON）且明确在做"解密 IPA 下载"的业务。需要：

1. 注册 `armconverter.com` 账号（`/auth/login`）
2. 登录后 `POST /decryptedappstore/ad/start` 拿授权（现在 401 就是缺这步）
3. 在该站按 App Store 名字搜 `Reverse: 1999` / `重返未来`，逐条比对 bundle id（站内 id 是内部数字，如 `8674`，**不能**用 `1611712418` 直接对）
4. 确认收录后再下 3.9 GB 包
   → **仍未验证是否收录本作**，属于"值得花 10 分钟注册试一下"的档位，不是保证。

**路径 C（成本最低、无外部依赖）：沿用你们已有的自写启动壳路线。**
本次调研没有找到能替代它的现成解密包，所以那条路目前**不是备选，就是主选**。

**路径 D（半自动、能省掉设备的一半）**：`majd/ipatool`（12.2k stars，2026-11-10 仍在维护）用你自己的 Apple ID 直接下 `.ipa` 到 Mac。
- 能拿到：完整加密 IPA、精确二进制/资源清单、`Info.plist`、Mach-O 头
- 拿不到：解密后的 `__TEXT`
- 对你们的价值：**给"自写启动壳替换 FairPlay 主二进制"提供真实输入**（加密主二进制 + 真实 LC_LOAD_DYLIB 布局），比凭空写壳靠谱
- 前提：该 Apple ID 在对应区（国服/国际服）**下载过**该 app（免费即可，不需要付费）

### 3.3 各渠道具体卡点速查

- decrypt.day → **451 法律封锁** + `/app/*` 全 404 + **api 子域 TLS 重置**
- ipa.cypwn.xyz → **302 → /error**，库已下线；`api.cypwn.xyz` **401**
- armconverter → **401 需登录**（接口活着，业务门禁在登录）
- appdb.to → 全路径同一 SPA 壳，**需账号**，未验证收录
- GitHub → repo 搜索 **0 命中**；code 搜索 **401 需 token**；公开产物只有资源 dump
- Telegram → 真资源群 **302（预览关闭）**，需登录账号人工求包；能预览的三个频道全无内容
- 52pojie / 贴吧 / NGA → **302 登录墙 / 403 人机校验 / 未登录无权限**
- 国际服 → 只有 App Store（+ Steam 的 Windows 版），**没有任何解密分发渠道**

---

## 4. 自己 dump 的最低条件

> 核心事实：FairPlay 解密**必须在能运行该 app 的 iOS/iPadOS 设备上**完成（密钥在设备 Secure Enclave 侧，进程内存里才是明文）。Apple Silicon Mac 跑 iOS app 用的是 macOS 的 FairPlay 通路，**不能**当作 dump 源。所以"只用 Mac"这条路不存在。

### 4.1 设备 / 系统 / 越狱工具矩阵

| 工具 | 支持范围 | 对本作的可用性 | 备注 |
|---|---|---|---|
| **Dopamine** | iOS **15.0 – 16.6.1**，A12–A16（arm64e），半持久（重启需重跑） | ✅ **首选**。本作 minOS 13.0，16.x 设备完全能装能跑 | `opa334/Dopamine` 7.3k stars，2026-11-03 仍在更新 |
| **palera1n** | checkm8 设备（**A11 及更早**：iPhone 8/X 一代、iPad 6/7 等），iOS **15 – 16.7.x / 17.x rootless** | ⚠️ 能用但吃紧：A11 + 16.x 跑 4 GB 级 3D 手游很勉强，dump 会 OOM/超时 | `palera1n/palera1n` 6.6k stars |
| **TrollStore** | iOS **14.0 – 17.0**（含 16.x 全系、17.0） | ⚠️ 只是"能装未签名 app"，**本身不解密 App Store 加密二进制** | `opa334/TrollStore` 22.6k stars。要解密仍需能在目标进程内执行代码的 helper（TrollDecrypt 类），且 helper 对 App Store 版 app 的注入成功率不稳定 |
| 无越狱（仅 TrollStore/纯签名） | — | ❌ | App Store 版 app 的 `get-task-allow` 为 false，无越狱拿不到 `task_for_pid` 权限 |

**最低可行配置（推荐）**：一台 **A12–A16、iOS 15.0–16.6.1** 的 iPhone/iPad + **Dopamine** + 该区 Apple ID 装好游戏（进到登录界面即可，不必真玩）+ Mac 侧 `frida-ios-dump`。
**最低成本配置**：一台 **iPhone 8/X（A11，checkm8）** + **palera1n** + iOS 16.x ——硬件便宜，但 dump 4 GB 游戏容易失败。

### 4.2 三个工具的前置条件

**`frida-ios-dump`**（`AloneMonkey/frida-ios-dump`，4.0k stars，2026-11-02 更新）
- 越狱设备（Dopamine / palera1n / unc0ver 均可）+ **版本匹配的 `frida-server`**（frida 大版本必须与 Mac 侧 `frida` 一致）
- Mac 侧：`python3` + `pip install frida-tools`
- 目标 app **已在前台运行**且已过 FairPlay 解密点（进到游戏内或至少登录界面）
- 设备剩余空间 ≥ 包体 2 倍（≈8 GB），dump 期间不能锁屏
- 会连带 dump 出 `Payload/<App>.app`，再 `zip` 成 `.ipa`

**`bagbak`**（`ChiChou/bagbak`，1.5k stars，2026-09-29 更新）
- **Node.js ≥ 16** + `npm i -g bagbak` + `frida`（同上版本约束）
- 越狱环境或具备注入能力的环境（作者对 arm64e 支持较好，适合 A12+ 新机）
- 支持按 bundle id 直接指定：`bagbak com.bluepoch.m.reverse1999`
- 优点：对 **arm64e + 大二进制**比 frida-ios-dump 稳；缺点：同样是 4 GB 级 IO，慢

**`ipatool`**（`majd/ipatool`，12.3k stars，2026-11-10 更新）
- **不需要越狱、不需要设备**
- 需要：Apple ID（**该账号已在对应区下载过该 app**）+ 该账号密码 + 2FA 码
- 命令：`ipatool auth login` → `ipatool download -b com.bluepoch.m.reverse1999`
- **产出仍是 FairPlay 加密的 IPA**，PlayCover 不能直接装
- 真正的用途：给"自写壳"路线提供**真实输入样本**（真实加密主二进制、`Info.plist`、依赖列表），或做版本归档/差分

### 4.3 dump 完成后的 PlayCover 侧检查清单

1. `unzip -l <App>.ipa` 里主二进制大小正常（≈数百 MB），且 `otool -l` 能看到 `LC_ENCRYPTION_INFO_64` 的 **cryptid = 0**（= 已解密）
2. `lipo -info` 含 `arm64`（PlayCover 3.x 只吃 arm64，arm64e 会被 patch）
3. PlayCover 拖入 → 它会自动注入 `PlayTools`；本作有强反调试/完整性校验风险，首次启动若闪退，先关 SIP 相关加固、再考虑 hook `ptrace`/`sysctl`
4. 4 GB 包首次解压+注入约需 10–20 分钟与 ≥12 GB 磁盘

---

## 5. 一句话回报

**目前公开渠道拿不到《重返未来：1999》的解密 IPA；最靠谱的是自己在 iOS 15.0–16.6.1（A12–A16 + Dopamine）设备上用 `bagbak`/`frida-ios-dump` 现 dump，其余方案里只有 armconverter 解密商店（需注册登录）还有一线可能，未验证收录。**
