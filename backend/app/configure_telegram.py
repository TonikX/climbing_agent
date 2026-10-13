"""Configure Telegram's native command menu after deployment; never send messages."""
import asyncio

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands

from app.config import get_settings


async def main():
    async with Bot(get_settings().telegram_bot_token.get_secret_value()) as bot:
        commands = [BotCommand(command=command, description=description) for command, description in (
            ("journal", "Главное меню"), ("training", "Начать тренировку"),
            ("stats", "Личная статистика"), ("profile", "Профиль"),
            ("finish", "Завершить тренировку"), ("cancel", "Отменить ввод"),
            ("start", "Доступ к боту"), ("privacy", "Личные данные"))]
        await bot.set_my_commands(commands)
        await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        print("Telegram command menu configured; /journal opens the main menu")


if __name__ == "__main__":
    asyncio.run(main())
