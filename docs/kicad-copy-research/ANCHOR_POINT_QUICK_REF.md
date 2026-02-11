# Anchor Point в KiCAD: Краткий справочник  

**Дата:** 11 февраля 2026 | **Версия:** 9.0.7 | **Статус:** Для быстрого поиска информации

---

## БЫСТРАЯ НАВИГАЦИЯ

### 📍 Четыре функции, которые нужно помнить:

```
GetReferencePoint()     → Вернуть якорную точку или центр bbox
SetReferencePoint()     → Установить якорную точку
SaveSelection()         → Сохранить в буфер обмена (нормализация!)
copyToClipboard()       → Выбрать якорную точку и скопировать
placeBoardItems()       → Переустановить якорную точку и запустить move
```

---

## КОД: ВСЁ САМОЕ ВАЖНОЕ

### 1️⃣ GetReferencePoint() — Линия 169 в selection.cpp

```cpp
VECTOR2I SELECTION::GetReferencePoint() const
{
    if( m_referencePoint )
        return *m_referencePoint;           // Явная точка
    else
        return GetBoundingBox().Centre();   // или центр bbox
}
```

**Ключевое:** НИКОГДА не вернёт null, ВСЕГДА есть валидная точка.

---

### 2️⃣ SaveSelection() — Линия 118 в kicad_clipboard.cpp

```cpp
void CLIPBOARD_IO::SaveSelection( const PCB_SELECTION& aSelected, bool isFootprintEditor )
{
    VECTOR2I refPoint( 0, 0 );
    
    if( aSelected.HasReferencePoint() )
        refPoint = aSelected.GetReferencePoint();   // Получить якорную точку

    // ... код подготовки ...

    // КРИТИЧНО: Нормализовать координаты!
    newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );  // или
    copy->Move( -refPoint );                        // якорная точка → (0,0)
    
    Format( ... );  // Форматировать в буфер
}
```

**Ключевое:** Все элементы смещаются на `-refPoint`, якорная точка в буфере = (0, 0).

---

### 3️⃣ copyToClipboard() — Линия 3342 в edit_tool.cpp

```cpp
int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    PCB_SELECTION& selection = m_selectionTool->RequestSelection( /* ... */ );

    if( !selection.Empty() )
    {
        VECTOR2I refPoint;

        // Два способа выбрать якорную точку:
        if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
            pickReferencePoint( /* интерактивно */ );  // Пользователь выбирает
        else
            refPoint = grid.BestDragOrigin( /* ... */ );  // Автоматически

        selection.SetReferencePoint( refPoint );    // КРИТИЧНО!
        io.SaveSelection( selection, ... );         // Сохранить с якорной точкой
    }
}
```

**Ключевое:** `SetReferencePoint(refPoint)` ТЕМ перед `SaveSelection()`.

---

### 4️⃣ placeBoardItems() — Линия 1365 в pcb_control.cpp

```cpp
bool PCB_CONTROL::placeBoardItems( BOARD_COMMIT* aCommit, 
                                   std::vector<BOARD_ITEM*>& aItems,
                                   bool aIsNew, 
                                   bool aAnchorAtOrigin,
                                   bool aReannotateDuplicates )
{
    // ... подготовка элементов (выделение, UUID, parent и т.д.) ...

    PCB_SELECTION& selection = selectionTool->GetSelection();

    if( selection.Size() > 0 )
    {
        // КРИТИЧНО: Переустановить якорную точку ДЛЯ ВСТАВКИ
        if( aAnchorAtOrigin )
            selection.SetReferencePoint( VECTOR2I( 0, 0 ) );  // В начало
        else
            selection.SetReferencePoint( 
                dynamic_cast<BOARD_ITEM*>( 
                    selection.GetTopLeftItem() 
                )->GetPosition() 
            );  // В левый верхний элемент

        // Запустить move tool с якорной точкой
        return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
    }

    return true;
}
```

**Ключевое:** `SetReferencePoint()` ПЕРЕД `move`. Move tool использует эту точку.

---

## 📊 ТАБЛИЧКА КООРДИНАТНЫХ СИСТЕМ

| Этап | Координаты | Якорная точка | Где? |
|------|-----------|---------------|------|
| На плате (до копирования) | Абсолютные на платеBoard coords) | Явная или центр bbox | SELECTION |
| В буфере обмена | Относительные к (0,0) | Всегда (0, 0) | wxTheClipboard |
| При вставке (до move) | Относительные к (0,0) | Переустановляется | Новое SELECTION |
| При перемещении (move) | Смещаются вместе с якорной точкой | Следует за курсором | MOVE TOOL |
| На плате (после вставки) | Абсолютные новые | Зависит от пользователя | Board |

---

## 🔄 FULL CYCLE (Полный цикл Copy-Paste)

