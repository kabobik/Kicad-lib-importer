/*
 * Library Tree Panel for KiCad Project Manager — Implementation
 *
 * Copyright 2026 Anton Tsulin
 * License: GPL-3.0+
 */

#include "library_tree_panel.h"

#include <wx/sizer.h>
#include <wx/artprov.h>
#include <wx/menu.h>
#include <wx/msgdlg.h>
#include <wx/textdlg.h>

#include <git/kicad_git_common.h>
#include <git/kicad_git_memory.h>
#include <git/git_push_handler.h>
#include <git/git_pull_handler.h>
#include <git/git_commit_handler.h>

#include <dialogs/git/dialog_git_repository.h>
#include <dialogs/git/dialog_git_commit.h>
#include <widgets/wx_progress_reporters.h>

#include <trace_helpers.h>

static const wxChar* traceLibGit = wxT( "KICAD_LIB_GIT" );

// ═══════════════════════════════════════════════════════════════════════
// Таблица событий
// ═══════════════════════════════════════════════════════════════════════

wxBEGIN_EVENT_TABLE( LIBRARY_TREE_PANEL, wxPanel )
    EVT_TOOL( LIBRARY_TREE_PANEL::ID_LIB_PULL,    LIBRARY_TREE_PANEL::onPull )
    EVT_TOOL( LIBRARY_TREE_PANEL::ID_LIB_PUSH,    LIBRARY_TREE_PANEL::onPush )
    EVT_TOOL( LIBRARY_TREE_PANEL::ID_LIB_COMMIT,  LIBRARY_TREE_PANEL::onCommit )
    EVT_TOOL( LIBRARY_TREE_PANEL::ID_LIB_REFRESH, LIBRARY_TREE_PANEL::onRefresh )
    EVT_TOOL( LIBRARY_TREE_PANEL::ID_LIB_SETTINGS,LIBRARY_TREE_PANEL::onSettings )
    EVT_TREE_ITEM_RIGHT_CLICK( wxID_ANY,           LIBRARY_TREE_PANEL::onContextMenu )
    EVT_TREE_ITEM_ACTIVATED( wxID_ANY,             LIBRARY_TREE_PANEL::onItemActivated )
wxEND_EVENT_TABLE()


// ═══════════════════════════════════════════════════════════════════════
// Конструктор / Деструктор
// ═══════════════════════════════════════════════════════════════════════

LIBRARY_TREE_PANEL::LIBRARY_TREE_PANEL( wxWindow* aParent, EDA_BASE_FRAME* aFrame )
    : wxPanel( aParent, wxID_ANY ),
      m_parentFrame( aFrame ),
      m_toolbar( nullptr ),
      m_tree( nullptr ),
      m_branchLabel( nullptr ),
      m_statusLabel( nullptr ),
      m_gitIconList( nullptr ),
      m_gitIconsInitialized( false )
{
    m_gitStatusTimer.SetOwner( this );
    m_gitSyncTimer.SetOwner( this );

    Bind( wxEVT_TIMER,
          wxTimerEventHandler( LIBRARY_TREE_PANEL::onGitStatusTimer ),
          this, m_gitStatusTimer.GetId() );
    Bind( wxEVT_TIMER,
          wxTimerEventHandler( LIBRARY_TREE_PANEL::onGitSyncTimer ),
          this, m_gitSyncTimer.GetId() );

    createControls();
}


LIBRARY_TREE_PANEL::~LIBRARY_TREE_PANEL()
{
    m_gitStatusTimer.Stop();
    m_gitSyncTimer.Stop();

    Unbind( wxEVT_TIMER,
            wxTimerEventHandler( LIBRARY_TREE_PANEL::onGitStatusTimer ),
            this, m_gitStatusTimer.GetId() );
    Unbind( wxEVT_TIMER,
            wxTimerEventHandler( LIBRARY_TREE_PANEL::onGitSyncTimer ),
            this, m_gitSyncTimer.GetId() );

    if( m_gitCommon && m_gitCommon->GetRepo() )
    {
        git_repository_free( m_gitCommon->GetRepo() );
        m_gitCommon->SetRepo( nullptr );
    }

    delete m_gitIconList;
}


