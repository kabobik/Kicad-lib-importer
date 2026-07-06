# TODO: полноценная группировка списка компонентов KiCad

Дата: 2026-07-06

## Цель

Довести список компонентов KiCad до grouped-table/browser поведения, близкого к
референсам из `docs/screenshots`:

- активная группировка явно показана над таблицей как метки/chips с кнопкой
  удаления, например `ElementType` и `ElementSubType`;
- дерево компонентов строится многоуровнево по нескольким полям;
- поля, по которым выполнена группировка, не повторяются в колонках строк;
- первая tree-колонка остается технической колонкой wxDataViewCtrl, но может
  отображать полезное поле вроде `Description`, а не сырой `Item`;
- строки компонентов не показывают служебные префиксы вида
  `Графические элементы/3327`, если этот префикс уже представлен уровнем
  группировки;
- внешний вид боковой панели компактный и пригодный для постоянного docked UI.

## Исходное состояние до `0010`

- `patches/kicad-10.0.4/0002-library-tree-group-by-column.patch` добавляет
  одноуровневую группировку через `LIB_TREE_MODEL_ADAPTER::m_groupByColumn`.
- `LIB_TREE_NODE_GROUP` уже существует и может быть промежуточным узлом.
- Архитектура вокруг `GROUP` пока рассчитана в основном на один уровень:
  `flattenGroups()`, `FindItem()`, `GetItemCount()` и часть восстановления
  состояния обходят дерево не полностью рекурсивно.
- `m_shownColumns` одновременно означает и пользовательскую конфигурацию
  колонок, и фактические колонки отображения. Из-за этого grouped fields
  продолжают повторяться в таблице.
- Первая колонка `Item` нельзя просто скрыть: wxDataViewCtrl использует ее как
  tree-column с expander-иконками.

## Фаза 1. Модель многоуровневой группировки

- [x] Заменить `wxString m_groupByColumn` на
      `std::vector<wxString> m_groupByColumns`.
- [x] Добавить API в `LIB_TREE_MODEL_ADAPTER`:
      `SetGroupColumns()`, `AddGroupColumn()`, `RemoveGroupColumn()`,
      `GetGroupColumns()`, `ClearGroupColumns()`.
- [x] Расширить `APP_SETTINGS_BASE::LIB_TREE`:
      добавить `std::vector<wxString> group_by_columns`.
- [x] Не делать миграцию со старого `lib_tree.group_by_column`: для текущего
      сценария пользователь сбрасывает настройки окна перед тестированием.
- [x] Сохранить совместимость API для существующего кода через
      `SetGroupColumn()`/`GetGroupColumn()`.

## Фаза 2. Рекурсивное построение GROUP-дерева

- [x] Переписать `rebuildGroupNodes()` на рекурсивное построение:
      `LIBRARY -> GROUP(field0) -> GROUP(field1) -> ITEM`.
- [x] Расширить `LIB_TREE_NODE_GROUP` полями:
      `m_GroupColumn`, `m_GroupValue`. `m_GroupPath` пока не нужен.
- [x] Сделать `flattenGroups()` рекурсивным.
- [x] Перевести `FindItem()` на рекурсивный обход.
- [x] Исправить `GetItemCount()`, чтобы он считал реальные `ITEM`, а не только
      прямых детей библиотеки.
- [x] Проверить `GetChildren()`, `IsContainer()`, `GetParent()` для вложенных
      `GROUP`.
- [x] Проверить `AssignIntrinsicRanks()` и сортировку внутри групп.

## Фаза 3. Effective columns вместо прямого `m_shownColumns`

- [x] Оставить `m_shownColumns` как сохраненную пользовательскую настройку.
- [x] Добавить вычисляемый `GetEffectiveShownColumns()`.
- [x] Исключать из effective columns все поля из `m_groupByColumns`.
- [x] Не удалять обязательную tree-column физически.
- [x] Сохранять ширины колонок по исходным именам, чтобы снятие группировки
      восстанавливало прежний вид.
- [x] Убедиться, что поиск и ranking продолжают использовать исходные поля,
      включая grouped fields.

