# Multi-Project Architecture Research for KiCad Project Manager

**Дата:** 2026-02-13  
**Версия KiCad:** 9.0.x (ветка master)  
**Автор исследования:** Copilot deep-research

---

## Executive Summary

Текущая архитектура KiCad Project Manager жёстко привязана к модели «одно окно = один проект». Глобальная функция `Prj()` (kicad/kicad.cpp:601) возвращает `Kiway.Prj()` — единственный экземпляр `PROJECT` привязанный к глобальному `KIWAY Kiway` (kicad/kicad.cpp:425). Дерево проекта (`PROJECT_TREE`) использует один корень (`m_root`) и один `KIGIT_COMMON` для git-операций. **78 вызовов `Prj()`** в каталоге `kicad/`, **110 обращений** к git-объектам через `m_TreeProject->GetGitRepo()/GitCommon()` — всё это завязано на единственный проект.

Однако архитектура KiCad **уже предусматривает** многопроектность на уровне дизайна: диаграмма в `kiway.h` показывает множественные KIWAY для разных проектов, а `SETTINGS_MANAGER` хранит `m_projects_list` (vector) и `m_projects` (map). Это означает, что фундамент для multi-project существует, но не задействован в Project Manager.

**Рекомендуемый вариант:** Вариант A (множество корней в wxTreeCtrl с `wxTR_HIDE_ROOT`) — минимальные изменения, максимальная совместимость.

---

## 1. Текущая архитектура (подробно)

### 1.1 PROJECT "singleton" — как работает Prj()

**Файлы:**
- `kicad/kicad.cpp:599-603` — определение `Prj()`
- `include/project.h` — интерфейс класса `PROJECT`
- `include/settings/settings_manager.h:296` — `SETTINGS_MANAGER::Prj()`

```cpp
// kicad/kicad.cpp:599-603
// The C++ project manager supports one open PROJECT, so Prj() calls within
// the project manager are all the same PROJECT.
PROJECT& Prj()
{
    return Kiway.Prj();
}
```

```cpp
// kicad/kicad.cpp:425
KIWAY  Kiway( KFCTL_CPP_PROJECT_SUITE );
```

**Не настоящий singleton** — `PROJECT` это обычный класс без `static instance()`. Но в контексте Project Manager существует **ровно один** `KIWAY Kiway`, который содержит **ровно один** `PROJECT`. Функция `Prj()` — это просто удобный глобальный accessor.

**SETTINGS_MANAGER** уже хранит **множество** проектов:

```cpp
// include/settings/settings_manager.h:475-478
std::vector<std::unique_ptr<PROJECT>> m_projects_list;
std::map<wxString, PROJECT*> m_projects;
```

Метод `SETTINGS_MANAGER::LoadProject()` добавляет проект в оба контейнера. Однако `Prj()` возвращает только «активный» проект. Комментарий в коде (settings_manager.h:278):

> *"@todo This should be deprecated along with Prj() once we support multiple projects fully."*

**Вывод:** Инфраструктура для множества PROJECT-ов **есть**, но `Prj()` нужно заменить на явную передачу `PROJECT&` в вызовы.

### 1.2 KIWAY и маршрутизация

**Файлы:**
- `include/kiway.h:270-395` — класс `KIWAY`
- `include/kiway_player.h:63-115` — класс `KIWAY_PLAYER`

Диаграмма из kiway.h (строки 71-100) **явно показывает multi-project архитектуру**:

```
              ┏━━━process top━━━━━┓
              ┃                   ┃       wxEvent channels
  ┏━━━━━━━━━━━━━-━[KIWAY project 1]━-━━━━━━━━━━━━━━━━┓
  ┃           ┃                   ┃                  ┃
  ┃     ┏━━━━━-━[KIWAY project 2]━-━━━━━━━┓          ┃
  ┃     ┃     ┃                   ┃       ┃          ┃
  ┃     ┃   ┏━-━[KIWAY project 3]━-━┓     ┃          ┃
```

Каждый KIWAY содержит:
- Ссылку на `PROJECT` (`KIWAY::Prj()` — kiway.h:393)
- Массив `KIWAY_PLAYER` фреймов (`m_playerFrameId[KIWAY_PLAYER_COUNT]` — kiway.h:491)
- Ссылки на загруженные KIFACE DSO (eeschema, pcbnew и др.)

**Ключевой момент:** `KICAD_MANAGER_FRAME` — **НЕ** является KIWAY_PLAYER. Он наследует от `EDA_BASE_FRAME` (kicad_manager_frame.h:47):

```cpp
class KICAD_MANAGER_FRAME : public EDA_BASE_FRAME
```

А `EDA_BASE_FRAME` является `KIWAY_HOLDER`. При создании `KICAD_MANAGER_FRAME` ему передаётся `&::Kiway` (kicad_manager_frame.cpp:145):