// ═══════════════════════════════════════════════════════════════════════
// Создание UI
// ═══════════════════════════════════════════════════════════════════════

void LIBRARY_TREE_PANEL::createControls()
{
    wxBoxSizer* mainSizer = new wxBoxSizer( wxVERTICAL );

    // --- Заголовок с именем ветки ---
    wxBoxSizer* headerSizer = new wxBoxSizer( wxHORIZONTAL );

    wxStaticText* titleLabel = new wxStaticText( this, wxID_ANY, _( "Library:" ) );
    titleLabel->SetFont( titleLabel->GetFont().Bold() );
    headerSizer->Add( titleLabel, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 4 );

    m_branchLabel = new wxStaticText( this, wxID_ANY, wxEmptyString );
    m_branchLabel->SetForegroundColour( wxColour( 80, 120, 200 ) );
    headerSizer->Add( m_branchLabel, 1, wxALIGN_CENTER_VERTICAL | wxLEFT, 8 );

    mainSizer->Add( headerSizer, 0, wxEXPAND | wxALL, 2 );

    // --- Тулбар ---
    createToolbar();
    mainSizer->Add( m_toolbar, 0, wxEXPAND );

    // --- Дерево ---
    createTree();
    mainSizer->Add( m_tree, 1, wxEXPAND );

    // --- Строка статуса ---
    m_statusLabel = new wxStaticText( this, wxID_ANY, _( "No library configured" ) );
    m_statusLabel->SetFont( m_statusLabel->GetFont().Smaller() );
    mainSizer->Add( m_statusLabel, 0, wxEXPAND | wxALL, 4 );

    SetSizer( mainSizer );
}


void LIBRARY_TREE_PANEL::createToolbar()
{
    m_toolbar = new wxToolBar( this, wxID_ANY, wxDefaultPosition, wxDefaultSize,
                               wxTB_FLAT | wxTB_HORIZONTAL | wxTB_NODIVIDER );

    // Используем стандартные wx-иконки для тулбара
    // В реальной интеграции — заменить на KiCad bitmaps (KiBitmapBundle)
    m_toolbar->AddTool( ID_LIB_PULL, _( "Pull" ),
                        wxArtProvider::GetBitmap( wxART_GO_DOWN, wxART_TOOLBAR ),
                        _( "Pull changes from remote library repository" ) );

    m_toolbar->AddTool( ID_LIB_COMMIT, _( "Commit" ),
                        wxArtProvider::GetBitmap( wxART_TICK_MARK, wxART_TOOLBAR ),
                        _( "Commit local changes" ) );

    m_toolbar->AddTool( ID_LIB_PUSH, _( "Push" ),
                        wxArtProvider::GetBitmap( wxART_GO_UP, wxART_TOOLBAR ),
                        _( "Push commits to remote library repository" ) );

    m_toolbar->AddSeparator();

    m_toolbar->AddTool( ID_LIB_REFRESH, _( "Refresh" ),
                        wxArtProvider::GetBitmap( wxART_REDO, wxART_TOOLBAR ),
                        _( "Refresh library tree and git status" ) );

    m_toolbar->AddTool( ID_LIB_SETTINGS, _( "Settings" ),
                        wxArtProvider::GetBitmap( wxART_HELP_SETTINGS, wxART_TOOLBAR ),
                        _( "Configure library repository" ) );

    m_toolbar->Realize();
}


