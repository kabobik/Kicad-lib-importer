# Отчёт: Исследование импорта символов Altium в KiCad 8.0

**Дата:** 9 февраля 2026 г.  
**Проект:** KiCAD_Importer  
**Цель:** Полный импорт всех символов из Altium .SchLib в KiCad .kicad_sym

---

## 1. Архитектура импорта Altium в KiCad 8.0

### 1.1 Файловая структура модуля

Импорт Altium-схем и библиотек в KiCad реализован в нескольких слоях:

| Слой | Путь (относительно `kicad-8.0/`) | Назначение |
|------|----------------------------------|------------|
| **OLE/CFB парсер** | `thirdparty/compoundfilereader/compoundfilereader.h` | Microsoft CFB (OLE Compound Document) — header-only библиотека от Microsoft |
| **Бинарный парсер Altium** | `common/io/altium/altium_binary_parser.h/.cpp` | Обёртка над CFB: класс `ALTIUM_COMPOUND_FILE`, `ALTIUM_BINARY_PARSER` |
| **Утилиты свойств** | `common/io/altium/altium_props_utils.h/.cpp` | Чтение свойств из pipe-delimited строк Altium |
| **Парсер SCH-структур** | `eeschema/sch_io/altium/altium_parser_sch.h/.cpp` | Структуры данных Altium: `ASCH_SYMBOL`, `ASCH_PIN`, `ASCH_RECTANGLE` и т.д. |
| **IO-плагин (основной)** | `eeschema/sch_io/altium/sch_io_altium.h/.cpp` | Класс `SCH_IO_ALTIUM` — 4572 строки, основная логика импорта |
| **Кеш библиотек** | `eeschema/sch_io/altium/sch_io_altium_lib_cache.h` | Кеширование загруженных библиотек |

### 1.2 Ключевые классы

#### `ALTIUM_COMPOUND_FILE` (altium_binary_parser.h)
Обёртка над `CFB::CompoundFileReader`. Основные методы:
- **`GetLibSymbols(start)`** — перечисляет все папки-компоненты в OLE-файле, находит стрим `Data` в каждой. **Это ключевой метод, который находит ВСЕ компоненты в .SchLib**.
- **`FindStream(path)`** — поиск стрима по пути
- **`EnumDir(dir)`** — перечисление файлов в директории (для IntLib)
- **`DecodeIntLibStream(cfe)`** — декодирование интегрированных библиотек

#### `ALTIUM_BINARY_PARSER` (altium_binary_parser.h)
Парсер бинарного потока данных:
- `ReadProperties()` — чтение pipe-delimited свойств (формат `|KEY=VALUE|KEY2=VALUE2|`)
- `Read<Type>()` — чтение примитивных типов
- `ReadWxString()` — чтение Pascal-строк
- `ReadWideStringTable()` — чтение UTF-16 таблицы строк

#### `SCH_IO_ALTIUM` (sch_io_altium.h)
Центральный класс, наследник `SCH_IO`. Ключевые методы:

**Для библиотек (.SchLib):**
- `EnumerateSymbolLib()` — перечисление символов
- `LoadSymbol()` — загрузка конкретного символа
- `ensureLoadedLibrary()` — загрузка и кеширование
- **`ParseLibFile()`** — парсинг ВСЕХ символов из .SchLib (строка 4212)
- **`ParseLibComponent()`** — создание `LIB_SYMBOL` из свойств компонента (строка 4182)
- `ParseLibHeader()` — чтение заголовка библиотеки (строка 4456)

**Для графических примитивов:**
- `ParsePin()`, `ParseRectangle()`, `ParsePolyline()`, `ParsePolygon()`
- `ParseArc()`, `ParseEllipse()`, `ParseCircle()`, `ParseLine()`
- `ParseBezier()`, `ParseRoundRectangle()`, `ParseEllipticalArc()`
- `ParseLabel()`, `ParseTextFrame()`
- `ParseLibDesignator()`, `ParseLibParameter()`
- `ParseImplementation()` — привязка footprint'ов

### 1.3 Поток данных

```
Altium .SchLib (OLE Compound Document)
    │
    ▼
ALTIUM_COMPOUND_FILE  ──── CFB::CompoundFileReader (thirdparty)
    │
    ├─ FindStream("FileHeader") → ParseLibHeader() → шрифты, версия
    │
    ├─ GetLibSymbols(nullptr) → map<name, CFB::COMPOUND_FILE_ENTRY*>
    │   │
    │   ▼ для каждого компонента:
    │   ALTIUM_BINARY_PARSER(entry) → ReadProperties()
    │       │
    │       ├─ Первая запись: RECORD=1 (COMPONENT) → ParseLibComponent() → vector<LIB_SYMBOL*>
    │       │
    │       └─ Остальные записи: ParsePin(), ParseRectangle(), ... → добавление в LIB_SYMBOL
    │
    ▼
map<wxString, LIB_SYMBOL*>  → m_libCache[path]
    │
    ▼
EnumerateSymbolLib() / LoadSymbol()  → KiCad Symbol Editor
```

