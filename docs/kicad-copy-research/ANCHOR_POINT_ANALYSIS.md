# Анализ GetReferencePoint() и логики anchor point в KiCAD 9.0.7

**Дата анализа:** 11 февраля 2026  
**Версия KiCAD:** 9.0.7  
**Директория исследования:** `/home/anton/VsCode/kicad-research/kicad`

---

## ЧАСТЬ 1: АЛГОРИТМ GetReferencePoint()

### Файл: `common/tool/selection.cpp` (строка 169)

#### Полный код функции:

```cpp
VECTOR2I SELECTION::GetReferencePoint() const
{
    if( m_referencePoint )
        return *m_referencePoint;
    else
        return GetBoundingBox().Centre();
}
```

#### Объяснение алгоритма:

**Логика вычисления anchor point:**

1. **Проверка явно установленной точки:**
   - `if( m_referencePoint )` — проверяет, есть ли явно установленная якорная точка
   - `m_referencePoint` имеет тип `std::optional<VECTOR2I>` (может быть пусто или иметь значение)

2. **Возврат явной якорной точки:**
   - `return *m_referencePoint;` — если точка установлена, возвращается её значение
   - Это может быть любая произвольная точка, установленная пользователем или программой

3. **Fallback на центр bbox:**
   - `return GetBoundingBox().Centre();` — если точка не установлена, используется центр bounding box всех выбранных элементов
   - Это гарантирует, что anchor point всегда имеет корректное значение

#### Объявление в заголовке (`include/tool/selection.h` строка 216-221):

```cpp
bool HasReferencePoint() const
{
    return m_referencePoint != std::nullopt;
}

VECTOR2I GetReferencePoint() const;
```

#### Хранилище данных (`include/tool/selection.h`):

```cpp
protected:
    std::optional<VECTOR2I>         m_referencePoint;
    // ... другие поля
```

### Ассоциированные методы:

```cpp
// Явная установка anchor point
void SELECTION::SetReferencePoint( const VECTOR2I& aP )
{
    m_referencePoint = aP;
}

// Очистка anchor point (вернёт к fallback)
void SELECTION::ClearReferencePoint()
{
    m_referencePoint = std::nullopt;
}
```

---

## ЧАСТЬ 2: СОХРАНЕНИЕ ANCHOR POINT ПРИ КОПИРОВАНИИ

### Файл: `pcbnew/kicad_clipboard.cpp` (строка 118)

#### Полный код функции SaveSelection():

```cpp
void CLIPBOARD_IO::SaveSelection( const PCB_SELECTION& aSelected, bool isFootprintEditor )
{
    VECTOR2I refPoint( 0, 0 );

    // dont even start if the selection is empty
    if( aSelected.Empty() )
        return;

    if( aSelected.HasReferencePoint() )
        refPoint = aSelected.GetReferencePoint();

    // Prepare net mapping that assures that net codes saved in a file are consecutive integers
    m_mapping->SetBoard( m_board );

    // ... обработка таблиц и других структур данных ...

    if( aSelected.Size() == 1 && aSelected.Front()->Type() == PCB_FOOTPRINT_T )
    {
        // make the footprint safe to transfer to other pcbs
        const FOOTPRINT* footprint = static_cast<FOOTPRINT*>( aSelected.Front() );
        // Do not modify existing board
        FOOTPRINT newFootprint( *footprint );

        for( PAD* pad : newFootprint.Pads() )
            pad->SetNetCode( 0 );

        // locked means "locked in place"; copied items therefore can't be locked
        newFootprint.SetLocked( false );

        // locate the reference point at (0, 0) in the copied items
        newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );

        Format( static_cast<BOARD_ITEM*>( &newFootprint ) );

        newFootprint.SetParent( nullptr );
        newFootprint.SetParentGroup( nullptr );
    }
    else if( isFootprintEditor )
    {
        FOOTPRINT partialFootprint( m_board );

        // ... подготовка partial footprint ...

        for( EDA_ITEM* item : aSelected )
        {
            // ... обработка каждого элемента ...

            // Add the pad to the new footprint before moving to ensure the local coords are
            // correct
            partialFootprint.Add( copy );

            // A list of not added items, when adding items to the footprint
            // some PCB_TEXT (reference and value) cannot be added to the footprint
            std::vector<BOARD_ITEM*> skipped_items;

            if( copy->Type() == PCB_GROUP_T || copy->Type() == PCB_GENERATOR_T )
            {
                copy->RunOnDescendants(
                        [&]( BOARD_ITEM* descendant )
                        {
                            // ... обработка потомков ...

                            if( can_add )
                                partialFootprint.Add( descendant );
                            else
                                skipped_items.push_back( descendant );
                        } );
            }

            // locate the reference point at (0, 0) in the copied items
            copy->Move( -refPoint );
```

