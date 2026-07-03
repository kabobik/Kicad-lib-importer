# План реализации: боковая панель компонентов KiCad

Дата: 2026-07-03

## Цель

Сделать боковую панель компонентов в редакторе схем KiCad на базе существующего
окна выбора символа. Текущий chooser уже содержит нужные блоки:

1. Поиск и настройки дерева.
2. Дерево библиотек/символов.
3. Информация о выбранном символе.
4. Превью символа и footprint.

Для боковой панели эти блоки должны располагаться последовательно по вертикали,
а не в широком split-layout диалога.

## Базовые решения

- Не копировать `DIALOG_SYMBOL_CHOOSER` целиком.
- Переиспользовать существующие компоненты:
  - `LIB_TREE`
  - `SYMBOL_TREE_MODEL_ADAPTER`
  - `SYMBOL_PREVIEW_WIDGET`
  - `FOOTPRINT_SELECT_WIDGET`
  - `FOOTPRINT_PREVIEW_WIDGET`
  - `HTML_WINDOW`
- Вынести из `PANEL_SYMBOL_CHOOSER` общий reusable-код и оставить диалог только
  как один из layout/host вариантов.
- Сохранить поддержку group-by-column из
  `patches/kicad-10.0.4/0002-library-tree-group-by-column.patch`.
- В боковой панели отключить hover popup preview дерева: постоянное встроенное
  превью делает popup лишним и уменьшает Wayland-риск.

## Текущие точки входа в коде

| Файл | Роль |
|---|---|
| `eeschema/dialogs/dialog_symbol_chooser.cpp` | Модальная обёртка над `PANEL_SYMBOL_CHOOSER` |
| `eeschema/widgets/panel_symbol_chooser.cpp` | Основная логика выбора символа и текущий split-layout |
| `include/widgets/lib_tree.h`, `common/widgets/lib_tree.cpp` | Поиск, дерево, details, context menu колонок/group-by |
| `eeschema/symbol_tree_model_adapter.cpp` | Загрузка символов, поля, `GenerateInfo()` |
| `common/lib_tree_model_adapter.cpp` | Общий adapter, group-by, сохранение колонок |
| `eeschema/widgets/symbol_preview_widget.cpp` | Превью символа |
| `common/widgets/footprint_preview_widget.cpp` | Превью footprint |
| `eeschema/sch_edit_frame.cpp` | AUI-панели редактора схем |
| `eeschema/menubar.cpp` | `View -> Panels` |
| `eeschema/tools/sch_actions.*` | Actions для show/hide панели |
| `eeschema/tools/sch_editor_control.cpp` | Tool handler для toggle панели |

## Важная предварительная проверка

Патч group-by уже добавляет `APP_SETTINGS_BASE::LIB_TREE::group_by_column` и
логику в `LIB_TREE_MODEL_ADAPTER::loadColumnConfig()`.

Но `SYMBOL_TREE_MODEL_ADAPTER::loadColumnConfig()` переопределяет базовый метод.
Перед реализацией панели нужно проверить и при необходимости добавить туда:

```cpp
m_groupByColumn = m_cfg.group_by_column;
```

Иначе group-by может сохраняться в базовых деревьях, но не восстанавливаться в
дереве символов.

## Фаза 1. Развязать chooser от модального диалога

Проблема: `PANEL_SYMBOL_CHOOSER` сейчас содержит modal assumptions:

- `static SCH_BASE_FRAME* m_frame`;
- accept/escape handlers для `EndModal()`;
- double-click close timer;
- сохранение размеров окна chooser в `m_SymChooserPanel.width/height`;
- layout жёстко построен вокруг horizontal/vertical splitters.

Работы:

1. Заменить `static SCH_BASE_FRAME* m_frame` на обычный member.
2. Вынести modal-only поведение в `DIALOG_SYMBOL_CHOOSER` или отдельный режим.
3. Сохранить общую логику:
   - создание `SYMBOL_TREE_MODEL_ADAPTER`;
   - загрузка libraries/history/already placed;
   - обработка `EVT_LIBITEM_SELECTED`;
   - обновление symbol/footprint preview;
   - footprint selector и `m_field_edits`.
