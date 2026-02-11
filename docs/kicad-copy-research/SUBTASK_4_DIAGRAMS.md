# Подзадача 4 (Приложение): Диаграммы и UML

**Дата:** 11 февраля 2026  
**Цель:** Визуализация архитектуры и потоков выполнения для трёх вариантов решения

---

## ДИАГРАММА 1: Текущая архитектура (базовое состояние)

```
flowchart TD
    A["👤 Пользователь<br/>Ctrl+C"] -->|нажимает| B["EDIT_TOOL::<br/>copyToClipboard"]
    
    B -->|1. RequestSelection| C["SELECTION<br/>получена"]
    C -->|2. GetReferencePoint| D{"Есть явная<br/>anchor point?"}
    
    D -->|ДА| E["return *m_referencePoint"]
    D -->|НЕ| F["return bbox.Centre<br/>FALLBACK"]
    
    E -->|3. SetReferencePoint| G["SELECTION::SetRef<br/>Point updated"]
    F -->|3. SetReferencePoint| G
    
    G -->|4. SaveSelection| H["CLIPBOARD_IO::<br/>SaveSelection"]
    
    H -->|Нормализация| I["Move item<br/>-refPoint"]
    I -->|Координаты → 0,0| J["Format<br/>S-expression"]
    
    J -->|clipboardWriter| K["📋 БУФЕР ОБМЕНА<br/>S-expr format"]
    
    K -->|Ctrl+V| L["PCB_CONTROL<br/>Paste"]
    L -->|Parse| M["Загрузить<br/>из буфера"]
    M -->|placeBoardItems| N["🎯 Вставить на плату"]

    style A fill:#e1f5ff
    style K fill:#f3e5f5
    style N fill:#c8e6c9
```

---

## ДИАГРАММА 2: Вариант A (Интерактивный клик)

```
flowchart TD
    A["👤 Пользователь<br/>Shift+Ctrl+C"] -->|нажимает| B["EDIT_TOOL::<br/>copyWithInteractiveAnchor"]
    
    B -->|enter interactive mode| C["pickAnchorPoint<br/>Ожидание клика"]
    
    C -->|MouseEvent| D{"Левая<br/>кнопка?"}
    D -->|NO| E["Cancel /Esc"]
    D -->|YES| F["OnMouseClick<br/>getPosition"]
    
    E -->|EXIT| Z1["❌ Отмена"]
    
    F -->|cursor position| G["clickPoint =<br/>GetCursorPosition"]
    G -->|SetReferencePoint| H["SELECTION::<br/>m_referencePoint = clickPoint"]
    
    H -->|обычное копирование| I["SaveSelection<br/>с пользовательской точкой"]
    I -->|Move(-refPoint)| J["Нормализация в 0,0"]
    J -->|→ буфер обмена| K["📋 CLIPBOARD<br/>anchor at 0,0"]
    
    style A fill:#fff9c4
    style C fill:#ffccbc
    style K fill:#f3e5f5
    style Z1 fill:#ffcdd2
```

**UX цикл Варианта A:**
```
1. Ctrl+C (быстро)
   ↓ (не выбирает anchor point)
   ↓ ОШИБКА: использует старый автоматический выбор

CORRECTED: Shift+Ctrl+C
   ↓
2. Пользователь видит инструкцию: "Click on anchor point"
   ↓
3. Кликает на плате → выбирает точку
   ↓
4. Копирует с точкой привязки пользователя
   ↓
5. Вставляет в новое место
```

---

## ДИАГРАММА 3: Вариант B (Диалог со списком)

```
flowchart TD
    A["👤 Пользователь<br/>Ctrl+C"] -->|нажимает| B["EDIT_TOOL::<br/>copyToClipboard"]
    
    B -->|requestSelection| C["Check selection<br/>not empty"]
    C -->|YES| D["DIALOG_ANCHOR_<br/>POINT_SELECTION<br/>ShowModal"]
    C -->|NO| Z1["❌ EXIT"]
    
    D -->|User selects| E{"Which mode?"}
    
    E -->|Default| F1["Use fallback<br/>GetReferencePoint"]
    E -->|Center| F2["refPoint =<br/>bbox.Centre"]
    E -->|First Item| F3["refPoint =<br/>firstItem.position"]
    E -->|Top-Left| F4["refPoint =<br/>bbox.origin"]
    E -->|Custom| F5["interactive click<br/>pending..."]
    E -->|Manual X,Y| F6["refPoint =<br/>ParseCoords"]
    
    F1 -->|Continue| G["SaveSelection<br/>with refPoint"]
    F2 -->|SetReferencePoint| G
    F3 -->|SetReferencePoint| G
    F4 -->|SetReferencePoint| G
    F5 -->|setTimeout| G
    F6 -->|SetReferencePoint| G
    
    G -->|Normalize| H["Move(-refPoint)<br/>→ 0,0"]
    H -->|→ clipboard| K["📋 CLIPBOARD"]
    
    D -->|Cancel| Z2["❌ Dialog closed"]
    Z1 --> Z3["[ No action ]"]
    Z2 --> Z3
    
    style A fill:#e1f5ff
    style D fill:#fff9c4
    style G fill:#c8e6c9
    style K fill:#f3e5f5
    style Z1 fill:#ffcdd2
```

