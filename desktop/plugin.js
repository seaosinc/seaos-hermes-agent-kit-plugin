/**
 * SEAOS — デスクトップ側の薄い皮。
 *
 * **ここは滅多に変えない。** Hermes はプラグインの JS を起動時に一度だけ読み込み、
 * ⌘K の Reload desktop plugins は既知のファイルを素通りする（増えた／消えた
 * フォルダしか見ない）。**編集をその場で反映する手が、ホスト側に無い。**
 *
 * レンダラごと読み直せば入れ替わるが、それはペインの構成を壊した（サイドバーが
 * 幅0で残り、Reset layout が要る状態になった）。**便利さのために本体のレイアウトを
 * 危険に晒す取引は割に合わない。**
 *
 * そこで、入れ替わらないのはこのファイルだけにする。画面の中身（ui.js）は
 * バックエンドから取り直して、その場で読み込む。**中身はいつでも作り直せる。**
 *
 * 素の ESM で読まれる（ビルド不要）。JSX 構文は使えないので jsx() 呼び出しで書く。
 */

import { ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, host } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useCallback, useEffect, useRef, useState } from 'react'

const ID = 'seaos-hermes-agent-kit-plugin'  // plugin.yaml / dashboard/manifest.json と同じ名前
const DANGER = '#B4413C'
const WARN = '#B4761F'
// **エラーの文言は選択・コピーできるようにする。** アプリ全体で選択が止められていて、
// 画面に出た原因を貼ることすらできなかった。
const SELECTABLE = { userSelect: 'text', WebkitUserSelect: 'text', cursor: 'text' }

/** ui.js へ渡す道具。**あちらは import を書けない**ので、ここで揃えて渡す。 */
const DEPS = { jsx, jsxs, useCallback, useEffect, useRef, useState, host }

/** 画面の中身を取り込んで描く。
 *
 * ホストのローダと同じ手口（ブロブにして動的 import）を使う。**取り込むたびに
 * 別の URL になる**ので、モジュールのキャッシュは効かない——つまり毎回、
 * ディスクにある新しいコードが走る。
 */
function Host({ ctx }) {
  const [Page, setPage] = useState(null)
  // { message, detail, warn }。warn は「待てば直ることが多い」ものを警告色で出す印
  const [error, setError] = useState(null)

  const fetchUi = useCallback(async () => {
    setError(null)
    let res
    try {
      res = await ctx.rest('/ui.js')
    } catch (e) {
      // **原因はほぼ一つ。** 「いま選んでいるプロファイルの設定で、このプラグインが
      // 有効になっていない」。プラグインの本体は共通に1つしか無いのに、有効かどうかは
      // プロファイルごとに決まるため、役のプロファイル（operator など）を選んだまま
      // 開くとここに来る。**入れ直しても直らない**——プロファイルの設定は変わらないため。
      // 再読み込みも詳細のコピーも、この状況では何も動かせないので出さない。
      const detail = e?.detail || e?.message || String(e)
      setError({
        warn: true,
        message:
          '画面左下でプロファイルを default に切り替えてから、もう一度 SEAOS を開いてください。' +
          'SEAOS の画面は default でだけ開きます（他の役を選んでいる間は開けません）。',
        detail
      })
      return
    }
    const source = res?.source
    if (!source) {
      setError({ message: '画面の内容が空でした', detail: '' })
      return
    }
    const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }))
    try {
      const mod = await import(/* @vite-ignore */ url)
      if (typeof mod.default !== 'function') {
        throw new Error('ui.js が関数を既定エクスポートしていません')
      }
      // 関数をそのまま state に入れると呼ばれてしまうので、包んで渡す
      const built = mod.default({ ...DEPS, ctx, reloadUi: fetchUi })
      setPage(() => built)
    } catch (e) {
      setError({ message: '画面を読み込めません', detail: String(e?.message || e) })
    } finally {
      URL.revokeObjectURL(url)
    }
  }, [ctx])

  useEffect(() => {
    fetchUi()
  }, [fetchUi])

  if (error) {
    const color = error.warn ? WARN : DANGER
    return jsxs('div', {
      className: 'mx-auto flex max-w-3xl flex-col gap-3 p-6',
      children: [
        jsx('div', { className: 'text-lg font-medium', children: 'SEAOS' }),
        jsxs('div', {
          className: 'select-text break-all rounded px-3 py-2 text-xs',
          style: { border: `1px solid ${color}`, color, ...SELECTABLE },
          children: [
            jsx('div', { children: error.message }),
            error.detail
              ? jsx('div', { className: 'mt-1 opacity-70', style: SELECTABLE, children: `詳細: ${error.detail}` })
              : null
          ]
        })
      ]
    })
  }

  if (!Page) {
    return jsx('div', { className: 'p-6 text-xs opacity-60', children: '読み込み中…' })
  }

  return jsx(Page, { ctx })
}

export default {
  id: ID,
  name: 'SEAOS',
  register(ctx) {
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/agent-kit' },
        render: () => jsx(Host, { ctx })
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: '/agent-kit', label: 'SEAOS', codicon: 'organization' }
      },
      {
        id: 'palette',
        area: PALETTE_AREA,
        data: {
          id: `${ID}.open`,
          title: 'SEAOS を開く',
          run: () => host.navigate('/agent-kit')
        }
      }
    ])
  }
}