## Фаза 4. Настраиваемая tree-column

- [ ] Ввести параметр `m_treeDisplayColumn` или аналог.
- [ ] Tree-column остается первой колонкой wxDataViewCtrl, но для `ITEM` может
      показывать не `m_Name`, а значение выбранного поля: `Description`,
      `Part Number`, `Item`, etc.
- [ ] Для `LIBRARY` и `GROUP` tree-column продолжает показывать имя раздела или
      значение группы.
- [ ] Добавить настройки/дефолт для символов: вероятно `Description`.
- [ ] Проверить поведение modal chooser и symbol editor tree, чтобы изменение
      не испортило их UX.

## Фаза 5. Очистка отображаемого имени компонента

- [ ] Не менять `LIB_ID` и `LIB_TREE_NODE::m_Name` как источник истины.
- [ ] Добавить display-функцию для item-row.
- [ ] Если item name начинается с уже показанного group path, скрывать этот
      префикс только в отображении.
- [ ] Не использовать грубое правило "отрезать все до `/` всегда": это может
      сломать легитимные имена компонентов.
- [ ] Покрыть случаи:
      - `Графические элементы/3327` при группе `Графические элементы`;
      - вложенные группы `Диоды -> Шоттки`;
      - отсутствие совпадающего префикса;
      - пустые поля группировки.

## Фаза 6. UI меток группировки

- [ ] Добавить в `LIB_TREE` строку grouping chips под search/filter row.
- [ ] Показывать chips только когда `m_groupByColumns` не пуст.
- [ ] Chip содержит имя поля и кнопку удаления.
- [ ] Удаление chip вызывает `RemoveGroupColumn()`.
- [ ] Header context menu расширить пунктами:
      - `Group by this column`;
      - `Add to grouping`;
      - `Remove from grouping`;
      - `Clear grouping`.
- [ ] Опционально добавить reorder группировок через контекстное меню или
      drag/drop chips.

## Фаза 7. Compact mode для боковой панели

- [ ] Добавить флаг `LIB_TREE::COMPACT` или отдельный style/options объект.
- [ ] Уменьшить row height и вертикальные отступы.
- [ ] Уменьшить padding search/chips/header.
- [ ] Включить compact mode в `SCH_SYMBOL_LIBRARY_PANE`.
- [ ] Не менять дефолтный modal chooser без отдельного решения.

## Фаза 8. Проверка и разбиение на патчи

- [x] Собрать `cmake --build kicad-src-arch/build --target eeschema`.
- [x] Проверить dry-run применения нового патча поверх `0001-0009`.
- [ ] Разбить изменения на последовательные патчи:
      - [x] `0010-lib-tree-multigroup-model.patch` включает model,
        recursive groups и effective columns;
      - `0011-lib-tree-grouping-ui.patch`;
      - `0012-symbol-tree-display-cleanup.patch`;
      - `0013-symbol-tree-compact-display.patch`;
      - `0014-symbol-sidebar-details-polish.patch`.

## Блокеры и риски

- **Нет внешних блокеров.** Задача реализуема в текущем стеке wxWidgets/KiCad.
- **Главный одноуровневый блокер закрыт в `0010`.** Оставшиеся риски в UI:
  chips группировки, display value для tree-column и сохранение expanded state.
- **Общий adapter используется не только символами.** `LIB_TREE_MODEL_ADAPTER`
  общий для symbol/design-block деревьев, поэтому изменения надо делать
  обратимо и с дефолтами, чтобы не сломать другие деревья.
- **Tree-column нельзя скрыть напрямую.** Решение: оставить первую колонку как
  техническую, но отделить ее display value от поля `Item`.
- **Settings migration снята для текущего пользователя.** Старый
  `group_by_column` намеренно не читается; перед тестированием нужно сбросить
  настройки этого окна.
- **Поиск не должен деградировать.** Скрытие grouped columns из UI не должно
  удалять их из search terms.
- **Сохранение expanded state может сломаться.** Для nested groups нужны
  устойчивые ключи group path, а не только имена библиотек.