```cpp
EDA_BASE_FRAME( parent, KICAD_MAIN_FRAME_T, title, pos, size,
                KICAD_DEFAULT_DRAWFRAME_STYLE,
                KICAD_MANAGER_FRAME_NAME, &::Kiway, unityScale )
```

**Может ли KIWAY_PLAYER работать с разными проектами?**

Из kiway_player.h:98:
> *"opening files from multiple projects into the same KIWAY_PLAYER is precluded"*

Каждый `KIWAY_PLAYER::OpenProjectFiles()` привязан к одному KIWAY (=одному PROJECT). Для открытия редактора другого проекта нужен **отдельный KIWAY**.

### 1.3 PROJECT_TREE_PANE и дерево

**Файлы:**
- `kicad/project_tree_pane.h` (336 строк)
- `kicad/project_tree_pane.cpp` (2762 строки)
- `kicad/project_tree.h` (78 строк)
- `kicad/project_tree.cpp` (248 строк)

**Как строится дерево — ReCreateTreePrj()** (project_tree_pane.cpp:617-731):

```cpp
void PROJECT_TREE_PANE::ReCreateTreePrj()
{
    // ...
    m_root = m_TreeProject->AddRoot( fn.GetFullName(),
                    static_cast<int>( TREE_FILE_TYPE::ROOT ),
                    static_cast<int>( TREE_FILE_TYPE::ROOT ) );
    m_TreeProject->SetItemBold( m_root, true );

    PROJECT_TREE_ITEM* data = new PROJECT_TREE_ITEM(
                    TREE_FILE_TYPE::JSON_PROJECT, fn.GetFullPath(), m_TreeProject );
    m_TreeProject->SetItemData( m_root, data );

    // Now adding all current files
    // ... итерация по файлам директории, добавление через addItemToProjectTree()

    m_TreeProject->Expand( m_root );
    m_TreeProject->SortChildren( m_root );
}
```

**Один корень `m_root`** — единственный `wxTreeItemId` корень дерева.

**wxTreeCtrl** поддерживает `wxTR_HIDE_ROOT` — если скрыть корень, можно добавить несколько дочерних элементов верхнего уровня, каждый из которых визуально будет выглядеть как отдельный корень.

Текущий стиль создания (project_tree.cpp:50-53):

```cpp
PROJECT_TREE::PROJECT_TREE( PROJECT_TREE_PANE* parent ) :
    wxTreeCtrl( parent, ID_PROJECT_TREE, wxDefaultPosition, wxDefaultSize,
                PLATFORM_STYLE | wxTR_HAS_BUTTONS | wxTR_MULTIPLE, ...)
```

Нет `wxTR_HIDE_ROOT` — дерево имеет видимый корень.

### 1.4 Git-привязка

**Файлы:**
- `kicad/project_tree.h:50-65` — одно поле `m_gitCommon`
- `common/git/kicad_git_common.h` — класс `KIGIT_COMMON`

```cpp
// project_tree.h:50
std::unique_ptr<KIGIT_COMMON> m_gitCommon;

// project_tree.h:62-65
void SetGitRepo( git_repository* aRepo )    { m_gitCommon->SetRepo( aRepo ); }
git_repository* GetGitRepo() const          { return m_gitCommon->GetRepo(); }
KIGIT_COMMON* GitCommon() const             { return m_gitCommon.get(); }
```

**Один `KIGIT_COMMON`** на весь `PROJECT_TREE`. Все git-операции в project_tree_pane.cpp (110 обращений) используют:
- `m_TreeProject->GetGitRepo()` — для получения `git_repository*`
- `m_TreeProject->GitCommon()` — для настроек (username, SSH key, branches)

**Git-таймеры** (project_tree_pane.h:324-325):
```cpp
wxTimer  m_gitSyncTimer;     // периодический fetch с remote
wxTimer  m_gitStatusTimer;   // обновление статуса файлов
```

Оба таймера — по одному экземпляру, привязаны к единственному репозиторию.

**Git-кэш и статусы** (project_tree_pane.h:327-331):
```cpp
std::mutex                                       m_gitTreeCacheMutex;
std::unordered_map<wxString, wxTreeItemId>       m_gitTreeCache;     // путь -> treeItem
std::mutex                                       m_gitStatusMutex;
std::map<wxTreeItemId, KIGIT_COMMON::GIT_STATUS> m_gitStatusIcons;   // item -> статус
bool                                             m_gitIconsInitialized;
```

### 1.5 Настройки проекта

**PROJECT_FILE** (`.kicad_pro`):
- Хранит metadata проекта, библиотеки, переменные
- Один файл на проект

