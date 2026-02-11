# Исследование: Плавное масштабирование через удержание средней кнопки мыши в KiCad 9.0.7

**Дата:** 2026-02-11  
**Версия KiCad:** 9.0.7  
**Директория исходников:** `/home/anton/VsCode/kicad-research/kicad`

---

## Содержание

1. [Текущая система обработки событий мыши](#1-текущая-система-обработки-событий-мыши)
2. [Текущая система масштабирования (Zoom)](#2-текущая-система-масштабирования-zoom)
3. [Система управления видом (View Controls)](#3-система-управления-видом-view-controls)
4. [Настройки мыши](#4-настройки-мыши)
5. [Код ключевых функций](#5-код-ключевых-функций)
6. [ТЗ для реализации нового функционала](#6-тз-для-реализации-нового-функционала)

---

## 1. Текущая система обработки событий мыши

### 1.1. Архитектура классов

Обработка мыши в KiCad построена на трёхуровневой архитектуре:

```
KIGFX::VIEW_CONTROLS (абстрактный базовый класс)
    ├── VC_SETTINGS (структура настроек)
    └── KIGFX::WX_VIEW_CONTROLS (wxWidgets реализация)
            ├── onMotion()     — обработка движения мыши
            ├── onButton()     — обработка нажатий кнопок
            ├── onWheel()      — обработка колёсика
            ├── onMagnify()    — обработка pinch-zoom (macOS)
            ├── onZoomGesture() — zoom через тачпад
            ├── onPanGesture()  — pan через тачпад
            └── onScroll()     — обработка scrollbar
```

### 1.2. Файлы и расположение

| Файл | Строки | Описание |
|------|--------|----------|
| `include/view/view_controls.h` | 398 | Базовый класс VIEW_CONTROLS + структура VC_SETTINGS |
| `include/view/wx_view_controls.h` | 215 | Заголовок WX_VIEW_CONTROLS |
| `common/view/wx_view_controls.cpp` | 1168 | Реализация WX_VIEW_CONTROLS — **главный файл** |
| `include/view/view.h` | 907 | Класс VIEW — масштаб и позиция |
| `common/view/view.cpp` | 1749 | Реализация VIEW |
| `include/view/zoom_controller.h` | 173 | Контроллеры масштабирования |
| `common/view/zoom_controller.cpp` | 139 | Реализация контроллеров масштабирования |
| `include/settings/common_settings.h` | 238 | Настройки мыши (COMMON_SETTINGS::INPUT) |
| `common/settings/common_settings.cpp` | 897 | Сериализация настроек |
| `common/dialogs/panel_mouse_settings.cpp` | 296 | Диалог настроек мыши |
| `common/dialogs/panel_mouse_settings_base.h` | — | Базовый класс диалога (wxFormBuilder) |

### 1.3. Подключение обработчиков событий

Все обработчики подключаются в конструкторе `WX_VIEW_CONTROLS` (файл `common/view/wx_view_controls.cpp`, строки 79–140):

```cpp
// Файл: common/view/wx_view_controls.cpp, строки 85-105
WX_VIEW_CONTROLS::WX_VIEW_CONTROLS( VIEW* aView, EDA_DRAW_PANEL_GAL* aParentPanel ) :
        VIEW_CONTROLS( aView ), m_state( IDLE ), m_parentPanel( aParentPanel ),
        m_scrollScale( 1.0, 1.0 ), m_cursorPos( 0, 0 ), m_updateCursor( true ),
        m_infinitePanWorks( false ), m_gestureLastZoomFactor( 1.0 )
{
    LoadSettings();

    m_parentPanel->Connect( wxEVT_MOTION,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onMotion ), nullptr, this );
    m_parentPanel->Connect( wxEVT_MOUSEWHEEL,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onWheel ), nullptr, this );
    m_parentPanel->Connect( wxEVT_MIDDLE_UP,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onButton ), nullptr, this );
    m_parentPanel->Connect( wxEVT_MIDDLE_DOWN,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onButton ), nullptr, this );
    m_parentPanel->Connect( wxEVT_LEFT_UP,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onButton ), nullptr, this );
    m_parentPanel->Connect( wxEVT_LEFT_DOWN,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onButton ), nullptr, this );
    m_parentPanel->Connect( wxEVT_RIGHT_UP,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onButton ), nullptr, this );
    m_parentPanel->Connect( wxEVT_RIGHT_DOWN,
                            wxMouseEventHandler( WX_VIEW_CONTROLS::onButton ), nullptr, this );
    // ... scrollbar, capture lost, touch gesture обработчики
}
```

### 1.4. Конечный автомат состояний

`WX_VIEW_CONTROLS` использует конечный автомат с 4 состояниями:

```cpp
// Файл: include/view/wx_view_controls.h, строки 129-134
enum STATE
{
    IDLE = 1,           ///< Nothing is happening.
    DRAG_PANNING,       ///< Panning with mouse button pressed.
    AUTO_PANNING,       ///< Panning on approaching borders of the frame.
    DRAG_ZOOMING,       ///< Zooming with mouse button pressed.
};
```

**Граф переходов:**

```
IDLE ──── MiddleDown + PAN ────> DRAG_PANNING
IDLE ──── MiddleDown + ZOOM ──> DRAG_ZOOMING
IDLE ──── AutoPan trigger ────> AUTO_PANNING

DRAG_PANNING ──── MiddleUp ──> IDLE
DRAG_ZOOMING ──── MiddleUp ──> IDLE
AUTO_PANNING ──── LeftUp ────> IDLE
```

### 1.5. Что сейчас делает средняя кнопка мыши

Поведение средней кнопки (зажатие + перетаскивание) определяется настройкой `m_settings.m_dragMiddle`, которая может принимать значения:

- `MOUSE_DRAG_ACTION::PAN` (по умолчанию) — панорамирование
- `MOUSE_DRAG_ACTION::ZOOM` — масштабирование
- `MOUSE_DRAG_ACTION::NONE` — ничего

**Обработка нажатия** (файл `common/view/wx_view_controls.cpp`, строки 491-522):

```cpp
// Файл: common/view/wx_view_controls.cpp, строки 491-522
void WX_VIEW_CONTROLS::onButton( wxMouseEvent& aEvent )
{
    switch( m_state )
    {
    case IDLE:
    case AUTO_PANNING:
        if( ( aEvent.MiddleDown() && m_settings.m_dragMiddle == MOUSE_DRAG_ACTION::PAN ) ||
            ( aEvent.RightDown() && m_settings.m_dragRight == MOUSE_DRAG_ACTION::PAN ) )
        {
            m_dragStartPoint = VECTOR2D( aEvent.GetX(), aEvent.GetY() );
            setState( DRAG_PANNING );
            m_infinitePanWorks = KIPLATFORM::UI::InfiniteDragPrepareWindow( m_parentPanel );

#if defined USE_MOUSE_CAPTURE
            if( !m_parentPanel->HasCapture() )
                m_parentPanel->CaptureMouse();
#endif
        }
        else if( ( aEvent.MiddleDown() && m_settings.m_dragMiddle == MOUSE_DRAG_ACTION::ZOOM ) ||
                 ( aEvent.RightDown() && m_settings.m_dragRight == MOUSE_DRAG_ACTION::ZOOM ) )
        {
            m_dragStartPoint   = VECTOR2D( aEvent.GetX(), aEvent.GetY() );
            m_zoomStartPoint = m_dragStartPoint;
            setState( DRAG_ZOOMING );

#if defined USE_MOUSE_CAPTURE
            if( !m_parentPanel->HasCapture() )
                m_parentPanel->CaptureMouse();
#endif
        }

        if( aEvent.LeftUp() )
            setState( IDLE );     // Stop autopanning when user release left mouse button

        break;

    case DRAG_ZOOMING:
    case DRAG_PANNING:
        if( aEvent.MiddleUp() || aEvent.LeftUp() || aEvent.RightUp() )
        {
            setState( IDLE );
            KIPLATFORM::UI::InfiniteDragReleaseWindow();

#if defined USE_MOUSE_CAPTURE
            if( !m_settings.m_cursorCaptured && m_parentPanel->HasCapture() )
                m_parentPanel->ReleaseMouse();
#endif
        }

        break;
    }

    aEvent.Skip();
}
```

---

## 2. Текущая система масштабирования (Zoom)

### 2.1. Zoom через колёсико мыши (onWheel)

Текущий zoom через колёсико реализован в методе `onWheel()` (файл `common/view/wx_view_controls.cpp`, строки 380-454):

```cpp
// Файл: common/view/wx_view_controls.cpp, строки 380-454
void WX_VIEW_CONTROLS::onWheel( wxMouseEvent& aEvent )
{
    const double wheelPanSpeed = 0.001;
    const int    axis = aEvent.GetWheelAxis();

    if( axis == wxMOUSE_WHEEL_HORIZONTAL && !m_settings.m_horizontalPan )
        return;

    int nMods = 0;
    int modifiers = 0;

    if( aEvent.ShiftDown() )  { nMods += 1; modifiers = WXK_SHIFT; }
    if( aEvent.ControlDown() ) { nMods += 1; modifiers = modifiers == 0 ? WXK_CONTROL : modifiers; }
    if( aEvent.AltDown() )     { nMods += 1; modifiers = modifiers == 0 ? WXK_ALT : modifiers; }

    if( nMods <= 1 )
    {
        if( modifiers == m_settings.m_scrollModifierZoom && axis == wxMOUSE_WHEEL_VERTICAL )
        {
            const int rotation =
                    aEvent.GetWheelRotation() * ( m_settings.m_scrollReverseZoom ? -1 : 1 );
            const double zoomScale = m_zoomController->GetScaleForRotation( rotation );

            if( IsCursorWarpingEnabled() )
            {
                CenterOnCursor();
                m_view->SetScale( m_view->GetScale() * zoomScale );
            }
            else
            {
                const VECTOR2D anchor = m_view->ToWorld( VECTOR2D( aEvent.GetX(), aEvent.GetY() ) );
                m_view->SetScale( m_view->GetScale() * zoomScale, anchor );
            }

            refreshMouse( true );
        }
        else
        {
            // Scrolling (горизонтальное/вертикальное панорамирование)
            // ...
        }
    }
}
```

**Ключевые моменты:**
- Два режима масштабирования: с центрированием на курсоре (`IsCursorWarpingEnabled()`) и с anchor-point
- `m_zoomController->GetScaleForRotation(rotation)` вычисляет коэффициент масштабирования
- `m_view->SetScale(scale, anchor)` устанавливает масштаб с фиксированной точкой

### 2.2. Zoom через перетаскивание (DRAG_ZOOMING)

Текущий drag-zoom работает через вертикальное перемещение мыши. Реализован в `onMotion()` (файл `common/view/wx_view_controls.cpp`, строки 340-378):

```cpp
// Файл: common/view/wx_view_controls.cpp, строки 340-378
// Внутри onMotion(), ветка m_state == DRAG_ZOOMING:
else if( m_state == DRAG_ZOOMING )
{
    static bool justWarped = false;
    int warpY = 0;
    wxSize parentSize = m_parentPanel->GetClientSize();

    if( y < 0 )
    {
        warpY = parentSize.y;
    }
    else if( y >= parentSize.y )
    {
        warpY = -parentSize.y;
    }

    if( !justWarped )
    {
        VECTOR2D d = m_dragStartPoint - mousePos;
        m_dragStartPoint = mousePos;

        double scale = exp( d.y * m_settings.m_zoomSpeed * 0.001 );

        wxLogTrace( traceZoomScroll, wxString::Format( "dy: %f  scale: %f", d.y, scale ) );

        m_view->SetScale( m_view->GetScale() * scale, m_view->ToWorld( m_zoomStartPoint ) );
        aEvent.StopPropagation();
    }

    if( warpY )
    {
        if( !justWarped )
        {
            KIPLATFORM::UI::WarpPointer( m_parentPanel, x, y + warpY );
            m_dragStartPoint += VECTOR2D( 0, warpY );
            justWarped = true;
        }
        else
            justWarped = false;
    }
    else
    {
        justWarped = false;
    }
}
```

**Ключевые моменты:**
- Коэффициент масштабирования вычисляется как `exp(dy * zoomSpeed * 0.001)`
- Якорная точка — `m_zoomStartPoint` (точка начала перетаскивания)
- Используется бесконечное перетаскивание: при выходе мыши за границы окна, курсор телепортируется на противоположную сторону (`warpY`)
- `justWarped` — флаг для игнорирования ложного события motion после warp

### 2.3. Контроллеры масштабирования (ZOOM_CONTROLLER)

Иерархия:
```
ZOOM_CONTROLLER (абстрактный)
    ├── ACCELERATING_ZOOM_CONTROLLER — ускоряющийся zoom при быстрой прокрутке
    └── CONSTANT_ZOOM_CONTROLLER     — линейный zoom
```

**CONSTANT_ZOOM_CONTROLLER** (файл `common/view/zoom_controller.cpp`, строки 121-137):
```cpp
// Файл: common/view/zoom_controller.cpp, строки 121-138
CONSTANT_ZOOM_CONTROLLER::CONSTANT_ZOOM_CONTROLLER( double aScale ) : m_scale( aScale )
{
}

double CONSTANT_ZOOM_CONTROLLER::GetScaleForRotation( int aRotation )
{
    aRotation = ( aRotation > 0 ) ? std::min( aRotation, 100 ) : std::max( aRotation, -100 );

    double dscale = aRotation * m_scale;

    double zoom_scale = ( aRotation > 0 ) ? ( 1 + dscale ) : 1 / ( 1 - dscale );

    return zoom_scale;
}
```

**Константы масштаба по платформам:**
```cpp
// Файл: include/view/zoom_controller.h, строки 156-166
static constexpr double GTK3_SCALE = 0.002;
static constexpr double MAC_SCALE = 0.01;
static constexpr double MSW_SCALE = 0.005;
static constexpr double MANUAL_SCALE_FACTOR = 0.001;
```

### 2.4. VIEW::SetScale — основной метод масштабирования

```cpp
// Файл: common/view/view.cpp, строки 569-591
void VIEW::SetScale( double aScale, VECTOR2D aAnchor )
{
    if( aAnchor == VECTOR2D( 0, 0 ) )
        aAnchor = m_center;

    VECTOR2D a = ToScreen( aAnchor );

    if( aScale < m_minScale )
        m_scale = m_minScale;
    else if( aScale > m_maxScale )
        m_scale = m_maxScale;
    else
        m_scale = aScale;

    m_gal->SetZoomFactor( m_scale );
    m_gal->ComputeWorldScreenMatrix();

    VECTOR2D delta = ToWorld( a ) - aAnchor;

    SetCenter( m_center - delta );

    // Redraw everything after the viewport has changed
    MarkDirty();
}
```

**Алгоритм "zoom to anchor" (точка под курсором остаётся неподвижной):**

1. Запоминаем экранную позицию anchor: `a = ToScreen(aAnchor)`
2. Устанавливаем новый масштаб: `m_scale = aScale`
3. Пересчитываем матрицу: `m_gal->ComputeWorldScreenMatrix()`
4. Вычисляем дрифт: `delta = ToWorld(a) - aAnchor`
5. Компенсируем дрифт: `SetCenter(m_center - delta)`

Это **именно тот алгоритм**, который обеспечивает неподвижность точки под курсором при zoom.

---

## 3. Система управления видом (View Controls)

### 3.1. Класс KIGFX::VIEW

```cpp
// Файл: include/view/view.h, строки 271-325
virtual void SetScale( double aScale, VECTOR2D aAnchor = { 0, 0 } );

inline double GetScale() const
{
    return m_scale;
}

void SetScaleLimits( double aMaximum, double aMinimum )
{
    m_minScale = aMinimum;
    m_maxScale = aMaximum;
}

void SetCenter( const VECTOR2D& aCenter );
```

**Ключевые поля VIEW** (файл `common/view/view.cpp`, строки 240-241):
```cpp
m_scale( 4.0 ),
m_minScale( 0.2 ), m_maxScale( 50000.0 ),
```

### 3.2. Класс VC_SETTINGS — настройки вида

```cpp
// Файл: include/view/view_controls.h, строки 43-127
struct VC_SETTINGS
{
    bool m_showCursor;
    VECTOR2D m_forcedPosition;
    bool m_forceCursorPosition;
    bool m_cursorCaptured;
    bool m_snappingEnabled;
    bool m_grabMouse;
    bool m_focusFollowSchPcb;
    bool m_autoPanEnabled;
    bool m_autoPanSettingEnabled;
    float m_autoPanMargin;
    float m_autoPanSpeed;
    float m_autoPanAcceleration;
    bool m_warpCursor;
    bool m_horizontalPan;
    bool m_zoomAcceleration;
    int m_zoomSpeed;
    bool m_zoomSpeedAuto;
    int m_scrollModifierZoom;
    int m_scrollModifierPanH;
    int m_scrollModifierPanV;

    MOUSE_DRAG_ACTION m_dragLeft;
    MOUSE_DRAG_ACTION m_dragMiddle;    // ← Настройка средней кнопки
    MOUSE_DRAG_ACTION m_dragRight;

    bool m_scrollReverseZoom;
    bool m_scrollReversePanH;
};
```

### 3.3. Переменные экземпляра WX_VIEW_CONTROLS

```cpp
// Файл: include/view/wx_view_controls.h, строки 170-210
STATE       m_state;                 // Текущее состояние конечного автомата
EDA_DRAW_PANEL_GAL* m_parentPanel;   // Панель рисования
VECTOR2D    m_dragStartPoint;        // Начало перетаскивания (экранные координаты)
VECTOR2D    m_panDirection;          // Направление autopan
wxTimer     m_panTimer;              // Таймер autopan
VECTOR2D    m_scrollScale;           // Масштаб scrollbar
VECTOR2I    m_scrollPos;             // Позиция scrollbar
VECTOR2D    m_zoomStartPoint;        // Начальная точка drag-zoom (экранные координаты)
VECTOR2D    m_cursorPos;             // Позиция курсора (мировые координаты)
bool        m_updateCursor;          // Обновлять ли курсор по мыши
bool        m_infinitePanWorks;      // Работает ли бесконечный drag на платформе
std::unique_ptr<ZOOM_CONTROLLER> m_zoomController;  // Контроллер масштабирования
double      m_gestureLastZoomFactor; // Последний zoom factor жеста
VECTOR2D    m_gestureLastPos;        // Последняя позиция жеста
```

### 3.4. Платформо-зависимые функции

```
KIPLATFORM::UI::InfiniteDragPrepareWindow(wxWindow*)  — подготовка к бесконечному перетаскиванию
KIPLATFORM::UI::InfiniteDragReleaseWindow()            — завершение бесконечного перетаскивания
KIPLATFORM::UI::WarpPointer(wxWindow*, x, y)           — телепортация курсора мыши
```

Реализации:
- **Linux GTK:** `libs/kiplatform/port/wxgtk/ui.cpp`, строка 592
- **macOS:** `libs/kiplatform/port/wxosx/ui.mm`, строка 211
- **Windows:** `libs/kiplatform/port/wxmsw/ui.cpp`, строка 202

---

## 4. Настройки мыши

### 4.1. Перечисление MOUSE_DRAG_ACTION

```cpp
// Файл: include/settings/common_settings.h, строки 28-36
enum class MOUSE_DRAG_ACTION
{
    DRAG_ANY = -2,
    DRAG_SELECTED,
    SELECT,
    ZOOM,
    PAN,
    NONE
};
```

### 4.2. Настройки в JSON (common_settings.cpp)

```cpp
// Файл: common/settings/common_settings.cpp, строки 280-286
m_params.emplace_back( new PARAM_ENUM<MOUSE_DRAG_ACTION>( "input.mouse_middle",
        &m_Input.drag_middle, MOUSE_DRAG_ACTION::PAN, MOUSE_DRAG_ACTION::SELECT,
        MOUSE_DRAG_ACTION::NONE ) );
```

Параметры: ключ JSON `"input.mouse_middle"`, значение по умолчанию `PAN`, диапазон `SELECT..NONE`.

### 4.3. Диалог настроек мыши

```cpp
// Файл: common/dialogs/panel_mouse_settings_base.cpp, строки 139-143
wxString m_choiceMiddleButtonDragChoices[] = { _("Pan"), _("Zoom"), _("None") };
int m_choiceMiddleButtonDragNChoices = sizeof( m_choiceMiddleButtonDragChoices ) / sizeof( wxString );
m_choiceMiddleButtonDrag = new wxChoice( this, wxID_ANY, wxDefaultPosition, wxDefaultSize,
                                         m_choiceMiddleButtonDragNChoices,
                                         m_choiceMiddleButtonDragChoices, 0 );
```

**Преобразование выбора → значение** (файл `common/dialogs/panel_mouse_settings.cpp`, строки 98-103):
```cpp
switch( m_choiceMiddleButtonDrag->GetSelection() )
{
case 0: cfg->m_Input.drag_middle = MOUSE_DRAG_ACTION::PAN;  break;
case 1: cfg->m_Input.drag_middle = MOUSE_DRAG_ACTION::ZOOM; break;
case 2: cfg->m_Input.drag_middle = MOUSE_DRAG_ACTION::NONE; break;
default:                                                    break;
}
```

### 4.4. Загрузка настроек в WX_VIEW_CONTROLS

```cpp
// Файл: common/view/wx_view_controls.cpp, строки 167-200
void WX_VIEW_CONTROLS::LoadSettings()
{
    COMMON_SETTINGS* cfg = Pgm().GetCommonSettings();

    m_settings.m_warpCursor            = cfg->m_Input.center_on_zoom;
    m_settings.m_zoomAcceleration      = cfg->m_Input.zoom_acceleration;
    m_settings.m_zoomSpeed             = cfg->m_Input.zoom_speed;
    m_settings.m_zoomSpeedAuto         = cfg->m_Input.zoom_speed_auto;
    m_settings.m_dragLeft              = cfg->m_Input.drag_left;
    m_settings.m_dragMiddle            = cfg->m_Input.drag_middle;   // ← средняя кнопка
    m_settings.m_dragRight             = cfg->m_Input.drag_right;
    m_settings.m_scrollReverseZoom     = cfg->m_Input.reverse_scroll_zoom;
    m_settings.m_scrollReversePanH     = cfg->m_Input.reverse_scroll_pan_h;

    m_zoomController.reset();

    if( cfg->m_Input.zoom_speed_auto )
    {
        m_zoomController = GetZoomControllerForPlatform( cfg->m_Input.zoom_acceleration );
    }
    else
    {
        if( cfg->m_Input.zoom_acceleration )
        {
            m_zoomController =
                    std::make_unique<ACCELERATING_ZOOM_CONTROLLER>( cfg->m_Input.zoom_speed );
        }
        else
        {
            double scale = CONSTANT_ZOOM_CONTROLLER::MANUAL_SCALE_FACTOR * cfg->m_Input.zoom_speed;
            m_zoomController = std::make_unique<CONSTANT_ZOOM_CONTROLLER>( scale );
        }
    }
}
```

---

## 5. Код ключевых функций

### 5.1. onMotion() — полная обработка перемещения мыши

```cpp
// Файл: common/view/wx_view_controls.cpp, строки 204-383
void WX_VIEW_CONTROLS::onMotion( wxMouseEvent& aEvent )
{
    ( *m_MotionEventCounter )++;

    wxPoint mouseRel = m_parentPanel->ScreenToClient( KIPLATFORM::UI::GetMousePosition() );

    bool     isAutoPanning = false;
    int      x = mouseRel.x;
    int      y = mouseRel.y;
    VECTOR2D mousePos( x, y );

    // Clear keyboard cursor position flag when actual mouse motion is detected
    if( !m_cursorWarped && m_settings.m_lastKeyboardCursorPositionValid )
    {
        VECTOR2I screenPos( x, y );
        VECTOR2I keyboardScreenPos = m_view->ToScreen( m_settings.m_lastKeyboardCursorPosition );

        if( screenPos != keyboardScreenPos )
        {
            m_settings.m_lastKeyboardCursorPositionValid = false;
            m_settings.m_lastKeyboardCursorPosition = { 0.0, 0.0 };
        }
    }

    // Automatic focus switching...
    // (код фокуса опущен для краткости)

    if( m_state != DRAG_PANNING && m_state != DRAG_ZOOMING )
        handleCursorCapture( x, y );

    if( m_settings.m_autoPanEnabled && m_settings.m_autoPanSettingEnabled )
        isAutoPanning = handleAutoPanning( aEvent );

    if( !isAutoPanning && aEvent.Dragging() )
    {
        if( m_state == DRAG_PANNING )
        {
            // Панорамирование — перемещение вида
            static bool justWarped = false;
            int warpX = 0;
            int warpY = 0;
            wxSize parentSize = m_parentPanel->GetClientSize();

            // Бесконечный drag: телепортация при выходе за границы
            if( x < 0 )        warpX = parentSize.x;
            else if(x >= parentSize.x ) warpX = -parentSize.x;
            if( y < 0 )        warpY = parentSize.y;
            else if( y >= parentSize.y ) warpY = -parentSize.y;

            if( !justWarped )
            {
                VECTOR2D d = m_dragStartPoint - mousePos;
                m_dragStartPoint = mousePos;
                VECTOR2D delta = m_view->ToWorld( d, false );
                m_view->SetCenter( m_view->GetCenter() + delta );
                aEvent.StopPropagation();
            }

            if( warpX || warpY )
            {
                if( !justWarped )
                {
                    if( m_infinitePanWorks
                        && KIPLATFORM::UI::WarpPointer( m_parentPanel, x + warpX, y + warpY ) )
                    {
                        m_dragStartPoint += VECTOR2D( warpX, warpY );
                        justWarped = true;
                    }
                }
                else
                    justWarped = false;
            }
            else
                justWarped = false;
        }
        else if( m_state == DRAG_ZOOMING )
        {
            // Масштабирование — zoom по вертикали
            static bool justWarped = false;
            int warpY = 0;
            wxSize parentSize = m_parentPanel->GetClientSize();

            if( y < 0 )        warpY = parentSize.y;
            else if( y >= parentSize.y ) warpY = -parentSize.y;

            if( !justWarped )
            {
                VECTOR2D d = m_dragStartPoint - mousePos;
                m_dragStartPoint = mousePos;

                double scale = exp( d.y * m_settings.m_zoomSpeed * 0.001 );
                m_view->SetScale( m_view->GetScale() * scale, m_view->ToWorld( m_zoomStartPoint ) );
                aEvent.StopPropagation();
            }

            if( warpY )
            {
                if( !justWarped )
                {
                    KIPLATFORM::UI::WarpPointer( m_parentPanel, x, y + warpY );
                    m_dragStartPoint += VECTOR2D( 0, warpY );
                    justWarped = true;
                }
                else
                    justWarped = false;
            }
            else
                justWarped = false;
        }
    }

    if( m_updateCursor )
        m_cursorPos = GetClampedCoords( m_view->ToWorld( mousePos ) );
    else
        m_updateCursor = true;

    aEvent.Skip();
}
```

### 5.2. Вспомогательные функции

**refreshMouse()** — отправка события обновления позиции мыши:
```cpp
// Файл: common/view/wx_view_controls.cpp, строки 1107-1123
void WX_VIEW_CONTROLS::refreshMouse( bool aSetModifiers )
{
    wxMouseEvent moveEvent( EVT_REFRESH_MOUSE );
    wxPoint msp = getMouseScreenPosition();
    moveEvent.SetX( msp.x );
    moveEvent.SetY( msp.y );

    if( aSetModifiers )
    {
        moveEvent.SetControlDown( wxGetKeyState( WXK_CONTROL ) );
        moveEvent.SetShiftDown( wxGetKeyState( WXK_SHIFT ) );
        moveEvent.SetAltDown( wxGetKeyState( WXK_ALT ) );
    }

    m_cursorPos = GetClampedCoords( m_view->ToWorld( VECTOR2D( msp.x, msp.y ) ) );
    wxPostEvent( m_parentPanel, moveEvent );
}
```

**CancelDrag()** — отмена текущего перетаскивания:
```cpp
// Файл: common/view/wx_view_controls.cpp, строки 800-812
void WX_VIEW_CONTROLS::CancelDrag()
{
    if( m_state == DRAG_PANNING || m_state == DRAG_ZOOMING )
    {
        setState( IDLE );

#if defined USE_MOUSE_CAPTURE
        if( !m_settings.m_cursorCaptured && m_parentPanel->HasCapture() )
            m_parentPanel->ReleaseMouse();
#endif
    }
}
```

---

## 6. ТЗ для реализации нового функционала

### 6.1. Описание функционала

**Название:** Smooth Drag Zoom (Плавное масштабирование через удержание средней кнопки мыши)

**UX описание:**

1. Пользователь **зажимает среднюю кнопку мыши** (нажатие колёсика).
2. Не отпуская кнопку, **двигает мышь вверх** — изображение **плавно увеличивается** (zoom in).
3. Не отпуская кнопку, **двигает мышь вниз** — изображение **плавно уменьшается** (zoom out).
4. **Курсор мыши НЕ двигается** на экране — позиция курсора фиксирована в точке нажатия.
5. **Изображение масштабируется относительно точки нажатия** — мировые координаты под курсором остаются неподвижными.
6. Скорость масштабирования **пропорциональна расстоянию** перемещения мыши от начальной точки.
7. При **отпускании средней кнопки** — возврат к обычному режиму (IDLE).

**Отличия от текущего DRAG_ZOOMING:**

| Параметр | Текущий DRAG_ZOOMING | Новый SMOOTH_DRAG_ZOOM |
|----------|---------------------|----------------------|
| Курсор мыши | Двигается (с warp при выходе) | **Скрыт и зафиксирован** |
| Масштабирование | По инкрементам dy | **Плавное, по абсолютному смещению** |
| Точка anchor | m_zoomStartPoint (начало drag) | **Позиция курсора при нажатии** |
| Бесконечный drag | Через warp | **Не нужен (курсор скрыт)** |
| Визуальная обратная связь | Нет | **Можно добавить индикатор** |

### 6.2. Текущее поведение средней кнопки

При `m_settings.m_dragMiddle == MOUSE_DRAG_ACTION::ZOOM`:
- Конечный автомат переходит в `DRAG_ZOOMING`
- Фиксируется `m_dragStartPoint` и `m_zoomStartPoint`
- В `onMotion()` вычисляется `d.y` (разница по Y), коэффициент `exp(d.y * speed * 0.001)`
- Масштаб применяется через `VIEW::SetScale()`
- Курсор мыши видимо перемещается (пользователь видит движение)

**Файлы:**
- `common/view/wx_view_controls.cpp` — логика обработки (строки 340-378, 491-540)
- `include/view/wx_view_controls.h` — объявление (строки 129-134, 197-198)

### 6.3. Архитектура изменений

#### 6.3.1. Новое состояние (опционально)

Можно добавить новое состояние `SMOOTH_DRAG_ZOOMING` или переиспользовать `DRAG_ZOOMING` с дополнительным флагом. **Рекомендация: добавить новое значение MOUSE_DRAG_ACTION.**

```cpp
// include/settings/common_settings.h
enum class MOUSE_DRAG_ACTION
{
    DRAG_ANY = -2,
    DRAG_SELECTED,
    SELECT,
    ZOOM,
    SMOOTH_ZOOM,    // ← НОВОЕ: плавное масштабирование с фиксацией курсора
    PAN,
    NONE
};
```

**Альтернативный вариант (проще):** Модифицировать существующий `DRAG_ZOOMING` для фиксации курсора. Это проще, но менее гибко — пользователь не сможет выбирать между старым и новым поведением.

**Рекомендация:** использовать альтернативный вариант (модификация DRAG_ZOOMING), поскольку:
- Текущий DRAG_ZOOMING уже делает почти то, что нужно
- Фиксация курсора — улучшение, а не альтернатива
- Меньше изменений в коде

#### 6.3.2. Классы для модификации

```
KIGFX::WX_VIEW_CONTROLS
    ├── onButton()  — скрыть курсор и захватить мышь при DRAG_ZOOMING
    ├── onMotion()  — фиксировать курсор при DRAG_ZOOMING
    └── + новые поля: m_smoothZoomOriginScreen, m_smoothZoomCursorHidden
```

#### 6.3.3. Диаграмма потока

```
         MiddleDown (ZOOM mode)
              │
    ┌─────────▼──────────┐
    │   Запомнить         │
    │   m_zoomStartPoint  │
    │   Скрыть курсор     │
    │   Захватить мышь    │
    │   → DRAG_ZOOMING    │
    └─────────┬──────────┘
              │
    ┌─────────▼──────────┐
    │   onMotion()        │  ◄── повторяется при каждом событии
    │   dy = startY - y   │
    │   scale = exp(dy)   │
    │   SetScale(anchor)  │
    │   WarpPointer(start)│  ← возврат курсора в начальную точку
    └─────────┬──────────┘
              │
         MiddleUp
              │
    ┌─────────▼──────────┐
    │   Показать курсор   │
    │   Освободить мышь   │
    │   → IDLE            │
    └─────────┘
```

### 6.4. Пошаговый план реализации

#### Шаг 1: Добавить поля в WX_VIEW_CONTROLS

**Файл:** `include/view/wx_view_controls.h`  
**Место:** после строки 198 (`VECTOR2D m_zoomStartPoint;`)

Добавить:
```cpp
    /// Screen position where the cursor should stay during smooth drag zoom.
    VECTOR2D m_smoothZoomCursorScreenPos;

    /// Flag: cursor is hidden during smooth drag zoom.
    bool m_smoothZoomCursorHidden = false;
```

#### Шаг 2: Модифицировать onButton() — вход в DRAG_ZOOMING

**Файл:** `common/view/wx_view_controls.cpp`  
**Место:** строки 509-520 (ветка MiddleDown + ZOOM)

**Текущий код:**
```cpp
else if( ( aEvent.MiddleDown() && m_settings.m_dragMiddle == MOUSE_DRAG_ACTION::ZOOM ) ||
         ( aEvent.RightDown() && m_settings.m_dragRight == MOUSE_DRAG_ACTION::ZOOM ) )
{
    m_dragStartPoint   = VECTOR2D( aEvent.GetX(), aEvent.GetY() );
    m_zoomStartPoint = m_dragStartPoint;
    setState( DRAG_ZOOMING );

#if defined USE_MOUSE_CAPTURE
    if( !m_parentPanel->HasCapture() )
        m_parentPanel->CaptureMouse();
#endif
}
```

**Новый код:**
```cpp
else if( ( aEvent.MiddleDown() && m_settings.m_dragMiddle == MOUSE_DRAG_ACTION::ZOOM ) ||
         ( aEvent.RightDown() && m_settings.m_dragRight == MOUSE_DRAG_ACTION::ZOOM ) )
{
    m_dragStartPoint = VECTOR2D( aEvent.GetX(), aEvent.GetY() );
    m_zoomStartPoint = m_dragStartPoint;
    m_smoothZoomCursorScreenPos = m_dragStartPoint;  // запомнить экранную позицию
    setState( DRAG_ZOOMING );

    // Скрыть системный курсор мыши
    m_parentPanel->SetCursor( wxCURSOR_BLANK );
    m_smoothZoomCursorHidden = true;

#if defined USE_MOUSE_CAPTURE
    if( !m_parentPanel->HasCapture() )
        m_parentPanel->CaptureMouse();
#endif
}
```

#### Шаг 3: Модифицировать onButton() — выход из DRAG_ZOOMING

**Файл:** `common/view/wx_view_controls.cpp`  
**Место:** строки 528-540 (ветка MiddleUp в DRAG_ZOOMING)

**Текущий код:**
```cpp
case DRAG_ZOOMING:
case DRAG_PANNING:
    if( aEvent.MiddleUp() || aEvent.LeftUp() || aEvent.RightUp() )
    {
        setState( IDLE );
        KIPLATFORM::UI::InfiniteDragReleaseWindow();

#if defined USE_MOUSE_CAPTURE
        if( !m_settings.m_cursorCaptured && m_parentPanel->HasCapture() )
            m_parentPanel->ReleaseMouse();
#endif
    }

    break;
```

**Новый код:**
```cpp
case DRAG_ZOOMING:
case DRAG_PANNING:
    if( aEvent.MiddleUp() || aEvent.LeftUp() || aEvent.RightUp() )
    {
        // Восстановить курсор мыши если был скрыт
        if( m_smoothZoomCursorHidden )
        {
            m_parentPanel->SetCursor( wxNullCursor );  // восстановить дефолтный курсор
            m_smoothZoomCursorHidden = false;

            // Вернуть курсор на место — на начальную позицию
            KIPLATFORM::UI::WarpPointer( m_parentPanel,
                                         m_smoothZoomCursorScreenPos.x,
                                         m_smoothZoomCursorScreenPos.y );
        }

        setState( IDLE );
        KIPLATFORM::UI::InfiniteDragReleaseWindow();

#if defined USE_MOUSE_CAPTURE
        if( !m_settings.m_cursorCaptured && m_parentPanel->HasCapture() )
            m_parentPanel->ReleaseMouse();
#endif
    }

    break;
```

#### Шаг 4: Модифицировать onMotion() — ветка DRAG_ZOOMING

**Файл:** `common/view/wx_view_controls.cpp`  
**Место:** строки 340-378 (ветка `m_state == DRAG_ZOOMING`)

**Новая реализация:**
```cpp
else if( m_state == DRAG_ZOOMING )
{
    // Вычисляем смещение от начальной точки
    VECTOR2D d = m_dragStartPoint - mousePos;
    m_dragStartPoint = mousePos;

    if( d.y != 0.0 )
    {
        // Коэффициент масштабирования: экспоненциальный от смещения dy
        double scale = exp( d.y * m_settings.m_zoomSpeed * 0.001 );

        wxLogTrace( traceZoomScroll, wxString::Format( "dy: %f  scale: %f", d.y, scale ) );

        // Масштабируем с anchor в точке, где мышь была при нажатии
        m_view->SetScale( m_view->GetScale() * scale,
                          m_view->ToWorld( m_zoomStartPoint ) );
    }

    // Фиксируем курсор на начальной экранной позиции (не даём двигаться)
    KIPLATFORM::UI::WarpPointer( m_parentPanel,
                                 (int) m_smoothZoomCursorScreenPos.x,
                                 (int) m_smoothZoomCursorScreenPos.y );

    // Обновляем dragStartPoint на зафиксированную позицию,
    // чтобы следующее dy корректно вычислялось
    m_dragStartPoint = m_smoothZoomCursorScreenPos;

    aEvent.StopPropagation();
}
```

**Ключевое отличие от текущей реализации:**
- Убран бесконечный drag (warp на противоположную сторону экрана)
- Вместо этого курсор **всегда возвращается** в начальную точку (`m_smoothZoomCursorScreenPos`)
- `m_dragStartPoint` обновляется до фиксированной позиции, обеспечивая корректный расчёт `dy`
- Поскольку курсор скрыт, пользователь не видит мигания

#### Шаг 5: Модифицировать CancelDrag()

**Файл:** `common/view/wx_view_controls.cpp`  
**Место:** строки 800-812

Добавить восстановление курсора:
```cpp
void WX_VIEW_CONTROLS::CancelDrag()
{
    if( m_state == DRAG_PANNING || m_state == DRAG_ZOOMING )
    {
        // Восстановить курсор если был скрыт при smooth drag zoom
        if( m_smoothZoomCursorHidden )
        {
            m_parentPanel->SetCursor( wxNullCursor );
            m_smoothZoomCursorHidden = false;
        }

        setState( IDLE );

#if defined USE_MOUSE_CAPTURE
        if( !m_settings.m_cursorCaptured && m_parentPanel->HasCapture() )
            m_parentPanel->ReleaseMouse();
#endif
    }
}
```

### 6.5. Файлы для модификации

| # | Файл | Строки | Что менять |
|---|------|--------|-----------|
| 1 | `include/view/wx_view_controls.h` | 197-198 | Добавить `m_smoothZoomCursorScreenPos`, `m_smoothZoomCursorHidden` |
| 2 | `common/view/wx_view_controls.cpp` | 509-520 | onButton() — скрытие курсора при входе в DRAG_ZOOMING |
| 3 | `common/view/wx_view_controls.cpp` | 528-540 | onButton() — показ курсора при выходе из DRAG_ZOOMING |
| 4 | `common/view/wx_view_controls.cpp` | 340-378 | onMotion() — фиксация курсора + упрощение логики |
| 5 | `common/view/wx_view_controls.cpp` | 800-812 | CancelDrag() — восстановление курсора |

### 6.6. Полный новый код

#### 6.6.1. Модификация `include/view/wx_view_controls.h`

```diff
--- a/include/view/wx_view_controls.h
+++ b/include/view/wx_view_controls.h
@@ -195,6 +195,12 @@ private:
     /// The mouse position when a drag zoom started.
     VECTOR2D      m_zoomStartPoint;
 
+    /// The screen position where cursor is locked during smooth drag zoom.
+    VECTOR2D      m_smoothZoomCursorScreenPos;
+
+    /// True when cursor is hidden during smooth drag zoom.
+    bool          m_smoothZoomCursorHidden = false;
+
     /// Current cursor position (world coordinates).
     VECTOR2D    m_cursorPos;
```

#### 6.6.2. Модификация `common/view/wx_view_controls.cpp` — onButton()

```diff
--- a/common/view/wx_view_controls.cpp
+++ b/common/view/wx_view_controls.cpp
@@ -509,6 +509,10 @@ void WX_VIEW_CONTROLS::onButton( wxMouseEvent& aEvent )
             m_dragStartPoint   = VECTOR2D( aEvent.GetX(), aEvent.GetY() );
             m_zoomStartPoint = m_dragStartPoint;
+            m_smoothZoomCursorScreenPos = m_dragStartPoint;
             setState( DRAG_ZOOMING );
 
+            // Hide system cursor during smooth drag zoom
+            m_parentPanel->SetCursor( wxCURSOR_BLANK );
+            m_smoothZoomCursorHidden = true;
+
 #if defined USE_MOUSE_CAPTURE
             if( !m_parentPanel->HasCapture() )
@@ -528,6 +532,15 @@ void WX_VIEW_CONTROLS::onButton( wxMouseEvent& aEvent )
     case DRAG_ZOOMING:
     case DRAG_PANNING:
         if( aEvent.MiddleUp() || aEvent.LeftUp() || aEvent.RightUp() )
         {
+            if( m_smoothZoomCursorHidden )
+            {
+                m_parentPanel->SetCursor( wxNullCursor );
+                m_smoothZoomCursorHidden = false;
+
+                KIPLATFORM::UI::WarpPointer( m_parentPanel,
+                                             m_smoothZoomCursorScreenPos.x,
+                                             m_smoothZoomCursorScreenPos.y );
+            }
+
             setState( IDLE );
             KIPLATFORM::UI::InfiniteDragReleaseWindow();
```

#### 6.6.3. Модификация `common/view/wx_view_controls.cpp` — onMotion() DRAG_ZOOMING

```diff
--- a/common/view/wx_view_controls.cpp
+++ b/common/view/wx_view_controls.cpp
@@ -340,45 +340,25 @@ void WX_VIEW_CONTROLS::onMotion( wxMouseEvent& aEvent )
         else if( m_state == DRAG_ZOOMING )
         {
-            static bool justWarped = false;
-            int warpY = 0;
-            wxSize parentSize = m_parentPanel->GetClientSize();
-
-            if( y < 0 )
-            {
-                warpY = parentSize.y;
-            }
-            else if( y >= parentSize.y )
-            {
-                warpY = -parentSize.y;
-            }
+            VECTOR2D d = m_dragStartPoint - mousePos;
 
-            if( !justWarped )
+            if( d.y != 0.0 )
             {
-                VECTOR2D d = m_dragStartPoint - mousePos;
-                m_dragStartPoint = mousePos;
-
                 double scale = exp( d.y * m_settings.m_zoomSpeed * 0.001 );
 
                 wxLogTrace( traceZoomScroll, wxString::Format( "dy: %f  scale: %f", d.y, scale ) );
 
-                m_view->SetScale( m_view->GetScale() * scale, m_view->ToWorld( m_zoomStartPoint ) );
-                aEvent.StopPropagation();
+                m_view->SetScale( m_view->GetScale() * scale,
+                                  m_view->ToWorld( m_zoomStartPoint ) );
             }
 
-            if( warpY )
-            {
-                if( !justWarped )
-                {
-                    KIPLATFORM::UI::WarpPointer( m_parentPanel, x, y + warpY );
-                    m_dragStartPoint += VECTOR2D( 0, warpY );
-                    justWarped = true;
-                }
-                else
-                    justWarped = false;
-            }
-            else
-            {
-                justWarped = false;
-            }
+            // Lock cursor at the initial smooth zoom position
+            KIPLATFORM::UI::WarpPointer( m_parentPanel,
+                                         (int) m_smoothZoomCursorScreenPos.x,
+                                         (int) m_smoothZoomCursorScreenPos.y );
+            m_dragStartPoint = m_smoothZoomCursorScreenPos;
+
+            aEvent.StopPropagation();
         }
     }
```

#### 6.6.4. Модификация `common/view/wx_view_controls.cpp` — CancelDrag()

```diff
--- a/common/view/wx_view_controls.cpp
+++ b/common/view/wx_view_controls.cpp
@@ -800,6 +800,13 @@ void WX_VIEW_CONTROLS::CancelDrag()
     if( m_state == DRAG_PANNING || m_state == DRAG_ZOOMING )
     {
+        if( m_smoothZoomCursorHidden )
+        {
+            m_parentPanel->SetCursor( wxNullCursor );
+            m_smoothZoomCursorHidden = false;
+        }
+
         setState( IDLE );

 #if defined USE_MOUSE_CAPTURE
```

### 6.7. Настройки

**Вариант A (минимальный, рекомендуется):** Не добавлять отдельную настройку. Новое поведение применяется автоматически, когда `drag_middle = ZOOM`. Пользователь уже может переключить middle button drag на Pan или None через настройки.

**Вариант B (расширенный):** Добавить чекбокс в диалог настроек мыши.

Если реализовать вариант B:

1. **`include/settings/common_settings.h`** — добавить поле:
```cpp
struct INPUT
{
    // ...существующие поля...
    bool smooth_zoom_lock_cursor;  // ← НОВОЕ: фиксировать курсор при drag zoom
};
```

2. **`common/settings/common_settings.cpp`** — добавить параметр:
```cpp
m_params.emplace_back( new PARAM<bool>( "input.smooth_zoom_lock_cursor",
        &m_Input.smooth_zoom_lock_cursor, true ) );
```

3. **`include/view/view_controls.h`** — добавить в VC_SETTINGS:
```cpp
bool m_smoothZoomLockCursor;
```

4. **`common/view/wx_view_controls.cpp`** — загрузка:
```cpp
m_settings.m_smoothZoomLockCursor = cfg->m_Input.smooth_zoom_lock_cursor;
```

5. **`common/dialogs/panel_mouse_settings_base.fbp`** — добавить чекбокс в wxFormBuilder.

6. **`common/dialogs/panel_mouse_settings.cpp`** — маппинг чекбокса.

**Для минимальной реализации (Вариант A) никаких изменений в настройках не требуется.**

### 6.8. Тестирование

#### 6.8.1. Ручное тестирование

| # | Тест | Ожидаемый результат |
|---|------|---------------------|
| 1 | Настройки: Middle Button = Zoom. Зажать среднюю кнопку | Курсор скрывается |
| 2 | Зажать среднюю + двигать вверх | Изображение плавно увеличивается |
| 3 | Зажать среднюю + двигать вниз | Изображение плавно уменьшается |
| 4 | Отпустить среднюю кнопку | Курсор появляется в той же точке |
| 5 | Точка под курсором при zoom | Остаётся неподвижной |
| 6 | Настройки: Middle Button = Pan. Зажать среднюю | Курсор НЕ скрывается, pan как обычно |
| 7 | Настройки: Middle Button = None. Зажать среднюю | Ничего не происходит |
| 8 | Быстрое движение мыши при zoom | Нет дёрганий или артефактов |
| 9 | Zoom до минимума (minScale) | Zoom останавливается, без ошибок |
| 10 | Zoom до максимума (maxScale) | Zoom останавливается, без ошибок |
| 11 | Правой кнопкой + ZOOM mode | Такое же поведение как со средней |
| 12 | CancelDrag() (например, Escape) | Курсор восстанавливается, состояние IDLE |
| 13 | Alt+Tab во время zoom | Курсор восстанавливается |

#### 6.8.2. Автоматическое тестирование

Для юнит-тестов можно использовать QA Framework KiCad:

```cpp
// Файл: qa/tests/common/view/test_wx_view_controls.cpp

#include <boost/test/unit_test.hpp>
#include <view/view.h>
#include <view/wx_view_controls.h>

BOOST_AUTO_TEST_CASE( SmoothDragZoomScaleCalculation )
{
    // Проверка, что exp(dy * speed * 0.001) корректна для разных dy
    double speed = 5; // default zoom speed
    
    // dy > 0 (движение вверх, zoom in)
    double scale_in = exp( 10.0 * speed * 0.001 );
    BOOST_CHECK( scale_in > 1.0 );
    
    // dy < 0 (движение вниз, zoom out)  
    double scale_out = exp( -10.0 * speed * 0.001 );
    BOOST_CHECK( scale_out < 1.0 );
    
    // dy == 0 (без движения)
    double scale_none = exp( 0.0 * speed * 0.001 );
    BOOST_CHECK_CLOSE( scale_none, 1.0, 1e-10 );
}
```

#### 6.8.3. Платформо-специфичное тестирование

| Платформа | Что проверить |
|-----------|---------------|
| Linux (X11) | WarpPointer работает, курсор скрывается |
| Linux (Wayland) | WarpPointer может не работать! Нужно протестировать |
| Windows | CaptureMouse + скрытие курсора |
| macOS | SetCursor(wxCURSOR_BLANK) может не работать. Альтернатива: `[NSCursor hide]` |

**Потенциальная проблема на Wayland:**

На Wayland `KIPLATFORM::UI::WarpPointer` может не работать (Wayland не позволяет приложениям перемещать курсор). В текущей кодовой базе KiCad уже есть обработка этой ситуации:

```cpp
// Файл: libs/kiplatform/port/wxgtk/ui.cpp, строка 592
bool KIPLATFORM::UI::InfiniteDragPrepareWindow( wxWindow* aWindow )
{
    wxLogTrace( traceWayland, wxS( "InfiniteDragPrepareWindow" ) );
    // ... Wayland-specific code ...
}
```

Для Wayland может потребоваться альтернативный подход: использовать `pointer-constraints` протокол Wayland для блокировки указателя.

---

## Дополнительные заметки

### A. Формула масштабирования

Текущая формула в DRAG_ZOOMING:
```
scale = exp(dy * zoomSpeed * 0.001)
```

Где:
- `dy` — разница по Y между текущей и предыдущей позицией мыши (в пикселях)
- `zoomSpeed` — настройка скорости (целое число, по умолчанию 5)
- `0.001` — нормализующий коэффициент

**Свойства формулы:**
- `dy > 0` (мышь вверх) → `scale > 1` → zoom in
- `dy < 0` (мышь вниз) → `scale < 1` → zoom out
- `dy = 0` → `scale = 1` → без изменений
- Экспоненциальная функция обеспечивает **симметричность**: одни и те же пиксели вверх и вниз дают одинаковое увеличение/уменьшение

### B. Anchor point (неподвижная точка)

Функция `VIEW::SetScale(scale, anchor)` обеспечивает неподвижность точки `anchor` при масштабировании:

```cpp
void VIEW::SetScale( double aScale, VECTOR2D aAnchor )
{
    VECTOR2D a = ToScreen( aAnchor );           // экранные координаты anchor до zoom
    m_scale = aScale;                            // новый масштаб
    m_gal->SetZoomFactor( m_scale );
    m_gal->ComputeWorldScreenMatrix();           // пересчитать матрицу
    VECTOR2D delta = ToWorld( a ) - aAnchor;     // дрифт anchor
    SetCenter( m_center - delta );               // компенсировать дрифт
}
```

Это **именно тот механизм**, который нужен: точка под курсором остаётся неподвижной.

### C. Сравнение с другими приложениями

| Приложение | Поведение |
|------------|-----------|
| **Blender** | MMB drag = orbit, shift+MMB = pan, ctrl+MMB = smooth zoom (именно то, что мы делаем) |
| **ZBrush** | RMB drag up/down = smooth zoom |
| **Fusion 360** | MMB = orbit, scroll = zoom, shift+MMB = pan |
| **SolidWorks** | MMB = rotate, shift+MMB = pan, scroll = zoom |
| **Altium Designer** | MMB drag = pan, scroll = zoom |
| **KiCad (текущий)** | MMB drag = pan (default) / zoom (настраиваемо), scroll = zoom |

### D. Потенциальные улучшения (опционально, вне текущего ТЗ)

1. **Индикатор zoom уровня** — показывать overlay с текущим процентом масштаба
2. **Сглаживание (smoothing)** — использовать EMA (exponential moving average) для плавности
3. **Мёртвая зона** — игнорировать маленькие смещения мыши (< 2-3px) для предотвращения дрожания
4. **Визуальная подсказка** — показать иконку zoom при входе в режим
5. **Комбинация Pan+Zoom** — использовать горизонтальное смещение для pan, вертикальное для zoom

### E. Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| WarpPointer не работает на Wayland | Высокая | Использовать relative_pointer + pointer_constraints протокол |
| SetCursor(wxCURSOR_BLANK) не работает на macOS | Средняя | Использовать [NSCursor hide]/[NSCursor unhide] |
| Конфликт с инструментами (drag + zoom) | Низкая | aEvent.StopPropagation() уже используется |
| Быстрое движение → большой dy → резкий zoom | Средняя | Ограничить max dy или использовать сглаживание |
| Потеря захвата мыши (focus change) | Низкая | Обработчик onCaptureLost() + восстановление курсора |

---

## Итого

### Минимальная реализация

Для реализации плавного масштабирования необходимо изменить **2 файла**:

1. **`include/view/wx_view_controls.h`** — добавить 2 поля (3 строки)
2. **`common/view/wx_view_controls.cpp`** — модифицировать 3 функции (~40 строк изменений)

### Оценка трудозатрат

| Задача | Время |
|--------|-------|
| Модификация кода | 1-2 часа |
| Тестирование (Linux) | 1 час |
| Тестирование (Windows, macOS) | 2-3 часа |
| Обработка Wayland edge-cases | 2-4 часа |
| Code review + исправления | 1-2 часа |
| **Итого** | **7-12 часов** |

### Зависимости

Нет внешних зависимостей. Все используемые API уже присутствуют в кодовой базе KiCad:
- `wxWindow::SetCursor()` — стандартный wxWidgets
- `KIPLATFORM::UI::WarpPointer()` — уже реализован для всех платформ
- `VIEW::SetScale()` — уже реализован с anchor point
- `CaptureMouse()/ReleaseMouse()` — уже используется в DRAG_PANNING
