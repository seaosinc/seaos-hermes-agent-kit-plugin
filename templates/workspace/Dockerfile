# カードごとに立てて捨てる作業部屋。
#
# **薄く保つことが目的である。** 1台の Mac の上で何部屋も同時に立てるので、
# 1部屋が重いと全部が詰まる。Codex や Claude のクラウドは1セッションに
# VM を1台あてがえるから全部入りで殴れるが、こちらは同じ手が使えない。
#
# 層の切り方は「変わる頻度」で決める（Cursor の snapshot / install / start と同じ）。
#
#   ここ（image）  年に数回変わる    シェル・git・gh・opencode・mise
#   /cache（volume）たまに変わる      言語ランタイム本体、落としたパッケージ
#   /workspace      毎回変わる        clone したコード。コンテナごと消える
#
# **言語ランタイムはここに焼かない。** リポジトリの .tool-versions / mise.toml を
# 読んで mise が /cache に入れる。焼くと言語ごとにイメージを持つ羽目になる。
#
# ブラウザの依存だけは焼く。**実装役が自分の変更を画面で確かめられないと、
# 「テストが通る」を完了条件にできない**ためで、E2E を別の役へ渡すと往復が増える。
# 実測で **イメージが 343MB 太っても起動は変わらない**（212ms → 209ms。
# overlayfs は遅延マウント）ので、増えるのはディスクだけである。

FROM ubuntu:24.04

# `curl | sh` は既定だとパイプの左側の失敗を飲む。**握りつぶすと「入っていない
# イメージ」が黙って出来上がる**ので、pipefail を立ててから使う。
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# **無人で動くための宣言。** この部屋には答える人がいないので、対話に落ちた道具は
# タイムアウトまで固まる。**止まるより、はっきり失敗するほうがよい。**
# パッケージを足すより効く場面が多いので、ここに集めてある。
ENV CI=true \
    TERM=dumb \
    NO_COLOR=1 \
    PAGER=cat \
    GIT_PAGER=cat \
    GIT_TERMINAL_PROMPT=0 \
    npm_config_yes=true \
    npm_config_fund=false \
    npm_config_audit=false \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
