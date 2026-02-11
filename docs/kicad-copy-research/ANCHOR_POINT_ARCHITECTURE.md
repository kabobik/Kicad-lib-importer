# Расширенный анализ anchor point: Архитектура и История

**Дата:** 11 февраля 2026  
**Версия KiCAD:** 9.0.7  
**Уровень деталей:** Архитектурный

---

## ЧАСТЬ 1: АРХИТЕКТУРНАЯ ДИАГРАММА

### Классовая иерархия выделения:

```
┌──────────────────────────────────────┐
│        SELECTION (base class)        │
│   include/tool/selection.h (L.40)   │
├──────────────────────────────────────┤
│ - m_referencePoint: std::optional    │
│ - m_items: std::deque<EDA_ITEM*>     │
│ - m_itemsOrders: std::deque<int>     │
│ - m_orderCounter: int                │
│ - m_lastAddedItem: EDA_ITEM*         │
│ - m_isHover: bool                    │
├──────────────────────────────────────┤
│ МЕТОДЫ (PUBLIC):                     │
│ + GetReferencePoint(): VECTOR2I (L169) │
│ + HasReferencePoint(): bool (L216)   │
│ + SetReferencePoint(aP: VECTOR2I)    │
│ + ClearReferencePoint()              │
│ + GetBoundingBox(): BOX2I (fallback) │
│ + GetCenter(): VECTOR2I              │
└──────────────────────────────────────┘
                   ▲
                   │ наследуется
                   │
         ┌─────────┴─────────┐
         │                   │
    ┌────────────────┐  ┌──────────────────┐
    │  PCB_SELECTION │  │  SCH_SELECTION   │
    │  (pcbnew)      │  │  (eeschema)      │
    └────────────────┘  └──────────────────┘
```

### Иерархия I/O операций:

```
┌─────────────────────────────────────────┐
│      PCB_IO_KICAD_SEXPR (base class)    │
│      pcbnew/plugins/kicad/pcb_parser.h │
├─────────────────────────────────────────┤
│ Методы парсинга/форматирования S-expr  │
└─────────────────────────────────────────┘
           ▲
           │ наследуется
           │
┌─────────────────────────────────────────┐
│    CLIPBOARD_IO                         │
│    pcbnew/kicad_clipboard.h (L.53)     │
├─────────────────────────────────────────┤
│ +SaveSelection(aSelected: PCB_SELECTION)│
│ +SaveBoard(fileName, aBoard, ...)       │
│ +Parse(): BOARD_ITEM*                  │
│ +LoadBoard(fileName, ...): BOARD*       │
│ -clipboardReader(): wxString            │
│ -clipboardWriter(aData: wxString)       │
├─────────────────────────────────────────┤
│ КЛЮЧЕВОЙ МЕТОД:                         │
│ SaveSelection (L.118):                  │
│  1. refPoint = aSelected.GetReferencePoint()
│  2. for(item):                          │
│     └─ Move(item, -refPoint)     ← НОРМАЛИЗАЦИЯ
│  3. Format() → S-expression             │
│  4. clipboardWriter() → wxTheClipboard │
└─────────────────────────────────────────┘
```

### Взаимосвязь EDIT_TOOL и PCB_CONTROL:

```
┌────────────────────────────────┐
│         EDIT_TOOL              │
│  pcbnew/tools/edit_tool.cpp    │
├────────────────────────────────┤
│ copyToClipboard() (L.3342)      │
│  ├─ RequestSelection()          │
│  ├─ Выбрать anchor point:       │
│  │  ├─ pickReferencePoint() или │
│  │  └─ grid.BestDragOrigin()    │
│  ├─ SetReferencePoint(refPoint)│
│  └─ CLIPBOARD_IO::SaveSelection()
│      └─→ СОХРАНИТЬ В БУФЕР    │
└────────────────────────────────┘
            ↓ (Ctrl+V)
┌────────────────────────────────┐
│      PCB_CONTROL               │
│  pcbnew/tools/pcb_control.cpp  │
├────────────────────────────────┤
│ Paste() (L.1018)               │
│  ├─ CLIPBOARD_IO::Parse()      │
│  │  └─→ получить clipItem      │
│  └─ placeBoardItems()          │
│      (L.1365):                 │
│      ├─ Выделить элементы      │
│      ├─ SetReferencePoint():    │
│      │  ├─ (0,0) или            │
│      │  └─ GetTopLeftItem()     │
│      └─ RunSynchronousAction(   │
│         PCB_ACTIONS::move)      │
│          └─→ MOVE TOOL          │
│            (интерактивное       │
│             перемещение)        │
└────────────────────────────────┘
```