```
1. КОПИРОВАНИЕ (Ctrl+C)
   ┌──────────────────────────────┐
   │ copyToClipboard()            │
   ├──────────────────────────────┤
   │ 1. RequestSelection()        │
   │ 2. Выбрать якорную точку:    │
   │    - pickReference() или      │
   │    - grid.BestDragOrigin()   │
   │ 3. SetReferencePoint()  ◄─── ВАЖНО
   │ 4. SaveSelection()           │
   │    └─ Move(-refPoint)   ◄─── НОРМАЛИЗАЦИЯ
   │    └─ Format()          ◄─── S-expression
   │    └─ wxTheClipboard    ◄─── СИСТЕМНЫЙ БУФЕР
   └──────────────────────────────┘
                ↓
   В буфере обмена:
   coordnates нормализованы к (0,0)

2. ВСТАВЛЕНИЕ (Ctrl+V)
   ┌──────────────────────────────┐
   │ PCB_CONTROL::Paste()         │
   ├──────────────────────────────┤
   │ 1. CLIPBOARD_IO::Parse()     │
   │    └─ wxTheClipboard → BOARD │
   │ 2. placeBoardItems()         │
   │    ├─ Выделить элементы      │
   │    ├─ SetReferencePoint() ◄─ ПЕРЕУСТАНОВКА!
   │    │   (0,0) или GetTopLeftItem()
   │    └─ RunSynchronousAction::move ◄─ INTERACTIVE
   └──────────────────────────────┘
                ↓
   MOVE TOOL:
   ├─ Показать "фантом"
   ├─ Пользователь перетаскивает
   └─ При отпускании размещает элементы
```

---

## 🎯 КРИТИЧНЫЕ СТРОКИ КОДА

### Для поиска и модификации:

| Функция | Файл | Строка | ЧТО МЕНЯТЬ |
|---------|------|--------|-----------|
| GetReferencePoint | common/tool/selection.cpp | 169 | Логика возврата якорной точки |
| HasReferencePoint | include/tool/selection.h | 216 | Проверка наличия якорной точки |
| SetReferencePoint | common/tool/selection.cpp | 172 | Установка якорной точки |
| ClearReferencePoint | common/tool/selection.cpp | 177 | Очистка якорной точки |
| SaveSelection | pcbnew/kicad_clipboard.cpp | 118 | **НОРМАЛИЗАЦИЯ КООРДИНАТ** ← ГЛАВНОЕ |
| Move(-refPoint) | pcbnew/kicad_clipboard.cpp | 199 | **КЛЮЧЕВАЯ СТРОКА** |
| copyToClipboard | pcbnew/tools/edit_tool.cpp | 3342 | Выбор якорной точки |
| SetReferencePoint | pcbnew/tools/edit_tool.cpp | 3407 | Установка якорной точки перед сохранением |
| placeBoardItems | pcbnew/tools/pcb_control.cpp | 1365 | **ПЕРЕУСТАНОВКА ЯКОРНОЙ ТОЧКИ** ← ВАЖНОЕ |
| SetReferencePoint | pcbnew/tools/pcb_control.cpp | 1486 | (0,0) или GetTopLeftItem() |
| RunSynchronousAction::move | pcbnew/tools/pcb_control.cpp | 1492 | Запуск move tool |

---

## 💾 m_referencePoint: Как это хранится?

```cpp
// В include/tool/selection.h (protected member)
std::optional<VECTOR2I> m_referencePoint;

// Может быть в двух состояниях:
//  1. std::nullopt → якорная точка НЕ установлена (используется fallback)
//  2. VECTOR2I(x, y) → якорная точка установлена

// Проверка:
if( m_referencePoint )       // true если установлена
    auto p = *m_referencePoint;  // разыменовать

// Установка:
m_referencePoint = VECTOR2I( 100, 200 );

// Очистка:
m_referencePoint = std::nullopt;
```

---

## 🔍 ПОИСК В КОДЕ

### Grep команды для быстрого поиска:

```bash
# Найти все использования GetReferencePoint:
grep -rn "GetReferencePoint" /path/to/kicad/

# Найти SetReferencePoint:
grep -rn "SetReferencePoint" /path/to/kicad/

# Найти ClearReferencePoint:
grep -rn "ClearReferencePoint" /path/to/kicad/

# Найти HasReferencePoint:
grep -rn "HasReferencePoint" /path/to/kicad/

# Найти Move(-refPoint) — критичная строка:
grep -rn "Move.*-refPoint\|Move.*refPoint" /path/to/kicad/pcbnew/

# Найти SaveSelection:
grep -rn "SaveSelection" /path/to/kicad/pcbnew/

# Найти placeBoardItems:
grep -rn "placeBoardItems" /path/to/kicad/pcbnew/
```