**PROJECT_LOCAL_SETTINGS** (`.kicad_prl`):
- Хранит локальные настройки: открытые файлы, git username/ssh key, open job sets
- Используется: `Prj().GetLocalSettings()`

**COMMON_SETTINGS** (глобальные):
- `Pgm().GetCommonSettings()->m_Git.enableGit` — глобальная настройка
- `Pgm().GetCommonSettings()->m_Git.updatInterval` — интервал git sync

**KICAD_SETTINGS** (настройки менеджера):
- `m_OpenProjects` — список открытых проектов (уже есть!)
- `m_LeftWinWidth` — ширина дерева

Для multi-project **можно хранить** список проектов в `KICAD_SETTINGS::m_OpenProjects` (он уже существует!).

### 1.6 Файловый watcher

**Файл:** project_tree_pane.cpp:1445-1584

```cpp
void PROJECT_TREE_PANE::FileWatcherReset()
{
    // ...
    wxString prj_dir = wxPathOnly( m_Parent->GetProjectFileName() );

    // Создаёт watcher для директории проекта
    m_watcher = new wxFileSystemWatcher();
    m_watcher->SetOwner( this );

    // Добавляет корневую дир проекта и поддиректории
    fn.AssignDir( prj_dir );
    m_watcher->Add( fn );
    // ... добавление поддиректорий
}
```

**Один `wxFileSystemWatcher`** (`m_watcher`) — привязан к директории текущего проекта. Но wxFileSystemWatcher может следить за **множеством** директорий — достаточно вызвать `Add()` для каждой.

---

## 2. Зависимости и риски: "что сломается"

### 2.1 Количество Prj() вызовов

| Файл | Кол-во Prj() | Тип зависимости |
|------|-------------|-----------------|
| kicad_manager_frame.cpp | ~20 | GetProjectPath, SaveProject, ProjectSettings |
| project_tree_pane.cpp | ~15 | GitSettings, ProjectPath, ProjectName |
| tools/kicad_manager_control.cpp | ~18 | SaveAs, FileState, ProjectPath |
| files-io.cpp | ~5 | Archive/Unarchive operations |
| dialogs/panel_jobset.cpp | ~5 | Job execution |
| kicad.cpp / kicad_cli.cpp | 2 | Определение `Prj()` |
| **ИТОГО** | **~78** | |

### 2.2 GetProjectFileName / GetProjectFullName / GetProjectPath

**28+ вызовов** в `kicad/` — каждый возвращает путь **одного** текущего проекта. Ключевые:

- `m_Parent->GetProjectFileName()` в project_tree_pane.cpp — **12 вызовов**
- `Prj().GetProjectPath()` — **10 вызовов** в kicad_manager_frame.cpp
- `Prj().GetProjectFullName()` — **8 вызовов** в tools/kicad_manager_control.cpp

### 2.3 Git-привязки к одному repo

**110 обращений** к `m_TreeProject/GetGitRepo/GitCommon` в project_tree_pane.cpp:

- `m_TreeProject->GetGitRepo()` — 15 вызовов в git-handler функциях
- `m_TreeProject->GitCommon()` — 8 вызовов для получения настроек
- `m_TreeProject->SetGitRepo()` — 3 вызова (init, create, cleanup)
- Git-таймеры — обращаются к единственному repo

### 2.4 Что ТОЧНО сломается при multi-project

| Компонент | Проблема | Сложность фикса |
|-----------|----------|-----------------|
| `Prj()` | Возвращает один PROJECT | Заменить на передачу контекста (MEDIUM) |
| `m_root` | Один корень дерева | Заменить на hidden root + children (LOW) |
| `m_gitCommon` | Один git-repo | Заменить на map (MEDIUM) |
| FileWatcher | Одна корневая директория | Добавить Watch для каждого корня (LOW) |
| Git timers | Один набор | Мультиплексировать или per-project (MEDIUM) |
| Git caches | Один set кэшей | Расширить на per-project (MEDIUM) |
| Context menu | Определяет vcs_has_repo для единого repo | Определять repo по выделенному элементу (LOW) |
| `CloseProject()` | Закрывает единственный проект | Нужно закрывать selected project (MEDIUM) |
| `LoadProject()` | Загрузка с закрытием текущего | Добавлять проект без закрытия существующих (HIGH) |
| Branch display | Один branch name на root | Branch name per project root (LOW) |

### 2.5 Редакторы и KIWAY_PLAYER

**Можно ли открыть eeschema для Project A и pcbnew для Project B?**

**Нет** в текущей архитектуре. Причины:
1. Один глобальный `Kiway` → один `PROJECT` → один набор `KIWAY_PLAYER`
2. `Kiway.Player(FRAME_SCH)` возвращает **один** редактор schematic
3. `KIWAY_PLAYER::OpenProjectFiles()` (kiway_player.h:98): *"opening files from multiple projects into the same KIWAY_PLAYER is precluded"*