void LIBRARY_TREE_PANEL::createTree()
{
    long style = wxTR_DEFAULT_STYLE | wxTR_HAS_BUTTONS | wxTR_LINES_AT_ROOT
                 | wxTR_EDIT_LABELS | wxTR_HIDE_ROOT | wxTR_SINGLE;

    m_tree = new wxTreeCtrl( this, wxID_ANY, wxDefaultPosition, wxDefaultSize, style );

    // Создаём иконки git-статусов (16x16)
    m_gitIconList = new wxImageList( 16, 16, true );

    // Заполним пустыми цветными прямоугольниками
    // В реальной интеграции — использовать KiCad bitmaps
    auto makeIcon = []( const wxColour& colour ) -> wxBitmap
    {
        wxBitmap bmp( 16, 16 );
        wxMemoryDC dc( bmp );
        dc.SetBackground( wxBrush( colour ) );
        dc.Clear();
        dc.SelectObject( wxNullBitmap );
        return bmp;
    };

    m_gitIconList->Add( makeIcon( wxColour( 180, 180, 180 ) ) );  // UNTRACKED — серый
    m_gitIconList->Add( makeIcon( wxColour(  60, 180,  60 ) ) );  // CURRENT   — зелёный
    m_gitIconList->Add( makeIcon( wxColour( 220, 160,  40 ) ) );  // MODIFIED  — жёлтый
    m_gitIconList->Add( makeIcon( wxColour(  60, 120, 220 ) ) );  // ADDED     — синий
    m_gitIconList->Add( makeIcon( wxColour( 220,  60,  60 ) ) );  // DELETED   — красный
    m_gitIconList->Add( makeIcon( wxColour( 180,  80, 220 ) ) );  // BEHIND    — фиолетовый
    m_gitIconList->Add( makeIcon( wxColour(  40, 200, 200 ) ) );  // AHEAD     — бирюзовый
    m_gitIconList->Add( makeIcon( wxColour( 220,  80,  80 ) ) );  // CONFLICT  — яркий красный

    m_tree->SetStateImageList( m_gitIconList );
}


// ═══════════════════════════════════════════════════════════════════════
// Установка пути и инициализация
// ═══════════════════════════════════════════════════════════════════════

void LIBRARY_TREE_PANEL::SetLibraryPath( const wxString& aPath )
{
    if( aPath == m_libraryPath )
        return;

    m_libraryPath = aPath;
    initGitRepo();
    ReCreateTree();
}


void LIBRARY_TREE_PANEL::initGitRepo()
{
    m_gitStatusTimer.Stop();
    m_gitSyncTimer.Stop();

    if( m_gitCommon && m_gitCommon->GetRepo() )
    {
        git_repository_free( m_gitCommon->GetRepo() );
    }

    m_gitCommon.reset();
    m_statusCache.clear();

    if( m_libraryPath.IsEmpty() )
        return;

    git_repository* repo = nullptr;
    int error = git_repository_open( &repo, m_libraryPath.mb_str() );

    if( error != GIT_OK )
    {
        wxLogTrace( traceLibGit, "No git repo at %s: %s",
                    m_libraryPath, KIGIT_COMMON::GetLastGitError() );
        m_statusLabel->SetLabel( _( "No git repository in library path" ) );
        return;
    }

    m_gitCommon = std::make_unique<KIGIT_COMMON>( repo );
    m_gitCommon->UpdateCurrentBranchInfo();

    updateBranchLabel();

    m_statusLabel->SetLabel(
        wxString::Format( _( "Repository: %s" ), m_libraryPath ) );

    // Запускаем таймеры обновления
    m_gitStatusTimer.Start( 500, wxTIMER_ONE_SHOT );
    m_gitSyncTimer.Start( 60000, wxTIMER_ONE_SHOT );  // fetch каждые 60 сек

    wxLogTrace( traceLibGit, "Initialized git repo for library: %s", m_libraryPath );
}


// ═══════════════════════════════════════════════════════════════════════
// Дерево файлов
// ═══════════════════════════════════════════════════════════════════════

