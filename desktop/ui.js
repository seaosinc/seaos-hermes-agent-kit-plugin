/**
 * SEAOS — 設定画面の中身。
 *
 * **ここは `import` を一切書かない。** 実行時に取り込んで差し替えるため、
 * 素の関数として渡してもらう（`deps`）。ホストの解決に乗らないので、
 * 書ける依存は渡されたものだけである。
 *
 * なぜ分けてあるか: Hermes はプラグインの JS を起動時に一度だけ読み込み、
 * ⌘K の Reload desktop plugins は既知のファイルを素通りする。**編集を反映する
 * 手が無い。** そこで薄い皮（plugin.js）だけを常駐させ、中身はこのファイルを
 * その場で取り直して読み込む——アプリを終了せずに画面を作り直せる。
 */

export default function create(deps) {
  const { jsx, jsxs, useCallback, useEffect, useRef, useState, host, reloadUi } = deps

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
          `バックエンドに接続できません（${detail}）。` +
            'スキルとツール → プラグインで Python 側を有効にしてください。'
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
  function SecretRow({ secret, onEdit, onClear }) {
    // **必須は名前の脇に `*`。** 無いとキット自体が成り立たないものだけに付く。
    // 任意の鍵は、空でも動く代わりに何が使えなくなるかを書く。
    const missing = !secret.configured
    // **上書きの鍵は、空が正常。** 共通の値を使うだけなので、未設定を咎めない。
    const note = secret.override
      ? secret.configured
        ? 'この役だけ、共通とは別の値を使っています'
        : '未設定なら共通の値を使います'
      : secret.configured
      ? ''
      : secret.disables?.length
        ? `未設定の間は ${secret.disables.join('、')} を無効にします`
        : secret.description || ''

    return jsxs('div', {
      className: 'flex items-start gap-3 py-2',
      style: { borderBottom: BORDER },
      children: [
        jsxs('div', {
          className: 'min-w-0 flex-1',
          children: [
            jsxs('div', {
              className: 'text-sm',
              children: [
                secret.label || secret.name,
                secret.required
                  ? jsx('span', { style: { color: DANGER }, className: 'ml-1', children: '*' })
                  : null
              ]
            }),
            note ? jsx('div', { className: 'text-xs opacity-60', children: note }) : null
          ]
        }),
        jsx('span', {
          className: 'shrink-0 text-xs ' + (secret.configured || !secret.required ? MUTED : ''),
          style: secret.configured || !secret.required ? null : { color: DANGER },
          children: secret.override
            ? secret.configured
              ? '個別に設定'
              : '共通を使用'
            : secret.configured
              ? '設定済み'
              : secret.required
                ? '必須・未設定'
                : '未設定'
        }),
        secret.override && secret.configured && onClear
          ? jsx('button', {
              type: 'button',
              onClick: () => onClear(secret),
              className: 'shrink-0 text-xs hover:underline',
              style: { color: ACCENT },
              children: '共通に戻す'
            })
          : null,
        jsx('button', {
          type: 'button',
          onClick: () => onEdit(secret),
          className: 'shrink-0 text-xs hover:underline',
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
          jsx('div', { className: 'text-sm font-medium', children: secret.label || secret.name }),
          jsx('div', {
            className: 'mt-1 text-xs opacity-60',
            children: secret.description || ''
          }),
          jsx('input', {
            ref: inputRef,
            type: 'password',
            autoComplete: 'off',
            spellCheck: false,
            placeholder: '値を貼り付けてください',
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
            children: '保存後は表示されません。変更する場合は入力し直してください。'
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


  /** 削除する前に、何が起きるかを見せる。
   *
   * **記憶とセッションは戻せない。** 既定は残す側にして、消すほうを明示させる。
   */
  function RemoveDialog({
    role,
    impact,
    onRemove,
    onClose,
    title = `${role} を削除する`,
    lead = 'エージェントの定義を削除します。ボードの過去のカードは残ります。',
    actionLabel = '削除',
    workingLabel = '削除しています…'
  }) {
    const [alsoProfile, setAlsoProfile] = useState(false)
    const [working, setWorking] = useState(false)
    const blocked = (impact?.busy || 0) > 0

    return jsx('div', {
      className: 'fixed inset-0 z-50 flex items-center justify-center bg-black/40',
      onClick: onClose,
      children: jsxs('div', {
        className: 'w-[30rem] max-w-[90vw] rounded-lg p-5 shadow-xl',
        style: { border: BORDER, background: SURFACE },
        onClick: (e) => e.stopPropagation(),
        children: [
          jsx('div', { className: 'text-sm font-medium', children: title }),
          blocked
            ? jsx('div', {
                className: 'mt-3 rounded px-3 py-2 text-xs',
                style: { border: `1px solid ${WARN}`, color: WARN },
                children: `進行中のカードが ${impact.busy} 件あります。先に片付けてください。`
              })
            : jsx('div', {
                className: 'mt-2 text-xs opacity-70',
                children: lead
              }),
          !blocked && impact?.installed
            ? jsxs('label', {
                className: 'mt-4 flex items-start gap-2 text-xs',
                children: [
                  jsx('input', {
                    type: 'checkbox',
                    checked: alsoProfile,
                    onChange: (e) => setAlsoProfile(e.target.checked),
                    className: 'mt-0.5'
                  }),
                  jsxs('span', {
                    children: [
                      jsx('span', { style: { color: DANGER }, children: '記憶とセッションも削除する' }),
                      jsx('span', {
                        className: 'block opacity-70',
                        children: `記憶 ${impact.memories} 件、セッション ${impact.sessions} 件。元に戻せません。`
                      })
                    ]
                  })
                ]
              })
            : null,
          jsxs('div', {
            className: 'mt-5 flex justify-end gap-2',
            children: [
              jsx(Button, { label: 'キャンセル', onClick: onClose, disabled: working }),
              jsx(Button, {
                label: working ? workingLabel : actionLabel,
                disabled: working || blocked,
                onClick: async () => {
                  setWorking(true)
                  try {
                    await onRemove(role, !alsoProfile)
                  } finally {
                    setWorking(false)
                  }
                }
              })
            ]
          })
        ]
      })
    })
  }


  /** その役だけの鍵。**共通の一覧に混ぜない。**
   *
   * 窓口ごとに Slack のトークンが要るので、混ぜると役の数だけ行が増えて読めなくなる。
   * ダイアログが役に属するので、中では変数名だけでよい（役名が文脈になる）。
   */
  function OwnSecretsDialog({ role, secrets, overrides = [], onEdit, onClear, onClose }) {
    return jsx('div', {
      className: 'fixed inset-0 z-40 flex items-center justify-center bg-black/40',
      onClick: onClose,
      children: jsxs('div', {
        className: 'w-[32rem] max-w-[90vw] rounded-lg p-5 shadow-xl',
        style: { border: BORDER, background: SURFACE },
        onClick: (e) => e.stopPropagation(),
        children: [
          jsx('div', { className: 'text-sm font-medium', children: `${role} の接続情報` }),
          secrets.length
            ? jsx('div', {
                className: 'mt-1 text-xs opacity-60',
                children: 'この窓口だけが使います。他の窓口とは共有されません。'
              })
            : null,
          secrets.length
            ? jsx('div', {
                className: 'mt-3',
                children: secrets.map((x) => jsx(SecretRow, { secret: x, onEdit }, x.name))
              })
            : null,
          // **共通の値を、この役だけ差し替える。** 請求や上限を役ごとに分けたいときに使う。
          overrides.length
            ? jsx('div', {
                className: 'mt-4 text-xs opacity-60',
                children: '共通の接続情報を、この役だけ別の値にできます。'
              })
            : null,
          overrides.length
            ? jsx('div', {
                className: 'mt-1',
                children: overrides.map((x) => jsx(SecretRow, { secret: x, onEdit, onClear }, x.name))
              })
            : null,
          jsx('div', {
            className: 'mt-4 flex justify-end',
            children: jsx(Button, { label: '閉じる', onClick: onClose })
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
    const [removing, setRemoving] = useState(null)
    const [disabling, setDisabling] = useState(null)
    const [ownOf, setOwnOf] = useState(null)
    const [check, setCheck] = useState({ ok: true, blocking: [], warnings: [] })
    const [version, setVersion] = useState(null)
    const [machine, setMachine] = useState(null)

    const load = useCallback(async () => {
      setError('')
      try {
        // **並べて投げる。** 1つずつ待つと、遅いものの合計だけ画面が固まる
        const [r, s, c, v] = await Promise.all([
          call(ctx, '/roles'),
          call(ctx, '/secrets'),
          call(ctx, '/validate'),
          call(ctx, '/version')
        ])
        setRoles(r)
        setSecrets(s)
        setCheck(c)
        setVersion(v)
        // 道具の確認は Docker に問い合わせるぶん遅いので、画面の表示を待たせない
        call(ctx, '/machine').then(setMachine).catch(() => setMachine(null))
      } catch (e) {
        setError(e.message)
      }
    }, [ctx])

    useEffect(() => {
      load()
    }, [load])

    // 役ごとの上書きを外す（空で送ると、サーバが行を落として共通へ戻す）
    const clearSecret = useCallback(
      async (secret) => {
        setError('')
        try {
          await call(ctx, '/secrets', { method: 'POST', body: { name: secret.name, value: '' } })
          await load()
        } catch (e) {
          setError(e.message)
        }
      },
      [ctx, load]
    )

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
        setNotice(res.ok ? '反映しました' : '一部に失敗しました。実行結果をご確認ください。')
        await load()
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    }, [ctx, load])

    // 削除する前に、何が起きるかを取りに行く（進行中のカード、記憶とセッションの数）
    const askRemove = useCallback(
      async (name) => {
        setError('')
        try {
          setRemoving({ name, impact: await call(ctx, `/roles/${name}/removal`) })
        } catch (e) {
          setError(e.message)
        }
      },
      [ctx]
    )

    const doRemove = useCallback(
      async (name, keepProfile) => {
        setError('')
        try {
          await call(ctx, '/roles/remove', { method: 'POST', body: { name, keepProfile } })
          setRemoving(null)
          setNotice(
            keepProfile
              ? `${name} を削除しました（記憶とセッションは残しています）`
              : `${name} を削除しました`
          )
          await load()
        } catch (e) {
          setError(e.message)
        }
      },
      [ctx, load]
    )

    // **有効にするのは記録だけ。** 導入は「エージェントを反映」で行うので、そう言う。
    // 無効にするとき、プロファイルが既にあれば、残すか消すかを先に聞く
    // （記憶とセッションは戻せない）。まだ入っていなければ、聞くことが無い。
    const toggleRole = useCallback(
      async (role, enabled) => {
        setError('')
        setNotice('')
        try {
          if (!enabled && role.installed) {
            setDisabling({ name: role.name, impact: await call(ctx, `/roles/${role.name}/removal`) })
            return
          }
          // **押した瞬間に見た目を変える。** 応答を待ってから変えると、押せたのか分からない
          setRoles((rs) => rs.map((x) => (x.name === role.name ? { ...x, enabled } : x)))
          await call(ctx, '/roles/enabled', { method: 'POST', body: { name: role.name, enabled } })
          setNotice(
            enabled
              ? `${role.name} を有効にしました。「エージェントを反映」で導入されます。`
              : `${role.name} を無効にしました`
          )
          await load()
        } catch (e) {
          setError(e.message)
          // 先に変えた見た目を、実際の状態へ戻す
          load()
        }
      },
      [ctx, load]
    )

    const doDisable = useCallback(
      async (name, keepProfile) => {
        setError('')
        try {
          const res = await call(ctx, '/roles/enabled', {
            method: 'POST',
            body: { name, enabled: false, removeProfile: !keepProfile },
            timeoutMs: 60000
          })
          setDisabling(null)
          if (res.ok) {
            setNotice(
              keepProfile
                ? `${name} を無効にしました（プロファイルは残し、担当に選ばれないようにしています）`
                : `${name} を無効にし、プロファイルを削除しました`
            )
          } else {
            setError((res.lines || []).filter((l) => l.startsWith('✗')).join(' ') || '一部に失敗しました')
          }
          await load()
        } catch (e) {
          setError(e.message)
        }
      },
      [ctx, load]
    )

    // **キットへ取り込む PR を出す。** この環境で作った役は git に入らないので、
  // 共有しないと機械が飛べば消える。取り込まれたらこの環境のコピーは消すこと
  // ——残すと配布物より優先され続け、以後の更新が効かない。
  const shareRole = useCallback(
    async (name) => {
      setBusy(true)
      setError('')
      setNotice('')
      try {
        const res = await call(ctx, '/share', { method: 'POST', body: { name }, timeoutMs: 120000 })
        setNotice(
          res.url
            ? `${name} の取り込みを依頼しました（${res.url}）`
            : `${name} の取り込みを依頼しました`
        )
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [ctx]
  )

  const selfUpdate = useCallback(async () => {
      setBusy(true)
      setError('')
      setNotice('')
      setLog([])
      try {
        const res = await call(ctx, '/self-update', { method: 'POST', body: {}, timeoutMs: 60000 })
        if (res.version) setVersion(res.version)
        // **取り込んだら、その場で画面を作り直す。** アプリの再起動も、
        // レンダラの読み直し（ペインの構成が壊れる）も要らない。
        if (res.changed) await reloadUi()
        setNotice(res.changed ? '最新にしました' : 'すでに最新です')
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    }, [ctx])

    const enabledRoles = roles.filter((r) => r.enabled)
    const installed = enabledRoles.filter((r) => r.installed).length

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
                      : `エージェント ${installed} / ${enabledRoles.length}　接続情報 ${
                          secrets.filter((s) => s.configured).length
                        } / ${secrets.length}`
                })
              ]
            }),
            jsxs('div', {
              className: 'flex shrink-0 flex-col items-end gap-1',
              children: [
                jsxs('div', {
                  className: 'flex gap-2',
                  children: [
                    jsx(Button, { label: 'プラグインを最新化', onClick: selfUpdate, disabled: busy }),
                    jsx(Button, {
                      // **必須が欠けているあいだは押させない。** 押せてしまうと、
                      // 途中まで進んで失敗した状態が残る。
                      label: busy ? '実行中…' : 'エージェントを反映',
                      onClick: update,
                      disabled: busy || !check.ok,
                      primary: true
                    })
                  ]
                }),
                version?.revision
                  ? jsx('div', {
                      className: 'text-xs opacity-60',
                      children: `${version.revision}（${version.date}）`
                    })
                  : null
              ]
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

        // **古いコードが動いていたら、まずそれを言う。** 画面の内容が当てにならない。
      version?.stale
        ? jsxs('div', {
            className: 'flex items-center gap-3 rounded px-3 py-2 text-xs',
            style: { border: `1px solid ${WARN}`, color: WARN },
            children: [
              jsx('span', {
                className: 'flex-1',
                children: 'この画面は古い状態で動作しています。再起動すると最新になります。'
              }),
              jsx(Button, {
                label: '再起動',
                onClick: () => window.hermesDesktop?.relaunchApp?.()
              })
            ]
          })
        : null,

      check.blocking.length
          ? jsx('div', {
              className: 'rounded px-3 py-2 text-xs',
              style: { border: `1px solid ${DANGER}`, color: DANGER },
              children: `${check.blocking.join('、')} が未設定です。これが無いと動作しません。`
            })
          : null,

        ...check.warnings.map((w, i) =>
          jsx('div', {
            className: 'rounded px-3 py-2 text-xs',
            style: { border: `1px solid ${WARN}`, color: WARN },
            children: w
          }, `warn${i}`)
        ),

        // エージェント
        jsxs('section', {
          className: 'flex flex-col',
          children: [
            jsx('div', {
              className: 'pb-1 text-xs font-medium opacity-60',
              children: 'エージェント'
            }),
            jsx('div', {
              className: 'pb-1 text-xs opacity-60',
              children: 'チェックを外したエージェントは導入・更新しません。'
            }),
            ...roles.map((r) =>
              jsxs('div', {
                className: 'flex items-center gap-3 py-2',
      style: { borderBottom: BORDER },
                children: [
                  // **入れるかどうか。** 外せない役（窓口と詰まりを解く役）は触らせない。
                  jsx('input', {
                    type: 'checkbox',
                    checked: !!r.enabled,
                    disabled: busy || r.essential,
                    title: r.essential
                      ? 'チームの仕組みが前提にしているため、外せません'
                      : r.enabled
                        ? '無効にする'
                        : '有効にする',
                    onChange: (e) => toggleRole(r, e.target.checked),
                    className: 'shrink-0 disabled:opacity-40'
                  }),
                  jsxs('div', {
                    className: 'min-w-0 flex-1',
                    style: r.enabled ? null : { opacity: 0.5 },
                    children: [
                      jsxs('div', {
                        className: 'flex items-center gap-2 text-sm',
                        children: [
                          r.name,
                          // **この環境で作った役は、git に入らない。** 機械が飛べば
                          // 消えるので、見て分かるようにしておく。
                          r.origin === 'local'
                            ? jsx('span', {
                                className: 'shrink-0 rounded px-1.5 py-0.5 text-[0.625rem]',
                                style: { border: BORDER, opacity: 0.7 },
                                children: 'この環境'
                              })
                            : null
                        ]
                      }),
                      jsx('div', {
                        className: 'truncate text-xs opacity-60',
                        children: r.summary || ''
                      })
                    ]
                  }),
                  // **共有はこの環境の役だけ。** 配布物は既に入っている。
                  r.enabled && (r.ownSecrets?.length || r.overrideSecrets?.length)
                    ? jsxs('button', {
                        type: 'button',
                        onClick: () => setOwnOf(r),
                        className: 'shrink-0 text-xs hover:underline',
                        style: { color: ACCENT },
                        children: [
                          '設定',
                          (r.ownSecrets || []).every((x) => x.configured)
                            ? null
                            : jsx('span', { style: { color: WARN }, className: 'ml-1', children: '●' })
                        ]
                      })
                    : null,
                  r.origin === 'local'
                    ? jsx('button', {
                        type: 'button',
                        disabled: busy,
                        onClick: () => shareRole(r.name),
                        className: 'shrink-0 text-xs hover:underline disabled:opacity-40',
                        style: { color: ACCENT },
                        children: '共有'
                      })
                    : null,
                  r.origin === 'local'
                    ? jsx('button', {
                        type: 'button',
                        disabled: busy,
                        onClick: () => askRemove(r.name),
                        className: 'shrink-0 text-xs hover:underline disabled:opacity-40',
                        style: { color: DANGER },
                        children: '削除'
                      })
                    : null,
                  jsx('span', {
                    className: 'shrink-0 text-xs ' + (r.installed || !r.enabled ? MUTED : ''),
                    style: r.installed || !r.enabled ? null : { color: WARN },
                    children: !r.enabled
                      ? r.installed
                        ? '無効（プロファイルは残置）'
                        : '無効'
                      : r.installed
                        ? '導入済み'
                        : '未導入'
                  })
                ]
              }, r.name)
            )
          ]
        }),

        // この PC の道具。**揃えるのは provisioner** なので、ここは見せるだけにする。
        // provisioner を外しているときだけ、人が入れるためのコマンドを出す。
        machine?.tools?.some((t) => t.neededBy.length || t.installed)
          ? jsxs('section', {
              className: 'flex flex-col',
              children: [
                jsx('div', { className: 'pb-1 text-xs font-medium opacity-60', children: 'ツール' }),
                ...machine.tools
                  .filter((t) => t.neededBy.length || t.installed)
                  .map((t) =>
                    jsxs(
                      'div',
                      {
                        className: 'flex items-start gap-3 py-2',
                        style: { borderBottom: BORDER },
                        children: [
                          jsxs('div', {
                            className: 'min-w-0 flex-1',
                            children: [
                              jsx('div', { className: 'text-sm', children: t.label }),
                              jsx('div', {
                                className: 'text-xs opacity-60',
                                children: t.neededBy.length ? `${t.neededBy.join('、')} が使います` : t.why
                              }),
                              t.missing && !machine.provisioner && t.installCommand
                                ? jsx('div', {
                                    className: 'mt-1 font-mono text-[0.6875rem] opacity-80',
                                    children: t.installCommand
                                  })
                                : null
                            ]
                          }),
                          jsx('span', {
                            className: 'shrink-0 text-xs ' + (t.missing ? '' : MUTED),
                            style: t.missing ? { color: WARN } : null,
                            children: !t.missing
                              ? t.installed
                                ? '導入済み'
                                : '今は不要'
                              : machine.provisioner
                                ? t.installed
                                  ? '停止中（provisioner が起こします）'
                                  : '未導入（provisioner が入れます）'
                                : t.installed
                                  ? '停止中'
                                  : '未導入'
                          })
                        ]
                      },
                      t.name
                    )
                  )
              ]
            })
          : null,

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

        ownOf
          ? jsx(OwnSecretsDialog, {
              role: ownOf.name,
              secrets: (roles.find((x) => x.name === ownOf.name) || ownOf).ownSecrets || [],
              overrides: (roles.find((x) => x.name === ownOf.name) || ownOf).overrideSecrets || [],
              onEdit: setEditing,
              onClear: clearSecret,
              onClose: () => setOwnOf(null)
            })
          : null,

        disabling
          ? jsx(RemoveDialog, {
              role: disabling.name,
              impact: disabling.impact,
              onRemove: doDisable,
              onClose: () => setDisabling(null),
              title: `${disabling.name} を無効にする`,
              lead:
                '以後の反映・接続情報の配布・検証から外します。プロファイルを残す場合は、カードの担当に選ばれないよう説明文を書き換えます。',
              actionLabel: '無効にする',
              workingLabel: '無効にしています…'
            })
          : null,

        removing
          ? jsx(RemoveDialog, {
              role: removing.name,
              impact: removing.impact,
              onRemove: doRemove,
              onClose: () => setRemoving(null)
            })
          : null,

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

  return SettingsPage
}