**Для полной multi-project** нужны **отдельные KIWAY** для каждого проекта, что является глубокой архитектурной переделкой. Однако для **MVP** (показать несколько деревьев с git-статусами) редакторы можно оставить в режиме "один active project".

---

## 3. Три варианта реализации

### 3.1 Вариант A: Множество корней в одном wxTreeCtrl

**Концепция:**
```
wxTreeCtrl (wxTR_HIDE_ROOT)
├── Hidden Root (invisible)
│   ├── Project A (visible "root")
│   │   ├── a.kicad_sch
│   │   └── a.kicad_pcb
│   ├── Project B (visible "root")
│   │   ├── b.kicad_sch
│   │   └── b.kicad_pcb  
│   └── Library (visible "root")
│       ├── Caps.kicad_sym
│       └── IC.kicad_sym
```

**Реализация:**

1. Добавить `wxTR_HIDE_ROOT` в стиль `PROJECT_TREE`:
```cpp
// project_tree.cpp: конструктор
wxTreeCtrl( parent, ID_PROJECT_TREE, wxDefaultPosition, wxDefaultSize,
            wxTR_HIDE_ROOT | PLATFORM_STYLE | wxTR_HAS_BUTTONS | wxTR_MULTIPLE, ...)
```

2. Заменить `m_root` на `m_hiddenRoot` + `std::vector<wxTreeItemId> m_projectRoots`:
```cpp
// project_tree_pane.h
wxTreeItemId              m_hiddenRoot;
std::vector<wxTreeItemId> m_projectRoots;
```

3. `ReCreateTreePrj()` добавляет дочерние для hidden root:
```cpp
m_hiddenRoot = m_TreeProject->AddRoot( "HiddenRoot" );
for( const auto& prj : m_projectPaths ) {
    wxTreeItemId projRoot = m_TreeProject->AppendItem( m_hiddenRoot, prj.name );
    m_projectRoots.push_back( projRoot );
    populateProjectTree( projRoot, prj.path );
}
```

4. Для git — `map<wxString, unique_ptr<KIGIT_COMMON>>` вместо одного `m_gitCommon`:
```cpp
// project_tree.h
std::map<wxString, std::unique_ptr<KIGIT_COMMON>> m_gitRepos;  // path -> git
```

5. Определение repo по элементу — пройти вверх до project root:
```cpp
KIGIT_COMMON* getGitForItem( wxTreeItemId item ) {
    wxTreeItemId root = findProjectRoot( item );
    wxString path = getProjectPath( root );
    return m_gitRepos[path].get();
}
```

**Файлы для изменения:**

| Файл | Что менять | Строки | Риск |
|------|-----------|--------|------|
| project_tree.h | Заменить m_gitCommon на map | ~15 строк | LOW |
| project_tree.cpp | Стиль wxTR_HIDE_ROOT, конструктор | ~5 строк | LOW |
| project_tree_pane.h | m_root → m_hiddenRoot + m_projectRoots, новые поля | ~20 строк | LOW |
| project_tree_pane.cpp ReCreateTreePrj | Перестроить для multi-root | ~80 строк | MEDIUM |
| project_tree_pane.cpp onRight | Определять repo по выделенному элементу | ~30 строк | MEDIUM |
| project_tree_pane.cpp git handlers | Использовать getGitForItem() | ~50 строк | MEDIUM |
| project_tree_pane.cpp git timers | Мультиплексировать таймеры | ~40 строк | MEDIUM |
| project_tree_pane.cpp git caches | Per-project кэши | ~60 строк | MEDIUM |
| project_tree_pane.cpp FileWatcherReset | Добавить Watch для каждого проекта | ~20 строк | LOW |
| kicad_manager_frame.cpp | AddProject/RemoveProject методы | ~50 строк | LOW |
| kicad_manager_frame.h | Новые публичные методы | ~10 строк | LOW |
| **ИТОГО** | | **~380 строк** | **MEDIUM** |

**Преимущества:**
- Минимальные изменения в существующем коде
- wxTreeCtrl проверенный виджет
- Не ломает существующую навигацию
- Drag-and-drop между проектами возможен

**Недостатки:**
- Один wxTreeCtrl на все проекты — может быть медленным при >1000 файлов
- Иконки git-статуса нужно обрабатывать per-project

### 3.2 Вариант B: wxSplitterWindow с несколькими деревьями

**Концепция:**
```
wxScrolledWindow
├── CollapsiblePane "Project A [main] ●"
│   └── wxTreeCtrl (Project A tree)
├── CollapsiblePane "Project B [dev] ●2"
│   └── wxTreeCtrl (Project B tree)
└── CollapsiblePane "Library [main]"
    └── wxTreeCtrl (Library tree)
```

