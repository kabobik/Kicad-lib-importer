# Подзадача 3: UI и команды копирования в KiCad 9.0.7

**Дата исследования:** 11 февраля 2026  
**Версия KiCad:** 9.0.7  
**Директория исследования:** `/home/anton/VsCode/kicad-research/kicad`

---

## Секция 1: Все способы копирования

| Способ вызова | Модуль | Файл | Функция | Строка | Тип | Горячая клавиша |
|---|---|---|---|---|---|---|
| Меню Edit → Cut | pcbnew | `pcbnew/menubar_pcb_editor.cpp` | `doReCreateMenuBar()` | 196 | Меню | Ctrl+X |
| Меню Edit → Copy | pcbnew | `pcbnew/menubar_pcb_editor.cpp` | `doReCreateMenuBar()` | 197 | Меню | Ctrl+C |
| Меню Edit → Paste | pcbnew | `pcbnew/menubar_pcb_editor.cpp` | `doReCreateMenuBar()` | 198 | Меню | Ctrl+V |
| Меню Edit → Paste Special | pcbnew | `pcbnew/menubar_pcb_editor.cpp` | `doReCreateMenuBar()` | 199 | Меню | Ctrl+Shift+V |
| Горячая клавиша Ctrl+C | pcbnew | `pcbnew/tools/edit_tool.cpp` | `copyToClipboard()` | 3342 | Команда | Ctrl+C → ACTIONS::copy |
| Меню "Copy with Reference..." | pcbnew | `pcbnew/tools/edit_tool.cpp` | `copyToClipboard()` | 3390 | Специальная | Нет (интерактивное) |
| Контекстное меню (выделение) | pcbnew | `pcbnew/tools/edit_tool.cpp` | Контекстное меню | 138 | Контекстное меню | (через меню) |

---

## Секция 2: Регистрация команд

### 2.1 Основные команды (ACTIONS)

Команды определены в `include/tool/actions.h` и автоматически доступны во всех модулях через `ACTIONS::copy`, `ACTIONS::cut`, `ACTIONS::paste`.

**Файл:** `include/tool/actions.h`
```cpp
// Базовые команды редактирования (определены в ACTIONS::)
static TOOL_ACTION copy;       // Ctrl+C
static TOOL_ACTION cut;        // Ctrl+X
static TOOL_ACTION paste;      // Ctrl+V
static TOOL_ACTION pasteSpecial; // Ctrl+Shift+V
```

### 2.2 Специализированные команды PCBNew

**Файл:** `pcbnew/tools/pcb_actions.h` (строка 129)
```cpp
static TOOL_ACTION copyWithReference;  // Интерактивное копирование с выбором точки
```

**Файл:** `pcbnew/tools/pcb_actions.cpp` (строки 481-489)
```cpp
TOOL_ACTION PCB_ACTIONS::copyWithReference( TOOL_ACTION_ARGS()
        .Name( "pcbnew.InteractiveMove.copyWithReference" )
        .Scope( AS_GLOBAL )
        .FriendlyName( _( "Copy with Reference" ) )
        .Tooltip( _( "Copy selected item(s) to clipboard with a specified starting point" ) )
        .Icon( BITMAPS::copy )
        .Flags( AF_ACTIVATE ) );
```

### 2.3 Регистрация команд в меню (PCBNew)

**Файл:** `pcbnew/menubar_pcb_editor.cpp` (строки 188-200)
```cpp
//-- Edit menu --------------------------------------------------
//
ACTION_MENU* editMenu = new ACTION_MENU( false, selTool );

editMenu->Add( ACTIONS::undo );
editMenu->Add( ACTIONS::redo );

editMenu->AppendSeparator();
editMenu->Add( ACTIONS::cut );        // Меню Edit → Cut
editMenu->Add( ACTIONS::copy );       // Меню Edit → Copy
editMenu->Add( ACTIONS::paste );      // Меню Edit → Paste
editMenu->Add( ACTIONS::pasteSpecial ); // Меню Edit → Paste Special
editMenu->Add( ACTIONS::doDelete );
```

