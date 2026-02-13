# KiCad Library Panel — Git-панель для библиотек в Project Manager

## Обзор

Отдельная wxAUI-панель для управления Git-репозиторием **глобальной библиотеки** 
прямо из главного окна KiCad (Project Manager).

```
┌────────────────────────────────────────────────────┐
│  KiCad Project Manager                             │
├──────────────┬─────────────────────────────────────┤
│ Project Files│                                     │
│ 📁 test/     │   [PCB Editor] [Schema Editor]      │
│  ├ .sch      │                                     │
│  └ .pcb      │                                     │
├──────────────┤                                     │
│ Library [main]                                     │
│ ⬇ Pull │ ✔ Commit │ ⬆ Push │ 🔄 │ ⚙             │
│ 📁 Lib/      │                                     │
│  ├ 🟢 Caps.. │   Changes: 2 modified, 1 added     │
│  ├ 🟡 IC...  │                                     │
│  └ 🟢 Conn.. │                                     │
└──────────────┴─────────────────────────────────────┘
```

## Файлы

| Файл | Описание |
|------|----------|
| `library_tree_panel.h` | Заголовок — класс `LIBRARY_TREE_PANEL` |
| `library_tree_panel.cpp` | Реализация — UI, дерево файлов, git-операции |
| `integration_patch.diff` | Патч для интеграции в KiCad Manager Frame |
| `README.md` | Этот файл |

## Архитектура

### LIBRARY_TREE_PANEL (wxPanel)

```
┌─────────────────────────────┐
│ Header: "Library:" [main]   │  ← wxStaticText с именем ветки
├─────────────────────────────┤
│ [⬇Pull][✔Commit][⬆Push]   │  ← wxToolBar
│ [🔄Refresh][⚙Settings]     │
├─────────────────────────────┤
│ 📁 Lib/                    │  ← wxTreeCtrl с state images (git-статусы)
│  ├ 🟢 Capacitors.kicad_sym │
│  ├ 🟡 IC.kicad_sym         │ 
│  └ 📁 Footprints/          │
│     └ 🟢 Caps.pretty       │
├─────────────────────────────┤
│ Changes: 1 modified         │  ← wxStaticText (строка статуса)
└─────────────────────────────┘
```

### Зависимости от KiCad

Использует **существующую** Git-инфраструктуру KiCad:

- `KIGIT_COMMON` — базовый класс работы с git-репозиторием
- `GIT_PUSH_HANDLER`, `GIT_PULL_HANDLER` — push/pull через libgit2
- `DIALOG_GIT_COMMIT` — диалог коммита с выбором файлов
- `DIALOG_GIT_REPOSITORY` — настройка remote/auth
- `WX_PROGRESS_REPORTER` — прогресс-бар
- `credentials_cb` — callback аутентификации (SSH/HTTPS)

### Отличия от PROJECT_TREE_PANE

| | PROJECT_TREE_PANE | LIBRARY_TREE_PANEL |
|---|---|---|
| Привязка | Папка проекта (.kicad_pro) | Любая папка (настраивается) |
| Git-объект | Один на всё дерево | Свой, независимый |
| Фильтр файлов | Все файлы проекта | Только файлы библиотек |
| Тулбар Git | Нет (только контекстное меню) | Есть (Pull/Commit/Push) |
| Инициализация | При открытии проекта | Ручная через Settings |

## Как интегрировать в KiCad

### Требования

- KiCad 9.0+ исходники
- CMake, GCC/Clang
- libgit2-dev, libssh2-dev, wxWidgets

### Шаги

1. **Скопировать файлы** в `kicad/kicad/`:
   ```bash
   cp library_tree_panel.h  /path/to/kicad/kicad/
   cp library_tree_panel.cpp /path/to/kicad/kicad/
   ```

2. **Применить патч** из `integration_patch.diff`:
   - Добавить `#include` и `LIBRARY_TREE_PANEL*` в `kicad_manager_frame.h`
   - Создать панель и добавить в wxAUI в `kicad_manager_frame.cpp`
   - Добавить `library_tree_panel.cpp` в `CMakeLists.txt`

3. **Добавить настройку** в `PROJECT_LOCAL_SETTINGS`:
   ```cpp
   wxString m_LibraryGitPath;  // Путь к библиотечному репозиторию
   ```

4. **Собрать**:
   ```bash
   cd /path/to/kicad/build
   cmake --build . --target kicad -j$(nproc)
   ```

### Без сборки KiCad

Если пересборка KiCad нежелательна — используйте **Python-плагин** 
из `Git Integration Plugin for KiCad Libraries/git_integration/`.
Он работает через pcbnew ActionPlugin и не требует компиляции.

## Фичи

- ✅ Дерево файлов библиотеки с фильтрацией по типам (.kicad_sym, .kicad_mod, etc.)
- ✅ Git-маркеры статуса (8 состояний: current, modified, added, deleted, etc.)
- ✅ Кнопки Pull / Commit / Push на тулбаре
- ✅ Контекстное меню с git-операциями
- ✅ Автоматический fetch по таймеру (60 сек)
- ✅ Обновление статусов по таймеру (500 мс)
- ✅ Отображение текущей ветки
- ✅ Счётчик изменений в строке статуса
- ✅ Диалог настройки репозитория (через KiCad DIALOG_GIT_REPOSITORY)
- ✅ Поддержка SSH и HTTPS аутентификации

## Оценка сложности интеграции

| Задача | Файлов | Строк |
|--------|--------|-------|
| Новый код (panel) | 2 | ~650 |
| Патч kicad_manager_frame | 2 | ~20 |
| Патч CMakeLists.txt | 1 | ~1 |
| Патч PROJECT_LOCAL_SETTINGS | 2 | ~10 |
| **Итого** | **7** | **~680** |

Время интеграции: ~1-2 часа при наличии собранного KiCad из исходников.

## Лицензия

GPL-3.0+ (совместимо с KiCad)
