# Подзадача 4: Проектирование нового механизма выбора anchor point

**Дата:** 11 февраля 2026  
**Версия KiCad:** 9.0.7  
**Уровень деталей:** Архитектурный дизайн  
**Предыдущие подзадачи:** 1 (анализ), 2 (логика), 3 (интеграция)

---

## РЕЗЮМЕ

Этот документ решает задачу **интерактивного выбора точки привязки (anchor point) при копировании** в KiCad 9.0.7. Мы спроектировали три варианта UX, проанализировали архитектуру, и дали рекомендацию.

**Рекомендуемый подход:** Вариант C (гибридный) с минимальными изменениями существующего кода.

---

## ЧАСТЬ 1: КОНТЕКСТ ИЗ ПРЕДЫДУЩИХ ПОДЗАДАЧ

### Текущая архитектура

```
┌──────────────────────────────┐
│  Пользователь копирует (Ctrl+C)
└──────────────────┬───────────┘
                   │
                   ▼
┌──────────────────────────────┐
│  copyToClipboard()           │
│  (edit_tool.cpp, L.3342)     │
├──────────────────────────────┤
│ 1. RequestSelection()         │
│ 2. BestDragOrigin() → точка   │
│ 3. SetReferencePoint(точка)   │
│ 4. SaveSelection()            │
└──────────────────┬───────────┘
                   │
                   ▼
┌──────────────────────────────┐
│  SaveSelection()             │
│  (kicad_clipboard.cpp, L.118)│
├──────────────────────────────┤
│ 1. GetReferencePoint()        │
│ 2. Move(item, -refPoint)      │
│    → нормализация в (0,0)     │
│ 3. Format() → S-expr          │
│ 4. clipboardWriter()          │
│    → буфер обмена             │
└──────────────────┬───────────┘
                   │
                   ▼
┌──────────────────────────────┐
│  Вставка (Ctrl+V)            │
│  placeBoardItems()           │
│  (pcb_control.cpp, L.1486)   │
└──────────────────────────────┘
```

### Ключевые инварианты

| Принцип | Реализация | Файл, строка |
|---------|-----------|--------------|
| **Anchor point решение** | GetReferencePoint() → явно или fallback | selection.cpp, L.169 |
| **Fallback механизм** | Если нет явной точки → центр bbox | selection.cpp, L.171 |
| **Нормализация** | Move(item, -refPoint) → (0,0) | kicad_clipboard.cpp, L.199 |
| **Опциональность** | std::optional<VECTOR2I> m_referencePoint | selection.h, L.40 |

---

## ЧАСТЬ 2: АНАЛИЗ ТРЕБОВАНИЙ

### Вопрос 1: Как пользователь выбирает anchor point?

#### Текущее положение
- **Существующее решение:** автоматический выбор через `BestDragOrigin()`
- **Проблема:** иногда выбор не соответствует ожиданиям пользователя
- **Что нужно:** дать пользователю возможность ПЕРЕОПРЕДЕЛИТЬ выбор

#### Возможные процессы выбора

| Процесс | Описание | Примеры |
|---------|---------|---------|
| **A1: Интерактивный клик** | Копирование с модификатором → клик на плате | Shift+Ctrl+C → выбрать точку |
| **A2: Диалог со списком** | Диалог выбирает из предопределённых точек | Центр / Первый элемент / Custom X,Y |
| **A3: Комбинированный (Recomm.)** | Диалог с опцией интерактивного выбора | Menu: Copy → "Custom anchor point?" → выбрать |

### Вопрос 2: Архитектура изменений

#### Новые компоненты

```
┌─────────────────────────────────────────┐
│ ANCHOR_POINT_TOOL (новый класс)         │
├─────────────────────────────────────────┤
│ Назначение: Интерактивный выбор точки   │
│                                          │
│ Методы:                                  │
│ + PickPoint(): VECTOR2I                  │
│ + SelectFromDialog(): VECTOR2I (опция)   │
│ + GetPresets(): std::vector<Preset>      │
└─────────────────────────────────────────┘
```

#### Модификации существующих классов

```cpp
// В EDIT_TOOL (edit_tool.h, edit_tool.cpp)
class EDIT_TOOL
{
private:
    // NEW: Флаг для использования пользовательского anchor point
    bool m_useCustomAnchorPoint = false;
    
    // NEW: Хранилище выбранной точки (до SaveSelection)
    std::optional<VECTOR2I> m_customAnchorPoint;
    
    // NEW: Метод для обработки пользовательского выбора
    int pickAnchorPoint( const TOOL_EVENT& aEvent );
    
    // MODIFIED: Добавить параметр
    void copyToClipboard( bool aUseCustomAnchor = false );
};
```

#### Диалого-окно

```cpp
// Новый файл: pcbnew/dialogs/dialog_anchor_point_selection.h
class DIALOG_ANCHOR_POINT_SELECTION : public wxDialog
{
public:
    DIALOG_ANCHOR_POINT_SELECTION( wxWindow* aParent, const PCB_SELECTION& aSelection );
    
    // Получить выбранный режим
    enum ANCHOR_MODE
    {
        ANCHOR_DEFAULT = 0,        // Использовать автоматический выбор
        ANCHOR_CENTER,             // Центр bbox
        ANCHOR_FIRST_ITEM,         // Первый элемент в выделении
        ANCHOR_TOP_LEFT,           // Верхний левый угол
        ANCHOR_CUSTOM,             // Интерактивный выбор
        ANCHOR_CUSTOM_COORDS       // Ввести X,Y вручную
    };
    
    ANCHOR_MODE GetSelectedMode() const;
    VECTOR2I GetCustomCoordinates() const;
    bool UseInteractiveSelection() const;
};
```

---

## ЧАСТЬ 3: ТРИ ВАРИАНТА UX И АРХИТЕКТУРЫ

### Вариант A: Интерактивный клик (простейший в реализации)

#### Диаграмма взаимодействия

