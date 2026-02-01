import logging
import sqlite3
from datetime import datetime, timedelta
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    MessageHandler, 
    filters
)

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = '8003392869:AAHO4GwV0oX0yLE-SybLri0Q60rRCun2vqA'

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('sleep_tracker.db')
    c = conn.cursor()
    
    # Основная таблица сна
    c.execute('''
        CREATE TABLE IF NOT EXISTS sleep_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sleep_start TEXT NOT NULL,
            sleep_end TEXT NOT NULL,
            duration_hours REAL,
            quality INTEGER CHECK(quality >= 1 AND quality <= 5),
            notes TEXT,
            weekday INTEGER,
            recommendation TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Создаем кнопки главного меню
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("😴 Начать сон"), KeyboardButton("⏰ Закончить сон")],
        [KeyboardButton("📊 Моя статистика"), KeyboardButton("📋 Отчет за неделю")],
        [KeyboardButton("💡 Рекомендации"), KeyboardButton("🏆 Рекорды")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Создаем кнопки для оценки сна
def get_quality_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("1 😫", callback_data="quality_1"),
            InlineKeyboardButton("2 😕", callback_data="quality_2"),
            InlineKeyboardButton("3 😐", callback_data="quality_3"),
            InlineKeyboardButton("4 😊", callback_data="quality_4"),
            InlineKeyboardButton("5 😍", callback_data="quality_5")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - показывает кнопки"""
    try:
        user = update.effective_user
        
        welcome_text = f"""👋 Привет, {user.first_name}!

Я - твой персональный трекер сна! 
Отслеживай свой сон, получай анализ и рекомендации.

📱 Используй кнопки ниже:"""
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in start: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    try:
        text = update.message.text
        
        if text == "😴 Начать сон":
            await start_sleep(update, context)
        elif text == "⏰ Закончить сон":
            await end_sleep(update, context)
        elif text == "📊 Моя статистика":
            await show_statistics(update, context)
        elif text == "📋 Отчет за неделю":
            await weekly_report(update, context)
        elif text == "💡 Рекомендации":
            await get_recommendations(update, context)
        elif text == "🏆 Рекорды":
            await show_records(update, context)
    except Exception as e:
        logger.error(f"Error in button_handler: {e}")

async def start_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать сон"""
    try:
        now = datetime.now()
        context.user_data['sleep_start'] = now.isoformat()
        
        weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        weekday = weekdays[now.weekday()]
        
        await update.message.reply_text(
            f"🌙 Начинаем отслеживать сон!\n"
            f"📅 {weekday}, {now.strftime('%H:%M')}\n\n"
            f"Спи крепко! Нажми '⏰ Закончить сон' при пробуждении.",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in start_sleep: {e}")

async def end_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закончить сон"""
    try:
        if 'sleep_start' not in context.user_data:
            await update.message.reply_text(
                "❌ Сон не начат! Нажми '😴 Начать сон' сначала.",
                reply_markup=get_main_keyboard()
            )
            return
        
        sleep_start = datetime.fromisoformat(context.user_data['sleep_start'])
        sleep_end = datetime.now()
        
        duration = sleep_end - sleep_start
        hours = duration.total_seconds() / 3600
        minutes = int((duration.total_seconds() % 3600) / 60)
        
        # Сохраняем для оценки
        context.user_data['last_sleep'] = {
            'start': sleep_start,
            'end': sleep_end,
            'hours': hours
        }
        
        message = (
            f"✅ Сон окончен!\n\n"
            f"📊 Результаты:\n"
            f"🛏️ Лег: {sleep_start.strftime('%H:%M')}\n"
            f"⏰ Проснулся: {sleep_end.strftime('%H:%M')}\n"
            f"⏱️ Длительность: {int(hours)}ч {minutes}м\n\n"
            f"Оцени качество сна:"
        )
        
        await update.message.reply_text(
            message,
            reply_markup=get_quality_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in end_sleep: {e}")

async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик оценки сна"""
    try:
        query = update.callback_query
        await query.answer()
        
        quality = int(query.data.split('_')[1])
        user_id = query.from_user.id
        
        if 'last_sleep' not in context.user_data:
            await query.edit_message_text("❌ Данные о сне не найдены")
            return
        
        sleep_data = context.user_data['last_sleep']
        sleep_start = sleep_data['start']
        sleep_end = sleep_data['end']
        hours = sleep_data['hours']
        
        # Генерируем рекомендацию
        recommendation = generate_recommendation(sleep_start, sleep_end, hours, quality)
        analysis = analyze_sleep_pattern(sleep_start, sleep_end, hours, quality)
        
        # Сохраняем в базу
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO sleep_logs 
            (user_id, sleep_start, sleep_end, duration_hours, quality, recommendation, weekday)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, 
            sleep_start.isoformat(), 
            sleep_end.isoformat(), 
            hours, 
            quality, 
            recommendation, 
            sleep_start.weekday()
        ))
        
        conn.commit()
        conn.close()
        
        quality_emojis = ["😫", "😕", "😐", "😊", "😍"]
        
        response = (
            f"{quality_emojis[quality-1]} Оценка {quality}/5 сохранена!\n\n"
            f"📈 Анализ сна:\n{analysis}\n\n"
            f"💡 Рекомендация:\n{recommendation}"
        )
        
        await query.edit_message_text(response)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Используй кнопки ниже:",
            reply_markup=get_main_keyboard()
        )
        
        # Очищаем данные
        if 'last_sleep' in context.user_data:
            del context.user_data['last_sleep']
        if 'sleep_start' in context.user_data:
            del context.user_data['sleep_start']
            
    except Exception as e:
        logger.error(f"Error in quality_callback: {e}")

def generate_recommendation(start_time, end_time, hours, quality):
    """Генерирует рекомендации"""
    recommendations = []
    
    # Анализ времени отхода ко сну
    hour = start_time.hour
    if hour < 22:
        recommendations.append("✓ Отличное время для отхода ко сну")
    elif hour < 24:
        recommendations.append("✓ Нормальное время засыпания")
    else:
        recommendations.append("⚠️ Старайся ложиться до полуночи")
    
    # Анализ продолжительности
    if hours < 6:
        recommendations.append("⚠️ Мало сна! Нужно 7-9 часов")
    elif hours < 8:
        recommendations.append("✓ Нормальная продолжительность")
    elif hours <= 10:
        recommendations.append("✓ Хорошо выспался!")
    else:
        recommendations.append("⚠️ Слишком долгий сон")
    
    # Анализ качества
    if quality <= 2:
        recommendations.append("⚠️ Плохое качество. Проверь условия сна")
    elif quality == 3:
        recommendations.append("✓ Среднее качество")
    else:
        recommendations.append("✓ Отличное качество!")
    
    return "\n".join(recommendations)

def analyze_sleep_pattern(start_time, end_time, hours, quality):
    """Анализирует сон"""
    analysis = []
    
    sleep_time = start_time.strftime("%H:%M")
    wake_time = end_time.strftime("%H:%M")
    
    if start_time.hour >= 22 or start_time.hour < 2:
        sleep_type = "Ночной сон 🌙"
    else:
        sleep_type = "Дневной/поздний сон 🌅"
    
    analysis.append(f"• Тип: {sleep_type}")
    analysis.append(f"• Засыпание: {sleep_time}")
    analysis.append(f"• Пробуждение: {wake_time}")
    analysis.append(f"• Длительность: {hours:.1f} ч")
    
    if quality >= 4:
        quality_text = "Высокое ⭐⭐⭐⭐⭐"
    elif quality >= 2:
        quality_text = "Среднее ⭐⭐⭐"
    else:
        quality_text = "Низкое ⭐"
    
    analysis.append(f"• Качество: {quality_text}")
    
    return "\n".join(analysis)

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику"""
    try:
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT COUNT(*), AVG(duration_hours), AVG(quality), 
                   MAX(duration_hours), MIN(duration_hours)
            FROM sleep_logs 
            WHERE user_id = ? AND quality IS NOT NULL
        ''', (user_id,))
        
        stats = c.fetchone()
        
        if stats and stats[0] > 0:
            total, avg_hours, avg_quality, best, worst = stats
            
            c.execute('''
                SELECT sleep_start, duration_hours, quality
                FROM sleep_logs 
                WHERE user_id = ? AND quality IS NOT NULL
                ORDER BY sleep_start DESC LIMIT 5
            ''', (user_id,))
            
            recent = c.fetchall()
            
            message = (
                f"📊 Ваша статистика:\n\n"
                f"📈 Всего снов: {total}\n"
                f"⏱️ Средняя длина: {avg_hours:.1f} ч\n"
                f"⭐ Средняя оценка: {avg_quality:.1f}/5\n"
                f"🏆 Лучший: {best:.1f} ч\n"
                f"📉 Худший: {worst:.1f} ч\n\n"
                f"🔄 Последние 5 записей:\n"
            )
            
            for i, (start_time, duration, quality) in enumerate(recent, 1):
                date = datetime.fromisoformat(start_time).strftime("%d.%m %H:%M")
                message += f"{i}. {date} - {duration:.1f}ч ({quality}/5)\n"
            
        else:
            message = "📭 Нет записей о сне.\nНачни с кнопки '😴 Начать сон'!"
        
        conn.close()
        
        await update.message.reply_text(
            message,
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in show_statistics: {e}")

async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отчет за неделю"""
    try:
        user_id = update.effective_user.id
        week_ago = datetime.now() - timedelta(days=7)
        
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT DATE(sleep_start) as date,
                   AVG(duration_hours) as avg_hours,
                   AVG(quality) as avg_quality
            FROM sleep_logs 
            WHERE user_id = ? 
            AND DATE(sleep_start) >= DATE(?)
            AND quality IS NOT NULL
            GROUP BY DATE(sleep_start)
            ORDER BY date DESC
        ''', (user_id, week_ago.isoformat()))
        
        days = c.fetchall()
        conn.close()
        
        if days:
            weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            
            report = "📋 ОТЧЕТ ЗА НЕДЕЛЮ\n\n"
            report += "День        Сон     Качество\n"
            report += "―" * 30 + "\n"
            
            total_hours = 0
            for date_str, hours, quality in days:
                date_obj = datetime.fromisoformat(date_str)
                weekday = weekdays[date_obj.weekday()]
                day_str = date_obj.strftime(f"{weekday} %d.%m")
                
                hours_bar = "█" * min(int(hours), 10)
                quality_stars = "★" * min(int(quality or 0), 5)
                
                report += f"{day_str:12} {hours:.1f}ч {hours_bar:10} {quality_stars}\n"
                total_hours += hours or 0
            
            avg_quality = sum(day[2] for day in days if day[2]) / len(days) if days else 0
            
            report += f"\n📊 ИТОГО:\n"
            report += f"• Дней со сном: {len(days)}\n"
            report += f"• Средний сон: {total_hours/len(days):.1f} ч/день\n"
            report += f"• Среднее качество: {avg_quality:.1f}/5"
            
        else:
            report = "📭 За неделю нет записей о сне.\nНачни отслеживание сегодня!"
        
        await update.message.reply_text(
            report,
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in weekly_report: {e}")

async def get_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рекомендации"""
    try:
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT AVG(duration_hours), AVG(quality), COUNT(*)
            FROM sleep_logs 
            WHERE user_id = ? AND quality IS NOT NULL
        ''', (user_id,))
        
        stats = c.fetchone()
        conn.close()
        
        if stats and stats[2] > 0:
            avg_hours, avg_quality, count = stats
            
            recommendations = []
            
            if avg_hours < 7:
                recommendations.append("⚠️ Спи больше! Оптимально 7-9 часов")
            elif avg_hours > 9:
                recommendations.append("⚠️ Слишком много сна")
            
            if avg_quality < 3:
                recommendations.append("💡 Улучши условия сна:")
                recommendations.append("  • Темнота и тишина")
                recommendations.append("  • Комфортная температура")
                recommendations.append("  • Без гаджетов за час до сна")
            
            recommendations.append("🌙 Ложись в 22:00-23:00")
            recommendations.append("☀️ Вставай в 6:00-8:00")
            
            if count < 10:
                recommendations.append("📊 Отслеживай сон регулярно!")
            
            response = "💡 РЕКОМЕНДАЦИИ\n\n" + "\n".join(recommendations)
            
        else:
            response = (
                "📭 Мало данных для рекомендаций.\n"
                "Отслеживай сон несколько дней для анализа."
            )
        
        await update.message.reply_text(
            response,
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in get_recommendations: {e}")

async def show_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рекорды"""
    try:
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT MAX(duration_hours), MIN(duration_hours),
                   MAX(quality), MIN(quality)
            FROM sleep_logs 
            WHERE user_id = ? AND quality IS NOT NULL
        ''', (user_id,))
        
        records = c.fetchone()
        conn.close()
        
        if records and records[0]:
            longest, shortest, best_quality, worst_quality = records
            
            message = (
                "🏆 ВАШИ РЕКОРДЫ\n\n"
                f"⭐ Самый длинный сон: {longest:.1f} ч\n"
                f"📉 Самый короткий: {shortest:.1f} ч\n"
                f"😍 Лучшее качество: {int(best_quality)}/5\n"
                f"😫 Худшее качество: {int(worst_quality)}/5"
            )
        else:
            message = "📭 Пока нет рекордов."
        
        await update.message.reply_text(
            message,
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in show_records: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений"""
    try:
        await update.message.reply_text(
            "Используй кнопки для управления:",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update and update.message:
        try:
            await update.message.reply_text(
                "❌ Ошибка. Попробуй еще раз.",
                reply_markup=get_main_keyboard()
            )
        except:
            pass

def main():
    """Главная функция"""
    try:
        # Инициализация БД
        init_db()
        
        print("🚀 Запуск бота...")
        
        # Создаем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
        application.add_handler(CallbackQueryHandler(quality_callback, pattern="^quality_"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        print("✅ Бот запущен! Ctrl+C для остановки")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")

if __name__ == '__main__':
    main()