#### Ключевая логика (строки 118-128):

```cpp
void CLIPBOARD_IO::SaveSelection( const PCB_SELECTION& aSelected, bool isFootprintEditor )
{
    VECTOR2I refPoint( 0, 0 );

    // dont even start if the selection is empty
    if( aSelected.Empty() )
        return;

    if( aSelected.HasReferencePoint() )
        refPoint = aSelected.GetReferencePoint();
    // ... ДАЛЕЕ используется refPoint для смещения элементов ...
```

#### Объяснение алгоритма сохранения:

**Что происходит при сохранении в буфер обмена:**

1. **Инициализация якорной точки:**
   - `VECTOR2I refPoint( 0, 0 );` — по умолчанию (0, 0)
   - `if( aSelected.HasReferencePoint() )` — если выделение имеет явную якорную точку
   - `refPoint = aSelected.GetReferencePoint();` — получить её значение

2. **Нормализация скопированных элементов:**
   - `newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );` — для footprints
   - `copy->Move( -refPoint );` — для остальных элементов
   - **Результат:** якорная точка смещается в (0, 0) в буфере обмена

3. **Почему это важно:**
   - Данные в буфере обмена всегда содержат относительные координаты
   - При вставке эти относительные координаты переносятся на новое место
   - Anchor point (0, 0) служит базой для позиционирования

#### Обработка разных типов элементов:

```
Footprint (единичный)
    ↓ newFootprint.Move( -refPoint )
    ↓ координаты нормализованы

Partial footprint (в редакторе footprint)
    ├─ copy->Move( -refPoint ) для каждого элемента
    ├─ Потомки обрабатываются через RunOnDescendants
    └─ Все координаты относительны к anchor point

Board items (плата целиком)
    ├─ Скопированные элементы нормализованы к (0, 0)
    └─ При вставке используется для базирования
```

---

## ЧАСТЬ 3: ИСПОЛЬЗОВАНИЕ ANCHOR POINT ПРИ КОПИРОВАНИИ

### Файл: `pcbnew/tools/edit_tool.cpp` (строка 3342)