```
┌────────────────────────────────────────┐
│ Пользователь нажимает Shift+Ctrl+C      │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ copyToClipboard( useCustom=true )       │
│ (edit_tool.cpp)                         │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ pickAnchorPoint( aEvent )               │
│ (перехватывает мышь)                    │
│                                         │
│ Инструкция: "Клик на точку привязки"  │
└────────────────┬───────────────────────┘
                 │
         (пользователь кликает)
                 │
                 ▼
┌────────────────────────────────────────┐
│ OnMouseClick( aEvent )                  │
│                                         │
│ m_customAnchorPoint = aEvent.Position() │
│ SetReferencePoint( m_customAnchorPoint )│
│ SaveSelection()                         │
│ → БУФЕР ОБМЕНА                         │
└────────────────────────────────────────┘
```

#### Код реализации

```cpp
// edit_tool.cpp

int EDIT_TOOL::copyToClipboardWithCustomAnchor( const TOOL_EVENT& aEvent )
{
    // Переменные состояния
    m_useCustomAnchorPoint = true;
    m_customAnchorPoint = std::nullopt;
    
    // Запросить выделение
    if( !selection().GetSize() )
    {
        m_toolMgr->RunAction( PCB_ACTIONS::selectionCursor );
        if( !selection().GetSize() )
            return 0;
    }
    
    // Показать инструкцию пользователю
    m_frame->ShowInfoBarMessage( _( "Click on the anchor point for the selection" ),
                                 wxICON_INFORMATION );
    
    // Перейти в режим выбора точки
    return pickAnchorPoint( aEvent );
}

int EDIT_TOOL::pickAnchorPoint( const TOOL_EVENT& aEvent )
{
    // Активировать захват событий мыши
    while( OwnLoopAndDorists() )
    {
        const TOOL_EVENT& event = Wait();
        
        if( event.IsClick( BUT_LEFT ) )
        {
            // Пользователь кликнул на точку
            VECTOR2I clickPoint = getViewControls()->GetCursorPosition();
            
            // Установить anchor point
            SetReferencePointForSelection( clickPoint );
            
            // Обычное копирование
            copyToClipboard( false );  // useCustom=false, так как уже установили
            
            break;
        }
        else if( event.IsActivate() || event.IsCancel() )
        {
            break;
        }
    }
    
    // Очистить флаг
    m_useCustomAnchorPoint = false;
    return 0;
}

// Вспомогательный метод
void EDIT_TOOL::SetReferencePointForSelection( const VECTOR2I& aPoint )
{
    PCB_SELECTION& sel = selection();
    sel.SetReferencePoint( aPoint );
}
```

#### Плюсы и минусы

| Аспект | Плюсы | Минусы |
|--------|-------|--------|
| **Простота реализации** | ✅ Минимум кода | ❌ Требует нового режима в tool |
| **UX** | ✅ Интуитивна (как Move tool) | ❌ Лишний клик для каждого копирования |
| **Совместимость** | ✅ Полностью обратная совместимость | ✅ Отдельный hotkey |
| **Предсказуемость** | ✅ Точный выбор пользователя | ❌ Требует внимания пользователя |

#### Когда использовать

- Пользователь часто копирует отдельные детали на специфичные позиции
- Нужна точка привязки в специальном месте (не центр, не край)
- Платы с нерегулярной геометрией

---

### Вариант B: Диалог со списком (наиболее гибкий)

#### Диаграмма взаимодействия

```
┌────────────────────────────────────────┐
│ Пользователь нажимает Ctrl+C            │
│ (обычное копирование)                  │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ copyToClipboard()                      │
│ (всегда с опцией диалога)              │
├────────────────────────────────────────┤
│ if( showAnchorDialog )                 │
│   showDialogAnchorPointSelection()      │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ DIALOG_ANCHOR_POINT_SELECTION           │
│                                         │
│ ┌──────────────────────────────────┐   │
│ │ [✓] Use default anchor point     │   │
│ │                                  │   │
│ │ [ ] Center of bounding box       │   │
│ │ [ ] First selected item          │   │
│ │ [ ] Top-left corner              │   │
│ │ [ ] Custom (interactive)     --> │←–– Клик запускает pickPoint
│ │ [ ] Manual coordinates:  X _  Y_ │   │
│ │                                  │   │
│ │    [OK]      [Cancel]            │   │
│ └──────────────────────────────────┘   │
└────────────────┬───────────────────────┘
                 │
         (пользователь выбирает)
                 │
                 ▼
┌────────────────────────────────────────┐
│ GetSelectedMode() → ANCHOR_MODE         │
│ ProcessSelection( mode )                │
│ → SetReferencePoint()                   │
│ → SaveSelection()                       │
│ → БУФЕР ОБМЕНА                         │
└────────────────────────────────────────┘
```

#### Код реализации

