# Подзадача 4 (Приложение): Практические примеры кода и реализация

**Дата:** 11 февраля 2026  
**Уровень деталей:** Код готов к использованию  
**Статус:** Полные примеры для всех компонентов

---

## ЧАСТЬ 1: ПОЛНЫЙ КОД ДИАЛОГА

### Файл: `pcbnew/dialogs/dialog_anchor_point_selection.h`

```cpp
#ifndef DIALOG_ANCHOR_POINT_SELECTION_H
#define DIALOG_ANCHOR_POINT_SELECTION_H

#include <wx/wx.h>
#include <wx/spinctrl.h>
#include "geometry/vector2d.h"

// Forward declarations
class PCB_SELECTION;
class BOX2I;

/**
 * Dialog for selecting an anchor point for copy operations.
 * 
 * Provides multiple strategies for choosing the reference point:
 * - Default (automatic selection via BestDragOrigin)
 * - Center of bounding box
 * - First selected item position
 * - Top-left corner of bounding box
 * - Custom (interactive click - future)
 * - Manual coordinates input
 */
class DIALOG_ANCHOR_POINT_SELECTION : public wxDialog
{
public:
    enum ANCHOR_MODE
    {
        ANCHOR_DEFAULT = 0,        ///< Use automatic selection
        ANCHOR_CENTER = 1,         ///< Center of bounding box
        ANCHOR_FIRST_ITEM = 2,     ///< Position of first selected item
        ANCHOR_TOP_LEFT = 3,       ///< Top-left corner of bbox
        ANCHOR_CUSTOM = 4,         ///< Interactive selection (future)
        ANCHOR_MANUAL_COORDS = 5   ///< Manual X,Y input
    };

public:
    /**
     * Constructor.
     * @param aParent Parent window
     * @param aSelection The current selection for analysis
     * @param aBbox Bounding box of selection (for preview)
     */
    DIALOG_ANCHOR_POINT_SELECTION( wxWindow* aParent,
                                   const PCB_SELECTION& aSelection,
                                   const BOX2I& aBbox );
    
    /**
     * Destructor.
     */
    ~DIALOG_ANCHOR_POINT_SELECTION() override;

    /**
     * Get the selected anchor point mode.
     * @return The ANCHOR_MODE enum value
     */
    ANCHOR_MODE GetSelectedMode() const;

    /**
     * Get custom coordinates (if ANCHOR_MANUAL_COORDS is selected).
     * @return VECTOR2I with the custom point in internal units
     */
    VECTOR2I GetCustomPoint() const;

protected:
    void onRadioButtonSelected( wxCommandEvent& aEvent ) override;
    void onManualCoordsChanged( wxCommandEvent& aEvent ) override;
    void onInteractiveClick( wxCommandEvent& aEvent ) override;

private:
    /**
     * Update the enabled/disabled state of controls based on selection.
     */
    void updateControlStates();

    /**
     * Validate manual coordinate input.
     * @return true if coordinates are valid
     */
    bool validateCoordinates();

    /**
     * Display an info message with current selection info.
     */
    void displaySelectionInfo();

    // Data
    const PCB_SELECTION& m_selection;
    BOX2I m_bbox;
    
    // UI Controls
    wxRadioButton* m_rbDefault;
    wxRadioButton* m_rbCenter;
    wxRadioButton* m_rbFirstItem;
    wxRadioButton* m_rbTopLeft;
    wxRadioButton* m_rbCustom;
    wxRadioButton* m_rbManual;
    
    // Manual input controls
    wxTextCtrl* m_xInput;
    wxTextCtrl* m_yInput;
    wxStaticText* m_coordUnits;
    
    // Interactive button
    wxButton* m_btnInteractive;
    
    // Info display
    wxStaticText* m_infoText;
    
    // Validation message
    wxStaticText* m_validationMsg;
};

#endif // DIALOG_ANCHOR_POINT_SELECTION_H
```

---

### Файл: `pcbnew/dialogs/dialog_anchor_point_selection.cpp`

