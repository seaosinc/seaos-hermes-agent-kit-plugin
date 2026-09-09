# 作業部屋のセッション初期化。ログインシェルから /etc/profile 経由で読まれる。
#
# **ここに必須のものは置かない。** Hermes は /root と /home を tmpfs で潰すので、
# シェルの初期化ファイルが読まれない経路がある。効かないと困るもの（PATH、
# キャッシュの向き先、CA、git の名乗り）は Dockerfile の ENV に焼いてある。
# ここに残るのは「あれば嬉しい」だけの後始末である。

# キャッシュの置き場を用意する。無くても各ツールが自分で作るので、失敗しても進む。
mkdir -p /cache/mise /cache/m2 /cache/gradle /cache/npm /cache/xdg \
         /cache/pip /cache/uv /cache/go/mod /cache/go/build /cache/cargo 2>/dev/null || true

# 委譲先の出力を置く場所。**clone したリポジトリの外**に作る（commit に混ざらないよう）。
mkdir -p /workspace/.hermes 2>/dev/null || true
