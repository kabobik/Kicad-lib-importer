# Исследование встроенной Git-интеграции KiCad 9.x

**Дата:** 2026-02-13  
**Исходники:** KiCad 9.0.7 (`/home/anton/VsCode/kicad-research/kicad/`)

---

## 1. Настройки — где хранятся, какие параметры

### 1.1 Глобальные настройки (Preferences → Git)

**Файл:** `~/.config/kicad/9.0/kicad_common.json`  
**Формат:** JSON  
**Секция:** `"git"`

```json
{
  "git": {
    "enableGit": true,
    "updatInterval": 5,
    "useDefaultAuthor": true,
    "authorName": "",
    "authorEmail": "",
    "repositories": []
  }
}
```

**Поля:**

| Поле | Тип | По умолчанию | Описание |
|------|-----|-------------|----------|
| `enableGit` | bool | `true` | Включить/выключить Git-интеграцию |
| `updatInterval` | int | `5` | Интервал обновления статуса (секунды) |
| `useDefaultAuthor` | bool | `true` | Использовать автора из глобального git config |
| `authorName` | string | `""` | Имя автора (если useDefaultAuthor=false) |
| `authorEmail` | string | `""` | Email автора (если useDefaultAuthor=false) |
| `repositories` | array | `[]` | Список репозиториев |

**Структура элемента `repositories`:**

```json
{
  "name": "my-lib",
  "path": "/path/to/repo",
  "authType": "ssh",
  "username": "git",
  "ssh_path": "/home/user/.ssh/id_rsa",
  "active": true
}
```

> **Источник:** `common/settings/common_settings.cpp:370-428`, `include/settings/common_settings.h:155-178`

### 1.2 Настройки проекта (per-project)

**Файл:** `<project>.kicad_prl` (project local settings)  
**Секция:** `"git"`

```json
{
  "git": {
    "repo_username": "",
    "repo_type": "",
    "ssh_key": ""
  }
}
```

| Поле | Описание |
|------|----------|
| `git.repo_username` | Имя пользователя для remote |
| `git.repo_type` | Тип подключения: `"ssh"`, `"https"`, `"local"` |
| `git.ssh_key` | Путь к SSH-ключу |

> **Источник:** `common/project/project_local_settings.cpp:204-208`, `include/settings/project_local_settings.h:152-154`

### 1.3 Панель настроек (Preferences → Git)

**Файл:** `common/dialogs/git/panel_git_repos.cpp`

Панель содержит:
- **Чекбокс** `m_enableGit` — включить/выключить Git
- **Спиннер** `m_updateInterval` — интервал обновления статуса
- **Чекбокс** `m_cbDefault` — использовать стандартного автора (из `~/.gitconfig`)
- **Поля** `m_author`, `m_authorEmail` — кастомный автор

> **Важно:** В панели настроек **НЕТ** возможности настроить remote, SSH-ключ или credentials для конкретных репозиториев. Это делается только через диалог при инициализации проекта.

---

## 2. SSH/Auth — аутентификация

### 2.1 Типы подключения

Определяются в `kicad_git_common.h`:

```cpp
enum class GIT_CONN_TYPE {
    GIT_CONN_HTTPS = 0,  // HTTPS с логином/паролем или токеном
    GIT_CONN_SSH,        // SSH с ключом или ssh-agent
    GIT_CONN_LOCAL,      // Локальный репозиторий (без auth)
};
```

Тип определяется автоматически по URL remote:
- `https://` или `http://` → `GIT_CONN_HTTPS`
- `ssh://`, `git@`, `git+ssh://` → `GIT_CONN_SSH`
- Остальное → `GIT_CONN_LOCAL`

> **Источник:** `kicad_git_common.cpp:706-770` (`updateConnectionType()`)

### 2.2 Порядок аутентификации (credentials_cb)

**Файл:** `common/git/kicad_git_common.cpp:948-1010`

```
1. GIT_CREDENTIAL_USERNAME → просто отправляет username
2. HTTPS → HandlePlaintextAuthentication() → username + password
3. SSH → HandleSSHKeyAuthentication():
   3a. Сначала пробует ssh-agent (HandleSSHAgentAuthentication)
   3b. Затем перебирает SSH-ключи по очереди (GetNextPublicKey)
4. Если ничего не подошло → GIT_EAUTH (ошибка аутентификации)
```

### 2.3 SSH-ключи — порядок поиска

