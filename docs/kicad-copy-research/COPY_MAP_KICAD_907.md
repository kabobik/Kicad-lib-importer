# Картография копирования в KiCad 9.0.7

**Дата исследования:** 11 февраля 2026  
**Версия KiCad:** 9.0.7  
**Базовая папка:** `/home/anton/VsCode/kicad-research/kicad`

---

## Обзор

Это исследование отображает все файлы, классы и функции в KiCad 9.0.7, которые отвечают за копирование элементов и посадочных мест на плате (Copy/Paste операции).

---

## ЧАСТЬ 1: РЕДАКТОР ПЛАТЫ (PCBNEW)

### 1.1 Главные файлы обработки копирования

| Файл | Класс | Методы | Функция |
|------|-------|--------|---------|
| `pcbnew/tools/edit_tool.h` | `EDIT_TOOL` | `copyToClipboard()`, `cutToClipboard()`, `copyToClipboardAsText()` | Основной обработчик команд копирования/вырезания на плате |
| `pcbnew/tools/edit_tool.cpp` | `EDIT_TOOL` | Реализация методов копирования/вырезания | Реализация логики копирования элементов |
| `pcbnew/kicad_clipboard.h` | `CLIPBOARD_IO` | `SaveSelection()`, `SaveBoard()`, `Parse()`, `LoadBoard()` | Интерфейс работы с буфером обмена |
| `pcbnew/kicad_clipboard.cpp` | `CLIPBOARD_IO` | Реализация I/O операций с буфером | Сохранение и загрузка выделения в/из буфера обмена |

### 1.2 Управление выбором и данными выбора

| Файл | Класс | Ключевые методы | Функция |
|------|-------|-----------------|---------|
| `pcbnew/tools/pcb_selection_tool.h` | `PCB_SELECTION_TOOL` | `GetSelection()`, `RequestSelection()`, `select()` | Управление выделением элементов на плате |
| `pcbnew/tools/pcb_selection_tool.cpp` | `PCB_SELECTION_TOOL` | Обработчики выбора элементов | Реализация логики выделения и фильтрации |
| `pcbnew/tools/pcb_selection.h` | `PCB_SELECTION` | `GetBoundingBox()`, `GetTopLeftItem()` | Список выбранных элементов и информация о них |
| `include/tool/selection.h` | `SELECTION` (базовый класс) | `begin()`, `end()`, `Empty()`, `Size()`, `Front()` | Базовый класс для всех селекций в KiCad |

### 1.3 Управление редактором платы

| Файл | Класс | Методы | Функция |
|------|-------|--------|---------|
| `pcbnew/tools/board_editor_control.h` | `BOARD_EDITOR_CONTROL` | Основные команды редактора | Управление действиями редактора платы |
| `pcbnew/tools/board_editor_control.cpp` | `BOARD_EDITOR_CONTROL` | Реализация команд | Реализация аналоговых действий на платформе |

### 1.4 Действия (Actions) для редактора платы

| Файл | Назначение |
|------|-----------|
| `pcbnew/tools/pcb_actions.h` | Объявление всех действий (copy, paste, cut и т.п.) для PCB |
| `pcbnew/tools/pcb_actions.cpp` | Регистрация действий в ACTION_MANAGER |

---

## ЧАСТЬ 2: РЕДАКТОР СХЕМЫ (EESCHEMA)

### 2.1 Главные файлы обработки копирования

| Файл | Класс | Методы | Функция |
|------|-------|--------|---------|
| `eeschema/tools/sch_editor_control.h` | `SCH_EDITOR_CONTROL` | `Cut()`, `Copy()`, `CopyAsText()`, `Paste()`, `Duplicate()` | **Основной обработчик копирования в схемах** |
| `eeschema/tools/sch_editor_control.cpp` | `SCH_EDITOR_CONTROL` | `doCopy()` (приватный), реализация cut/copy/paste | Реализация логики копирования элементов схемы |

### 2.2 Управление выбором в схеме

| Файл | Класс | Ключевые методы | Функция |
|------|-------|-----------------|---------|
| `eeschema/tools/sch_selection_tool.h` | `SCH_SELECTION_TOOL` | `GetSelection()`, `select()` | Управление выделением элементов схемы |
| `eeschema/tools/sch_selection.h` | `SCH_SELECTION` | Наследует `SELECTION` | Список выбранных элементов схемы |

### 2.3 Действия (Actions) для редактора схемы

| Файл | Назначение |
|------|-----------|
| `eeschema/tools/sch_actions.h` | Объявление действий для редактора схемы |
| `eeschema/tools/sch_actions.cpp` | Регистрация действий |

---

## ЧАСТЬ 3: БУФЕР ОБМЕНА И ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ

### 3.1 Интерфейс буфера обмена