```cpp
#include "dialog_anchor_point_selection.h"
#include <tools/selection.h>
#include <board.h>
#include <math/box2.h>
#include <confirm.h>

DIALOG_ANCHOR_POINT_SELECTION::DIALOG_ANCHOR_POINT_SELECTION( 
    wxWindow* aParent,
    const PCB_SELECTION& aSelection,
    const BOX2I& aBbox )
    : wxDialog( aParent, wxID_ANY, _( "Anchor Point Selection" ),
                wxDefaultPosition, wxSize( 450, 450 ) ),
      m_selection( aSelection ),
      m_bbox( aBbox )
{
    // Create main sizer
    wxBoxSizer* mainSizer = new wxBoxSizer( wxVERTICAL );
    
    // Info section
    wxStaticBoxSizer* infoSizer = 
        new wxStaticBoxSizer( wxVERTICAL, this, _( "Selection Info" ) );
    m_infoText = new wxStaticText( this, wxID_ANY, "" );
    infoSizer->Add( m_infoText, 0, wxALL, 5 );
    mainSizer->Add( infoSizer, 0, wxALL | wxEXPAND, 10 );
    
    // Options section
    wxStaticBoxSizer* optionsSizer = 
        new wxStaticBoxSizer( wxVERTICAL, this, _( "Anchor Point Mode" ) );
    
    // Default option
    m_rbDefault = new wxRadioButton( this, wxID_ANY, 
        _( "Default (automatic selection)" ), wxDefaultPosition, wxDefaultSize, 
        wxRB_GROUP );
    m_rbDefault->SetValue( true );
    optionsSizer->Add( m_rbDefault, 0, wxALL, 5 );
    
    // Center option
    m_rbCenter = new wxRadioButton( this, wxID_ANY,
        _( "Center of bounding box" ) );
    optionsSizer->Add( m_rbCenter, 0, wxALL, 5 );
    
    // First item option
    m_rbFirstItem = new wxRadioButton( this, wxID_ANY,
        _( "First selected item" ) );
    optionsSizer->Add( m_rbFirstItem, 0, wxALL, 5 );
    
    // Top-left option
    m_rbTopLeft = new wxRadioButton( this, wxID_ANY,
        _( "Top-left corner of bounding box" ) );
    optionsSizer->Add( m_rbTopLeft, 0, wxALL, 5 );
    
    // Custom (interactive) option
    wxBoxSizer* customSizer = new wxBoxSizer( wxHORIZONTAL );
    m_rbCustom = new wxRadioButton( this, wxID_ANY,
        _( "Custom (interactive click on board)" ) );
    customSizer->Add( m_rbCustom, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10 );
    m_btnInteractive = new wxButton( this, wxID_ANY, _( "Select..." ) );
    m_btnInteractive->Bind( wxEVT_BUTTON, 
        &DIALOG_ANCHOR_POINT_SELECTION::onInteractiveClick, this );
    customSizer->Add( m_btnInteractive );
    optionsSizer->Add( customSizer, 0, wxALL, 5 );
    
    // Manual coordinates option
    m_rbManual = new wxRadioButton( this, wxID_ANY,
        _( "Manual coordinates:" ) );
    optionsSizer->Add( m_rbManual, 0, wxALL, 5 );
    
    // Coordinates input
    wxBoxSizer* coordsSizer = new wxBoxSizer( wxHORIZONTAL );
    coordsSizer->AddSpacer( 20 );  // Indentation
    
    coordsSizer->Add( new wxStaticText( this, wxID_ANY, "X:" ), 0, 
        wxRIGHT | wxALIGN_CENTER_VERTICAL, 5 );
    m_xInput = new wxTextCtrl( this, wxID_ANY, "0" );
    coordsSizer->Add( m_xInput, 1, wxRIGHT, 10 );
    
    coordsSizer->Add( new wxStaticText( this, wxID_ANY, "Y:" ), 0,
        wxRIGHT | wxALIGN_CENTER_VERTICAL, 5 );
    m_yInput = new wxTextCtrl( this, wxID_ANY, "0" );
    coordsSizer->Add( m_yInput, 1, wxRIGHT, 5 );
    
    m_coordUnits = new wxStaticText( this, wxID_ANY, "mm" );
    coordsSizer->Add( m_coordUnits, 0, wxALIGN_CENTER_VERTICAL );
    
    optionsSizer->Add( coordsSizer, 0, wxEXPAND | wxLEFT, 5 );
    
    mainSizer->Add( optionsSizer, 1, wxALL | wxEXPAND, 10 );
    
    // Validation message
    m_validationMsg = new wxStaticText( this, wxID_ANY, "" );
    m_validationMsg->SetForegroundColour( *wxRED );
    mainSizer->Add( m_validationMsg, 0, wxALL | wxEXPAND, 5 );
    
    // Buttons
    wxSizer* buttonSizer = CreateButtonSizer( wxOK | wxCANCEL );
    mainSizer->Add( buttonSizer, 0, wxALL | wxEXPAND, 10 );
    
    SetSizer( mainSizer );
    
    // Bind events
    m_rbDefault->Bind( wxEVT_RADIOBUTTON,
        &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected, this );
    m_rbCenter->Bind( wxEVT_RADIOBUTTON,
        &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected, this );
    m_rbFirstItem->Bind( wxEVT_RADIOBUTTON,
        &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected, this );
    m_rbTopLeft->Bind( wxEVT_RADIOBUTTON,
        &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected, this );
    m_rbCustom->Bind( wxEVT_RADIOBUTTON,
        &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected, this );
    m_rbManual->Bind( wxEVT_RADIOBUTTON,
        &DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected, this );
    
    m_xInput->Bind( wxEVT_TEXT,
        &DIALOG_ANCHOR_POINT_SELECTION::onManualCoordsChanged, this );
    m_yInput->Bind( wxEVT_TEXT,
        &DIALOG_ANCHOR_POINT_SELECTION::onManualCoordsChanged, this );
    
    // Display selection info
    displaySelectionInfo();
    updateControlStates();
}

DIALOG_ANCHOR_POINT_SELECTION::~DIALOG_ANCHOR_POINT_SELECTION()
{
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

VECTOR2I DIALOG_ANCHOR_POINT_SELECTION::GetCustomPoint() const
{
    long x = 0, y = 0;
    m_xInput->GetValue().ToLong( &x );
    m_yInput->GetValue().ToLong( &y );
    return VECTOR2I( x, y );
}

void DIALOG_ANCHOR_POINT_SELECTION::onRadioButtonSelected( wxCommandEvent& aEvent )
{
    updateControlStates();
    m_validationMsg->SetLabel( "" );
}

void DIALOG_ANCHOR_POINT_SELECTION::onManualCoordsChanged( wxCommandEvent& aEvent )
{
    if( validateCoordinates() )
        m_validationMsg->SetLabel( "" );
    else
        m_validationMsg->SetLabel( _( "Invalid coordinates" ) );
}

void DIALOG_ANCHOR_POINT_SELECTION::onInteractiveClick( wxCommandEvent& aEvent )
{
    // In future: This will launch an interactive selection mode
    // For now: placeholder
    wxMessageBox( _( "Interactive click mode not yet implemented.\n"
                     "Please use manual coordinates instead." ),
                  _( "Not Implemented" ), wxICON_INFORMATION );
}

void DIALOG_ANCHOR_POINT_SELECTION::updateControlStates()
{
    bool useManual = m_rbManual->GetValue();
    m_xInput->Enable( useManual );
    m_yInput->Enable( useManual );
    
    bool useCustom = m_rbCustom->GetValue();
    m_btnInteractive->Enable( useCustom );
}

bool DIALOG_ANCHOR_POINT_SELECTION::validateCoordinates()
{
    long x, y;
    bool xValid = m_xInput->GetValue().ToLong( &x );
    bool yValid = m_yInput->GetValue().ToLong( &y );
    return xValid && yValid;
}

void DIALOG_ANCHOR_POINT_SELECTION::displaySelectionInfo()
{
    wxString info;
    info.Printf( _( "Selected items: %zu\nBounding box: (%.1f, %.1f) to (%.1f, %.1f)" ),
                 m_selection.GetSize(),
                 m_bbox.GetOrigin().x / 1000000.0,  // Convert to mm (assume nm units)
                 m_bbox.GetOrigin().y / 1000000.0,
                 m_bbox.GetEnd().x / 1000000.0,
                 m_bbox.GetEnd().y / 1000000.0 );
    m_infoText->SetLabel( info );
}
```