**Файл:** `kicad_git_common.cpp:589-660` (`updatePublicKeys()`)

1. Если в `.ssh/config` есть `IdentityFile` для хоста → этот ключ ставится **первым**
2. `~/.ssh/id_rsa`
3. `~/.ssh/id_dsa`
4. `~/.ssh/id_ecdsa`
5. `~/.ssh/id_ed25519`

**ssh-agent поддерживается!** Вызывается `git_credential_ssh_key_from_agent()` **первым** при SSH-соединении.

### 2.4 Хранение паролей

**Linux:** Используется `libsecret` (GNOME Keyring / KDE Wallet)  
**Windows:** Windows Credential Manager  
**macOS:** Keychain  

**Схема хранения (Linux):**
```
service = URL remote (например "https://github.com/user/repo.git")
key = username
secret = password/token
```

Пароль запрашивается через `KIPLATFORM::SECRETS::GetSecret(m_remote, m_username, secret)`.  
Сохраняется через `KIPLATFORM::SECRETS::StoreSecret()` при инициализации проекта.

> **Источник:** `libs/kiplatform/os/unix/secrets.cpp`, `kicad_git_common.cpp:105-117`

### 2.5 Диалог настройки репозитория  

**Файл:** `common/dialogs/git/dialog_git_repository.cpp`

Диалог предоставляет:
- **URL** — адрес remote
- **Connection Type** — HTTPS / SSH / Local (выбирается из `m_ConnType`)
- **Username** — имя пользователя
- **Password** — пароль (для HTTPS) или passphrase SSH-ключа (для SSH)
- **SSH Key** — путь к приватному ключу (file picker, `m_fpSSHKey`)
- **Custom checkbox** — включить ручной ввод auth для SSH
- **Test Connection** — кнопка проверки соединения

При SSH-типе:
- Автоматически ищет стандартные ключи (`id_rsa`, `id_dsa`, `id_ecdsa`)
- Проверяет что файл содержит "PRIVATE KEY"
- Определяет зашифрован ли ключ → включает поле пароля

---

## 3. Remote — как добавить/настроить

### 3.1 Через UI (Version Control → Add Project to Version Control)

1. Правый клик в дереве проекта → **Version Control** → **Add Project to Version Control...**
2. Открывается `DIALOG_GIT_REPOSITORY`
3. Вводится URL, тип подключения, credentials
4. KiCad делает:
   - `git_repository_init()` — инициализация .git
   - `git_remote_create_with_fetchspec()` — создание remote "origin"
   - `handler.PerformFetch()` — первый fetch
   - Сохраняет credentials в секретное хранилище

> **Источник:** `kicad/project_tree_pane.cpp:1631-1757`

### 3.2 Через командную строку (для существующего репо)

Если `.git` уже существует:
```bash
cd /path/to/kicad/project
git remote add origin git@github.com:user/repo.git
git branch -u origin/main main
```

> **Важно:** KiCad ищет remote по имени `"origin"` (хардкод в `git_push_handler.cpp:55`). Другие имена remote **НЕ поддерживаются**.

### 3.3 Нет UI для редактирования remote

В KiCad 9.x **нет диалога для изменения remote** у уже существующего репозитория. Диалог `DIALOG_GIT_REPOSITORY` используется **только** при инициализации нового проекта. Для изменения remote нужно использовать командную строку:

```bash
git remote set-url origin <new-url>
```

---

## 4. Push flow — что происходит при нажатии Push

### Шаг за шагом (файл `common/git/git_push_handler.cpp`)

```
1. Захват мьютекса m_gitActionMutex (try_lock)
   ├── Если занято → возврат PushResult::Error (молча!)

2. git_remote_lookup(&remote, repo, "origin")
   ├── Если нет remote "origin" → "Could not lookup remote"

3. Настройка callbacks:
   ├── credentials_cb → аутентификация
   ├── progress_cb → прогресс
   ├── transfer_progress_cb → прогресс передачи
   └── push_transfer_progress_cb → прогресс push

4. TestedTypes() = 0; ResetNextKey();
   └── Сброс счётчиков аутентификации

5. git_remote_connect(remote, GIT_DIRECTION_PUSH, &callbacks, ...)
   ├── Здесь происходит SSH/HTTPS аутентификация через callbacks
   └── Ошибка → "Could not connect to remote: <error>"

6. git_repository_head(&head, repo)
   └── Получение текущей ветки

7. git_remote_push(remote, &refspecs, &pushOptions)
   ├── refspecs = имя текущей ветки (refs/heads/main)
   └── Ошибка → "Could not push to remote: <error>"

8. git_remote_disconnect(remote)
   └── Закрытие соединения
```

