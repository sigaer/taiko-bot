from io import BytesIO
from taiko_bot.runtime.qq_images import authorize_image_publication
from nonebot.exception import MatcherException
from . import provider
from .config import profile, root
from . import center_messages, client_messages
from . import fumen_url


def transport():
    return center_messages if profile() == 'center' else client_messages


async def reply(matcher, event, text, image=None):
    t = transport()
    if not t.is_qq_official_event(event):
        await matcher.finish(t._build_onebot_reply_message(text=text, image_bytes=image), reply_message=True)
    if image is not None:
        authorize_image_publication(matcher)
    # Retain each host's existing quick-action keyboard for song error text.
    quick = image is None and bool(getattr(event, 'group_openid', None)) and any(k in text for k in t.QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS)
    if quick:
        message = t._build_qq_markdown_reply_message(event, markdown_text=text.strip() or '快捷操作', include_quick_actions=True)
    else:
        message = t._build_qq_reply_message(event, text=text, image_bytes=image)
    await _send_qq_message(matcher, event, message)


async def _send_qq_message(matcher, event, message):
    t = transport()
    try:
        await matcher.send(message)
    except Exception as exc:
        if profile() != 'center' or not t._is_qq_passive_reply_limit_error(exc) or not await t._send_qq_proactive(matcher, event, message):
            raise
    await matcher.finish()


async def deliver(matcher, event, result):
    if result.kind == 'text':
        if result.delivery == 'direct':
            await matcher.finish(result.payload)
        await reply(matcher, event, result.payload)
    fuzzy = result.kind == 'fuzzy_fumen'
    if fuzzy:
        rows = result.payload
        difficulty, song_id = result.difficulty, str(rows[0][0]).strip()
        hint = f'你要找的可能是：{rows[0][1]}\n匹配度：{float(rows[0][2])/100:.2f}'
    else:
        difficulty, song_id = result.payload
        label = {'Kantan':'简单','Futsuu':'普通','Muzukashii':'困难','Oni':'魔王','InnerOni':'里谱'}[difficulty]
        hint = f'你要找的是不是：\n{label} id{song_id}'
    if profile() == 'center':
        extra = provider.brief(song_id)
        if extra:
            hint += '\n' + extra
    if profile() == 'center' and transport().is_qq_official_event(event):
        # Lookup/construction may fall back BEFORE any send. Once send is
        # attempted, timeout/unknown results must escape without a second reply.
        image_markdown = fumen_url.markdown_image(difficulty, song_id)
        if image_markdown is not None:
            authorize_image_publication(matcher)
            try:
                from nonebot.adapters.qq import Message, MessageSegment
                content = hint + '\n\n' + image_markdown
                prepared = Message(MessageSegment.markdown(content))
            except Exception:
                prepared = None
            if prepared is not None:
                return await _send_qq_message(matcher, event, prepared)
    ok, message = provider.asset_ready()
    if not ok:
        await reply(matcher, event, message)
    path = root()/'assets/fumens'/difficulty/f'{song_id}.png'
    if path.exists():
        with path.open('rb') as f:
            image = BytesIO(f.read())
        try:
            await reply(matcher, event, hint, image)
        except MatcherException:
            raise
        except Exception:
            if transport().is_qq_official_event(event):
                raise
            await reply(matcher, event, hint+'\n（谱面图片发送失败，请稍后重试）')
        finally:
            image.close()
    if fuzzy:
        await reply(matcher, event, hint)
    if profile() == 'center':
        await matcher.finish(hint+'\n（谱面图暂缺，请稍后再试）')
    await matcher.finish(f'未找到谱面文件：{difficulty}/{song_id}.png（路径：assets/fumens/{difficulty}/{song_id}.png）')