**Реализация:**

Каждый проект получает свой `PROJECT_TREE` внутри `wxCollapsiblePane`:

```cpp
struct ProjectPanel {
    wxCollapsiblePane*            pane;
    PROJECT_TREE*                 tree;
    std::unique_ptr<KIGIT_COMMON> git;
    wxTimer                       syncTimer;
    wxTimer                       statusTimer;
};
std::vector<ProjectPanel> m_panels;
```

**Файлы для изменения:**

| Файл | Что менять | Строки | Риск |
|------|-----------|--------|------|
| project_tree_pane.h | Новая структура ProjectPanel | ~30 строк | MEDIUM |
| project_tree_pane.cpp | Полная перестройка ReCreateTreePrj | ~200 строк | HIGH |
| project_tree.h | Убрать m_gitCommon (переместить в panel) | ~10 строк | LOW |
| project_tree.cpp | Обновить конструктор | ~10 строк | LOW |
| kicad_manager_frame.cpp/.h | Новые методы управления | ~60 строк | MEDIUM |
| **ИТОГО** | | **~310 строк** | **HIGH** |

**Преимущества:**
- Каждый проект полностью изолирован (свой tree, свой git)
- Проще git-мультиплексирование (каждый panel независим)
- Collapse/expand нативно

**Недостатки:**
- Множество wxTreeCtrl вместо одного — больше потребление ресурсов
- Event routing сложнее (какой tree сейчас active?)
- Selection между деревьями не работает нативно
- Нужен кастомный scroll-контейнер
- Ломает существующие event handlers (ID_PROJECT_TREE теперь множественный)

### 3.3 Вариант C: wxDataViewCtrl вместо wxTreeCtrl

**Концепция:**

Замена `wxTreeCtrl` на `wxDataViewCtrl` с виртуальной моделью данных:

```cpp
class MultiProjectModel : public wxDataViewModel {
    struct ProjectNode {
        wxString                          name;
        wxString                          path;
        std::unique_ptr<KIGIT_COMMON>     git;
        std::vector<FileNode>             files;
    };
    std::vector<ProjectNode> m_projects;
};
```

**Файлы для изменения:**

| Файл | Что менять | Строки | Риск |
|------|-----------|--------|------|
| project_tree.h/.cpp | Полная переписка (wxTreeCtrl → wxDataViewCtrl) | ~300 строк | VERY HIGH |
| project_tree_item.h/.cpp | Адаптация к DataViewModel | ~100 строк | HIGH |
| project_tree_pane.h/.cpp | Адаптация всех handlers | ~500 строк | VERY HIGH |
| **ИТОГО** | | **~900 строк** | **VERY HIGH** |

**Преимущества:**
- Виртуальная модель — отлично масштабируется
- Колонки (имя, статус, ветка) нативно
- Современный виджет wx

**Недостатки:**
- **Полная переписка** дерева и всех обработчиков
- Теряется совместимость с текущим кодом KiCad
- wxDataViewCtrl имеет platform-specific bugs
- Огромный объём тестирования

---

## 4. Git Multi-Repo план

### 4.1 Текущая git-архитектура

```
PROJECT_TREE
├── m_gitCommon: unique_ptr<KIGIT_COMMON>  ← ОДИН на всё дерево
│   ├── m_repo: git_repository*
│   ├── m_username, m_password, m_sshKey
│   └── methods: GetBranchNames, HasLocalCommits, etc.

PROJECT_TREE_PANE
├── m_gitSyncTimer      ← ОДИН таймер
├── m_gitStatusTimer    ← ОДИН таймер
├── m_gitTreeCache      ← ОДИН кэш (path → treeItemId)
├── m_gitStatusIcons    ← ОДИН кэш (treeItemId → status)
└── m_gitCurrentBranchName ← ОДНА ветка
```

### 4.2 Предлагаемая multi-repo архитектура (для Варианта A)

```
PROJECT_TREE (modified)
├── m_gitRepos: map<wxString, unique_ptr<KIGIT_COMMON>>
│   ├── "/path/to/projectA" → KIGIT_COMMON(repoA)
│   ├── "/path/to/projectB" → KIGIT_COMMON(repoB)
│   └── "/path/to/library"  → KIGIT_COMMON(repoLib)

PROJECT_TREE_PANE (modified)
├── m_gitSyncTimer      ← один таймер, мультиплексированный
├── m_gitStatusTimer    ← один таймер, мультиплексированный
├── m_gitTreeCaches: map<wxString, unordered_map<wxString, wxTreeItemId>>
├── m_gitStatusIcons    ← общий кэш (item → status), заполняется per-repo
└── m_gitBranchNames: map<wxString, wxString>  ← ветка per project
```

### 4.3 Новые методы