### Вызов из UI (`project_tree_pane.cpp:1790-1813`)

```
1. Проверка: repo != nullptr
2. Создание GIT_PUSH_HANDLER с GitCommon()
3. Установка WX_PROGRESS_REPORTER (диалог прогресса)
4. handler.PerformPush()
5. Если ошибка → DisplayErrorMessage с errorString
6. Перезапуск таймера статуса (500ms)
```

### Условия доступности Push в меню

```cpp
bool vcs_can_fetch = vcs_has_repo && git->HasPushAndPullRemote();
bool vcs_can_push  = vcs_can_fetch && git->HasLocalCommits();
```

Push **доступен** только если:
1. Есть открытый git-репозиторий
2. Есть remote "origin" (`HasPushAndPullRemote()` → `git_remote_lookup(&remote, repo, "origin")`)
3. Есть локальные коммиты, не запушенные в remote (`HasLocalCommits()`)

---

## 5. Возможные причины "не пушит"

### 5.1 Push disabled (серый) в меню

| Причина | Как проверить | Решение |
|---------|-------------|---------|
| Git отключён в настройках | `kicad_common.json` → `git.enableGit` | Preferences → Git → включить |
| Нет remote "origin" | `git remote -v` | `git remote add origin <url>` |
| Нет локальных коммитов | `git log --oneline origin/main..HEAD` | Сначала commit |
| Нет upstream branch | `git branch -vv` | `git branch -u origin/main` |

### 5.2 Push кликабелен, но ошибка

| Причина | Сообщение | Решение |
|---------|-----------|---------|
| Мьютекс занят (другая git-операция) | Ничего (молча Error) | Подождать завершения fetch/pull |
| Remote не найден | "Could not lookup remote" | `git remote add origin <url>` |
| Ошибка аутентификации SSH | "Could not connect to remote: ..." | Проверить ключ, ssh-agent |
| HTTPS без пароля | "Could not connect to remote: ..." | Проверить credentials в keyring |
| Нет прав на push | "Could not push to remote: ..." | Проверить права на сервере |
| Нет HEAD | "Could not get repository head" | Сделать первый коммит |
| Remote отклонил push | "Could not push to remote: ..." | `git pull` сначала |

### 5.3 SSH-специфичные проблемы

- **ssh-agent не запущен:** KiCad пробует ssh-agent ПЕРВЫМ. Если он не запущен — переходит к ключам на диске.
- **Ключ не в стандартном месте:** KiCad ищет только `~/.ssh/id_{rsa,dsa,ecdsa,ed25519}`. Нестандартные пути должны быть в `~/.ssh/config` с `IdentityFile`.
- **Ключ зашифрован, пароль не сохранён:** Пароль берётся из libsecret (GNOME Keyring). Если не сохранён — auth failure.
- **`.pub` файл отсутствует:** libgit2 требует **оба** файла (приватный + `.pub`).

### 5.4 HTTPS-специфичные проблемы

- **Пароль/токен не сохранён в keyring:** Пароль ищется через `KIPLATFORM::SECRETS::GetSecret(remote_url, username)`. Если не найден в GNOME Keyring → пустой пароль → auth failure.
- **GitHub/GitLab требует token вместо пароля:** В поле Password нужно вводить Personal Access Token.

---

## 6. Логирование и отладка

### 6.1 Trace (wxLogTrace)

Весь Git-код использует `wxLogTrace(traceGit, ...)` с trace key:

```
KICAD_GIT
```

**Как включить:**

```bash
# Linux
export KICAD_GIT=1
kicad

# Или через переменную окружения WX trace:
export WXTRACE=KICAD_GIT
kicad
```

### 6.2 Ошибки в UI

- **DisplayErrorMessage** — для критических ошибок push/pull (модальное окно)
- **DisplayInfoMessage** — для информационных сообщений
- **WX_PROGRESS_REPORTER** — диалог прогресса при push/pull

### 6.3 Что логируется

При push:
- Попытки аутентификации (тип, username)
- SSH: какой ключ тестируется
- Результат каждого шага
- Ошибки libgit2

---

## 7. Рекомендации — пошаговая инструкция для настройки Push

### Вариант A: Новый проект через KiCad UI