```cpp
// dialogs/dialog_anchor_point_selection.h

class DIALOG_ANCHOR_POINT_SELECTION : public wxDialog
{
public:
    enum ANCHOR_MODE
    {
        ANCHOR_DEFAULT = 0,
        ANCHOR_CENTER,
        ANCHOR_FIRST_ITEM,
        ANCHOR_TOP_LEFT,
        ANCHOR_CUSTOM,
        ANCHOR_MANUAL_COORDS
    };
    
    DIALOG_ANCHOR_POINT_SELECTION( wxWindow* aParent, const PCB_SELECTION& aSelection,
                                   const BOX2I& aBbox );
    
    ANCHOR_MODE GetSelectedMode() const;
    VECTOR2I GetCustomPoint() const;
    bool NeedsInteractiveSelection() const;
    
private:
    wxRadioButton* m_rbDefault;
    wxRadioButton* m_rbCenter;
    wxRadioButton* m_rbFirstItem;
    wxRadioButton* m_rbTopLeft;
    wxRadioButton* m_rbCustom;
    wxRadioButton* m_rbManual;
    
    wxTextCtrl* m_xInput;
    wxTextCtrl* m_yInput;
    wxButton* m_btnInteractive;
    
    const PCB_SELECTION& m_selection;
    BOX2I m_bbox;
    std::optional<VECTOR2I> m_customPoint;
    
    void onInteractiveClick( wxCommandEvent& aEvent );
};

// dialogs/dialog_anchor_point_selection.cpp

DIALOG_ANCHOR_POINT_SELECTION::DIALOG_ANCHOR_POINT_SELECTION( 
    wxWindow* aParent, 
    const PCB_SELECTION& aSelection,
    const BOX2I& aBbox ) 
    : wxDialog( aParent, wxID_ANY, _( "Anchor Point Selection" ) ),
      m_selection( aSelection ),
      m_bbox( aBbox )
{
    wxBoxSizer* mainSizer = new wxBoxSizer( wxVERTICAL );
    
    // Группа опций
    wxStaticBoxSizer* optionsSizer = 
        new wxStaticBoxSizer( wxVERTICAL, this, _( "Anchor Point" ) );
    
    m_rbDefault = new wxRadioButton( this, wxID_ANY, _( "Use automatic selection" ) );
    m_rbDefault->SetValue( true );
    optionsSizer->Add( m_rbDefault );
    
    m_rbCenter = new wxRadioButton( this, wxID_ANY, _( "Center of bounding box" ) );
    optionsSizer->Add( m_rbCenter );
    
    m_rbFirstItem = new wxRadioButton( this, wxID_ANY, _( "First selected item" ) );
    optionsSizer->Add( m_rbFirstItem );
    
    m_rbTopLeft = new wxRadioButton( this, wxID_ANY, _( "Top-left corner" ) );
    optionsSizer->Add( m_rbTopLeft );
    
    m_rbCustom = new wxRadioButton( this, wxID_ANY, _( "Custom point (click on board)" ) );
    optionsSizer->Add( m_rbCustom );
    
    // Интерактивная кнопка
    m_btnInteractive = new wxButton( this, wxID_ANY, _( "Select" ) );
    optionsSizer->Add( m_btnInteractive, 0, wxLEFT, 20 );
    m_btnInteractive->Bind( wxEVT_BUTTON, &DIALOG_ANCHOR_POINT_SELECTION::onInteractiveClick, this );
    
    // Manual coords
    m_rbManual = new wxRadioButton( this, wxID_ANY, _( "Manual coordinates:" ) );
    optionsSizer->Add( m_rbManual );
    
    wxBoxSizer* coordsSizer = new wxBoxSizer( wxHORIZONTAL );
    coordsSizer->Add( new wxStaticText( this, wxID_ANY, _( "X:" ) ) );
    m_xInput = new wxTextCtrl( this, wxID_ANY, "0" );
    coordsSizer->Add( m_xInput, 1, wxLEFT, 5 );
    coordsSizer->Add( new wxStaticText( this, wxID_ANY, _( "Y:" ) ), 0, wxLEFT, 10 );
    m_yInput = new wxTextCtrl( this, wxID_ANY, "0" );
    coordsSizer->Add( m_yInput, 1, wxLEFT, 5 );
    optionsSizer->Add( coordsSizer, 0, wxLEFT | wxRIGHT | wxBOTTOM, 20 );
    
    mainSizer->Add( optionsSizer, 0, wxALL | wxEXPAND, 10 );
    
    // Buttons
    wxSizer* buttonSizer = CreateButtonSizer( wxOK | wxCANCEL );
    mainSizer->Add( buttonSizer, 0, wxALL | wxEXPAND, 10 );
    
    SetSizer( mainSizer );
}

DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE 
DIALOG_ANCHOR_POINT_SELECTION::GetSelectedMode() const
{
    if( m_rbCenter->GetValue() )
        return ANCHOR_CENTER;
    else if( m_rbFirstItem->GetValue() )
        return ANCHOR_FIRST_ITEM;
    else if( m_rbTopLeft->GetValue() )
        return ANCHOR_TOP_LEFT;
    else if( m_rbCustom->GetValue() )
        return ANCHOR_CUSTOM;
    else if( m_rbManual->GetValue() )
        return ANCHOR_MANUAL_COORDS;
    else
        return ANCHOR_DEFAULT;
}

void DIALOG_ANCHOR_POINT_SELECTION::onInteractiveClick( wxCommandEvent& aEvent )
{
    // Закрыть диалог временно
    EndModal( wxID_NONE );  // Специальный код для "выбираем интерактивно"
}
```

#### Обработка в EDIT_TOOL

```cpp
// edit_tool.cpp

int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    // ... обычные проверки ...
    
    PCB_SELECTION& sel = selection();
    
    // Показать диалог выбора
    DIALOG_ANCHOR_POINT_SELECTION dlg( m_frame, sel, sel.GetBoundingBox() );
    int result = dlg.ShowModal();
    
    VECTOR2I anchorPoint;
    
    if( result == wxID_OK )
    {
        auto mode = dlg.GetSelectedMode();
        
        switch( mode )
        {
            case DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_DEFAULT:
                // Использовать GetReferencePoint() по умолчанию
                break;
                
            case DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_CENTER:
                anchorPoint = sel.GetBoundingBox().Centre();
                sel.SetReferencePoint( anchorPoint );
                break;
                
            case DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_FIRST_ITEM:
                anchorPoint = sel.Front()->GetPosition();
                sel.SetReferencePoint( anchorPoint );
                break;
                
            case DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_TOP_LEFT:
                anchorPoint = sel.GetBoundingBox().GetOrigin();
                sel.SetReferencePoint( anchorPoint );
                break;
                
            case DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_CUSTOM:
                // Запустить интерактивный выбор
                return pickAnchorPoint( aEvent );
                
            case DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MANUAL_COORDS:
                anchorPoint = dlg.GetCustomPoint();
                sel.SetReferencePoint( anchorPoint );
                break;
        }
    }
    
    // Сохранить в буфер обмена
    CLIPBOARD_IO clipboard_io( m_board );
    clipboard_io.SaveSelection( sel, false );
    
    return 0;
}
```

#### Плюсы и минусы

