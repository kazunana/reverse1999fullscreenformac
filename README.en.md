# reverse1999fullscreenformac

[中文](README.md) · [日本語](README.ja.md)

Run the **iPad version** of *Reverse: 1999* on Apple Silicon Macs as a freely resizable ordinary window, with the letterbox black bars removed.

**Version**: `v0.1.400` — patch version `0.1` × upstream game `4.0.0 (build 210)`

**This repository contains only patch code and tooling, no game files.** The game itself is **free** on the App Store — just install it with your own Apple ID.

---

## 1. What it solves

When the App Store iPad version is installed on a Mac, it runs as an "iOS app on Mac":

| Current state | Cause |
|---|---|
| Window locked at 1366×1024 (4:3), cannot be dragged | `UIRequiresFullScreen=true` + landscape orientation only |
| Large black bars at top and bottom | The game is designed for 1920×1080 (16:9), so a 4:3 window must letterbox |
| Going fullscreen produces black bars on the left and right | Window aspect is fixed at 4:3 while the screen is 16:10 |

After patching: the window resizes freely, can go fullscreen, and **has zero black bars at 16:9**.

---

## 2. How it works (four layers)

### ① Key observation: FairPlay only locked 32 KB

```
Wrapper/1999.app/1999          71,632 B   __TEXT 32 KB   cryptid=1 → encrypted
  └ Just a standard Unity iOS boot shell; it loads UnityFramework and calls runUIApplicationMain

Frameworks/UnityFramework.framework/UnityFramework
                              143,858,752 B              cryptid=0 → plaintext
  └ All il2cpp logic: 18,279 types / 167,004 methods
```

The game's real code is plaintext; only that few-dozen-KB boot shell is encrypted.

### ② Our own boot shell (bypassing FairPlay)

Reproduce the standard Unity iOS boot sequence with the objc runtime, compile it into a macCatalyst binary, and substitute it for `1999`:

```objc
NSBundle *b = [NSBundle bundleWithPath:@".../Frameworks/UnityFramework.framework"];
[b load];
id ufw = [b.principalClass getInstance];
if (![ufw appController]) [ufw setExecuteHeader:&_mh_execute_header];
[ufw runUIApplicationMainWithArgc:argc argv:argv];
```

The encrypted `1999` never takes part in execution again.

**Pitfall**: never call `setDataBundleId:`. If you do, Unity looks for `global-metadata.dat` under `UnityFramework.framework/Data/`, IL2CPP initialization fails, and the app exits.

### ③ PlayCover performs the platform conversion

When PlayCover 3.x imports an app it:

- changes `LC_BUILD_VERSION platform` of every Mach-O in the app from `IOS` to `MACCATALYST`
- injects `PlayTools.framework` (mouse → `UITouch` mapping, window management)
- re-signs with an ad-hoc signature

The result is an ordinary Mac app with a freely resizable window.

**Pitfall 1**: PlayCover writes the injected dylib path string near `main`. If the shell's `main` sits too early, it gets overwritten with garbage (`EXC_BAD_INSTRUCTION`; the ASCII is visible in `subcode`). That is why `entry.s` has a `.space 0x1200` guard in front of `_main`.

**Pitfall 2**: `PlayTools` must be linked, otherwise the game runs but **mouse clicks do nothing at all** (no UITouch translation).

### ④ Memory patch (in the shell, before Unity initializes)

```
ZProj.ScreenAdaption (pure-code static class, not inside any AssetBundle)
    DesignWidth       = 1920.0f      UnityFramework offset 0x6e07a30
    DesignHeight      = 1080.0f      offset 0x6e07a34
    WHRateThreshold   = 0.01f        offset 0x54daafc   movk w9,#0x3c23

    _GetHeightScaleRate()  0x54da6ac   |screenAspect − 16:9| <= 0.01 ? 1.0 : compensation factor
    _AutoAdapterMask()     0x54da7dc   (rate−1) > 0.01 ? enable maskRoots black-bar mask : disable
    LateUpdate()           0x54daa74   re-runs when the window changes
```

Screen 4:3 = 1.3339 vs design 16:9 = 1.7778, difference **0.4439 ≫ 0.01** → the mask is guaranteed to activate.

In the shell, `vm_protect` obtains write permission and then changes 4 bytes:

```
0x54daafc:  69 84 a7 72  →  09 e8 a7 72
            movk w9,#0x3c23  →  movk w9,#0x3f40   (0.01f → 0.7537f)
```

With the threshold enlarged, `(rate − 1) > threshold` is always false → the black-bar mask never activates.

### Three other Mac porting pitfalls, also fixed

| Symptom | Cause | Fix |
|---|---|---|
| Hot update hangs in an infinite loop at 629 KB, log spams `Network is unreachable!` | The game downloads via an `NSURLSession` **background session**; under macCatalyst the background transfer never returns to the delegate, and after the timeout Unity wraps it as unreachable | In the shell, swizzle `backgroundSessionConfigurationWithIdentifier:` → `defaultSessionConfiguration` |
| Some environments report unreachable as well | The machine has no IPv6 egress route | interpose `getaddrinfo` to force `AF_INET` |
| Mouse does nothing | PlayTools not loaded | at build time `-Wl,-weak_framework,PlayTools -Wl,-rpath,$HOME/Library/Frameworks` |

---

## 3. Compatibility

