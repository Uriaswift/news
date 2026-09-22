# Hermes News

Персональный сборщик Telegram-каналов и новостных дайджестов для Windows и Linux.
Сборщик читает подписки вашего Telegram-аккаунта. Ollama объединяет новости,
бот публикует результат в выбранный канал. Новые сообщения сохраняются в SQLite.

## Возможности

Заголовок: время Москвы и Екатеринбурга, USD/RUB, EUR/RUB, BTC/USD.
Для курса ЦБ предусмотрен резервный источник cbr-xml-daily.ru.
Короткая новость с фото публикуется одним сообщением с полной подписью.

- Один сервис запускает сборщик и обработку дайджестов; перезапускает упавшие процессы.
- При старте и каждые пять минут сборщик восстанавливает пропущенные посты.
- Сохранённая очередь отправляется до обращения к модели. Каждая отправленная часть
  имеет отдельную отметку: повторный запуск продолжает незаконченный дайджест.
- Неоднозначный ответ Telegram требует проверки конкретной части; приложение
  не повторяет её вслепую. Ошибки API не выводят токен бота в журнал.
- Длинный текст разбивается до HTML-экранирования. Ссылки на источники сохраняются.
- База создаётся и обновляется автоматически. История не сбрасывается.
- Очистка и определение рекламы выполняются только для новых сообщений.
- Тяжёлая модель embeddings необязательна; по умолчанию дубли объединяет Ollama.
- Логи нового сервиса ограничены 5 МБ на файл и тремя резервными копиями.

## Требования и настройки

Python 3.11+, доступ к Telegram и работающая Ollama. Зависимости зафиксированы
в `requirements.txt`. `.env` загружается из папки приложения независимо от места запуска.

Скопируйте `.env.example` в `.env` и заполните:

- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` — для чтения каналов.
- `TELEGRAM_BOT_TOKEN` — токен бота.
- `TELEGRAM_CHANNEL_ID` — целевой канал, например `@your_channel` или числовой ID.
  Бот должен быть администратором с разрешением публикации.
- `HERMES_DATA_DIR` — папка данных; относительный путь считается от папки приложения.
- `OLLAMA_HOST`, `OLLAMA_MODEL` — адрес Ollama и установленная модель.

`glm-5.3-flash:cloud` — модель прежней установки. На новом сервере нужен доступ
к этой модели и авторизация Ollama для cloud, либо другая доступная модель с JSON-ответами.
Сначала выполните `ollama pull <модель>`, при необходимости `ollama signin`.
Сам сервис не устанавливает и не запускает Ollama: настройте её как отдельный сервис.
Если Ollama недоступна, готовая очередь отправляется, создание новых дайджестов повторяется.

`HERMES_INTERVAL_SECONDS=3600` задаёт паузу после успешной обработки.
Один запуск обрабатывает не более часа накопившихся событий. При большом простое
можно несколько раз выполнить `pipeline`, чтобы разобрать очередь быстрее.
`HERMES_EMBEDDINGS=1` включает прежнюю семантическую кластеризацию; для неё
установите `requirements-embeddings.txt`. Этот режим требует существенно больше памяти.

## Windows

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Заполните .env
.\.venv\Scripts\python.exe hermes.py init
.\.venv\Scripts\python.exe hermes.py login
.\.venv\Scripts\python.exe hermes.py run
```

`start.cmd` запускает сервис в фоне, `stop.cmd` останавливает его.
В уже исправленной установке `C:\hermes-news` используется `.venv-portable`.
Это локальное окружение; копировать его на Linux нельзя.

Для автозапуска при входе в Windows используйте `setup_windows.ps1 -Autostart`.
Перед переходом со старой версии отключите старые задачи Hermes Collector,
Hourly Pipeline и Watchdog в Планировщике заданий, остановите их процессы.
Одновременный запуск старой версии и новой не поддерживается.
Новая версия защищена от двух экземпляров собственными блокировками.