```cpp
// project_tree.h
class PROJECT_TREE : public wxTreeCtrl {
    std::map<wxString, std::unique_ptr<KIGIT_COMMON>> m_gitRepos;
public:
    void SetGitRepo( const wxString& aProjectPath, git_repository* aRepo );
    git_repository* GetGitRepo( const wxString& aProjectPath ) const;
    KIGIT_COMMON* GitCommon( const wxString& aProjectPath ) const;
    
    // Определить к какому проекту относится элемент дерева
    wxString GetProjectPathForItem( wxTreeItemId aItem ) const;
};
```

### 4.4 Мультиплексированный таймер

```cpp
void PROJECT_TREE_PANE::gitStatusTimerHandler()
{
    // Для каждого проекта обновляем кэш и статусы
    for( const auto& [path, git] : m_TreeProject->GetGitRepos() ) {
        updateTreeCacheForProject( path );
    }
    
    thread_pool& tp = GetKiCadThreadPool();
    tp.push_task( [this]() {
        for( const auto& [path, git] : m_TreeProject->GetGitRepos() ) {
            updateGitStatusIconMapForProject( path );
        }
    });
}
```

### 4.5 Определение repo по клику

При контекстном меню (onRight) и при git-операциях:

```cpp
KIGIT_COMMON* PROJECT_TREE_PANE::getGitForSelectedItem()
{
    std::vector<PROJECT_TREE_ITEM*> selection = GetSelectedData();
    if( selection.empty() ) return nullptr;
    
    wxString projectPath = m_TreeProject->GetProjectPathForItem( selection[0]->GetId() );
    return m_TreeProject->GitCommon( projectPath );
}
```

---

## 5. Минимальный PoC (Proof of Concept)

### Цель PoC

Показать 2+ проекта в одном дереве, каждый со своим git-статусом, без поломки открытия редакторов для «активного» проекта.

### Пошаговый план

#### Шаг 1: wxTR_HIDE_ROOT и множество корней (без git)

**Файлы:** project_tree.cpp, project_tree_pane.h, project_tree_pane.cpp

1. В `PROJECT_TREE` конструктор добавить `wxTR_HIDE_ROOT`:
   ```cpp
   // project_tree.cpp:50-53
   wxTreeCtrl( parent, ID_PROJECT_TREE, wxDefaultPosition, wxDefaultSize,
               wxTR_HIDE_ROOT | PLATFORM_STYLE | wxTR_HAS_BUTTONS | wxTR_MULTIPLE, ...)
   ```

2. В `project_tree_pane.h` добавить:
   ```cpp
   wxTreeItemId              m_hiddenRoot;
   std::vector<wxTreeItemId> m_projectRoots;
   std::vector<wxString>     m_projectPaths;  // пути к проектам
   ```

3. Переписать `ReCreateTreePrj()`:
   ```cpp
   void PROJECT_TREE_PANE::ReCreateTreePrj()
   {
       m_TreeProject->DeleteAllItems();
       m_projectRoots.clear();
       
       m_hiddenRoot = m_TreeProject->AddRoot( "Root" );  // invisible
       
       // Добавить текущий проект как первый корень
       wxString mainPrjPath = m_Parent->GetProjectFileName();
       if( !mainPrjPath.empty() )
           addProjectRoot( mainPrjPath );
       
       // Добавить дополнительные проекты из настроек
       for( const wxString& path : m_projectPaths )
           addProjectRoot( path );
   }
   
   wxTreeItemId PROJECT_TREE_PANE::addProjectRoot( const wxString& aProjectFile )
   {
       wxFileName fn( aProjectFile );
       wxTreeItemId projRoot = m_TreeProject->AppendItem( m_hiddenRoot, fn.GetFullName() );
       m_TreeProject->SetItemBold( projRoot, true );
       
       PROJECT_TREE_ITEM* data = new PROJECT_TREE_ITEM(
           TREE_FILE_TYPE::JSON_PROJECT, fn.GetFullPath(), m_TreeProject );
       m_TreeProject->SetItemData( projRoot, data );
       
       // Populate files
       wxDir dir( fn.GetPath() );
       if( dir.IsOpened() ) {
           // ... add files
       }
       
       m_TreeProject->Expand( projRoot );
       m_projectRoots.push_back( projRoot );
       return projRoot;
   }
   ```

4. Добавить UI для "Add Project":
   - Кнопка или пункт меню → wxFileDialog для выбора `.kicad_pro`
   - Добавление пути в `m_projectPaths` и пересоздание дерева

**Оценка:** ~150 строк изменений, 2-3 файла.

#### Шаг 2: Git multi-repo поддержка

**Файлы:** project_tree.h, project_tree_pane.cpp

1. Заменить `m_gitCommon` на map в `PROJECT_TREE`:
   ```cpp
   std::map<wxString, std::unique_ptr<KIGIT_COMMON>> m_gitRepos;
   ```