### 1.4 Три пути импорта .SchLib в KiCad — подробный анализ

#### Путь 1: Symbol Editor → Файл → Импорт → Символ (`ImportSymbol()`)

**Файл:** `eeschema/symbol_editor/symbol_editor_import_export.cpp`, строка 39  
**Поведение:** Импортирует **ТОЛЬКО ПЕРВЫЙ символ** из файла!

```cpp
void SYMBOL_EDIT_FRAME::ImportSymbol()
{
    // ...
    pi->EnumerateSymbolLib( symbols, fn.GetFullPath() );  // ← Находит ВСЕ символы
    // ...
    wxString symbolName = symbols[0];                      // ← Берёт ТОЛЬКО ПЕРВЫЙ!
    LIB_SYMBOL* entry = pi->LoadSymbol( fn.GetFullPath(), symbolName );
    // ...
}
```

Обратите внимание на строку 128: `symbols[0]` — жёстко закодировано взятие первого элемента.  
Есть даже TODO-комментарий на строке 102:
```cpp
// TODO dialog to select the symbol to be imported if there is more than one
```

**Это и есть ограничение, из-за которого импортируется только один компонент.**

---

#### Путь 2: Добавить библиотеку через sym-lib-table (`AddLibraryFile()`)

**Файл:** `eeschema/symbol_editor/symbol_edit_frame.cpp`, строка 931  
**Как вызвать:** Symbol Editor → Файл → Добавить библиотеку (или перетащить файл)  
**Поведение:** Добавляет .SchLib **как библиотеку-источник** в `sym-lib-table`. KiCad использует плагин `SCH_IO_ALTIUM` для чтения **всех** символов «на лету» через `EnumerateSymbolLib()` и `LoadSymbol()`.

```cpp
wxString SYMBOL_EDIT_FRAME::AddLibraryFile( bool aCreateNew )
{
    // ...
    m_libMgr->AddLibrary( fn.GetFullPath(), libTable );
    // ...
}
```

Внутри `addLibrary()` (symbol_library_manager.cpp:721):
```cpp
SCH_IO_MGR::SCH_FILE_T schFileType = SCH_IO_MGR::GuessPluginTypeFromLibPath( aFilePath );
// Для .SchLib → SCH_ALTIUM
wxString typeName = SCH_IO_MGR::ShowType( schFileType ); // → "Altium"
SYMBOL_LIB_TABLE_ROW* libRow = new SYMBOL_LIB_TABLE_ROW( libName, relPath, typeName );
aTable->InsertRow( libRow );
```

**Результат:** .SchLib остаётся как есть, но **все символы доступны** через плагин. Однако, это **не конвертирует** в .kicad_sym — файл Altium используется напрямую.

---

#### Путь 3: CLI-команда `kicad-cli sym upgrade` (`ConvertLibrary()`)

**Файл:** `eeschema/sch_io/sch_io_mgr.cpp`, строка 191 (`ConvertLibrary()`)  
**Вызов:** `eeschema/eeschema_jobs_handler.cpp`, строка 948 (`JobSymUpgrade()`)  
**Команда:**
```bash
kicad-cli sym upgrade --input Capacitors.SchLib --output Capacitors.kicad_sym
```

**Поведение:** Полная конвертация **ВСЕХ символов** из любого формата в .kicad_sym:

```cpp
bool SCH_IO_MGR::ConvertLibrary(...)
{
    oldFilePI->EnumerateSymbolLib( symbols, aOldFilePath );  // ← Все символы!
    
    for( LIB_SYMBOL* symbol : symbols )    // ← Обрабатывает каждый
    {
        if( symbol->IsAlias() ) continue;
        newSymbols.push_back( new LIB_SYMBOL( *symbol ) );
    }
    
    kicadPI->SaveLibrary( aNewFilepath );
    for( LIB_SYMBOL* symbol : newSymbols )
        kicadPI->SaveSymbol( aNewFilepath, symbol );  // ← Сохраняет все
}
```

**Это — наиболее полный путь, использующий полный парсер.**

---

### 1.5 Исходный вопрос: полный парсер SchLib

**ВАЖНО: Штатный KiCad 8.0 уже поддерживает импорт ВСЕХ компонентов из .SchLib!**

Код `ParseLibFile()` (строка 4212 файла `sch_io_altium.cpp`) итерирует ВСЕ символы:

```cpp
std::map<wxString,LIB_SYMBOL*> SCH_IO_ALTIUM::ParseLibFile(
    const ALTIUM_COMPOUND_FILE& aAltiumLibFile )
{
    std::map<wxString,LIB_SYMBOL*> ret;
    // ...
    std::map<wxString, const CFB::COMPOUND_FILE_ENTRY*> syms =
        aAltiumLibFile.GetLibSymbols( nullptr );

    for( auto& [name, entry] : syms )
    {
        // Парсит каждый компонент, добавляет в ret
        // ...
    }
    return ret;
}
```

Функция `ensureLoadedLibrary()` (строка 4396) обрабатывает как `.SchLib`, так и `.IntLib`:

```cpp
void SCH_IO_ALTIUM::ensureLoadedLibrary(...)
{
    if( aLibraryPath.Lower().EndsWith( wxS( ".schlib" ) ) )
    {
        compoundFiles.push_back(
            std::make_unique<ALTIUM_COMPOUND_FILE>( aLibraryPath ) );
    }
    // ...
    for( auto& altiumSchFilePtr : compoundFiles )
    {
        std::map<wxString, LIB_SYMBOL*> parsed =
            ParseLibFile( *altiumSchFilePtr );
        cacheMapRef.insert( parsed.begin(), parsed.end() );
    }
}
```

**Ограничение «один компонент» существует только в контексте импорта СХЕМ (.SchDoc), а не библиотек:**

При импорте SchDoc (функция `ParseComponent()`, строка 1092), KiCad создаёт **уникальный LIB_SYMBOL для каждого экземпляра** символа на схеме, с суффиксами ориентации/зеркалирования. Это работает корректно для схем, но создаёт «дубликаты».

**Реальное ограничение при импорте библиотек:**
- KiCad прекрасно читает все компоненты из SchLib через `EnumerateSymbolLib()`
- Но импорт происходит через UI-диалог «Add Library», а не через отдельный инструмент пакетного импорта
- Пользователь должен вручную добавить .SchLib как библиотеку символов — KiCad распознаёт формат и показывает все компоненты

**Возможная причина жалобы заказчика:** Пользователь пытался **импортировать SchDoc** (схему), а не SchLib (библиотеку). При импорте схемы каждый символ создаётся как отдельный `LIB_SYMBOL` с уникальным именем — это может выглядеть как «один компонент».

---

## 2. Парсинг .SchLib — бинарный формат

### 2.1 Формат файла

**Altium .SchLib — это OLE Compound Document (Microsoft CFB).**

Подтверждено анализом `Capacitors.SchLib`:
```
Composite Document File V2 Document
Magic: D0 CF 11 E0 A1 B1 1A E1
```

Заголовок в данных:
```
|HEADER=Protel for Windows - Schematic Library Editor Binary File Version 5.0|
```

### 2.2 Структура OLE-потоков

Исследование файла `Capacitors.SchLib` (177 152 байт) показало:

```
📁 Root
├── 📄 FileHeader (2810 bytes)     ← Метаданные библиотеки, шрифты
├── 📄 Storage (25 bytes)          ← Хранилище embedded-файлов
├── 📁 C-0.1uF-250V/              ← Каждый компонент = папка
│   ├── 📄 Data (2482 bytes)       ← Бинарные данные компонента
│   └── 📄 PinFrac (87 bytes)      ← Дробные координаты пинов
├── 📁 C-0.1uF-63V/
│   ├── 📄 Data (2222 bytes)
│   └── 📄 PinFrac (87 bytes)
├── 📁 C-4_array/                  ← Многосекционный компонент
│   ├── 📄 Data (2341 bytes)
│   └── 📄 PinFrac (261 bytes)     ← Больше данных → больше пинов
├── 📁 Capacitor/                  ← Компонент с Display Modes
│   ├── 📄 Data (5766 bytes)       ← Больший размер → сложная графика
│   └── 📄 PinFrac (87 bytes)
├── 📁 К50-29/                     ← Кириллические имена поддерживаются
│   ├── 📄 Data (2632 bytes)
│   └── 📄 PinFrac (83 bytes)
...
```

**Всего найдено 48 компонентов** в этой библиотеке.

### 2.3 Формат данных компонента (стрим Data)

Стрим `Data` содержит последовательность записей в формате pipe-delimited properties:

```
|RECORD=1|LIBREFERENCE=C-0.1uF-250V|COMPONENTDESCRIPTION=...|PARTCOUNT=2|DISPLAYMODECOUNT=1|...
|RECORD=14|LOCATION.X=...|LOCATION.Y=...|CORNER.X=...|CORNER.Y=...|...   (Rectangle)
|RECORD=2|NAME=1|DESIGNATOR=1|PINLENGTH=...|LOCATION.X=...|...           (Pin - бинарный)
...
```

**Первая запись всегда RECORD=1 (COMPONENT)** — описание самого компонента.
Далее идут примитивы: пины (RECORD=2), графика (RECORD=6,7,12,14...), параметры (RECORD=41) и т.д.

**Пины в библиотеке хранятся в бинарном формате**, в отличие от scheme, где используется text format. KiCad обрабатывает это через лямбду `handleBinaryDataLambda` в `ParseLibFile()` (строка 4256).

### 2.4 Как KiCad читает бинарный формат

