#!/usr/bin/env python3
"""booking-guest — Slack で会話できるゲストを足す／外す。

``seaos-kit guest`` の実体。引数だけで完結するので、operator 自身が terminal から
実行できる（オーナーが Slack で「この人を16時まで」と言えば operator がこれを打つ）。

アクセス許可は ``grants.json`` に書き、書いた直後に booking-sync を1回走らせて
アクセス許可表と pairing 承認へ即座に反映する。次のポーラー起動（最大1分）を待たない。

カレンダー由来の許可と対等な材料として扱われる（VISION.md）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import booking_sync as bs  # noqa: E402


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


# ------------------------------------------------------------------ 時刻の解釈


DURATION = re.compile(r"^\+?(\d+)\s*(m|min|分|h|時間|d|日)$", re.IGNORECASE)


def parse_duration(text: str) -> timedelta | None:
    m = DURATION.match(text.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit in ("m", "min", "分"):
        return timedelta(minutes=n)
    if unit in ("h", "時間"):
        return timedelta(hours=n)
    return timedelta(days=n)


def parse_when(text: str, base: datetime) -> datetime:
    """``16:00`` / ``2026-09-02T16:00`` / ``+90m`` を解釈する。

    ``16:00`` のように時刻だけ渡されて、それが既に過ぎている場合は翌日とみなす。
    「いま15時で『14時まで』」は言い間違いなので、遡って無効なアクセス許可にはしない。
    """
    text = text.strip()
    d = parse_duration(text)
    if d is not None:
        return base + d
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        cand = base.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                            second=0, microsecond=0)
        return cand if cand > base else cand + timedelta(days=1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"✗ 時刻を解釈できない: {text}（16:00 / +90m / 2026-09-02T16:00）")
    return dt if dt.tzinfo else dt.astimezone()


# ------------------------------------------------------------------ 保存


def load() -> dict:
    try:
        path = bs.GUESTS_PATH if bs.GUESTS_PATH.exists() else bs._LEGACY_GUESTS_PATH
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("grants"), list):
            return data
    except FileNotFoundError:
        pass
    except Exception as e:
        raise SystemExit(f"✗ grants.json が壊れている: {e}")
    return {"grants": []}


def save(data: dict) -> None:
    bs.write_atomic(bs.GUESTS_PATH, json.dumps(data, indent=2, ensure_ascii=False))


def apply_now() -> None:
    """アクセス許可表と pairing 承認へ即座に反映する。"""
    bs.main()


def _token(cfg: dict) -> str:
    return bs.read_env_file(bs.profile_home(cfg["profile"]) / ".env").get("SLACK_BOT_TOKEN", "")


def resolve_target(target: str, cfg: dict) -> tuple[str, str]:
    """相手の指定を Slack ユーザー ID に直す。(user_id, email) を返す。

    受けつけるのは3通り。**メンションは表示名で届く**ので、名前でも引けることが重要。

      U01ABCDEF          Slack ユーザー ID（そのまま）
      tanaka@example.com メールアドレス（users:read.email が要る）
      @田中 / 田中        表示名・本名・ハンドル（users.list から引く）
    """
    raw = target.strip()
    name = raw.lstrip("@").strip()
    # 「@田中さん」のように敬称が付いたまま渡されることがある。落として引く
    name = re.sub(r"(さん|サン|くん|クン|ちゃん|さま|様|氏|先生)$", "", name).strip()
    if not name:
        raise SystemExit("✗ 相手が指定されていない")

    # Slack ID は U/W で始まる英数字。表示名と衝突しないので先に判定する
    if re.fullmatch(r"[UW][A-Z0-9]{6,}", name.upper()):
        return (name.upper(), "")

    token = _token(cfg)
    if not token:
        raise SystemExit("✗ SLACK_BOT_TOKEN が無いので名前から引けない。Slack ユーザー ID を渡すこと")

    if "@" in name and "." in name.split("@")[-1]:
        uid = bs.slack_lookup(token, name)
        if not uid:
            raise SystemExit(
                f"✗ {name} の Slack ユーザーを引けなかった"
                "（users:read.email が要る。ID か表示名を渡してもよい）"
            )
        return (uid, name)

    cache = bs.load_identity_cache()
    names = bs.slack_directory(token, cache)
    bs.write_atomic(bs.IDENTITY_CACHE_PATH, json.dumps(cache, indent=2, ensure_ascii=False))
    key = name.lower()
    if key in names:
        return (names[key], "")
    # 部分一致は候補を出して止まる。人違いで許可を出すより聞き返すほうがよい
    hits = sorted({v: k for k, v in names.items() if key in k}.items())
    if len(hits) == 1:
        return (hits[0][0], "")
    if hits:
        cand = ", ".join(f"{n}({u})" for u, n in hits[:8])
        raise SystemExit(f"✗ 「{name}」は候補が複数ある: {cand}")
    raise SystemExit(f"✗ 「{name}」に一致する Slack ユーザーが見つからない（ID を直接渡してもよい）")


def _looks_like_channel_id(text: str) -> bool:
    """チャンネル ID（C… / G…）か。**大文字に直してから見ない。**

    「christina」を大文字にすると C で始まる英字の並びになり、ID と区別できない。
    Slack の ID は大文字と数字だけで、数字を含む。
    """
    return bool(re.fullmatch(r"[CG][A-Z0-9]{8,}", text)) and any(c.isdigit() for c in text)


def is_channel_target(target: str) -> bool:
    """相手の指定がチャンネルか。``#名前`` / ``<#C…|名前>`` / ``C…``。"""
    raw = target.strip()
    return raw.startswith("#") or raw.startswith("<#") or _looks_like_channel_id(raw)


