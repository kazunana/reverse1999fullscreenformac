# reverse1999fullscreenformac

[中文](README.md) · [English](README.en.md)

『リバース：1999』(Reverse: 1999) の **iPad 版** を Apple Silicon Mac 上で「自由にリサイズできる通常のウィンドウ」として動作させ、letterbox の黒帯を取り除きます。

**バージョン**：`v0.1.400` — パッチバージョン `0.1` × 上流ゲーム `4.0.0 (build 210)`

**本リポジトリに含まれるのはパッチコードとツールのみで、ゲームファイルは一切含まれていません。** ゲーム本体は App Store で**無料**配布されています。ご自身の Apple ID でインストールしてください。

---

## 1. 何を解決するのか

App Store の iPad 版を Mac にインストールすると、「iOS app on Mac」として動作します：

| 現状 | 原因 |
|---|---|
| ウィンドウが 1366×1024（4:3）に固定され、ドラッグできない | `UIRequiresFullScreen=true` と横向きのみの許可 |
| 上下に大きな黒帯が出る | ゲームは 1920×1080（16:9）で設計されているため、4:3 のウィンドウでは letterbox が必然 |
| フルスクリーンにすると今度は左右に黒帯が出る | ウィンドウの比率が 4:3 固定であるのに対し、画面は 16:10 |

変更後は、ウィンドウを自由にリサイズでき、フルスクリーンにもでき、**16:9 では黒帯ゼロ**になります。

---

## 2. 仕組み（4 つの層）

### ① 重要な観測：FairPlay がロックしているのは 32 KB だけ

```
Wrapper/1999.app/1999          71,632 B   __TEXT 32 KB   cryptid=1 → 暗号化
  └ 標準的な Unity iOS の起動シェルにすぎず、UnityFramework をロードしてから runUIApplicationMain を呼ぶ

Frameworks/UnityFramework.framework/UnityFramework
                              143,858,752 B              cryptid=0 → 平文
  └ il2cpp のロジック全体：18,279 型 / 167,004 メソッド
```

ゲームの実コードは平文で、暗号化されているのは数十 KB の起動シェルだけです。

### ② 自作の起動シェル（FairPlay を回避）

objc runtime で標準的な Unity iOS の起動手順を再現し、macCatalyst バイナリとしてコンパイルしたうえで `1999` を置き換えます：

```objc
NSBundle *b = [NSBundle bundleWithPath:@".../Frameworks/UnityFramework.framework"];
[b load];
id ufw = [b.principalClass getInstance];
if (![ufw appController]) [ufw setExecuteHeader:&_mh_execute_header];
[ufw runUIApplicationMainWithArgc:argc argv:argv];
```

暗号化された `1999` は、これ以降実行に関与しません。

**ハマりどころ**：`setDataBundleId:` は絶対に呼ばないでください。呼ぶと Unity は `UnityFramework.framework/Data/` 配下の `global-metadata.dat` を探しに行き、IL2CPP の初期化に失敗して即座に終了します。

### ③ PlayCover によるプラットフォーム変換

PlayCover 3.x は app をインポートするときに次を行います：

- app 内の全 Mach-O の `LC_BUILD_VERSION platform` を `IOS` から `MACCATALYST` に変更する
- `PlayTools.framework` を注入する（マウス → `UITouch` のマッピング、ウィンドウ管理）
- ad-hoc 署名で再署名する

これで普通の Mac app になり、ウィンドウを自由にリサイズできます。

**ハマりどころ 1**：PlayCover は注入する dylib のパス文字列を `main` の近くに書き込みます。シェルの `main` が先頭に寄りすぎていると、そこが上書きされて文字化けします（`EXC_BAD_INSTRUCTION`、`subcode` の中に ASCII が見えます）。そのため `entry.s` では `_main` の前に `.space 0x1200` のガードを置いています。

**ハマりどころ 2**：`PlayTools` をリンクする必要があります。リンクしないとゲームは動きますが、**マウスクリックに一切反応しません**（UITouch の変換がないため）。

### ④ メモリパッチ（シェル内、Unity 初期化前）