1. **CFB-уровень:** `thirdparty/compoundfilereader/compoundfilereader.h` — header-only C++ библиотека от Microsoft (https://github.com/microsoft/compoundfilereader)
2. **Обёртка:** `ALTIUM_COMPOUND_FILE` загружает файл целиком в память, создаёт `CompoundFileReader`
3. **Перечисление:** `GetLibSymbols()` обходит корневые папки, в каждой ищет стрим `Data`
4. **Чтение свойств:** `ALTIUM_BINARY_PARSER::ReadProperties()` читает pipe-delimited записи из стрима

### 2.5 Ключевые структуры данных

Все структуры определены в `altium_parser_sch.h`:

```cpp
struct ASCH_SYMBOL {                // RECORD=1, компонент
    int      currentpartid;
    wxString libreference;          // Имя компонента
    wxString componentdescription;  // Описание
    int      partcount;             // Количество частей (+1, т.к. включает "общую")
    int      displaymodecount;      // Количество режимов отображения
    int      orientation;
    bool     isMirrored;
    VECTOR2I location;
};

struct ASCH_PIN : ASCH_OWNER_INTERFACE {  // RECORD=2, пин
    wxString name, designator;
    ASCH_PIN_ELECTRICAL electrical;       // INPUT/OUTPUT/BIDI/PASSIVE/...
    ASCH_RECORD_ORIENTATION orientation;  // 0-3 (направление)
    VECTOR2I location;
    int      pinlength;
    int      ownerpartid;                 // К какой секции (unit) принадлежит
    // Символьные модификаторы: negated, clock, etc.
    ASCH_PIN_SYMBOL::PTYPE symbolOuterEdge, symbolInnerEdge;
};
```

### 2.6 Преобразование единиц

Altium хранит координаты в **милах (mils)** с дробной частью:

```cpp
constexpr int Altium2KiCadUnit( const int val, const int frac )
{
    double dbase = 10 * schIUScale.MilsToIU( val );
    double dfrac = schIUScale.MilsToIU( frac ) / 10000.0;
    return KiROUND( (dbase + dfrac) / 10.0 ) * 10;
}
```

Ось Y **инвертируется**: `location.y = -ReadKiCadUnitFrac( aProps, "LOCATION.Y" )`

---

## 3. Формат .kicad_sym

### 3.1 Общая структура

Формат `.kicad_sym` — это S-expression (Lisp-подобный текстовый формат):

```lisp
(kicad_symbol_lib (version 20231120) (generator "kicad_symbol_editor")
  (generator_version "8.0")

  (symbol "SymbolName" (pin_names (offset 1.016)) (in_bom yes) (on_board yes)
    ;; Свойства (обязательные)
    (property "Reference" "C" (at 0 2.54 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Value" "SymbolName" (at 0 -2.54 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Footprint" "" (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "" (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )

    ;; Sub-символ: SymbolName_<unit>_<bodyStyle>
    ;; unit=0 → общая графика для всех секций
    ;; bodyStyle=1 → нормальный, 2 → De Morgan

    (symbol "SymbolName_0_1"          ;; Графика, общая для всех units
      (polyline
        (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
        (stroke (width 0.508) (type default))
        (fill (type none))
      )
    )

    (symbol "SymbolName_1_1"          ;; Unit 1, bodyStyle 1 (пины)
      (pin passive line (at 0 3.81 270) (length 2.794)
        (name "1" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))
      )
    )
  )
)
```

### 3.2 Ключевые элементы

| Элемент | Описание |
|---------|----------|
| `(symbol "Name" ...)` | Определение символа верхнего уровня |
| `(symbol "Name_U_B" ...)` | Sub-символ: U=unit (0=общий), B=bodyStyle |
| `(property ...)` | Свойства: Reference, Value, Footprint, Datasheet, + custom |
| `(pin type shape ...)` | Пин: тип (passive, input, ...), форма (line, inverted, clock, ...) |
| `(polyline ...)` | Полилиния |
| `(rectangle ...)` | Прямоугольник |
| `(circle ...)` | Окружность |
| `(arc ...)` | Дуга |
| `(text ...)` | Текст |
| `(text_box ...)` | Текстовая рамка |
| `(bezier ...)` | Кривая Безье |

### 3.3 Версионирование

Текущая версия KiCad 8: `SEXPR_SYMBOL_LIB_FILE_VERSION = 20231120`
Определено в `eeschema/sch_file_versions.h`.

Основные изменения версий:
- `20220331` — Text colors (совместимо с KiCad 7)
- `20220914` — Unit display names
- `20230620` — ki_description → Description Field
- `20231120` — generator_version; V8 cleanups

### 3.4 Генерация .kicad_sym в исходниках

Файл: `eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_lib_cache.cpp`

**Ключевая функция: `SaveSymbol()`** (строка 133) — сериализует `LIB_SYMBOL` в S-expression:

```cpp
void SCH_IO_KICAD_SEXPR_LIB_CACHE::SaveSymbol(
    LIB_SYMBOL* aSymbol, OUTPUTFORMATTER& aFormatter, int aNestLevel, ...)
{
    // 1. Заголовок символа: имя, флаги
    aFormatter.Print( aNestLevel, "(symbol %s", name.c_str() );
    // pin_numbers hide, pin_names offset/hide, in_bom, on_board

    // 2. Обязательные свойства (fields)
    for( LIB_FIELD* field : fields )
        saveField( field, aFormatter, aNestLevel + 1 );

    // 3. Sub-символы (units × bodyStyles)
    std::vector<LIB_SYMBOL_UNIT> units = aSymbol->GetUnitDrawItems();
    for( const LIB_SYMBOL_UNIT& unit : units )
    {
        aFormatter.Print( "symbol \"%s_%d_%d\"", name, unit.m_unit, unit.m_bodyStyle );
        for( LIB_ITEM* item : unit.m_items )
            saveSymbolDrawItem( item, aFormatter, aNestLevel + 2 );
    }
}
```

**Вспомогательные функции:**
- `savePin()` — сериализация пина
- `saveField()` — сериализация свойства
- `saveSymbolDrawItem()` — диспетчер для LIB_SHAPE, LIB_PIN, LIB_TEXT, LIB_TEXTBOX
- `saveDcmInfoAsFields()` — ki_keywords, ki_fp_filters

### 3.5 Обёртка для файла

Файл .kicad_sym обёрнут в:
```lisp
(kicad_symbol_lib (version 20231120) (generator "kicad_symbol_editor")
  (generator_version "8.0")
  ;; символы в порядке наследования
  (symbol "Name1" ...)
  (symbol "Name2" ...)
)
```

---

## 4. Маппинг Altium → KiCad

### 4.1 Графические примитивы

| Altium Record | KiCad тип | Функция конвертации |
|---------------|-----------|---------------------|
| RECORD=14 (RECTANGLE) | `LIB_SHAPE(SHAPE_T::RECTANGLE)` | `ParseRectangle()` |
| RECORD=6 (POLYLINE) | `LIB_SHAPE(SHAPE_T::POLY)` | `ParsePolyline()` |
| RECORD=7 (POLYGON) | `LIB_SHAPE(SHAPE_T::POLY)` + замыкание | `ParsePolygon()` |
| RECORD=12 (ARC) | `LIB_SHAPE(SHAPE_T::ARC)` | `ParseArc()` |
| RECORD=8 (ELLIPSE) | `LIB_SHAPE(SHAPE_T::CIRCLE)` / дуга | `ParseEllipse()` |
| RECORD=5 (BEZIER) | `LIB_SHAPE(SHAPE_T::BEZIER)` | `ParseBezier()` |
| RECORD=13 (LINE) | `LIB_SHAPE(SHAPE_T::POLY)` 2 точки | `ParseLine()` |
| RECORD=10 (ROUND_RECTANGLE) | `LIB_SHAPE(SHAPE_T::RECTANGLE)` | `ParseRoundRectangle()` |
| RECORD=11 (ELLIPTICAL_ARC) | `LIB_SHAPE(SHAPE_T::ARC)` | `ParseEllipticalArc()` |
| RECORD=4 (LABEL) | `LIB_TEXT` | `ParseLabel()` |
| RECORD=28 (TEXT_FRAME) | `LIB_TEXTBOX` | `ParseTextFrame()` |
| RECORD=30 (IMAGE) | Не поддерживается | — |
| RECORD=3 (IEEE_SYMBOL) | Не поддерживается | — |

### 4.2 Конвертация пинов (ParsePin, строка 1181)

```
Altium ASCH_PIN  →  KiCad LIB_PIN

Координаты:    pin.SetPosition( VECTOR2I(x, -y) )      ← инверсия Y
Ориентация:    RIGHTWARDS → PIN_LEFT, UPWARDS → PIN_DOWN  ← инверсия
               LEFTWARDS → PIN_RIGHT, DOWNWARDS → PIN_UP
Эл.тип:       INPUT → PT_INPUT, BIDI → PT_BIDI, OUTPUT → PT_OUTPUT
               PASSIVE → PT_PASSIVE, POWER → PT_POWER_IN
               OPEN_COLLECTOR → PT_OPENCOLLECTOR
               OPEN_EMITTER → PT_OPENEMITTER
               TRISTATE → PT_TRISTATE
Форма:         NEGATED → INVERTED, CLOCK → CLOCK
               NEGATED+CLOCK → INVERTED_CLOCK
               LOW_INPUT → INPUT_LOW, LOW_OUTPUT → OUTPUT_LOW
Unit:          pin.SetUnit( max(0, elem.ownerpartid) )
```

Важные нюансы:
- В Altium `location` пина указывает на основание (где начинается линия), KiCad хранит позицию **контактной точки** → нужно прибавить `pinlength` в направлении ориентации
- Для library pins (ISKICADLIBPIN=T) координаты уже скорректированы
- Размеры имени/номера пина: если скрыт — устанавливается 0

### 4.3 Конвертация заливки и цвета

```cpp
// Altium: IsSolid + AreaColor → KiCad: FillMode + FillColor
if( !elem.IsSolid )     → FILL_T::NO_FILL
if( AreaColor == Color ) → FILL_T::FILLED_SHAPE
if( bgcolor == default ) → FILL_T::FILLED_WITH_BG_BODYCOLOR
else                     → FILL_T::FILLED_WITH_COLOR

// Цвет из int: RGB packed
int red   = color & 0xFF;
int green = (color >> 8) & 0xFF;
int blue  = (color >> 16) & 0xFF;
```

### 4.4 Многосекционные компоненты (Parts → Units)

В Altium:
- `PARTCOUNT` — количество частей (Parts). **Внимание:** KiCad вычитает 1: `SetUnitCount(partcount - 1)`, т.к. Altium считает «общую» часть (Part 0) отдельно
- `OWNERPARTID` в каждом примитиве указывает, к какой части он принадлежит
- `OWNERPARTID = 0` → примитив принадлежит всем секциям
- `DISPLAYMODECOUNT` — количество режимов отображения (аналог KiCad bodyStyle/De Morgan)

В KiCad:
- `Unit 0` → общая графика
- `Unit 1..N` → конкретные секции
- `BodyStyle 1` → Normal, `BodyStyle 2` → De Morgan (converted)

Код конвертации (`ParseLibComponent()`, строка 4182):
```cpp
std::vector<LIB_SYMBOL*> SCH_IO_ALTIUM::ParseLibComponent(...)
{
    ASCH_SYMBOL elem( aProperties );
    std::vector<LIB_SYMBOL*> symbols;
    symbols.reserve( elem.displaymodecount );

    for( int i = 0; i < elem.displaymodecount; i++ )
    {
        LIB_SYMBOL* symbol = new LIB_SYMBOL( wxEmptyString );
        if( elem.displaymodecount > 1 )
            symbol->SetName( wxString::Format( "%s (Altium Display %d)",
                             elem.libreference, i + 1 ) );
        else
            symbol->SetName( elem.libreference );

        symbol->SetUnitCount( elem.partcount - 1 );
        symbols.push_back( symbol );
    }
    return symbols;
}
```

**Примечание:** при `displaymodecount > 1` KiCad создаёт **отдельные** символы с суффиксом `(Altium Display N)`, а не использует bodyStyle. Это потенциальная область для улучшения.

---

## 5. Анализ файла Capacitors.SchLib

### 5.1 Метаданные

```
Формат: Protel for Windows - Schematic Library Editor Binary File Version 5.0
Размер: 177 152 байт
OLE: Composite Document File V2
Weight: 918
Шрифты: Times New Roman (10pt), GOST type A (12pt), Arial (6pt)
```

### 5.2 Содержимое

Найдено **48 компонентов**, включая:
- Простые конденсаторы: `C-NP`, `C-P`, `C-0.1uF-250V`, ...
- SMD конденсаторы: `C_0805_50V_NP0`, `C_1206_250V_X7R`, ...
- Электролиты: `C_R_1000uF_25V`, `CL_R_2200uF_50V`, ...
- Танталовые: `C-TAN-A-10uF-16V`, `C-TAN-D-100uF-16V`, ...
- Многосекционный: `C-4_array` (PinFrac=261 bytes → больше пинов)
- Универсальные: `Capacitor` (5766 bytes → сложная графика, display modes)
- С display modes: `Polar Capacitor` (5797 bytes)
- Кириллические: `К50-29`, `С_Y1-KX250-10mm`

---

## 6. Рекомендации для нашего проекта

### 6.1 Что можно переиспользовать из KiCad

**Рекомендация: Писать на Python, переиспользуя ЛОГИКУ из KiCad C++ кода.**

Из кода KiCad стоит заимствовать:
1. **Структуру OLE-потоков:** каждый компонент = папка с `Data` + `PinFrac`
2. **Формат свойств:** pipe-delimited `|KEY=VALUE|`
3. **Бинарный формат пинов:** точная структура из `handleBinaryDataLambda`
4. **Маппинг записей:** `ALTIUM_SCH_RECORD` enum с номерами RECORD
5. **Преобразование единиц:** `Altium2KiCadUnit()`, инверсия Y
6. **Маппинг типов пинов:** Altium electrical → KiCad pin type
7. **Маппинг форм пинов:** символьные модификаторы edge/inner
8. **Правило `partcount - 1`** для UnitCount
9. **Формат .kicad_sym:** S-expression с конкретными именами полей

### 6.2 Рекомендуемый подход

**Вариант: Автономный Python-скрипт** (не модификация KiCad, не обёртка)

Обоснование:
- KiCad C++ код сложен (4572 строки только для одного плагина), тесно связан с GUI
- Задача хорошо изолирована: файл-в → файл-out
- Python имеет `olefile` для OLE/CFB
- Формат .kicad_sym — простой текст, генерируется строками
- Не нужно компилировать KiCad

### 6.3 Рекомендуемый стек

```
Python 3.10+
├── olefile           ← чтение OLE/CFB (.SchLib)
├── struct            ← разбор бинарных данных пинов
├── dataclasses       ← внутренняя модель
├── pathlib           ← работа с путями
└── argparse / click  ← CLI
```

### 6.4 Архитектура решения

```
altium2kicad/
├── __main__.py           ← CLI entry point
├── schlib_parser.py      ← Парсер SchLib (OLE → компоненты)
│   ├── read_file_header()
│   ├── list_components()
│   └── parse_component()
├── altium_records.py     ← Структуры данных Altium (RECORD=1,2,6,7,12,14...)
│   ├── parse_properties()  ← pipe-delimited → dict
│   ├── parse_binary_pin()  ← бинарный формат пинов
│   └── Altium2KiCadUnit()
├── symbol_model.py       ← Внутренняя модель
│   ├── Symbol, Unit, Pin, Shape, ...
│   └── normalize()
├── kicad_sym_writer.py   ← Генератор .kicad_sym
│   ├── write_library()
│   ├── write_symbol()
│   ├── write_pin()
│   └── write_shape()
└── tests/
    ├── test_parser.py
    └── test_writer.py
```

### 6.5 Потенциальные проблемы и подводные камни

1. **Бинарный формат пинов в библиотеках** — в отличие от SchDoc, пины в SchLib хранятся в бинарном формате. Нужно точно воспроизвести парсинг из `handleBinaryDataLambda` (строка 4256)

2. **Координатная система** — Altium: Y вверх, KiCad в library editor: Y вниз для позиции. При чтении из Altium, Y инвертируется (`-ReadKiCadUnitFrac("LOCATION.Y")`)

3. **PinFrac стрим** — содержит дробные координаты пинов для повышения точности. KiCad читает их, но в текущей реализации использует основные координаты + frac из properties

4. **Display Modes** — KiCad создаёт отдельные символы с суффиксом `(Altium Display N)`, но в идеале это должно маппиться на bodyStyle (De Morgan)

5. **PARTCOUNT наследие** — Altium`s PARTCOUNT включает «общую» часть (Part 0), KiCad вычитает 1. Необходимо корректно обрабатывать

6. **Кириллические имена** — OLE-файл хранит имена в UTF-16. Python `olefile` обрабатывает это корректно, но нужно проверить валидность в KiCad

7. **Уникальность имён** — если в SchLib есть компоненты с одинаковым `LIBREFERENCE` (маловероятно, но возможно), нужна дедупликация

8. **Размеры шрифтов** — Altium хранит в pt (1 pt = 1/72 дюйма), KiCad в mil (1 mil = 1/1000 дюйма). Формула: `kicad_mils = altium_pt * 72 / 10`

9. **Цвета** — Altium хранит как packed int (R | G<<8 | B<<16). KiCad позволяет unspecified цвет — если цвет совпадает с default, лучше не задавать

10. **Implementation (Footprint)** — RECORD=45 содержит привязку к footprint. Формат: `libname:fpname`. Нужно маппить в свойство Footprint

---

## 7. Вопросы к заказчику

### Критические

1. **Версия KiCad?** — Нужна поддержка KiCad 7, 8 или 9? Формат .kicad_sym немного отличается. Рекомендация: генерировать format version 20220331 (совместимо с 7+).

2. **Что именно «не работает» в штатном импортёре?** — Код KiCad 8.0 уже импортирует ВСЕ компоненты из SchLib. Нужно уточнить:
   - Пользователь пытался импортировать SchDoc или SchLib?
   - Какой UI-путь использовался?
   - Есть ли конкретный пример, где импорт не работает?

3. **Тестовые библиотеки** — Кроме `Capacitors.SchLib`, есть ли более сложные библиотеки с:
   - Многосекционными компонентами (микросхемы с >2 Parts)?
   - Несколькими Display Modes?
   - Embedded изображениями?

### Уточняющие

4. **Формат footprint** — нужно ли сохранять привязки к footprint'ам? Если да, как разрешать имена библиотек?

5. **Параметры (User Properties)** — нужно ли переносить все пользовательские параметры Altium, или только стандартные (Reference, Value, Footprint, Datasheet)?

6. **Batch vs Interactive** — достаточно ли CLI-утилиты, или обязателен KiCad Plugin с GUI?

7. **Валидация** — нужна ли автоматическая проверка через KiCad CLI (`kicad-cli sym check`)?

### Предположения, требующие подтверждения

- Предполагаю, что входные файлы — только .SchLib (не .IntLib). **IntLib** — это интегрированная библиотека, содержащая SchLib + PcbLib + 3D-модели в одном файле. Поддержка IntLib значительно сложнее.
- Предполагаю, что 100% визуальная идентичность не требуется (согласно ТЗ).
- Предполагаю, что порядок компонентов в выходном файле не важен.

---

## 8. Баг KiCad 9.0.7: Крэш при импорте IC.SchLib

### 8.1 Симптом

`kicad-cli sym upgrade IC.SchLib -o output.kicad_sym` завершается с ошибкой:
```
Unable to convert library
```
Исключение (перехвачено через LD_PRELOAD `__cxa_throw` hook):
```
std::out_of_range("ALTIUM_BINARY_READER: out of range")
```

### 8.2 Корневая причина

**Баг в `ALTIUM_BINARY_PARSER::ReadProperties()`** — функция ошибочно обрезает trailing null-byte у **бинарных** записей.

Файл: `common/io/altium/altium_binary_parser.cpp`, строки 375-387:
```cpp
bool hasNullByte = m_pos[length - 1] == '\0';
// ...
std::string str = std::string( m_pos, length - ( hasNullByte ? 1 : 0 ) );
m_pos += length;

if( isBinary )
{
    return handleBinaryData( str );  // str уже обрезана на 1 байт!
}
```

Проблема: `hasNullByte` проверяется **до** ветки `isBinary`. Для текстовых записей (`|KEY=VALUE|...`) trailing `\0` — это терминатор, и обрезка корректна. Но для **бинарных** записей (PinFrac compressed data) последний байт `0x00` является **частью zlib-потока**, а не терминатором.

Когда zlib-данные случайно заканчиваются на `0x00`:
1. KiCad обрезает этот байт → `binaryData` короче на 1
2. `ALTIUM_COMPRESSED_READER::ReadCompressedString()` вызывает `ReadFullPascalString()`
3. Длина в FullPascalString указывает на N байт, но доступно только N-1
4. **`ReadFullPascalString()` бросает `std::out_of_range`**

### 8.3 Стек вызовов (GDB + debug symbols, kicad-dbg 9.0.7)

```
#6  ALTIUM_BINARY_READER::ReadFullPascalString()     ← THROW
#7  ALTIUM_COMPRESSED_READER::ReadCompressedString()  ← PinFrac parsing
#8  operator() [parse_binary_pin_frac lambda]          ← sch_io_altium.cpp:4598
#9  SCH_IO_ALTIUM::ParseLibFile()
#10 SCH_IO_ALTIUM::ensureLoadedLibrary()
#11 SCH_IO_ALTIUM::doEnumerateSymbolLib()
#12 SCH_IO_ALTIUM::EnumerateSymbolLib()
#13 SCH_IO_MGR::ConvertLibrary()                       ← catch(...) глушит ошибку
```

### 8.4 Затронутые компоненты (IC.SchLib, 311 компонентов)

10 записей PinFrac в 9 компонентах ломаются:

| Компонент | PinFrac rec# | Длина записи | zlib нужно | zlib доступно |
|-----------|-------------|-------------|-----------|--------------|
| ATMega128 | 64 | 25 | 17 | 16 |
| ATtiny13 | 8 | 24 | 17 | 16 |
| CY8C29466-24SX | 3 | 27 | 20 | 19 |
| MAX7219 | 22 | 28 | 20 | 19 |
| PIC32MX795F512LT-80V_PT | 100 | 25 | 17 | 16 |
| STM32F303CCT6 | 1 | 27 | 20 | 19 |
| STM32F401CCU6 | 36 | 28 | 20 | 19 |
| STM32F401CCU6 | 45 | 28 | 20 | 19 |
| STP16CP05 | 17 | 28 | 20 | 19 |
| TPS61088RHLR | 4 | 27 | 20 | 19 |

### 8.5 Предлагаемый фикс для KiCad

```cpp
// В ReadProperties(), ПЕРЕД обрезкой null byte, проверить isBinary:
bool hasNullByte = m_pos[length - 1] == '\0';

if( !hasNullByte && !isBinary )
{
    wxLogTrace( ... );
}

// Для бинарных записей НЕ обрезать null byte
std::string str = std::string( m_pos, length - ( ( hasNullByte && !isBinary ) ? 1 : 0 ) );
m_pos += length;
```

### 8.6 Workaround для нашего конвертера

В Python-конвертере при парсинге PinFrac **НЕ обрезать** trailing null-byte для бинарных записей:
```python
if is_binary:
    effective = record_data[:length]  # Полный размер, без обрезки
else:
    effective = record_data[:length - (1 if has_null else 0)]
```

### 8.7 Методика расследования

1. **LD_PRELOAD hook** — perехват `__cxa_throw` с backtrace → определение типа исключения
2. **Python OLE анализ** (olefile) → структура IC.SchLib, 311 компонентов
3. **C++ тест с CFB** — минимальная программа с KiCad CFB-библиотекой → 0 ошибок (не повторило баг, т.к. не обрезала null-byte)
4. **kicad-dbg пакет** (804 MB debug symbols) → GDB core dump анализ → точный стек вызовов
5. **Python bisect** → все 10 затронутых записей найдены

---

## 9. Краткие выводы

1. **KiCad 8/9 умеет читать все компоненты из SchLib** через `SCH_IO_ALTIUM`, но содержит **баг с null-byte stripping** в `ReadProperties()`, который ломает импорт PinFrac для компонентов где zlib-данные случайно заканчиваются на `0x00`.

2. **Баг присутствует и в master-ветке KiCad** (проверено через GitLab). Не зарегистрирован как issue.

3. **Ограничение Symbol Editor** — `ImportSymbol()` использует `symbols[0]`, импортирует только первый символ.

4. **Автономный Python-конвертер** позволяет обойти оба ограничения — batch-обработка всех символов и корректный парсинг бинарных записей без null-byte stripping.

5. **Рекомендуется Python-решение** с использованием `olefile`, с логикой, заимствованной из KiCad C++ кода, но с исправленным обращением с бинарными записями.

6. **Объём работ оценивается в ~500-800 строк Python-кода** + тесты.