1. Создайте проект в KiCad
2. Правый клик в дереве → **Version Control** → **Add Project to Version Control...**
3. Введите URL remote (например `git@github.com:user/kicad-lib.git`)
4. Выберите тип подключения (SSH или HTTPS)
5. Для SSH:
   - Убедитесь что ssh-agent запущен, или
   - Укажите путь к приватному ключу
6. Для HTTPS:
   - Введите username
   - Введите password/token
7. Нажмите **Test Connection**
8. Нажмите **OK**

### Вариант B: Существующий Git-репозиторий

1. Убедитесь что `enableGit = true` в Preferences → Git

2. Проверьте remote:
   ```bash
   cd /path/to/project
   git remote -v
   ```
   Если нет — добавьте:
   ```bash
   git remote add origin git@github.com:user/repo.git
   ```

3. Настройте upstream для текущей ветки:
   ```bash
   git branch -u origin/main main
   ```

4. Для SSH — убедитесь что ключ работает:
   ```bash
   ssh -T git@github.com
   ```

5. Для HTTPS — сохраните пароль в системный keyring:
   ```bash
   # GNOME Keyring (Linux)
   secret-tool store --label="KiCad Git" service "https://github.com/user/repo.git" key "username"
   # Введите пароль/токен
   ```

6. **Сохраните credentials в project local settings.**  
   KiCad при инициализации сохраняет `git.repo_username`, `git.repo_type`, `git.ssh_key` в `*.kicad_prl`.  
   Если проект был инициализирован через CLI, эти настройки пусты. Можно добавить вручную в `.kicad_prl`:
   ```json
   {
     "git": {
       "repo_username": "git",
       "repo_type": "ssh",
       "ssh_key": "/home/user/.ssh/id_ed25519"
     }
   }
   ```

7. Сделайте commit через Version Control → Commit
8. Нажмите Version Control → Push

### Вариант C: Диагностика если не работает

1. Запустите KiCad с трассировкой:
   ```bash
   WXTRACE=KICAD_GIT kicad 2>&1 | tee /tmp/kicad_git.log
   ```

2. Попробуйте push — в логе будет видно:
   - Какой callback вызывается
   - Какой тип auth пробуется
   - Какой SSH-ключ тестируется
   - Точная ошибка libgit2

3. Проверьте что `.pub` файл существует рядом с приватным ключом

4. Проверьте что `git_remote_lookup("origin")` найдёт remote:
   ```bash
   git remote -v
   # Должно быть:
   # origin  git@github.com:user/repo.git (fetch)
   # origin  git@github.com:user/repo.git (push)
   ```

---

## 8. Архитектура (ключевые файлы)

| Файл | Назначение |
|------|-----------|
| `common/git/git_push_handler.cpp` | Логика push (115 строк) |
| `common/git/git_pull_handler.cpp` | Логика pull + fetch + merge/rebase (570 строк) |
| `common/git/kicad_git_common.cpp` | Базовый класс: auth, SSH, remote, branch, credentials_cb (1011 строк) |
| `common/git/kicad_git_common.h` | Заголовок: GIT_CONN_TYPE, GIT_STATUS, API |
| `common/dialogs/git/dialog_git_repository.cpp` | Диалог настройки нового репозитория |
| `common/dialogs/git/panel_git_repos.cpp` | Панель Preferences → Git |
| `common/settings/common_settings.cpp` | Сериализация git-настроек в JSON |
| `common/project/project_local_settings.cpp` | Per-project git settings |
| `kicad/project_tree_pane.cpp` | Контекстное меню Version Control, обработчики push/pull |
| `libs/kiplatform/os/unix/secrets.cpp` | Хранение паролей через libsecret |

---

## 9. Известные ограничения KiCad 9.x Git

1. **Remote только "origin"** — имя remote хардкодировано в push/pull handlers
2. **Нет UI для изменения remote** — только при первичной инициализации
3. **Мьютекс блокирует операции** — если fetch работает в фоне, push молча вернёт Error
4. **Нет диалога ввода пароля at runtime** — пароль берётся из keyring или из сохранённых настроек. Если не найден — authentication failure без возможности ввести вручную
5. **SSH passphrase** — если ключ зашифрован, passphrase должен быть в keyring или в ssh-agent
6. **Нет поддержки GPG-подписи коммитов**
7. **updateInterval** (sic — опечатка в коде: `updatInterval`) — интервал фоновой проверки статуса