### 2.4 Регистрация в контекстном меню

**Файл:** `pcbnew/tools/edit_tool.cpp` (строки 135-145)
```cpp
menu->AddItem( PCB_ACTIONS::copyWithReference,
               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
menu->AddItem( ACTIONS::copy,
               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
menu->AddItem( ACTIONS::cut,
               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
menu->AddItem( ACTIONS::paste,
               SELECTION_CONDITIONS::ShowAlways );
```

---

## Секция 3: Граф вызовов (Call Graph)

### 3.1 Маршрут Ctrl+C → SaveSelection()

```
Пользователь нажимает Ctrl+C
    ↓
Tool Event System (TOOL_MANAGER)
    ↓
EDIT_TOOL::copyToClipboard() [pcbnew/tools/edit_tool.cpp:3342]
    ├─ if ( aEvent.IsAction(&PCB_ACTIONS::copyWithReference) )
    │   └─ pickReferencePoint() [интерактивный выбор точки]
    │       └─ refPoint = [координата, выбранная пользователем]
    │
    └─ else
        └─ refPoint = grid.BestDragOrigin() [автоматический выбор]
            ↓
selection.SetReferencePoint( refPoint )
    ↓
CLIPBOARD_IO::SaveSelection( selection ) [pcbnew/kicad_clipboard.cpp:126]
    ├─ Move(-refPoint) [нормализация координат]
    └─ Write to wxClipboard
```

### 3.2 Регистрация команды в Tool Manager

**Файл:** `pcbnew/tools/edit_tool.cpp` (строки 3585-3590)
```cpp
Go( &EDIT_TOOL::copyToClipboard,       ACTIONS::copy.MakeEvent() );
Go( &EDIT_TOOL::copyToClipboard,       PCB_ACTIONS::copyWithReference.MakeEvent() );
Go( &EDIT_TOOL::copyToClipboardAsText, ACTIONS::copyAsText.MakeEvent() );
```

### 3.3 Функции, вызываемые copyToClipboard()

1. **RequestSelection()** — получить выделённые элементы
   - **Файл:** `pcbnew/tools/pcb_selection_tool.cpp`
   - **Функция:** `PCB_SELECTION_TOOL::RequestSelection()`
   - Запрашивает пользователя выбрать элементы для копирования

2. **pickReferencePoint()** — интерактивный выбор базовой точки
   - **Файл:** `pcbnew/tools/edit_tool.cpp` (строка ~3340)
   - **Функция:** `EDIT_TOOL::pickReferencePoint()`
   - Используется только при `copyWithReference`

3. **grid.BestDragOrigin()** — автоматический выбор якоря
   - **Файл:** `include/tool/grid_helper.h` или `common/tool/grid_helper.cpp`
   - **Функция:** `PCB_GRID_HELPER::BestDragOrigin()`
   - Вычисляет оптимальную точку привязки для перемещения

4. **SaveSelection()** — сохранение в буфер обмена
   - **Файл:** `pcbnew/kicad_clipboard.cpp` (строка 126)
   - **Функция:** `CLIPBOARD_IO::SaveSelection()`
   - Сохраняет выделение с привязкой в wxClipboard

---

## Секция 4: Существующие диалоги и опции

### 4.1 Dois режима копирования

Существуют **два встроенных режима** копирования, различающихся выбором точки привязки:

#### Режим 1: Быстрое копирование (Ctrl+C)
```cpp
// Функция: copyToClipboard()
// Условие: else ветка (строка 3408)
refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
```
- **Использует:** `PCB_GRID_HELPER::BestDragOrigin()`
- **Логика:** выбирает оптимальную точку на основе:
  - Позиции курсора
  - Размера и формы выделения
  - Сетки сэпов на плате
