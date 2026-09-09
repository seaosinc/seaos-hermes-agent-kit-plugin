# **エージェント側（ツール・フック）は持たない。** このプラグインの中身は
# dashboard/ と desktop/ にある。
#
# それでもこのファイルが要るのは、ローダが v1 プラグインを Python パッケージとして
# import しようとし、無いと起動のたびに errors.log へ
# 「Failed to load plugin ... No __init__.py」を残すため。空で黙る。