4. Проверить, что текущий диалог выбора символа продолжает работать без
   изменений поведения.

## Фаза 2. Новый reusable виджет для browser/sidebar

Создать новый виджет, условное имя:

```cpp
SCH_SYMBOL_LIBRARY_PANE
```

или:

```cpp
PANEL_SYMBOL_LIBRARY_BROWSER
```

Минимальная структура:

```text
SCH_SYMBOL_LIBRARY_PANE
  search/settings row        (внутри LIB_TREE)
  LIB_TREE                   (compact mode)
  HTML_WINDOW details
  SYMBOL_PREVIEW_WIDGET
  FOOTPRINT_SELECT_WIDGET
  FOOTPRINT_PREVIEW_WIDGET
```

Рекомендуемая компоновка:

```text
vertical root sizer
  LIB_TREE with SEARCH (+ tree only)
  horizontal splitter or fixed/min section:
    details HTML_WINDOW
  SYMBOL_PREVIEW_WIDGET
  FOOTPRINT_SELECT_WIDGET
  FOOTPRINT_PREVIEW_WIDGET
```

Для первого прототипа можно использовать `wxSplitterWindow` по вертикали, но
лучше держать их как внутренние split sections, а не AUI panes.

## Фаза 3. Compact mode для LIB_TREE

Текущий `LIB_TREE` уже строит:

- `wxSearchCtrl`;
- кнопка настроек;
- `WX_DATAVIEWCTRL`;
- optional `HTML_WINDOW details`;
- context menu заголовка с `Select Columns`, `Group by`, `Remove Grouping`.

Для боковой панели добавить режим/flags:

```cpp
COMPACT_COLUMNS
NO_HOVER_PREVIEW
```

Поведение:

- по умолчанию показывать только `Item`;
- `Description`, `Value`, `Footprint` оставить доступными через выбор колонок;
- описание показывать в `HTML_WINDOW` ниже дерева;
- не создавать `wxPopupWindow` hover preview;
- group-by оставить через context menu заголовка.

Если не хочется добавлять новые flags сразу, на первом этапе можно:

- передать внешний `HTML_WINDOW` как details;
- вызвать `m_tree->BlockPreview( true )`;
- настроить shown columns через adapter.

## Фаза 4. Размещение символа из боковой панели

Не дублировать `SCH_DRAWING_TOOLS::PlaceSymbol()`.

При double-click/Enter:

1. Получить `LIB_ID` и unit из `LIB_TREE`.
2. Загрузить `LIB_SYMBOL` через `SCH_BASE_FRAME::GetLibSymbol()`.
3. Собрать `PICKED_SYMBOL`:
   - `LibId`;
   - `Unit`;
   - `Fields` из footprint selector override;
   - `KeepSymbol`/`PlaceAllUnits` пока можно оставить false или вынести в
     compact controls позже.
4. Создать `SCH_SYMBOL`.
5. Запустить существующий placement tool:

```cpp
m_frame->GetToolManager()->PostAction(
        SCH_ACTIONS::placeSymbol,
        SCH_ACTIONS::PLACE_SYMBOL_PARAMS{ symbol.release(), true } );
```

Так placement, annotation, preview-moving, cancel и canvas-интеракция остаются
в существующем инструменте.

## Фаза 5. Интеграция в SCH_EDIT_FRAME

Добавить новую AUI-панель в редактор схем.

Работы:

1. Добавить member в `SCH_EDIT_FRAME`, например:

```cpp
SCH_SYMBOL_LIBRARY_PANE* m_symbolLibraryPane;
```

2. Создать pane рядом с существующими:

```cpp
m_symbolLibraryPane = new SCH_SYMBOL_LIBRARY_PANE( this );
```

3. Добавить в `m_auimgr`:

```cpp
m_auimgr.AddPane( m_symbolLibraryPane,
        EDA_PANE().Palette().Name( SymbolLibraryPaneName() )
        .Caption( _( "Symbols" ) )
        .Left().Layer( 3 ).Position( ... )
        .TopDockable( false )
        .BottomDockable( false )
        .CloseButton( true )
        .MinSize( FromDIP( wxSize( 240, 160 ) ) )
        .BestSize( FromDIP( wxSize( 320, 700 ) ) )
        .Show( cfg->m_AuiPanels.show_symbol_library_panel ) );
```

