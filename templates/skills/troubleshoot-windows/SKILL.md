---
name: troubleshoot-windows
description: "Windows に固有の不具合の手順。seaos-kit が「パスが見つかりません」、文字化け・エンコーディングのエラー、スキルを読めない、Docker が動かない（WSL2）、wsl --install が REGDB_E_CLASSNOTREG で止まるとき。"
version: 1.0.0
metadata:
  hermes:
    tags: [troubleshooting, windows, encoding, wsl]
---

# Windows で壊れる

Windows の Hermes のホームは `%LOCALAPPDATA%\hermes`（`~\.hermes` ではない）。PowerShell では
`$env:LOCALAPPDATA` と書く（`%LOCALAPPDATA%` はコマンドプロンプトの書き方で、PowerShell では展開されない）。

## seaos-kit が「指定されたパスが見つかりません」

`%LOCALAPPDATA%\Programs\seaos-kit\seaos-kit.cmd` の中身を見る。

- 改行が `\r\r\n` になっていないか、パスが化けていないか（ユーザー名が日本語だと起きやすい）
- `seaos-kit update` で書き直される。それまでは、Python で直接呼べる

      & "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" `
        "$env:LOCALAPPDATA\hermes\plugins\seaos-hermes-agent-kit-plugin\core\cli.py" doctor

## 文字化け・エンコーディングのエラー

日本語版 Windows の既定の文字コードは cp932。先に UTF-8 を指定してから実行する。

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

## スキルを読めない（「Skill '…' is not supported on this platform」）

スキルの `platforms:` に Windows が入っていない。キットのスキルからは外してあるので、`seaos-kit update` で直る。
この PC で書いたスキルなら、`platforms:` の行を消す。

## Docker が動かない

Windows の Docker Desktop は WSL2 が要る。WSL2 は既定では入っていない。

1. 管理者の PowerShell で `wsl --install --no-distribution` → 再起動
2. Docker Desktop を起動して、利用規約に同意する

### wsl --install が `Wsl/CallMsi/Install/REGDB_E_CLASSNOTREG` で止まる

WSL ではなく、Windows のインストーラー（MSI）が動いていない。管理者の PowerShell で:

    Set-Service msiserver -StartupType Manual
    Start-Service msiserver
    msiexec /unregister
    msiexec /regserver

`Start-Service` で「無効」と言われたら、会社のポリシーで止められている。情報システムの担当に頼む。
BIOS で仮想化（Intel VT-x / AMD-V）が切られていても動かない。