---

## ЧАСТЬ 2: ИЗМЕНЕНИЯ В EDIT_TOOL

### Файл: `pcbnew/tools/edit_tool.h` (добавить в класс)

```cpp
// Add to class EDIT_TOOL in include/tools/edit_tool.h

private:
    /**
     * Copy selection with interactive anchor point options.
     * Shows a dialog for selecting the anchor point mode.
     * @param aEvent Tool event
     * @return 0 on success
     */
    int copyWithAnchorOptions( const TOOL_EVENT& aEvent );
    
    /**
     * Apply a selected anchor point mode to the current selection.
     * @param aMode The ANCHOR_MODE to apply
     * @param aCustomPoint Custom point (used if aMode == ANCHOR_MANUAL_COORDS)
     * @param aSelection The selection to modify
     */
    void ApplyAnchorMode( int aMode, const VECTOR2I& aCustomPoint, 
                          PCB_SELECTION& aSelection );
```

---

### Файл: `pcbnew/tools/edit_tool.cpp` (новые методы)

```cpp
#include "dialogs/dialog_anchor_point_selection.h"

// Добавить в EDIT_TOOL

int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
{
    // Get current selection
    PCB_SELECTION& sel = selection();
    
    // Request selection if empty
    if( sel.Empty() )
    {
        m_toolMgr->RunAction( PCB_ACTIONS::selectionCursor );
        
        if( sel.Empty() )
        {
            wxMessageBox( _( "No items selected for copying" ),
                          _( "Copy Error" ), wxICON_WARNING );
            return 0;
        }
    }
    
    // Show the anchor point selection dialog
    BOX2I bbox = sel.GetBoundingBox();
    DIALOG_ANCHOR_POINT_SELECTION dlg( m_frame, sel, bbox );
    
    if( dlg.ShowModal() != wxID_OK )
    {
        // User cancelled
        return 0;
    }
    
    // Get the selected mode and custom point
    int mode = (int)dlg.GetSelectedMode();
    VECTOR2I customPoint = dlg.GetCustomPoint();
    
    // Apply the anchor mode to the selection
    ApplyAnchorMode( mode, customPoint, sel );
    
    // Save to clipboard
    try
    {
        CLIPBOARD_IO clipboard_io( m_board );
        clipboard_io.SaveSelection( sel, false );  // isFootprintEditor = false
    }
    catch ( const std::exception& e )
    {
        wxMessageBox( wxString::Format( _( "Error saving to clipboard: %s" ),
                                       e.what() ),
                      _( "Clipboard Error" ), wxICON_ERROR );
        return 0;
    }
    
    return 0;
}

void EDIT_TOOL::ApplyAnchorMode( int aMode, const VECTOR2I& aCustomPoint,
                                  PCB_SELECTION& aSelection )
{
    using ANCHOR_MODE = DIALOG_ANCHOR_POINT_SELECTION::ANCHOR_MODE;
    
    VECTOR2I anchorPoint;
    BOX2I bbox = aSelection.GetBoundingBox();
    
    switch( (ANCHOR_MODE)aMode )
    {
        case ANCHOR_MODE::ANCHOR_DEFAULT:
        {
            // Don't set anything - GetReferencePoint() will use fallback
            // This allows the automatic selection to work
            break;
        }
        
        case ANCHOR_MODE::ANCHOR_CENTER:
        {
            // Use center of bounding box
            anchorPoint = bbox.Centre();
            aSelection.SetReferencePoint( anchorPoint );
            wxLogDebug( "Anchor mode: CENTER at (%lld, %lld)",
                        anchorPoint.x, anchorPoint.y );
            break;
        }
        
        case ANCHOR_MODE::ANCHOR_FIRST_ITEM:
        {
            // Use position of first selected item
            if( aSelection.GetSize() > 0 )
            {
                EDA_ITEM* firstItem = *aSelection.begin();
                anchorPoint = firstItem->GetPosition();
                aSelection.SetReferencePoint( anchorPoint );
                wxLogDebug( "Anchor mode: FIRST_ITEM at (%lld, %lld)",
                            anchorPoint.x, anchorPoint.y );
            }
            break;
        }
        
        case ANCHOR_MODE::ANCHOR_TOP_LEFT:
        {
            // Use top-left corner of bounding box
            anchorPoint = bbox.GetOrigin();
            aSelection.SetReferencePoint( anchorPoint );
            wxLogDebug( "Anchor mode: TOP_LEFT at (%lld, %lld)",
                        anchorPoint.x, anchorPoint.y );
            break;
        }
        
        case ANCHOR_MODE::ANCHOR_CUSTOM:
        {
            // Interactive selection - future implementation
            // For now, leave unimplemented
            wxLogWarning( "Anchor mode: CUSTOM - not yet implemented" );
            break;
        }
        
        case ANCHOR_MODE::ANCHOR_MANUAL_COORDS:
        {
            // Use manually entered coordinates
            aSelection.SetReferencePoint( aCustomPoint );
            wxLogDebug( "Anchor mode: MANUAL_COORDS at (%lld, %lld)",
                        aCustomPoint.x, aCustomPoint.y );
            break;
        }
        
        default:
            wxLogWarning( "Unknown anchor mode: %d", aMode );
            break;
    }
}
```

