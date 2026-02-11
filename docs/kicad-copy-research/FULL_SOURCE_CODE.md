# Полный исходный код трёх ключевых функций

**Дата:** 11 февраля 2026  
**Версия KiCAD:** 9.0.7  
**Статус:** Полный текст кода из исходников

---

## ФУНКЦИЯ 1: GetReferencePoint() и ассоциированные методы

### Файл: `common/tool/selection.cpp`

#### Строка 169-178: GetReferencePoint() и ассоциированные методы

```cpp
VECTOR2I SELECTION::GetReferencePoint() const
{
    if( m_referencePoint )
        return *m_referencePoint;
    else
        return GetBoundingBox().Centre();
}


void SELECTION::SetReferencePoint( const VECTOR2I& aP )
{
    m_referencePoint = aP;
}


void SELECTION::ClearReferencePoint()
{
    m_referencePoint = std::nullopt;
}
```

#### Строка 214-221: Объявление в заголовочном файле

```cpp
// Из: include/tool/selection.h

bool HasReferencePoint() const
{
    return m_referencePoint != std::nullopt;
}

VECTOR2I GetReferencePoint() const;
void SetReferencePoint( const VECTOR2I& aP );
void ClearReferencePoint();
```

#### Хранилище данных в классе (private/protected):

```cpp
// Из: include/tool/selection.h (строка ~240)

protected:
    std::optional<VECTOR2I>         m_referencePoint;
    std::deque<EDA_ITEM*>           m_items;
    std::deque<int>                 m_itemsOrders;
    int                             m_orderCounter;
    EDA_ITEM*                       m_lastAddedItem;
    bool                            m_isHover;
```

#### Анализ:

**Логика:**
1. Если `m_referencePoint` содержит значение → вернуть его
2. Иначе → вернуть центр bounding box всех элементов выделения
3. КРИТИЧНО: метод НИКОГДА не вернёт null

**Использование std::optional:**
- Позволяет различить "явно установлена" vs "не установлена"
- Лучше чем "специальное значение" типа (-1, -1)

---

## ФУНКЦИЯ 2: SaveSelection() и нормализация координат

### Файл: `pcbnew/kicad_clipboard.cpp`

