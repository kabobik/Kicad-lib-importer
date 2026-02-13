# Git Integration Plugin for KiCad Libraries

Плагин для KiCad, позволяющий управлять библиотеками через Git прямо из редактора PCB.

## Возможности

- **Pull / Push / Commit** — базовые Git-операции одной кнопкой
- **Автоматический Fetch** — периодическая проверка обновлений на сервере
- **SSH Setup** — генерация ключей, настройка `~/.ssh/config`, проверка соединения
- **First-run Wizard** — автоматическая настройка при первом запуске
- **Индикация статуса** — ветка, ahead/behind, количество изменённых файлов
- **Совместимость** — Forgejo, Gitea, GitLab, GitHub

## Установка

### 1. Скопировать плагин

```bash
# Linux
cp -r git_integration/ ~/.local/share/kicad/8.0/scripting/plugins/git_integration/

# Windows
# Скопировать папку git_integration в:
# %APPDATA%\kicad\8.0\scripting\plugins\

# macOS
# ~/Library/Preferences/kicad/8.0/scripting/plugins/
```

### 2. Сгенерировать иконку (опционально)

```bash
cd ~/.local/share/kicad/8.0/scripting/plugins/git_integration/
python3 create_icon.py
```

### 3. Перезапустить KiCad

Плагин появится в меню **Tools → External Plugins → Git Integration for KiCad Libraries**.

## Быстрый старт

1. Откройте плагин из меню KiCad
2. При первом запуске автоматически откроется мастер настройки
3. Укажите:
   - Адрес сервера (например: `git.example.com`)
   - Путь к локальному репозиторию с библиотеками
4. Сгенерируйте SSH-ключ и добавьте публичный ключ на сервер
5. Проверьте соединение кнопкой «Проверить соединение»
6. Используйте кнопки Pull / Commit / Push

## Интерфейс

```
┌─────────────────────────────────────────────────┐
│  Git Integration for KiCad Libraries            │
├─────────────────────────────────────────────────┤
│  [main]  ⬇0 ⬆1    2 изменено, 0 новых   ↻ ... │
├─────────────────────────────────────────────────┤
│  [Pull] [Commit (2)] [Push ⬆1] [Status]        │
├─────────────────────────────────────────────────┤
│  Output:                                        │
│  ┌─────────────────────────────────────────────┐│
│  │ [14:30:05] Fetch OK.                        ││
│  │ [14:30:06] --- git status ---               ││
│  │ [14:30:06] Modified: lib1.kicad_sym         ││
│  └─────────────────────────────────────────────┘│
├─────────────────────────────────────────────────┤
│  [⚙ Settings] [🔑 SSH Setup]        [? Help]   │
└─────────────────────────────────────────────────┘
```

## Конфигурация (config.ini)

Файл `config.ini` находится рядом с плагином и содержит:

```ini
[server]
host = git.example.com     # Адрес Git-сервера
port = 22                  # SSH порт
user = git                 # SSH пользователь

[repository]
path = /home/user/libs     # Путь к локальному репозиторию

[ssh]
key_path = ~/.ssh/kicad_forgejo_ed25519   # Путь к SSH ключу

[fetch]
interval_sec = 300         # Интервал автоматического fetch (секунды, мин. 10)
timeout_sec = 10           # Таймаут сетевых операций
```

## Решение проблем

### «Git не найден»
Установите Git:
```bash
# Ubuntu/Debian
sudo apt install git

# Fedora
sudo dnf install git

# Windows — скачайте с https://git-scm.com/
```

### «Push заблокирован — отстаёт от сервера»
Сначала выполните **Pull**, чтобы получить обновления с сервера, затем повторите **Push**.

### «Есть незакоммиченные изменения. Сделайте Commit перед Pull»
Зафиксируйте свои изменения кнопкой **Commit** перед выполнением **Pull**.

### «Доступ запрещён (Permission denied)»
1. Откройте **SSH Setup**
2. Скопируйте публичный ключ
3. Добавьте его на сервер (Forgejo → Settings → SSH Keys → Add Key)
4. Нажмите «Проверить соединение»

### «Обнаружены конфликты слияния»
Разрешите конфликты вручную в текстовом редакторе, затем выполните в терминале:
```bash
cd /path/to/repo
git add .
git commit -m "Resolved merge conflicts"
```

### «Сервер недоступен (таймаут)»
- Проверьте сетевое подключение
- Проверьте правильность адреса сервера в Settings
- Увеличьте `timeout_sec` в config.ini если сервер медленный

### Лог-файл
Подробный лог записывается в `~/.kicad_git_plugin.log`.

## Структура файлов

```
git_integration/
├── __init__.py          # Регистрация плагина в KiCad
├── main.py              # Точка входа (ActionPlugin)
├── config_service.py    # Чтение/запись config.ini
├── git_service.py       # Git-операции через subprocess
├── ssh_service.py       # SSH-ключи и ~/.ssh/config
├── ui.py                # wxPython диалоги
├── config.ini           # Настройки плагина
├── create_icon.py       # Генератор иконки
├── icon.png             # Иконка плагина (24×24)
└── README.md            # Эта документация
```

## Требования

- KiCad 8.0+
- Python 3.6+
- Git
- OpenSSH (для SSH-ключей)

## Лицензия

MIT