**Dialog UI (Вариант B):**
```
┌─────────────────────────────────────────┐
│  Anchor Point Selection                  │
├─────────────────────────────────────────┤
│                                         │
│  ◉ Default (automatic selection)        │
│  ◯ Center of bounding box               │
│  ◯ First selected item                  │
│  ◯ Top-left corner                      │
│  ◯ Custom (interactive click)           │
│     [Select] button                     │
│  ◯ Manual coordinates:                  │
│     X: [.........] Y: [.........] mm    │
│                                         │
│            [OK]      [Cancel]           │
└─────────────────────────────────────────┘
```

---

## ДИАГРАММА 4: Вариант C (Комбинированный - РЕКОМЕНДУЕМЫЙ)

```
flowchart TD
    A["👤 Пользователь"]
    
    A -->|Path 1:<br/>Ctrl+C<br/>быстро| B1["copyToClipboard<br/>NO DIALOG"]
    A -->|Path 2:<br/>Menu →<br/>Copy Custom| B2["copyWithAnchor<br/>Options WITH DIALOG"]
    
    B1 -->|GetReferencePoint| C1["Auto selection<br/>via BestDragOrigin<br/>or bbox.Centre"]
    C1 -->|SaveSelection| K1["📋 CLIPBOARD"]
    
    B2 -->|Show dialog| D["DIALOG_ANCHOR_<br/>POINT_SELECTION"]
    D -->|User chooses| E{"Mode?"}
    
    E -->|Default/<br/>Center/<br/>First Item| F["ApplyAnchorMode<br/>SetReferencePoint"]
    E -->|Manual X,Y| G["ParseCoords<br/>SetReferencePoint"]
    
    F -->|SaveSelection| K2["📋 CLIPBOARD"]
    G -->|SaveSelection| K2
    
    K1 -->|Ctrl+V| L["Paste<br/>normal"]
    K2 -->|Ctrl+V| L
    
    L -->|placeBoardItems| M["Вставить<br/>на плату"]
    
    subgraph "Path 1: FAST"
        B1
        C1
        K1
    end
    
    subgraph "Path 2: FLEXIBLE"
        B2
        D
        E
        F
        G
        K2
    end
    
    style A fill:#e1f5ff
    style B1 fill:#90ee90
    style B2 fill:#fff9c4
    style M fill:#c8e6c9
    style K1 fill:#f3e5f5
    style K2 fill:#f3e5f5
```

**UX Summary для Варианта C:**

```
БЫСТРОЕ КОПИРОВАНИЕ (Ctrl+C):
  Пользователь: Ctrl+C
  KiCad: Копирует, выбирает anchor point автоматически
  Время: ~100ms
  Диалогов: 0
  
ГИБКОЕ КОПИРОВАНИЕ (Menu → Custom):
  Пользователь: Edit → Copy with Anchor Point Options
  KiCad: Показывает диалог с 5+ вариантов
  Пользователь: Выбирает нужный режим
  KiCad: Копирует с выбранным anchor point
  Время: ~500ms (включая выбор)
  Диалогов: 1
  
РЕЗУЛЬТАТ:
  Обе опции в одном приложении → максимум гибкости
```

---

## ДИАГРАММА 5: Класс DIALOG_ANCHOR_POINT_SELECTION