#### Полный код функции copyToClipboard():

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

    PCB_SELECTION& selection = m_selectionTool->RequestSelection(
            []( const VECTOR2I& aPt, GENERAL_COLLECTOR& aCollector, PCB_SELECTION_TOOL* sTool )
            {
                for( int i = aCollector.GetCount() - 1; i >= 0; --i )
                {
                    BOARD_ITEM* item = aCollector[i];

                    // We can't copy both a footprint and its text in the same operation, so if
                    // both are selected, remove the text
                    if( ( item->Type() == PCB_FIELD_T || item->Type() == PCB_TEXT_T )
                        && aCollector.HasItem( item->GetParentFootprint() ) )
                    {
                        aCollector.Remove( item );
                    }
                    else if( item->Type() == PCB_MARKER_T )
                    {
                        // Don't allow copying marker objects
                        aCollector.Remove( item );
                    }
                }
            },

            // Prompt user regarding locked items.
            aEvent.IsAction( &ACTIONS::cut ) && !m_isFootprintEditor );

    if( !selection.Empty() )
    {
        std::vector<BOARD_ITEM*> items;

        for( EDA_ITEM* item : selection )
        {
            if( item->IsBOARD_ITEM()  )
                items.push_back( static_cast<BOARD_ITEM*>( item ) );
        }

        VECTOR2I refPoint;

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

#### Ключевые этапы (строки 3342-3418):

```cpp
int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    CLIPBOARD_IO io;
    PCB_GRID_HELPER grid( /* magnetic items settings */ );
    
    // 1. Получить выделение от пользователя
    PCB_SELECTION& selection = m_selectionTool->RequestSelection( /* filter */ );

    if( !selection.Empty() )
    {
        std::vector<BOARD_ITEM*> items;

        // 2. Собрать все BOARD_ITEM в вектор
        for( EDA_ITEM* item : selection )
        {
            if( item->IsBOARD_ITEM() )
                items.push_back( static_cast<BOARD_ITEM*>( item ) );
        }

        VECTOR2I refPoint;

        // 3. Выбрать anchor point по типу команды
        if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
        {
            // Вариант A: пользователь выбирает точку интерактивно
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
            // Вариант B: автоматический расчёт по сетке и позиции курсора
            refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
        }

        // 4. Установить якорную точку для выделения
        selection.SetReferencePoint( refPoint );

        // 5. Сохранить в буфер обмена
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

#### Объяснение алгоритма копирования:

**Две стратегии определения anchor point:**

| Стратегия | Команда | Логика | Когда используется |
|-----------|---------|--------|-------------------|
| **Интерактивная** | `copyWithReference` | Пользователь выбирает точку | Когда пользователь нажимает специальную команду копирования |
| **Автоматическая** | `copy` (Ctrl+C) | `grid.BestDragOrigin()` | При обычном копировании (оптимальная точка для перетаскивания) |

**Функция `grid.BestDragOrigin()`:**
- Анализирует позицию выбранных элементов
- Находит оптимальную точку для переноса (обычно левый верхний угол или центр)
- Учитывает магнитные привязки (snap to grid)

---

## ЧАСТЬ 4: ИСПОЛЬЗОВАНИЕ ANCHOR POINT ПРИ ВСТАВКЕ

### Файл: `pcbnew/tools/pcb_control.cpp` (строка 1365)

#### Полный код функции placeBoardItems() (вторая перегрузка):

```cpp
bool PCB_CONTROL::placeBoardItems( BOARD_COMMIT* aCommit, std::vector<BOARD_ITEM*>& aItems,
                                   bool aIsNew, bool aAnchorAtOrigin, bool aReannotateDuplicates )
{
    m_toolMgr->RunAction( PCB_ACTIONS::selectionClear );

    PCB_SELECTION_TOOL* selectionTool = m_toolMgr->GetTool<PCB_SELECTION_TOOL>();

    std::vector<BOARD_ITEM*> itemsToSel;
    itemsToSel.reserve( aItems.size() );

    for( BOARD_ITEM* item : aItems )
    {
        if( aIsNew )
        {
            const_cast<KIID&>( item->m_Uuid ) = KIID();

            item->RunOnDescendants(
                    []( BOARD_ITEM* aChild )
                    {
                        const_cast<KIID&>( aChild->m_Uuid ) = KIID();
                    } );

            // Even though BOARD_COMMIT::Push() will add any new items to the group, we're
            // going to run PCB_ACTIONS::move first, and the move tool will throw out any
            // items that aren't in the entered group.
            if( selectionTool->GetEnteredGroup() && !item->GetParentGroup() )
                selectionTool->GetEnteredGroup()->AddItem( item );

            item->SetParent( board() );
        }

        // Update item attributes if needed
        if( BaseType( item->Type() ) == PCB_DIMENSION_T )
        {
            static_cast<PCB_DIMENSION_BASE*>( item )->UpdateUnits();
        }
        else if( item->Type() == PCB_FOOTPRINT_T )
        {
            FOOTPRINT* footprint = static_cast<FOOTPRINT*>( item );

            // Update the footprint path with the new KIID path if the footprint is new
            if( aIsNew )
                footprint->SetPath( KIID_PATH() );

            for( BOARD_ITEM* dwg : footprint->GraphicalItems() )
            {
                if( BaseType( dwg->Type() ) == PCB_DIMENSION_T )
                    static_cast<PCB_DIMENSION_BASE*>( dwg )->UpdateUnits();
            }
        }

        // We only need to add the items that aren't inside a group currently selected
        // to the selection. If an item is inside a group and that group is selected,
        // then the selection tool will select it for us.
        if( !item->GetParentGroup() || !alg::contains( aItems, item->GetParentGroup() ) )
            itemsToSel.push_back( item );
    }

    // Select the items that should be selected
    EDA_ITEMS toSel( itemsToSel.begin(), itemsToSel.end() );
    m_toolMgr->RunAction<EDA_ITEMS*>( PCB_ACTIONS::selectItems, &toSel );

    // Reannotate duplicate footprints (make sense only in board editor )
    if( aReannotateDuplicates && m_isBoardEditor )
        m_toolMgr->GetTool<BOARD_REANNOTATE_TOOL>()->ReannotateDuplicatesInSelection();

    for( BOARD_ITEM* item : aItems )
    {
        if( aIsNew )
            aCommit->Add( item );
        else
            aCommit->Added( item );
    }

    PCB_SELECTION& selection = selectionTool->GetSelection();

    if( selection.Size() > 0 )
    {
        if( aAnchorAtOrigin )
        {
            selection.SetReferencePoint( VECTOR2I( 0, 0 ) );
        }
        else if( BOARD_ITEM* item = dynamic_cast<BOARD_ITEM*>( selection.GetTopLeftItem() ) )
        {
            selection.SetReferencePoint( item->GetPosition() );
        }

        getViewControls()->SetCursorPosition( getViewControls()->GetMousePosition(), false );

        m_toolMgr->ProcessEvent( EVENTS::SelectedEvent );

        return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
    }

    return true;
}
```

#### Ключевые этапы (строки 1365-1492):

```cpp
bool PCB_CONTROL::placeBoardItems( BOARD_COMMIT* aCommit, std::vector<BOARD_ITEM*>& aItems,
                                   bool aIsNew, bool aAnchorAtOrigin, bool aReannotateDuplicates )
{
    // 1. Очистить текущее выделение
    m_toolMgr->RunAction( PCB_ACTIONS::selectionClear );

    PCB_SELECTION_TOOL* selectionTool = m_toolMgr->GetTool<PCB_SELECTION_TOOL>();

    std::vector<BOARD_ITEM*> itemsToSel;
    itemsToSel.reserve( aItems.size() );

    // 2. Обработать каждый элемент для вставки
    for( BOARD_ITEM* item : aItems )
    {
        if( aIsNew )
        {
            // Назначить новые UUID для новых элементов
            const_cast<KIID&>( item->m_Uuid ) = KIID();

            item->RunOnDescendants( /* обработка потомков */ );

            // Добавить в группу если нужно
            if( selectionTool->GetEnteredGroup() && !item->GetParentGroup() )
                selectionTool->GetEnteredGroup()->AddItem( item );

            item->SetParent( board() );
        }

        // Обновить атрибуты элемента (размеры, слои и т.д.)
        // ... обновление типов PCB_DIMENSION_T, PCB_FOOTPRINT_T ...

        if( !item->GetParentGroup() || !alg::contains( aItems, item->GetParentGroup() ) )
            itemsToSel.push_back( item );
    }

    // 3. Выделить элементы для перемещения
    EDA_ITEMS toSel( itemsToSel.begin(), itemsToSel.end() );
    m_toolMgr->RunAction<EDA_ITEMS*>( PCB_ACTIONS::selectItems, &toSel );

    // 4. Переаннотировать дубликаты если нужно
    if( aReannotateDuplicates && m_isBoardEditor )
        m_toolMgr->GetTool<BOARD_REANNOTATE_TOOL>()->ReannotateDuplicatesInSelection();

    // 5. Добавить элементы в commit
    for( BOARD_ITEM* item : aItems )
    {
        if( aIsNew )
            aCommit->Add( item );
        else
            aCommit->Added( item );
    }

    PCB_SELECTION& selection = selectionTool->GetSelection();

    // 6. КРИТИЧНО: Установить anchor point для перемещения
    if( selection.Size() > 0 )
    {
        if( aAnchorAtOrigin )
        {
            // Вариант A: Якорная точка в (0, 0)
            selection.SetReferencePoint( VECTOR2I( 0, 0 ) );
        }
        else if( BOARD_ITEM* item = dynamic_cast<BOARD_ITEM*>( selection.GetTopLeftItem() ) )
        {
            // Вариант B: Якорная точка в левый верхний угол
            selection.SetReferencePoint( item->GetPosition() );
        }

        // 7. Установить позицию курсора
        getViewControls()->SetCursorPosition( getViewControls()->GetMousePosition(), false );

        // 8. Отправить событие выделения
        m_toolMgr->ProcessEvent( EVENTS::SelectedEvent );

        // 9. ВСЁ КЛЮЧЕВОЕ: Запустить инструмент перемещения с якорной точкой
        return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
    }

    return true;
}
```

#### Объяснение алгоритма вставки:

**Поток вставки:**

```
1. PCB_CONTROL::Paste()
    ├─ CLIPBOARD_IO::Parse()  ← Парсит буфер обмена с нормализованными координатами
    │
    ├─ placeBoardItems( &commit, clipBoard, ... )
    │
    └─→ 2. placeBoardItems() (строка 1365)
        ├─ Очистить выделение
        ├─ Добавить элементы в выделение
        ├─ Добавить элементы в commit
        │
        └─→ 3. УСТАНОВИТЬ ANCHOR POINT (строки 1481-1489)
            ├─ if( aAnchorAtOrigin )
            │   └─ SetReferencePoint( (0, 0) )  ← якорная точка в начало координат
            │
            └─ else
                └─ SetReferencePoint( GetTopLeftItem()->GetPosition() )  ← якорная точка в левый верхний элемент
        
        └─→ 4. ЗАПУСТИТЬ MOVE TOOL (строка 1492)
            ├─ RunSynchronousAction( PCB_ACTIONS::move, aCommit )
            │
            └─→ MOVE TOOL захватывает выделение с установленной anchor point
                ├─ Пользователь переносит anchor point (и все объекты с ним)
                └─ При отпускании мыши элементы размещаются на плате
```

---

## ЧАСТЬ 5: ПОЛНЫЙ ПОТОК COPY-PASTE

### Диаграмма последовательности:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        КОПИРОВАНИЕ (Copy)                            │
└─────────────────────────────────────────────────────────────────────┘

USER: Ctrl+C (или копировать)
  ↓
EDIT_TOOL::copyToClipboard()
  ├─ Получить выделение
  ├─ Выбрать anchor point:
  │  ├─ Интерактивно (pickReferencePoint)
  │  └─ Автоматически (grid.BestDragOrigin)
  └─ SetReferencePoint( refPoint ) ← Установить якорную точку в выделении

CLIPBOARD_IO::SaveSelection()
  ├─ GetReferencePoint() ← Получить якорную точку
  ├─ Для каждого элемента:
  │  └─ Move( -refPoint ) ← НОРМАЛИЗОВАТЬ координаты (якорная точка → 0,0)
  └─ Format в буфер обмена → wxTheClipboard


┌─────────────────────────────────────────────────────────────────────┐
│                       ВСТАВЛЕНИЕ (Paste)                             │
└─────────────────────────────────────────────────────────────────────┘

USER: Ctrl+V (или вставить)
  ↓
PCB_CONTROL::Paste()
  ├─ CLIPBOARD_IO::Parse() ← Парсить из буфера обмена
  │  └─ Координаты нормализованы (якорная точка в 0,0)
  │
  └─ placeBoardItems( commit, clipBoard, ...)
     ├─ Очистить выделение
     ├─ Выбрать элементы
     │
     └─ SetReferencePoint():
        ├─ if( aAnchorAtOrigin ) → (0, 0)
        └─ else → GetTopLeftItem()->GetPosition()
     
     └─ RunSynchronousAction( PCB_ACTIONS::move, commit )
        └─→ MOVE TOOL активируется с выделением
            ├─ Anchor point готов для перемещения
            ├─ Пользователь перемещает элементы
            └─ При подтверждении элементы размещаются на плате
```

### Ключевые инварианты:

| Этап | Якорная точка | Координаты элементов | Назначение |
|------|---------------|-------------------|-----------|
| **При копировании** | Явно установлена или рассчитана | Абсолютные (на плате) | Определить смещение при нормализации |
| **В буфере обмена** | Всегда (0, 0) | Относительные к (0,0) | Нейтральное представление для передачи |
| **При вставке** | Переустановлена | Относительные к (0,0) на плате | Базис для инструмента перемещения |
| **При перемещении** | Следует за курсором | Смещаются вместе с anchor point | Пользователь видит интерактивное перемещение |

---

## ЧАСТЬ 6: КРИТИЧНЫЕ ДЕТАЛИ

### 1. Почему нормализация в SaveSelection() критична

**Проблема:** Если элементы сохраняются с абсолютными координатами, при вставке они будут размещены в исходной позиции.

**Решение:** Все элементы смещаются на `-refPoint`, приводя anchor point в (0, 0).

```cpp
// В SaveSelection()
newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );
copy->Move( -refPoint );
```

### 2. Fallback в GetReferencePoint()

Если якорная точка не установлена, используется центр bounding box:

```cpp
VECTOR2I SELECTION::GetReferencePoint() const
{
    if( m_referencePoint )
        return *m_referencePoint;
    else
        return GetBoundingBox().Centre();  // FALLBACK
}
```

**Преимущество:** Программа никогда не вернёт null/undefined, всегда есть валидная точка.

### 3. Две стратегии вычисления anchor point при копировании

```cpp
if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
{
    // Интерактивная: пользователь выбирает сам
    pickReferencePoint( ... );
}
else
{
    // Автоматическая: сетка и магнитная привязка
    refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
}
```

### 4. Anchor point при вставке (`aAnchorAtOrigin`)

```cpp
if( aAnchorAtOrigin )
{
    selection.SetReferencePoint( VECTOR2I( 0, 0 ) );  // В начало координат
}
else
{
    selection.SetReferencePoint( item->GetPosition() ); // В левый верхний элемент
}
```

Это определяет, где пользователь будет удерживать "мышкой" при перемещении.

---

## ВЫВОДЫ И ОБОБЩЕНИЕ

### Алгоритм anchor point в KiCAD:

1. **Явная якорная точка** имеет приоритет, если установлена
2. **Fallback на центр bounding box**, если не установлена
3. **При копировании** якорная точка либо явная (интерактивно), либо автоматическая (сетка)
4. **При сохранении** элементы нормализуются к (0, 0)
5. **При вставке** якорная точка переустанавливается для move tool
6. **Move tool** активируется синхронно с установленной якорной точкой

### Критичные файлы и строки для модификации anchor point logic:

| Файл | Строка | Функция | Назначение |
|------|--------|---------|-----------|
| `include/tool/selection.h` | 216-221 | `HasReferencePoint()`, `GetReferencePoint()` | **Интерфейс якорной точки** |
| `common/tool/selection.cpp` | 169 | `GetReferencePoint()` | **Логика возврата якорной точки** |
| `pcbnew/tools/edit_tool.cpp` | 3342 | `copyToClipboard()` | **Выбор anchor point при копировании** |
| `pcbnew/tools/edit_tool.cpp` | 3407 | `SetReferencePoint()` | **Установка якорной точки перед сохранением** |
| `pcbnew/kicad_clipboard.cpp` | 118 | `SaveSelection()` | **Нормализация координат к (0, 0)** |
| `pcbnew/kicad_clipboard.cpp` | 199 | `copy->Move( -refPoint )` | **Фактическое смещение элементов** |
| `pcbnew/tools/pcb_control.cpp` | 1365 | `placeBoardItems()` | **Переустановка якорной точки при вставке** |
| `pcbnew/tools/pcb_control.cpp` | 1486-1492 | `SetReferencePoint()` + `move` | **Запуск move tool с якорной точкой** |

---

## Дополнительные источники

- **GitLab/KiCAD issues:** Поиск по "anchor point", "reference point", "copy paste"
- **Коммиты KiCAD:** История изменений в файлах выше за последние версии
- **SELECTION_TOOL:** Подробнее о том как управляется выделение

---

**Документация подготовлена:** 11.02.2026  
**Исследователь:** GitHub Copilot  
**Статус:** АНАЛИЗ ЗАВЕРШЁН