| Аспект | Плюсы | Минусы |
|--------|-------|--------|
| **Простота реализации** | ✅ Стандартное диалоговое окно | ❌ Требует создания новой формы |
| **UX** | ✅ Явные опции, нет лишних кликов| ❌ Диалог при каждом копировании |
| **Совместимость** | ✅ Безопасно (диалог опциональный) | ❌ Замедляет обычное копирование |
| **Предсказуемость** | ✅ Очень предсказуемо | ❌ Много опций (может запутать) |

#### Когда использовать

- Пользователь регулярно меняет точку привязки
- Нужны предопределённые опции (центр, угол, и т.д.)
- Поддержка ручного ввода координат нужна

---

### Вариант C: Комбинированный (Рекомендуемый ✅)

#### Философия

Комбинируем преимущества A и B:
- **По умолчанию:** обычное копирование (Ctrl+C) — быстро, как сейчас
- **По требованию:** новая опция меню "Copy with Custom Anchor Point" → диалог
- **В диалоге:** опция интерактивного выбора без отдельного click-pick режима

#### Диаграмма взаимодействия

```
┌─────────────────────────────────────────┐
│ Пользователь:                           │
│ Вариант 1: Ctrl+C (быстро)              │
│ Вариант 2: Menu → Copy → Custom (опция) │
└────────────────┬────────────────────────┘
                 │
         Вариант 1: быстро              Вариант 2: опциональный диалог
                 │                              │
                 ▼                              ▼
    ┌─────────────────────┐      ┌──────────────────────────────┐
    │ copyToClipboard()    │      │ DIALOG_ANCHOR_POINT_SELECTION│
    │ (обычное)           │      │ (опциональный диалог)        │
    │                     │      │                              │
    │ GetReferencePoint()  │      │ Выбрать режим:              │
    │ → автоматический    │      │  • Default                  │
    │                     │      │  • Center                   │
    │ SaveSelection()      │      │  • First Item               │
    │ → БУФЕР ОБМЕНА      │      │  • Custom (interactive)     │
    └─────────────────────┘      │  • Manual X,Y               │
                                  │                              │
                                  │ После выбора → обработка    │
                                  │ SetReferencePoint()         │
                                  │ SaveSelection()             │
                                  │ → БУФЕР ОБМЕНА             │
                                  └──────────────────────────────┘
```

#### Архитектурные изменения

```cpp
// edit_tool.h

class EDIT_TOOL : public PCB_TOOL
{
private:
    // NEW: Вспомогательный метод для обработки режимов диалога
    void ApplyAnchorMode( 
        int aMode,
        VECTOR2I aCustomPoint,
        PCB_SELECTION& aSelection );
};

// В PCB_ACTIONS (pcbnew/tools/pcb_actions.h)

namespace PCB_ACTIONS
{
    // NEW: Действие для копирования с опциональным диалогом
    static TOOL_ACTION copyWithAnchorOptions;
}
```

#### Меню интеграция

```cpp
// В pcbnew/menus/edit_menu.cpp

void EDIT_MENU::PopulateMenu( wxMenu* aMenu )
{
    // ... существующие пункты ...
    
    aMenu->AppendSeparator();
    aMenu->Append( PCB_ACTIONS::copy );  // Ctrl+C (существует, без изменений)
    
    // NEW: Новый пункт меню
    aMenu->Append( PCB_ACTIONS::copyWithAnchorOptions );
    aMenu->Append( PCB_ACTIONS::paste );  // Ctrl+V (существует)
    aMenu->Append( PCB_ACTIONS::pasteSpecial );
}
```

#### Код реализации

```cpp
// edit_tool.cpp

int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    // Обработка Ctrl+C - БЕЗ ДИАЛОГА (как сейчас)
    
    PCB_SELECTION& sel = selection();
    if( sel.Empty() )
        return 0;
    
    // Использовать автоматический anchor point
    // (GetReferencePoint() использует fallback на центр bbox)
    
    CLIPBOARD_IO clipboard_io( m_board );
    clipboard_io.SaveSelection( sel, false );
    return 0;
}

int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
{
    // NEW: Копирование с опциональным диалогом выбора anchor point
    
    PCB_SELECTION& sel = selection();
    if( sel.Empty() )
    {
        m_toolMgr->RunAction( PCB_ACTIONS::selectionCursor );
        if( sel.Empty() )
            return 0;
    }
    
    // Показать диалог
    DIALOG_ANCHOR_POINT_SELECTION dlg( m_frame, sel, sel.GetBoundingBox() );
    
    if( dlg.ShowModal() != wxID_OK )
        return 0;
    
    // Получить выбранный режим и обработать
    int mode = (int)dlg.GetSelectedMode();
    VECTOR2I customPoint = dlg.GetCustomPoint();
    
    ApplyAnchorMode( mode, customPoint, sel );
    
    // Сохранить в буфер обмена
    CLIPBOARD_IO clipboard_io( m_board );
    clipboard_io.SaveSelection( sel, false );
    return 0;
}

void EDIT_TOOL::ApplyAnchorMode( 
    int aMode,
    VECTOR2I aCustomPoint,
    PCB_SELECTION& aSelection )
{
    using ANCHOR_MODE = DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE;
    
    VECTOR2I anchorPoint;
    
    switch( (ANCHOR_MODE)aMode )
    {
        case ANCHOR_MODE::ANCHOR_DEFAULT:
            // Не устанавливаем ничего, GetReferencePoint() вернёт fallback
            break;
            
        case ANCHOR_MODE::ANCHOR_CENTER:
            anchorPoint = aSelection.GetBoundingBox().Centre();
            aSelection.SetReferencePoint( anchorPoint );
            break;
            
        case ANCHOR_MODE::ANCHOR_FIRST_ITEM:
            if( aSelection.GetSize() > 0 )
            {
                anchorPoint = aSelection.Front()->GetPosition();
                aSelection.SetReferencePoint( anchorPoint );
            }
            break;
            
        case ANCHOR_MODE::ANCHOR_TOP_LEFT:
            anchorPoint = aSelection.GetBoundingBox().GetOrigin();
            aSelection.SetReferencePoint( anchorPoint );
            break;
            
        case ANCHOR_MODE::ANCHOR_CUSTOM:
            // Интерактивный выбор - запрос у пользователя
            // Это будет обработано в диалоге или отдельном режиме
            // Пока пропускаем (может быть реализовано в следующей версии)
            break;
            
        case ANCHOR_MODE::ANCHOR_MANUAL_COORDS:
            aSelection.SetReferencePoint( aCustomPoint );
            break;
    }
}
```