```
classDiagram
    class DIALOG_ANCHOR_POINT_SELECTION {
        +enum ANCHOR_MODE
        
        ANCHOR_DEFAULT
        ANCHOR_CENTER
        ANCHOR_FIRST_ITEM
        ANCHOR_TOP_LEFT
        ANCHOR_CUSTOM
        ANCHOR_MANUAL_COORDS
        
        -wxRadioButton* m_rbDefault
        -wxRadioButton* m_rbCenter
        -wxRadioButton* m_rbFirstItem
        -wxRadioButton* m_rbTopLeft
        -wxRadioButton* m_rbCustom
        -wxRadioButton* m_rbManual
        -wxTextCtrl* m_xInput
        -wxTextCtrl* m_yInput
        -wxButton* m_btnInteractive
        -const PCB_SELECTION& m_selection
        -BOX2I m_bbox
        
        +GetSelectedMode() ANCHOR_MODE
        +GetCustomPoint() VECTOR2I
        
        -onRadioButtonSelected()
        -onManualCoordsChanged()
        -updateControlStates()
        -validateCoordinates() bool
    }
    
    class EDIT_TOOL {
        +copyToClipboard(aEvent) int
        +copyWithAnchorOptions(aEvent) int
        -ApplyAnchorMode(aMode, aCustomPoint, aSel) void
    }
    
    DIALOG_ANCHOR_POINT_SELECTION --|> wxDialog : inherits
    EDIT_TOOL --|> PCB_TOOL : inherits
    
    EDIT_TOOL --> DIALOG_ANCHOR_POINT_SELECTION : creates
    EDIT_TOOL --> PCB_SELECTION : modifies
```

---

## ДИАГРАММА 6: Последовательность сохранения anchor point

```
sequenceDiagram
    actor User
    participant EDIT_TOOL
    participant SELECTION
    participant CLIPBOARD_IO
    participant wxClipboard
    
    User->>EDIT_TOOL: copyWithAnchorOptions()
    
    Note over EDIT_TOOL: Show dialog
    EDIT_TOOL->>EDIT_TOOL: DIALOG_ANCHOR_POINT_SELECTION<br/>ShowModal()
    
    Note over EDIT_TOOL: User chooses mode
    EDIT_TOOL->>EDIT_TOOL: ApplyAnchorMode(mode)
    
    EDIT_TOOL->>SELECTION: SetReferencePoint(point)
    activate SELECTION
    SELECTION->>SELECTION: m_referencePoint = point
    deactivate SELECTION
    
    EDIT_TOOL->>CLIPBOARD_IO: SaveSelection(selection)
    activate CLIPBOARD_IO
    
    CLIPBOARD_IO->>SELECTION: GetReferencePoint()
    SELECTION-->>CLIPBOARD_IO: refPoint
    
    CLIPBOARD_IO->>CLIPBOARD_IO: for each item:<br/>Move(item, -refPoint)
    Note over CLIPBOARD_IO: НОРМАЛИЗАЦИЯ<br/>anchor point → 0,0
    
    CLIPBOARD_IO->>CLIPBOARD_IO: Format() S-expression
    
    CLIPBOARD_IO->>wxClipboard: clipboardWriter(data)
    wxClipboard-->>wxClipboard: Store S-expr
    
    deactivate CLIPBOARD_IO
    
    User->>User: Ctrl+V (paste)
    Note over User: Вставляет из буфера<br/>с anchor point в (0,0)
```

---

## ДИАГРАММА 7: Сравнение трёх вариантов (таблица состояний)

```
graph LR
    A["ВАРИАНТ A<br/>Интерактивный <br/>клик"] -->|Basic| B["⭐⭐⭐⭐<br/>4/5"]
    C["ВАРИАНТ B<br/>Диалог<br/>со списком"] -->|Flexible| D["⭐⭐⭐⭐⭐<br/>5/5"]
    E["ВАРИАНТ C<br/>Комбинированный<br/>✅ RECOMMENDED"] -->|Best| F["⭐⭐⭐⭐⭐<br/>5/5"]
    
    style B fill:#fff9c4
    style D fill:#fff9c4
    style F fill:#c8e6c9
```

| Критерий | A | B | C ✅ |
|----------|---|---|------|
| **Простота UX** | 🟢 Простая | 🟡 Сложная | 🟢 Простая |
| **Скорость Ctrl+C** | 🔴 Медленно | 🔴 Медленно | 🟢 Быстро |
| **Гибкость** | 🟡 Средняя | 🟢 Высокая | 🟢 Высокая |
| **Обратная совместимость** | 🟢 100% | 🟡 Частичная | 🟢 100% |
| **Простота реализации** | 🟢 Просто | 🟡 Средне | 🟢 Просто |
| **Очевидность для пользователя** | 🟡 Не очень | 🟢 Очень | 🟢 Очень |

---

## ДИАГРАММА 8: Архитектура изменений файлов