void LIBRARY_TREE_PANEL::ReCreateTree()
{
    m_tree->DeleteAllItems();
    m_treeCache.clear();

    if( m_libraryPath.IsEmpty() )
        return;

    wxFileName fn( m_libraryPath );
    wxString rootName = fn.GetFullName();

    if( rootName.IsEmpty() )
        rootName = fn.GetDirs().Last();

    // Добавляем имя ветки к корню
    wxString branchName = GetCurrentBranchName();

    if( !branchName.IsEmpty() )
        rootName += wxString::Format( " [%s]", branchName );

    m_root = m_tree->AddRoot( rootName );

    if( wxDirExists( m_libraryPath ) )
    {
        populateTree( m_libraryPath, m_root );
    }
    else
    {
        m_tree->AppendItem( m_root, _( "Library path not found" ) );
    }

    m_tree->Expand( m_root );
    m_tree->SortChildren( m_root );

    // Запускаем обновление git-статусов
    if( HasGitRepo() )
        m_gitStatusTimer.Start( 500, wxTIMER_ONE_SHOT );
}


void LIBRARY_TREE_PANEL::populateTree( const wxString& aDir, wxTreeItemId aParent )
{
    wxDir dir( aDir );

    if( !dir.IsOpened() )
        return;

    wxString filename;
    bool haveFile;

    // Сначала - подпапки
    haveFile = dir.GetFirst( &filename, wxEmptyString, wxDIR_DIRS );

    while( haveFile )
    {
        // Пропускаем скрытые папки и .git
        if( !filename.StartsWith( "." ) )
        {
            wxString fullPath = aDir + wxFileName::GetPathSeparator() + filename;
            wxTreeItemId child = m_tree->AppendItem( aParent, filename );

            // Рекурсивно заполняем подпапки
            populateTree( fullPath, child );

            // Кэшируем для git-статусов
            m_treeCache[fullPath] = child;
        }

        haveFile = dir.GetNext( &filename );
    }

    // Затем - файлы
    haveFile = dir.GetFirst( &filename, wxEmptyString, wxDIR_FILES );

    while( haveFile )
    {
        if( shouldShowFile( filename ) )
        {
            wxString fullPath = aDir + wxFileName::GetPathSeparator() + filename;
            wxTreeItemId child = m_tree->AppendItem( aParent, filename );

            m_treeCache[fullPath] = child;
        }

        haveFile = dir.GetNext( &filename );
    }
}


bool LIBRARY_TREE_PANEL::shouldShowFile( const wxString& aFilename ) const
{
    // Показываем файлы KiCad библиотек
    static const wxString extensions[] = {
        ".kicad_sym",       // Символы
        ".kicad_mod",       // Footprints
        ".kicad_dbl",       // Database library
        ".lib",             // Legacy symbols
        ".dcm",             // Legacy descriptions
        ".pretty",          // Footprint library folder
        ".3dshapes",        // 3D models
        ".step", ".wrl",    // 3D model files
        ".SchLib",          // Altium symbol library
        ".PcbLib",          // Altium footprint library
    };

    wxString lower = aFilename.Lower();

    for( const auto& ext : extensions )
    {
        if( lower.EndsWith( ext.Lower() ) )
            return true;
    }

    // Также показываем README, .gitignore и т.д.
    if( lower == "readme.md" || lower == ".gitignore" || lower == "license" )
        return true;

    return false;
}


// ═══════════════════════════════════════════════════════════════════════
// Git операции
// ═══════════════════════════════════════════════════════════════════════

wxString LIBRARY_TREE_PANEL::GetCurrentBranchName() const
{
    if( !m_gitCommon || !m_gitCommon->GetRepo() )
        return wxEmptyString;

    return m_gitCommon->GetCurrentBranchName();
}


void LIBRARY_TREE_PANEL::updateBranchLabel()
{
    wxString branch = GetCurrentBranchName();

    if( branch.IsEmpty() )
        m_branchLabel->SetLabel( wxEmptyString );
    else
        m_branchLabel->SetLabel( wxString::Format( "[%s]", branch ) );
}


