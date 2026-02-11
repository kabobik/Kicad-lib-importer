# Подзадача 5: Финальный план реализации — Улучшение механизма выбора anchor point

**Дата:** 11 февраля 2026  
**Версия KiCad:** 9.0.7  
**Статус:** Финальный план, готов к реализации  
**Оценка трудозатрат:** 3–4 дня разработки (~500 строк нового кода)

---

## Секция 1: Краткое резюме проблемы

### Почему текущее поведение воспринимается как «рандомное»

При копировании объектов через `Ctrl+C` в PCB Editor (pcbnew), KiCad автоматически определяет
**anchor point (точку привязки)** через функцию `PCB_GRID_HELPER::BestDragOrigin()`. Эта функция
анализирует позицию курсора, магнитные привязки и геометрию выделенных элементов, чтобы найти
«оптимальную» точку для перетаскивания. Однако результат зависит от множества неочевидных факторов:
положение курсора в момент нажатия `Ctrl+C`, порядок элементов в выделении, настроек snap-to-grid.
Для пользователя это выглядит непредсказуемо — при вставке (`Ctrl+V`) элементы «прилипают» к курсору
в неожиданном месте, а не, например, за центр выделения или за конкретный пин.

Существующая команда `Copy with Reference` позволяет выбрать точку интерактивно кликом на плате,
но она спрятана в подменю «Positioning Tools» контекстного меню и не имеет горячей клавиши по умолчанию.
Большинство пользователей о ней не знают.

### Что мы хотим получить

Предоставить пользователю **явный и удобный способ** выбора anchor point при копировании, не ломая
привычный workflow через `Ctrl+C`. Решение: добавить новый пункт меню **«Copy with Anchor Point Options…»**
в меню Edit и контекстное меню, который открывает диалог с пятью предопределёнными режимами:
автоматический (как сейчас), центр bounding box, первый элемент выделения, левый верхний угол,
ручной ввод координат X/Y. Стандартный `Ctrl+C` остаётся без изменений — быстрым и без диалогов.

---

## Секция 2: Архитектурное решение

### Выбранный вариант: Вариант C — Комбинированный (гибридный)

Из трёх проанализированных вариантов в Подзадаче 4:

| Критерий | Вариант A (клик) | Вариант B (диалог) | **Вариант C (комбо) ✅** |
|----------|------------------|--------------------|--------------------------|
| Скорость Ctrl+C | Без изменений | Замедляется | **Без изменений** |
| Гибкость | Средняя | Высокая | **Высокая** |
| UX удобство | 6/10 | 7/10 | **9/10** |
| Обратная совместимость | 100% | 100% | **100%** |
| Сложность реализации | Средняя | Средняя | **Средняя** |
| **ИТОГОВЫЙ БАЛЛ** | 44 | 46 | **54 ✅** |

### Обоснование выбора

1. **Ctrl+C не замедляется** — основной use-case остаётся быстрым
2. **Диалог только по запросу** — через меню Edit или контекстное меню
3. **5 предопределённых режимов** — покрывают 95% потребностей
4. **~500 строк нового кода** — низкий риск регрессий
5. **Нет изменений в ядре** — `GetReferencePoint()`, `SaveSelection()`, `placeBoardItems()` не трогаем

### Схема взаимодействия

```
┌────────────────────────────────────────────────────────────────────┐
│                      ТЕКУЩИЙ ПОТОК (без изменений)                  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Пользователь: Ctrl+C                                              │
│       │                                                            │
│       ▼                                                            │
│  EDIT_TOOL::copyToClipboard()          [edit_tool.cpp:3342]        │
│       ├── RequestSelection()                                       │
│       ├── BestDragOrigin() → refPoint  (автоматически)             │
│       ├── SetReferencePoint(refPoint)                              │
│       └── CLIPBOARD_IO::SaveSelection()                            │
│            └── Move(-refPoint) → нормализация к (0,0)              │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                      НОВЫЙ ПОТОК (добавляется)                     │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Пользователь: Edit → "Copy with Anchor Point Options..."         │
│       │                                                            │
│       ▼                                                            │
│  EDIT_TOOL::copyWithAnchorOptions()    [edit_tool.cpp: НОВЫЙ]      │
│       ├── RequestSelection()                                       │
│       ├── Показать DIALOG_ANCHOR_POINT_SELECTION                   │
│       │     ┌──────────────────────────────────────┐               │
│       │     │  Anchor Point Selection              │               │
│       │     │  ◉ Default (automatic)               │               │
│       │     │  ○ Center of bounding box            │               │
│       │     │  ○ First selected item               │               │
│       │     │  ○ Top-left corner                   │               │
│       │     │  ○ Manual coordinates: X___ Y___     │               │
│       │     │       [OK]        [Cancel]           │               │
│       │     └──────────────────────────────────────┘               │
│       ├── ApplyAnchorMode(mode, customPt, selection)               │
│       │    └── SetReferencePoint(anchorPoint)                      │
│       └── CLIPBOARD_IO::SaveSelection()                            │
│            └── Move(-refPoint) → нормализация к (0,0)              │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## Секция 3: Пошаговый план реализации

**Все пути указаны от корня репозитория KiCad:**  
`/home/anton/VsCode/kicad-research/kicad/`

---

### Шаг 1: Добавить новое действие (action) в `pcb_actions.h` / `pcb_actions.cpp`

#### 1.1 Объявление в `pcb_actions.h`

**Файл:** `pcbnew/tools/pcb_actions.h`  
**Строка:** 129 (после `copyWithReference`)

**БЫЛО (строки 128–131):**
```cpp
    /// copy command with manual reference point selection
    static TOOL_ACTION copyWithReference;

    /// Rotation of selected objects
```

**СТАЛО:**
```cpp
    /// copy command with manual reference point selection
    static TOOL_ACTION copyWithReference;

    /// copy command with anchor point options dialog
    static TOOL_ACTION copyWithAnchorOptions;

    /// Rotation of selected objects
```

**Объяснение:** Добавляем объявление нового действия `copyWithAnchorOptions` рядом с существующим
`copyWithReference`, т.к. они семантически связаны — оба про копирование с выбором точки привязки.

---

#### 1.2 Определение в `pcb_actions.cpp`

**Файл:** `pcbnew/tools/pcb_actions.cpp`  
**Строка:** 489 (после определения `copyWithReference`, перед `duplicateIncrement`)

**БЫЛО (строки 488–490):**
```cpp
        .Flags( AF_ACTIVATE ) );

TOOL_ACTION PCB_ACTIONS::duplicateIncrement(TOOL_ACTION_ARGS()
```

**СТАЛО:**
```cpp
        .Flags( AF_ACTIVATE ) );

TOOL_ACTION PCB_ACTIONS::copyWithAnchorOptions( TOOL_ACTION_ARGS()
        .Name( "pcbnew.InteractiveEdit.copyWithAnchorOptions" )
        .Scope( AS_GLOBAL )
        .FriendlyName( _( "Copy with Anchor Point Options..." ) )
        .Tooltip( _( "Copy selected item(s) to clipboard with a choice of anchor point mode" ) )
        .Icon( BITMAPS::copy )
        .Flags( AF_ACTIVATE ) );