```
graph LR
    subgraph "Существующие файлы (модифицировать)"
        F1["edit_tool.h<br/>+ copyWithAnchorOptions<br/>+ ApplyAnchorMode"]
        F2["edit_tool.cpp<br/>+ реализация методов"]
        F3["pcb_actions.h<br/>+ copyWithAnchorOptions action"]
        F4["pcb_actions.cpp<br/>+ регистрация"]
    end
    
    subgraph "Новые файлы (создать)"
        F5["dialog_anchor_point<br/>_selection.h"]
        F6["dialog_anchor_point<br/>_selection.cpp"]
        F7["dialog_anchor_point<br/>_selection_base.cpp<br/>(wxFormBuilder)"]
    end
    
    subgraph "Меню (обновить)"
        F8["edit_menu.cpp<br/>+ пункт меню"]
    end
    
    F1 -.->|uses| F5
    F2 -.->|uses| F6
    F2 -.->|uses| F3
    F3 -.->|uses| F4
    F4 -.->|used by| F8
    
    style F1 fill:#ffccbc
    style F2 fill:#ffccbc
    style F3 fill:#ffccbc
    style F4 fill:#ffccbc
    style F5 fill:#c8e6c9
    style F6 fill:#c8e6c9
    style F7 fill:#c8e6c9
    style F8 fill:#fff9c4
```

---

## ДИАГРАММА 9: Состояния диалога

```
stateDiagram-v2
    [*] --> Dialog_Init: ShowModal()
    
    Dialog_Init --> Options_View: Display radio buttons
    
    Options_View --> Default_Selected: user clicks default
    Options_View --> Center_Selected: user clicks center
    Options_View --> FirstItem_Selected: user clicks first item
    Options_View --> TopLeft_Selected: user clicks top-left
    Options_View --> Custom_Selected: user clicks custom
    Options_View --> Manual_Selected: user clicks manual
    
    Manual_Selected --> Coords_Input: user enters X,Y
    Coords_Input --> Validation: OnTextChanged
    
    Validation --> Coords_Valid: X,Y valid
    Validation --> Coords_Invalid: X,Y invalid
    
    Coords_Valid --> Manual_Selected
    Coords_Invalid --> Error_Display: show error message
    Error_Display --> Manual_Selected
    
    Default_Selected --> User_Action
    Center_Selected --> User_Action
    FirstItem_Selected --> User_Action
    TopLeft_Selected --> User_Action
    Custom_Selected --> User_Action
    Coords_Valid --> User_Action
    
    User_Action --> OK_Click: user clicks OK
    User_Action --> Cancel_Click: user clicks Cancel
    
    OK_Click --> [*]: wxID_OK
    Cancel_Click --> [*] : wxID_CANCEL
```

---

## ДИАГРАММА 10: Компонентная диаграмма

```
graph TB
    subgraph "UI Layer"
        MENU["Edit Menu<br/>🎯"]
        DIALOG["Dialog<br/>ANCHOR_POINT<br/>SELECTION<br/>🎨"]
    end
    
    subgraph "Logic Layer"
        TOOL["EDIT_TOOL<br/>copyWithAnchor<br/>Options<br/>📋"]
        APPLY["ApplyAnchor<br/>Mode<br/>⚙️"]
    end
    
    subgraph "Data Layer"
        SEL["SELECTION<br/>🎁"]
        CB["CLIPBOARD_IO<br/>💾"]
    end
    
    subgraph "Storage"
        WXCB["wxClipboard<br/>📦"]
    end
    
    MENU -->|user action| DIALOG
    DIALOG -->|selected mode| TOOL
    TOOL -->|apply mode| APPLY
    APPLY -->|SetReferencePoint| SEL
    TOOL -->|SaveSelection| CB
    CB -->|read RefPoint| SEL
    CB -->|write| WXCB
    
    style MENU fill:#fff9c4
    style DIALOG fill:#fff9c4
    style TOOL fill:#ffccbc
    style APPLY fill:#ffccbc
    style SEL fill:#b3e5fc
    style CB fill:#f3e5f5
    style WXCB fill:#f3e5f5
```

---

## ДИАГРАММА 11: Конечный автомат (State machine) для копирования