| Item | Status |
|---|---|
| Region | CN `com.bluepoch.m.reverse1999` **v4.0.0 (build 210)** — actually tested |
| International | `com.bluepoch.m.en.reverse1999.ios` — same structure, untested (offsets must be confirmed yourself) |
| JP | not verified |
| macOS | 26.x (Apple Silicon, M series) |
| PlayCover | 3.1.0 |
| Game engine | Unity 2022.3.62f2 + il2cpp (metadata v31) |

---

## 4. Quick start

Install PlayCover and the Xcode Command Line Tools, then import the game once in PlayCover. From this checkout run:

```bash
./r1999 deploy
./r1999 install  # One-time Finder shortcut in /Applications
./r1999 start
./r1999 verify
./r1999 update
```

Update fast-forwards the current branch and redeploys. For a game update, import the new game in PlayCover and run `./r1999 deploy`. If clicking a login field fails to focus it, quit the game, run `./r1999 controls native`, then restart. This disables PlayCover keymapping for this game. To restore it, quit, run `./r1999 controls mapped` and restart.

---

## 5. Known issues

| # | Issue | Impact | Status |
|---|---|---|---|
| 1 | Account or password field cannot gain focus | Login input is unavailable | With native controls enabled (section 4), the phone number field accepted focus and typing on PlayCover 3.1.0. |
| 2 | 16:10 fullscreen still has about 5% black bars at top and bottom | Screen 3024×1964 (1.539) ≠ design 16:9 (1.778) | Drag the window to 16:9 for zero black bars; a fullscreen 16:10 screen needs a Camera aspect change (v0.2) |
| 3 | 120Hz not verified | The screen supports ProMotion, but the game may set its own `Application.targetFrameRate=60` and override the hook | v0.2 |
| 4 | First launch requires a full download of ~22 GB | PlayCover's app is an independent container | Normal. Resources already downloaded by the official app are TCC-isolated and cannot be reused directly |
| 5 | The game is not sandboxed and writes straight into `~/Documents/` | `ResLib/`, `logicLog`, `XfPayReport.sqlite` are scattered in Documents | Can be cleaned up manually |

---

## 6. What to do after a game version update

**The shell does not change, but the offsets must be re-located — signature scanning keeps maintenance near zero.**

`locate_offset.py` searches `UnityFramework` with a 12-byte signature:

```
49 e1 9a 52    mov  w9, #0xd70a
69 84 a7 72    movk w9, #0x3c23, lsl #16      ← 0x3c23 is exactly 0.01f
09 09 00 b9    str  w9, [x8, #8]
```

Measured on v4.0.0: **only one hit each** in both the original binary and the PlayCover-converted binary, so uniqueness is not a problem.

| Change | What you need to do |
|---|---|
| Minor update (4.0.x → 4.1.x) | Run `locate_offset.py` to get the new offset; the shell logic stays untouched |
| Official rewrite of the adaptation system | Reverse `ScreenAdaption` again |
| Major Unity upgrade (2022.3 → 6.x) | The il2cpp metadata format changes; dump the method addresses again |

---

## 7. Where the game body comes from (extraction method)

**Everything comes from the official app already installed on your own machine** — no IPA decryption and no jailbreak required:

```
/Applications/重返未来：1999.app/
└── Wrapper/1999.app/
    ├── 1999                                       ← encrypted shell, this project never executes it
    ├── Frameworks/UnityFramework.framework/       ← plaintext, loaded at runtime by our shell
    ├── Data/Managed/Metadata/global-metadata.dat  ← type/method tables, used to locate offsets
    └── Data/                                      ← assets, used as-is
```

What `extract.py` does (**read-only**, produces no distributable game files):

1. Read the sha256 / segment layout / encryption state of `UnityFramework`
2. Read the version and type/method counts of `global-metadata.dat`
3. Locate the offsets of the threshold and the design resolution via signature scanning, and print a report
4. Optional: parse the metadata and list the RVA of each `ZProj.ScreenAdaption` method

It does **not** copy UnityFramework or any game asset into the repository; it only generates a `report.json` for `build.sh` to use.

> This is also why this project needs no "IPA decryption" — PlayCover is only a platform converter, we supply the shell ourselves, and the encrypted main binary never takes part from beginning to end.

---

## 8. Repository layout

```
reverse1999fullscreenformac/
├── README.md / README.en.md / README.ja.md
├── shell/
│   ├── entry.s          .space 0x1200 guard + b _r1999_main
│   └── shell.m          the shell itself: PlayTools weak linkage / CADisplayLink hook /
│                        threshold patch / background session fix / IPv4 forcing
├── build.sh             compile → deploy → re-sign → self-check
├── locate_offset.py     signature search, prints an offset report
├── extract.py           read info from the official app on this machine and self-check (read-only)
├── patch_ipa.py         insert the shell into an unpacked IPA
└── docs/
    ├── ANATOMY.md       why the patch cannot be applied to the official app (three measured facts: FairPlay / amfid / TCC)
    └── IPA-SOURCES.md   findings from research into decrypted-IPA channels
```

---

## 9. Disclaimer

- This project contains **no** game files, assets, or keys; the game itself is free on the App Store.
- It is only meant to let you play **a copy you installed yourself** at a suitable window size on your Mac.
- The modified app is signed and run locally by you, and does not affect server-side checks.
- Do not distribute the modified `.ipa`.