---

## ЧАСТЬ 3: РЕГИСТРАЦИЯ В PCB_ACTIONS

### Файл: `pcbnew/tools/pcb_actions.h` (добавить действие)

```cpp
// В namespace PCB_ACTIONS, в конец раздела Copy/Paste

namespace PCB_ACTIONS
{
    // Existing
    extern const TOOL_ACTION copy;
    extern const TOOL_ACTION paste;
    extern const TOOL_ACTION pasteSpecial;
    
    // NEW
    extern const TOOL_ACTION copyWithAnchorOptions;
}
```

---

### Файл: `pcbnew/tools/pcb_actions.cpp` (регистрация)

```cpp
// Добавить в pcbnew/tools/pcb_actions.cpp

// NEW ACTION for copy with anchor point options
TOOL_ACTION PCB_ACTIONS::copyWithAnchorOptions( "pcbnew.Edit.copyWithAnchorOptions",
    AS_GLOBAL,
    // No default hotkey - use menu only, or could add CTRL+SHIFT+C if desired
    // TOOL_ACTION::LegacyHotKey( HK_COPY_WITH_ANCHOR ),  // Future
    _( "Copy with Anchor Point Options..." ),
    _( "Copy selection with interactive anchor point selection dialog",
       "\nAllows you to choose how the anchor point (reference point) is determined:\n"
       "  • Default: Automatic selection\n"
       "  • Center: Center of bounding box\n"
       "  • First Item: Position of first selected item\n"
       "  • Top-Left: Top-left corner\n"
       "  • Manual: Enter X,Y coordinates" ),
    BITMAPS::copy_16 );
```