void LIBRARY_TREE_PANEL::doFetch()
{
    if( !HasGitRepo() )
        return;

    std::unique_lock<std::mutex> lock( m_statusMutex, std::try_to_lock );

    if( !lock.owns_lock() )
        return;

    git_remote* remote = nullptr;

    if( git_remote_lookup( &remote, m_gitCommon->GetRepo(), "origin" ) != GIT_OK )
    {
        wxLogTrace( traceLibGit, "Library fetch: no remote 'origin'" );
        return;
    }

    KIGIT::GitRemotePtr remotePtr( remote );

    git_remote_callbacks callbacks;
    git_remote_init_callbacks( &callbacks, GIT_REMOTE_CALLBACKS_VERSION );
    callbacks.credentials = credentials_cb;
    callbacks.payload = new KIGIT_REPO_MIXIN( m_gitCommon.get() );

    git_fetch_options fetchOpts;
    git_fetch_init_options( &fetchOpts, GIT_FETCH_OPTIONS_VERSION );
    fetchOpts.callbacks = callbacks;

    if( git_remote_fetch( remote, nullptr, &fetchOpts, "library auto-fetch" ) != GIT_OK )
    {
        wxLogTrace( traceLibGit, "Library fetch failed: %s",
                    KIGIT_COMMON::GetLastGitError() );
    }
    else
    {
        wxLogTrace( traceLibGit, "Library fetch OK" );
    }

    delete reinterpret_cast<KIGIT_REPO_MIXIN*>( callbacks.payload );
}


void LIBRARY_TREE_PANEL::doPull()
{
    if( !HasGitRepo() )
        return;

    GIT_PULL_HANDLER handler( m_gitCommon.get() );

    handler.SetProgressReporter(
        std::make_unique<WX_PROGRESS_REPORTER>( this, _( "Pulling library..." ), 1 ) );

    if( handler.PerformPull() < PullResult::Success )
    {
        wxString err = handler.GetErrorString();
        wxMessageBox( wxString::Format( _( "Failed to pull library:\n%s" ), err ),
                      _( "Library Git Error" ), wxICON_ERROR | wxOK, this );
    }
    else
    {
        ReCreateTree();
        m_statusLabel->SetLabel( _( "Pull completed successfully" ) );
    }
}


void LIBRARY_TREE_PANEL::doPush()
{
    if( !HasGitRepo() )
        return;

    if( !m_gitCommon->HasLocalCommits() )
    {
        m_statusLabel->SetLabel( _( "Nothing to push — no local commits ahead of remote" ) );
        return;
    }

    GIT_PUSH_HANDLER handler( m_gitCommon.get() );

    handler.SetProgressReporter(
        std::make_unique<WX_PROGRESS_REPORTER>( this, _( "Pushing library..." ), 1 ) );

    if( handler.PerformPush() != PushResult::Success )
    {
        wxString err = handler.GetErrorString();
        wxMessageBox( wxString::Format( _( "Failed to push library:\n%s" ), err ),
                      _( "Library Git Error" ), wxICON_ERROR | wxOK, this );
    }
    else
    {
        m_statusLabel->SetLabel( _( "Push completed successfully" ) );
    }

    updateGitStatusIcons();
}


void LIBRARY_TREE_PANEL::doCommit()
{
    if( !HasGitRepo() )
        return;

    // Используем встроенный KiCad-диалог коммита
    // DIALOG_GIT_COMMIT принимает repo и показывает список изменённых файлов
    DIALOG_GIT_COMMIT dlg( this, m_gitCommon->GetRepo(), m_gitCommon.get(),
                           m_libraryPath );

    if( dlg.ShowModal() == wxID_OK )
    {
        m_statusLabel->SetLabel( _( "Changes committed" ) );
        updateGitStatusIcons();
        updateBranchLabel();
    }
}


