from aiogram.types import ContentType, ReplyKeyboardRemove
from aiogram.utils.exceptions import Unauthorized, MessageCantBeDeleted
import logging

from .settings import bot, dp, BOT_ID, ADMIN, redis

from .state import add_link
from .models import UserToGroup, Group
from .views import (
    check_user, search_link, admin_panel,
    get_link_menu, save_link,
    check_admin, main_menu, save_settings)
from .callback_factory import spam, admin_menu, group_cb, back
from .filters import AdminFilter


dp.filters_factory.bind(AdminFilter)


@dp.errors_handler()
async def error(update, error):
    logging.exception(f'Update - {update} with error')
    return True


# Admin menu
@dp.message_handler(commands='start', state='*', is_admin=True)
@dp.message_handler(text='Отмена', state='*', is_admin=True)
async def welcome(message, state):
    await state.finish()
    if message.text == 'Отмена':
        await bot.send_message(
            message.from_user.id,
            'Отменено',
            reply_markup=ReplyKeyboardRemove()
        )
    text, kb = await main_menu()
    await bot.send_message(
        message.from_user.id,
        text,
        reply_markup=kb
    )


@dp.callback_query_handler(group_cb.filter(action='main'), is_admin=True)
async def handle_main_menu_call(call, callback_data):
    text, kb = await admin_panel(callback_data['id'])
    await bot.edit_message_text(
        text,
        call.from_user.id,
        call.message.message_id,
        reply_markup=kb
    )


@dp.callback_query_handler(back.filter(action='back'), is_admin=True)
async def back_to_main_menu(call, state):
    await state.finish()
    text, kb = await main_menu()
    await bot.edit_message_text(
        text,
        call.from_user.id,
        call.message.message_id,
        reply_markup=kb
    )


@dp.callback_query_handler(
    admin_menu.filter(action=['join', 'check_user', 'left', 'media']),
    is_admin=True)
async def switch_result_handler(call, callback_data):
    mode, action, group_id = callback_data['mode'], callback_data['action'], callback_data['id']
    if mode == 't':
        mode = 'f'
    else:
        mode = 't'
    await redis.set(f'{group_id}:{action}', mode)
    text, kb = await admin_panel(group_id)
    await bot.edit_message_text(
        text,
        call.from_user.id,
        call.message.message_id,
        reply_markup=kb
    )


@dp.callback_query_handler(admin_menu.filter(action='links'), is_admin=True)
async def link_add_menu(call, state, callback_data):
    await add_link.set()
    await state.update_data(id=callback_data['id'])
    text, kb = await get_link_menu()
    await bot.delete_message(
        call.from_user.id,
        call.message.message_id
    )
    await bot.send_message(
        call.from_user.id,
        text,
        reply_markup=kb
    )


@dp.message_handler(state=add_link, is_admin=True)
async def handle_link(message, state):
    data = await state.get_data()
    first, second = await save_link(message.text, data['id'])
    if first[1]:
        await state.finish()
    await bot.send_message(
        message.from_user.id,
        first[0],
        reply_markup=first[2]
    )
    if second:
        await bot.send_message(
            message.from_user.id,
            second[0],
            reply_markup=second[1]
        )


@dp.callback_query_handler(
    admin_menu.filter(action='download'),
    is_admin=True,
    run_task=True)
async def handle_download(call, callback_data):
    cid = int(callback_data['id'])
    await bot.answer_callback_query(
        call.id,
        text='Генерирую документ'
    )

    file = await Group.download_data(cid)
    await bot.send_document(
        call.from_user.id,
        ('group.csv', file)
    )


@dp.message_handler(content_types=ContentType.NEW_CHAT_MEMBERS)
async def new_chat_members_handler(message):
    join = await redis.get(f'{message.chat.id}:join')
    if join is not None and join.decode() == 't':
        try:
            await bot.delete_message(
                message.chat.id,
                message.message_id
            )
        except MessageCantBeDeleted:
            pass
    for member in message.new_chat_members:
        if member.id == BOT_ID:
            await save_settings(message.chat.id)
            if message.chat.type == 'group':
                await bot.leave_chat(message.chat.id)
            # Bot added in the group
            # if it is not added by admin, leave
            elif ADMIN != message.from_user.id:
                await bot.leave_chat(message.chat.id)
            else:
                # Save group in the db
                # or check mark that the group is deleted (deleted=False)
                await Group.save_group(message.chat, readded=True)
        else:
            # User added in the group
            # Save user in the db (group - user)
            # or check mark that user is deleted (deleted=False)
            await UserToGroup.save_user_to_group(
                member,
                message.chat
            )
            check = await redis.get(f'{message.chat.id}:check_user')
            if check is not None and check.decode() == 't':
                # Use restrictChatMember
                await bot.restrict_chat_member(
                    message.chat.id,
                    member.id,
                    until_date=0,
                    can_send_messages=False,
                    )
                text, kb = await check_user(member)
                # Send message with button
                await bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=kb
                )


@dp.callback_query_handler(spam.filter(action='filter'))
async def handle_click(call, callback_data):
    user_id = int(callback_data['id'])
    if call.from_user.id == user_id:
        await bot.restrict_chat_member(
            call.message.chat.id,
            user_id,
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await bot.delete_message(
            call.message.chat.id,
            call.message.message_id
        )
    else:
        await bot.answer_callback_query(call.id)


@dp.message_handler(content_types=ContentType.LEFT_CHAT_MEMBER)
async def left_user_handler(message):
    left = await redis.get(f'{message.chat.id}:left')
    if left is not None and left.decode() == 't':
        # try delete service message
        try:
            await bot.delete_message(
                message.chat.id,
                message.message_id
            )
        except Unauthorized:
            pass

    if message.left_chat_member.id == BOT_ID:
        # Bot was removed from the group
        # Mark in the db that the group is deleted
        await Group.delete_group(message.chat.id)
    else:
        # User left from the group
        # Mark in the db that user is deleted
        await UserToGroup.delete_user_from_group(
            message.left_chat_member,
            message.chat.id
        )


@dp.message_handler(
    lambda msg: msg.chat.type == 'supergroup',
    content_types=[ContentType.AUDIO, ContentType.VIDEO,
                   ContentType.VIDEO_NOTE, ContentType.VOICE,
                   ContentType.PHOTO, ContentType.DOCUMENT])
async def media_handler(message):
    media = await redis.get(f'{message.chat.id}:media')
    if media is not None and media.decode() == 't':
        # if media off - delete message
        # if user != admin
        if not await check_admin(bot, message):
            await bot.delete_message(
                message.chat.id,
                message.message_id
            )


@dp.message_handler(
    lambda msg: msg.chat.type == 'supergroup',
    content_types=[ContentType.STICKER])
async def handle_stickers(message):
    # if user days > 7 days => can send stickers
    # if user != admin
    if not await check_admin(bot, message):
        if await UserToGroup.can_send_sticker(message.from_user, message.chat):
            await bot.delete_message(
                message.chat.id,
                message.message_id
            )


@dp.message_handler(lambda msg: msg.chat.type == 'supergroup')
async def all(message):
    # Check messages in the group (link)
    # if user != admin
    await UserToGroup.save_new_user(
        message.from_user, message.chat
        )
    if not await check_admin(bot, message):
        if await search_link(message.text, message.chat.id):
            await bot.delete_message(
                message.chat.id,
                message.message_id
            )
