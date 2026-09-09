/**
 * SEAOS — デスクトップ側の半身。
 *
 * **素の ESM で読まれる（ビルド不要）。** JSX 構文は使えないので UI は jsx() 呼び出しで書く。
 * 解決する import は @hermes/plugin-sdk / react / react/jsx-runtime だけ。
 *
 * この画面は判断を持たない。ctx.rest 経由で dashboard/plugin_api.py を呼び、
 * その先の core/ が CLI とまったく同じ関数を実行する。
 *
 * 画面は**設定画面**である。手順を追わせるウィザードではないので番号は振らない。
 * 状態を上に置き、操作を下に置く。足りないものがあるときだけ促す。
 */

import { ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, host } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useCallback, useEffect, useRef, useState } from 'react'

const ID = 'seaos-hermes-agent-kit'

// 配色はトークンに頼らない——アクセント上の文字色が解決されず、青地に黒文字に
// なる環境があった。意味を持つ3色だけ自前で持つ。
const ACCENT = '#0B6E6E'
const WARN = '#B4761F'
const DANGER = '#B4413C'
const MUTED = 'opacity-60'
const BORDER = '1px solid var(--ui-border, rgba(127,127,127,.3))'
const SURFACE = 'var(--ui-surface, Canvas)'
const SURFACE_2 = 'var(--ui-surface-2, rgba(127,127,127,.08))'

/** バックエンドを呼ぶ。
 *
 * **body はオブジェクトで渡す。** ctx.rest が直列化まで面倒を見るので、
 * JSON 文字列を渡すと二重に包まれて 422 になる（実際に「更新」がこれで落ちた）。
 *
 * **失敗した理由をそのまま出す。** 全部を「バックエンドが無効です」に丸めると、
 * 応答しているのに接続エラーが出るという嘘をつく——これも実際に起きた。
 * その文言は、本当に繋がっていないときだけに使う。
 */
async function call(ctx, path, init) {
  try {
    return await ctx.rest(path, init)
  } catch (error) {
    const detail = error?.detail || error?.message || String(error)
    if (/404|not found|ECONNREFUSED|failed to fetch/i.test(detail)) {
      throw new Error(
        `バックエンドに繋がりません（${detail}）。設定 → プラグインで Python 側を有効にし、` +
          'それでも直らなければゲートウェイを再起動してください。'
      )
    }
    throw new Error(detail)
  }
}

/** 主ボタン。**配色はトークン任せにしない**——アクセント上の文字色が解決されず、
 *  青地に黒文字になる環境があった。 */
function Button({ label, onClick, disabled, primary }) {
  return jsx('button', {
    type: 'button',
    disabled,
    onClick,
    className: 'rounded px-3 py-1.5 text-xs transition-opacity disabled:opacity-40',
    style: primary
      ? { background: ACCENT, color: '#fff', border: `1px solid ${ACCENT}` }
      : { background: 'transparent', color: 'inherit', border: BORDER },
    children: label
  })
}

/** 接続情報の1行。
 *
 * **普段は入力欄を出さない。** 設定済みの鍵に空欄が並ぶのは、何を求められて
 * いるのか分からない。行は状態だけを見せ、変更したいときにダイアログを開く。 */
function SecretRow({ secret, onEdit }) {
  return jsxs('div', {
    className: 'flex items-center gap-3 py-2',
    style: { borderBottom: BORDER },
    children: [
      jsx('span', { className: 'flex-1 truncate text-sm', children: secret.name }),
      jsx('span', {
        className: 'text-xs ' + (secret.configured || !secret.required ? MUTED : ''),
        style: secret.configured || !secret.required ? null : { color: WARN },
        children: secret.configured ? '設定済み' : secret.required ? '未設定' : '任意・未設定'
      }),
      jsx('button', {
        type: 'button',
        onClick: () => onEdit(secret),
        className: 'text-xs hover:underline',
        style: { color: ACCENT },
        children: secret.configured ? '変更' : '設定'
      })
    ]
  })
}

