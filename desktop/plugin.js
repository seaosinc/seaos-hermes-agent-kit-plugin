/**
 * Agent Kit — デスクトップ側の半身。
 *
 * **素の ESM で読まれる（ビルド不要）。** JSX 構文は使えないので UI は jsx() 呼び出しで書く。
 * 解決する import は @hermes/plugin-sdk / react / react/jsx-runtime だけ。
 *
 * この画面は判断を持たない。ctx.rest 経由で dashboard/plugin_api.py を呼び、
 * その先の core/ が CLI とまったく同じ関数を実行する。
 */

import { ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, host } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useCallback, useEffect, useState } from 'react'

const ID = 'seaos-hermes-agent-kit'

/** バックエンドが落ちている（＝Python 側のトグルが未投入）ときは、そう言う。 */
async function call(ctx, path, init) {
  try {
    return await ctx.rest(path, init)
  } catch (error) {
    throw new Error(
      'バックエンドに届きません。設定 → プラグインで、この拡張の Python 側を有効にしてください。'
    )
  }
}

function Row({ label, value, tone }) {
  const color =
    tone === 'ok' ? 'text-(--ui-success)' : tone === 'warn' ? 'text-(--ui-warning)' : 'text-(--ui-text-tertiary)'
  return jsxs('div', {
    className: 'flex items-center justify-between gap-3 py-1.5 border-b border-(--ui-border) last:border-0',
    children: [
      jsx('span', { className: 'text-sm', children: label }),
      jsx('span', { className: `text-xs ${color}`, children: value })
    ]
  })
}

function KitPane({ ctx }) {
  const [roles, setRoles] = useState([])
  const [secrets, setSecrets] = useState([])
  const [log, setLog] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      setRoles(await call(ctx, '/roles'))
      setSecrets(await call(ctx, '/secrets'))
    } catch (e) {
      setError(e.message)
    }
  }, [ctx])

  useEffect(() => {
    load()
  }, [load])

  const run = useCallback(
    async (path, body) => {
      setBusy(true)
      setError('')
      try {
        const res = await call(ctx, path, {
          method: 'POST',
          body: JSON.stringify(body || {})
        })
        setLog(res.lines || [])
        await load()
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [ctx, load]
  )

  const missing = secrets.filter((s) => s.required && !s.configured)

  return jsxs('div', {
    className: 'flex h-full flex-col gap-4 overflow-y-auto p-4 text-sm',
    children: [
      jsx('div', { className: 'text-base font-medium', children: 'エージェント役の導入' }),

      error
        ? jsx('div', {
            className: 'rounded border border-(--ui-danger) px-3 py-2 text-xs text-(--ui-danger)',
            children: error
          })
        : null,

      // 1. 鍵
      jsxs('section', {
        className: 'flex flex-col gap-1',
        children: [
          jsx('div', { className: 'text-xs uppercase tracking-wide text-(--ui-text-tertiary)', children: '1. 鍵' }),
          ...secrets.map((s) =>
            jsx(Row, {
              label: s.name + (s.required ? ' *' : ''),
              value: s.configured ? '設定済み' : '未設定',
              tone: s.configured ? 'ok' : s.required ? 'warn' : 'muted'
            }, s.name)
          ),
          jsx('div', {
            className: 'pt-1 text-xs text-(--ui-text-tertiary)',
            children: '値は画面に表示しません。保存先はキット直下の .env です。'
          })
        ]
      }),

      // 2. 役
      jsxs('section', {
        className: 'flex flex-col gap-1',
        children: [
          jsx('div', { className: 'text-xs uppercase tracking-wide text-(--ui-text-tertiary)', children: '2. 役' }),
          ...roles.map((r) =>
            jsx(Row, {
              label: r.name + (r.onBoard ? '' : '（板に載らない）'),
              value: r.installed ? '導入済み' : '未導入',
              tone: r.installed ? 'ok' : 'muted'
            }, r.name)
          )
        ]
      }),

      // 3. 実行
      jsxs('section', {
        className: 'flex flex-col gap-2',
        children: [
          jsx('div', { className: 'text-xs uppercase tracking-wide text-(--ui-text-tertiary)', children: '3. 反映' }),
          missing.length
            ? jsx('div', {
                className: 'text-xs text-(--ui-warning)',
                children: `必須の鍵が ${missing.length} 件未設定です（${missing.map((s) => s.name).join(', ')}）`
              })
            : null,
          jsxs('div', {
            className: 'flex gap-2',
            children: [
              jsx('button', {
                className:
                  'rounded bg-(--ui-accent) px-3 py-1.5 text-xs text-(--ui-accent-foreground) disabled:opacity-50',
                disabled: busy,
                onClick: () => run('/update'),
                children: busy ? '実行中…' : '生成して反映'
              }),
              jsx('button', {
                className: 'rounded border border-(--ui-border) px-3 py-1.5 text-xs disabled:opacity-50',
                disabled: busy,
                onClick: () => run('/env/apply'),
                children: '鍵だけ配る'
              })
            ]
          }),
          log.length
            ? jsx('pre', {
                className:
                  'max-h-48 overflow-auto rounded bg-(--ui-surface-2) p-2 text-[0.6875rem] leading-relaxed',
                children: log.join('\n')
              })
            : null
        ]
      })
    ]
  })
}

export default {
  id: ID,
  name: 'Agent Kit',
  register(ctx) {
    // **ペインではなくフルページにする。** 鍵が7本・役が8つ並ぶので、
    // 細い枠に押し込むと縦に長くなって読めない。サイドバーの行から開く。
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/agent-kit' },
        render: () => jsx(KitPane, { ctx })
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: '/agent-kit', label: 'Agent Kit', codicon: 'organization' }
      },
      {
        id: 'palette',
        area: PALETTE_AREA,
        data: {
          id: `${ID}.open`,
          title: 'Agent Kit を開く',
          run: () => host.navigate('/agent-kit')
        }
      }
    ])
  }
}
