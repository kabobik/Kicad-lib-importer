# SUBTASK 4: QUICK START FOR DEVELOPERS

**Быстрый старт для разработчиков**  
**Время прочтения:** 5-10 минут  
**Категория:** Практический гайд

---

## 🚀 5-минутная ориентация

### Что нужно сделать?

**Создать диалоговое окно для выбора anchor point при копировании в KiCad.**

```
┌─────────────────────────────────┐
│ Anchor Point Selection          │
├─────────────────────────────────┤
│ ◉ Default                       │
│ ◯ Center of bounding box        │
│ ◯ First selected item           │
│ ◯ Top-left corner               │
│ ◯ Manual coordinates: X___ Y___ │
│         [OK]       [Cancel]     │
└─────────────────────────────────┘
```

### Почему это нужно?

Пользователи иногда хотят выбрать другую точку привязки при копировании, а не используемую по умолчанию.

### Как это работает?

```
1. Пользователь нажимает: Edit → Copy with Anchor Point Options
2. Показывается диалог с 5 вариантами
3. Пользователь выбирает режим
4. Нажимает OK
5. KiCad копирует с выбранным anchor point
6. Пользователь вставляет (Ctrl+V) в новое место
```

---

## 📁 ЧТО СОЗДАВАТЬ

### 3 новых файла:

```
pcbnew/dialogs/
  ├─ dialog_anchor_point_selection.h         (новый)
  ├─ dialog_anchor_point_selection.cpp       (новый)
  └─ dialog_anchor_point_selection_base.cpp  (wxFormBuilder)
```

### 5 файлов для модификации:

```
pcbnew/tools/
  ├─ edit_tool.h                             (+ 2 метода)
  └─ edit_tool.cpp                           (+ реализация)

pcbnew/tools/
  ├─ pcb_actions.h                           (+ действие)
  └─ pcb_actions.cpp                         (+ регистрация)

pcbnew/menus/
  └─ edit_menu.cpp                           (+ меню пункт)
```

---

## 💻 КОД ДЛЯ КОПИРОВАНИЯ

### Шаг 1: Создать dialog_anchor_point_selection.h

```cpp
#ifndef DIALOG_ANCHOR_POINT_SELECTION_H
#define DIALOG_ANCHOR_POINT_SELECTION_H

#include <wx/wx.h>
#include "geometry/vector2d.h"

class PCB_SELECTION;
class BOX2I;

class DIALOG_ANCHOR_POINT_SELECTION : public wxDialog
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

    ANCHOR_MODE GetSelectedMode() const;
    VECTOR2I GetCustomPoint() const;

protected:
    void onRadioButtonSelected( wxCommandEvent& aEvent ) override;
    void onManualCoordsChanged( wxCommandEvent& aEvent ) override;

private:
    const PCB_SELECTION& m_selection;
    BOX2I m_bbox;
    
    wxRadioButton* m_rbDefault;
    wxRadioButton* m_rbCenter;
    wxRadioButton* m_rbFirstItem;
    wxRadioButton* m_rbTopLeft;
    wxRadioButton* m_rbCustom;
    wxRadioButton* m_rbManual;
    wxTextCtrl* m_xInput;
    wxTextCtrl* m_yInput;
    wxButton* m_btnInteractive;
    
    void updateControlStates();
    bool validateCoordinates();
    void displaySelectionInfo();
};

#endif
```

**⏱️ Время:** 10 минут копирования + 10 минут реализации

---

### Шаг 2: Реализация in dialog_anchor_point_selection.cpp

**Скопируйте полный код из [SUBTASK_4_CODE_EXAMPLES.md](SUBTASK_4_CODE_EXAMPLES.md) Part 1!**

```cpp
// Используйте готовый код из документа
// ~400 строк, готовое к использованию
```

**⏱️ Время:** 5 минут копирования

---

### Шаг 3: Добавить методы в edit_tool.h