#### Строка 118-300: SaveSelection() с нормализацией

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

    auto deleteUnselectedCells =
            []( PCB_TABLE* aTable )
            {
                int minCol = aTable->GetColCount();
                int maxCol = -1;
                int minRow = aTable->GetRowCount();
                int maxRow = -1;

                for( int row = 0; row < aTable->GetRowCount(); ++row )
                {
                    for( int col = 0; col < aTable->GetColCount(); ++col )
                    {
                        PCB_TABLECELL* cell = aTable->GetCell( row, col );

                        if( cell->IsSelected() )
                        {
                            minRow = std::min( minRow, row );
                            maxRow = std::max( maxRow, row );
                            minCol = std::min( minCol, col );
                            maxCol = std::max( maxCol, col );
                        }
                        else
                        {
                            cell->SetFlags( STRUCT_DELETED );
                        }
                    }
                }

                wxCHECK_MSG( maxCol >= minCol && maxRow >= minRow, /*void*/,
                             wxT( "No selected cells!" ) );

                // aTable is always a clone in the clipboard case
                int destRow = 0;

                for( int row = minRow; row <= maxRow; row++ )
                    aTable->SetRowHeight( destRow++, aTable->GetRowHeight( row ) );

                int destCol = 0;

                for( int col = minCol; col <= maxCol; col++ )
                    aTable->SetColWidth( destCol++, aTable->GetColWidth( col ) );

                aTable->DeleteMarkedCells();
                aTable->SetColCount( ( maxCol - minCol ) + 1 );
                aTable->Normalize();
            };

    std::set<PCB_TABLE*> promotedTables;

    auto parentIsPromoted =
            [&]( PCB_TABLECELL* cell ) -> bool
            {
                for( PCB_TABLE* table : promotedTables )
                {
                    if( table->m_Uuid == cell->GetParent()->m_Uuid )
                        return true;
                }

                return false;
            };

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

        // ⭐ КРИТИЧНО: НОРМАЛИЗАЦИЯ КООРДИНАТ К (0, 0)
        // locate the reference point at (0, 0) in the copied items
        newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );

        Format( static_cast<BOARD_ITEM*>( &newFootprint ) );

        newFootprint.SetParent( nullptr );
        newFootprint.SetParentGroup( nullptr );
    }
    else if( isFootprintEditor )
    {
        FOOTPRINT partialFootprint( m_board );

        // Useful to copy the selection to the board editor (if any), and provides
        // a dummy lib id.
        // Perhaps not a good Id, but better than a empty id
        KIID dummy;
        LIB_ID id( "clipboard", dummy.AsString() );
        partialFootprint.SetFPID( id );

        for( EDA_ITEM* item : aSelected )
        {
            if( !item->IsBOARD_ITEM() )
                continue;

            BOARD_ITEM* boardItem = static_cast<BOARD_ITEM*>( item );
            BOARD_ITEM* copy = nullptr;

            if( PCB_FIELD* field = dynamic_cast<PCB_FIELD*>( item ) )
            {
                if( field->IsMandatory() )
                    continue;
            }

            if( boardItem->Type() == PCB_GROUP_T )
            {
                copy = static_cast<PCB_GROUP*>( boardItem )->DeepClone();
            }
            else if( boardItem->Type() == PCB_GENERATOR_T )
            {
                copy = static_cast<PCB_GENERATOR*>( boardItem )->DeepClone();
            }
            else if( item->Type() == PCB_TABLECELL_T )
            {
                if( parentIsPromoted( static_cast<PCB_TABLECELL*>( item ) ) )
                    continue;

                copy = static_cast<BOARD_ITEM*>( item->GetParent()->Clone() );
                promotedTables.insert( static_cast<PCB_TABLE*>( copy ) );
            }
            else
            {
                copy = static_cast<BOARD_ITEM*>( boardItem->Clone() );
            }

            // If it is only a footprint, clear the nets from the pads
            if( PAD* pad = dynamic_cast<PAD*>( copy ) )
               pad->SetNetCode( 0 );

            // Don't copy group membership information for the 1st level objects being copied
            // since the group they belong to isn't being copied.
            copy->SetParentGroup( nullptr );

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
                            // One cannot add an additional mandatory field to a given footprint:
                            // only one is allowed. So add only non-mandatory fields.
                            bool can_add = true;

                            if( const PCB_FIELD* field = dynamic_cast<const PCB_FIELD*>( item ) )
                            {
                                if( field->IsMandatory() )
                                    can_add = false;
                            }

                            if( can_add )
                                partialFootprint.Add( descendant );
                            else
                                skipped_items.push_back( descendant );
                        } );
            }

            // ⭐ КРИТИЧНО: НОРМАЛИЗАЦИЯ КАЖДОГО ЭЛЕМЕНТА
            // locate the reference point at (0, 0) in the copied items
            copy->Move( -refPoint );

            // Add skipped items (such as mandatory fields) directly to the footprint
            // to avoid the need to explicitly delete them later
            for( BOARD_ITEM* skipped_item : skipped_items )
                partialFootprint.Add( skipped_item );
        }

        // ... остальной код обработки ...

        Format( static_cast<BOARD_ITEM*>( &partialFootprint ) );
    }
    else
    {
        // BOARD case (полная плата)
        // ... аналогичная обработка ...
    }
}
```

#### КЛЮЧЕВЫЕ СТРОКИ:

```cpp
// Строка 126-127: Получить якорную точку
if( aSelected.HasReferencePoint() )
    refPoint = aSelected.GetReferencePoint();

// Строка 197: Нормализация footprint
newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );

// Строка 273: Нормализация каждого элемента
copy->Move( -refPoint );
```

---

## ФУНКЦИЯ 3: copyToClipboard() - выбор якорной точки

### Файл: `pcbnew/tools/edit_tool.cpp`

#### Строка 3342-3418: copyToClipboard()

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

        // ⭐ ДВУХ СТРАТЕГИИ ВЫБОРА ЯКОРНОЙ ТОЧКИ

        if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
        {
            // СТРАТЕГИЯ 1: Интерактивный выбор
            // Пользователь выбирает якорную точку на плате
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
            // СТРАТЕГИЯ 2: Автоматический выбор
            // Вычислить оптимальную якорную точку на основе:
            // - позиции курсора
            // - позиций выбранных элементов
            // - магнитной привязки (snap to grid)
            refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );
        }

        // ⭐ КРИТИЧНО: УСТАНОВИТЬ ЯКОРНУЮ ТОЧКУ ПЕРЕД СОХРАНЕНИЕМ
        selection.SetReferencePoint( refPoint );

        io.SetBoard( board() );
        
        // ⭐ ГЛАВНЫЙ ВЫЗОВ: SaveSelection() получит якорную точку и нормализует координаты
        io.SaveSelection( selection, m_isFootprintEditor );
        
        frame()->SetStatusText( _( "Selection copied" ) );
    }

    frame()->PopTool( selectReferencePoint );

    if( selection.IsHover() )
        m_selectionTool->ClearSelection();

    return 0;
}
```

#### КЛЮЧЕВЫЕ СТРОКИ:

```cpp
// Строка 3388: Интерактивный выбор якорной точки
if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
    if( !pickReferencePoint( /* ... */ ) )

// Строка 3398: Автоматический выбор якорной точки
refPoint = grid.BestDragOrigin( getViewControls()->GetCursorPosition(), items );

// Строка 3407: УСТАНОВИТЬ ЯКОРНУЮ ТОЧКУ ДЛЯ ВЫДЕЛЕНИЯ
selection.SetReferencePoint( refPoint );

// Строка 3409-3411: СОХРАНИТЬ В БУФЕР ОБМЕНА (с якорной точкой)
io.SetBoard( board() );
io.SaveSelection( selection, m_isFootprintEditor );
```

---

## ФУНКЦИЯ 4: placeBoardItems() - использование якорной точки при вставке

### Файл: `pcbnew/tools/pcb_control.cpp`

#### Строка 1365-1492: placeBoardItems() (вторая перегрузка)

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
        // ⭐ КРИТИЧНО: УСТАНОВИТЬ ЯКОРНУЮ ТОЧКУ ДЛЯ ПЕРЕМЕЩЕНИЯ

        if( aAnchorAtOrigin )
        {
            // ВАРИАНТ A: якорная точка в начало координат (0, 0)
            selection.SetReferencePoint( VECTOR2I( 0, 0 ) );
        }
        else if( BOARD_ITEM* item = dynamic_cast<BOARD_ITEM*>( selection.GetTopLeftItem() ) )
        {
            // ВАРИАНТ B: якорная точка в левый верхний элемент выделения
            selection.SetReferencePoint( item->GetPosition() );
        }

        getViewControls()->SetCursorPosition( getViewControls()->GetMousePosition(), false );

        m_toolMgr->ProcessEvent( EVENTS::SelectedEvent );

        // ⭐ ЗАПУСТИТЬ MOVE TOOL С УСТАНОВЛЕННОЙ ЯКОРНОЙ ТОЧКОЙ
        // Это СИНХРОННЫЙ вызов - программа ждёт пока пользователь закончит перемещение
        return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
    }

    return true;
}
```

#### КЛЮЧЕВЫЕ СТРОКИ:

```cpp
// Строка 1481-1489: УСТАНОВИТЬ ЯКОРНУЮ ТОЧКУ
if( aAnchorAtOrigin )
{
    selection.SetReferencePoint( VECTOR2I( 0, 0 ) );
}
else if( BOARD_ITEM* item = dynamic_cast<BOARD_ITEM*>( selection.GetTopLeftItem() ) )
{
    selection.SetReferencePoint( item->GetPosition() );
}