2. При `addProjectRoot()` — discover git repo для каждого проекта:
   ```cpp
   git_repository* repo = get_git_repository_for_file( fn.GetPath().c_str() );
   if( repo ) {
       m_TreeProject->SetGitRepo( fn.GetPath(), repo );
   }
   ```

3. Адаптировать git status update — итерировать по всем repos.

**Оценка:** ~100 строк изменений, 2 файла.

#### Шаг 3: Контекстное меню и git-операции per-project

**Файлы:** project_tree_pane.cpp

1. В `onRight()` — определять repo по выбранному элементу
2. В каждом git-handler — использовать `getGitForSelectedItem()` вместо `m_TreeProject->GetGitRepo()`

**Оценка:** ~80 строк изменений, 1 файл.

#### Шаг 4: Активный проект и редакторы

**Файлы:** kicad_manager_frame.cpp

1. При double-click на файл проекта — сделать его «активным» (LoadProject если другой)
2. Или: при double-click на .kicad_sch — открыть eeschema для этого проекта (если тот же KIWAY, нужен CloseProject+LoadProject)

**Это самая сложная часть** — пока оставить как "active project switch":
- Клик правой кнопкой на корне проекта → "Switch to this Project" (уже есть!)
- После switch — редакторы работают с новым активным проектом

**Оценка:** ~30 строк изменений, 1 файл.

#### Шаг 5: Сохранение/загрузка списка проектов

**Файлы:** settings/kicad_settings.h (или COMMON_SETTINGS)

`KICAD_SETTINGS::m_OpenProjects` уже существует. Нужно только использовать его при загрузке:

```cpp
void KICAD_MANAGER_FRAME::LoadSettings( APP_SETTINGS_BASE* aCfg )
{
    // ...
    auto settings = dynamic_cast<KICAD_SETTINGS*>( aCfg );
    m_leftWin->SetAdditionalProjects( settings->m_OpenProjects );
}
```

**Оценка:** ~20 строк изменений, 2 файла.

### Общая оценка PoC

| Шаг | Строки | Файлы | Сложность |
|-----|--------|-------|-----------|
| 1. Multi-root tree | ~150 | 3 | LOW |
| 2. Git multi-repo | ~100 | 2 | MEDIUM |
| 3. Context menu per-project | ~80 | 1 | LOW |
| 4. Active project switch | ~30 | 1 | LOW* |
| 5. Settings persistence | ~20 | 2 | LOW |
| **ИТОГО** | **~380** | **5** | **MEDIUM** |

*\* LOW только потому что мы не трогаем KIWAY — просто переключаем активный проект.*

---

## 6. Рекомендация

### Выбор: Вариант A (множество корней в одном wxTreeCtrl)

**Почему:**

1. **Минимальные изменения** (~380 строк vs ~310 для B, но B имеет HIGH risk, и ~900 для C)
2. **Совместимость** с текущим кодом KiCad — не ломает event handlers
3. **wxTR_HIDE_ROOT** — стандартный механизм wx, проверенный
4. **Инкрементальность** — можно делать по шагам, каждый шаг — рабочее состояние
5. **Git multi-repo** реализуется через простую map, без structural changes
6. **Не трогает KIWAY** — редакторы продолжают работать с "active project"

### Дорожная карта

```
Phase 1: PoC (2-3 недели)
├── Hidden root + multi-root tree
├── Git multi-repo (status icons per project)
├── Context menu per-project
└── Settings persistence

Phase 2: UX Polish (2 недели)
├── "Add Project" button/dialog
├── Drag-and-drop reorder
├── Branch indicator per root
├── Collapse/expand persistence
└── "Remove Project" (without deleting)

Phase 3: Multi-KIWAY (future, much later)
├── Multiple KIWAY instances
├── Independent editors per project
├── Cross-project DRC is NOT in scope
└── This is a separate major effort
```

---

## 7. Таблица изменений