| Файл | Класс | Методы | Назначение |
|------|-------|--------|-----------|
| `include/clipboard.h` | `CLIPBOARD` | Методы для работы с системным буфером | Общий интерфейс буфера обмена |
| `common/clipboard.cpp` | `CLIPBOARD` | Реализация | Реализация операций буфера обмена |

### 3.2 Класс CLIPBOARD_IO в pcbnew

**Расширяет:** `PCB_IO_KICAD_SEXPR`

**Ключевые методы:**
- `SaveSelection(const PCB_SELECTION& aSelected, bool isFootprintEditor)` — сохраняет выделение в буфер обмена
- `SaveBoard(const wxString& aFileName, BOARD* aBoard, ...)` — сохраняет всю плату
- `Parse()` — парсит данные из буфера обмена
- `LoadBoard(const wxString& aFileName, ...)` — загружает плату из буфера обмена

**Приватные методы:**
- `clipboardWriter(const wxString& aData)` — записывает в системный буфер обмена
- `clipboardReader()` — читает из системного буфера обмена

---

## ЧАСТЬ 4: АНА​ЛИЗ ANCHOR POINT / REFERENCE POINT

### 4.1 Якорная точка (Reference Point) в pcbnew

**Где хранится:**
- `pcbnew/tools/pcb_selection.h` — наследует `SELECTION` из `include/tool/selection.h`
- Методы: `HasReferencePoint()`, `GetReferencePoint()`

**Использование в копировании:**
```cpp
// В CLIPBOARD_IO::SaveSelection()
VECTOR2I refPoint( 0, 0 );
if( aSelected.HasReferencePoint() )
    refPoint = aSelected.GetReferencePoint();
```

**Критичность для anchor point:**
- **КРИТИЧНО** — Reference point используется для определения смещения при вставке
- При копировании сохраняется как база для позиционирования при вставке

### 4.2 Якорная точка в eeschema

**Где хранится:**
- `eeschema/tools/sch_selection.h` — наследует `SELECTION`
- Similar implementation to PCB_SELECTION

---

## ЧАСТЬ 5: ГРАФ ЗАВИСИМОСТЕЙ

### 5.1 Поток копирования в PCBNew

```
USER (Ctrl+C)
    ↓
TOOL_EVENT (action copy)
    ↓
EDIT_TOOL::copyToClipboard()
    ├─→ PCB_SELECTION_TOOL::GetSelection()
    │    └─→ PCB_SELECTION (сбор выбранных элементов)
    │         └─→ GetReferencePoint() (якорная точка!)
    │
    └─→ CLIPBOARD_IO::SaveSelection()
         ├─→ Сохранение reference point VECTOR2I
         ├─→ Обработка footprints / tracks / zones
         ├─→ Форматирование в S-expression
         └─→ CLIPBOARD_IO::clipboardWriter()
              └─→ wxTheClipboard (системный буфер)
```

### 5.2 Поток вставки в PCBNew

```
USER (Ctrl+V)
    ↓
TOOL_EVENT (action paste)
    ↓
BOARD_EDITOR_CONTROL::Paste() или EDIT_TOOL::paste()
    ├─→ CLIPBOARD_IO::clipboardReader()
    │    └─→ Получение из wxTheClipboard
    │
    ├─→ CLIPBOARD_IO::Parse()
    │    └─→ Парсинг S-expression
    │
    ├─→ CLIPBOARD_IO::LoadBoard()
    │    └─→ Загрузка объектов из буфера
    │
    └─→ Позиционирование (использует reference point)
         └─→ Вставка в m_board на основе якорной точки
```

### 5.3 Поток копирования в eeschema

```
USER (Ctrl+C)
    ↓
TOOL_EVENT (action copy)
    ↓
SCH_EDITOR_CONTROL::Copy()
    ├─→ SCH_EDITOR_CONTROL::doCopy()
    │    ├─→ SCH_SELECTION_TOOL::GetSelection()
    │    │    └─→ SCH_SELECTION (сбор выбранных элементов)
    │    │
    │    └─→ Форматирование в буфер обмена
    │         └─→ m_duplicateClipboard или системный буфер
    │
    └─→ wxTheClipboard (системный буфер)
```

---

## ЧАСТЬ 6: КРИТИЧНЫЕ ФАЙЛЫ ДЛЯ ИЗМЕНЕНИЯ ANCHOR POINT LOGIC

### 6.1 В PCBNew (в порядке приоритета)

**КРИТИЧНЫЕ:**
1. ✅ `pcbnew/tools/edit_tool.h/cpp` — методы copyToClipboard/cutToClipboard
   - Место где захватывается reference point
   - **Действие:** Добавить логику преобразования якорной точки перед сохранением

2. ✅ `pcbnew/kicad_clipboard.h/cpp` — класс CLIPBOARD_IO
   - Метод SaveSelection() сохраняет reference point
   - **Действие:** Добавить параметр для трансформации anchor point