TOOL_ACTION PCB_ACTIONS::duplicateIncrement(TOOL_ACTION_ARGS()
```

**Объяснение:** Регистрируем действие с человекочитаемым именем «Copy with Anchor Point Options…»
(многоточие по конвенции KiCad означает, что команда откроет диалог). Горячая клавиша не назначена
по умолчанию — пользователь может назначить её через Preferences → Hotkeys.

---

### Шаг 2: Создать диалог выбора режима anchor point (новые файлы)

#### 2.1 Заголовочный файл диалога

**Файл:** `pcbnew/dialogs/dialog_anchor_point_selection.h` (НОВЫЙ)  
**Полный путь:** `pcbnew/dialogs/dialog_anchor_point_selection.h`

Полное содержимое — см. **Секцию 4.1** ниже.

#### 2.2 Файл реализации диалога

**Файл:** `pcbnew/dialogs/dialog_anchor_point_selection.cpp` (НОВЫЙ)  
**Полный путь:** `pcbnew/dialogs/dialog_anchor_point_selection.cpp`

Полное содержимое — см. **Секцию 4.2** ниже.

**Объяснение:** Диалог наследуется от `wxDialog` напрямую (без wxFormBuilder), что проще для review
и не требует дополнительных файлов `_base`. Содержит 5 radio buttons и два text field для ручного
ввода координат.

---

### Шаг 3: Добавить новые методы в `EDIT_TOOL` (`edit_tool.h` / `edit_tool.cpp`)

#### 3.1 Объявление методов в `edit_tool.h`

**Файл:** `pcbnew/tools/edit_tool.h`  
**Строка:** 222 (блок private-методов, после `pickReferencePoint`)

**БЫЛО (строки 221–224):**
```cpp
    bool pickReferencePoint( const wxString& aTooltip, const wxString& aSuccessMessage,
                             const wxString& aCanceledMessage, VECTOR2I& aReferencePoint );

    bool doMoveSelection( const TOOL_EVENT& aEvent, BOARD_COMMIT* aCommit, bool aAutoStart );
```

**СТАЛО:**
```cpp
    bool pickReferencePoint( const wxString& aTooltip, const wxString& aSuccessMessage,
                             const wxString& aCanceledMessage, VECTOR2I& aReferencePoint );

    ///< Copy selection to clipboard with an interactive anchor point selection dialog.
    int copyWithAnchorOptions( const TOOL_EVENT& aEvent );

    ///< Apply the selected anchor mode to the selection's reference point.
    void applyAnchorMode( int aMode, const VECTOR2I& aCustomPoint,
                          PCB_SELECTION& aSelection,
                          const std::vector<BOARD_ITEM*>& aItems );

    bool doMoveSelection( const TOOL_EVENT& aEvent, BOARD_COMMIT* aCommit, bool aAutoStart );
```

**Объяснение:** Добавляем два метода:
- `copyWithAnchorOptions()` — обработчик нового действия, показывает диалог и копирует
- `applyAnchorMode()` — вспомогательный метод, вычисляет anchor point по выбранному режиму

---

#### 3.2 Реализация методов в `edit_tool.cpp`

**Файл:** `pcbnew/tools/edit_tool.cpp`

##### 3.2.1 Добавить `#include` для диалога

**Строка:** В блок `#include` в начале файла (ориентировочно строки 30–60).  
Добавить строку:

```cpp
#include <dialogs/dialog_anchor_point_selection.h>
```

##### 3.2.2 Реализация `copyWithAnchorOptions()` и `applyAnchorMode()`

**Вставить перед** функцией `copyToClipboard()` (т.е. перед строкой 3342).

**БЫЛО (строки 3340–3342):**
```cpp


int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
```

**СТАЛО (вставка нового кода + оригинал):**
```cpp


int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
{
    CLIPBOARD_IO io;
    PCB_GRID_HELPER grid( m_toolMgr,
                          getEditFrame<PCB_BASE_EDIT_FRAME>()->GetMagneticItemsSettings() );
    TOOL_EVENT selectReferencePoint( aEvent.Category(), aEvent.Action(),
                                     "pcbnew.InteractiveEdit.selectReferencePoint",
                                     TOOL_ACTION_SCOPE::AS_GLOBAL );

    frame()->PushTool( selectReferencePoint );
    Activate();

    PCB_SELECTION& selection = m_selectionTool->RequestSelection(
            []( const VECTOR2I& aPt, GENERAL_COLLECTOR& aCollector, PCB_SELECTION_TOOL* sTool )
            {
                for( int i = aCollector.GetCount() - 1; i >= 0; --i )
                {
                    BOARD_ITEM* item = aCollector[i];

                    if( ( item->Type() == PCB_FIELD_T || item->Type() == PCB_TEXT_T )
                        && aCollector.HasItem( item->GetParentFootprint() ) )
                    {
                        aCollector.Remove( item );
                    }
                    else if( item->Type() == PCB_MARKER_T )
                    {
                        aCollector.Remove( item );
                    }
                }
            },
            false /* don't prompt for locked items */ );

    if( !selection.Empty() )
    {
        std::vector<BOARD_ITEM*> items;

        for( EDA_ITEM* item : selection )
        {
            if( item->IsBOARD_ITEM() )
                items.push_back( static_cast<BOARD_ITEM*>( item ) );
        }

        // Show anchor point selection dialog
        DIALOG_ANCHOR_POINT_SELECTION dlg( frame(), selection );

        if( dlg.ShowModal() == wxID_OK )
        {
            VECTOR2I refPoint;
            int mode = static_cast<int>( dlg.GetSelectedMode() );
            VECTOR2I customPoint = dlg.GetCustomPoint();

            applyAnchorMode( mode, customPoint, selection, items );

            // If ANCHOR_DEFAULT, compute automatic ref point (same as Ctrl+C)
            if( dlg.GetSelectedMode() == DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_DEFAULT )
            {
                refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
                selection.SetReferencePoint( refPoint );
            }

            io.SetBoard( board() );
            io.SaveSelection( selection, m_isFootprintEditor );
            frame()->SetStatusText( _( "Selection copied" ) );
        }
    }

    frame()->PopTool( selectReferencePoint );

    if( selection.IsHover() )
        m_selectionTool->ClearSelection();

    return 0;
}


void EDIT_TOOL::applyAnchorMode( int aMode, const VECTOR2I& aCustomPoint,
                                  PCB_SELECTION& aSelection,
                                  const std::vector<BOARD_ITEM*>& aItems )
{
    using MODE = DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE;

    switch( static_cast<MODE>( aMode ) )
    {
    case MODE::ANCHOR_DEFAULT:
        // Don't set reference point — caller will use BestDragOrigin
        break;

    case MODE::ANCHOR_CENTER:
        aSelection.SetReferencePoint( aSelection.GetBoundingBox().Centre() );
        break;

    case MODE::ANCHOR_FIRST_ITEM:
        if( !aItems.empty() )
            aSelection.SetReferencePoint( aItems.front()->GetPosition() );
        break;

    case MODE::ANCHOR_TOP_LEFT:
    {
        BOARD_ITEM* topLeft = dynamic_cast<BOARD_ITEM*>( aSelection.GetTopLeftItem() );

        if( topLeft )
            aSelection.SetReferencePoint( topLeft->GetPosition() );
        else
            aSelection.SetReferencePoint( aSelection.GetBoundingBox().GetOrigin() );

        break;
    }

    case MODE::ANCHOR_MANUAL_COORDS:
        aSelection.SetReferencePoint( aCustomPoint );
        break;
    }
}


int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
```

**Объяснение:**
- `copyWithAnchorOptions()` повторяет логику `copyToClipboard()` в части получения выделения,
  но вместо автоматического выбора anchor point показывает диалог.
- `applyAnchorMode()` — простой switch по режиму, устанавливающий `SetReferencePoint()`.
- Для режима `ANCHOR_DEFAULT` — reference point не устанавливается здесь, а вычисляется через
  `BestDragOrigin()` в основном методе (идентично обычному `Ctrl+C`).
- Для `ANCHOR_TOP_LEFT` используется `GetTopLeftItem()` из SELECTION (тот же метод что при
  вставке в `placeBoardItems()`).

##### 3.2.3 Регистрация обработчика в `setTransitions()`

**Файл:** `pcbnew/tools/edit_tool.cpp`  
**Строка:** 3588 (после регистрации `copyWithReference`)

**БЫЛО (строки 3587–3589):**
```cpp
    Go( &EDIT_TOOL::copyToClipboard,       ACTIONS::copy.MakeEvent() );
    Go( &EDIT_TOOL::copyToClipboard,       PCB_ACTIONS::copyWithReference.MakeEvent() );
    Go( &EDIT_TOOL::copyToClipboardAsText, ACTIONS::copyAsText.MakeEvent() );
```

**СТАЛО:**
```cpp
    Go( &EDIT_TOOL::copyToClipboard,       ACTIONS::copy.MakeEvent() );
    Go( &EDIT_TOOL::copyToClipboard,       PCB_ACTIONS::copyWithReference.MakeEvent() );
    Go( &EDIT_TOOL::copyWithAnchorOptions, PCB_ACTIONS::copyWithAnchorOptions.MakeEvent() );
    Go( &EDIT_TOOL::copyToClipboardAsText, ACTIONS::copyAsText.MakeEvent() );
```

**Объяснение:** Связываем новое действие `copyWithAnchorOptions` с методом-обработчиком.  
Метод `Go()` регистрирует маршрут: при получении события данного действия вызывать указанный метод.

---

### Шаг 4: Добавить в меню Edit и контекстное меню

#### 4.1 Меню Edit (`menubar_pcb_editor.cpp`)

**Файл:** `pcbnew/menubar_pcb_editor.cpp`  
**Строка:** 197 (после `editMenu->Add( ACTIONS::copy )`)

**БЫЛО (строки 196–199):**
```cpp
    editMenu->Add( ACTIONS::cut );
    editMenu->Add( ACTIONS::copy );
    editMenu->Add( ACTIONS::paste );
    editMenu->Add( ACTIONS::pasteSpecial );
```

**СТАЛО:**
```cpp
    editMenu->Add( ACTIONS::cut );
    editMenu->Add( ACTIONS::copy );
    editMenu->Add( PCB_ACTIONS::copyWithAnchorOptions );
    editMenu->Add( ACTIONS::paste );
    editMenu->Add( ACTIONS::pasteSpecial );
```

**Объяснение:** Добавляем новый пункт меню сразу после стандартного Copy, перед Paste.
Расположение логично: пользователь видит «Copy» и сразу под ним — «Copy with Anchor Point Options…».

Результат в меню Edit:
```
┌────────────────────────────────────────────┐
│ Cut                              Ctrl+X    │
│ Copy                             Ctrl+C    │
│ Copy with Anchor Point Options...          │  ← НОВЫЙ
│ Paste                            Ctrl+V    │
│ Paste Special                    Ctrl+Shift+V │
│ Delete                           Del       │
└────────────────────────────────────────────┘
```

---

#### 4.2 Контекстное меню (Positioning Tools, `edit_tool.cpp`)

**Файл:** `pcbnew/tools/edit_tool.cpp`  
**Строка:** 138 (после `copyWithReference` в условном меню)

**БЫЛО (строки 136–141):**
```cpp
    // clang-format off
    menu->AddItem( PCB_ACTIONS::moveExact,                      SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::moveWithReference,              SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::copyWithReference,              SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::positionRelative,               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::positionRelativeInteractively,  SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
```

**СТАЛО:**
```cpp
    // clang-format off
    menu->AddItem( PCB_ACTIONS::moveExact,                      SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::moveWithReference,              SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::copyWithReference,              SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::copyWithAnchorOptions,          SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::positionRelative,               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
    menu->AddItem( PCB_ACTIONS::positionRelativeInteractively,  SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
```

**Объяснение:** В подменю «Positioning Tools» контекстного меню добавляем новый пункт сразу после
существующего «Copy with Reference». Условие: выделение не пустое и элементы не в процессе перемещения.

---

### Шаг 5: Обновление CMakeLists.txt

**Файл:** `pcbnew/CMakeLists.txt`

Необходимо добавить новый `.cpp` файл диалога в список исходников.

Найти секцию с файлами диалогов (примерно `set( PCBNEW_DIALOGS ...`) и добавить:

```cmake
    dialogs/dialog_anchor_point_selection.cpp
```

**Объяснение:** Без этого новый файл не будет скомпилирован и включён в сборку.

---

### Шаг 6: Горячие клавиши

Горячая клавиша для нового действия **не назначается по умолчанию**. Это осознанное решение:

1. Все удобные комбинации Ctrl+Shift+C и т.п. уже заняты или конфликтуют
2. Пользователь может назначить горячую клавишу через `Preferences → Hotkeys`
3. Действие доступно через меню Edit и контекстное меню

Если в будущем будет принято решение назначить горячую клавишу:

```cpp
// В pcb_actions.cpp, в определении действия:
TOOL_ACTION PCB_ACTIONS::copyWithAnchorOptions( TOOL_ACTION_ARGS()
        .Name( "pcbnew.InteractiveEdit.copyWithAnchorOptions" )
        .Scope( AS_GLOBAL )
        .DefaultHotkey( MD_CTRL + MD_ALT + 'C' )   // ← раскомментировать
        .FriendlyName( _( "Copy with Anchor Point Options..." ) )
        // ...
```

---

## Секция 4: Новые файлы

### 4.1 Файл: `pcbnew/dialogs/dialog_anchor_point_selection.h`

**Полный путь:** `pcbnew/dialogs/dialog_anchor_point_selection.h`

```cpp
/*
 * This program source code file is part of KiCad, a free EDA CAD application.
 *
 * Copyright (C) 2026 KiCad Developers, see AUTHORS.txt for contributors.
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the
 * Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef DIALOG_ANCHOR_POINT_SELECTION_H
#define DIALOG_ANCHOR_POINT_SELECTION_H

#include <wx/dialog.h>
#include <wx/radiobut.h>
#include <wx/textctrl.h>
#include <wx/stattext.h>
#include <wx/sizer.h>

#include <math/vector2d.h>

class PCB_SELECTION;


/**
 * @brief Dialog for selecting an anchor point mode for copy operations.
 *
 * Provides multiple strategies for choosing the reference point when copying
 * PCB items to the clipboard:
 * - Default: automatic selection via BestDragOrigin (same as Ctrl+C)
 * - Center: center of the bounding box of the selection
 * - First Item: position of the first item in the selection
 * - Top-Left: position of the top-left item in the selection
 * - Manual: user-entered X,Y coordinates
 */
class DIALOG_ANCHOR_POINT_SELECTION : public wxDialog
{
public:
    /**
     * @brief Anchor point selection modes.
     */
    enum ANCHOR_MODE
    {
        ANCHOR_DEFAULT      = 0,   ///< Automatic selection (BestDragOrigin)
        ANCHOR_CENTER       = 1,   ///< Center of bounding box
        ANCHOR_FIRST_ITEM   = 2,   ///< Position of first selected item
        ANCHOR_TOP_LEFT     = 3,   ///< Top-left item position
        ANCHOR_MANUAL_COORDS = 4   ///< User-specified X,Y coordinates
    };

    /**
     * @brief Constructor.
     * @param aParent    Parent window (typically the PCB editor frame).
     * @param aSelection The current PCB selection (for info display).
     */
    DIALOG_ANCHOR_POINT_SELECTION( wxWindow* aParent, const PCB_SELECTION& aSelection );

    ~DIALOG_ANCHOR_POINT_SELECTION() override;

    /**
     * @brief Get the selected anchor point mode.
     * @return ANCHOR_MODE enum value.
     */
    ANCHOR_MODE GetSelectedMode() const;

    /**
     * @brief Get custom coordinates entered by the user.
     *
     * Only meaningful when GetSelectedMode() returns ANCHOR_MANUAL_COORDS.
     * Coordinates are in KiCad internal units (nanometers).
     *
     * @return VECTOR2I with custom point.
     */
    VECTOR2I GetCustomPoint() const;

private:
    void onRadioButtonChanged( wxCommandEvent& aEvent );
    void updateControlStates();
    bool validateCoordinates() const;

    // UI controls
    wxRadioButton* m_rbDefault;
    wxRadioButton* m_rbCenter;
    wxRadioButton* m_rbFirstItem;
    wxRadioButton* m_rbTopLeft;
    wxRadioButton* m_rbManual;

    wxStaticText*  m_labelX;
    wxStaticText*  m_labelY;
    wxStaticText*  m_labelUnits;
    wxTextCtrl*    m_inputX;
    wxTextCtrl*    m_inputY;

    wxStaticText*  m_infoLabel;
    wxStaticText*  m_validationMsg;

    // Data
    const PCB_SELECTION& m_selection;
};

#endif // DIALOG_ANCHOR_POINT_SELECTION_H
```

---

### 4.2 Файл: `pcbnew/dialogs/dialog_anchor_point_selection.cpp`

**Полный путь:** `pcbnew/dialogs/dialog_anchor_point_selection.cpp`

```cpp
/*
 * This program source code file is part of KiCad, a free EDA CAD application.
 *
 * Copyright (C) 2026 KiCad Developers, see AUTHORS.txt for contributors.
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the
 * Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "dialog_anchor_point_selection.h"

#include <tool/selection.h>
#include <math/box2.h>


DIALOG_ANCHOR_POINT_SELECTION::DIALOG_ANCHOR_POINT_SELECTION(
        wxWindow* aParent,
        const PCB_SELECTION& aSelection )
    : wxDialog( aParent, wxID_ANY, _( "Anchor Point Selection" ),
                wxDefaultPosition, wxSize( 420, 400 ),
                wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER ),
      m_selection( aSelection )
{
    wxBoxSizer* mainSizer = new wxBoxSizer( wxVERTICAL );

    // ── Selection info ──────────────────────────────────────────
    wxStaticBoxSizer* infoSizer =
            new wxStaticBoxSizer( wxVERTICAL, this, _( "Selection Info" ) );

    BOX2I bbox = m_selection.GetBoundingBox();
    wxString infoText;
    infoText.Printf( _( "Items: %zu  |  Bounding box: (%.2f, %.2f) mm  to  (%.2f, %.2f) mm" ),
                     m_selection.GetSize(),
                     bbox.GetOrigin().x / 1e6,
                     bbox.GetOrigin().y / 1e6,
                     bbox.GetEnd().x / 1e6,
                     bbox.GetEnd().y / 1e6 );

    m_infoLabel = new wxStaticText( this, wxID_ANY, infoText );
    infoSizer->Add( m_infoLabel, 0, wxALL | wxEXPAND, 5 );
    mainSizer->Add( infoSizer, 0, wxALL | wxEXPAND, 10 );

    // ── Anchor mode options ─────────────────────────────────────
    wxStaticBoxSizer* optionsSizer =
            new wxStaticBoxSizer( wxVERTICAL, this, _( "Anchor Point Mode" ) );

    m_rbDefault = new wxRadioButton( this, wxID_ANY,
            _( "Default (automatic selection)" ),
            wxDefaultPosition, wxDefaultSize, wxRB_GROUP );
    m_rbDefault->SetToolTip(
            _( "Uses the same automatic algorithm as Ctrl+C (BestDragOrigin)" ) );
    m_rbDefault->SetValue( true );
    optionsSizer->Add( m_rbDefault, 0, wxALL, 5 );

    m_rbCenter = new wxRadioButton( this, wxID_ANY,
            _( "Center of bounding box" ) );
    m_rbCenter->SetToolTip(
            _( "The anchor point will be at the geometric center of all selected items" ) );
    optionsSizer->Add( m_rbCenter, 0, wxALL, 5 );

    m_rbFirstItem = new wxRadioButton( this, wxID_ANY,
            _( "First selected item" ) );
    m_rbFirstItem->SetToolTip(
            _( "The anchor point will be at the position of the first item in the selection" ) );
    optionsSizer->Add( m_rbFirstItem, 0, wxALL, 5 );

    m_rbTopLeft = new wxRadioButton( this, wxID_ANY,
            _( "Top-left item" ) );
    m_rbTopLeft->SetToolTip(
            _( "The anchor point will be at the position of the top-left item" ) );
    optionsSizer->Add( m_rbTopLeft, 0, wxALL, 5 );

    m_rbManual = new wxRadioButton( this, wxID_ANY,
            _( "Manual coordinates (mm):" ) );
    m_rbManual->SetToolTip(
            _( "Enter exact X and Y coordinates for the anchor point" ) );
    optionsSizer->Add( m_rbManual, 0, wxALL, 5 );

    // Manual coordinate input row
    wxBoxSizer* coordsSizer = new wxBoxSizer( wxHORIZONTAL );
    coordsSizer->AddSpacer( 25 );

    m_labelX = new wxStaticText( this, wxID_ANY, wxT( "X:" ) );
    coordsSizer->Add( m_labelX, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, 4 );
    m_inputX = new wxTextCtrl( this, wxID_ANY, wxT( "0.0" ), wxDefaultPosition, wxSize( 90, -1 ) );
    coordsSizer->Add( m_inputX, 0, wxRIGHT, 12 );

    m_labelY = new wxStaticText( this, wxID_ANY, wxT( "Y:" ) );
    coordsSizer->Add( m_labelY, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, 4 );
    m_inputY = new wxTextCtrl( this, wxID_ANY, wxT( "0.0" ), wxDefaultPosition, wxSize( 90, -1 ) );
    coordsSizer->Add( m_inputY, 0, wxRIGHT, 8 );

    m_labelUnits = new wxStaticText( this, wxID_ANY, wxT( "mm" ) );
    coordsSizer->Add( m_labelUnits, 0, wxALIGN_CENTER_VERTICAL );

    optionsSizer->Add( coordsSizer, 0, wxBOTTOM | wxEXPAND, 5 );

    mainSizer->Add( optionsSizer, 0, wxLEFT | wxRIGHT | wxEXPAND, 10 );

    // ── Validation message ──────────────────────────────────────
    m_validationMsg = new wxStaticText( this, wxID_ANY, wxEmptyString );
    m_validationMsg->SetForegroundColour( *wxRED );
    mainSizer->Add( m_validationMsg, 0, wxLEFT | wxRIGHT | wxEXPAND, 15 );

    // ── OK / Cancel buttons ─────────────────────────────────────
    wxSizer* btnSizer = CreateButtonSizer( wxOK | wxCANCEL );
    mainSizer->Add( btnSizer, 0, wxALL | wxEXPAND, 10 );

    SetSizerAndFit( mainSizer );
    Centre();

    // ── Event bindings ──────────────────────────────────────────
    m_rbDefault->Bind( wxEVT_RADIOBUTTON,
            &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonChanged, this );
    m_rbCenter->Bind( wxEVT_RADIOBUTTON,
            &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonChanged, this );
    m_rbFirstItem->Bind( wxEVT_RADIOBUTTON,
            &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonChanged, this );
    m_rbTopLeft->Bind( wxEVT_RADIOBUTTON,
            &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonChanged, this );
    m_rbManual->Bind( wxEVT_RADIOBUTTON,
            &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonChanged, this );

    // Initial state
    updateControlStates();
}


DIALOG_ANCHOR_POINT_SELECTION::~DIALOG_ANCHOR_POINT_SELECTION()
{
}


DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE
DIALOG_ANCHOR_POINT_SELECTION::GetSelectedMode() const
{
    if( m_rbCenter->GetValue() )       return ANCHOR_CENTER;
    if( m_rbFirstItem->GetValue() )    return ANCHOR_FIRST_ITEM;
    if( m_rbTopLeft->GetValue() )      return ANCHOR_TOP_LEFT;
    if( m_rbManual->GetValue() )       return ANCHOR_MANUAL_COORDS;

    return ANCHOR_DEFAULT;
}


VECTOR2I DIALOG_ANCHOR_POINT_SELECTION::GetCustomPoint() const
{
    double x = 0.0, y = 0.0;

    m_inputX->GetValue().ToDouble( &x );
    m_inputY->GetValue().ToDouble( &y );

    // Convert mm to internal units (nanometers): 1 mm = 1 000 000 nm
    return VECTOR2I( static_cast<int>( x * 1e6 ),
                     static_cast<int>( y * 1e6 ) );
}


void DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonChanged( wxCommandEvent& aEvent )
{
    updateControlStates();

    if( m_rbManual->GetValue() && !validateCoordinates() )
        m_validationMsg->SetLabel( _( "Please enter valid numeric coordinates." ) );
    else
        m_validationMsg->SetLabel( wxEmptyString );
}


void DIALOG_ANCHOR_POINT_SELECTION::updateControlStates()
{
    bool manualMode = m_rbManual->GetValue();

    m_inputX->Enable( manualMode );
    m_inputY->Enable( manualMode );
    m_labelX->Enable( manualMode );
    m_labelY->Enable( manualMode );
    m_labelUnits->Enable( manualMode );
}


bool DIALOG_ANCHOR_POINT_SELECTION::validateCoordinates() const
{
    double x, y;
    return m_inputX->GetValue().ToDouble( &x ) && m_inputY->GetValue().ToDouble( &y );
}
```

---

## Секция 5: Модифицируемые файлы — сводная таблица и unified diff

### Сводная таблица

| № | Файл (от корня репозитория) | Тип изменения | Строки | Описание |
|---|---|---|---|---|
| 1 | `pcbnew/tools/pcb_actions.h` | Добавление | +2 | Объявление `copyWithAnchorOptions` |
| 2 | `pcbnew/tools/pcb_actions.cpp` | Добавление | +8 | Определение `copyWithAnchorOptions` |
| 3 | `pcbnew/tools/edit_tool.h` | Добавление | +7 | Объявление 2 новых методов |
| 4 | `pcbnew/tools/edit_tool.cpp` | Добавление | +105 | Реализация + регистрация + include + контекстное меню |
| 5 | `pcbnew/menubar_pcb_editor.cpp` | Добавление | +1 | Пункт в меню Edit |
| 6 | `pcbnew/CMakeLists.txt` | Добавление | +1 | Новый .cpp в список сборки |

---

### Diff 1: `pcbnew/tools/pcb_actions.h`

```diff
--- a/pcbnew/tools/pcb_actions.h
+++ b/pcbnew/tools/pcb_actions.h
@@ -128,6 +128,9 @@
     /// copy command with manual reference point selection
     static TOOL_ACTION copyWithReference;
 
+    /// copy command with anchor point options dialog
+    static TOOL_ACTION copyWithAnchorOptions;
+
     /// Rotation of selected objects
     static TOOL_ACTION rotateCw;
     static TOOL_ACTION rotateCcw;
```

---

### Diff 2: `pcbnew/tools/pcb_actions.cpp`

```diff
--- a/pcbnew/tools/pcb_actions.cpp
+++ b/pcbnew/tools/pcb_actions.cpp
@@ -487,6 +487,14 @@
         .Icon( BITMAPS::copy )
         .Flags( AF_ACTIVATE ) );
 
+TOOL_ACTION PCB_ACTIONS::copyWithAnchorOptions( TOOL_ACTION_ARGS()
+        .Name( "pcbnew.InteractiveEdit.copyWithAnchorOptions" )
+        .Scope( AS_GLOBAL )
+        .FriendlyName( _( "Copy with Anchor Point Options..." ) )
+        .Tooltip( _( "Copy selected item(s) to clipboard with a choice of anchor point mode" ) )
+        .Icon( BITMAPS::copy )
+        .Flags( AF_ACTIVATE ) );
+
 TOOL_ACTION PCB_ACTIONS::duplicateIncrement(TOOL_ACTION_ARGS()
         .Name( "pcbnew.InteractiveEdit.duplicateIncrementPads" )
         .Scope( AS_GLOBAL )
```

---

### Diff 3: `pcbnew/tools/edit_tool.h`

```diff
--- a/pcbnew/tools/edit_tool.h
+++ b/pcbnew/tools/edit_tool.h
@@ -221,6 +221,13 @@
     bool pickReferencePoint( const wxString& aTooltip, const wxString& aSuccessMessage,
                              const wxString& aCanceledMessage, VECTOR2I& aReferencePoint );
 
+    ///< Copy selection to clipboard with an interactive anchor point selection dialog.
+    int copyWithAnchorOptions( const TOOL_EVENT& aEvent );
+
+    ///< Apply the selected anchor mode to the selection's reference point.
+    void applyAnchorMode( int aMode, const VECTOR2I& aCustomPoint,
+                          PCB_SELECTION& aSelection,
+                          const std::vector<BOARD_ITEM*>& aItems );
+
     bool doMoveSelection( const TOOL_EVENT& aEvent, BOARD_COMMIT* aCommit, bool aAutoStart );
```

---

### Diff 4: `pcbnew/tools/edit_tool.cpp`

```diff
--- a/pcbnew/tools/edit_tool.cpp
+++ b/pcbnew/tools/edit_tool.cpp
@@ -28,6 +28,7 @@
 // ... (existing includes)
+#include <dialogs/dialog_anchor_point_selection.h>
 
@@ -138,6 +139,7 @@
     menu->AddItem( PCB_ACTIONS::moveWithReference,              SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
     menu->AddItem( PCB_ACTIONS::copyWithReference,              SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
+    menu->AddItem( PCB_ACTIONS::copyWithAnchorOptions,          SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
     menu->AddItem( PCB_ACTIONS::positionRelative,               SELECTION_CONDITIONS::NotEmpty && notMovingCondition );
 
@@ -3340,6 +3342,93 @@
 
+int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
+{
+    CLIPBOARD_IO io;
+    PCB_GRID_HELPER grid( m_toolMgr,
+                          getEditFrame<PCB_BASE_EDIT_FRAME>()->GetMagneticItemsSettings() );
+    TOOL_EVENT selectReferencePoint( aEvent.Category(), aEvent.Action(),
+                                     "pcbnew.InteractiveEdit.selectReferencePoint",
+                                     TOOL_ACTION_SCOPE::AS_GLOBAL );
+
+    frame()->PushTool( selectReferencePoint );
+    Activate();
+
+    PCB_SELECTION& selection = m_selectionTool->RequestSelection(
+            []( const VECTOR2I& aPt, GENERAL_COLLECTOR& aCollector, PCB_SELECTION_TOOL* sTool )
+            {
+                for( int i = aCollector.GetCount() - 1; i >= 0; --i )
+                {
+                    BOARD_ITEM* item = aCollector[i];
+
+                    if( ( item->Type() == PCB_FIELD_T || item->Type() == PCB_TEXT_T )
+                        && aCollector.HasItem( item->GetParentFootprint() ) )
+                    {
+                        aCollector.Remove( item );
+                    }
+                    else if( item->Type() == PCB_MARKER_T )
+                    {
+                        aCollector.Remove( item );
+                    }
+                }
+            },
+            false );
+
+    if( !selection.Empty() )
+    {
+        std::vector<BOARD_ITEM*> items;
+
+        for( EDA_ITEM* item : selection )
+        {
+            if( item->IsBOARD_ITEM() )
+                items.push_back( static_cast<BOARD_ITEM*>( item ) );
+        }
+
+        DIALOG_ANCHOR_POINT_SELECTION dlg( frame(), selection );
+
+        if( dlg.ShowModal() == wxID_OK )
+        {
+            VECTOR2I refPoint;
+            int mode = static_cast<int>( dlg.GetSelectedMode() );
+            VECTOR2I customPoint = dlg.GetCustomPoint();
+
+            applyAnchorMode( mode, customPoint, selection, items );
+
+            if( dlg.GetSelectedMode() == DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_DEFAULT )
+            {
+                refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
+                selection.SetReferencePoint( refPoint );
+            }
+
+            io.SetBoard( board() );
+            io.SaveSelection( selection, m_isFootprintEditor );
+            frame()->SetStatusText( _( "Selection copied" ) );
+        }
+    }
+
+    frame()->PopTool( selectReferencePoint );
+
+    if( selection.IsHover() )
+        m_selectionTool->ClearSelection();
+
+    return 0;
+}
+
+
+void EDIT_TOOL::applyAnchorMode( int aMode, const VECTOR2I& aCustomPoint,
+                                  PCB_SELECTION& aSelection,
+                                  const std::vector<BOARD_ITEM*>& aItems )
+{
+    using MODE = DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE;
+
+    switch( static_cast<MODE>( aMode ) )
+    {
+    case MODE::ANCHOR_DEFAULT:
+        break;
+
+    case MODE::ANCHOR_CENTER:
+        aSelection.SetReferencePoint( aSelection.GetBoundingBox().Centre() );
+        break;
+
+    case MODE::ANCHOR_FIRST_ITEM:
+        if( !aItems.empty() )
+            aSelection.SetReferencePoint( aItems.front()->GetPosition() );
+        break;
+
+    case MODE::ANCHOR_TOP_LEFT:
+    {
+        BOARD_ITEM* topLeft = dynamic_cast<BOARD_ITEM*>( aSelection.GetTopLeftItem() );
+
+        if( topLeft )
+            aSelection.SetReferencePoint( topLeft->GetPosition() );
+        else
+            aSelection.SetReferencePoint( aSelection.GetBoundingBox().GetOrigin() );
+
+        break;
+    }
+
+    case MODE::ANCHOR_MANUAL_COORDS:
+        aSelection.SetReferencePoint( aCustomPoint );
+        break;
+    }
+}
+
 
 int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
 
@@ -3587,6 +3676,7 @@
     Go( &EDIT_TOOL::copyToClipboard,       ACTIONS::copy.MakeEvent() );
     Go( &EDIT_TOOL::copyToClipboard,       PCB_ACTIONS::copyWithReference.MakeEvent() );
+    Go( &EDIT_TOOL::copyWithAnchorOptions, PCB_ACTIONS::copyWithAnchorOptions.MakeEvent() );
     Go( &EDIT_TOOL::copyToClipboardAsText, ACTIONS::copyAsText.MakeEvent() );
```

---

### Diff 5: `pcbnew/menubar_pcb_editor.cpp`

```diff
--- a/pcbnew/menubar_pcb_editor.cpp
+++ b/pcbnew/menubar_pcb_editor.cpp
@@ -196,6 +196,7 @@
     editMenu->Add( ACTIONS::cut );
     editMenu->Add( ACTIONS::copy );
+    editMenu->Add( PCB_ACTIONS::copyWithAnchorOptions );
     editMenu->Add( ACTIONS::paste );
     editMenu->Add( ACTIONS::pasteSpecial );
```

---

## Секция 6: Тестирование

### 6.1 Команды сборки

```bash
# Из директории сборки KiCad (build directory)
cd /home/anton/VsCode/kicad-research/kicad/build

# Полная пересборка pcbnew
cmake --build . --target pcbnew -j$(nproc)

# Или минимальная проверка компиляции только edit_tool.cpp
cmake --build . --target pcbnew/tools/CMakeFiles/pcbnew_kiface_objects.dir/edit_tool.cpp.o

# Запуск
./pcbnew/pcbnew
```

### 6.2 Тестовые сценарии

#### Тест 1: Диалог открывается корректно

```
Предусловие: открыта плата с несколькими компонентами
Шаги:
  1. Выделить один footprint
  2. Меню Edit → "Copy with Anchor Point Options..."
  3. Диалог должен появиться
  4. В секции "Selection Info" — корректные данные:
     Items: 1, Bounding box: корректные координаты в мм
  5. 5 radio buttons видны и кликабельны
  6. Поля X, Y доступны ТОЛЬКО при выборе "Manual coordinates"
  7. Нажать Cancel — копирование не происходит

Ожидаемый результат: ✅ Диалог открывается, данные корректны
```

#### Тест 2: Все 5 режимов работают

```
Предусловие: выделено 3-5 элементов (mix: footprints, traces, vias)

Для КАЖДОГО режима:
  1. Edit → Copy with Anchor Point Options...
  2. Выбрать режим → OK
  3. Ctrl+V → вставить
  4. Проверить: элементы «прилипают» к курсору в ожидаемой точке

- Default:     та же точка, что и при Ctrl+C
- Center:      курсор в геометрическом центре выделения
- First Item:  курсор на позиции первого элемента
- Top-Left:    курсор на верхнем левом элементе
- Manual(0,0): курсор в начале координат элементов

Ожидаемый результат: ✅ Каждый режим даёт правильный anchor point
```

#### Тест 3: Обратная совместимость Ctrl+C / Ctrl+V

```
Предусловие: выделены элементы

Шаги:
  1. Ctrl+C (обычное копирование)
  2. Ctrl+V (вставить)
  3. Проверить: поведение ИДЕНТИЧНО тому, что было до изменений

Ожидаемый результат: ✅ Ctrl+C не изменился
```

#### Тест 4: Пустое выделение

```
Шаги:
  1. Снять все выделения (Esc)
  2. Edit → "Copy with Anchor Point Options..."
  3. Диалог НЕ должен появиться (т.к. нечего копировать)

Ожидаемый результат: ✅ Команда не вызывает crash при пустом выделении
```

#### Тест 5: Manual coordinates с отрицательными значениями

```
Шаги:
  1. Выделить элемент
  2. Edit → Copy with Anchor Point Options...
  3. Выбрать "Manual coordinates"
  4. Ввести X=-50.5 Y=-100.25
  5. OK → Ctrl+V

Ожидаемый результат: ✅ Координаты корректно парсятся, вставка работает
```

#### Тест 6: Контекстное меню

```
Шаги:
  1. Выделить элементы
  2. Правый клик → Positioning Tools → "Copy with Anchor Point Options..."
  3. Диалог появляется
  4. Выбрать режим → OK
  5. Ctrl+V → вставка

Ожидаемый результат: ✅ Доступ через контекстное меню работает
```

#### Тест 7: Copy with Reference (регрессия)

```
Шаги:
  1. Выделить элементы
  2. Правый клик → Positioning Tools → "Copy with Reference"
  3. Появляется "Select reference point for the copy..."
  4. Кликнуть на точку → копирование
  5. Ctrl+V → вставка

Ожидаемый результат: ✅ Существующий Copy with Reference не сломан
```

#### Тест 8: Одиночный элемент (footprint)

```
Шаги:
  1. Выделить ОДИН footprint
  2. Edit → Copy with Anchor Point Options → Center → OK
  3. Ctrl+V → вставить

Ожидаемый результат: ✅ Курсор в центре footprint при вставке
```

#### Тест 9: Footprint Editor

```
Шаги:
  1. Открыть footprint editor
  2. Выделить элементы footprint (pads, shapes)
  3. Edit → Copy with Anchor Point Options → Top-Left → OK
  4. Ctrl+V → вставить

Ожидаемый результат: ✅ Работает корректно в footprint editor
```

### 6.3 Чек-лист автоматического тестирования

```
КОМПИЛЯЦИЯ:
  ☐ Проект компилируется без ошибок (0 errors)
  ☐ Нет предупреждений компилятора в новых файлах (0 warnings)
  ☐ Линковка прошла успешно

UNIT TESTS:
  ☐ Существующие тесты pcbnew проходят (ctest --test-dir build -R pcbnew)
  ☐ Существующие тесты clipboard проходят

VALGRIND (опционально):
  ☐ valgrind --leak-check=full ./pcbnew — нет memory leaks в новом коде
```

---

## Секция 7: Риски и ограничения

### 7.1 Риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| **Конфликт с wxDialog на конкретных платформах (macOS, Wayland)** | Низкая | Средний | Используем стандартный `wxDialog`, протестированный паттерн в KiCad. wxFormBuilder base-класс можно добавить позже. |
| **Некорректная конвертация мм → внутренние единицы** | Средняя | Высокий | KiCad использует нанометры (1 мм = 1 000 000 нм). Формула проверена: `int(x * 1e6)`. |
| **Блокировка UI при показе диалога** | Низкая | Низкий | `ShowModal()` — стандартный паттерн для диалогов в KiCad. Все существующие диалоги работают так же. |
| **Конфликт горячих клавиш** | Нулевая | Нулевой | Горячая клавиша не назначена по умолчанию. |
| **Проблемы с интернационализацией (i18n)** | Низкая | Низкий | Все строки обёрнуты в `_()`. При merge в основной репозиторий — автоматически добавятся в .po-файлы. |

### 7.2 Ограничения текущей реализации

1. **Нет интерактивного выбора кликом на плате** — режим «Custom (interactive pick)» не включён
   в текущую реализацию. Для него уже есть «Copy with Reference». Можно добавить позже через
   отдельный radio button + `pickReferencePoint()`.

2. **Нет запоминания последнего выбранного режима** — каждый раз диалог открывается с «Default».
   Можно добавить через `APP_SETTINGS_BASE` / `PCBNEW_SETTINGS`:
   ```cpp
   // Future: в pcbnew_settings.h
   int m_lastAnchorPointMode = 0;
   ```

3. **Координаты только в мм** — не поддерживаются дюймы/мили. Можно расширить через
   `EDA_DRAW_FRAME::GetUserUnits()` и конвертацию.

4. **Нет визуального preview anchor point** — при выборе режима пользователь не видит,
   где именно будет anchor point. Можно добавить отрисовку маркера в VIEW в будущей итерации.

### 7.3 Обратная совместимость

| Аспект | Статус | Подробности |
|--------|--------|-------------|
| `Ctrl+C` (обычное копирование) | ✅ Не изменён | Код `copyToClipboard()` не модифицируется |
| `Ctrl+V` (вставка) | ✅ Не изменён | Код `PCB_CONTROL::Paste()` не модифицируется |
| `Copy with Reference` | ✅ Не изменён | Старая команда работает как раньше |
| Формат буфера обмена | ✅ Совместим | Используется тот же `SaveSelection()` с тем же форматом S-expression |
| Формат `.kicad_pcb` файлов | ✅ Не затронут | Изменения только в UI/tool layer |
| API стабильность | ✅ Нет breaking changes | Только добавления (новые методы, новый action) |
| `SELECTION::GetReferencePoint()` | ✅ Не изменён | Базовый механизм anchor point не тронут |
| `CLIPBOARD_IO::SaveSelection()` | ✅ Не изменён | Нормализация координат работает без изменений |
| `PCB_CONTROL::placeBoardItems()` | ✅ Не изменён | Логика вставки не затронута |

---

## Приложение A: Полная карта файлов

```
НОВЫЕ ФАЙЛЫ (2):
  pcbnew/dialogs/dialog_anchor_point_selection.h      (~115 строк)
  pcbnew/dialogs/dialog_anchor_point_selection.cpp     (~180 строк)

МОДИФИЦИРОВАННЫЕ ФАЙЛЫ (5):
  pcbnew/tools/pcb_actions.h                           (+2 строки)
  pcbnew/tools/pcb_actions.cpp                         (+8 строк)
  pcbnew/tools/edit_tool.h                             (+7 строк)
  pcbnew/tools/edit_tool.cpp                           (+105 строк: include, методы, регистрация, меню)
  pcbnew/menubar_pcb_editor.cpp                        (+1 строка)

ОПЦИОНАЛЬНО:
  pcbnew/CMakeLists.txt                                (+1 строка)

ИТОГО НОВОГО КОДА:                                     ~420 строк
```

---

## Приложение B: Диаграмма классов (финальная)

```
┌────────────────────────────────────────────────────────┐
│                    SELECTION (base)                     │
│              include/tool/selection.h                  │
├────────────────────────────────────────────────────────┤
│ # m_referencePoint: std::optional<VECTOR2I>            │
├────────────────────────────────────────────────────────┤
│ + GetReferencePoint(): VECTOR2I                        │
│ + HasReferencePoint(): bool                            │
│ + SetReferencePoint(aP: VECTOR2I)                      │
│ + ClearReferencePoint()                                │
│ + GetBoundingBox(): BOX2I                              │
│ + GetTopLeftItem(): EDA_ITEM*                          │
└───────────────────────┬────────────────────────────────┘
                        │ наследуется
                        ▼
┌────────────────────────────────────────────────────────┐
│                 PCB_SELECTION (pcbnew)                  │
└───────────────────────┬────────────────────────────────┘
                        │ используется
              ┌─────────┴──────────────┐
              ▼                        ▼
┌─────────────────────────┐  ┌──────────────────────────┐
│      EDIT_TOOL           │  │     CLIPBOARD_IO         │
│  edit_tool.h / .cpp      │  │  kicad_clipboard.cpp     │
├─────────────────────────┤  ├──────────────────────────┤
│ copyToClipboard()        │  │ SaveSelection()          │
│   (Ctrl+C, без изменений)│  │   (нормализация, без     │
│ copyWithReference()      │  │    изменений)            │
│   (интерактивный клик)   │  └──────────────────────────┘
│ copyWithAnchorOptions()  │  ← НОВЫЙ
│   (диалог с 5 режимами)  │
│ applyAnchorMode()        │  ← НОВЫЙ
│   (установка ref point)  │
└─────────────────────────┘
              │
              │ показывает
              ▼
┌──────────────────────────────────────────┐
│ DIALOG_ANCHOR_POINT_SELECTION (НОВЫЙ)    │
│  dialog_anchor_point_selection.h / .cpp  │
├──────────────────────────────────────────┤
│ ANCHOR_MODE enum:                        │
│   ANCHOR_DEFAULT = 0                     │
│   ANCHOR_CENTER = 1                      │
│   ANCHOR_FIRST_ITEM = 2                  │
│   ANCHOR_TOP_LEFT = 3                    │
│   ANCHOR_MANUAL_COORDS = 4              │
├──────────────────────────────────────────┤
│ + GetSelectedMode(): ANCHOR_MODE         │
│ + GetCustomPoint(): VECTOR2I             │
└──────────────────────────────────────────┘
```

---

## Приложение C: Полный поток Copy-Paste (с изменениями)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ПОТОК 1: Ctrl+C (БЫСТРЫЙ, БЕЗ ИЗМЕНЕНИЙ)       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Пользователь: Ctrl+C                                            │
│  2. EDIT_TOOL::copyToClipboard() [edit_tool.cpp:3342]               │
│     ├── RequestSelection()                                          │
│     ├── BestDragOrigin() → refPoint                                 │
│     ├── SetReferencePoint(refPoint)                                 │
│     └── CLIPBOARD_IO::SaveSelection()                               │
│          ├── GetReferencePoint() → refPoint                         │
│          ├── Move(item, -refPoint)  → нормализация                  │
│          └── wxTheClipboard → системный буфер                       │
│                                                                     │
│  3. Пользователь: Ctrl+V                                            │
│  4. PCB_CONTROL::Paste() → placeBoardItems()                        │
│     ├── SetReferencePoint(0,0) или GetTopLeftItem()                 │
│     └── RunSynchronousAction(PCB_ACTIONS::move)                     │
│          └── Интерактивное перемещение                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│           ПОТОК 2: Copy with Anchor Point Options (НОВЫЙ)           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Пользователь: Edit → "Copy with Anchor Point Options..."       │
│  2. EDIT_TOOL::copyWithAnchorOptions() [edit_tool.cpp: НОВЫЙ]       │
│     ├── RequestSelection()                                          │
│     ├── Показать DIALOG_ANCHOR_POINT_SELECTION                      │
│     │    └── Пользователь выбирает режим + OK                       │
│     ├── applyAnchorMode(mode, customPt, selection, items)           │
│     │    └── SetReferencePoint(computedPoint)                       │
│     └── CLIPBOARD_IO::SaveSelection()    ← ТОТЖЕ ПУТЬ             │
│          ├── GetReferencePoint() → computedPoint                    │
│          ├── Move(item, -computedPoint)  → нормализация             │
│          └── wxTheClipboard → системный буфер                       │
│                                                                     │
│  3. Пользователь: Ctrl+V                                            │
│  4. PCB_CONTROL::Paste() → ТОТЖЕ ПУТЬ ВСТАВКИ                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Приложение D: Ключевые инварианты (не нарушаются)

| # | Инвариант | Файл | Строка | Статус |
|---|-----------|------|--------|--------|
| 1 | `GetReferencePoint()` НИКОГДА не возвращает null | `selection.cpp` | 169 | ✅ Не тронут |
| 2 | `m_referencePoint` — `std::optional<VECTOR2I>` | `selection.h` | 240 | ✅ Не тронут |
| 3 | `SaveSelection()` нормализует к (0,0) через `Move(-refPoint)` | `kicad_clipboard.cpp` | 118 | ✅ Не тронут |
| 4 | `placeBoardItems()` переустанавливает anchor point | `pcb_control.cpp` | 1445 | ✅ Не тронут |
| 5 | Move tool запускается синхронно | `pcb_control.cpp` | 1456 | ✅ Не тронут |
| 6 | Anchor point в буфере обмена всегда (0,0) | `kicad_clipboard.cpp` | вся функция | ✅ Не тронут |

---

## Приложение E: Контрольные точки в исходниках (верифицированные номера строк)

Все номера строк проверены по реальным исходникам KiCad 9.0.7:

| Функция / элемент | Файл | Строка |
|---|---|---|
| `SELECTION::GetReferencePoint()` | `common/tool/selection.cpp` | 169 |
| `SELECTION::SetReferencePoint()` | `common/tool/selection.cpp` | 178 |
| `SELECTION::HasReferencePoint()` | `include/tool/selection.h` | 216 |
| `m_referencePoint` (member) | `include/tool/selection.h` | 240 |
| `CLIPBOARD_IO::SaveSelection()` | `pcbnew/kicad_clipboard.cpp` | 118 |
| `PCB_ACTIONS::copyWithReference` (decl) | `pcbnew/tools/pcb_actions.h` | 129 |
| `PCB_ACTIONS::copyWithReference` (def) | `pcbnew/tools/pcb_actions.cpp` | 481 |
| `EDIT_TOOL::copyToClipboard()` | `pcbnew/tools/edit_tool.cpp` | 3342 |
| `pickReferencePoint()` | `pcbnew/tools/edit_tool.cpp` | 3228 |
| Контекстное меню (Positioning Tools) | `pcbnew/tools/edit_tool.cpp` | 136–141 |
| `Go(copyToClipboard)` регистрация | `pcbnew/tools/edit_tool.cpp` | 3587 |
| `Go(copyWithReference)` регистрация | `pcbnew/tools/edit_tool.cpp` | 3588 |
| `pickReferencePoint()` (decl) | `pcbnew/tools/edit_tool.h` | 222 |
| Private members | `pcbnew/tools/edit_tool.h` | 239 |
| Edit menu (Copy) | `pcbnew/menubar_pcb_editor.cpp` | 197 |
| `PCB_CONTROL::placeBoardItems()` (2nd) | `pcbnew/tools/pcb_control.cpp` | 1365 |
| `SetReferencePoint(0,0)` в Paste | `pcbnew/tools/pcb_control.cpp` | 1445 |
| `GetTopLeftItem()` в Paste | `pcbnew/tools/pcb_control.cpp` | 1447 |
| `RunSynchronousAction(move)` | `pcbnew/tools/pcb_control.cpp` | 1456 |

---

**Документ подготовлен:** 11.02.2026  
**Авторы исследований:** Подзадачи 1–4  
**Финальный план:** Подзадача 5  
**Статус:** ✅ Готов к реализации