```
ZProj.ScreenAdaption（純粋なコードの静的クラスで、どの AssetBundle にも含まれない）
    DesignWidth       = 1920.0f      UnityFramework オフセット 0x6e07a30
    DesignHeight      = 1080.0f      オフセット 0x6e07a34
    WHRateThreshold   = 0.01f        オフセット 0x54daafc   movk w9,#0x3c23

    _GetHeightScaleRate()  0x54da6ac   |screenAspect − 16:9| <= 0.01 ? 1.0 : 補正係数
    _AutoAdapterMask()     0x54da7dc   (rate−1) > 0.01 ? maskRoots の黒帯マスクを有効化 : 解除
    LateUpdate()           0x54daa74   ウィンドウ変化時に再実行
```

画面 4:3 = 1.3339 に対し設計 16:9 = 1.7778、差は **0.4439 ≫ 0.01** → マスクは必ず有効になります。

シェル内で `vm_protect` により書き込み権限を取得し、4 バイトを書き換えます：

```
0x54daafc:  69 84 a7 72  →  09 e8 a7 72
            movk w9,#0x3c23  →  movk w9,#0x3f40   (0.01f → 0.7537f)
```

しきい値を大きくした結果、`(rate − 1) > threshold` は常に偽になり → 黒帯マスクは決して有効になりません。

### あわせて修正した Mac 移植の 3 つのハマりどころ

| 症状 | 原因 | 修正方法 |
|---|---|---|
| ホットアップデートが 629 KB で無限ループし、ログに `Network is unreachable!` が出続ける | ゲームが `NSURLSession` の **background session** でダウンロードするが、macCatalyst ではバックグラウンド転送が delegate に戻らず、タイムアウト後に Unity が unreachable としてラップしてしまう | シェル内で `backgroundSessionConfigurationWithIdentifier:` を `defaultSessionConfiguration` に swizzle する |
| 一部の環境でも同じく unreachable になる | 本機に IPv6 の出口ルートがない | `getaddrinfo` に interpose を差し込み、`AF_INET` を強制する |
| マウスでクリックできない | PlayTools がロードされていない | ビルド時に `-Wl,-weak_framework,PlayTools -Wl,-rpath,$HOME/Library/Frameworks` |

---

## 3. 互換性

| 項目 | 状態 |
|---|---|
| サーバー | 中国版 `com.bluepoch.m.reverse1999` **v4.0.0 (build 210)** — 実機検証済み |
| 国際版 | `com.bluepoch.m.en.reverse1999.ios` — 構造は同一、未検証（オフセットは各自で確認が必要） |
| 日本版 | 未検証 |
| macOS | 26.x（Apple Silicon、M シリーズ） |
| PlayCover | 3.1.0 |
| ゲームエンジン | Unity 2022.3.62f2 + il2cpp（metadata v31） |

---

## 4. クイックスタート

```bash
# 1. PlayCover をインストール  https://github.com/PlayCover/PlayCover/releases
# 2. インストール済みの app から IPA を作成し、PlayCover にインポート（ゲームは無料）
#    PlayCover が次のディレクトリを生成します：
#    ~/Library/Containers/io.playcover.PlayCover/Applications/com.bluepoch.m.reverse1999.app
# 3. パッチをインストール
./build.sh --all
# 4. 起動
open ~/Library/Containers/io.playcover.PlayCover/Applications/com.bluepoch.m.reverse1999.app
```

`build.sh --verify` は、元のセグメント配置 / しきい値のバイト列が一致しているか / デプロイ済みシェルの署名と弱リンクを自己検査します。

---

## 5. 既知の問題

| # | 問題 | 影響 | 状態 |
|---|---|---|---|
| 1 | **ゲーム内のテキストボックスがキーボード入力を受け付けない** | ログインは**QR コードの読み取り**で行ってください。名前変更や検索など、入力が必要な場面に影響します。入力欄はゲーム内でごく僅かな割合です | 既知。PlayTools の `UITextField` → `UITextInput` ブリッジが macCatalyst では機能しないため、シェル側に `insertText:` の転送層を追加する必要があります（v0.2） |
| 2 | 16:10 のフルスクリーンでは上下に約 5% の黒帯が残る | 画面 3024×1964（1.539）≠ 設計 16:9（1.778） | ウィンドウを 16:9 にドラッグすれば黒帯ゼロ。16:10 で画面いっぱいに使うには Camera aspect の変更が必要（v0.2） |
| 3 | 120Hz は未検証 | 画面は ProMotion に対応しているが、ゲームが `Application.targetFrameRate=60` を独自に設定して hook を上書きしている可能性がある | v0.2 |
| 4 | 初回起動時に約 22 GB の全量ダウンロードが必要 | PlayCover の app は独立したコンテナである | 正常です。正規版でダウンロード済みのリソースは TCC で分離されているため、そのまま流用できません |
| 5 | ゲームはサンドボックス化されておらず、`~/Documents/` に直接書き込む | `ResLib/`、`logicLog`、`XfPayReport.sqlite` が Documents に散在する | 手動で整理できます |