---

## ЧАСТЬ 2: ПОДРОБНЫЙ КОД С КОММЕНТАРИЯМИ

### GetReferencePoint() с подробными комментариями:

```cpp
// Файл: common/tool/selection.cpp (строка 169)
// Класс: SELECTION
// Назначение: Получить якорную точку выделения

VECTOR2I SELECTION::GetReferencePoint() const
{
    // Проверить, есть ли явно установленная якорная точка
    // m_referencePoint типа std::optional<VECTOR2I>
    // Может быть пусто (nullopt) или содержать значение
    if( m_referencePoint )
        // Якорная точка установлена явно
        // Возвращаем её значение (разыменовываем optional)
        return *m_referencePoint;
    else
        // Якорная точка не установлена
        // FALLBACK МЕХАНИЗМ: вернуть центр bounding box
        // GetBoundingBox() возвращает OX2I (oriented box 2D)
        // .Centre() вычисляет центр прямоугольника
        // 
        // КРИТИЧНО: Это гарантирует, что метод НИКОГДА не вернёт
        // null/undefined/invalid value, всегда есть валидная точка
        return GetBoundingBox().Centre();
}
```

### SaveSelection() - критичная часть нормализации:

```cpp
// Файл: pcbnew/kicad_clipboard.cpp (строка 118)
// Класс: CLIPBOARD_IO : public PCB_IO_KICAD_SEXPR
// Назначение: Сохранить выделённые элементы в буфер обмена

void CLIPBOARD_IO::SaveSelection( const PCB_SELECTION& aSelected, bool isFootprintEditor )
{
    // ══════════════════════════════════════════════════════════════
    // ШАГ 1: Инициализация якорной точки
    // ══════════════════════════════════════════════════════════════
    
    // Инициализируем якорную точку по умолчанию
    VECTOR2I refPoint( 0, 0 );

    // Проверяем, есть ли выделение
    if( aSelected.Empty() )
        return;

    // КРИТИЧНО: Получить якорную точку из выделения
    // Это может быть:
    //  - явно установленная точка, или
    //  - центр bounding box (fallback в GetReferencePoint())
    if( aSelected.HasReferencePoint() )
        refPoint = aSelected.GetReferencePoint();

    // На этом этапе refPoint имеет валидное значение в абсолютных
    // координатах платы (BOARD coordinates)
    
    // ══════════════════════════════════════════════════════════════
    // ШАГ 2: Подготовка сетевого маппинга
    // ══════════════════════════════════════════════════════════════
    
    m_mapping->SetBoard( m_board );
    // Это обеспечивает последовательные номера сетей при сохранении

    // ══════════════════════════════════════════════════════════════
    // ШАГ 3: Обработка выбранных элементов
    // ══════════════════════════════════════════════════════════════

    if( aSelected.Size() == 1 && aSelected.Front()->Type() == PCB_FOOTPRINT_T )
    {
        // СЛУЧАЙ 1: Единственный выделённый элемент - это footprint
        // (т.е. скопировано целое посадочное место)

        const FOOTPRINT* footprint = static_cast<FOOTPRINT*>( aSelected.Front() );
        FOOTPRINT newFootprint( *footprint );  // Клон

        // Очистить сетевые коды (элементы без сети в буфере обмена)
        for( PAD* pad : newFootprint.Pads() )
            pad->SetNetCode( 0 );

        newFootprint.SetLocked( false );  // Копия не может быть заблокирована

        // ═══════════════════════════════════════════════════════════
        // КРИТИЧНО: НОРМАЛИЗАЦИЯ КООРДИНАТ К (0, 0)
        // ═══════════════════════════════════════════════════════════
        // Move( -refPoint ) смещает элемент на вектор (-refPoint)
        // 
        // Пример:
        //  Если refPoint = (100, 200) на плате
        //  Элемент был в (150, 250)
        //  После Move(-refPoint) элемент будет в (50, 50)
        //  
        // Т.е. якорная точка становится (0, 0) в буфере обмена
        newFootprint.Move( VECTOR2I( -refPoint.x, -refPoint.y ) );

        // Форматировать в S-expression (текстовый формат KiCAD)
        Format( static_cast<BOARD_ITEM*>( &newFootprint ) );

        newFootprint.SetParent( nullptr );
        newFootprint.SetParentGroup( nullptr );
    }
    else if( isFootprintEditor )
    {
        // СЛУЧАЙ 2: Редактор footprint - копируем элементы в footprint
        
        FOOTPRINT partialFootprint( m_board );
        // ... инициализация ...

        for( EDA_ITEM* item : aSelected )
        {
            if( !item->IsBOARD_ITEM() )
                continue;

            BOARD_ITEM* boardItem = static_cast<BOARD_ITEM*>( item );
            BOARD_ITEM* copy = nullptr;

            // Обработка разных типов элементов...
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
                copy = static_cast<BOARD_ITEM*>( item->GetParent()->Clone() );
            }
            else
            {
                copy = static_cast<BOARD_ITEM*>( boardItem->Clone() );
            }

            // Очистить сетевые коды для PAD'ов
            if( PAD* pad = dynamic_cast<PAD*>( copy ) )
                pad->SetNetCode( 0 );

            copy->SetParentGroup( nullptr );

            // Добавить в partial footprint
            partialFootprint.Add( copy );

            // ... обработка потомков (если это группа или генератор) ...

            // ═══════════════════════════════════════════════════════════
            // КРИТИЧНО: НОРМАЛИЗАЦИЯ КАЖДОГО СКОПИРОВАННОГО ЭЛЕМЕНТА
            // ═══════════════════════════════════════════════════════════
            // Move( -refPoint ) переносит элемент так, чтобы
            // якорная точка стала (0, 0) в буфере обмена
            copy->Move( -refPoint );
        }

        // Форматировать в S-expression
        Format( static_cast<BOARD_ITEM*>( &partialFootprint ) );
    }
    // если это полная плата, обработка аналогична...
}
```