#### В файле pcb_actions.cpp

```cpp
// Новое действие
TOOL_ACTION PCB_ACTIONS::copyWithAnchorOptions( "pcbnew.Edit.copyWithAnchorOptions",
    AS_GLOBAL,
    TOOL_ACTION::LegacyHotKey( HK_COPY ),  // или новый hotkey
    _( "Copy with Anchor Point Options..." ),
    _( "Copy selection with interactive anchor point selection" ),
    BITMAPS::copy_16 );

// Регистрироваться в EDIT_TOOL::SetTools()
m_toolMgr->RegisterAction( PCB_ACTIONS::copyWithAnchorOptions,
    &EDIT_TOOL::copyWithAnchorOptions );
```

#### Плюсы и минусы

| Аспект | Плюсы | Минусы |
|--------|-------|--------|
| **Простота реализации** | ✅ Минимальное изменение существующего + диалог | ⚠️ Требует двух функций |
| **UX** | ✅ Быстрое копирование по умолчанию + опция | ✅ Простая, понятная |
| **Совместимость** | ✅ 100% обратно совместимо | ✅ Старый Ctrl+C не меняется |
| **Предсказуемость** | ✅ Два явных режима | ✅ Нет путаницы |
| **Производительность** | ✅ Нет замедления быстрого копирования | ✅ Диалог только по запросу |

---

## ЧАСТЬ 4: ИНТЕГРАЦИЯ С ТЕКУЩЕЙ СИСТЕМОЙ

### Точка входа для новой логики

```
Старая архитектура (Ctrl+C):
  copyToClipboard() 
  → (использует BestDragOrigin автоматически)
  → SaveSelection()

Новая архитектура (Copy → Custom):
  copyWithAnchorOptions()
  → showDialog()
  → ApplyAnchorMode()
  → SaveSelection()
```

### Параметры буфера обмена

**Текущее положение:**
- S-expression формат в буфере обмена
- Anchor point во время сохранения нормализуется к (0, 0)
- Нет явных метаданных об anchor point в самом S-expr

**Предлагаемое изменение:**
- Добавить комментарий в S-expression с информацией о типе anchor point (опционально)
- Или хранить как отдельное свойство в формате

```cpp
// Пример нового формата (опциональный комментарий)
(kicad_clipboard
  (version 9)
  (generator "KiCad 9.0.7")
  (anchor_point center)  ; NEW: информация об anchor point
  (uuid "...")
  ; ... items ...
)
```

**Обратная совместимость:**
- Если комментария нет → используется старый алгоритм (fallback)
- Обновленный KiCad может читать старые буферы обмена
- Нет поломок в существующем коде

### Влияние на существующий код

```
Файлы, которые НЕ меняются:
  ✓ common/tool/selection.cpp (GetReferencePoint)
  ✓ common/tool/selection.h (SELECTION class)
  ✓ pcbnew/kicad_clipboard.cpp (SaveSelection логика)
  ✓ pcbnew/tools/pcb_control.cpp (placeBoardItems)

Файлы, которые добавляют код / расширяют:
  ➕ pcbnew/tools/edit_tool.h (добавить методы)
  ➕ pcbnew/tools/edit_tool.cpp (реализация новых методов)
  ➕ pcbnew/tools/pcb_actions.h (новое действие)
  ➕ pcbnew/tools/pcb_actions.cpp (регистрация)

Новые файлы:
  🆕 pcbnew/dialogs/dialog_anchor_point_selection.h
  🆕 pcbnew/dialogs/dialog_anchor_point_selection.cpp
  🆕 pcbnew/dialogs/dialog_anchor_point_selection_base.cpp (генерируется wxFormBuilder)
```

---

## ЧАСТЬ 5: ПРИМЕРЫ ИЗ ПОХОЖИХ ДИАЛОГОВ

### Пример 1: DIALOG_MOVE в KiCad

```cpp
// pcbnew/dialogs/dialog_move.h

class DIALOG_MOVE : public DIALOG_MOVE_BASE
{
public:
    DIALOG_MOVE( PCB_BASE_FRAME* aParent );
    
    // Получить смещение
    VECTOR2I GetMoveVector() const;
    
    // Параметры выбора относительной точки
    bool UseAbsolutePosition() const;
    VECTOR2I GetAbsolutePosition() const;
};
```

**Сходство:** оба диалога работают с координатами и вектора смещения

### Пример 2: DIALOG_TEXT_PROPERTIES

```cpp
// pcbnew/dialogs/dialog_text_properties.h

class DIALOG_TEXT_PROPERTIES : public DIALOG_TEXT_PROPERTIES_BASE
{
    // Группа опций с radio buttons
    // Координативты X, Y
    // Кнопка "Apply"
};
```

**Сходство:** группы опций (radio buttons), поля для координат

### Пример 3: Диалог в Move Tool

```cpp
// В edit_tool.cpp, метод interactiveMoveMode()

// Пример опции в контекстном меню
// Можно использовать как образец для интеграции
```

---

## ЧАСТЬ 6: АЛЬТЕРНАТИВНЫЕ ПОДХОДЫ И СРАВНЕНИЕ

### Подход 1: Только интерактивный выбор (без диалога)

```
Вариант А полностью
  Shift+Ctrl+C → клик на плате → копировать
  
  Преимущества:
    ✅ Минимум UI, максимум контроля
    ✅ Как в MOVE TOOL (знакомо пользователям)
    
  Недостатки:
    ❌ Лишний клик каждый раз
    ❌ Если хочешь быстро - обычный Ctrl+C без варианта выбора
    ❌ Не подходит для пакетного копирования (много элементов)
```

**Вывод:** Годится для power users, но не очень удобна.

---

### Подход 2: Только диалог (без быстрой опции)