## Linux / systemd

Пример для Debian/Ubuntu; команды установки пакетов и службы выполняются с sudo.

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv git
sudo useradd --system --create-home --home-dir /var/lib/hermes --shell /usr/sbin/nologin hermes
sudo git clone https://github.com/Uriaswift/news.git /opt/hermes-news
sudo chown -R hermes:hermes /opt/hermes-news
sudo -u hermes python3 -m venv /opt/hermes-news/.venv
sudo -u hermes /opt/hermes-news/.venv/bin/python -m pip install -r /opt/hermes-news/requirements.txt
sudo -u hermes cp /opt/hermes-news/.env.example /opt/hermes-news/.env
# Заполните .env. Рекомендуем HERMES_DATA_DIR=/var/lib/hermes/data
sudo chmod 600 /opt/hermes-news/.env
sudo -u hermes /opt/hermes-news/.venv/bin/python /opt/hermes-news/hermes.py init
sudo -u hermes /opt/hermes-news/.venv/bin/python /opt/hermes-news/hermes.py login
sudo cp /opt/hermes-news/deploy/hermes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hermes
sudo systemctl status hermes
```

Диагностика: `journalctl -u hermes -n 100` и `python hermes.py status --network`.
Измените пути и `User` в unit-файле, если выбрали другую установку.

## Перенос существующих данных

1. Остановите старое и новое приложение на Windows и отключите старые задачи.
2. Скопируйте папку `HERMES_DATA_DIR` целиком: `db`, `media`, `sessions` и,
   если используются, `embeddings`. Копируйте SQLite после остановки процессов,
   включая имеющиеся `-wal` и `-shm`, либо используйте SQLite backup.
3. Передайте `.env` отдельно от Git, измените Windows-путь `HERMES_DATA_DIR` на Linux-путь.
4. Сессия находится в `sessions/news_collector.session`. При первом запуске новая версия
   автоматически импортирует старую `news_collector.session` из корня приложения.
   Если сессию не переносите, выполните `hermes.py login` на сервере.
5. Назначьте владельца папки данных пользователю `hermes`. Запустите `init`, затем сервис.

Абсолютные старые пути медиа вида `D:\hermes-data\media\photos\...` разрешаются
относительно новой папки `media`; редактировать SQLite вручную не требуется.
Токены, сессии, база, фотографии и виртуальные окружения исключены из Git.

## Управление

```text
python hermes.py init             создать/обновить базу
python hermes.py login            интерактивный вход Telegram (код и 2FA)
python hermes.py run              сборщик + периодическая обработка
python hermes.py stop             остановить сервис
python hermes.py pipeline         обработать очередной период и отправить
python hermes.py send             отправить сохранённую очередь
python hermes.py status --network база, heartbeat, очередь, Telegram, Ollama
```

`status` завершается с ненулевым кодом при отсутствии heartbeat или проблемах.
Время последней входящей новости и время последнего отправленного дайджеста
показываются отдельно; отсутствие новых новостей не доказывает исправность сборщика.

Если Telegram принял сообщение, но соединение оборвалось до ответа, невозможно
автоматически установить факт доставки через Bot API. Приложение покажет ID дайджеста
и номер части. Посмотрите канал и выполните одну из команд:

```text
python hermes.py resolve-delivery 11 0 --result sent
python hermes.py resolve-delivery 11 0 --result retry
python hermes.py send
```

`sent` подтверждает уже увиденное сообщение; `retry` разрешает повтор, если его нет.
Без проверки не используйте `retry`: это может создать дубль.

## Проверки

```bash
python -m pip check
python -m unittest discover -s tests -v
```

Тесты работают на временной базе с подменённым Telegram API. Они не отправляют
сообщения и не читают рабочую сессию. GitHub Actions проверяет Windows/Linux,
Python 3.11/3.12 после отправки кода в репозиторий.