### Файл: `pcbnew/tools/edit_tool.cpp` (регистрация в SetTools)

```cpp
// В функции EDIT_TOOL::SetTools()

void EDIT_TOOL::SetTools()
{
    // ... существующие регистрации ...
    
    m_toolMgr->RegisterAction( PCB_ACTIONS::copyWithAnchorOptions,
        std::bind( &EDIT_TOOL::copyWithAnchorOptions, this, _1 ) );
}
```

---

## ЧАСТЬ 4: МЕНЮ ИНТЕГРАЦИЯ

### Файл: `pcbnew/menus/edit_menu.cpp` (добавить пункт)

```cpp
// В function EDIT_MENU::PopulateMenu( wxMenu* aMenu )

void EDIT_MENU::PopulateMenu( wxMenu* aMenu )
{
    // ... существующие пункты ...
    
    // Standard cut/copy/paste
    AddItem( PCB_ACTIONS::cut );
    AddItem( PCB_ACTIONS::copy );
    
    // NEW: Copy with anchor point options
    AddItem( PCB_ACTIONS::copyWithAnchorOptions );
    
    AddItem( PCB_ACTIONS::paste );
    AddItem( PCB_ACTIONS::pasteSpecial );
    
    aMenu->AppendSeparator();
    
    // ... остальные пункты ...
}
```