### copyToClipboard() с пояснениями:

```cpp
// Файл: pcbnew/tools/edit_tool.cpp (строка 3342)
// Класс: EDIT_TOOL : public PCB_TOOL_BASE
// Команды: ACTIONS::copy, ACTIONS::cut, PCB_ACTIONS::copyWithReference
// Назначение: Скопировать выделение в буфер обмена

int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    // ══════════════════════════════════════════════════════════════
    // ШАГ 1: Инициализация
    // ══════════════════════════════════════════════════════════════
    
    CLIPBOARD_IO io;  // Объект для работы с буфером обмена
    PCB_GRID_HELPER grid(  // Помощник для привязки к сетке
        m_toolMgr,
        getEditFrame<PCB_BASE_EDIT_FRAME>()->GetMagneticItemsSettings()
    );

    // Создать TOOL_EVENT для интерактивного выбора якорной точки
    TOOL_EVENT selectReferencePoint(
        aEvent.Category(),
        aEvent.Action(),
        "pcbnew.InteractiveEdit.selectReferencePoint",
        TOOL_ACTION_SCOPE::AS_GLOBAL
    );

    frame()->PushTool( selectReferencePoint );  // Зарегистрировать инструмент
    Activate();  // Активировать текущий инструмент

    // ══════════════════════════════════════════════════════════════
    // ШАГ 2: Получить выделение от пользователя
    // ══════════════════════════════════════════════════════════════
    
    PCB_SELECTION& selection = m_selectionTool->RequestSelection(
        // ФИЛЬТР: какие элементы исключить из выделения
        []( const VECTOR2I& aPt, GENERAL_COLLECTOR& aCollector, PCB_SELECTION_TOOL* sTool )
        {
            for( int i = aCollector.GetCount() - 1; i >= 0; --i )
            {
                BOARD_ITEM* item = aCollector[i];

                // Не копировать текст footprint если скопирован сам footprint
                if( ( item->Type() == PCB_FIELD_T || item->Type() == PCB_TEXT_T )
                    && aCollector.HasItem( item->GetParentFootprint() ) )
                {
                    aCollector.Remove( item );
                }
                // Не копировать маркеры DRC ошибок
                else if( item->Type() == PCB_MARKER_T )
                {
                    aCollector.Remove( item );
                }
            }
        },
        
        // Второй параметр: запросить ли пользователю разблокировку элементов?
        // Да, если это команда CUT и не редактор footprint
        aEvent.IsAction( &ACTIONS::cut ) && !m_isFootprintEditor
    );

    // ══════════════════════════════════════════════════════════════
    // ШАГ 3: Обработка выделения
    // ══════════════════════════════════════════════════════════════
    
    if( !selection.Empty() )
    {
        // Собрать все BOARD_ITEM элементы из выделения
        std::vector<BOARD_ITEM*> items;

        for( EDA_ITEM* item : selection )
        {
            if( item->IsBOARD_ITEM() )
                items.push_back( static_cast<BOARD_ITEM*>( item ) );
        }

        // ══════════════════════════════════════════════════════════════
        // ШАГ 4: ОПРЕДЕЛИТЬ ЯКОРНУЮ ТОЧКУ
        // ══════════════════════════════════════════════════════════════
        
        VECTOR2I refPoint;

        // ВАРИАНТ A: Команда copyWithReference - пользователь выбирает точку
        if( aEvent.IsAction( &PCB_ACTIONS::copyWithReference ) )
        {
            // Запустить интерактивное выбор якорной точки
            // Пользователь кликает на плате чтобы выбрать точку
            if( !pickReferencePoint(
                _( "Select reference point for the copy..." ),
                _( "Selection copied" ),
                _( "Copy canceled" ),
                refPoint  // Выходной параметр
            ) )
            {
                // Пользователь отменил
                frame()->PopTool( selectReferencePoint );
                return 0;
            }
        }
        else
        {
            // ВАРИАНТ B: Обычное копирование (Ctrl+C)
            // Автоматически выбрать оптимальную точку для перемещения
            //
            // grid.BestDragOrigin() анализирует:
            //  - Позицию курсора
            //  - Позиции всех выбранных элементов
            //  - Магнитную привязку (snap to grid)
            // И возвращает оптимальную точку для перемещения
            // (обычно левый верхний элемент или близкий узел сетки)
            
            refPoint = grid.BestDragOrigin(
                getViewControls()->GetCursorPosition(),
                items
            );
        }

        // ══════════════════════════════════════════════════════════════
        // ШАГ 5: УСТАНОВИТЬ ЯКОРНУЮ ТОЧКУ В ВЫДЕЛЕНИИ
        // ══════════════════════════════════════════════════════════════
        
        // Это КРИТИЧНО: SetReferencePoint() сохраняет якорную точку
        // в объекте PCB_SELECTION, который будет передан в SaveSelection()
        selection.SetReferencePoint( refPoint );

        // ══════════════════════════════════════════════════════════════
        // ШАГ 6: СОХРАНИТЬ В БУФЕР ОБМЕНА
        // ══════════════════════════════════════════════════════════════
        
        io.SetBoard( board() );  // Установить контекст платы
        
        // ГЛАВНЫЙ ВЫЗОВ: SaveSelection() делает всю работу
        //  - Получит якорную точку из selection (которую мы только что установили)
        //  - Нормализует координаты элементов к (0, 0)
        //  - Форматирует в S-expression
        //  - Записывает в wxTheClipboard
        io.SaveSelection( selection, m_isFootprintEditor );
        
        frame()->SetStatusText( _( "Selection copied" ) );
    }

    frame()->PopTool( selectReferencePoint );

    if( selection.IsHover() )
        m_selectionTool->ClearSelection();

    return 0;
}
```

