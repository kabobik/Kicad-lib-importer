# Исследование: панели KiCad, wxAUI и Wayland

Дата: 2026-07-03

## Краткий вывод

Проблема с панелями KiCad под native Wayland не связана с конкретной панелью
`Properties`, `Hierarchy`, `Net Navigator` или локальными патчами вроде
`lib_tree_model`. Эти панели управляются через `wxAuiManager`, а классическая
модель wxAUI предполагает, что оторванная панель становится отдельным top-level
окном ОС.

На X11 приложение может достаточно свободно получать глобальную геометрию окон,
двигать окна и определять, где floating-панель находится относительно главного
окна. На Wayland эти операции намеренно ограничены: compositor владеет
размещением окон, фокусом и глобальными координатами. Поэтому drag-to-dock через
отдельные floating windows под Wayland ненадёжен архитектурно.

Практически это означает:

- текущий X11-style docking KiCad/wxAUI полноценно и стабильно не переносится на
  native Wayland;
- панели KiCad могут нормально работать под Wayland, если отказаться от native
  floating top-level окон;
- самый реалистичный малый патч: Wayland-safe режим, где панели не могут
  становиться floating и сохранённые floating-состояния нормализуются обратно в
  docked layout;
- архитектурно правильный большой путь: internal dock/overlay manager внутри
  главного окна KiCad.

## Наблюдаемая проблема

Симптом:

- панель `Properties` работает как отдельное окно;
- вернуть её обратно как боковую панель drag-and-drop не получается;
- на X11 то же действие работает нормально;
- на Wayland проблема воспроизводится.

В исходниках KiCad панели добавляются через `wxAuiManager`, например в
`eeschema/sch_edit_frame.cpp`:

```cpp
m_auimgr.AddPane( m_hierarchy, EDA_PANE().Palette().Name( SchematicHierarchyPaneName() )
                  .Caption( _( "Schematic Hierarchy" ) )
                  .Left().Layer( 3 ).Position( 1 )
                  .TopDockable( false )
                  .BottomDockable( false )
                  .CloseButton( true )
                  .Show( false ) );

m_auimgr.AddPane( m_propertiesPanel, defaultPropertiesPaneInfo( this ) );
m_auimgr.AddPane( createHighlightedNetNavigator(), defaultNetNavigatorPaneInfo() );
```

`Properties` по умолчанию описана как dockable pane:

```cpp
paneInfo.Name( EDA_DRAW_FRAME::PropertiesPaneName() )
        .Caption( _( "Properties" ) )
        .Left().Layer( 3 ).Position( 2 )
        .TopDockable( false )
        .BottomDockable( false )
        .CloseButton( true )
        .Show( true );
```

То есть проблема не в содержимом панели, а в механизме docking/floating.

## Почему Wayland ломает этот сценарий

Классическая схема wxAUI:

```text
панель оторвали -> создано отдельное окно ОС -> пользователь тащит окно ->
wxAUI определяет dock target по позиции -> панель снова встраивается в frame
```

Для этого приложению нужны X11-подобные возможности:

- знать глобальные координаты top-level окон;
- сопоставлять floating window с областью главного окна;
- надёжно управлять позицией top-level окон;
- восстанавливать сохранённые позиции и размеры;
- предсказуемо работать с focus/activation во время drag.

Wayland намеренно ограничивает эти возможности. Приложение рисует своё
содержимое, но не является владельцем рабочего стола. Позиционирование,
размещение окон и глобальная геометрия находятся у compositor.

Это повышает безопасность и изоляцию приложений, но плохо совместимо с
старыми desktop-механиками вроде docking через отдельные floating windows.

## Что говорит сообщество и апстрим

В официальном посте KiCad "KiCad and Wayland Support" от 2025-06-10 среди
известных проблем перечислены:

- docked panels/toolbars cannot be properly managed or restored;
- dragging tabs and panels between areas is broken or unreliable;
- window positioning/focus issues;
- проблемы с pointer warp.

Позиция KiCad: для стабильной профессиональной работы на Linux рекомендуется
использовать X11/XWayland, а Wayland-only проблемы часто находятся вне зоны,
которую KiCad может исправить внутри приложения.

Практические workaround'ы сообщества:

```bash
GDK_BACKEND=x11 kicad
```

Для Flatpak:

```bash
flatpak run --env=GDK_BACKEND=x11 org.kicad.KiCad
```

Если раскладка уже сохранена в плохом состоянии, помогает сброс `aui_state` или
`perspective` в настройках редактора, например `eeschema.json` / `pcbnew.json`.

Источники:

- https://www.kicad.org/blog/2025/06/KiCad-and-Wayland-Support/
- https://www.kicad.org/help/known-system-related-issues/
- https://gitlab.com/kicad/code/kicad/-/issues/22718

## Малый реалистичный патч: Wayland-safe AUI mode

Цель: не чинить drag-to-dock на Wayland, а не допускать состояния, где панель
оторвалась и не может вернуться.

Идея:

```text
Wayland detected:
  - disable floating for side panels
  - normalize saved floating panes back to docked
  - add Reset/Dock Panels command
```

Возможная реализация:

- для проблемных `wxAuiPaneInfo` вызывать `.Floatable( false )`;
- после `RestoreAuiLayout()` проверять `IsFloating()` у известных панелей и
  принудительно делать `Dock().Left()` / `Dock().Right()` / `Bottom()`;
- сохранить ширину/высоту через существующие поля `m_AuiPanels`;
- добавить команду меню `Reset Panel Layout` или `Dock All Panels`.

Плюсы:

- небольшой объём работы;
- не требует новых зависимостей;
- сохраняет текущую архитектуру KiCad;
- прямо решает проблему "панель стала отдельным окном и не возвращается".

Минусы:

- на Wayland не будет полноценного floating-window UX;
- это адаптация поведения, а не настоящий internal docking engine.

Оценка: несколько часов для первого прототипа, 1-2 дня для аккуратного патча по
`eeschema`/`pcbnew`, больше если покрывать все редакторы и настройки.

## Большой вариант: internal dock/overlay manager на wxWidgets

Архитектурно правильный путь для Wayland: не делать floating-панель отдельным
окном ОС. Панель остаётся child window внутри главного frame, а перемещение,
hit-test и dock preview считаются в координатах главного окна.

Минимальная модель:

```text
main frame
  canvas
  left/right/bottom dock zones
  tab stacks
  splitter resize
  internal floating child panels
  drag preview overlay
```

Стек:

- `wxWindow` / `wxPanel` для существующих панелей;
- `wxSplitterWindow` или собственный layout на sizer'ах;
- `wxNotebook` / `wxAuiNotebook` для tab stacks, если подходит;
- существующий `nlohmann::json` для layout state;
- текущие KiCad settings/actions/theme/DPI helpers.

Новые внешние зависимости не обязательны. Qt, Electron, CEF или ImGui для этой
задачи лучше не тащить в текущий KiCad: они добавят runtime, packaging, focus,
event-loop и styling проблемы.

## Риски internal manager

Новый manager почти гарантированно принесёт новые классы UI-багов:

- focus и hotkeys: панель может съедать фокус у canvas или наоборот;
- HiDPI/fractional scaling: размеры splitter'ов и hit-test должны быть
  DIP-aware;
- macOS z-order/event routing: child overlay может вести себя иначе, чем на GTK
  и Windows;
- layout persistence: нужно переживать закрытые панели, смену монитора, смену
  DPI, обновление KiCad и переименование pane id;
- минимальные размеры: таблицы, деревья и property grid нельзя сжимать до
  нерабочего состояния;
- миграция старого `aui_state` / `perspective`;
- смешанный режим, если часть UI остаётся на wxAUI, а часть переезжает в новый
  manager.

Главный риск не Wayland, а качество новой подсистемы layout/panels. wxAUI сейчас
даёт много поведения "из коробки", пусть и с проблемами на Wayland. Новый
manager должен заново решить resize, tabbing, show/hide, persistence, dock
preview и взаимодействие с canvas.

## Оценка трудозатрат internal manager

Оценка для ограниченной цели, без полного переписывания wxAUI:

- прототип: 1-2 недели;
- usable версия для `eeschema`: 3-6 недель;
- распространение на `pcbnew`, symbol editor, footprint editor: 2-4 месяца;
- upstream-quality реализация с нормальным тестированием: дольше, потому что
  основной объём уйдёт на edge cases и платформенное поведение.

Если цель практическая, лучше начать с Wayland-safe режима поверх wxAUI. Если
цель исследовательская или архитектурная, internal dock manager на wxWidgets -
самый разумный большой путь без смены UI-стека.

## Сравнение с Electron/web-подходом

Electron и web UI часто лучше переживают Wayland не потому, что Wayland там
магически исправлен, а потому что интерфейс обычно живёт внутри одного
top-level окна. Docking, tabs и panels реализованы внутри HTML/CSS/JS surface,
а не через отдельные окна ОС.

Если Electron-приложение начнёт использовать несколько настоящих окон ОС, те же
ограничения Wayland вернутся:

- нет X11-подобного глобального позиционирования;
- focus/activation зависят от compositor;
- screen capture, pointer lock и глобальные hotkeys требуют portal/protocol;
- поведение отличается между GNOME, KDE и wlroots.

Для KiCad переписывание на Electron ради docking не выглядит оправданным:
появятся IPC, runtime, packaging, memory и native integration проблемы. Более
прагматично оставить wxWidgets и изменить модель panel management.

## Рекомендация

Для локального набора патчей KiCad рациональная последовательность такая:

1. Сделать Wayland-safe AUI mode:
   - запретить floating для известных side/bottom панелей под Wayland;
   - нормализовать сохранённые floating panes в docked state;
   - добавить reset/dock command.
2. Если этого окажется мало, сделать экспериментальный internal dock-only
   manager для одного редактора (`eeschema`).
3. Только после успешного прототипа думать о tab stacks, internal floating
   child panels и распространении на остальные редакторы.

Полноценный drag-to-dock "как на X11" через native floating windows под Wayland
не стоит считать реалистичной целью. Панели под Wayland стоит проектировать как
внутреннюю часть главного окна KiCad.