- **UX:** **Никакого диалога**, мгновенное копирование
- **Достоинства:** быстро, не раздражает при частом использовании
- **Недостатки:** точка привязки "магическая", не всегда очевидна

#### Режим 2: Интерактивное копирование (Menu → Copy with Reference / или через контекстное меню)
```cpp
// Функция: copyToClipboard()
// Условие: if ветка (строка 3390)
if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
{
    if( !pickReferencePoint( _( "Select reference point for the copy..." ),
                             _( "Selection copied" ),
                             _( "Copy canceled" ),
                             refPoint ) )
    {
        frame()->PopTool( selectReferencePoint );
        return 0;
    }
}
```
- **Функция:** `EDIT_TOOL::pickReferencePoint()` (есть в edit_tool.cpp)
- **Логика:** система переходит в режим выбора, пользователь кликает в нужную точку
- **UX:** **Явный выбор точки через клик**
- **Достоинства:** полный контроль, понятно, где будет привязка
- **Недостатки:** медленнее (требует дополнительного клика)

### 4.2 Параметры копирования

Копирование **не имеет конфигурируемых параметров** через диалог.  
Единственные "параметры":
1. **Какие элементы копируются** (выбор пользователя через SelectionTool)
2. **Режим привязки** (быстрый vs интерактивный)

### 4.3 Окна/диалоги

**Явного диалога для параметров копирования НЕ СУЩЕСТВУЕТ.**

Единственный "диалог" — это интерактивный режим `Copy with Reference`:
- Пользователь видит сообщение в статус-баре: "Select reference point for the copy..."
- Пользователь кликает в нужную точку
- Скопированное сохраняется с этой точкой как якорь

---

## Секция 5: Анализ для интеграции нового функционала

### 5.1 Где лучше всего добавить диалог выбора anchor point?

**Рекомендация:** Модифицировать функцию `copyToClipboard()` в `pcbnew/tools/edit_tool.cpp` (строка 3342).

**Текущий код** (строки 3386-3410):
```cpp
if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
{
    if( !pickReferencePoint( _( "Select reference point for the copy..." ),
                             _( "Selection copied" ),
                             _( "Copy canceled" ),
                             refPoint ) )
    {
        frame()->PopTool( selectReferencePoint );
        return 0;
    }
}
else
{
    refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
}
```

### 5.2 Точки входа для изменения

| Точка входа | Файл | Функция | Строка | Назначение | Сложность |
|---|---|---|---|---|---|
| **ПЕРВИЧНАЯ** | `pcbnew/tools/edit_tool.cpp` | `copyToClipboard()` | 3342-3420 | Основная логика копирования | 🟢 Простая |
| **ВТОРИЧНАЯ** | `pcbnew/tools/edit_tool.cpp` | `pickReferencePoint()` | ~3340 | Интерактивный выбор точки | 🟡 Средняя |
| **ТРЕТИЧНАЯ** | `pcbnew/kicad_clipboard.cpp` | `SaveSelection()` | 126+ | Сохранение в буфер обмена | 🟢 Простая |
| **Опциональная** | `pcbnew/tools/pcb_actions.h/cpp` | Новое действие | - | Может быть новая команда | 🟡 Средняя |

### 5.3 Рекомендуемая стратегия интеграции

**Вариант A (РЕКОМЕНДУЕТСЯ):** Добавить диалог при copyToClipboard() для выбора режима
```
КОПИРОВАНИЕ (Ctrl+C или Menu)
    ↓
[ДИАЛОГ]: Выбери режим якоря:
    ☐ Автоматический (как сейчас)
    ☐ Центр выделения
    ☐ Интерактивный (клик)
    ☐ Координата X,Y
    [OK] [ОТМЕНА]
    ↓
copyToClipboard() с выбранным режимом
```

**Преимущества:**
- Не требует изменения интерфейса горячих клавиш
- Явный выбор пользователя
- Обратно совместимо (можно отключить диалог в настройках)

**Недостатки:**
- При частом копировании может раздражать