void LIBRARY_TREE_PANEL::updateGitStatusIcons()
{
    if( !HasGitRepo() )
        return;

    std::unique_lock<std::mutex> lock( m_statusMutex, std::try_to_lock );

    if( !lock.owns_lock() )
    {
        m_gitStatusTimer.Start( 500, wxTIMER_ONE_SHOT );
        return;
    }

    git_repository* repo = m_gitCommon->GetRepo();
    wxString repoWorkDir( git_repository_workdir( repo ) );

    git_status_options statusOpts;
    git_status_init_options( &statusOpts, GIT_STATUS_OPTIONS_VERSION );
    statusOpts.show = GIT_STATUS_SHOW_INDEX_AND_WORKDIR;
    statusOpts.flags = GIT_STATUS_OPT_INCLUDE_UNTRACKED | GIT_STATUS_OPT_INCLUDE_UNMODIFIED
                       | GIT_STATUS_OPT_RECURSE_UNTRACKED_DIRS;

    git_status_list* statusList = nullptr;

    if( git_status_list_new( &statusList, repo, &statusOpts ) != GIT_OK )
    {
        wxLogTrace( traceLibGit, "Failed to get status: %s",
                    KIGIT_COMMON::GetLastGitError() );
        return;
    }

    // Обновляем кэш статусов
    m_statusCache.clear();

    size_t entryCount = git_status_list_entrycount( statusList );

    for( size_t i = 0; i < entryCount; i++ )
    {
        const git_status_entry* entry = git_status_byindex( statusList, i );

        if( !entry )
            continue;

        const char* path = entry->head_to_index ? entry->head_to_index->old_file.path
                         : entry->index_to_workdir ? entry->index_to_workdir->old_file.path
                         : nullptr;

        if( !path )
            continue;

        wxString absPath = repoWorkDir + path;
        LIB_GIT_STATUS status = LIB_GIT_STATUS::CURRENT;

        unsigned int flags = entry->status;

        if( flags & ( GIT_STATUS_WT_MODIFIED | GIT_STATUS_INDEX_MODIFIED ) )
            status = LIB_GIT_STATUS::MODIFIED;
        else if( flags & ( GIT_STATUS_WT_NEW | GIT_STATUS_INDEX_NEW ) )
            status = LIB_GIT_STATUS::ADDED;
        else if( flags & ( GIT_STATUS_WT_DELETED | GIT_STATUS_INDEX_DELETED ) )
            status = LIB_GIT_STATUS::DELETED;
        else if( flags & GIT_STATUS_CONFLICTED )
            status = LIB_GIT_STATUS::CONFLICTED;
        else if( flags == GIT_STATUS_CURRENT )
            status = LIB_GIT_STATUS::CURRENT;
        else
            status = LIB_GIT_STATUS::UNTRACKED;

        m_statusCache[absPath] = status;
    }

    git_status_list_free( statusList );

    // Применяем иконки к дереву
    for( auto& [path, treeId] : m_treeCache )
    {
        auto it = m_statusCache.find( path );

        if( it != m_statusCache.end() )
            m_tree->SetItemState( treeId, static_cast<int>( it->second ) );
        else
            m_tree->SetItemState( treeId, static_cast<int>( LIB_GIT_STATUS::CURRENT ) );
    }

    // Обновляем счётчики в строке статуса
    int modified = 0, added = 0, deleted = 0;

    for( auto& [path, status] : m_statusCache )
    {
        switch( status )
        {
        case LIB_GIT_STATUS::MODIFIED: modified++; break;
        case LIB_GIT_STATUS::ADDED:    added++;    break;
        case LIB_GIT_STATUS::DELETED:  deleted++;  break;
        default: break;
        }
    }

    wxString statusText;

    if( modified + added + deleted == 0 )
    {
        statusText = _( "Clean — no changes" );
    }
    else
    {
        statusText = wxString::Format( _( "Changes: %d modified, %d added, %d deleted" ),
                                       modified, added, deleted );
    }

    m_statusLabel->SetLabel( statusText );
}


// ═══════════════════════════════════════════════════════════════════════
// Обработчики кнопок тулбара
// ═══════════════════════════════════════════════════════════════════════

void LIBRARY_TREE_PANEL::onPull( wxCommandEvent& aEvent )
{
    doPull();
}


void LIBRARY_TREE_PANEL::onPush( wxCommandEvent& aEvent )
{
    doPush();
}


void LIBRARY_TREE_PANEL::onCommit( wxCommandEvent& aEvent )
{
    doCommit();
}