```
Вариант B полностью
  Ctrl+C → диалог → выбрать → копировать
  
  Преимущества:
    ✅ Один способ, не нужно помнить hotkeys
    ✅ Гибко и явно
    
  Недостатки:
    ❌ ВСЕГДА показывать диалог - это раздражает
    ❌ Замедляет обычное копирование в 2-3 раза
    ❌ Пользователи привыкли к Ctrl+C без диалога
    ❌ Нарушает ожидание от стандартного Ctrl+C
```

**Вывод:** Слишком навязчив, нарушает привычку пользователя.

---

### Подход 3: Комбинированный (рекомендуемый) ✅

```
Вариант С
  Ctrl+C → быстро (без диалога) - как обычно
  Menu → Copy → Custom → диалог - по требованию
  
  Преимущества:
    ✅ Ctrl+C остаётся быстрым (обратная совместимость)
    ✅ Диалог только когда пользователь хочет
    ✅ Явное меню - легко найти
    ✅ Максимум гибкости (5+ вариантов anchor point)
    ✅ Минимум раздражения
    
  Недостатки:
    ⚠️ Требует чуть больше кода (диалог + метод)
    ⚠️ Два разных пути - нужно документировать
```

**Вывод:** ✅ РЕКОМЕНДУЕМЫЙ подход. Баланс удобства, гибкости и совместимости.

---

### Подход 4: Опция в Preferences (глобальная)

```
Edit → Preferences → PCB Editor → Copy behavior
  [✓] Show anchor point dialog on copy
  [ ] Use center of selection as anchor
  [ ] Use first item as anchor
  [ ] Use custom anchor point
  
  Преимущества:
    ✅ Пользователь выбирает один раз
    ✅ Автоматизирует копирование
    
  Недостатки:
    ❌ Скрыто в preferences (не очевидно)
    ❌ Нельзя быстро переключаться
    ❌ Сложнее реализовать (требует конфига)
    ❌ Не подходит для разных типов копирования
```

**Вывод:** Можно как дополнение к подходу C, но не основное решение.

---

### Сравнительная таблица

| Критерий | A | B | C ✅ | D |
|----------|---|---|------|---|
| **Простота реализации** | 8/10 | 6/10 | 7/10 | 5/10 |
| **UX удобство** | 6/10 | 7/10 | 9/10 | 5/10 |
| **Обратная совместимость** | 9/10 | 8/10 | 10/10 | 8/10 |
| **Производительность** | 9/10 | 8/10 | 10/10 | 10/10 |
| **Гибкость** | 7/10 | 9/10 | 9/10 | 6/10 |
| **Очевидность** | 5/10 | 8/10 | 8/10 | 3/10 |
| **ИТОГО** | 44 | 46 | **54** | 37 |

**Рекомендация: Вариант C (Комбинированный)**

---

## ЧАСТЬ 7: РЕКОМЕНДУЕМОЕ РЕШЕНИЕ

### Архитектура (из Варианта C)

```
Изменяемые файлы:
  1. pcbnew/tools/edit_tool.h
     ➕ Добавить метод copyWithAnchorOptions()
     ➕ Добавить метод ApplyAnchorMode()
     
  2. pcbnew/tools/edit_tool.cpp
     ✏️ Модифицировать copyToClipboard() (оставить как есть)
     ➕ Реализовать copyWithAnchorOptions()
     ➕ Реализовать ApplyAnchorMode()
     
  3. pcbnew/tools/pcb_actions.h
     ➕ Добавить PCB_ACTIONS::copyWithAnchorOptions
     
  4. pcbnew/tools/pcb_actions.cpp
     ➕ Регистрировать новое действие
     
  5. pcbnew/menus/edit_menu.cpp
     ➕ Добавить пункт меню

Новые файлы:
  6. pcbnew/dialogs/dialog_anchor_point_selection.h
  7. pcbnew/dialogs/dialog_anchor_point_selection.cpp
  8. pcbnew/dialogs/dialog_anchor_point_selection_base.cpp (wxFormBuilder)
```

### Логика выполнения

```cpp
// Исходный код (Ctrl+C) - БЕЗ ИЗМЕНЕНИЙ
int EDIT_TOOL::copyToClipboard( const TOOL_EVENT& aEvent )
{
    // Быстро копирует, использует автоматический anchor point
    // Старое поведение - не меняем
}

// НОВЫЙ КОД (Copy → Custom)
int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
{
    // 1. Проверить выделение
    // 2. Показать диалог
    // 3. Получить выбранный режим
    // 4. Применить режим (SetReferencePoint)
    // 5. Сохранить в буфер обмена
}

void EDIT_TOOL::ApplyAnchorMode( int aMode, VECTOR2I aCustomPoint, PCB_SELECTION& aSel )
{
    // Вспомогательный метод для применения выбранного режима
    // поддерживает CENTER, FIRST_ITEM, TOP_LEFT, MANUAL_COORDS
}
```

### Пространства имён и структуры

```cpp
// dialog_anchor_point_selection.h

namespace DIALOG_ANCHOR_POINT_SELECTION_CONSTANTS {
    static const wxString PRESET_NAMES[] = {
        _( "Default (automatic)" ),
        _( "Center of bounding box" ),
        _( "First selected item" ),
        _( "Top-left corner" ),
        _( "Custom (interactive)" ),
        _( "Manual coordinates" )
    };
};
```

### Меню интеграция

```
Edit Menu:
┌──────────────────────────────────────┐
│ Undo                      Ctrl+Z      │
│ Redo                      Ctrl+Y      │
│ ─────────────────────────────────    │
│ Cut                       Ctrl+X      │
│ Copy                      Ctrl+C      │ ← Существует
│ Copy with Anchor Options  [new]      │ ← НОВЫЙ пункт
│ Paste                     Ctrl+V      │
│ Paste Special             Ctrl+Shift+V
│ ─────────────────────────────────    │
│ Delete                    Del         │
└──────────────────────────────────────┘
```

---

## ЧАСТЬ 8: ПРИМЕРЫ КОДА (ПОЛНАЯ РЕАЛИЗАЦИЯ)

