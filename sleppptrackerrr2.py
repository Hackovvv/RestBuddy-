import logging
import sqlite3
from datetime import datetime, timedelta
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Настройки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = '8003392869:AAHO4GwV0oX0yLE-SybLri0Q60rRCun2vqA'

# База данных
def init_db():
    conn = sqlite3.connect('sleep_tracker.db')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS sleep_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sleep_start TEXT NOT NULL,
            sleep_end TEXT,
            duration REAL,
            quality INTEGER,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER PRIMARY KEY,
            sleep_pattern TEXT,
            common_issues TEXT,
            last_analysis TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Кнопки
def main_menu():
    keyboard = [
        [KeyboardButton("😴 Начать сон"), KeyboardButton("⏰ Закончить сон")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("📈 Отчет")],
        [KeyboardButton("🧠 AI Анализ"), KeyboardButton("💡 Советы")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def quality_buttons():
    keyboard = [[
        InlineKeyboardButton("1 😫", callback_data="q1"),
        InlineKeyboardButton("2 😕", callback_data="q2"),
        InlineKeyboardButton("3 😐", callback_data="q3"),
        InlineKeyboardButton("4 😊", callback_data="q4"),
        InlineKeyboardButton("5 😍", callback_data="q5")
    ]]
    return InlineKeyboardMarkup(keyboard)

# "Нейросеть" для анализа
class SleepAI:
    def __init__(self):
        self.patterns = {
            'night_owl': {
                'name': 'Сова 🦉',
                'desc': 'Поздно ложишься и поздно встаешь',
                'issues': ['Недостаток утреннего солнца', 'Сбой циркадных ритмов'],
                'solutions': ['Постепенно сдвигай сон на 15 мин раньше', 'Яркий свет утром']
            },
            'early_bird': {
                'name': 'Жаворонок 🌅',
                'desc': 'Рано ложишься и рано встаешь',
                'issues': ['Усталость к вечеру', 'Ранние пробуждения'],
                'solutions': ['Легкий сон днем 20-30 мин', 'Вечерний ритуал расслабления']
            },
            'irregular': {
                'name': 'Непостоянный 📅',
                'desc': 'Нет четкого режима сна',
                'issues': ['Хроническая усталость', 'Проблемы с концентрацией'],
                'solutions': ['Фиксированное время подъема', 'Будильник каждый день в одно время']
            },
            'good_sleeper': {
                'name': 'Идеальный сон 😴',
                'desc': 'Стабильный и качественный сон',
                'issues': [],
                'solutions': ['Продолжай в том же духе!', 'Делись секретами с друзьями']
            }
        }
    
    def analyze_user_pattern(self, sleep_data):
        """Анализирует паттерн сна пользователя"""
        if not sleep_data or len(sleep_data) < 5:
            return self.patterns['irregular']
        
        avg_sleep_times = []
        avg_wake_times = []
        durations = []
        
        for start_str, end_str, duration, quality in sleep_data:
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)
            avg_sleep_times.append(start.hour + start.minute/60)
            avg_wake_times.append(end.hour + end.minute/60)
            durations.append(duration)
        
        avg_sleep = sum(avg_sleep_times) / len(avg_sleep_times)
        avg_wake = sum(avg_wake_times) / len(avg_wake_times)
        avg_duration = sum(durations) / len(durations)
        
        # Определяем паттерн
        if avg_sleep < 22 and avg_wake < 7:
            return self.patterns['early_bird']
        elif avg_sleep >= 23 or avg_wake >= 9:
            return self.patterns['night_owl']
        elif avg_duration >= 7 and avg_duration <= 9:
            return self.patterns['good_sleeper']
        else:
            return self.patterns['irregular']
    
    def detect_issues(self, sleep_data):
        """Выявляет проблемы со сном"""
        issues = []
        
        for start_str, end_str, duration, quality in sleep_data:
            start = datetime.fromisoformat(start_str)
            
            # Позднее засыпание
            if start.hour >= 23:
                issues.append('Позднее засыпание')
            
            # Короткий сон
            if duration < 6:
                issues.append('Недостаток сна')
            
            # Длинный сон
            if duration > 10:
                issues.append('Избыток сна')
            
            # Низкое качество
            if quality and quality <= 2:
                issues.append('Низкое качество сна')
        
        # Убираем дубликаты
        return list(set(issues))
    
    def generate_personal_advice(self, user_id, sleep_data):
        """Генерирует персонализированные советы"""
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        # Получаем статистику
        c.execute('''
            SELECT 
                AVG(duration),
                AVG(quality),
                COUNT(*)
            FROM sleep_sessions 
            WHERE user_id = ? AND quality IS NOT NULL
        ''', (user_id,))
        
        stats = c.fetchone()
        conn.close()
        
        if not stats or stats[2] < 3:
            return self._get_general_advice()
        
        avg_duration, avg_quality, count = stats
        
        # Анализируем паттерн
        pattern = self.analyze_user_pattern(sleep_data)
        issues = self.detect_issues(sleep_data)
        
        # Генерируем советы
        advice = []
        advice.append(f"🎯 **Твой тип:** {pattern['name']}")
        advice.append(f"📊 **Характеристика:** {pattern['desc']}")
        
        if pattern['issues']:
            advice.append("\n⚠️ **Типичные проблемы:**")
            for issue in pattern['issues']:
                advice.append(f"• {issue}")
        
        if issues:
            advice.append("\n🚨 **Выявленные проблемы:**")
            for issue in list(set(issues))[:3]:  # Максимум 3 проблемы
                advice.append(f"• {issue}")
        
        # Персонализированные советы
        advice.append("\n💡 **Персональные рекомендации:**")
        
        # По продолжительности
        if avg_duration < 6.5:
            advice.append("• Увеличь сон до 7-9 часов - это необходимо для здоровья")
        elif avg_duration > 9.5:
            advice.append("• Оптимально 7-9 часов - слишком долгий сон тоже вреден")
        else:
            advice.append("• Отличная продолжительность! Продолжай в том же духе")
        
        # По качеству
        if avg_quality and avg_quality < 3:
            advice.append("• Улучши условия сна: темнота, тишина, прохлада")
            advice.append("• За 1 час до сна - никаких экранов")
            advice.append("• Попробуй медитацию или чтение перед сном")
        elif avg_quality and avg_quality >= 4:
            advice.append("• Отличное качество сна! Ты на правильном пути")
        
        # Советы по паттерну
        for solution in pattern['solutions'][:2]:
            advice.append(f"• {solution}")
        
        # Случайный полезный совет
        random_tips = [
            "Пей достаточно воды в течение дня",
            "Регулярные физические нагрузки улучшают сон",
            "Старайся ложиться и вставать в одно время",
            "Кофеин после 15:00 может мешать засыпанию",
            "Легкий ужин за 3 часа до сна",
            "Температура в спальне 18-20°C оптимальна"
        ]
        advice.append(f"• {random.choice(random_tips)}")
        
        return "\n".join(advice)
    
    def _get_general_advice(self):
        """Общие советы при недостатке данных"""
        return """🧠 **AI Анализ сна**

📊 **Недостаточно данных для глубокого анализа**
Чтобы получить персонализированные рекомендации, нужно:

1. 📝 Отслеживать сон минимум 3-5 дней
2. ⭐ Оценивать качество после каждого сна
3. 🕒 Быть последовательным в записях

💡 **Пока что общие рекомендации:**
• Старайся спать 7-9 часов
• Ложись до 23:00
• Создай вечерний ритуал
• Избегай гаджетов перед сном

Продолжай отслеживать сон для получения персональных советов!"""

# Создаем экземпляр AI
sleep_ai = SleepAI()

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я - умный бот для анализа сна с ИИ-помощником 🧠\n\n"
        "📊 **Что я умею:**\n"
        "• Отслеживать твой сон\n"
        "• Анализировать паттерны сна\n"
        "• Давать персональные рекомендации\n"
        "• Показывать статистику и отчеты\n\n"
        "Используй кнопки ниже:",
        reply_markup=main_menu()
    )