---

## ЧАСТЬ 5: ТЕСТИРОВАНИЕ

### Чек-лист функционального тестирования

```
ТЕСТИРОВАНИЕ ДИАЛОГА:
  ☐ Диалог открывается при выборе "Copy with Anchor Point Options"
  ☐ Все radio buttons включены и эксклюзивны
  ☐ Поля X, Y доступны только при выборе "Manual coordinates"
  ☐ Информация о выделении отображается корректно
  ☐ Валидация координат работает (отклоняет нечисла)
  ☐ OK сохраняет выбранный режим
  ☐ Cancel закрывает диалог без изменений

ТЕСТИРОВАНИЕ РЕЖИМОВ ANCHOR POINT:
  ☐ Default: использует GetReferencePoint() fallback
  ☐ Center: anchor point = bbox.Centre()
  ☐ First Item: anchor point = первого элемента
  ☐ Top-Left: anchor point = bbox.GetOrigin()
  ☐ Manual: anchor point = введённые X,Y

ТЕСТИРОВАНИЕ КОПИРОВАНИЯ:
  ☐ Выбранный режим применяется к SELECTION
  ☐ SaveSelection() нормализует координаты в 0,0
  ☐ Данные попадают в wxClipboard корректно
  ☐ Старые копирования (Ctrl+C) работают как раньше

ТЕСТИРОВАНИЕ ВСТАВКИ:
  ☐ Ctrl+V загружает из буфера обмена
  ☐ Элементы вставляются с правильной позицией
  ☐ Anchor point не влияет на положение при вставке (работает как раньше)

ГРАНИЧНЫЕ СЛУЧАИ:
  ☐ Пустое выделение → ошибка, предложить выделить
  ☐ Одиночный элемент → все режимы работают
  ☐ Множество элементов → все режимы работают
  ☐ Элементы с отрицательными координатами → работает
  ☐ Очень большие координаты (>1000000) → работает
  ☐ Отрицательные ручные координаты → работает

РЕГРЕССИЯ:
  ☐ Ctrl+C (быстрое копирование) не меняется
  ☐ Ctrl+V (вставка) работает как раньше
  ☐ Старые буферы обмена совместимы
  ☐ Move tool работает как раньше
  ☐ Другие операции не затронуты

ПРОИЗВОДИТЕЛЬНОСТЬ:
  ☐ Диалог открывается быстро (<500ms)
  ☐ Копирование с диалогом быстро (<1s)
  ☐ Ctrl+C (без диалога) остаётся быстрым (<100ms)

ЮЗАБИЛИТИ:
  ☐ Меню пункт легко найти
  ☐ Диалог понятен пользователю (no jargon)
  ☐ Информация о выделении помогает
  ☐ Ошибки сообщаются четко
```

---

## ЧАСТЬ 6: ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ

### Пример 1: Простое копирование с центром

```cpp
// Пользователь: выбрал резистор, нажимает меню → Copy with Anchor...
// → диалог → выбирает "Center of bounding box" → OK

// Пошагово:
// 1. SELECTION имеет 1 элемент (резистор)
// 2. Dialog показывает "Selected items: 1"
// 3. Пользователь выбирает "Center"
// 4. ApplyAnchorMode( ANCHOR_CENTER, ..., sel )
//    → sel.SetReferencePoint( bbox.Centre() )
// 5. SaveSelection()
//    → refPoint = bbox.Centre() = (125, 150) mm
//    → Move( R1, -(125, 150) mm )
//    → Координаты R1 меняются: (125, 150) → (0, 0)
//    → S-expression содержит (at 0 0)
// 6. Буфер обмена содержит нормализованный R1
// 7. При Ctrl+V пользователь может вставить в позицию (300, 400)
//    → R1 будет в (300, 400), что совпадает с центром
```

---

### Пример 2: Копирование нескольких элементов с вручную заданной точкой