### Файл 1: dialog_anchor_point_selection.h (новый)

```cpp
#ifndef DIALOG_ANCHOR_POINT_SELECTION_H
#define DIALOG_ANCHOR_POINT_SELECTION_H

#include <wx/wx.h>
#include "dialogs/dialog_anchor_point_selection_base.h"
#include "geometry/vector2d.h"

// Forward declarations
class PCB_SELECTION;
class BOX2I;

class DIALOG_ANCHOR_POINT_SELECTION : public DIALOG_ANCHOR_POINT_SELECTION_BASE
{
public:
    enum ANCHOR_MODE
    {
        ANCHOR_DEFAULT = 0,
        ANCHOR_CENTER = 1,
        ANCHOR_FIRST_ITEM = 2,
        ANCHOR_TOP_LEFT = 3,
        ANCHOR_CUSTOM = 4,
        ANCHOR_MANUAL_COORDS = 5
    };

public:
    DIALOG_ANCHOR_POINT_SELECTION( wxWindow* aParent,
                                   const PCB_SELECTION& aSelection,
                                   const BOX2I& aBbox );
    
    ~DIALOG_ANCHOR_POINT_SELECTION() override;

    /**
     * Get the selected anchor point mode.
     */
    ANCHOR_MODE GetSelectedMode() const;

    /**
     * Get custom coordinates (if ANCHOR_MANUAL_COORDS is selected).
     */
    VECTOR2I GetCustomPoint() const;

protected:
    void onRadioButtonSelected( wxCommandEvent& aEvent ) override;
    void onManualCoordsChanged( wxCommandEvent& aEvent ) override;

private:
    const PCB_SELECTION& m_selection;
    BOX2I m_bbox;

    void updateControlStates();
    bool validateCoordinates();
};

#endif // DIALOG_ANCHOR_POINT_SELECTION_H
```

### Файл 2: edit_tool.h (изменения)

Добавить в заголовок класса EDIT_TOOL:

```cpp
// In PCB_TOOL class definition, in tools/edit_tool.h

private:
    /**
     * Copy selection with interactive anchor point options dialog.
     */
    int copyWithAnchorOptions( const TOOL_EVENT& aEvent );
    
    /**
     * Apply the selected anchor mode to the selection.
     * @param aMode The anchor point mode
     * @param aCustomPoint Custom point if aMode is ANCHOR_MANUAL_COORDS
     * @param aSelection The selection to apply the anchor point to
     */
    void ApplyAnchorMode( int aMode, VECTOR2I aCustomPoint, PCB_SELECTION& aSelection );
```

### Файл 3: edit_tool.cpp (реализация)

```cpp
// В edit_tool.cpp

int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
{
    PCB_SELECTION& sel = selection();
    
    // Check if we have a selection
    if( sel.Empty() )
    {
        m_toolMgr->RunAction( PCB_ACTIONS::selectionCursor );
        if( sel.Empty() )
            return 0;
    }
    
    // Show the dialog
    DIALOG_ANCHOR_POINT_SELECTION dlg( m_frame, sel, sel.GetBoundingBox() );
    
    if( dlg.ShowModal() != wxID_OK )
        return 0;
    
    // Get selected mode and custom point
    int mode = (int)dlg.GetSelectedMode();
    VECTOR2I customPoint = dlg.GetCustomPoint();
    
    // Apply the anchor mode
    ApplyAnchorMode( mode, customPoint, sel );
    
    // Save to clipboard
    CLIPBOARD_IO clipboard_io( m_board );
    clipboard_io.SaveSelection( sel, false );
    
    return 0;
}

void EDIT_TOOL::ApplyAnchorMode( int aMode, VECTOR2I aCustomPoint, PCB_SELECTION& aSelection )
{
    using ANCHOR_MODE = DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE;
    
    VECTOR2I anchorPoint;
    BOX2I bbox = aSelection.GetBoundingBox();
    
    switch( (ANCHOR_MODE)aMode )
    {
        case ANCHOR_MODE::ANCHOR_DEFAULT:
            // Don't set anything, GetReferencePoint() will return the fallback
            break;
            
        case ANCHOR_MODE::ANCHOR_CENTER:
            anchorPoint = bbox.Centre();
            aSelection.SetReferencePoint( anchorPoint );
            break;
            
        case ANCHOR_MODE::ANCHOR_FIRST_ITEM:
            if( aSelection.GetSize() > 0 )
            {
                EDA_ITEM* firstItem = *aSelection.begin();
                anchorPoint = firstItem->GetPosition();
                aSelection.SetReferencePoint( anchorPoint );
            }
            break;
            
        case ANCHOR_MODE::ANCHOR_TOP_LEFT:
            anchorPoint = bbox.GetOrigin();
            aSelection.SetReferencePoint( anchorPoint );
            break;
            
        case ANCHOR_MODE::ANCHOR_CUSTOM:
            // Interactive selection would be handled by the dialog
            // For now, leave unimplemented (can be done in future)
            break;
            
        case ANCHOR_MODE::ANCHOR_MANUAL_COORDS:
            aSelection.SetReferencePoint( aCustomPoint );
            break;
    }
}
```

---

## ЧАСТЬ 9: ПЛАН РЕАЛИЗАЦИИ И ЭТАПЫ

### Этап 1: Создание диалога (1-2 дня)

```
1.1. Создать файлы:
     - dialog_anchor_point_selection.h
     - dialog_anchor_point_selection.cpp
     
1.2. Реализовать:
     - ANCHOR_MODE enum
     - UI с radio buttons и полями координат
     - Валидация координат
     
1.3. Тестирование:
     - Открытие диалога
     - Переключение между опциями
     - Ввод координат
```

### Этап 2: Интеграция в EDIT_TOOL (1 день)

```
2.1. Добавить методы в EDIT_TOOL:
     - copyWithAnchorOptions()
     - ApplyAnchorMode()
     
2.2. Добавить новое действие:
     - PCB_ACTIONS::copyWithAnchorOptions
     
2.3. Регистрировать в меню Edit
```

### Этап 3: Тестирование (1 день)