async def start_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = datetime.now()
    
    context.user_data['sleep_start'] = now
    context.user_data['sleep_start_time'] = now.strftime('%H:%M')
    
    await update.message.reply_text(
        f"😴 **Начинаем отслеживание сна!**\n\n"
        f"🕐 Время: {now.strftime('%H:%M %d.%m.%Y')}\n"
        f"🌙 Ложись спать, я буду следить...\n\n"
        f"Когда проснешься, нажми '⏰ Закончить сон'",
        reply_markup=main_menu()
    )

async def end_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if 'sleep_start' not in context.user_data:
        await update.message.reply_text(
            "❌ Сначала начни сон!",
            reply_markup=main_menu()
        )
        return
    
    start_time = context.user_data['sleep_start']
    end_time = datetime.now()
    
    duration = end_time - start_time
    hours = duration.total_seconds() / 3600
    
    # Сохраняем данные
    context.user_data['last_sleep'] = {
        'start': start_time,
        'end': end_time,
        'hours': hours
    }
    
    # Сохраняем в БД
    conn = sqlite3.connect('sleep_tracker.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO sleep_sessions (user_id, sleep_start, sleep_end, duration)
        VALUES (?, ?, ?, ?)
    ''', (user_id, start_time.isoformat(), end_time.isoformat(), hours))
    context.user_data['last_sleep_id'] = c.lastrowid
    conn.commit()
    conn.close()
    
    # AI анализ сразу
    quick_analysis = sleep_ai._get_quick_analysis(start_time, end_time, hours)
    
    await update.message.reply_text(
        f"✅ **Сон завершен!**\n\n"
        f"📊 **Быстрый анализ:**\n{quick_analysis}\n\n"
        f"🛏️ **Детали:**\n"
        f"• Начало: {start_time.strftime('%H:%M')}\n"
        f"• Конец: {end_time.strftime('%H:%M')}\n"
        f"• Длительность: {hours:.1f} часов\n\n"
        f"⭐ **Оцени качество сна:**",
        reply_markup=quality_buttons()
    )

# Добавляем метод быстрого анализа
SleepAI._get_quick_analysis = lambda self, start, end, hours: f"""🕐 Время засыпания: {'рано 🌅' if start.hour < 22 else 'нормально ⏰' if start.hour < 24 else 'поздно 🌙'}
⏱️ Продолжительность: {'мало 😴' if hours < 6 else 'нормально 👍' if hours < 9 else 'много ⭐'}
🌅 Время пробуждения: {'рано ☀️' if end.hour < 7 else 'идеально 🌞' if end.hour < 9 else 'поздно 😴'}"""

async def quality_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    quality = int(query.data[1])
    user_id = query.from_user.id
    sleep_id = context.user_data.get('last_sleep_id')
    
    if sleep_id:
        conn = sqlite3.connect('sleep_tracker.db')
        c = conn.cursor()
        
        # Обновляем оценку
        c.execute('UPDATE sleep_sessions SET quality = ? WHERE id = ?', (quality, sleep_id))
        conn.commit()
        
        # Получаем данные для AI анализа
        c.execute('SELECT sleep_start, sleep_end, duration FROM sleep_sessions WHERE id = ?', (sleep_id,))
        sleep_data = c.fetchone()
        
        if sleep_data:
            start_str, end_str, hours = sleep_data
            start_time = datetime.fromisoformat(start_str)
            end_time = datetime.fromisoformat(end_str)
            
            # Генерируем детальный анализ
            quality_emojis = ["😫", "😕", "😐", "😊", "😍"]
            quality_texts = ["Ужасно", "Плохо", "Нормально", "Хорошо", "Отлично"]
            
            # AI рекомендации для этого конкретного сна
            ai_tips = []
            if hours < 6:
                ai_tips.append("⚠️ Мало сна - организм не успевает восстановиться")
            elif hours > 10:
                ai_tips.append("⚠️ Слишком долгий сон может вызывать вялость")
            
            if start_time.hour >= 23:
                ai_tips.append("🌙 Позднее засыпание нарушает циркадные ритмы")
            
            if quality <= 2:
                ai_tips.append("💡 Попробуй: темную комнату, белый шум, комфортную температуру")
            elif quality >= 4:
                ai_tips.append("🌟 Отличный результат! Продолжай соблюдать режим")
            
            response = (
                f"{quality_emojis[quality-1]} **Оценка: {quality}/5** ({quality_texts[quality-1]})\n\n"
                f"🧠 **AI Анализ этого сна:**\n"
            )
            
            if ai_tips:
                response += "\n".join([f"• {tip}" for tip in ai_tips])
            else:
                response += "• Сон в пределах нормы\n• Продолжай отслеживать для лучшего анализа"
            
            response += f"\n\n💾 Данные сохранены. Для полного анализа используй '🧠 AI Анализ' через 3-5 записей."
        
        conn.close()
        
        await query.edit_message_text(response)
        await context.bot.send_message(
            chat_id=user_id,
            text="Используй кнопки ниже для продолжения:",
            reply_markup=main_menu()
        )
        
        # Очищаем данные
        context.user_data.pop('last_sleep_id', None)
        context.user_data.pop('sleep_start', None)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('sleep_tracker.db')
    c = conn.cursor()
    
    # Общая статистика
    c.execute('''
        SELECT 
            COUNT(*),
            AVG(duration),
            AVG(quality),
            MIN(duration),
            MAX(duration)
        FROM sleep_sessions 
        WHERE user_id = ? AND quality IS NOT NULL
    ''', (user_id,))
    
    stats = c.fetchone()
    
    if stats and stats[0] > 0:
        count, avg_hours, avg_quality, min_hours, max_hours = stats
        
        # AI анализ паттерна
        c.execute('''
            SELECT sleep_start, sleep_end, duration, quality
            FROM sleep_sessions 
            WHERE user_id = ? AND quality IS NOT NULL
            ORDER BY sleep_start DESC LIMIT 10
        ''', (user_id,))
        
        recent_data = c.fetchall()
        
        # Сохраняем для AI анализа
        pattern = sleep_ai.analyze_user_pattern(recent_data)
        
        message = f"📊 **Статистика сна**\n\n"
        message += f"📈 Всего записей: {count}\n"
        message += f"⏱️ Средняя длина: {avg_hours:.1f} ч\n"
        
        if avg_quality:
            message += f"⭐ Средняя оценка: {avg_quality:.1f}/5\n"
        
        message += f"📉 Минимум: {min_hours:.1f} ч\n"
        message += f"📈 Максимум: {max_hours:.1f} ч\n\n"
        
        message += f"🧠 **AI Распознал паттерн:** {pattern['name']}\n"
        message += f"📝 {pattern['desc']}\n\n"
        
        message += f"🔄 **Последние записи:**\n"
        
        for start_str, end_str, duration, quality in recent_data[:5]:
            start = datetime.fromisoformat(start_str)
            date_str = start.strftime('%d.%m %H:%M')
            quality_stars = "★" * quality if quality else "?"
            message += f"• {date_str} - {duration:.1f}ч ({quality_stars}/5)\n"
        
        # Сохраняем анализ в базу
        c.execute('''
            INSERT OR REPLACE INTO user_stats (user_id, sleep_pattern, last_analysis)
            VALUES (?, ?, ?)
        ''', (user_id, pattern['name'], datetime.now().isoformat()))
        conn.commit()
        
    else:
        message = "📭 **Нет данных для анализа**\n\n"
        message += "Чтобы получить статистику и AI-рекомендации:\n"
        message += "1. Отслеживай сон минимум 3 раза\n"
        message += "2. Оценивай качество после каждого сна\n"
        message += "3. Будь последователен в записях"
    
    conn.close()
    
    await update.message.reply_text(message, reply_markup=main_menu())

async def ai_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный AI анализ сна пользователя"""
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('sleep_tracker.db')
    c = conn.cursor()
    
    # Получаем данные для анализа
    c.execute('''
        SELECT sleep_start, sleep_end, duration, quality
        FROM sleep_sessions 
        WHERE user_id = ? AND quality IS NOT NULL
        ORDER BY sleep_start DESC LIMIT 20
    ''', (user_id,))
    
    sleep_data = c.fetchall()
    
    if len(sleep_data) >= 3:
        # Генерируем персонализированные рекомендации
        advice = sleep_ai.generate_personal_advice(user_id, sleep_data)
        
        # Получаем последний анализ из базы
        c.execute('SELECT sleep_pattern FROM user_stats WHERE user_id = ?', (user_id,))
        pattern_result = c.fetchone()
        
        if pattern_result:
            pattern_name = pattern_result[0]
            # Добавляем прогноз
            advice += f"\n\n🔮 **Прогноз AI:**\n"
            
            if "Идеальный" in pattern_name:
                advice += "• Продолжая такой режим, через месяц заметишь:\n"
                advice += "  - Повышение энергии на 30%\n"
                advice += "  - Улучшение концентрации\n"
                advice += "  - Лучшее настроение в течение дня"
            elif "Сова" in pattern_name:
                advice += "• Исправляя режим, через 2 недели:\n"
                advice += "  - Более легкое пробуждение\n"
                advice += "  - Улучшение качества сна\n"
                advice += "  - Больше продуктивных часов утром"
            elif "Жаворонок" in pattern_name:
                advice += "• Оптимизируя режим, ты получишь:\n"
                advice += "  - Стабильную энергию весь день\n"
                advice += "  - Лучшее восстановление\n"
                advice += "  - Укрепление иммунитета"
            else:
                advice += "• Стабилизируя режим, через 3 недели:\n"
                advice += "  - Исчезнет хроническая усталость\n"
                advice += "  - Улучшится память\n"
                advice += "  - Повысится общее самочувствие"
        
    else:
        advice = sleep_ai._get_general_advice()
    
    conn.close()
    
    await update.message.reply_text(advice, reply_markup=main_menu())

async def tips_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню советов"""
    keyboard = [
        [InlineKeyboardButton("🌙 Для засыпания", callback_data="tips_sleep")],
        [InlineKeyboardButton("🌅 Для пробуждения", callback_data="tips_wake")],
        [InlineKeyboardButton("📊 Для улучшения качества", callback_data="tips_quality")],
        [InlineKeyboardButton("🔄 Для режима", callback_data="tips_schedule")]
    ]
    
    await update.message.reply_text(
        "💡 **Выбери категорию советов:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def tips_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик советов"""
    query = update.callback_query
    await query.answer()
    
    tip_category = query.data
    
    tips = {
        'tips_sleep': """🌙 **Советы для легкого засыпания:**
        
1. 🛀 **Вечерний ритуал:** Теплая ванна за 1-2 часа до сна
2. 📚 **Без экранов:** Замени телефон книгой
3. 🌡️ **Температура:** 18-20°C - идеально для сна
4. 🍵 **Травяной чай:** Ромашка, мята, мелисса
5. 🧘 **Дыхание 4-7-8:** Вдох 4 сек, задержка 7, выдох 8
6. 🎵 **Белый шум:** Дождь, океан, вентилятор
7. 🌃 **Полная темнота:** Шторы blackout или маска для сна""",
        
        'tips_wake': """🌅 **Советы для легкого пробуждения:**
        
1. ☀️ **Свет:** Яркий свет сразу после пробуждения
2. 💧 **Вода:** Стакан воды комнатной температуры
3. 🏃 **Зарядка:** 5-10 мин легкой зарядки
4. 🎶 **Музыка:** Бодрая музыка для настроения
5. 🕒 **Постепенно:** Будильник за 10 мин до реального подъема
6. 🍋 **Аромат:** Цитрусовые или мятные ароматы
7. 🥶 **Прохлада:** Умойся прохладной водой""",
        
        'tips_quality': """📊 **Советы для улучшения качества сна:**
        
1. 🛌 **Поза:** Спи на боку или спине
2. 🧹 **Чистота:** Регулярно меняй постельное белье
3. 🌬️ **Воздух:** Проветривай комнату перед сном
4. 🔊 **Тишина:** Беруши при необходимости
5. 🍽️ **Ужин:** Легкий, за 3 часа до сна
6. 🚫 **Кофеин:** Никакого после 15:00
7. 📵 **Гаджеты:** Режим "Не беспокоить" на ночь""",
        
        'tips_schedule': """🔄 **Советы для стабильного режима:**
        
1. ⏰ **Фиксированное время:** +/- 30 мин каждый день
2. 🌞 **Солнце:** Утренний свет помогает настроить биоритмы
3. 🏋️ **Спорт:** Завершай тренировки за 3 часа до сна
4. 📅 **План:** Распиши день для снижения стресса
5. 🧠 **Медитация:** 10 мин перед сном для расслабления
6. 📝 **Дневник:** Записывай мысли перед сном
7. 🔄 **Выходные:** Разница во времени сна не более 1 часа"""
    }
    
    await query.edit_message_text(
        tips.get(tip_category, "Выбери категорию советов"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Назад к меню", callback_data="back_to_tips")
        ]])
    )

async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    week_ago = datetime.now() - timedelta(days=7)
    
    conn = sqlite3.connect('sleep_tracker.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT sleep_start, duration, quality
        FROM sleep_sessions 
        WHERE user_id = ? 
        AND DATE(sleep_start) >= DATE(?)
        AND quality IS NOT NULL
        ORDER BY sleep_start
    ''', (user_id, week_ago.isoformat()))
    
    records = c.fetchall()
    conn.close()
    
    if records:
        total_hours = sum(r[1] for r in records)
        avg_quality = sum(r[2] for r in records) / len(records)
        
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        
        message = "📈 **Отчет за неделю**\n\n"
        message += "День      Сон        Качество\n"
        message += "―" * 35 + "\n"
        
        for start_str, duration, quality in records:
            start = datetime.fromisoformat(start_str)
            weekday = weekdays[start.weekday()]
            date_str = start.strftime(f"{weekday} %d.%m")
            
            # График
            bars = "█" * min(int(duration), 10)
            stars = "★" * quality
            
            message += f"{date_str:12} {duration:.1f}ч {bars:10} {stars}\n"
        
        message += f"\n📊 **Итоги недели:**\n"
        message += f"• Записей: {len(records)}\n"
        message += f"• Всего часов: {total_hours:.1f}\n"
        message += f"• Средняя оценка: {avg_quality:.1f}/5\n"
        
        # AI оценка недели
        if avg_quality >= 4:
            message += f"\n🌟 **AI Оценка:** Отличная неделя! Продолжай так!"
        elif avg_quality >= 3:
            message += f"\n👍 **AI Оценка:** Хорошая неделя. Есть куда расти!"
        else:
            message += f"\n⚠️ **AI Оценка:** Нужно работать над качеством сна"
        
    else:
        message = "📭 **За неделю нет данных**\n\n"
        message += "Начни отслеживать сон, чтобы видеть отчеты!\n"
        message += "Достаточно 3-5 дней для первого анализа."
    
    await update.message.reply_text(message, reply_markup=main_menu())

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "😴 Начать сон":
        await start_sleep(update, context)
    elif text == "⏰ Закончить сон":
        await end_sleep(update, context)
    elif text == "📊 Статистика":
        await show_stats(update, context)
    elif text == "📈 Отчет":
        await weekly_report(update, context)
    elif text == "🧠 AI Анализ":
        await ai_analysis(update, context)
    elif text == "💡 Советы":
        await tips_menu(update, context)
    else:
        await update.message.reply_text("Используй кнопки ниже:", reply_markup=main_menu())

async def back_to_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться к меню советов"""
    query = update.callback_query
    await query.answer()
    await tips_menu(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

def main():
    # Инициализация
    init_db()
    
    print("🚀 Запуск AI бота для анализа сна...")
    print("🧠 ИИ-анализатор инициализирован")
    print("📊 База данных готова")
    
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    app.add_handler(CallbackQueryHandler(quality_handler, pattern="^q[1-5]$"))
    app.add_handler(CallbackQueryHandler(tips_handler, pattern="^tips_"))
    app.add_handler(CallbackQueryHandler(back_to_tips, pattern="^back_to_tips$"))
    app.add_error_handler(error_handler)
    
    print("\n✅ **Бот запущен!**")
    print("🤖 **Функции:**")
    print("  • 🧠 AI анализ паттернов сна")
    print("  • 📊 Персонализированные рекомендации")
    print("  • 📈 Подробная статистика")
    print("  • 💡 Умные советы по категориям")
    print("\n📱 Иди в Telegram и пиши /start")
    print("⏹️ Ctrl+C для остановки")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()