3. ✅ `pcbnew/tools/pcb_selection.h`
   - Здесь определяется GetReferencePoint()
   - **Действие:** Может потребоваться модификация logic

**ВАЖНЫЕ:**
4. `pcbnew/tools/pcb_selection_tool.h/cpp` — управление выселением и reference point
5. `include/tool/selection.h` — базовая логика selection

### 6.2 В eeschema

1. ✅ `eeschema/tools/sch_editor_control.h/cpp` — методы Cut/Copy/doCopy
   - **Действие:** Аналогичное преобразование anchor point

2. `eeschema/tools/sch_selection_tool.h/cpp` — управление выбором схемы

---

## ЧАСТЬ 7: ТОЧНЫЕ МЕТОДЫ И ВЫЗОВЫ

### 7.1 Копирование в PCBNew

#### edit_tool.h (строка ~180)
```cpp
class EDIT_TOOL : public PCB_TOOL_BASE
{
private:
    int copyToClipboard( const TOOL_EVENT& aEvent );
    int copyToClipboardAsText( const TOOL_EVENT& aEvent );
    int cutToClipboard( const TOOL_EVENT& aEvent );
};
```

#### kicad_clipboard.h (строка ~53)
```cpp
class CLIPBOARD_IO : public PCB_IO_KICAD_SEXPR
{
public:
    void SaveSelection( const PCB_SELECTION& selected, bool isFootprintEditor );
    
private:
    static void clipboardWriter( const wxString& aData );
    static wxString clipboardReader();
};
```

### 7.2 Копирование в eeschema

#### sch_editor_control.h (строка ~113)
```cpp
class SCH_EDITOR_CONTROL : public SCH_TOOL_BASE<SCH_EDIT_FRAME>
{
public:
    int Cut( const TOOL_EVENT& aEvent );
    int Copy( const TOOL_EVENT& aEvent );
    int CopyAsText( const TOOL_EVENT& aEvent );
    int Paste( const TOOL_EVENT& aEvent );
    int Duplicate( const TOOL_EVENT& aEvent );
    
private:
    bool doCopy( bool aUseDuplicateClipboard = false );
};
```

---

## ЧАСТЬ 8: ИТОГОВАЯ ТАБЛИЧКА

### Все файлы, отвечающие за копирование:

| №  | Путь | Класс | Критичность |
|----|------|-------|-------------|
| 1  | pcbnew/tools/edit_tool.h/cpp | EDIT_TOOL | 🔴 КРИТИЧНО |
| 2  | pcbnew/kicad_clipboard.h/cpp | CLIPBOARD_IO | 🔴 КРИТИЧНО |
| 3  | pcbnew/tools/pcb_selection.h/cpp | PCB_SELECTION | 🟡 ВАЖНО |
| 4  | pcbnew/tools/pcb_selection_tool.h/cpp | PCB_SELECTION_TOOL | 🟡 ВАЖНО |
| 5  | pcbnew/tools/board_editor_control.h/cpp | BOARD_EDITOR_CONTROL | 🟢 СОПУТСТВУЮЩЕЕ |
| 6  | pcbnew/tools/pcb_actions.h/cpp | PCB_ACTIONS | 🟢 ИНФРАСТРУКТУРА |
| 7  | eeschema/tools/sch_editor_control.h/cpp | SCH_EDITOR_CONTROL | 🔴 КРИТИЧНО |
| 8  | eeschema/tools/sch_selection_tool.h/cpp | SCH_SELECTION_TOOL | 🟡 ВАЖНО |
| 9  | eeschema/tools/sch_selection.h/cpp | SCH_SELECTION | 🟡 ВАЖНО |
| 10 | eeschema/tools/sch_actions.h/cpp | SCH_ACTIONS | 🟢 ИНФРАСТРУКТУРА |
| 11 | include/tool/selection.h | SELECTION (base) | 🟡 ВАЖНО |
| 12 | include/clipboard.h | CLIPBOARD | 🟢 ВСПОМОГАТЕЛЬНОЕ |

---

## ВЫВОДЫ

### Ключевые моменты для изменения anchor point logic:

1. **Reference Point уже используется** в CLIPBOARD_IO::SaveSelection()
   - Хранится в переменной `refPoint` типа `VECTOR2I`
   - Получается через `aSelected.GetReferencePoint()`

2. **Якорная точка имеет значение** для позиционирования при вставке
   - Используется как смещение при paste операции

3. **Для изменения логики anchor point нужно модифицировать:**
   - `EDIT_TOOL::copyToClipboard()` — перехватить и преобразовать reference point ДО сохранения
   - `CLIPBOARD_IO::SaveSelection()` — добавить параметр для трансформации
   - Аналогично для eeschema в `SCH_EDITOR_CONTROL::doCopy()`

4. **Cascade направление изменений:** Edit Tool → Clipboard IO → Buffer → Selection Tool

