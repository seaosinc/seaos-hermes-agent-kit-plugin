"""owner-away — オーナーが不在（Slack ステータスの絵文字が 🤖）のあいだ、
オーナー宛の話を operator が代わりに受ける。

オーナーが operator の Slack App に「本人の DM とメンションを読む」権限（ユーザースコープ）を
与えると、オーナーに見える会話のイベントも operator の接続に届くようになる。
ここでそれを選り分ける。**返事はボット（operator）の名前で出す**——本人になりすまさない。

  * ボットがいる会話 → ふだんどおり。オーナーが不在で `@オーナー` と呼ばれたら、
    ボットが呼ばれたものとして読み替える（そのスレッドで operator が返す）
  * ボットがいない会話（オーナーと誰かの DM、ボットのいないチャンネル）
      - オーナーが不在で、オーナー宛（DM、または `@オーナー`）なら、相手とボットの DM へ移す。
        人と人の DM にボットは入れないので、場所を移してから operator が返す
      - それ以外は**捨てる。** operator に見せない（オーナーの会話を読ませない）
  * オーナー自身の発言は、代わりに受ける対象にしない

**許可の無い人も、用件だけは預かる。** オーナーが不在だと、許可を出せる人がいない。
  * 社内の正規メンバーなら、オーナーが戻るまでのゲスト許可を出し（`seaos-kit guest add`）、
    operator に「用件の預かりのみ」と伝えて渡す。operator はカードにできるところまで話を聞き、
    `seaos-kit card hold` で**保留のカード**を作る（分解にも担当にも回らない）
  * 社外の人・ゲストアカウントには許可を出さない。「戻ったら伝えます」とだけ返し、用件を控える
  * オーナーが戻ったら（🤖 を外したら）、保留のカードと控えた用件をオーナーに DM で渡し、
    不在中に出したゲスト許可を外す

**捨てるときも ack は返す。** イベントの種類を誰も持たない名前に書き換え、アダプタの
「何にでも当たる受け皿」に ack させる。ack が返らない失敗が続くと、Slack は App の
イベント配信そのものを止める（Hermes の slack アダプタの説明のとおり）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AWAY_EMOJI = ":robot_face:"
# イベントを取りこぼしても、この間隔で読み直して追いつく。
REFRESH_SEC = 300
# ボットがその会話に入っているかの覚え（秒）。入退室はまれなので長めでよい。
MEMBER_TTL = 600
IGNORED = "owner_away_ignored"
# 「代わりに受けます」の案内は、同じ相手に対してこの間隔に1回まで（続けて送られても繰り返さない）。
NOTICE_INTERVAL = 1800
INTAKE = "（用件の預かりのみ）"

_state: dict = {"profile": None, "owner": None, "away": False, "checked_at": 0.0, "task": None,
                "client": None, "team": None}
_members: dict[str, tuple[bool, float]] = {}
_noticed: dict[str, float] = {}


def _hermes_root() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


# 外から状態を確かめる痕跡（doctor が読む）。
STATE_PATH = _hermes_root() / "owner-away" / "state.json"
# 不在中に預かった相手と用件。ゲートウェイが起こし直されても、戻ったときに渡せるよう残す。
VISITS_PATH = _hermes_root() / "owner-away" / "visits.json"
# 保留のカードの記録（`seaos-kit card hold` が書く。core/cards.py）。
HELD_PATH = _hermes_root() / "seaos-kit" / "held.json"


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _visits() -> dict:
    data = _read_json(VISITS_PATH, {})
    data.setdefault("away_since", None)
    data.setdefault("guests", {})
    data.setdefault("messages", [])
    return data


def _save_visits(data: dict) -> None:
    try:
        VISITS_PATH.parent.mkdir(parents=True, exist_ok=True)
        VISITS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("[owner-away] 預かりの記録を書けなかった: %s", e)


# ------------------------------------------------------------------ オーナーの状態


def is_away(profile: dict, now: float | None = None) -> bool:
    """ステータスの**絵文字だけ**で決める。文言は何でもよい。期限切れは不在ではない。"""
    if (profile or {}).get("status_emoji") != AWAY_EMOJI:
        return False
    expiration = int((profile or {}).get("status_expiration") or 0)
    return expiration == 0 or expiration > (now if now is not None else time.time())


def _apply(profile: dict, *, source: str) -> None:
    away = is_away(profile)
    was = _state["away"]
    # 起こし直した直後の最初の読み取り。不在中に預かったまま起こし直され、そのあいだに
    # オーナーが戻っていたら、「戻った」という変化は見えない。残っている預かりで気づく。
    first = _state["checked_at"] == 0.0
    if away != was:
        logger.info("[owner-away] %s（%s）", "オーナー不在：代わりに受ける" if away else "オーナー在席：受けない", source)
    _state["away"] = away
    _state["checked_at"] = time.time()
    if away and not was:
        data = _visits()
        data["away_since"] = data.get("away_since") or time.time()
        _save_visits(data)
    elif not away and (was or (first and _visits().get("away_since"))):
        _schedule(on_return())
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({
            "profile": _state["profile"], "owner": _state["owner"], "away": away,
            "checked_at": datetime.now(timezone.utc).astimezone().isoformat(), "pid": os.getpid(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.debug("[owner-away] 状態を書けなかった: %s", e)


def _schedule(coro) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        logger.warning("[owner-away] 戻ったときの処理を始められなかった（イベントループが無い）")


def _owner_id() -> str:
    """オーナー（SLACK_OWNER_ID）。multiplex では役の secret scope から読む。"""
    try:
        from agent.secret_scope import get_secret

        value = get_secret("SLACK_OWNER_ID")
        if value:
            return str(value).strip()
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get("SLACK_OWNER_ID") or "").strip()


async def _refresh(client) -> None:
    owner = _state["owner"]
    if not owner:
        return
    try:
        resp = await client.users_profile_get(user=owner)
        _apply(resp.get("profile") or {}, source="読み直し")
    except Exception as e:  # noqa: BLE001
        # 読めないときは前の状態を保つ。**不在へは倒さない。** 長く読めなければ在席に戻す。
        logger.warning("[owner-away] オーナーのステータスを読めなかった: %s", e)
        if _state["away"] and time.time() - _state["checked_at"] > REFRESH_SEC * 3:
            _state["away"] = False
            logger.warning("[owner-away] 長く読めないので、代わりに受けるのをやめた")


async def _learn_team(client) -> None:
    """自分のワークスペース（社外の人を見分けるため）。"""
    try:
        _state["team"] = (await client.auth_test()).get("team_id")
    except Exception:  # noqa: BLE001
        pass


async def _refresh_loop(client) -> None:
    while True:
        await _refresh(client)
        await asyncio.sleep(REFRESH_SEC)


# ------------------------------------------------------------------ 預かり


def _command(name: str) -> str | None:
    """`seaos-kit` の場所。ゲートウェイの PATH に無いこともあるので、置き場も見る。"""
    found = shutil.which(name)
    if found:
        return found
    for cand in (Path.home() / ".local" / "bin" / name,
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "seaos-kit" / f"{name}.cmd"):
        if cand.is_file():
            return str(cand)
    return None


async def _run(*args: str, timeout: float = 60) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode or 0, (out or b"").decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


async def _internal_member(client, user: str) -> dict | None:
    """社内の正規メンバーなら、そのユーザー情報を返す。社外の人・ゲストアカウント・ボットは None。"""
    try:
        info = (await client.users_info(user=user)).get("user") or {}
    except Exception:  # noqa: BLE001
        return None
    if (info.get("is_bot") or info.get("deleted") or info.get("is_restricted")
            or info.get("is_ultra_restricted") or info.get("is_stranger")):
        return None
    if _state["team"] and info.get("team_id") and info.get("team_id") != _state["team"]:
        return None
    return info


async def admit_visitor(client, user: str) -> bool:
    """許可の無い社内の人に、オーナーが戻るまでのゲスト許可を出す。出せたら True。

    **出し終えてから Hermes に渡す。** Hermes は承認のファイルを毎回開いて読むので、
    ここで待てば、この発言から許可が効く。
    """
    info = await _internal_member(client, user)
    if info is None:
        return False
    kit = _command("seaos-kit")
    if not kit:
        logger.warning("[owner-away] seaos-kit が見つからないので、許可を出せない")
        return False
    name = (info.get("profile") or {}).get("real_name") or info.get("name") or user
    code, out = await _run(kit, "guest", "add", user, "--unlimited", "--label", name,
                           "--note", "オーナー不在中の用件の預かり", "--by", "owner-away")
    if code != 0:
        logger.warning("[owner-away] %s に許可を出せなかった: %s", user, out[-300:])
        return False
    data = _visits()
    data["guests"][user] = {"name": name, "since": time.time()}
    _save_visits(data)
    return True


async def acknowledge(client, user: str, text: str, where: str) -> None:
    """許可を出せない相手（社外の人など）に一言だけ返し、用件を控える。"""
    data = _visits()
    data["messages"].append({"user": user, "text": text, "where": where, "at": time.time()})
    _save_visits(data)
    if time.time() - _noticed.get(user, 0.0) <= NOTICE_INTERVAL:
        return
    try:
        dm = ((await client.conversations_open(users=user)).get("channel") or {}).get("id")
        await client.chat_postMessage(channel=dm, text="オーナーは不在です。戻ったら伝えます。")
        _noticed[user] = time.time()
    except Exception as e:  # noqa: BLE001  （社外の人とはボットの DM を開けないことがある）
        logger.info("[owner-away] %s に一言返せなかった: %s", user, e)


def held_since(started: float) -> list:
    """不在のあいだに保留にしたカード（`seaos-kit card hold` の記録）。"""
    rows = [{"id": k, **v} for k, v in _read_json(HELD_PATH, {}).items() if isinstance(v, dict)]
    return sorted((r for r in rows if float(r.get("held_at") or 0) >= started),
                  key=lambda r: r.get("held_at", 0))


def return_report(cards: list, messages: list, guests: dict) -> str:
    """戻ったオーナーへの DM。保留のカードと、控えた用件。"""
    lines = ["おかえりなさい。不在のあいだに預かったものです。"]
    if cards:
        lines += ["", "*保留のカード*（まだ誰も着手していません）"]
        lines += [f"• {c.get('title')}（<@{c.get('requester')}>、`{c.get('id')}`）" for c in cards]
        lines.append("進めるものは「`t_xxxx` を進めて」、要らないものは「`t_xxxx` を閉じて」と言ってください。")
    if messages:
        lines += ["", "*許可を出せなかった相手からの用件*（社外の人など）"]
        for m in messages:
            text = (m.get("text") or "").replace("\n", " ")
            lines.append(f"• <@{m.get('user')}>（{m.get('where')}）: {text[:200]}")
    talked = [u for u in guests if u not in {c.get("requester") for c in cards}]
    if talked:
        lines += ["", "話しかけてきたが、カードにはならなかった人: " + "、".join(f"<@{u}>" for u in talked)]
    return "\n".join(lines)


async def on_return() -> None:
    """オーナーが戻ったら、預かったものを DM で渡し、不在中に出したゲスト許可を外す。"""
    data = _visits()
    guests, messages = data.get("guests") or {}, data.get("messages") or []
    cards = held_since(float(data.get("away_since") or time.time()))
    if cards or messages or guests:
        client, owner = _state["client"], _state["owner"]
        if not (client and owner):
            return  # 記録は残す。次に戻ったときに渡す
        try:
            await client.chat_postMessage(channel=owner, text=return_report(cards, messages, guests))
        except Exception as e:  # noqa: BLE001
            logger.warning("[owner-away] オーナーへ預かりを渡せなかった: %s", e)
            return
        kit = _command("seaos-kit")
        for user in guests:
            if kit:
                await _run(kit, "guest", "rm", user, "--by", "owner-away", "--reason", "オーナーが戻った")
    _save_visits({"away_since": None, "guests": {}, "messages": []})


# ------------------------------------------------------------------ 選り分け


async def _bot_is_member(client, channel: str) -> bool:
    """ボットがその会話に入っているか。入っていない会話はボットのトークンでは見えない。"""
    hit = _members.get(channel)
    if hit and time.time() - hit[1] < MEMBER_TTL:
        return hit[0]
    try:
        info = (await client.conversations_info(channel=channel)).get("channel") or {}
        member = bool(info.get("is_member") or info.get("is_im"))
    except Exception:  # noqa: BLE001  （channel_not_found = ボットは入っていない）
        member = False
    _members[channel] = (member, time.time())
    return member


def _mentions(text: str, user: str | None) -> bool:
    return bool(user) and f"<@{user}>" in (text or "")


def _drop(event: dict) -> None:
    event["type"] = IGNORED


def _note(kind: str, text: str, intake: bool = False) -> str:
    """operator が「オーナー宛を代わりに受けた」と分かるように、頭に一言添える。

    **文言は owner-away スキルの見出しと一字一句そろえる。** operator はこの一行でスキルを引く。
    `intake` は、不在中にだけ許可を出した相手。operator は保留のカードを作るところまでにする。
    """
    label = f" {kind} " if kind.isascii() else kind
    return f"［オーナー宛の{label}を、オーナーの不在中に代わりに受けた{INTAKE if intake else ''}］\n{text}"


def _authorized(adapter, user: str, channel: str) -> bool:
    """operator と話してよい相手か。**Hermes 自身の判定**（許可ユーザー・ゲストの承認）を使う。

    判定できないときは通す（その先で Hermes が同じ判定をするので、すり抜けはしない）。
    """
    check = getattr(adapter, "_early_reject_unauthorized", None)
    if not callable(check):
        return True
    try:
        return not check(user, channel, True)
    except Exception:  # noqa: BLE001
        return True


async def route(event: dict, client, bot_id: str | None, adapter=None) -> None:
    """届いたメッセージを、そのまま通す・読み替える・移す・捨てる、のどれかにする（その場で書き換える）。"""
    if event.get("type") != "message":
        return
    owner = _state["owner"]
    channel = event.get("channel") or ""
    sender = event.get("user") or ""
    text = event.get("text") or ""
    away = _state["away"]
    from_other = bool(sender) and sender != owner and not event.get("bot_id") and not event.get("subtype")
    member = await _bot_is_member(client, channel)
    is_dm = event.get("channel_type") == "im"
    if member:
        for_owner = away and from_other and bool(bot_id) and _mentions(text, owner) and not _mentions(text, bot_id)
    else:
        for_owner = away and from_other and (is_dm or _mentions(text, owner))
    visitors = _visits().get("guests") or {}

    if not for_owner:
        if not member:
            # オーナーの権限でだけ見えている会話は、operator に見せない。
            _drop(event)
        elif from_other and sender in visitors and not text.startswith("［"):
            # 不在中にだけ許可を出した相手が、operator に直接話しかけてきた。預かりのみに留める。
            event["text"] = _note("話", text, intake=True)
        return

    intake = sender in visitors
    if adapter is not None and not intake and not _authorized(adapter, sender, channel):
        if await admit_visitor(client, sender):
            intake = True
        else:
            await acknowledge(client, sender, text, "DM" if is_dm else f"<#{channel}>")
            _drop(event)
            return

    if member:
        # ボットがいる会話。ボットが呼ばれたものとして、そのスレッドで返させる。
        event["text"] = _note("メンション", text.replace(f"<@{owner}>", f"<@{bot_id}>"), intake)
        return
    try:
        dm = ((await client.conversations_open(users=sender)).get("channel") or {}).get("id")
        kind = "DM" if is_dm else f"メンション（<#{channel}>）"
        first = time.time() - _noticed.get(sender, 0.0) > NOTICE_INTERVAL
        lead = f"オーナーは不在なので、代わりに受けます。届いた{kind}はこちらです。\n" if first else ""
        posted = await client.chat_postMessage(channel=dm, text=f"{lead}>>> {text}")
        _noticed[sender] = time.time()
    except Exception as e:  # noqa: BLE001
        logger.warning("[owner-away] 相手との DM を開けなかった: %s", e)
        _drop(event)
        return
    # 相手とボットの DM で、いま出した案内に続けて話したことにする。
    event.update({"channel": dm, "channel_type": "im", "ts": posted.get("ts"),
                  "text": _note("DM" if is_dm else "メンション", text, intake)})
    event.pop("thread_ts", None)


# ------------------------------------------------------------------ 取り付け


def _is_mine() -> bool:
    mine = _state["profile"]
    if not mine:
        return False
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() == mine
    except Exception:  # noqa: BLE001
        return False


def wire(native, adapter) -> None:
    """Slack の口に、オーナーの見張りと選り分けを足す（接続のたびに呼ばれる）。"""
    if not _is_mine():
        return
    _state["owner"] = _owner_id() or None
    if not _state["owner"]:
        logger.info("[owner-away] SLACK_OWNER_ID が無いので、代わりに受けない")
    bot_id = getattr(adapter, "_bot_user_id", None)
    client = native.client
    _state["client"] = client

    # **ミドルウェアで拾う。** アダプタは「何にでも当たる受け皿」をプラグインより先に
    # 登録するので、`@app.event(...)` を足しても呼ばれない。ミドルウェアは振り分けの前に必ず通る。
    async def owner_away(body, next):  # noqa: A002 — bolt が名前で渡す
        event = (body or {}).get("event") or {}
        try:
            if event.get("type") == "user_status_changed":
                user = event.get("user") or {}
                if user.get("id") and user.get("id") == _state["owner"]:
                    _apply(user.get("profile") or {}, source="ステータスの変化")
            elif _state["owner"]:
                await route(event, client, bot_id, adapter)
        except Exception as e:  # noqa: BLE001  （選り分けで落ちても、ふだんの受け取りは止めない）
            logger.warning("[owner-away] 選り分けに失敗した: %s", e)
        await next()

    native.use(owner_away)

    task = _state.get("task")
    if task is not None and not task.done():
        task.cancel()
    try:
        loop = asyncio.get_running_loop()
        _state["task"] = loop.create_task(_refresh_loop(client))
        loop.create_task(_learn_team(client))
    except RuntimeError:
        logger.warning("[owner-away] ステータスの見張りを始められなかった（イベントループが無い）")


def register(ctx) -> None:
    _state["profile"] = ctx.profile_name
    ctx.register_platform_handler("slack", wire)