```cpp
// В конец класса EDIT_TOOL, в приватное сечение:

private:
    int copyWithAnchorOptions( const TOOL_EVENT& aEvent );
    void ApplyAnchorMode( int aMode, const VECTOR2I& aCustomPoint,
                          PCB_SELECTION& aSelection );
```

**⏱️ Время:** 2 минуты

---

### Шаг 4: Реализация в edit_tool.cpp

**Скопируйте полный код из [SUBTASK_4_CODE_EXAMPLES.md](SUBTASK_4_CODE_EXAMPLES.md) Part 2!**

```cpp
#include "dialogs/dialog_anchor_point_selection.h"

int EDIT_TOOL::copyWithAnchorOptions( const TOOL_EVENT& aEvent )
{
    // Полный код ~100 строк готов в документе
}

void EDIT_TOOL::ApplyAnchorMode( ... )
{
    // Полный код ~80 строк готов в документе
}

// В SetTools():
m_toolMgr->RegisterAction( PCB_ACTIONS::copyWithAnchorOptions,
    std::bind( &EDIT_TOOL::copyWithAnchorOptions, this, _1 ) );
```

**⏱️ Время:** 10 минут копирования

---

### Шаг 5: Добавить действие в pcb_actions.h

```cpp
// В namespace PCB_ACTIONS:

extern const TOOL_ACTION copyWithAnchorOptions;
```

**⏱️ Время:** 1 минута

---

### Шаг 6: Регистрировать в pcb_actions.cpp

```cpp
TOOL_ACTION PCB_ACTIONS::copyWithAnchorOptions(
    "pcbnew.Edit.copyWithAnchorOptions",
    AS_GLOBAL,
    _( "Copy with Anchor Point Options..." ),
    _( "Copy selection with interactive anchor point selection dialog" ),
    BITMAPS::copy_16 );
```

**⏱️ Время:** 5 минут копирования

---

### Шаг 7: Добавить в меню (edit_menu.cpp)

```cpp
// В функции popula menu:

AddItem( PCB_ACTIONS::copy );
AddItem( PCB_ACTIONS::copyWithAnchorOptions );  // <- NEW
AddItem( PCB_ACTIONS::paste );
```

**⏱️ Время:** 1 минута

---

## 🧪 ТЕСТИРОВАНИЕ (Чек-лист)

### Тест 1: Диалог открывается
```
□ Выбрать элемент на плате
□ Edit → Copy with Anchor Point Options
□ ✓ Диалог должен появиться
```

### Тест 2: Режимы работают
```
□ Выбрать Default → OK
  ✓ Копирует без проблем

□ Выбрать Center → OK
  ✓ Копирует с центром bbox

□ Выбрать Manual X,Y → ввести 100, 200 → OK
  ✓ Копирует с координатами (100, 200)
```

### Тест 3: Вставка работает
```
□ После копирования нажать Ctrl+V
□ Выбрать позицию на плате
□ ✓ Элемент вставляется правильно
```

### Тест 4: Обратная совместимость
```
□ Ctrl+C по-прежнему работает (без диалога)
□ Ctrl+V по-прежнему работает
□ ✓ Старые буферы обмена читаются
```

---

## 🐛 ЧАСТЫЕ ОШИБКИ И РЕШЕНИЯ

### Ошибка 1: "Cannot find dialog_anchor_point_selection.h"
**Решение:** Проверьте путь `#include "dialogs/dialog_anchor_point_selection.h"`

### Ошибка 2: "GetSelectedMode undefined"
**Решение:** Убедитесь, что методы объявлены в .h и реализованы в .cpp

### Ошибка 3: "Диалог не открывается при нажатии меню"
**Решение:** Проверьте регистрацию в SetTools() и меню binding

### Ошибка 4: "Координаты не валидируются"
**Решение:** ToLong() результат должен быть проверен на true

### Ошибка 5: "Компиляция падает"
**Решение:** Добавьте все необходимые #include в .cpp

---

## 🗂️ ФАЙЛЫ В ОДНОМ МЕСТЕ

**Все коды готовы к копированию:** [SUBTASK_4_CODE_EXAMPLES.md](SUBTASK_4_CODE_EXAMPLES.md)