/** 値を入れるダイアログ。**入力はここだけ。** */
function SecretDialog({ secret, onSave, onClose }) {
  const inputRef = useRef(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const save = async () => {
    const value = inputRef.current ? inputRef.current.value : ''
    if (!value) return
    setSaving(true)
    try {
      await onSave(secret.name, value)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return jsx('div', {
    className: 'fixed inset-0 z-50 flex items-center justify-center bg-black/40',
    onClick: onClose,
    children: jsxs('div', {
      className:
        'w-[28rem] max-w-[90vw] rounded-lg p-5 shadow-xl',
      style: { border: BORDER, background: SURFACE },
      onClick: (e) => e.stopPropagation(),
      children: [
        jsx('div', { className: 'text-sm font-medium', children: secret.name }),
        jsx('div', {
          className: 'mt-1 text-xs opacity-60',
          children: secret.description || ''
        }),
        jsx('input', {
          ref: inputRef,
          type: 'password',
          autoComplete: 'off',
          spellCheck: false,
          placeholder: '値を貼り付け',
          className:
            'mt-4 w-full rounded px-2 py-1.5 text-sm focus:outline-none',
        style: { border: BORDER, background: SURFACE_2, color: 'inherit' },
          onKeyDown: (e) => {
            if (e.key === 'Enter') save()
            if (e.key === 'Escape') onClose()
          }
        }),
        jsx('div', {
          className: 'mt-2 text-xs opacity-60',
          children: '保存後は表示できません。変更するときは入れ直してください。'
        }),
        jsxs('div', {
          className: 'mt-4 flex justify-end gap-2',
          children: [
            jsx(Button, { label: 'キャンセル', onClick: onClose, disabled: saving }),
            jsx(Button, { label: '保存', onClick: save, disabled: saving, primary: true })
          ]
        })
      ]
    })
  })
}

function SettingsPage({ ctx }) {
  const [roles, setRoles] = useState([])
  const [secrets, setSecrets] = useState([])
  const [log, setLog] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(null)

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

  const saveSecret = useCallback(
    async (name, value) => {
      await call(ctx, '/secrets', { method: 'POST', body: { name, value } })
      await load()
    },
    [ctx, load]
  )

  const update = useCallback(async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      // 8役ぶん生成して配るので、既定のタイムアウトでは足りない。
      const res = await call(ctx, '/update', {
        method: 'POST',
        body: { forceConfig: false },
        timeoutMs: 180000
      })
      setLog(res.lines || [])
      // **成否を一言で言う。** ログだけ出して黙ると、読める人しか結果が分からない。
      setNotice(res.ok ? '反映しました。' : '一部が失敗しました。下の実行結果を確認してください。')
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [ctx, load])

  const selfUpdate = useCallback(async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await call(ctx, '/self-update', { method: 'POST', body: {}, timeoutMs: 60000 })
      setLog(res.lines || [])
      setNotice(
        res.changed
          ? 'プラグインを更新しました。アプリを再起動してください。'
          : 'すでに最新です。'
      )
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [ctx])

  const missing = secrets.filter((s) => s.required && !s.configured)
  const installed = roles.filter((r) => r.installed).length

  return jsxs('div', {
    className: 'mx-auto flex h-full w-full max-w-3xl flex-col gap-6 overflow-y-auto p-6',
    children: [
      // 見出しと状態
      jsxs('div', {
        className: 'flex items-start justify-between gap-4',
        children: [
          jsxs('div', {
            children: [
              jsx('div', { className: 'text-lg font-medium', children: 'SEAOS' }),
              jsx('div', {
                className: 'mt-0.5 text-xs opacity-60',
                children:
                  roles.length === 0
                    ? '読み込み中…'
                    : `エージェント ${installed} / ${roles.length}　接続情報 ${
                        secrets.filter((s) => s.configured).length
                      } / ${secrets.length}`
              })
            ]
          }),
          jsx(Button, {
            label: busy ? '実行中…' : '反映',
            onClick: update,
            disabled: busy,
            primary: true
          })
        ]
      }),

      error
        ? jsx('div', {
            className: 'rounded px-3 py-2 text-xs',
            style: { border: `1px solid ${DANGER}`, color: DANGER },
            children: error
          })
        : null,

      notice
        ? jsx('div', {
            className: 'rounded px-3 py-2 text-xs',
            style: { border: `1px solid ${ACCENT}`, color: ACCENT },
            children: notice
          })
        : null,

      missing.length
        ? jsx('div', {
            className: 'rounded px-3 py-2 text-xs',
            style: { border: `1px solid ${WARN}`, color: WARN },
            children: `${missing.map((s) => s.name).join(', ')} が未設定です。設定してから更新してください。`
          })
        : null,

      // エージェント
      jsxs('section', {
        className: 'flex flex-col',
        children: [
          jsx('div', {
            className: 'pb-1 text-xs font-medium opacity-60',
            children: 'エージェント'
          }),
          ...roles.map((r) =>
            jsxs('div', {
              className: 'flex items-center gap-3 py-2',
    style: { borderBottom: BORDER },
              children: [
                jsxs('div', {
                  className: 'min-w-0 flex-1',
                  children: [
                    jsx('div', { className: 'text-sm', children: r.name }),
                    jsx('div', {
                      className: 'truncate text-xs opacity-60',
                      children: r.summary || ''
                    })
                  ]
                }),
                jsx('span', {
                  className: 'shrink-0 text-xs ' + (r.installed ? MUTED : ''),
                  style: r.installed ? null : { color: WARN },
                  children: r.installed ? '導入済み' : '未導入'
                })
              ]
            }, r.name)
          )
        ]
      }),

      // 接続情報
      jsxs('section', {
        className: 'flex flex-col',
        children: [
          jsx('div', {
            className: 'pb-1 text-xs font-medium opacity-60',
            children: '接続情報'
          }),
          ...secrets.map((s) => jsx(SecretRow, { secret: s, onEdit: setEditing }, s.name))
        ]
      }),

      log.length
        ? jsxs('section', {
            className: 'flex flex-col gap-1',
            children: [
              jsx('div', {
                className: 'text-xs font-medium opacity-60',
                children: '実行結果'
              }),
              jsx('pre', {
                className:
                  'max-h-56 overflow-auto rounded p-3 text-[0.6875rem] leading-relaxed whitespace-pre-wrap',
                style: { border: BORDER, background: SURFACE_2 },
                children: log.join('\n')
              })
            ]
          })
        : null,

      jsxs('section', {
        className: 'mt-auto flex items-center gap-3 pt-4',
        style: { borderTop: BORDER },
        children: [
          jsxs('div', {
            className: 'min-w-0 flex-1',
            children: [
              jsx('div', { className: 'text-sm', children: 'プラグイン' }),
              jsx('div', {
                className: 'text-xs opacity-60',
                children: '新しい版を取り込みます。取り込んだあとはアプリの再起動が要ります'
              })
            ]
          }),
          jsx(Button, { label: '更新', onClick: selfUpdate, disabled: busy })
        ]
      }),

      editing
        ? jsx(SecretDialog, {
            secret: editing,
            onSave: saveSecret,
            onClose: () => setEditing(null)
          })
        : null
    ]
  })
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
        render: () => jsx(SettingsPage, { ctx })
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