```cpp
// Пользователь: выбрал группу компонентов (конденсаторы C1-C10)
// → Copy with Anchor...
// → диалог → выбирает "Manual coordinates" → входит X=150, Y=200 → OK

// Пошагово:
// 1. SELECTION имеет 10 элементов
// 2. Dialog показывает "Selected items: 10"
// 3. Пользователь выбирает "Manual coordinates"
// 4. Полей X,Y становятся доступны
// 5. Вводит X=150 Y=200
// 6. Нажимает OK
// 7. ApplyAnchorMode( ANCHOR_MANUAL_COORDS, (150, 200), sel )
//    → sel.SetReferencePoint( (150, 200) )
// 8. SaveSelection()
//    → Все элементы смещаются на -(150, 200)
//    → Неважно какие были исходные координаты
// 9. При вставке, все элементы будут относительно (150, 200)
//    в новой позиции произвольно
```

---

### Пример 3: Копирование с интерактивным выбором (future)

```cpp
// (Это code для будущей версии с интерактивным pick)

// Пользователь: выбрал элемент → Copy with Anchor...
// → диалог → выбирает "Custom (interactive)"
// → диалог → нажимает кнопку "Select..."
// Диалог закрывается, пользователь кликает на плате на точку
// Диалог открывается заново с выбранной точкой
// Пользователь → OK

// Реализация (future):
void DIALOG_ANCHOR_POINT_SELECTION::onInteractiveClick( wxCommandEvent& aEvent )
{
    // Закрыть диалог с специальным кодом
    EndModal( wxID_NONE );
}

// В EDIT_TOOL::pickAnchorPoint (новый метод - future):
int EDIT_TOOL::pickAnchorPoint( const TOOL_EVENT& aEvent )
{
    // Перейти в режим ожидания клика
    while( OwnLoopAndDorists() )
    {
        const TOOL_EVENT& event = Wait();
        
        if( event.IsClick( BUT_LEFT ) )
        {
            VECTOR2I clickPoint = getViewControls()->GetCursorPosition();
            
            // Показать диалог заново с выбранной точкой
            // (диалог должен запомнить точку)
            
            break;
        }
    }
    
    return 0;
}
```

---

## ЧАСТЬ 7: ЧЕК-ЛИСТ РЕАЛИЗАЦИИ

### Этап 1: Создание диалога (Day 1-2)

```
DIALOG_ANCHOR_POINT_SELECTION:
  ☐ dialog_anchor_point_selection.h создан
  ☐ dialog_anchor_point_selection.cpp создан
  ☐ Enum ANCHOR_MODE определён
  ☐ UI с radio buttons реализован
  ☐ Поля X,Y для ручного ввода работают
  ☐ Валидация координат написана
  ☐ Информация о выделении отображается
  
Компиляция:
  ☐ Код компилируется без ошибок
  ☐ Нет предупреждений компилятора (warnings)
  ☐ Линковка успешна
```

### Этап 2: Интеграция в EDIT_TOOL (Day 2-3)

```
EDIT_TOOL методы:
  ☐ copyWithAnchorOptions() реализован
  ☐ ApplyAnchorMode() реализован
  ☐ Методы зарегистрированы в SetTools()
  
PCB_ACTIONS:
  ☐ copyWithAnchorOptions действие добавлено в .h
  ☐ Действие зарегистрировано в .cpp
  
Меню:
  ☐ Пункт меню добавлен в Edit menu
  ☐ Меню компилируется, нет ошибок

Компиляция:
  ☐ edit_tool.h/cpp компилируются
  ☐ pcb_actions.h/cpp компилируются
  ☐ edit_menu.cpp компилируется
  ☐ Весь проект линкуется
```

### Этап 3: Тестирование (Day 3-4)

```
ФУНКЦИОНАЛЬНОЕ:
  ☐ Диалог открывается при выборе меню
  ☐ Все режимы тестированы
  ☐ Копирование работает для каждого режима
  ☐ Вставка работает корректно
  
РЕГРЕССИОННОЕ:
  ☐ Ctrl+C работает как раньше
  ☐ Ctrl+V работает как раньше
  ☐ Старые данные в буфере обмена совместимы
  
ГРАНИЧНЫЕ СЛУЧАИ:
  ☐ Пустое выделение обработано
  ☐ Одиночный элемент работает
  ☐ Много элементов работает
  
ПРОИЗВОДИТЕЛЬНОСТЬ:
  ☐ Диалог открывается быстро
  ☐ Копирование не медленнее чем раньше
  
Логирование:
  ☐ wxLogDebug сообщения показывают режимы
  ☐ Ошибки логируются
```