---

## 6. ゲームのバージョンアップ後にやること

**シェルは変更不要ですが、オフセットは再特定が必要です —— シグネチャ検索を使えばメンテナンスはほぼゼロにできます。**

`locate_offset.py` は 12 バイトのシグネチャで `UnityFramework` 内を検索します：

```
49 e1 9a 52    mov  w9, #0xd70a
69 84 a7 72    movk w9, #0x3c23, lsl #16      ← 0x3c23 が 0.01f
09 09 00 b9    str  w9, [x8, #8]
```

v4.0.0 での実測：元のバイナリでも PlayCover 変換後のバイナリでも**ヒットはそれぞれ 1 か所だけ**で、一意性に問題はありません。

| 変化 | 必要な作業 |
|---|---|
| マイナーアップデート（4.0.x → 4.1.x） | `locate_offset.py` を実行して新しいオフセットを取得する。シェルのロジックはそのまま |
| 公式が適応システムを書き換えた | `ScreenAdaption` を再度リバースエンジニアリングする |
| Unity のメジャーアップグレード（2022.3 → 6.x） | il2cpp のメタデータ形式が変わるため、メソッドアドレスを再度 dump する |

---

## 7. ゲーム本体の入手元（抽出方法）

**すべて、ご自身のマシンにインストール済みの正規版 app から取得します。** IPA の復号も脱獄も不要です：

```
/Applications/重返未来：1999.app/
└── Wrapper/1999.app/
    ├── 1999                                       ← 暗号化シェル。本プロジェクトでは実行しない
    ├── Frameworks/UnityFramework.framework/       ← 平文。実行時に自前のシェルがロードする
    ├── Data/Managed/Metadata/global-metadata.dat  ← 型・メソッドテーブル。オフセット特定に使用
    └── Data/                                      ← アセット。そのまま使用
```

`extract.py` が行うこと（**読み取り専用**で、配布可能なゲームファイルは生成しません）：

1. `UnityFramework` の sha256 / セグメント配置 / 暗号化状態を読み出す
2. `global-metadata.dat` のバージョンと型・メソッド数を読み出す
3. シグネチャ検索でしきい値と設計解像度のオフセットを特定し、レポートを出力する
4. 任意：metadata を解析し、`ZProj.ScreenAdaption` の各メソッドの RVA を一覧表示する

UnityFramework やゲームのアセットをリポジトリへコピーすることは**ありません**。`build.sh` が使う `report.json` を 1 つ生成するだけです。

> これが本プロジェクトで「IPA の復号」が不要な理由でもあります。PlayCover はあくまでプラットフォーム変換器で、シェルは自前で用意し、暗号化されたメインバイナリは最初から最後まで関与しません。

---

## 8. リポジトリ構成

```
reverse1999fullscreenformac/
├── README.md / README.en.md / README.ja.md
├── shell/
│   ├── entry.s          .space 0x1200 のガード + b _r1999_main
│   └── shell.m          シェル本体：PlayTools の弱リンク / CADisplayLink hook /
│                        しきい値パッチ / background session の修正 / IPv4 の強制
├── build.sh             コンパイル → デプロイ → 再署名 → 自己検査
├── locate_offset.py     シグネチャ検索、オフセットレポートを出力
├── extract.py           本機の正規版から情報を読み出して自己検査（読み取り専用）
├── patch_ipa.py         展開済み IPA にシェルを差し込む
└── docs/
    ├── ANATOMY.md       正規版にパッチを当てられない理由（FairPlay / amfid / TCC の 3 点を実測）
    └── IPA-SOURCES.md   復号済み IPA の入手経路に関する調査結論
```

---

## 9. 免責

- 本プロジェクトにはゲームファイル・アセット・キーは**一切含まれません**。ゲーム本体は App Store で無料配布されています。
- Mac 上で**ご自身がインストールした**コピーを適切なウィンドウサイズでプレイするためのものに限られます。
- 改変後のアプリはご自身が本機で署名して実行するものであり、サーバー側の検証には影響しません。
- 改変後の `.ipa` を配布しないでください。