```
ЧАСТЬ 1: Полный код диалога (400+ строк, copy-paste ready)
ЧАСТЬ 2: Методы EDIT_TOOL (200+ строк, copy-paste ready)
ЧАСТЬ 3: Регистрация PCB_ACTIONS (30 строк, copy-paste ready)
ЧАСТЬ 4: Интеграция меню (5 линий, copy-paste ready)
```

**Просто копируйте код, адаптируйте пути и готово!**

---

## ⏱️ ТАЙМЛАЙН

```
День 1:   Диалог (файлы + реализация) = 4 часа
День 2:   Интеграция в EDIT_TOOL = 2 часа
День 2:   Меню и PCB_ACTIONS = 1 час
День 3:   Тестирование = 6 часов
День 4:   Полирование + code review = 2 часа
          ―――――――――――――
ВСЕГО:    ~15 часов разработки
```

**На полный день работы: 2-3 дня**

---

## 📚 ДОПОЛНИТЕЛЬНЫЕ РЕСУРСЫ

### Рекомендуемый порядок чтения:
1. ✅ Это быстрый старт (5 минут)
2. ✅ SUBTASK_4_EXECUTIVE_SUMMARY.md (10 минут)
3. ✅ SUBTASK_4_CODE_EXAMPLES.md (30 минут изучения, 4 часа кодирования)

### Если нужна полная информация:
- SUBTASK_4_INDEX.md (навигация)
- SUBTASK_4_ANCHOR_POINT_DESIGN.md (архитектура)
- SUBTASK_4_DIAGRAMS.md (диаграммы)

### Примеры похожих диалогов в KiCad:
- `pcbnew/dialogs/dialog_move.h` — работает с координатами
- `pcbnew/dialogs/dialog_text_properties.h` — radio buttons
- Любой файл в `pcbnew/dialogs/*.h`

---

## ✅ ЧЕКЛИСТ РАЗРАБОТКИ

### Перед началом:
```
☐ Прочитал этот quick start (10 минут)
☐ Понимаю что нужно сделать (один диалог + интеграция)
☐ Готов копировать код из SUBTASK_4_CODE_EXAMPLES.md
```

### День 1-2: Разработка
```
☐ Создал dialog_anchor_point_selection.h/cpp
☐ Добавил методы в edit_tool.h/cpp
☐ Зарегистрировал в pcb_actions.h/cpp
☐ Добавил в меню (edit_menu.cpp)
☐ Проект компилируется без ошибок
☐ Нет предупреждений компилятора
```

### День 3: Тестирование
```
☐ Диалог открывается
☐ 5 режимов тестированы
☐ Копирование работает
☐ Вставка работает
☐ Ctrl+C не меняется (обратная совместимость)
☐ Нет crashes или bagов
```

### День 4: Полиров
```
☐ Добавлены комментарии в коде
☐ Добавлены Doxygen comments
☐ Все строки завёрнуты в _("text") для i18n
☐ Code review пройден
```

---

## 🎯 КОД ГОТОВ!

**Вся необходимая реализация находится в:**

**👉 [SUBTASK_4_CODE_EXAMPLES.md](SUBTASK_4_CODE_EXAMPLES.md)**

Просто скопируйте части:
- ЧАСТЬ 1 → dialog_anchor_point_selection.h/cpp
- ЧАСТЬ 2 → методы в edit_tool.h/cpp
- ЧАСТЬ 3 → pcb_actions.h/cpp
- ЧАСТЬ 4 → edit_menu.cpp

**Готово к использованию!**

---

## 🚀 СЛЕДУЮЩИЙ ШАГ

1. 📖 Откройте [SUBTASK_4_CODE_EXAMPLES.md](SUBTASK_4_CODE_EXAMPLES.md)
2. 👨‍💻 Скопируйте код в ваш проект
3. 🛠️ Адаптируйте пути и names
4. ✅ Следуйте чек-листу тестирования
5. 🎉 Готово!

**Good luck! 💪**