def resolve_channel(target: str, cfg: dict) -> tuple[str, str]:
    """チャンネルの指定を (チャンネル ID, 名前) に直す。

    名前から引くのは ``conversations.list``。**非公開チャンネルは App が招待されて
    いないと見えない**——見えないチャンネルのメンバーは取れないので、ここで止める。
    """
    raw = target.strip()
    m = re.match(r"^<#([CG][A-Z0-9]+)(?:\|([^>]*))?>$", raw)
    if m:
        return (m.group(1), m.group(2) or "")
    if _looks_like_channel_id(raw):
        return (raw, "")
    name = raw.lstrip("#").strip().lower()
    if not name:
        raise SystemExit("✗ チャンネルが指定されていない")
    token = _token(cfg)
    if not token:
        raise SystemExit("✗ SLACK_BOT_TOKEN が無いので名前から引けない。チャンネル ID（C…）を渡すこと")
    cursor = ""
    for _ in range(50):
        params = {"types": "public_channel,private_channel", "exclude_archived": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        url = "https://slack.com/api/conversations.list?" + bs.urllib.parse.urlencode(params)
        req = bs.urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with bs.urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise SystemExit(f"✗ チャンネル一覧を取れない: {e}")
        if not data.get("ok"):
            raise SystemExit(f"✗ チャンネル一覧を取れない: {data.get('error')}")
        for ch in data.get("channels") or []:
            if str(ch.get("name", "")).lower() == name:
                return (ch["id"], ch.get("name", name))
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    raise SystemExit(
        f"✗ #{name} が見つからない（非公開チャンネルなら、先に App を招待する。チャンネル ID を直接渡してもよい）"
    )


def grant_key(g: dict) -> str:
    """アクセス許可を指す鍵。人なら U…、チャンネルなら C…。"""
    return str(g.get("slack_channel_id") or g.get("slack_user_id") or "")


def channel_member_count(channel_id: str) -> int | None:
    """いまの許可表に、そのチャンネルのメンバーが何人入っているか。"""
    try:
        table = json.loads(bs.RESERVATIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return len({s["slack_user_id"] for s in table.get("slots") or []
                if s.get("channel_id") == channel_id})


# ------------------------------------------------------------------ 表示


def is_live(g: dict, now: datetime) -> bool:
    """まだ効いているアクセス許可か。**カード紐付けはボードの状態で決まる。**"""
    end = g.get("end")
    if end and datetime.fromisoformat(end) < now:
        return False
    task_id = (g.get("task_id") or "").strip()
    if task_id and (bs.task_status(task_id) not in bs.OPEN_STATUSES):
        return False
    return True


def find_grant(data: dict, uid: str, now: datetime) -> dict | None:
    for g in data["grants"]:
        if grant_key(g) != uid or not is_live(g, now):
            continue
        if datetime.fromisoformat(g["start"]) > now:
            continue
        return g
    return None


def describe(g: dict, now: datetime) -> str:
    end = g.get("end")
    task_id = (g.get("task_id") or "").strip()
    if task_id and not end:
        st = bs.task_status(task_id) or "見つからない"
        span = f"{task_id} が終わるまで（いま {st}）"
    elif not end:
        span = "無期限"
    else:
        dt = datetime.fromisoformat(end)
        left = dt - now
        if left.total_seconds() < 0:
            span = f"期限切れ（{dt.strftime('%m/%d %H:%M')}）"
        else:
            mins = int(left.total_seconds() // 60)
            span = f"{dt.strftime('%m/%d %H:%M')} まで（あと{mins//60}時間{mins%60}分）"
    label = g.get("label") or g.get("email") or ""
    channel_id = g.get("slack_channel_id")
    if channel_id:
        count = channel_member_count(channel_id)
        who = f"#{g.get('channel_name') or channel_id} のメンバー"
        who += f"（{count}人・このチャンネルの中だけ）" if count is not None else "（このチャンネルの中だけ）"
        label = f"{who} {label}".strip()
    return f"{grant_key(g):<12} {span:<34} {label}"


# ------------------------------------------------------------------ サブコマンド


def cmd_add(args) -> int:
    cfg = bs.load_config()
    now = now_local()
    channel_id = channel_name = ""
    if is_channel_target(args.target):
        channel_id, channel_name = resolve_channel(args.target, cfg)
        uid, email = "", ""
    else:
        uid, email = resolve_target(args.target, cfg)

    task_id = (args.task or "").strip()
    if task_id:
        st = bs.task_status(task_id)
        if st is None:
            raise SystemExit(f"✗ カード {task_id} が見つからない")
        if st not in bs.OPEN_STATUSES:
            raise SystemExit(f"✗ カード {task_id} は {st}。畳まれたカードには紐づけられない")

    start = parse_when(args.start, now) if args.start else now
    if args.unlimited:
        # **無期限は、指示した人の名前が無いと出せない。** 終わり方の無い許可は
        # 外すまでオーナーと同じ強さで残る（会話が閉じても許可は生きている）。
        # 誰の判断かを残せないなら、それは出してよい許可ではない。
        if not (args.by or "").strip():
            raise SystemExit(
                "✗ --unlimited には --by が要る（誰の指示かを残す）\n"
                "  この件のためだけなら --task <カード> を使う。"
                "カードが終われば許可も切れる"
            )
        end = None
    elif args.until:
        end = parse_when(args.until, start)
    elif args.duration:
        d = parse_duration(args.duration)
        if d is None:
            raise SystemExit(f"✗ 長さを解釈できない: {args.duration}（90m / 2h / 1d）")
        end = start + d
    elif task_id:
        end = None  # カードが終わるまで。時計ではなくボードが期限になる
    else:
        end = start + timedelta(hours=1)  # 既定は1時間。無期限を既定にはしない

    data = load()
    key = channel_id or uid
    # 同じ人（同じチャンネル）のアクセス許可は1件にまとめる（重ねると期限も範囲も読めなくなる）
    data["grants"] = [g for g in data["grants"] if grant_key(g) != key]
    grant = {
        **({"slack_channel_id": channel_id, "channel_name": channel_name}
           if channel_id else {"slack_user_id": uid}),
        "email": email,
        "label": args.label or "",
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "task_id": task_id,
        # 無期限が「そう指示された」のか「終わり方を付け忘れた」のかを、
        # あとから区別できるようにする（doctor の文面が変わる）。
        "unlimited": bool(args.unlimited),
        "requested_by": (args.by or "").strip(),
        "note": args.note or "",
        "created_at": now.isoformat(),
    }
    data["grants"].append(grant)
    save(data)
    bs.audit("guest_add", slack_user_id=uid or None, slack_channel_id=channel_id or None,
             label=grant["label"] or None,
             until=grant["end"], task_id=task_id or None,
             requested_by=args.by or None)
    apply_now()

    if args.json:
        print(json.dumps(grant, ensure_ascii=False))
    else:
        print("✓ アクセス許可を出した")
        print("  " + describe(grant, now))
        if channel_id:
            print("  このチャンネルのメンバーが、このチャンネルの中でだけ話せる（メンバーは8時間ごとに取り直す）")
        if end is None and not task_id:
            print("  ! 無期限。外すときは seaos-kit guest rm " + key)
    return 0


def cmd_list(args) -> int:
    cfg = bs.load_config()
    now = now_local()
    data = load()
    live = [g for g in data["grants"] if is_live(g, now)]
    expired = [g for g in data["grants"] if g not in live]

    if args.json:
        print(json.dumps({"live": live, "expired": expired}, ensure_ascii=False, indent=2))
        return 0
    if not live:
        print("  アクセス許可なし（オーナーだけが話せる）")
    for g in sorted(live, key=lambda x: x.get("end") or "9999"):
        print("  " + describe(g, now))
    if expired:
        print(f"\n  （期限切れ {len(expired)} 件。次の seaos-kit guest prune で消える）")
    return 0


def cmd_rm(args) -> int:
    cfg = bs.load_config()
    data = load()
    if is_channel_target(args.target):
        uid, _name = resolve_channel(args.target, cfg)
        fields = {"slack_channel_id": uid}
    else:
        uid, _ = resolve_target(args.target, cfg)
        fields = {"slack_user_id": uid}
    before = len(data["grants"])
    data["grants"] = [g for g in data["grants"] if grant_key(g) != uid]
    removed = before - len(data["grants"])
    save(data)
    if removed:
        bs.audit("guest_rm", **fields, requested_by=args.by or None,
                 reason=args.reason or None)
    apply_now()
    print(f"✓ {uid} のアクセス許可を {removed} 件外した" if removed else f"= {uid} のアクセス許可は無かった")
    return 0


def cmd_prune(args) -> int:
    now = now_local()
    data = load()
    before = len(data["grants"])
    dropped = [g for g in data["grants"] if not is_live(g, now)]
    data["grants"] = [g for g in data["grants"] if is_live(g, now)]
    save(data)
    for g in dropped:
        bs.audit("guest_prune", slack_user_id=g.get("slack_user_id"),
                 slack_channel_id=g.get("slack_channel_id"), label=g.get("label") or None)
    apply_now()
    print(f"✓ 終わったアクセス許可を {len(dropped)} 件消した")
    return 0


def owner_mention(cfg: dict) -> str | None:
    """オーナーのメンション形。

    出どころは `.env` の ``SLACK_OWNER_ID``（プロファイル配下）。秘密ではないが、
    Slack まわりの識別子は .env に集まっているので同じ場所で管理する。
    未設定なら always_allow の先頭で代用する（自分の ID が入っているはず）。
    """
    env = bs.read_env_file(bs.profile_home(cfg["profile"]) / ".env")
    uid = (os.environ.get("SLACK_OWNER_ID") or env.get("SLACK_OWNER_ID") or "").strip()
    if not uid:
        allow = cfg.get("always_allow") or []
        uid = str(allow[0]).strip() if allow else ""
    return f"<@{uid}>" if uid else None


def cmd_escalate(args) -> int:
    """判断をオーナーへ上げる。**閉じない。記録して、聞き方を返すだけ。**

    コンプライアンス違反やハッキング、カードと無関係な依頼——これらは
    operator が独断で切らず、オーナーに聞く。切るかどうかはオーナーが決める。
    """
    cfg = bs.load_config()
    uid, _ = resolve_target(args.target, cfg)
    bs.audit("escalated", slack_user_id=uid, reason=args.reason,
             kind=args.kind or None)
    mention = owner_mention(cfg)
    if args.json:
        print(json.dumps({"slack_user_id": uid, "owner_mention": mention,
                          "reason": args.reason}, ensure_ascii=False))
        return 0
    print("✓ 記録した（許可はそのまま。閉じていない）")
    if mention:
        print(f"\n  {mention} {uid} から次の依頼がありました。許可を続けますか。")
        print(f"  理由: {args.reason}")
        print(f"\n  外す場合: seaos-kit guest rm {uid} --by \"<オーナー名>\" --reason \"...\"")
    else:
        print("  ! オーナーの Slack ID が設定に無い（owner_slack_id / always_allow）")
    return 0


def cmd_log(args) -> int:
    """監査ログを読む。**grants.json から消えた過去も、ここには残っている。**"""
    try:
        lines = bs.AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print("  記録なし")
        return 0
    rows = []
    for line in lines[-max(1, args.n) * 4:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if args.user:
        cfg = bs.load_config()
        uid, _ = resolve_target(args.user, cfg)
        rows = [r for r in rows if r.get("slack_user_id") == uid]
    rows = rows[-args.n:]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("  記録なし")
    for r in rows:
        when = r["at"][5:16].replace("T", " ")
        extra = []
        if r.get("label"):
            extra.append(r["label"])
        if r.get("task_id"):
            extra.append(r["task_id"])
        if r.get("until"):
            extra.append(f"→{r['until'][5:16].replace('T', ' ')}")
        if r.get("requested_by"):
            extra.append(f"（{r['requested_by']} の指示）")
        if r.get("kind"):
            extra.append(f"[{r['kind']}]")
        if r.get("reason"):
            extra.append(f"理由: {r['reason']}")
        who = r.get("slack_user_id") or r.get("slack_channel_id") or ""
        print(f"  {when}  {r['event']:<13} {who:<12}"
              f" {r.get('actor', ''):<9} {' '.join(extra)}")
    return 0


def cmd_who(args) -> int:
    """表示名から Slack ユーザー ID と、返信に貼れるメンション形を出す。

    Slack のメンションは、エージェントに届く時点で ``@表示名`` になっていて ID が無い。
    一方、**本物のメンション（通知が飛ぶ形）を書くには `<@U…>` が要る。**
    複数人がいるスレッドで「誰に言っているか」を明示するために使う。
    """
    cfg = bs.load_config()
    uid, email = resolve_target(args.target, cfg)
    if args.json:
        print(json.dumps({"slack_user_id": uid, "email": email, "mention": f"<@{uid}>"},
                         ensure_ascii=False))
    else:
        print(f"{uid}")
        print(f"  返信に貼るメンション: <@{uid}>")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="seaos-kit guest", description="Slack で会話できるゲストのアクセス許可")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="アクセス許可を出す")
    a.add_argument("target", help="相手（@表示名 / U… / メールアドレス）か、チャンネル（#名前 / C…）。"
                                  "チャンネルなら、そのメンバーがそのチャンネルの中でだけ話せる")
    a.add_argument("--until", help="いつまで（16:00 / 2026-09-02T16:00）")
    a.add_argument("--for", dest="duration", help="どれだけ（90m / 2h / 1d）")
    a.add_argument("--from", dest="start", help="いつから（既定: いま）")
    a.add_argument("--unlimited", action="store_true", help="無期限")
    a.add_argument("--task", help="このカードが終わるまで（t_xxxx）。時計ではなくボードが期限になる")
    a.add_argument("--label", help="表示名（誰なのか後で分かるように）")
    a.add_argument("--note", help="覚え書き")
    a.add_argument("--by", help="誰の指示か（監査ログに残す）")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="いま有効なアクセス許可を見る")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("rm", help="外す")
    r.add_argument("target", help="相手（@表示名 / U… / メールアドレス）か、チャンネル（#名前 / C…）")
    r.add_argument("--by", help="誰の指示か（監査ログに残す）。operator の判断なら operator と書く")
    r.add_argument("--reason", help="なぜ外したか（監査ログに残す）")
    r.set_defaults(func=cmd_rm)

    w = sub.add_parser("who", help="表示名 → Slack ID とメンション形（<@U…>）")
    w.add_argument("target", help="表示名 / メールアドレス / Slack ユーザー ID")
    w.add_argument("--json", action="store_true")
    w.set_defaults(func=cmd_who)

    e = sub.add_parser("escalate", help="判断をオーナーへ上げる（閉じない。記録と聞き方だけ）")
    e.add_argument("target", help="対象の相手")
    e.add_argument("--reason", required=True, help="何があったか（監査ログに残る）")
    e.add_argument("--kind", choices=["compliance", "security", "off-topic", "other"],
                   help="種類")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_escalate)

    lg = sub.add_parser("log", help="監査ログ（誰にいつ許可を出したか）")
    lg.add_argument("-n", type=int, default=20, help="表示する件数（既定 20）")
    lg.add_argument("--user", help="この人の分だけ")
    lg.add_argument("--json", action="store_true")
    lg.set_defaults(func=cmd_log)

    pr = sub.add_parser("prune", help="期限切れのアクセス許可を消す")
    pr.set_defaults(func=cmd_prune)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