---

## 📝 ТИПОВЫЕ ИЗМЕНЕНИЯ

### Если нужно ИЗМЕНИТЬ алгоритм anchor point:

**1. Изменить fallback (если якорная точка не установлена):**
```cpp
// Текущий Fallback: центр bbox
return GetBoundingBox().Centre();

// Альтернативы:
return GetBoundingBox().GetCorner( BOX2I_CORNER::TOP_LEFT );     // левый верхний
return GetBoundingBox().GetOrigin();                              // левый нижний
return selection.Front()->GetPosition();                          // первый элемент
```

**2. Изменить стратегию копирования:**
```cpp
// Текущая:
refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );

// Альтернативы:
refPoint = items.front()->GetPosition();                          // первый элемент
refPoint = selection.GetBoundingBox().Centre();                  // центр
refPoint = getViewControls()->GetMousePosition();                 // позиция курсора
```

**3. Изменить якорную точку при вставке:**
```cpp
// Текущие варианты:
if( aAnchorAtOrigin )
    selection.SetReferencePoint( VECTOR2I( 0, 0 ) );
else
    selection.SetReferencePoint( item->GetPosition() );

// Альтернатива:
selection.SetReferencePoint( selection.GetBoundingBox().Centre() );  // центр
```

---

## ⚙️ КОНФИГУРИРУЕМЫЕ ТОЧКИ

KiCAD 9.0.7 имеет встроенные параметры который влияют на anchor point:

```cpp
// pcbnew/tools/edit_tool.cpp
PCB_BASE_EDIT_FRAME()->GetMagneticItemsSettings()  // Магнитная привязка

// Это влияет на:
grid.BestDragOrigin()  // Выбор автоматической якорной точки
```

---

## 🐛 ЕСЛИ ЯКОРНАЯ ТОЧКА НЕПРАВИЛЬНАЯ

**Симптомы:**
- При копировании элементы "скачут" на странное место
- При вставке элементы в неожиданных координатах
- Якорная точка не совпадает с видимым местом

**Где искать проблему:**
1. `copyToClipboard()` — правильно ли выбрана якорная точка?
2. `SaveSelection()` — правильно ли нормализованы координаты? (строка 199)
3. `placeBoardItems()` — правильно ли переустановлена якорная точка? (строка 1486)
4. `GetReferencePoint()` — правильно ли fallback работает? (строка 169)

---

## 📚 ССЫЛКИ НА КОД

### Основные файлы:

- [include/tool/selection.h](file:///home/anton/VsCode/kicad-research/kicad/include/tool/selection.h) — базовый класс SELECTION
- [common/tool/selection.cpp](file:///home/anton/VsCode/kicad-research/kicad/common/tool/selection.cpp) — реализация GetReferencePoint()
- [pcbnew/tools/pcb_selection.h](file:///home/anton/VsCode/kicad-research/kicad/pcbnew/tools/pcb_selection.h) — PCB_SELECTION
- [pcbnew/kicad_clipboard.cpp](file:///home/anton/VsCode/kicad-research/kicad/pcbnew/kicad_clipboard.cpp) — SaveSelection() и нормализация
- [pcbnew/tools/edit_tool.cpp](file:///home/anton/VsCode/kicad-research/kicad/pcbnew/tools/edit_tool.cpp) — copyToClipboard()
- [pcbnew/tools/pcb_control.cpp](file:///home/anton/VsCode/kicad-research/kicad/pcbnew/tools/pcb_control.cpp) — placeBoardItems() и Paste()

---

## 🎓 ПОНИМАНИЕ В ОДНОЙ ФРАЗЕ

> **Якорная точка — это базовая координата выделения, которая нормализуется к (0, 0) при копировании, а затем переустанавливается при вставке для интерактивного перемещения элементов.**

---

## 📋 ЧЕКЛИСТ ДЛЯ СВОЕЙ РЕАЛИЗАЦИИ

Если вы делаете свою реализацию anchor point logic:

- [ ] GetReferencePoint() возвращает explicit точку или fallback (НИКОГДА null)
- [ ] SaveSelection() нормализует координаты: `Move(-refPoint)`  
- [ ] copyToClipboard() устанавливает якорную точку перед SaveSelection()  
- [ ] placeBoardItems() переустанавливает якорную точку перед move tool  
- [ ] Якорная точка в буфере обмена ВСЕГДА (0, 0)
- [ ] Move tool запускается СИНХРОННО и дожидается пользователя
- [ ] При Undo/Redo якорная точка сохраняется в commit

---

**Последнее обновление:** 11.02.2026  
**Автор исследования:** GitHub Copilot  
**Статус:** СПРАВОЧНИК ГОТОВ К ИСПОЛЬЗОВАНИЮ