**Вариант B:** Добавить новую горячую клавишу для меню выбора режима
```
Ctrl+C → быстрое (как сейчас)
Ctrl+Shift+C → показать диалог режима + интерактивное
```

---

## Секция 6: Примеры кода

### 6.1 Регистрация команды в Actions

**Файл:** `pcbnew/tools/pcb_actions.h` (строка 129)
```cpp
// Объявление
static TOOL_ACTION copyWithReference;
```

**Файл:** `pcbnew/tools/pcb_actions.cpp` (строки 481-489)
```cpp
// Определение
TOOL_ACTION PCB_ACTIONS::copyWithReference( TOOL_ACTION_ARGS()
        .Name( "pcbnew.InteractiveMove.copyWithReference" )
        .Scope( AS_GLOBAL )
        .FriendlyName( _( "Copy with Reference" ) )
        .Tooltip( _( "Copy selected item(s) to clipboard with a specified starting point" ) )
        .Icon( BITMAPS::copy )
        .Flags( AF_ACTIVATE ) );
```

### 6.2 Привязка команды к функции обработчика

**Файл:** `pcbnew/tools/edit_tool.cpp` (строки 3585-3590)
```cpp
// Регистрация обработчиков команд в конструкторе Tool
EDIT_TOOL::EDIT_TOOL()
{
    ...
    // Привязка команд к функциям обработчика
    Go( &EDIT_TOOL::copyToClipboard,       ACTIONS::copy.MakeEvent() );
    Go( &EDIT_TOOL::copyToClipboard,       PCB_ACTIONS::copyWithReference.MakeEvent() );
    Go( &EDIT_TOOL::copyToClipboardAsText, ACTIONS::copyAsText.MakeEvent() );
    ...
}
```

### 6.3 Основная функция копирования

**Файл:** `pcbnew/tools/edit_tool.cpp` (строки 3342-3420)
```cpp
int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    CLIPBOARD_IO io;
    PCB_GRID_HELPER grid( m_toolMgr, getEditFrame<PCB_BASE_EDIT_FRAME>()->GetMagneticItemsSettings() );
    TOOL_EVENT      selectReferencePoint( aEvent.Category(), aEvent.Action(),
                                          "pcbnew.InteractiveEdit.selectReferencePoint",
                                          TOOL_ACTION_SCOPE::AS_GLOBAL );

    frame()->PushTool( selectReferencePoint );
    Activate();

    // Запрос выделения
    PCB_SELECTION& selection = m_selectionTool->RequestSelection(
            []( const VECTOR2I& aPt, GENERAL_COLLECTOR& aCollector, PCB_SELECTION_TOOL* sTool )
            {
                for( int i = aCollector.GetCount() - 1; i >= 0; --i )
                {
                    BOARD_ITEM* item = aCollector[i];

                    // Фильтрация: нельзя копировать footprint и его текст одновременно
                    if( ( item->Type() == PCB_FIELD_T || item->Type() == PCB_TEXT_T )
                        && aCollector.HasItem( item->GetParentFootprint() ) )
                    {
                        aCollector.Remove( item );
                    }
                    else if( item->Type() == PCB_MARKER_T )
                    {
                        // Markers копировать нельзя
                        aCollector.Remove( item );
                    }
                }
            },
            aEvent.IsAction( &ACTIONS::cut ) && !m_isFootprintEditor );

    if( !selection.Empty() )
    {
        std::vector<BOARD_ITEM*> items;

        for( EDA_ITEM* item : selection )
        {
            if( item->IsBOARD_ITEM() )
                items.push_back( static_cast<BOARD_ITEM*>( item ) );
        }

        VECTOR2I refPoint;

        // КРИТИЧНАЯ ЧАСТЬ: Выбор режима привязки
        if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
        {
            // Режим 2: Интерактивное копирование
            if( !pickReferencePoint( _( "Select reference point for the copy..." ),
                                     _( "Selection copied" ),
                                     _( "Copy canceled" ),
                                     refPoint ) )
            {
                frame()->PopTool( selectReferencePoint );
                return 0;
            }
        }
        else
        {
            // Режим 1: Автоматическое копирование
            refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
        }

        // Установка якорной точки и сохранение
        selection.SetReferencePoint( refPoint );

        io.SetBoard( board() );
        io.SaveSelection( selection, m_isFootprintEditor );
        frame()->SetStatusText( _( "Selection copied" ) );
    }

    frame()->PopTool( selectReferencePoint );

    if( selection.IsHover() )
        m_selectionTool->ClearSelection();

    return 0;
}
```

