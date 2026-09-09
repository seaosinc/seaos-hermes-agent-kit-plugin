# 公式イメージ mem0/mem0-api-server:latest は、自分の既定設定
# （pgvector + neo4j graph store）に必要な依存を含んでいない。
# 起動時に ImportError が連鎖するので、足りないものをまとめて入れる。
#   psycopg          : pgvector の接続
#   langchain-neo4j  : graph_store。main.py にハードコードされていて外せない
#   rank-bm25        : グラフ検索のリランキング
FROM mem0/mem0-api-server:latest
RUN pip install --no-cache-dir \
      "psycopg[binary,pool]" \
      langchain-neo4j \
      rank-bm25

# Hermes の mem0 プラグインは user_id を filters の中に入れて送るが、
# このサーバーはトップレベルしか見ない。その差を吸収する。
COPY compat.py sitecustomize.py /app/
