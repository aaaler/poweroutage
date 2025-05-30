import os
import time
import logging
import sqlite3
import requests
from bs4 import BeautifulSoup

# --- Configuration from Environment Variables ---
# Значения по умолчанию на случай, если переменные окружения не установлены
SLEEP_SECONDS = int(os.getenv('SLEEP_SECONDS', '3600'))  # Пауза в секундах
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_IDS_STR = os.getenv('TELEGRAM_CHAT_IDS') # ID чатов через запятую
DB_PATH = os.getenv('DB_PATH', 'cache/outages.db')
TARGET_URL = os.getenv(
    'TARGET_URL',
    'https://rosseti-lenenergo.ru/planned_work/?reg=&city=%D0%92%D0%B0%D1%81%D0%BA%D0%B5%D0%BB%D0%BE%D0%B2%D0%BE&date_start=&date_finish=&res=&street=%D0%A2%D1%80%D0%BE%D0%B8%D1%86%D0%BA%D0%BE%D0%B5'
)

# --- Logging Setup ---
log_level = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Telegram Chat IDs ---
if TELEGRAM_CHAT_IDS_STR:
    TELEGRAM_CHAT_IDS = [chat_id.strip() for chat_id in TELEGRAM_CHAT_IDS_STR.split(',')]
else:
    TELEGRAM_CHAT_IDS = []
    if TELEGRAM_BOT_TOKEN: # Если есть токен, но нет ID, это странно
        logger.warning("TELEGRAM_BOT_TOKEN is set, but TELEGRAM_CHAT_IDS is empty. Notifications will not be sent.")

# --- Database Functions ---
def init_db():
    """Инициализирует базу данных и создает таблицу, если она не существует."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS outages (
                    data_record_id TEXT PRIMARY KEY,
                    address TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    comment TEXT,
                    fias TEXT,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            logger.info(f"База данных '{DB_PATH}' инициализирована.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при инициализации БД: {e}")
        raise

def is_record_new(conn, data_record_id):
    """Проверяет, существует ли запись с данным data_record_id в БД."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM outages WHERE data_record_id = ?", (data_record_id,))
        return cursor.fetchone() is None
    except sqlite3.Error as e:
        logger.error(f"Ошибка при проверке записи {data_record_id} в БД: {e}")
        return False # Лучше считать, что запись не новая, чтобы избежать дублей уведомлений

def add_record(conn, record_data):
    """Добавляет новую запись об отключении в БД."""
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO outages (data_record_id, address, start_time, end_time, comment, fias)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            record_data['data_record_id'],
            record_data['address'],
            record_data['start_time'],
            record_data['end_time'],
            record_data['comment'],
            record_data['fias']
        ))
        conn.commit()
        logger.info(f"Запись {record_data['data_record_id']} добавлена в БД.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при добавлении записи {record_data['data_record_id']} в БД: {e}")