### 6.4 Добавление в контекстное меню

**Файл:** `pcbnew/tools/edit_tool.cpp` (строки 135-145 в метода setupTools())
```cpp
ACTION_MENU* menu = new ACTION_MENU( false, selTool );
// ...
menu->AddItem( PCB_ACTIONS::copyWithReference,
               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
menu->AddItem( ACTIONS::copy,
               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
menu->AddItem( ACTIONS::cut,
               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
menu->AddItem( ACTIONS::paste,
               SELECTION_CONDITIONS::ShowAlways );
```

---

## Секция 7: Рекомендации для нового функционала

### 7.1 Минимальные изменения для добавления диалога выбора режима

1. **Создать новое действие** в `pcbnew/tools/pcb_actions.h/cpp`:
   ```cpp
   static TOOL_ACTION copyWithDialog;  // "Copy with Mode Selection"
   ```

2. **Модифицировать copyToClipboard()** для проверки:
   ```cpp
   if( aEvent.IsAction( &PCB_ACTIONS::copyWithDialog ) )
   {
       // Показать диалог выбора режима
       // Получить выбор пользователя
       // Вызвать copyToClipboard() с нужным режимом
   }
   ```

3. **Добавить в меню и контекстное меню** новое действие

### 7.2 Файлы для модификации (в порядке приоритета)

| Файл | Изменения | Сложность |
|---|---|---|
| `pcbnew/tools/edit_tool.cpp` | Модифицировать `copyToClipboard()` | 🟢 Низкая |
| `pcbnew/tools/pcb_actions.h` | Добавить новое действие | 🟢 Низкая |
| `pcbnew/tools/pcb_actions.cpp` | Определить новое действие | 🟢 Низкая |
| `pcbnew/tools/edit_tool.h` | Может потребоваться новый метод | 🟡 Средняя |
| `pcbnew/menubar_pcb_editor.cpp` | Добавить в меню Edit | 🟢 Низкая |
| **Новый файл** | `pcbnew/dialogs/dialog_copy_reference.h/cpp` | 🟡 Средняя |

---

## Выводы

1. **Существует уже механизм интерактивного выбора** через `PCB_ACTIONS::copyWithReference` и `pickReferencePoint()`

2. **Текущая проблема**: режим `copyWithReference` нужно вызывать через меню или контекстное меню, а `Ctrl+C` всегда использует автоматический режим

3. **Рекомендуемое решение**: 
   - Добавить диалог/меню выбора режима при копировании
   - Или создать новую горячую клавишу для интерактивного режима

4. **Ключевые функции для модификации**:
   - `EDIT_TOOL::copyToClipboard()` — основная логика (строка 3342)
   - `EDIT_TOOL::pickReferencePoint()` — интерактивный выбор
   - Регистрация команд в `pcb_actions.h/cpp`

5. **Обратная совместимость**: любые изменения должны оставить `Ctrl+C` быстрым и удобным, а новый функционал добавить через меню или новую горячую клавишу.

---

## Дополнительные материалы

- **Картография копирования:** смотри `COPY_MAP_KICAD_907.md`
- **Анализ anchor point:** смотри `SUBTASK_2_ANSWERS.md` и `ANCHOR_POINT_ANALYSIS.md`  
- **Проектирование решения:** смотри `SUBTASK_4_ANCHOR_POINT_DESIGN.md`