# CI=true の副作用: 一部のツールチェーン（create-react-app 系）は警告を
# エラーとして扱うようになる。**それでも入れる**——見えない停止より、見える失敗のほうが
# 扱いやすい。リポジトリ側で外したければ、そのコマンドの前で `CI= ` を付ければよい。

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg jq less openssh-client \
        ripgrep tini unzip wget xz-utils zip \
 && rm -rf /var/lib/apt/lists/*

# 組織の TLS 傍受プロキシの CA。**ホストは信頼していてもコンテナは知らない**ので、
# 入れないと clone も mise install も npm も全部 certificate エラーで落ちる。
# 中身は seaos-kit workspace build が用意する（無い環境では空ファイルになり、
# update-ca-certificates は何もしない）。
COPY extra-ca.crt /usr/local/share/ca-certificates/hermes-extra.crt
RUN if [ -s /usr/local/share/ca-certificates/hermes-extra.crt ]; then \
        update-ca-certificates && echo "組織の CA を入れた"; \
    else \
        rm -f /usr/local/share/ca-certificates/hermes-extra.crt; \
    fi

# gh は GitHub のリポジトリから入れる（Ubuntu の apt には無い）。
# ここに並ぶのは「リポジトリを問わず必ず要るもの」だけに保つ。
RUN install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /etc/apt/keyrings/githubcli.gpg \
 && chmod 0644 /etc/apt/keyrings/githubcli.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/* \
 && gh --version

# AWS CLI v2。**apt の awscli は v1 で古い**ので、公式の zip から入れる。
# アーキテクチャは dpkg に聞く（このイメージは arm64 だが、amd64 でも通るように）。
#
# **認証情報は焼かない。** 実行時に環境変数で渡る。無ければ `aws` は
# その呼び出しだけが失敗し、コンテナもエージェントも落ちない。
RUN arch="$(dpkg --print-architecture)" \
 && case "$arch" in \
      arm64) url=https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip ;; \
      amd64) url=https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip ;; \
      *) echo "未対応のアーキテクチャ: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL "$url" -o /tmp/awscliv2.zip \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscliv2.zip \
 && aws --version

# Chromium が要る OS ライブラリ。**ブラウザ本体は焼かない**——
# PLAYWRIGHT_BROWSERS_PATH を /cache に向けてあるので、849MB のバイナリは
# ボリュームに落ちて1台につき一度で済む。
#
# 一覧は `playwright install-deps chromium --dry-run` が出すものをそのまま使う。
# フォントと xvfb を削っても実測で 73MB しか減らないので、削らない。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
        libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
        libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 xvfb \
        libfontconfig1 libfreetype6 xfonts-cyrillic xfonts-scalable \
        fonts-noto-color-emoji fonts-unifont fonts-liberation \
        fonts-ipafont-gothic fonts-wqy-zenhei fonts-tlwg-loma-otf \
        fonts-freefont-ttf \
 && rm -rf /var/lib/apt/lists/*

# mise: リポジトリが宣言したツールチェーンを実行時に入れる係。
# 入れ先は /cache なので、ここに残るのは mise 自身だけ。
RUN curl -fsSL https://mise.run | MISE_INSTALL_PATH=/usr/local/bin/mise sh \
 && mise --version

# opencode: 実装を任せる CLI エージェント。ネイティブの単一バイナリで入るので
# node は要らない（node が要るのはリポジトリ側の都合であって、こちらの都合ではない）。
#
# **インストーラは $HOME の下に置くが、そこには残せない。** Hermes は使い捨ての部屋で
# /root と /home を tmpfs で潰すので（docker.py の非 persistent 分岐）、
# $HOME に置いたものは実行時に消える。**実体を /usr/local/bin へ移す。**
RUN curl -fsSL https://opencode.ai/install | bash \
 && mv "$(find /root /home -type f -name opencode -perm -u+x | head -1)" /usr/local/bin/opencode \
 && opencode --version

# private な npm レジストリ（GitHub Packages）の認証。
#
# **鍵は焼かない。** 焼くのは「GH_TOKEN を読め」という指示だけで、値は実行時に
# docker_forward_env で渡る。npmrc は ${VAR} をそのまま展開する。
#
# これが無いと、`@scope:registry=https://npm.pkg.github.com` を宣言している
# リポジトリで `npm ci` が 401 になり、**lint も typecheck も build も走らない**
# ——「テストが通る」を完了条件にできなくなる（実際に踏んだ）。
#
# リポジトリ側の .npmrc（スコープ → レジストリの対応）とは併存する。
# こちらが持つのは認証だけである。
RUN printf '//npm.pkg.github.com/:_authToken=${GH_TOKEN}\nalways-auth=true\n' > /etc/npmrc
ENV NPM_CONFIG_GLOBALCONFIG=/etc/npmrc

# キャッシュの向き先。**ENV で焼く**のが一番堅い。
# ~/.profile に頼れないのは opencode と同じ理由で、/root が tmpfs で潰されるため。
ENV MISE_DATA_DIR=/cache/mise \
    MISE_CACHE_DIR=/cache/mise/cache \
    GRADLE_USER_HOME=/cache/gradle \
    npm_config_cache=/cache/npm \
    XDG_CACHE_HOME=/cache/xdg \
    PIP_CACHE_DIR=/cache/pip \
    UV_CACHE_DIR=/cache/uv \
    GOMODCACHE=/cache/go/mod \
    GOCACHE=/cache/go/build \
    CARGO_HOME=/cache/cargo \
    MAVEN_OPTS=-Dmaven.repo.local=/cache/m2 \
    PATH=/cache/mise/shims:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PLAYWRIGHT_BROWSERS_PATH=/cache/playwright

# git の設定も ENV で渡す。**~/.gitconfig は毎回消える**（/root が tmpfs）ので、
# シェルの初期化に頼ると、初期化が走らない経路で名乗りが消えて commit が落ちる。
# GIT_CONFIG_COUNT は git が公式に用意している「設定を環境変数で渡す」口。
ENV GIT_CONFIG_COUNT=3 \
    GIT_CONFIG_KEY_0=safe.directory        GIT_CONFIG_VALUE_0=* \
    GIT_CONFIG_KEY_1=init.defaultBranch    GIT_CONFIG_VALUE_1=main \
    GIT_CONFIG_KEY_2=credential.https://github.com.helper \
    GIT_CONFIG_VALUE_2="!gh auth git-credential" \
    GIT_AUTHOR_NAME=hermes-worker    GIT_AUTHOR_EMAIL=hermes-worker@localhost \
    GIT_COMMITTER_NAME=hermes-worker GIT_COMMITTER_EMAIL=hermes-worker@localhost

# 委譲先（opencode）に部屋の性質を教える。
#
# **箱を作っても、中で動く側が何があるか知らなければ意味がない。**
# opencode は毎回 instructions を読むので、承認が無いこと・apt が通らないこと・
# /cache が残ることを、指示のたびに書かなくても知っている状態になる。
#
# 置き場を XDG_CONFIG_HOME で /etc へ逃がすのは、opencode の既定の探索先が
# $HOME/.config と $HOME/.opencode で、**どちらも tmpfs で消える**ため。
ENV XDG_CONFIG_HOME=/etc/hermes-config
COPY opencode-instructions.md /etc/hermes-config/box.md
RUN mkdir -p /etc/hermes-config/opencode \
 && printf '{"instructions":["/etc/hermes-config/box.md"]}\n' \
      > /etc/hermes-config/opencode/opencode.json

# **道具の一覧は手で書かない。** 実際に入っているものをビルド時に写す
# （手書きの一覧は中身と食い違っていくため）。
RUN { printf '\n## いま入っている道具\n\n```\n'; \
      for c in git gh mise opencode jq rg curl aws; do \
        printf '%-10s %s\n' "$c" "$($c --version 2>&1 | head -1)"; \
      done; \
      printf '```\n\nここに無いものは mise で入れる。\n'; \
    } >> /etc/hermes-config/box.md

# 実行が要る初期化（ディレクトリの用意、git の名乗り、gh の資格情報）。
# /etc に置くのは、ログインシェルが /etc/profile 経由で読むためである。
COPY profile.sh /etc/profile.d/hermes-workspace.sh

WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
