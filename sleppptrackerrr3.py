import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import random
from typing import List, Tuple, Optional, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройки логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ВАЖНО: Здесь должно быть ИМЯ переменной окружения, а не сам токен
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # ← ИЗМЕНЕНО: имя переменной окружения
if not BOT_TOKEN:
    # В качестве запасного варианта можно временно использовать токен напрямую
    # (но это небезопасно для production!)
    BOT_TOKEN = "8003392869:AAHO4GwV0oX0yLE-SybLri0Q60rRCun2vqA"  # ← ВАШ ТОКЕН
    logger.warning("Используется хардкодированный токен (для разработки)")

# Типы данных для анализа сна
SleepRecord = Tuple[str, str, float, Optional[int]]

class Database:
    """Безопасная работа с БД с контекстным менеджером"""
    
    @staticmethod
    @contextmanager
    def get_connection():
        conn = sqlite3.connect('sleep_tracker.db', timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.execute('PRAGMA cache_size=10000;')
        try:
            yield conn
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка БД: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def init_db():
        """Инициализация базы данных"""
        with Database.get_connection() as conn:
            c = conn.cursor()
            # Основная таблица сессий сна
            c.execute('''
                CREATE TABLE IF NOT EXISTS sleep_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    sleep_start TEXT NOT NULL,
                    sleep_end TEXT NOT NULL,
                    duration REAL NOT NULL,
                    quality INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Активные сессии (для восстановления после рестарта)
            c.execute('''
                CREATE TABLE IF NOT EXISTS active_sleeps (
                    user_id INTEGER PRIMARY KEY,
                    sleep_start TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Статистика пользователей
            c.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER PRIMARY KEY,
                    sleep_pattern TEXT,
                    common_issues TEXT,
                    last_analysis TEXT,
                    total_sessions INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Создаем индексы отдельно
            c.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_time 
                ON sleep_sessions (user_id, sleep_start)
            ''')
            
            # Создаем индекс для качества сна
            c.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_quality 
                ON sleep_sessions (user_id, quality)
            ''')

class SleepAI:
    """ИИ-анализатор сна"""
    
    PATTERNS = {
        'night_owl': {
            'name': '🦉 Сова',
            'desc': 'Поздно ложишься и поздно встаешь',
            'issues': ['Недостаток утреннего солнца', 'Сбой циркадных ритмов'],
            'solutions': ['Сдвигай сон на 15 мин раньше ежедневно', 'Яркий свет утром 30 мин']
        },
        'early_bird': {
            'name': '🌅 Жаворонок',
            'desc': 'Рано ложишься и рано встаешь',
            'issues': ['Усталость к вечеру', 'Ранние пробуждения'],
            'solutions': ['Дневной сон 20-30 мин', 'Вечерний ритуал расслабления']
        },
        'irregular': {
            'name': '📅 Нерегулярный',
            'desc': 'Нет четкого режима сна',
            'issues': ['Хроническая усталость', 'Проблемы с концентрацией'],
            'solutions': ['Фиксированное время подъема', 'Будильник каждый день']
        },
        'good_sleeper': {
            'name': '😴 Идеальный',
            'desc': 'Стабильный качественный сон',
            'issues': [],
            'solutions': ['Продолжай!', 'Делись опытом']
        }
    }
    
    @classmethod
    def analyze_pattern(cls, sleep_data: List[SleepRecord]) -> Dict[str, Any]:
        """Анализ паттерна сна"""
        if len(sleep_data) < 3:
            return cls.PATTERNS['irregular']
        
        avg_sleep_hour = sum(datetime.fromisoformat(r[0]).hour + datetime.fromisoformat(r[0]).minute/60 for r in sleep_data) / len(sleep_data)
        avg_wake_hour = sum(datetime.fromisoformat(r[1]).hour + datetime.fromisoformat(r[1]).minute/60 for r in sleep_data) / len(sleep_data)
        avg_duration = sum(r[2] for r in sleep_data) / len(sleep_data)
        
        if avg_sleep_hour < 22 and avg_wake_hour < 7:
            return cls.PATTERNS['early_bird']
        elif avg_sleep_hour >= 23 or avg_wake_hour >= 9:
            return cls.PATTERNS['night_owl']
        elif 7 <= avg_duration <= 9:
            return cls.PATTERNS['good_sleeper']
        return cls.PATTERNS['irregular']
    
    @classmethod
    def detect_issues(cls, sleep_data: List[SleepRecord]) -> List[str]:
        """Выявление проблем"""
        issues = set()
        for start_str, end_str, duration, quality in sleep_data:
            start = datetime.fromisoformat(start_str)
            if start.hour >= 23:
                issues.add('Позднее засыпание')
            if duration < 6:
                issues.add('Недостаток сна')
            if duration > 10:
                issues.add('Пересып')
            if quality and quality <= 2:
                issues.add('Плохое качество')
        return list(issues)[:3]

# Клавиатуры
def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("😴 Начать сон"), KeyboardButton("⏰ Закончить сон")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("📈 Отчет")],
        [KeyboardButton("🧠 AI Анализ"), KeyboardButton("💡 Советы")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def quality_keyboard():
    keyboard = [[InlineKeyboardButton(f"{i} {'😫😕😐😊😍'[i-1]}", callback_data=f"q{i}") for i in range(1, 6)]]
    return InlineKeyboardMarkup(keyboard)

def tips_keyboard():
    keyboard = [
        [InlineKeyboardButton("🌙 Засыпание", callback_data="tips_sleep")],
        [InlineKeyboardButton("🌅 Пробуждение", callback_data="tips_wake")],
        [InlineKeyboardButton("📊 Качество", callback_data="tips_quality")],
        [InlineKeyboardButton("🔄 Режим", callback_data="tips_schedule")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}! 🧠\n\n"
        "Я умный трекер сна с ИИ-анализом:\n"
        "• Отслеживаю сон 24/7\n"
        "• Анализирую паттерны\n"
        "• Даю персональные советы\n\n"
        "Нажми кнопку ниже:",
        reply_markup=main_menu_keyboard()
    )

async def handle_start_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать отслеживание сна"""
    user_id = update.effective_user.id
    now = datetime.now()
    
    with Database.get_connection() as conn:
        c = conn.cursor()
        # Проверяем активный сон
        c.execute("SELECT sleep_start FROM active_sleeps WHERE user_id = ?", (user_id,))
        if c.fetchone():
            await update.message.reply_text("⚠️ У вас уже активный сон! Завершите его сначала.")
            return
        
        # Создаем новую сессию
        c.execute(
            "INSERT INTO active_sleeps (user_id, sleep_start) VALUES (?, ?)",
            (user_id, now.isoformat())
        )
    
    await update.message.reply_text(
        f"😴 **Сон начат!**\n\n"
        f"🕐 {now.strftime('%H:%M %d.%m.%Y')}\n"
        f"🌙 Спокойной ночи! Когда проснешься → '⏰ Закончить сон'",
        reply_markup=main_menu_keyboard()
    )

async def handle_end_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершить сон"""
    user_id = update.effective_user.id
    now = datetime.now()
    
    with Database.get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT sleep_start FROM active_sleeps WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if not result:
            await update.message.reply_text("❌ Нет активного сна! Нажми '😴 Начать сон'.", reply_markup=main_menu_keyboard())
            return
        
        start_iso = result['sleep_start']
        start_time = datetime.fromisoformat(start_iso)
        duration = (now - start_time).total_seconds() / 3600
        
        # Сохраняем сессию
        c.execute('''
            INSERT INTO sleep_sessions (user_id, sleep_start, sleep_end, duration)
            VALUES (?, ?, ?, ?)
        ''', (user_id, start_iso, now.isoformat(), duration))
        
        # Удаляем активную сессию
        c.execute("DELETE FROM active_sleeps WHERE user_id = ?", (user_id,))
        session_id = c.lastrowid
        
        # Обновляем статистику
        c.execute('''
            INSERT OR IGNORE INTO user_stats (user_id) VALUES (?)
            ON CONFLICT(user_id) DO UPDATE SET total_sessions = total_sessions + 1
        ''', (user_id,))
    
    # Быстрый анализ
    analysis = SleepAI._quick_analysis(start_time, now, duration)
    
    await update.message.reply_text(
        f"✅ **Сон завершен!**\n\n"
        f"{analysis}\n\n"
        f"📊 Детали:\n"
        f"• Начало: {start_time.strftime('%H:%M')}\n"
        f"• Конец: {now.strftime('%H:%M')}\n"
        f"• {duration:.1f}ч\n\n"
        f"⭐ Оцени качество:",
        reply_markup=quality_keyboard(),
        parse_mode='Markdown'
    )
    context.user_data['last_session_id'] = session_id

SleepAI._quick_analysis = classmethod(
    lambda cls, start, end, hours: 
    f"🕐 Засыпание: {'рано 🌅' if start.hour < 22 else 'нормально ⏰' if start.hour < 0 else 'поздно 🌙'}\n"
    f"⏱️ Длительность: {'мало 😴' if hours < 6 else 'нормально 👍' if hours < 9 else 'много ⭐'}\n"
    f"🌅 Пробуждение: {'рано ☀️' if end.hour < 7 else 'идеально 🌞' if end.hour < 9 else 'поздно 😴'}"
)

async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка оценки качества"""
    query = update.callback_query
    await query.answer()
    
    quality = int(query.data[1])
    user_id = query.from_user.id
    session_id = context.user_data.get('last_session_id')
    
    if not session_id:
        await query.edit_message_text("❌ Ошибка сессии. Начни новый сон.")
        return
    
    with Database.get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE sleep_sessions SET quality = ? WHERE id = ?", (quality, session_id))
    
    # Детальный анализ
    analysis = await _get_detailed_analysis(session_id, quality)
    
    await query.edit_message_text(analysis, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Меню", callback_data="back_menu")]
    ]))
    
    # Очистка
    context.user_data.pop('last_session_id', None)

async def _get_detailed_analysis(session_id: int, quality: int) -> str:
    """Детальный анализ конкретного сна"""
    with Database.get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT sleep_start, sleep_end, duration FROM sleep_sessions WHERE id = ?
        ''', (session_id,))
        row = c.fetchone()
        
        if not row:
            return "❌ Данные не найдены"
        
        start = datetime.fromisoformat(row['sleep_start'])
        duration = row['duration']
        
        emojis = "😫😕😐😊😍"
        texts = ["Ужасно", "Плохо", "Нормально", "Хорошо", "Отлично"]
        
        tips = []
        if duration < 6:
            tips.append("⚠️ Мало сна — восстановление неполное")
        if start.hour >= 23:
            tips.append("🌙 Поздно лег — циркадные ритмы сбиты")
        if quality <= 2:
            tips.append("💡 Темнота + прохлада + тишина")
        
        tips_text = "\n".join(f"• {tip}" for tip in tips) if tips else "✅ Сон в норме"
        
        return (
            f"{emojis[quality-1]} **{quality}/5** ({texts[quality-1]})\n\n"
            f"🧠 **Анализ:**\n{tips_text}\n\n"
            f"💾 Сохранено! Для полного AI → '🧠 AI Анализ'"
        )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика пользователя"""
    user_id = update.effective_user.id
    
    with Database.get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT COUNT(*), AVG(duration), AVG(quality), MIN(duration), MAX(duration)
            FROM sleep_sessions WHERE user_id = ? AND quality IS NOT NULL
        ''', (user_id,))
        stats = c.fetchone()
        
        if not stats[0]:
            text = "📭 Нет данных\n\nОтследи 3+ сна с оценками!"
        else:
            count, avg_h, avg_q, min_h, max_h = stats
            
            c.execute('''
                SELECT sleep_start, sleep_end, duration, quality
                FROM sleep_sessions WHERE user_id = ? AND quality IS NOT NULL
                ORDER BY sleep_start DESC LIMIT 10
            ''', (user_id,))
            data = [(r['sleep_start'], r['sleep_end'], r['duration'], r['quality']) for r in c.fetchall()]
            
            pattern = SleepAI.analyze_pattern(data)
            
            text = (
                f"📊 **Статистика** ({count} записей)\n\n"
                f"⏱️ Средне: {avg_h:.1f}ч\n"
                f"⭐ Качество: {avg_q:.1f}/5\n"
                f"📉 Мин: {min_h:.1f}ч | 📈 Макс: {max_h:.1f}ч\n\n"
                f"🧠 **Паттерн:** {pattern['name']}\n"
                f"{pattern['desc']}\n\n"
                f"🔄 Последние:\n"
            )
            for start_str, _, dur, qual in data[:5]:
                dt = datetime.fromisoformat(start_str)
                text += f"• {dt.strftime('%d.%m %H:%M')} — {dur:.1f}ч (★×{qual})\n"
    
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

async def ai_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный AI анализ"""
    user_id = update.effective_user.id
    
    with Database.get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT sleep_start, sleep_end, duration, quality
            FROM sleep_sessions WHERE user_id = ? AND quality IS NOT NULL
            ORDER BY sleep_start DESC LIMIT 20
        ''', (user_id,))
        data = [(r['sleep_start'], r['sleep_end'], r['duration'], r['quality']) for r in c.fetchall()]
    
    if len(data) < 3:
        advice = SleepAI._general_advice()
    else:
        pattern = SleepAI.analyze_pattern(data)
        issues = SleepAI.detect_issues(data)
        
        advice = (
            f"🎯 **Твой тип:** {pattern['name']}\n"
            f"📝 {pattern['desc']}\n\n"
        )
        
        if issues:
            advice += "🚨 **Проблемы:**\n" + "\n".join(f"• {issue}" for issue in issues) + "\n\n"
        
        advice += "💡 **Рекомендации:**\n"
        advice += "• " + "; ".join(pattern['solutions']) + "\n"
        advice += f"• Рандом: {random.choice(['Вода днем', 'Спорт утром', 'Нет кофе после 15:00'])}"
    
    await update.message.reply_text(advice, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

SleepAI._general_advice = classmethod(lambda cls: 
    "🧠 **Нужно 3+ записей**\n\n"
    "1. Отслеживай сон\n2. Оценивай качество\n3. Будь регулярным\n\n"
    "💡 Пока: 7-9ч, до 23:00, без экранов"
)

# Остальные обработчики
async def tips_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💡 **Категория советов:**", reply_markup=tips_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых кнопок"""
    text = update.message.text
    handlers = {
        "😴 Начать сон": handle_start_sleep,
        "⏰ Закончить сон": handle_end_sleep,
        "📊 Статистика": show_stats,
        "🧠 AI Анализ": ai_analysis,
        "💡 Советы": tips_menu,
        "📈 Отчет": lambda u, c: update.message.reply_text("📈 Скоро!"),  # TODO
    }
    
    handler = handlers.get(text)
    if handler:
        await handler(update, context)
    else:
        await update.message.reply_text("👆 Используй кнопки!", reply_markup=main_menu_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный обработчик callback"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith('q'):  # Качество
        await quality_callback(update, context)
    elif data == 'back_menu':
        await query.edit_message_text("✅ Готово!", reply_markup=main_menu_keyboard())
    elif data == 'back_tips':
        await query.edit_message_text("💡 **Категория советов:**", reply_markup=tips_keyboard())
    elif data.startswith('tips_'):
        # Обработка советов
        tip_type = data.split('_')[1]
        tips = {
            'sleep': "🌙 **Советы для засыпания:**\n• Температура 18-20°C\n• За 1 час без экранов\n• Чай с ромашкой\n• Медитация 10 мин",
            'wake': "🌅 **Советы для пробуждения:**\n• Яркий свет утром\n• Стакан воды\n• Легкая зарядка\n• Завтрак с белком",
            'quality': "📊 **Качество сна:**\n• Удобная подушка\n• Тишина и темнота\n• Регулярное время\n• Маска для сна",
            'schedule': "🔄 **Режим:**\n• Фиксированное время\n• +-30 мин допустимо\n• Выходные тоже\n• Ложись в одно время"
        }
        await query.edit_message_text(tips.get(tip_type, "💡 Советы скоро обновятся!"), 
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_tips")]]))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    Database.init_db()
    print("🚀 AI Sleep Tracker запущен!")
    
    # Создаем приложение без job_queue
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    
    # Просто выводим сообщение без job_queue
    print("🤖 Бот запущен и готов к работе!")
    print("⚠️ JobQueue не используется - это нормально для этой версии")
    
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()