| Файл | Что менять | Строки (+/-) | Риск |
|------|-----------|-------------|------|
| `kicad/project_tree.cpp` | Добавить `wxTR_HIDE_ROOT` в стиль виджета | +1/-1 | LOW |
| `kicad/project_tree.h` | Заменить `m_gitCommon` на `map<path, KIGIT_COMMON>`, добавить `GetProjectPathForItem()` | +20/-5 | MEDIUM |
| `kicad/project_tree_pane.h` | `m_root` → `m_hiddenRoot` + `m_projectRoots`, добавить `m_projectPaths`, `addProjectRoot()`, `getGitForItem()` | +25/-3 | LOW |
| `kicad/project_tree_pane.cpp:ReCreateTreePrj` (L617-731) | Перестроить для hidden root + multiple project roots | +80/-60 | MEDIUM |
| `kicad/project_tree_pane.cpp:onRight` (L768-1080) | Определять vcs_has_repo/git per-project root | +20/-5 | MEDIUM |
| `kicad/project_tree_pane.cpp:git handlers` (L1620-1765) | Использовать `getGitForItem()` вместо `m_TreeProject->GetGitRepo()` | +30/-15 | MEDIUM |
| `kicad/project_tree_pane.cpp:updateGitStatusIconMap` (L2070-2260) | Итерировать по всем repos | +40/-10 | MEDIUM |
| `kicad/project_tree_pane.cpp:updateTreeCache` (L2035-2070) | Per-project cache | +20/-5 | LOW |
| `kicad/project_tree_pane.cpp:gitStatusTimerHandler` (L2710-2720) | Мультиплексированный handler | +15/-5 | LOW |
| `kicad/project_tree_pane.cpp:FileWatcherReset` (L1445-1584) | Watch множество директорий проектов | +15/-3 | LOW |
| `kicad/project_tree_pane.cpp:EmptyTreePrj` (L1586-1598) | Очистить все git repos | +8/-3 | LOW |
| `kicad/project_tree_pane.cpp:findSubdirTreeItem` (L1260-1320) | Искать в правильном project root | +10/-3 | LOW |
| `kicad/project_tree_pane.cpp:onFileSystemEvent` (L1322-1442) | Определять root по пути | +5/-2 | LOW |
| `kicad/kicad_manager_frame.h` | Добавить `AddProject()`, `RemoveProject()`, `GetProjectPaths()` | +10/-0 | LOW |
| `kicad/kicad_manager_frame.cpp` | Реализация AddProject/RemoveProject | +40/-0 | LOW |
| **ИТОГО** |  | **+339/-120** (~460 строк затронуто) | **MEDIUM** |

---

## Приложение A: Ключевые строки кода

### Prj() определение
- `kicad/kicad.cpp:599-603` — `PROJECT& Prj() { return Kiway.Prj(); }`
- `kicad/kicad.cpp:425` — `KIWAY Kiway( KFCTL_CPP_PROJECT_SUITE );`

### PROJECT_TREE конструктор
- `kicad/project_tree.cpp:48-55` — стиль wxTreeCtrl (сюда добавить wxTR_HIDE_ROOT)

### ReCreateTreePrj — единый корень
- `kicad/project_tree_pane.cpp:685-693` — `m_root = m_TreeProject->AddRoot(...)`

### Git single repo
- `kicad/project_tree.h:50` — `std::unique_ptr<KIGIT_COMMON> m_gitCommon`
- `kicad/project_tree.h:62-65` — SetGitRepo/GetGitRepo/GitCommon accessors

### Git инициализация при открытии проекта
- `kicad/project_tree_pane.cpp:659-670` — `get_git_repository_for_file()` + SetGitRepo

### Context menu git detection
- `kicad/project_tree_pane.cpp:771-804` — `vcs_has_repo = m_TreeProject->GetGitRepo() != nullptr`

### Branch display on root item
- `kicad/project_tree_pane.cpp:2025-2027` — `m_TreeProject->SetItemText( kid, filename + " [" + m_gitCurrentBranchName + "]" )`

### Settings for open projects
- `include/settings/settings_manager.h:475-478` — `m_projects_list`, `m_projects` (уже map!)
- `include/settings/settings_manager.h:278` — TODO комментарий о multi-project

### File watcher
- `kicad/project_tree_pane.cpp:1449-1461` — `FileWatcherReset()` добавляет ОДНУ директорию

---

## Приложение B: Диаграмма предлагаемых изменений

```
┌───────────────────────────────────────────────────────────────┐
│  KICAD_MANAGER_FRAME                                         │
│  ├── m_projectPaths: vector<wxString>                        │
│  ├── AddProject(path)     ← NEW                              │
│  ├── RemoveProject(path)  ← NEW                              │
│  └── m_leftWin: PROJECT_TREE_PANE*                           │
│       ├── m_hiddenRoot: wxTreeItemId  ← RENAMED from m_root  │
│       ├── m_projectRoots: vector<wxTreeItemId>  ← NEW        │
│       ├── m_TreeProject: PROJECT_TREE*                        │
│       │    ├── m_gitRepos: map<path, KIGIT_COMMON>  ← NEW    │
│       │    └── GetProjectPathForItem()  ← NEW                 │
│       ├── m_watcher: wxFileSystemWatcher*                     │
│       │    ← watches ALL project dirs                         │
│       ├── m_gitSyncTimer  ← iterates ALL repos               │
│       ├── m_gitStatusTimer ← iterates ALL repos              │
│       └── m_gitBranchNames: map<path, string>  ← NEW         │
└───────────────────────────────────────────────────────────────┘
```