### placeBoardItems() - использование якорной точки при вставке:

```cpp
// Файл: pcbnew/tools/pcb_control.cpp (строка 1365)
// Класс: PCB_CONTROL : public PCB_TOOL_BASE
// Назначение: Разместить скопированные элементы с интерактивным перемещением

bool PCB_CONTROL::placeBoardItems( BOARD_COMMIT* aCommit, 
                                   std::vector<BOARD_ITEM*>& aItems,
                                   bool aIsNew,  // true для новых элементов из буфера
                                   bool aAnchorAtOrigin,  // якорная точка в (0,0)?
                                   bool aReannotateDuplicates )  // переаннотировать duplicates?
{
    // ══════════════════════════════════════════════════════════════
    // ШАГ 1: Очистить текущее выделение
    // ══════════════════════════════════════════════════════════════
    
    m_toolMgr->RunAction( PCB_ACTIONS::selectionClear );

    PCB_SELECTION_TOOL* selectionTool = m_toolMgr->GetTool<PCB_SELECTION_TOOL>();
    std::vector<BOARD_ITEM*> itemsToSel;
    itemsToSel.reserve( aItems.size() );

    // ══════════════════════════════════════════════════════════════
    // ШАГ 2: Обработать каждый элемент
    // ══════════════════════════════════════════════════════════════
    
    for( BOARD_ITEM* item : aItems )
    {
        if( aIsNew )
        {
            // Новому элементу назначить новый UUID (уникальный ID)
            const_cast<KIID&>( item->m_Uuid ) = KIID();

            // Обработать потомков (для групп и генераторов)
            item->RunOnDescendants(
                []( BOARD_ITEM* aChild )
                {
                    const_cast<KIID&>( aChild->m_Uuid ) = KIID();
                }
            );

            // Добавить в группу если нужно
            if( selectionTool->GetEnteredGroup() && !item->GetParentGroup() )
                selectionTool->GetEnteredGroup()->AddItem( item );

            // Установить родителя (плату)
            item->SetParent( board() );
        }

        // Обновить атрибуты элемента (может зависеть от платы)
        if( BaseType( item->Type() ) == PCB_DIMENSION_T )
        {
            static_cast<PCB_DIMENSION_BASE*>( item )->UpdateUnits();
        }
        else if( item->Type() == PCB_FOOTPRINT_T )
        {
            FOOTPRINT* footprint = static_cast<FOOTPRINT*>( item );

            if( aIsNew )
                footprint->SetPath( KIID_PATH() );

            for( BOARD_ITEM* dwg : footprint->GraphicalItems() )
            {
                if( BaseType( dwg->Type() ) == PCB_DIMENSION_T )
                    static_cast<PCB_DIMENSION_BASE*>( dwg )->UpdateUnits();
            }
        }

        // Добавить в список выделяемых элементов
        if( !item->GetParentGroup() || !alg::contains( aItems, item->GetParentGroup() ) )
            itemsToSel.push_back( item );
    }

    // ══════════════════════════════════════════════════════════════
    // ШАГ 3: Выделить элементы
    // ══════════════════════════════════════════════════════════════
    
    EDA_ITEMS toSel( itemsToSel.begin(), itemsToSel.end() );
    m_toolMgr->RunAction<EDA_ITEMS*>( PCB_ACTIONS::selectItems, &toSel );

    // Переаннотировать дубликаты если нужно
    if( aReannotateDuplicates && m_isBoardEditor )
        m_toolMgr->GetTool<BOARD_REANNOTATE_TOOL>()->ReannotateDuplicatesInSelection();

    // ══════════════════════════════════════════════════════════════
    // ШАГ 4: Добавить элементы в commit (для undo/redo)
    // ══════════════════════════════════════════════════════════════
    
    for( BOARD_ITEM* item : aItems )
    {
        if( aIsNew )
            aCommit->Add( item );  // Новый элемент добавляется
        else
            aCommit->Added( item );  // Существующий элемент отмечен изменённым
    }

    PCB_SELECTION& selection = selectionTool->GetSelection();

    // ══════════════════════════════════════════════════════════════
    // ШАГ 5: КРИТИЧНО - УСТАНОВИТЬ ЯКОРНУЮ ТОЧКУ ДЛЯ ПЕРЕМЕЩЕНИЯ
    // ══════════════════════════════════════════════════════════════
    
    if( selection.Size() > 0 )
    {
        // Два варианта установки якорной точки:
        
        if( aAnchorAtOrigin )
        {
            // ВАРИАНТ A: Якорная точка в (0, 0)
            // При вставке элементы будут "зависать" над точкой (0, 0)
            // Пользователь переносит элементы с этой точкой
            
            selection.SetReferencePoint( VECTOR2I( 0, 0 ) );
        }
        else if( BOARD_ITEM* item = dynamic_cast<BOARD_ITEM*>( selection.GetTopLeftItem() ) )
        {
            // ВАРИАНТ B: Якорная точка в левый верхний элемент
            // Пользователь переносит элементы, захватив их за верхний-левый угол
            // (или за ближайший элемент)
            
            selection.SetReferencePoint( item->GetPosition() );
        }

        // Установить позицию курсора (где видит пользователь мышку)
        getViewControls()->SetCursorPosition( 
            getViewControls()->GetMousePosition(), 
            false  // не двигать параллельно
        );

        // Отправить событие выделения (другие инструменты узнают что-то выбрано)
        m_toolMgr->ProcessEvent( EVENTS::SelectedEvent );

        // ══════════════════════════════════════════════════════════════
        // ШАГ 6: ЗАПУСТИТЬ MOVE TOOL С УСТАНОВЛЕННОЙ ЯКОРНОЙ ТОЧКОЙ
        // ══════════════════════════════════════════════════════════════
        
        // Это СИНХРОННЫЙ вызов - программа ждёт пока пользователь
        // закончит перемещать элементы
        //
        // MOVE TOOL использует:
        //  - Выделение (selection) с установленной якорной точкой
        //  - Commit для отслеживания изменений (undo/redo)
        //
        // Пользователь:
        //  1. Видит "фантом" (preview) выбранных элементов
        //  2. Перетаскивает их мышкой (якорная точка следует за курсором)
        //  3. Отпускает кнопку мыши
        //  4. Элементы размещаются на новом месте
        
        return m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
    }

    return true;
}
```