4. Добавить static pane name helper по аналогии с:
   - `SchematicHierarchyPaneName()`;
   - `NetNavigatorPaneName()`;
   - `DesignBlocksPaneName()`.

5. Добавить settings в `EESCHEMA_SETTINGS::AUI_PANELS`:

```cpp
bool show_symbol_library_panel;
int  symbol_library_panel_docked_width;
int  symbol_library_panel_float_width;
int  symbol_library_panel_float_height;
```

6. Добавить params в `eeschema_settings.cpp`.

## Фаза 6. Actions/menu/toolbar conditions

Добавить action:

```cpp
SCH_ACTIONS::showSymbolLibraryPanel
```

Примерные свойства:

```cpp
.Name( "eeschema.SymbolLibrary.showPanel" )
.Scope( AS_GLOBAL )
.FriendlyName( _( "Symbols" ) )
.Tooltip( _( "Show/hide the symbol library panel" ) )
.ToolbarState( TOOLBAR_STATE::TOGGLE )
.Icon( BITMAPS::library_browser )
```

Интеграция:

- `SCH_EDITOR_CONTROL::ToggleSymbolLibraryPanel()`;
- `Go( &SCH_EDITOR_CONTROL::ToggleSymbolLibraryPanel, ... )`;
- `View -> Panels`;
- action condition в `SCH_EDIT_FRAME`;
- при необходимости кнопка на toolbar.

## Фаза 7. Persistence и состояние

Сохранять:

- видимость панели;
- docked width;
- float size, если floating остаётся разрешён;
- tree columns/group-by/open libs через существующий `m_LibTree`;
- search string можно оставить текущей статикой или перенести в settings позже.

Для Wayland-safe поведения можно сразу рассмотреть:

- `.Floatable( false )` для новой панели под Wayland;
- или общий будущий Wayland-safe AUI mode из
  `docs/research/kicad-wayland-panels.md`.

## Фаза 8. Проверки

Минимальные ручные проверки:

- панель открывается/закрывается через `View -> Panels`;
- поиск фильтрует дерево;
- контекстное меню заголовка показывает `Select Columns`, `Group by`,
  `Remove Grouping`;
- group-by сохраняется и восстанавливается;
- выбор символа обновляет details;
- выбор символа обновляет symbol preview;
- footprint selector обновляется от выбранного символа;
- footprint preview показывает default/override footprint;
- double-click/Enter запускает placement tool;
- закрытие KiCad не оставляет активные GAL canvases;
- повторное открытие KiCad восстанавливает ширину и видимость панели;
- Wayland: нет hover popup preview и нет обязательного floating workflow.

## Основные риски

- `PANEL_SYMBOL_CHOOSER` сейчас не готов к постоянному lifetime из-за static
  frame pointer и modal callbacks.
- `LIB_TREE` в узкой панели может быть перегружен колонками; нужен compact mode.
- `SYMBOL_TREE_MODEL_ADAPTER::loadColumnConfig()` может не восстанавливать
  `group_by_column`, если не поправить override.
- GAL preview widgets требуют аккуратного shutdown при закрытии панели/frame.
- Placement из панели должен идти через существующий `SCH_ACTIONS::placeSymbol`,
  иначе легко продублировать и сломать annotation/undo/preview логику.

## Рекомендуемая последовательность

1. Исправить/проверить восстановление `group_by_column` в
   `SYMBOL_TREE_MODEL_ADAPTER`.
2. Убрать `static m_frame` из `PANEL_SYMBOL_CHOOSER`.
3. Добавить compact/no-hover режим в `LIB_TREE`.
4. Создать `SCH_SYMBOL_LIBRARY_PANE` с вертикальной компоновкой.
5. Подключить selection -> details/preview/footprint.
6. Подключить double-click/Enter -> `SCH_ACTIONS::placeSymbol`.
7. Встроить pane в `SCH_EDIT_FRAME` и меню.
8. Добавить settings persistence.
9. Проверить диалог symbol chooser на регрессии.
10. Проверить боковую панель на X11 и Wayland.