# --- Telegram Notification Function ---
def send_telegram_notification(record_data):
    """Отправляет уведомление в Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        logger.warning("Токен бота или ID чатов не настроены. Уведомление не отправлено.")
        return

    message_template = (
        "Новое плановое отключение электроэнергии на сайте rosseti-lenenergo.ru.\n"
        "С {start_time} по {end_time} планируются отключения электричества по адресам: \n"
        "{address}"
        "{comment}"
    )
    message = message_template.format(
        start_time=record_data['start_time'],
        end_time=record_data['end_time'],
        address=record_data['address'],
        comment=record_data['comment']
    )

    for chat_id in TELEGRAM_CHAT_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown' # Или HTML, если нужно форматирование
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            response_data = response.json()
            if response.status_code == 200 and response_data.get("ok"):
                logger.info(f"Уведомление успешно отправлено в чат {chat_id} для записи {record_data['data_record_id']}.")
            else:
                logger.error(
                    f"Ошибка отправки уведомления в чат {chat_id} для записи {record_data['data_record_id']}: "
                    f"Статус {response.status_code}, Ответ: {response_data.get('description', response.text)}"
                )
            if DEBUG:
                logger.debug(f"Telegram request payload: {payload}")
                logger.debug(f"Telegram response status: {response.status_code}, body: {response.text}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при отправке запроса в Telegram для чата {chat_id}: {e}")

# --- Main Logic ---
def fetch_and_process_outages():
    """Загружает страницу, парсит данные и обрабатывает их."""
    logger.info(f"Запрашиваю данные с {TARGET_URL}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=30, verify=False)
        if DEBUG:
            logger.debug(f"HTTP Запрос: METHOD={response.request.method}, URL={response.request.url}")
            logger.debug(f"HTTP Запрос Headers: {response.request.headers}")
            if response.request.body:
                logger.debug(f"HTTP Запрос Body: {response.request.body}")

        response.raise_for_status() # Проверка на HTTP ошибки (4xx, 5xx)

        if DEBUG:
            logger.debug(f"HTTP Ответ: STATUS={response.status_code}")
            logger.debug(f"HTTP Ответ Headers: {response.headers}")
            logger.debug(f"HTTP Ответ Body (первые 3500 символов):\n{response.text[:3500]}...")

        logger.info("Страница успешно загружена. Начинаю парсинг.")
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ищем таблицу с классом 'items table table-hover'
        # Обычно данные находятся внутри <tbody>
        table = soup.find('table', class_='tableous_facts funds')
        if not table:
            logger.warning("Таблица с отключениями не найдена на странице.")
            return

        tbody = table.find('tbody')
        if not tbody:
            logger.warning("Тело таблицы (tbody) не найдено.")
            return

        rows = tbody.find_all('tr')
        if not rows:
            logger.info("Плановых отключений не найдено.")
            return

        logger.info(f"Найдено {len(rows)} строк с данными об отключениях.")
        new_outages_found = 0

        with sqlite3.connect(DB_PATH) as conn:
            for row in rows:
                data_record_id = row.get('data-record-id')
                if not data_record_id:
                    logger.warning("Найден tr без data-record-id, пропускаю.")
                    continue

                cols = row.find_all('td')
                if len(cols) < 10: # Ожидаем как минимум 10 колонoк
                    logger.warning(f"В строке {data_record_id} меньше 10 ячеек (td), пропускаю. Найдено: {len(cols)}")
                    continue

                # Извлекаем данные, предполагая следующий порядок колонок:
                # 2: Адрес
                # 3-4: Плановое время начала
                # 5-6: Плановое время восстановления (окончания)
                # 9: комментарий
                # 10: ФИАС
                # (Индексы могут потребовать корректировки, если структура сайта изменится)
                address = cols[2].get_text(separator='\n').strip().replace("\n \n", "\n").replace("\n\n", "\n").replace("  ", " ")
                start_time = cols[3].text.strip() + " " + cols[4].text.strip()
                end_time = cols[5].text.strip() + " " + cols[6].text.strip()
                comment = cols[9].text.strip()
                fias = cols[10].get_text(separator=',').strip()

                record_data = {
                    'data_record_id': data_record_id,
                    'address': address,
                    'start_time': start_time,
                    'end_time': end_time,
                    'comment': comment,
                    'fias': fias
                }

                if DEBUG:
                    logger.debug(f"Разобранная запись: {record_data}")

                if is_record_new(conn, data_record_id):
                    logger.info(f"Найдена новая запись: {data_record_id}. Адрес: {address}")
                    add_record(conn, record_data)
                    send_telegram_notification(record_data)
                    new_outages_found += 1
                else:
                    if DEBUG: # Чтобы не спамить в обычном режиме
                         logger.debug(f"Запись {data_record_id} уже существует в БД.")


        if new_outages_found > 0:
            logger.info(f"Обработано {new_outages_found} новых отключений.")
        else:
            logger.info("Новых отключений не обнаружено.")

    except requests.exceptions.Timeout:
        logger.error(f"Тайм-аут при запросе к {TARGET_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к {TARGET_URL}: {e}")
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка: {e}", exc_info=DEBUG)


if __name__ == "__main__":
    # Проверка обязательных переменных для Telegram
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Переменная окружения TELEGRAM_BOT_TOKEN не установлена. Уведомления в Telegram не будут работать.")
    if not TELEGRAM_CHAT_IDS:
        logger.warning("Переменная окружения TELEGRAM_CHAT_IDS не установлена или пуста. Уведомления в Telegram не будут работать.")

    logger.info(f"Скрипт запущен. Режим DEBUG: {DEBUG}. Пауза между циклами: {SLEEP_SECONDS} сек.")
    init_db() # Инициализируем БД один раз при старте

    try:
        while True:
            fetch_and_process_outages()
            logger.info(f"Цикл завершен. Следующий запуск через {SLEEP_SECONDS} секунд.")
            time.sleep(SLEEP_SECONDS)
    except KeyboardInterrupt:
        logger.info("Работа скрипта прервана пользователем.")
    except Exception as e:
        logger.critical(f"Критическая ошибка в главном цикле: {e}", exc_info=True)
    finally:
        logger.info("Скрипт завершает работу.")