---

## ЧАСТЬ 3: ИСТОРИЯ КОДА

### Почему выбран этот алгоритм?

**Исторический контекст (предположение на основе анализа):**

1. **std::optional<VECTOR2I> vs простой VECTOR2I**
   - Использование `std::optional` позволяет различить:
     - "якорная точка явно установлена" (например, пользователем)
     - "якорная точка не установлена, использовать fallback"
   - Это лучше чем специальные значения типа (-1, -1) или (0, 0)

2. **Fallback на GetBoundingBox().Centre()**
   - Гарантирует что метод никогда не вернёт invalid значение
   - Разумный дефолт: центр выделения - это интуитивный центр тяжести

3. **Нормализация координат при сохранении**
   ```cpp
   copy->Move( -refPoint );  // Якорная точка → (0, 0) в буфере
   ```
   - Это позволяет копировать выделение на другие платы без пересчётов
   - Буфер обмена содержит РЕЛЯТИВНЫЕ координаты

4. **Две стратегии выбора anchor point при копировании**
   - `copyWithReference`: интерактивный выбор (для мощных пользователей)
   - `copy`: автоматический (для чистоты и скорости)

### Возможные улучшения (спекуляция):

| Проблема | Текущее решение | Возможное улучшение |
|----------|-----------------|-------------------|
| Anchor point всегда центр при fallback | `GetBoundingBox().Centre()` | Конфигурируемая стратегия (центр, левый верхний, правый нижний и т.д.) |
| Нет визуального указателя якорной точки | Якорная точка невидима | Отрисовать маркер якорной точки при копировании |
| Только относительное позиционирование | Всегда одна якорная точка на выделение | Несколько якорных точек для сложных выделений |
| Якорная точка теряется при деселекте | `ClearReferencePoint()` при выбросе | Сохранять якорную точку в истории clipboard |