### Этап 4: Полирование (Day 4)

```
КОД:
  ☐ Комментарии добавлены
  ☐ Названия переменных ясны
  ☐ Нет мертвого кода
  ☐ Нет TODO без описания
  
ДОКУМЕНТАЦИЯ:
  ☐ Doxygen comments на методах
  ☐ Readme обновлён
  ☐ Примеры использования добавлены
  
ИНТЕРНАЦИОНАЛИЗАЦИЯ:
  ☐ Все строки завёрнуты в _( "text" )
  ☐ Русский текст может быть переведён
  
ОШИБКИ:
  ☐ Нет memory leaks
  ☐ Нет dangling pointers
  ☐ Exception handling валиден
```

---

## ЧАСТЬ 8: ВОЗМОЖНЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ

| Проблема | Причина | Решение |
|----------|---------|---------|
| **Диалог не открывается** | Действие не зарегистрировано | Проверить SetTools(), меню binding |
| **Координаты не валидируются** | Неправильный формат ввода | Добавить ToLong() после каждого ввода |
| **Anchor point не применяется** | SetReferencePoint() не вызвана | Проверить ApplyAnchorMode для каждого режима |
| **Буфер обмена пуст** | SaveSelection() не вызвана | Проверить CLIPBOARD_IO и wxClipboard API |
| **Вставка неправильная** | Координаты не нормализованы | Проверить Move(-refPoint) в SaveSelection |
| **Компиляция падает** | Missing includes | Добавить #include в edit_tool.cpp |
| **Меню пункт не виден** | Меню не пересчитана | Перезагрузить меню при инициализации |

---

## ЧАСТЬ 9: ДОПОЛНИТЕЛЬНЫЕ ОПТИМИЗАЦИИ (Future)

### Запоминание последнего режима

```cpp
// В DIALOG_ANCHOR_POINT_SELECTION constructor:

// Получить последний использованный режим
int lastMode = m_config->Read( "/pcbnew/lastAnchorMode", 
    (int)ANCHOR_MODE::ANCHOR_DEFAULT );

// Установить как выбранный
switch( lastMode )
{
    case ANCHOR_CENTER: m_rbCenter->SetValue( true ); break;
    case ANCHOR_FIRST_ITEM: m_rbFirstItem->SetValue( true ); break;
    // ... etc ...
}

// При OK сохранить выбор:
m_config->Write( "/pcbnew/lastAnchorMode", (int)GetSelectedMode() );
```

---

### Горячие клавиши для каждого режима

```cpp
// В pcb_actions.cpp

TOOL_ACTION PCB_ACTIONS::copyWithCenterAnchor( 
    "pcbnew.Edit.copyWithCenterAnchor",
    AS_GLOBAL,
    // TOOL_ACTION::LegacyHotKey( HK_COPY_CENTER ),  // Future: CTRL+ALT+C
    _( "Copy with Center Anchor" ),
    _( "Copy with center of bounding box as anchor point" ),
    BITMAPS::copy_16 );

TOOL_ACTION PCB_ACTIONS::copyWithTopLeftAnchor(
    "pcbnew.Edit.copyWithTopLeftAnchor",
    AS_GLOBAL,
    // TOOL_ACTION::LegacyHotKey( HK_COPY_TOPLEFT ),  // Future: CTRL+SHIFT+ALT+C
    _( "Copy with Top-Left Anchor" ),
    _( "Copy with top-left corner as anchor point" ),
    BITMAPS::copy_16 );
```

---

### Предпросмотр anchor point на плате

```cpp
// В EDIT_TOOL метод для отрисовки anchor point:

void EDIT_TOOL::highlightAnchorPoint( const VECTOR2I& aPoint )
{
    auto gal = m_frame->GetCanvas()->GetGAL();
    gal->SetStrokeColor( COLOR4D( CYAN ) );
    gal->SetLineWidth( 1 );
    gal->DrawCircle( aPoint, 200 );  // 200 nm radius
}
```

---

**Документ готов к использованию разработчиками!** ✅