```
stateDiagram-v2
    [*] --> Normal_Copy: Ctrl+C
    [*] --> Custom_Copy: Menu→Custom
    
    Normal_Copy --> Has_Selection: RequestSelection()
    Has_Selection --> Get_RefPoint: GetReferencePoint()
    Get_RefPoint --> Check_Explicit: m_referencePoint != nullopt?
    
    Check_Explicit -->|YES| Use_Explicit: return *m_referencePoint
    Check_Explicit -->|NO| Use_Fallback: return bbox.Centre()
    
    Use_Explicit --> Normalize: Move(item, -refPoint)
    Use_Fallback --> Normalize
    
    Normalize --> Format: Format() S-expr
    Format --> Clipboard: Write to wxClipboard
    Clipboard --> [*]
    
    Custom_Copy --> Has_Selection2: RequestSelection()
    Has_Selection2 --> Show_Dialog: DIALOG_ANCHOR_POINT<br/>_SELECTION
    Show_Dialog --> Choose_Mode: User selects mode
    
    Choose_Mode --> Default_Mode: ANCHOR_DEFAULT
    Choose_Mode --> Center_Mode: ANCHOR_CENTER
    Choose_Mode --> FirstItem_Mode: ANCHOR_FIRST_ITEM
    Choose_Mode --> TopLeft_Mode: ANCHOR_TOP_LEFT
    Choose_Mode --> Manual_Mode: ANCHOR_MANUAL_COORDS
    Choose_Mode --> Cancel: Cancel
    
    Cancel --> [*]
    
    Default_Mode --> Apply: ApplyAnchorMode()
    Center_Mode --> Apply
    FirstItem_Mode --> Apply
    TopLeft_Mode --> Apply
    Manual_Mode --> Apply
    
    Apply --> SetRef: SetReferencePoint()
    SetRef --> Normalize2: Move(item, -refPoint)
    Normalize2 --> Format2: Format() S-expr
    Format2 --> Clipboard2: Write to wxClipboard
    Clipboard2 --> [*]
```

---

## ТАБЛИЦА: Сравнение методов выбора anchor point

| Метод | Преимущества | Недостатки | Когда использовать |
|-------|-------------|-----------|------------------|
| **Автоматический (BestDragOrigin)** | Быстро, интуитивно | Не всегда точен | По умолчанию (Ctrl+C) |
| **Center bbox** | Предсказуемо, логично | Может быть не оптимален | Для симметричных деталей |
| **First item** | Просто для вычисления | Зависит от порядка выбора | Для упорядоченных наборов |
| **Top-left** | Вычисляемо, быстро | Часто не совпадает с логикой | Для сетки/матрицы |
| **Manual X,Y** | Точный, явный | Требует ввода | Специальные позиции |
| **Интерактивный клик** | Максимум контроля | Требует доп. клика | Precision placement |

---

## Пример выполнения (Step-by-step)

```
USER SCENARIO: Копирование резистора с точкой привязки в центре

ШАГ 1: Пользователь
┌─────────────────────────────────┐
│ На плате: [Резистор R1]          │
│ Положение: (100, 200)           │
│ Размер: 50x20 mm                │
│ Центр: (125, 210)               │
└─────────────────────────────────┘
  ↓
ШАГ 2: Выбрать резистор
  → SELECTION = {R1}
  → RefPoint = undefined
  ↓
ШАГ 3: Нажать "Edit → Copy with Anchor..."
  → Показать DIALOG_ANCHOR_POINT_SELECTION
  ↓
ШАГ 4: Выбрать "Center of bounding box"
  → Mode = ANCHOR_CENTER
  ↓
ШАГ 5: Нажать OK
  → ApplyAnchorMode( ANCHOR_CENTER, ... )
  → refPoint = bbox.Centre() = (125, 210)
  → SELECTION.SetReferencePoint( (125, 210) )
  ↓
ШАГ 6: SaveSelection()
  → for each item: Move( item, -(125, 210) )
  → Резистор сместился: (100, 200) → (-25, -10)
  → Форматировать S-expression
  →Format: (fp_text ... "R1" (at -25 -10 ...))
  ↓
ШАГ 7: Записать в буфер обмена
  → wxClipboard.SetData(S_expr)
  ↓
ШАГ 8: Пользователь нажимает Ctrl+V (вставка)
  → CLIPBOARD_IO::Parse()
  → Загрузить R1 из буфера: (-25, -10)
  → placeBoardItems()
  → Запросить позицию у пользователя (например, (300, 300))
  ↓
ШАГ 9: Резистор вставлен
┌─────────────────────────────────┐
│ На плате: [Резистор R1']         │
│ Положение: (300, 300)           │
│ Это центр резистора!            │
│ (как в исходной позиции -      │
│  точка привязки совпадает)      │
└─────────────────────────────────┘

РЕЗУЛЬТАТ: ✅ Успешное копирование с сохранением
           центра резистора как точки привязки
```

---

## Заключение

Эти диаграммы визуализируют:

1. ✅ **Текущую архитектуру** - как работает Ctrl+C сейчас
2. ✅ **Три варианта UX** - интерактивный, диалог, комбинированный
3. ✅ **Рекомендуемое решение** - вариант C с обоснованием
4. ✅ **Архитектурные изменения** - какие файлы менять/создавать
5. ✅ **Классы и методы** - полная структура кода
6. ✅ **Последовательности вызовов** - как работает система
7. ✅ **Примеры использования** - реальные сценарии

**Готово к реализации!** ✅