void LIBRARY_TREE_PANEL::onRefresh( wxCommandEvent& aEvent )
{
    if( HasGitRepo() )
    {
        doFetch();
        m_gitCommon->UpdateCurrentBranchInfo();
    }

    ReCreateTree();
}


void LIBRARY_TREE_PANEL::onSettings( wxCommandEvent& aEvent )
{
    if( m_libraryPath.IsEmpty() )
    {
        wxDirDialog dlg( this, _( "Select library directory" ), wxGetHomeDir() );

        if( dlg.ShowModal() == wxID_OK )
            SetLibraryPath( dlg.GetPath() );

        return;
    }

    // Показываем стандартный KiCad-диалог настройки git-репозитория
    DIALOG_GIT_REPOSITORY repoDlg( wxGetTopLevelParent( this ), nullptr );

    repoDlg.SetTitle( _( "Library Repository Settings" ) );

    if( repoDlg.ShowModal() == wxID_OK )
    {
        // Обновляем настройки подключения
        if( m_gitCommon )
        {
            m_gitCommon->SetPassword( repoDlg.GetPassword() );
            m_gitCommon->SetUsername( repoDlg.GetUsername() );
            m_gitCommon->SetSSHKey( repoDlg.GetRepoSSHPath() );
            m_gitCommon->UpdateCurrentBranchInfo();
        }

        updateBranchLabel();
    }
}


// ═══════════════════════════════════════════════════════════════════════
// Контекстное меню
// ═══════════════════════════════════════════════════════════════════════

void LIBRARY_TREE_PANEL::onContextMenu( wxTreeEvent& aEvent )
{
    wxMenu menu;

    bool hasRepo = HasGitRepo();
    bool hasChanges = false;

    if( hasRepo )
    {
        for( auto& [path, status] : m_statusCache )
        {
            if( status != LIB_GIT_STATUS::CURRENT )
            {
                hasChanges = true;
                break;
            }
        }
    }

    menu.Append( ID_LIB_REFRESH, _( "Refresh" ) );
    menu.AppendSeparator();

    if( hasRepo )
    {
        wxMenuItem* pullItem = menu.Append( ID_LIB_PULL, _( "Pull" ) );
        pullItem->Enable( m_gitCommon->HasPushAndPullRemote() );

        wxMenuItem* commitItem = menu.Append( ID_LIB_COMMIT, _( "Commit..." ) );
        commitItem->Enable( hasChanges );

        wxMenuItem* pushItem = menu.Append( ID_LIB_PUSH, _( "Push" ) );
        pushItem->Enable( m_gitCommon->HasLocalCommits() );

        menu.AppendSeparator();
    }

    menu.Append( ID_LIB_SETTINGS, _( "Library Settings..." ) );

    PopupMenu( &menu );
}


void LIBRARY_TREE_PANEL::onItemActivated( wxTreeEvent& aEvent )
{
    // При двойном клике можно открыть файл во внешнем редакторе
    // или перейти к нему в KiCad
    wxTreeItemId item = aEvent.GetItem();

    for( auto& [path, treeId] : m_treeCache )
    {
        if( treeId == item )
        {
            wxLogTrace( traceLibGit, "Activated: %s", path );
            // TODO: открыть файл в соответствующем редакторе KiCad
            break;
        }
    }
}


// ═══════════════════════════════════════════════════════════════════════
// Таймеры
// ═══════════════════════════════════════════════════════════════════════

void LIBRARY_TREE_PANEL::onGitStatusTimer( wxTimerEvent& aEvent )
{
    if( !HasGitRepo() )
        return;

    updateGitStatusIcons();
    updateBranchLabel();
}


void LIBRARY_TREE_PANEL::onGitSyncTimer( wxTimerEvent& aEvent )
{
    if( !HasGitRepo() )
        return;

    // Фоновый fetch
    doFetch();
    updateGitStatusIcons();

    // Перезапускаем таймер синхронизации
    m_gitSyncTimer.Start( 60000, wxTIMER_ONE_SHOT );
}