---

## ВЫВОДЫ

### Три функции, три роли:

| Функция | Файл | Роль |
|---------|------|------|
| **GetReferencePoint()** | selection.cpp:169 | **Получить и нормализовать** якорную точку |
| **SaveSelection()** | kicad_clipboard.cpp:118 | **Сохранить и нормализовать** координаты в буфер |
| **copyToClipboard()** | edit_tool.cpp:3342 | **Выбрать и установить** якорную точку перед сохранением |
| **placeBoardItems()** | pcb_control.cpp:1365 | **Переустановить** якорную точку перед вставкой |

### Критичные инварианты:

1. **Якорная точка в буфере обмена ВСЕГДА (0, 0)**
   ```cpp
   copy->Move( -refPoint );  // В SaveSelection()
   ```

2. **GetReferencePoint() НИКОГДА не вернёт null/invalid**
   ```cpp
   if( m_referencePoint )
       return *m_referencePoint;
   else
       return GetBoundingBox().Centre();  // FALLBACK
   ```

3. **Якорная точка переустанавливается ПРИ ВСТАВКЕ**
   ```cpp
   selection.SetReferencePoint( ... );  // В placeBoardItems()
   ```

4. **Move tool является синхронным (ждёт пользователя)**
   ```cpp
   m_toolMgr->RunSynchronousAction( PCB_ACTIONS::move, aCommit );
   ```

---

**Документация подготовлена:** 11.02.2026  
**Уровень деталей:** Архитектурный (код с комментариями)  
**Статус:** АНАЛИЗ УГЛУБЛЁННЫЙ