// Строка 1492: ЗАПУСТИТЬ MOVE TOOL
return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
```

---

## РЕЗЮМЕ: ЧЕТЫРЕ ФУНКЦИИ В КОНТЕКСТЕ

### 1. GetReferencePoint() (selection.cpp:169)
**Роль:** Получить якорную точку выделения

```cpp
VECTOR2I SELECTION::GetReferencePoint() const
{
    if( m_referencePoint )
        return *m_referencePoint;
    else
        return GetBoundingBox().Centre();
}
```

### 2. SaveSelection() (kicad_clipboard.cpp:118)
**Роль:** Сохранить выделение в буфер обмена с нормализацией координат

```cpp
void CLIPBOARD_IO::SaveSelection( const PCB_SELECTION& aSelected, bool isFootprintEditor )
{
    VECTOR2I refPoint( 0, 0 );
    if( aSelected.HasReferencePoint() )
        refPoint = aSelected.GetReferencePoint();
    
    // ...
    
    // НОРМАЛИЗАЦИЯ:
    newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );  // или
    copy->Move( -refPoint );
    
    Format( ... );
}
```

### 3. copyToClipboard() (edit_tool.cpp:3342)
**Роль:** Выбрать якорную точку и скопировать в буфер обмена

```cpp
int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    // Выбрать якорную точку:
    if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
        pickReferencePoint( /* интерактивно */ );
    else
        refPoint = grid.BestDragOrigin( /* автоматически */ );
    
    selection.SetReferencePoint( refPoint );  // 🔴 КРИТИЧНО!
    io.SaveSelection( selection, ... );        // 🔴 СОХРАНИТЬ!
}
```

### 4. placeBoardItems() (pcb_control.cpp:1365)
**Роль:** Переустановить якорную точку и запустить move tool для интерактивного размещения

```cpp
bool PCB_CONTROL::placeBoardItems( BOARD_COMMIT* aCommit, ... )
{
    // ... подготовка элементов ...
    
    PCB_SELECTION& selection = selectionTool->GetSelection();
    
    if( selection.Size() > 0 )
    {
        // Переустановить якорную точку:
        if( aAnchorAtOrigin )
            selection.SetReferencePoint( VECTOR2I( 0, 0 ) );  // 🔴 КРИТИЧНО!
        else
            selection.SetReferencePoint( item->GetPosition() );
        
        // Запустить move tool:
        return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );  // 🔴 ВАЖНОЕ!
    }
}
```

---

## ПОЛНЫЙ ЦИКЛ (Copy → SaveSelection → Parse → placeBoardItems → move)

```
┌─────────────────────────────────────────────────────────────────┐
│                   КОПИРОВАНИЕ (Ctrl+C)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  copyToClipboard() [edit_tool.cpp:3342]                         │
│    1. RequestSelection() → получить выделение                   │
│    2. Выбрать якорную точку:                                    │
│       ├─ pickReferencePoint() или                               │
│       └─ grid.BestDragOrigin()                                  │
│    3. SetReferencePoint(refPoint)  ◄─── якорная точка в выделение
│    4. io.SaveSelection()           ◄─── сохранить в буфер      │
│         │                                                        │
│         └─→ SaveSelection() [kicad_clipboard.cpp:118]          │
│              1. refPoint = GetReferencePoint()  ◄─── получить   │
│              2. for(item): Move(item, -refPoint) ◄─ НОРМАЛИЗАЦИЯ
│              3. Format() → S-expression                        │
│              4. wxTheClipboard  ◄─── системный буфер          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
              В буфере обмена: координаты → (0,0)

┌─────────────────────────────────────────────────────────────────┐
│                    ВСТАВЛЕНИЕ (Ctrl+V)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  PCB_CONTROL::Paste() [pcb_control.cpp:1018]                    │
│    1. CLIPBOARD_IO::Parse()  ◄─── парсить из буфера            │
│    2. placeBoardItems()      ◄─── разместить элементы          │
│         │                                                        │
│         └─→ placeBoardItems() [pcb_control.cpp:1365]           │
│              1. Выделить элементы                              │
│              2. SetReferencePoint()  ◄─── переустановить якорн. точку
│                 (0,0) или GetTopLeftItem()                      │
│              3. RunSynchronousAction(move)  ◄─ запустить MOVE  │
│                                                                   │
│              move TOOL (интерактивно):                          │
│                 1. Показать "фантом" элементов                │
│                 2. Пользователь перетаскивает якорную точку   │
│                 3. Элементы следуют за якорной точкой         │
│                 4. При отпускании мыши элементы размещаются   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
                Элементы размещены на платеboard
```

---

**Документация подготовлена:** 11.02.2026  
**Источник:** KiCAD 9.0.7 исходный код  
**Статус:** ПОЛНЫЙ И ГОТОВ К ИСПОЛЬЗОВАНИЮ