```
3.1. Функциональное тестирование:
     - Копирование с разными режимами anchor point
     - Вставка на другую позицию
     - Проверка нормализации (0, 0)
     
3.2. Регрессионное тестирование:
     - Ctrl+C работает как раньше
     - Ctrl+V работает как раньше
     - Старые буферы обмена совместимы
     
3.3. Граничные случаи:
     - Пустое выделение
     - Одиночный элемент
     - Множество элементов
     - Отрицательные координаты
```

### Этап 4: Документирование (0.5 дня)

```
4.1. Добавить комментарии в коде
4.2. Обновить user documentation
4.3. Добавить в release notes
```

**Общее время: ~3-4 дня работы**

---

## ЧАСТЬ 10: ОТКРЫТЫЕ ВОПРОСЫ И ВОЗМОЖНЫЕ РАСШИРЕНИЯ

### Вопрос 1: Интерактивный выбор в диалоге

**Текущее состояние:** Вариант C не включает полный интерактивный pick-point режим.

**Возможное решение:**
```
Диалог → Кнопка "Select" (при ANCHOR_CUSTOM)
  ↓
Закрыть диалог временно
  ↓
Режим ожидания клика на плате
  ↓
Пересчитать и показать диалог заново
  ↓
Пользователь подтверждает → OK
```

**Сложность:** Средняя (требует управления состоянием диалога)

---

### Вопрос 2: Запоминание последнего выбора

**Функция:** Диалог запомнит последний использованный режим

**Реализация:**
```cpp
m_config->Write( "/pcbnew/lastAnchorMode", (int)lastMode );
// ... на следующий раз перечитать и установить по умолчанию
```

**Сложность:** Низкая (просто конфиг)

---

### Вопрос 3: Горячие клавиши для каждого режима

**Функция:** Быстрые горячие клавиши для каждого anchor point режима

**Примером:**
- `Ctrl+Shift+C` → Copy with center anchor
- `Ctrl+Alt+C` → Copy with top-left anchor
- и т.д.

**Сложность:** Низкая-средняя (регистрировать действия в т)

**Преимущества:** Максимум гибкости для power users

---

### Вопрос 4: Предпросмотр anchor point на плате

**Функция:** Показать точку привязки визуально на плате перед копированием

**Реализация:**
```cpp
// Нарисовать кружок на GetReferencePoint()
gal->SetStrokeColor( CYAN );
gal->DrawCircle( refPoint, 100 );
```

**Сложность:** Низкая-средняя (требует доступ к GAL)

---

### Вопрос 5: Сохранение информации об anchor point в буфере обмена

**Функция:** Добавить метаданные об anchor point в S-expression

**Текущее:**
```lisp
(kicad_clipboard (version 9) ...)
```

**Предлагаемое:**
```lisp
(kicad_clipboard
  (version 9)
  (anchor_mode center)
  (anchor_point (0 0))
  ...)
```

**Сложность:** Средняя (требует изменение CLIPBOARD_IO::SaveSelection)

**Обратная совместимость:** Сохраняется (старые буферы читаются как fallback)

---

## ВЫВОДЫ

### Основные рекомендации

1. **Реализовать Вариант C (Комбинированный)**
   - Минимальное влияние на существующий код
   - Полная обратная совместимость
   - Хороший баланс удобства и гибкости

2. **Диалог должен включать:**
   - Default (автоматический выбор)
   - Center (центр bounding box)
   - First Item (первый элемент)
   - Top-Left (верхний левый угол)
   - Manual Coords (ввод X, Y вручную)

3. **Меню интеграция:**
   - Сохранить `Ctrl+C` без диалога
   - Добавить пункт меню "Copy with Anchor Point Options"
   - Возможно, новый hotkey `Ctrl+Shift+C`

4. **Архитектура:**
   - Новый диалоговый класс `DIALOG_ANCHOR_POINT_SELECTION`
   - Два метода в `EDIT_TOOL`: `copyWithAnchorOptions()` и `ApplyAnchorMode()`
   - Минимальные изменения в существующем коде

5. **Тестирование:**
   - Функциональное: все режимы anchor point
   - Регрессионное: старое копирование/вставка работает
   - Совместимость: старые буферы обмена читаются корректно

### Преимущества этого подхода

✅ **Производительность:** Ctrl+C остаётся быстрым  
✅ **Удобство:** Опция доступна в меню, не нужно помнить hotkeys  
✅ **Гибкость:** 5+ режимов anchor point  
✅ **Совместимость:** 100% обратно совместимо с KiCad 9.0.7  
✅ **Простота:** Код гораздо проще, чем другие варианты  

### Примерный объем кода

- `dialog_anchor_point_selection.h/cpp`: ~300 строк
- Изменения в `edit_tool.h/cpp`: ~100 строк
- Изменения в `pcb_actions.h/cpp`: ~30 строк
- Изменения в меню: ~5 строк
- **Итого:** ~435 строк нового/измененного кода

**Оценка:** Реализуемо за 3-4 дня, хороший ROI на удобство пользователя.

---

## ДАННЫЕ ИССЛЕДОВАНИЯ

**Документы, на которых основан этот анализ:**
- [ANCHOR_POINT_ANALYSIS.md](ANCHOR_POINT_ANALYSIS.md) — логика GetReferencePoint()
- [ANCHOR_POINT_ARCHITECTURE.md](ANCHOR_POINT_ARCHITECTURE.md) — архитектура системы
- [CONCLUSIONS_AND_RECOMMENDATIONS.md](CONCLUSIONS_AND_RECOMMENDATIONS.md) — выводы

**Исслелованные файлы KiCad:**
- `common/tool/selection.cpp/h` — GetReferencePoint()
- `pcbnew/kicad_clipboard.cpp` — SaveSelection()
- `pcbnew/tools/edit_tool.cpp` — copyToClipboard()
- `pcbnew/tools/pcb_control.cpp` — Paste operations

**Версия KiCad:** 9.0.7  
**Дата анализа:** 11 февраля 2026

---

*Документ готов к использованию как архитектурная база для реализации.*
