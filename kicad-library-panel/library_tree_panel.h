/*
 * Library Tree Panel for KiCad Project Manager
 *
 * Отдельная wxAUI-панель для отображения и управления Git-репозиторием
 * глобальной библиотеки компонентов. Работает независимо от PROJECT_TREE_PANE.
 *
 * Copyright 2026 Anton Tsulin
 * License: GPL-3.0+
 */

#ifndef LIBRARY_TREE_PANEL_H
#define LIBRARY_TREE_PANEL_H

#include <wx/panel.h>
#include <wx/treectrl.h>
#include <wx/timer.h>
#include <wx/toolbar.h>
#include <wx/stattext.h>
#include <wx/filename.h>
#include <wx/dir.h>
#include <wx/textfile.h>
#include <wx/log.h>

#include <git2.h>

#include <git/kicad_git_common.h>
#include <git/kicad_git_memory.h>
#include <git/git_push_handler.h>
#include <git/git_pull_handler.h>
#include <git/git_commit_handler.h>

#include <memory>
#include <mutex>
#include <map>

class EDA_BASE_FRAME;

/**
 * Маркеры состояния файлов в дереве библиотеки.
 * Совпадают с маркерами PROJECT_TREE для единообразия.
 */
enum class LIB_GIT_STATUS
{
    UNTRACKED = 0,
    CURRENT,
    MODIFIED,
    ADDED,
    DELETED,
    BEHIND,
    AHEAD,
    CONFLICTED,
    STATUS_COUNT
};


/**
 * @class LIBRARY_TREE_PANEL
 *
 * Панель дерева библиотеки с Git-интеграцией.
 * Встраивается в KiCad Project Manager (KICAD_MANAGER_FRAME) через wxAUI
 * как отдельная панель ниже или рядом с деревом проекта.
 *
 * Поддерживает:
 * - Отображение файлов библиотечного git-репозитория
 * - Маркеры git-статуса для каждого файла
 * - Push / Pull / Commit через контекстное меню и тулбар
 * - Автоматический fetch по таймеру
 * - Отображение текущей ветки
 */
class LIBRARY_TREE_PANEL : public wxPanel
{
public:
    LIBRARY_TREE_PANEL( wxWindow* aParent, EDA_BASE_FRAME* aFrame );
    ~LIBRARY_TREE_PANEL();

    /**
     * Задать путь к репозиторию библиотеки.
     * Вызывает полное перестроение дерева.
     */
    void SetLibraryPath( const wxString& aPath );

    /** Получить текущий путь */
    wxString GetLibraryPath() const { return m_libraryPath; }

    /** Есть ли привязанный git-репозиторий */
    bool HasGitRepo() const { return m_gitCommon && m_gitCommon->GetRepo() != nullptr; }

    /** Получить git-объект */
    KIGIT_COMMON* GitCommon() const { return m_gitCommon.get(); }

    /** Обновить дерево файлов */
    void ReCreateTree();

    /** Имя текущей ветки */
    wxString GetCurrentBranchName() const;

private:
    // ─── UI ──────────────────────────────────────────────────────────
    void createControls();
    void createToolbar();
    void createTree();
    void createStatusBar();

    // ─── Дерево файлов ──────────────────────────────────────────────
    void populateTree( const wxString& aDir, wxTreeItemId aParent );
    bool shouldShowFile( const wxString& aFilename ) const;

    // ─── Git операции ───────────────────────────────────────────────
    void initGitRepo();
    void doFetch();
    void doPull();
    void doPush();
    void doCommit();
    void updateGitStatusIcons();
    void updateBranchLabel();

    // ─── Контекстное меню ───────────────────────────────────────────
    void onContextMenu( wxTreeEvent& aEvent );
    void onItemActivated( wxTreeEvent& aEvent );

    // ─── Обработчики кнопок тулбара ─────────────────────────────────
    void onPull( wxCommandEvent& aEvent );
    void onPush( wxCommandEvent& aEvent );
    void onCommit( wxCommandEvent& aEvent );
    void onRefresh( wxCommandEvent& aEvent );
    void onSettings( wxCommandEvent& aEvent );

    // ─── Таймеры ────────────────────────────────────────────────────
    void onGitStatusTimer( wxTimerEvent& aEvent );
    void onGitSyncTimer( wxTimerEvent& aEvent );

    // ─── Данные ─────────────────────────────────────────────────────
    EDA_BASE_FRAME*                m_parentFrame;
    wxString                       m_libraryPath;

    // UI элементы
    wxToolBar*                     m_toolbar;
    wxTreeCtrl*                    m_tree;
    wxStaticText*                  m_branchLabel;
    wxStaticText*                  m_statusLabel;
    wxTreeItemId                   m_root;

    // Git
    std::unique_ptr<KIGIT_COMMON>  m_gitCommon;
    wxImageList*                   m_gitIconList;
    bool                           m_gitIconsInitialized;

    // Кэш статусов
    std::map<wxString, LIB_GIT_STATUS> m_statusCache;
    std::map<wxString, wxTreeItemId>   m_treeCache;
    std::mutex                         m_statusMutex;

    // Таймеры
    wxTimer                        m_gitStatusTimer;
    wxTimer                        m_gitSyncTimer;

    // ID команд тулбара
    enum
    {
        ID_LIB_PULL = wxID_HIGHEST + 2000,
        ID_LIB_PUSH,
        ID_LIB_COMMIT,
        ID_LIB_REFRESH,
        ID_LIB_SETTINGS,
        ID_LIB_FETCH,
    };

    wxDECLARE_EVENT_TABLE();
};


#endif // LIBRARY_TREE_PANEL_H
