; ============================================================================
;   УСТАНОВЩИК AUTO-COMPILER ДЛЯ WINDOWS (сценарий Inno Setup 7)
; ============================================================================
;
; Что делает готовый установщик AutoCompiler-Setup.exe:
;   1. Показывает мастер в тёмном стиле: приветствие → лицензия → выбор папки →
;      галочка «Создать значок на рабочем столе» → «Всё готово к установке».
;   2. ДО копирования файлов ищет в реестре Windows полноценный Python (3.10 и новее,
;      обязательно с tkinter). Если его нет — скачивает официальный установщик
;      Python 3.12.10 с python.org (с проверкой SHA-256) и ставит его скрыто:
;      /quiet InstallAllUsers=0 PrependPath=1 — пользователь видит только полосу прогресса.
;   3. Копирует в выбранную папку autocompiler\, main.py и requirements.txt.
;   4. В конце (секция [Run]) один раз выполняет pip install -r requirements.txt
;      в фоне, без чёрных окон, показывая понятный ход установки библиотек.
;   5. Создаёт ярлыки (рабочий стол и меню «Пуск»), которые запускают
;      pythonw.exe main.py — программа открывается без консольного окна.
;
; Как собрать установщик (нужно один раз установить Inno Setup 7.1 или новее):
;   * скачайте Inno Setup: https://jrsoftware.org/isdl.php (бесплатно);
;   * откройте этот файл в Inno Setup (программа ISIDE) и нажмите Ctrl+F9 (Build → Compile);
;   * или из командной строки:  "C:\Program Files\Inno Setup 7\ISCC.exe" installer\installer.iss
;   * готовый файл появится здесь: installer\Output\AutoCompiler-Setup.exe
;
; Полезные параметры командной строки готового установщика (для тестов и администраторов):
;   /SILENT или /VERYSILENT   — установка без вопросов (полностью тихая);
;   /SUPPRESSMSGBOXES          — не показывать окна сообщений (выбирается ответ по умолчанию);
;   /LOG="путь.txt"            — подробный журнал установки в указанный файл;
;   /DIR="папка"               — папка установки;
;   /TASKS="desktopicon"       — создать значок на рабочем столе;
;   /CURRENTUSER или /ALLUSERS — только для меня / для всех пользователей;
;   /FORCEPYTHON=1             — всегда скачивать и ставить Python 3.12.10, даже если
;                                подходящий Python уже найден (нужно для автотестов).
;
; Кодировка этого файла — UTF-8 с BOM: так Inno Setup правильно читает русский текст.
; ============================================================================


; ----------------------------------------------------------------------------
;   ПРЕПРОЦЕССОР: проверка версии Inno Setup и общие настройки
; ----------------------------------------------------------------------------

; Этот сценарий использует возможности Inno Setup 7 (тёмный стиль мастера,
; ExecAndLogOutput, OnLog в [Run]). На старой версии — понятная ошибка вместо десятка непонятных.
#if VER < EncodeVer(7, 0, 0)
  #error Для сборки нужен Inno Setup 7.0 или новее. Скачайте его: https://jrsoftware.org/isdl.php
#endif

; Название программы — показывается в мастере, в меню «Пуск» и в списке установленных программ.
#define AppName "Auto-Compiler"
; Автор (издатель) — показывается в «Приложениях и возможностях».
#define AppPublisher "Clayworld20"
; Страница проекта.
#define AppURL "https://github.com/Clayworld20/KakayatoBurmalda"
; Постоянный уникальный идентификатор программы. НИКОГДА не меняйте его: по нему
; новая версия установщика узнаёт старую и обновляет её, а не ставит вторую копию.
; Двойная «{{» — так Inno Setup записывает обычную фигурную скобку.
#define AppId "{{C9F4CBD5-4717-47AB-9203-2AE620BA3BD5}"

; Версия Python, которую установщик скачивает, если подходящего Python на компьютере нет.
; 3.12.10 — последняя версия ветки 3.12 с официальными установщиками для Windows;
; под неё есть готовые библиотеки практически для всего.
#define PythonVersion "3.12.10"
; Ветка Python (первые две цифры версии) — по ней ищем свежеустановленный Python в реестре.
#define PythonBranch "3.12"
; Контрольные суммы SHA-256 официальных установщиков с python.org (взяты из подписей Sigstore,
; которые python.org публикует рядом с каждым файлом). Если файл скачается повреждённым
; или подменённым, установщик заметит это и не станет его запускать.
; 64-битный Windows (обычные компьютеры с процессорами Intel/AMD) и Windows 11 на ARM.
#define PythonSha256Amd64 "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
; Windows 10 на процессорах ARM (без эмуляции x64).
#define PythonSha256Arm64 "377ac8fd478987940088e879441e702a71b53164d2a1e6f1d51ff77a7e470258"
; Старый 32-битный Windows.
#define PythonSha256Win32 "fdfe385b94f5b8785a0226a886979527fd26eb65defdbf29992fd22cc4b0e31e"

; Общие параметры pip (одни и те же в секции [Run] и при повторной попытке из [Code]):
;   --disable-pip-version-check — не проверять обновления самого pip (лишняя загрузка);
;   --no-warn-script-location   — не предупреждать про PATH (пользователю это не нужно);
;   --prefer-binary              — брать готовые сборки библиотек, а не собирать из исходников;
;   --no-input                   — никогда не ждать ввода с клавиатуры (окна всё равно нет);
;   --timeout 20 --retries 2     — без интернета pip сдастся примерно за минуту, а не будет
;                                  ждать по несколько минут: установщик не должен «висеть».
#define PipOptions "--disable-pip-version-check --no-warn-script-location --prefer-binary --no-input --timeout 20 --retries 2"
; Модуль, по которому проверяем, что библиотеки интерфейса действительно установились.
#define VerifyImport "customtkinter"

; Версия программы — читаем её прямо из autocompiler\__init__.py (строка APP_VERSION = "1.0.1"),
; чтобы не обновлять номер версии в двух местах. Можно переопределить из командной строки:
;   ISCC /DAppVersion=1.2.3 installer.iss
#ifndef AppVersion
  ; Путь к файлу с версией (SourcePath — папка этого сценария, то есть installer\).
  #define VersionFile AddBackslash(SourcePath) + "..\autocompiler\__init__.py"
  ; Номер открытого файла (0 — файл не открылся).
  #define VersionHandle 0
  ; Текущая прочитанная строка файла.
  #define VersionLine ""
  ; Здесь окажется найденная версия.
  #define AppVersion ""
  ; Подпрограмма препроцессора: прочитать одну строку и, если это APP_VERSION, взять текст в кавычках.
  ; Важно: внутри #sub используем присваивание (#expr X = …), а не #define — переменная,
  ; объявленная через #define внутри подпрограммы, после её окончания не сохраняется.
  #sub ReadVersionLine
    #expr VersionLine = FileRead(VersionHandle)
    #if Pos("APP_VERSION", VersionLine) == 1
      #expr AppVersion = Copy(VersionLine, Pos('"', VersionLine) + 1, RPos('"', VersionLine) - Pos('"', VersionLine) - 1)
    #endif
  #endsub
  ; Открываем файл и читаем строки, пока не найдём версию или не дойдём до конца.
  #for {VersionHandle = FileOpen(VersionFile); VersionHandle && !FileEof(VersionHandle) && AppVersion == ""; ""} ReadVersionLine
  ; Закрываем файл.
  #if VersionHandle
    #expr FileClose(VersionHandle)
  #endif
  ; Версию не нашли — останавливаем сборку с понятной причиной.
  #if AppVersion == ""
    #error Не удалось прочитать APP_VERSION из autocompiler\__init__.py. Укажите версию вручную: ISCC /DAppVersion=1.0.0 installer.iss
  #endif
#endif
; Показываем найденную версию в выводе компилятора (для самоконтроля).
#pragma message "Версия Auto-Compiler: " + AppVersion


; ----------------------------------------------------------------------------
;   [Setup] — ОБЩИЕ НАСТРОЙКИ УСТАНОВЩИКА
; ----------------------------------------------------------------------------
[Setup]
; Уникальный идентификатор программы (см. AppId выше).
AppId={#AppId}
; Название программы.
AppName={#AppName}
; Версия программы.
AppVersion={#AppVersion}
; Название с версией — заголовок мастера и строка в «Приложениях и возможностях».
AppVerName={#AppName} {#AppVersion}
; Издатель.
AppPublisher={#AppPublisher}
; Ссылки «Сайт», «Поддержка», «Обновления» в карточке программы в Windows.
AppPublisherURL={#AppURL}
; Ссылка на поддержку (вкладка Issues на GitHub).
AppSupportURL={#AppURL}/issues
; Ссылка на свежие версии.
AppUpdatesURL={#AppURL}/releases

; Папка по умолчанию. {autopf} сама выбирает правильное место:
;   * установка «только для меня» → %LOCALAPPDATA%\Programs\Auto-Compiler (права администратора не нужны);
;   * установка «для всех пользователей» → C:\Program Files\Auto-Compiler.
DefaultDirName={autopf}\{#AppName}
; Страница выбора папки ВКЛЮЧЕНА — пользователь может выбрать свою папку.
DisableDirPage=no
; Название папки в меню «Пуск».
DefaultGroupName={#AppName}
; Отдельную страницу выбора папки меню «Пуск» не показываем — меньше лишних вопросов.
DisableProgramGroupPage=yes
; Показываем приветственную страницу с большой картинкой (в Inno Setup 6+ она по умолчанию скрыта).
DisableWelcomePage=no
; Лицензионное соглашение — отдельная страница; без согласия кнопка «Далее» недоступна.
LicenseFile=license_ru.txt

; По умолчанию ставим БЕЗ прав администратора — «только для меня». Это совпадает с тем,
; как ставится Python (InstallAllUsers=0), и не вызывает окно UAC у обычного пользователя.
PrivilegesRequired=lowest
; Но даём выбор: в начале мастер спросит «Установить только для меня / для всех пользователей».
; «Для всех» потребует права администратора и поставит программу в Program Files.
; Примечание: Python всё равно ставится для текущей учётной записи (InstallAllUsers=0),
; поэтому другие пользователи этого компьютера должны будут один раз запустить установщик сами.
PrivilegesRequiredOverridesAllowed=dialog
; Мы сознательно работаем с реестром и папками текущего пользователя (Python ставится
; «только для меня»), поэтому отключаем соответствующее предупреждение компилятора.
UsedUserAreasWarning=no
; На 64-битных Windows (включая Windows 11 на ARM с эмуляцией x64) — 64-битный режим:
; «для всех пользователей» программа попадёт в C:\Program Files, а не в Program Files (x86).
ArchitecturesInstallIn64BitMode=x64compatible
; Минимальная версия — Windows 10 (Python 3.12 и Inno Setup 7 на более старых не работают).
MinVersion=10.0

; Внешний вид: современный стиль, принудительно тёмный (как сама программа),
; тёмным становится и заголовок окна.
WizardStyle=modern dark includetitlebar
; Большая картинка слева на первой и последней страницах — несколько размеров под разные
; масштабы экрана (100–200 %); Inno Setup сам выберет самую чёткую.
WizardImageFile=assets\wizard-202x386.png,assets\wizard-269x515.png,assets\wizard-336x643.png,assets\wizard-403x772.png,assets\wizard-430x824.png
; Маленькая картинка в правом верхнем углу остальных страниц — тоже в нескольких размерах.
WizardSmallImageFile=assets\wizard-small-58.png,assets\wizard-small-77.png,assets\wizard-small-97.png,assets\wizard-small-116.png,assets\wizard-small-124.png
; Значок самого файла установщика.
SetupIconFile=autocompiler.ico
; Значок программы в «Приложениях и возможностях» (файл копируется в папку программы).
UninstallDisplayIcon={app}\autocompiler.ico
; Название в списке установленных программ.
UninstallDisplayName={#AppName}
; Язык выбирается автоматически (он один — русский), окно выбора языка не нужно.
ShowLanguageDialog=no

; Куда положить готовый установщик (относительно этого файла): installer\Output\.
OutputDir=Output
; Имя готового файла: AutoCompiler-Setup.exe.
OutputBaseFilename=AutoCompiler-Setup
; Сжатие LZMA2 с максимальной степенью — установщик получается маленьким.
Compression=lzma2/max
; «Сплошное» сжатие всех файлов вместе — ещё меньше размер.
SolidCompression=yes
; Сведения о файле установщика (видны в «Свойства → Подробно»).
VersionInfoVersion={#AppVersion}
; Описание файла.
VersionInfoDescription=Установщик {#AppName}
; Название продукта.
VersionInfoProductName={#AppName}
; Дополнительное место на диске под Python и библиотеки (примерно 200 МБ),
; чтобы мастер честно предупредил, если места не хватает.
ExtraDiskSpaceRequired=209715200
; Всегда вести журнал установки в папке %TEMP% (файл «Setup Log ….txt»):
; если что-то пойдёт не так, его можно приложить к сообщению об ошибке.
SetupLogging=yes


; ----------------------------------------------------------------------------
;   [Languages] — ЯЗЫК МАСТЕРА
; ----------------------------------------------------------------------------
[Languages]
; Русский перевод всех стандартных кнопок и текстов (файл входит в комплект Inno Setup).
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"


; ----------------------------------------------------------------------------
;   [Messages] — НАШИ ТЕКСТЫ ВМЕСТО НЕКОТОРЫХ СТАНДАРТНЫХ
; ----------------------------------------------------------------------------
[Messages]
; Текст на приветственной странице: сразу объясняем, что про Python думать не нужно.
WelcomeLabel2=Мастер установит [name/ver] на ваш компьютер.%n%nAuto-Compiler превращает скрипты Python в обычные программы .exe — без командной строки и настроек.%n%nЕсли на компьютере нет Python, мастер сам скачает его с официального сайта python.org и установит. Понадобится подключение к интернету.
; Текст на последней странице.
FinishedLabel=Установка [name] завершена.%n%nПрограмму можно запустить ярлыком на рабочем столе или в меню «Пуск».


; ----------------------------------------------------------------------------
;   [Tasks] — ГАЛОЧКИ НА СТРАНИЦЕ «ДОПОЛНИТЕЛЬНЫЕ ЗАДАЧИ»
; ----------------------------------------------------------------------------
[Tasks]
; «Создать значок на рабочем столе» — по умолчанию отмечена (так проще новичку).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"


; ----------------------------------------------------------------------------
;   [InstallDelete] — ЧТО УДАЛИТЬ ПЕРЕД КОПИРОВАНИЕМ (при обновлении)
; ----------------------------------------------------------------------------
[InstallDelete]
; Старая папка с кодом программы удаляется целиком, чтобы после обновления не осталось
; устаревших модулей. Папку runtime (среда сборки, сотни мегабайт) НЕ трогаем.
Type: filesandordirs; Name: "{app}\autocompiler"


; ----------------------------------------------------------------------------
;   [Files] — КАКИЕ ФАЙЛЫ КОПИРОВАТЬ
; ----------------------------------------------------------------------------
; Пути «..\» — относительно этого файла: сценарий лежит в installer\, а код — на уровень выше.
; Флаг ignoreversion — всегда заменять файл (у .py-файлов нет «версии», сравнивать нечего).
[Files]
; Точка входа программы.
Source: "..\main.py"; DestDir: "{app}"; Flags: ignoreversion
; Список библиотек для pip (используется секцией [Run] ниже).
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Весь пакет autocompiler со всеми вложенными папками (gui, core, utils).
; Кэш байткода Python (__pycache__, *.pyc) не копируем — Python создаст его сам.
Source: "..\autocompiler\*"; DestDir: "{app}\autocompiler"; Excludes: "__pycache__,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs createallsubdirs
; Значок для ярлыков и для карточки программы в Windows.
Source: "autocompiler.ico"; DestDir: "{app}"; Flags: ignoreversion


; ----------------------------------------------------------------------------
;   [Icons] — ЯРЛЫКИ
; ----------------------------------------------------------------------------
; Ярлык запускает pythonw.exe (Python БЕЗ консольного окна) того Python, который найден
; или только что установлен — его путь возвращает функция GetPythonW из секции [Code].
; Параметр — путь к main.py в кавычках (на случай пробелов в пути).
[Icons]
; Ярлык в меню «Пуск».
Name: "{autoprograms}\{#AppName}"; Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\autocompiler.ico"; Comment: "Превращает скрипты Python в программы .exe"
; Ярлык на рабочем столе — только если пользователь оставил галочку desktopicon.
Name: "{autodesktop}\{#AppName}"; Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\autocompiler.ico"; Comment: "Превращает скрипты Python в программы .exe"; Tasks: desktopicon


; ----------------------------------------------------------------------------
;   [Run] — ЧТО ЗАПУСТИТЬ ПОСЛЕ КОПИРОВАНИЯ ФАЙЛОВ
; ----------------------------------------------------------------------------
[Run]
; 1) Установка библиотек: python.exe -m pip install -r requirements.txt — один раз, в фоне.
;    runhidden    — никаких чёрных окон;
;    logoutput    — вывод pip не теряется: каждая строка передаётся в процедуру PipOnLog,
;                   которая показывает понятный ход установки и замечает проблемы с интернетом;
;    BeforeInstall — перед запуском убеждаемся, что у Python есть pip;
;    AfterInstall  — после запуска ПРОВЕРЯЕМ результат (секция [Run] сама не видит код ошибки
;                   pip) и при неудаче вежливо предлагаем повторить.
Filename: "{code:GetPythonExe}"; Parameters: "-m pip install {#PipOptions} -r ""{app}\requirements.txt"""; WorkingDir: "{app}"; StatusMsg: "Скачиваю и устанавливаю библиотеки интерфейса…"; Flags: runhidden logoutput; OnLog: PipOnLog; BeforeInstall: BeforePipInstall; AfterInstall: AfterPipInstall
; 2) Галочка «Запустить Auto-Compiler» на последней странице мастера (через pythonw — без консоли).
;    nowait — не ждать закрытия программы; skipifsilent — при тихой установке не запускать.
Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Запустить {#AppName}"; Flags: postinstall nowait skipifsilent


; ----------------------------------------------------------------------------
;   [UninstallDelete] — ЧТО ЕЩЁ УДАЛИТЬ ПРИ УДАЛЕНИИ ПРОГРАММЫ
; ----------------------------------------------------------------------------
; Файлы, которые программа создала сама во время работы (установщик о них не знает).
[UninstallDelete]
; Портативная среда сборки, которую Auto-Compiler скачивает при первой сборке .exe.
Type: filesandordirs; Name: "{app}\runtime"
; Кэш байткода Python внутри пакета программы.
Type: filesandordirs; Name: "{app}\autocompiler"
; Кэш байткода рядом с main.py.
Type: filesandordirs; Name: "{app}\__pycache__"
; Сама папка программы — если в ней больше ничего не осталось.
Type: dirifempty; Name: "{app}"


; ----------------------------------------------------------------------------
;   [Code] — ЛОГИКА НА ЯЗЫКЕ PASCAL SCRIPT
; ----------------------------------------------------------------------------
; Здесь: поиск Python в реестре, скачивание и тихая установка Python, контроль pip,
; вежливые сообщения об ошибках и уборка при удалении.
[Code]

// ===================== Константы =====================
const
  // Версия Python для скачивания (из определения препроцессора вверху файла).
  PythonVersion = '{#PythonVersion}';
  // Ветка Python, например 3.12 — так называется раздел в реестре после установки.
  PythonBranch = '{#PythonBranch}';
  // Папка загрузок этой версии на официальном сайте.
  PythonDownloadUrl = 'https://www.python.org/ftp/python/{#PythonVersion}/';
  // Минимальная подходящая версия уже установленного Python.
  MinPythonVersion = '3.10';
  // Раздел реестра, где установщики python.org регистрируют Python (стандарт PEP 514).
  PythonCoreKey = 'Software\Python\PythonCore';
  // Сторож загрузки: если столько миллисекунд не пришло ни байта — считаем, что связь пропала.
  StallTimeoutMs = 45000;
  // Перевод строки для текстов сообщений.
  CRLF = #13#10;

// ===================== Глобальные переменные =====================
var
  // Полный путь к python.exe (консольный Python — для pip и проверок).
  PythonExe: String;
  // Полный путь к pythonw.exe (Python без консольного окна — для ярлыков).
  PythonWExe: String;
  // Как этот Python назван в реестре (например, 3.12) — для страницы «Готово к установке».
  PythonTag: String;
  // True — параметр /FORCEPYTHON=1: всегда ставить свой Python (для автотестов).
  ForcePython: Boolean;
  // Страница скачивания с полосой прогресса и кнопкой прерывания (встроена в Inno Setup).
  DownloadPage: TDownloadWizardPage;
  // Страница «Установка Python» с бегущей полосой (точный процент установщик Python не сообщает).
  InstallPage: TOutputMarqueeProgressWizardPage;
  // Сторож загрузки: сколько байт было скачано при прошлой проверке.
  LastBytes: Int64;
  // Сторож загрузки: когда (в миллисекундах от запуска Windows) байты приходили последний раз.
  LastTick: DWORD;
  // True — загрузку прервал сторож (данные перестали приходить), а не пользователь.
  StallDetected: Boolean;
  // Последние строки вывода pip — чтобы показать их в сообщении об ошибке.
  PipTail: String;
  // True — в выводе pip встретились признаки проблем с интернетом.
  PipNetworkError: Boolean;

// Функция Windows: сколько миллисекунд прошло с запуска системы (для сторожа загрузки).
function GetTickCount: DWORD; external 'GetTickCount@kernel32.dll stdcall';


// ===================== Мелкие помощники =====================

// Есть ли подстрока Needle в строке Haystack без учёта регистра букв.
function ContainsText(const Haystack, Needle: String): Boolean;
begin
  // Переводим обе строки в нижний регистр и ищем.
  Result := Pos(Lowercase(Needle), Lowercase(Haystack)) > 0;
end;

// Добавить строку в «хвост» вывода pip, храня только последние ~1500 символов.
procedure AddToPipTail(const Line: String);
begin
  // Дописываем строку с переводом строки.
  PipTail := PipTail + Line + CRLF;
  // Слишком длинно — отрезаем начало (старые строки не нужны).
  if Length(PipTail) > 1500 then
    // Оставляем последние 1500 символов.
    PipTail := Copy(PipTail, Length(PipTail) - 1499, 1500);
end;


// ===================== Поиск Python в реестре =====================

// Проверить, что Python по этому пути действительно работает: версия 3.10+ и рабочий tkinter.
function IsPythonUsable(const Exe: String): Boolean;
var
  // Код завершения проверочной команды.
  ResultCode: Integer;
begin
  // По умолчанию — не подходит.
  Result := False;
  // Файла нет — дальше не проверяем.
  if (Exe = '') or not FileExists(Exe) then
    // Выходим с ответом «не подходит».
    Exit;
  // «Python» из Microsoft Store (папка WindowsApps) — это часто лишь ярлык-заглушка; не используем.
  if Pos('\WINDOWSAPPS\', Uppercase(Exe)) > 0 then
  begin
    // Пишем в журнал установки, почему пропустили.
    Log('Пропускаю Python из Microsoft Store: ' + Exe);
    // Выходим.
    Exit;
  end;
  // Любая неожиданность при запуске не должна ронять установщик.
  try
    // Скрыто запускаем короткую проверку: импорт tkinter + создание интерпретатора Tcl
    // (проверяет, что файлы Tcl/Tk на месте) + сравнение версии. Код 0 — всё хорошо.
    if Exec(Exe, '-I -c "import sys, tkinter; tkinter.Tcl(); sys.exit(0 if sys.version_info >= (3, 10) else 3)"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      // Подходит, только если проверка завершилась с кодом 0.
      Result := (ResultCode = 0);
    // Записываем результат в журнал.
    Log(Format('Проверка Python %s: код %d', [Exe, ResultCode]));
  except
    // Записываем текст ошибки в журнал; ответ остаётся «не подходит».
    Log('Ошибка проверки Python ' + Exe + ': ' + GetExceptionMessage);
  end;
end;

// Разобрать имя раздела реестра (3.12, 3.12-32, 3.12-arm64, 3.13t) в номер версии.
// Возвращает True, если это обычный (не экспериментальный «t») Python версии 3.10 или новее.
function ParsePythonTag(const Tag: String; var Version: Int64): Boolean;
var
  // Номер текущего символа.
  I: Integer;
  // Цифры и точки в начале имени — собственно версия.
  VersionText: String;
  // Остаток имени после версии (например, -32 или t).
  Rest: String;
  // Минимальная версия в упакованном виде.
  MinVersion: Int64;
begin
  // По умолчанию — не подходит.
  Result := False;
  // Начинаем с пустой версии.
  VersionText := '';
  // Идём по символам имени.
  for I := 1 to Length(Tag) do
  begin
    // Цифра или точка — часть версии.
    if ((Tag[I] >= '0') and (Tag[I] <= '9')) or (Tag[I] = '.') then
      // Добавляем символ к версии.
      VersionText := VersionText + Tag[I]
    else
      // Первый другой символ — версия закончилась.
      Break;
  end;
  // Всё, что после версии.
  Rest := Copy(Tag, Length(VersionText) + 1, Length(Tag));
  // Версии нет, или это экспериментальная сборка без GIL («3.13t») — пропускаем.
  if (VersionText = '') or (Copy(Rest, 1, 1) = 't') then
    // Выходим.
    Exit;
  // Превращаем текст в число для сравнения; не получилось — пропускаем.
  if not StrToVersion(VersionText, Version) then
    // Выходим.
    Exit;
  // Минимальная версия в том же виде.
  if not StrToVersion(MinPythonVersion, MinVersion) then
    // Выходим (на практике не случается).
    Exit;
  // Подходит, если версия не меньше минимальной.
  Result := ComparePackedVersion(Version, MinVersion) >= 0;
end;

// Прочитать из реестра пути к python.exe и pythonw.exe для одного раздела Python.
procedure ReadPythonPaths(const Root: HKEY; const Key: String; var Exe, ExeW: String);
var
  // Папка установки Python.
  Dir: String;
begin
  // Путь к python.exe (значение ExecutablePath по стандарту PEP 514).
  if not RegQueryStringValue(Root, Key + '\InstallPath', 'ExecutablePath', Exe) then
    // Значения нет — пусто.
    Exe := '';
  // Путь к pythonw.exe (значение WindowedExecutablePath).
  if not RegQueryStringValue(Root, Key + '\InstallPath', 'WindowedExecutablePath', ExeW) then
    // Значения нет — пусто.
    ExeW := '';
  // Значение по умолчанию раздела InstallPath — папка установки (есть всегда).
  if RegQueryStringValue(Root, Key + '\InstallPath', '', Dir) and (Dir <> '') then
  begin
    // Нет ExecutablePath — собираем путь из папки.
    if Exe = '' then
      // python.exe в папке установки.
      Exe := AddBackslash(Dir) + 'python.exe';
    // Нет WindowedExecutablePath — собираем путь из папки.
    if ExeW = '' then
      // pythonw.exe в папке установки.
      ExeW := AddBackslash(Dir) + 'pythonw.exe';
  end;
  // Последняя попытка: pythonw.exe лежит рядом с python.exe.
  if (ExeW = '') and (Exe <> '') then
    // Берём папку python.exe.
    ExeW := AddBackslash(ExtractFileDir(Exe)) + 'pythonw.exe';
end;

// Проверить один конкретный раздел реестра; если Python там рабочий — запомнить его.
function TryPythonKey(const Root: HKEY; const RootName, Tag: String): Boolean;
var
  // Путь к python.exe.
  Exe: String;
  // Путь к pythonw.exe.
  ExeW: String;
begin
  // По умолчанию — не подошёл.
  Result := False;
  // Читаем пути из реестра.
  ReadPythonPaths(Root, PythonCoreKey + '\' + Tag, Exe, ExeW);
  // Без pythonw.exe ярлык без консоли не сделать — такой Python не берём.
  if (Exe = '') or not FileExists(ExeW) then
    // Выходим.
    Exit;
  // Проверяем, что Python запускается и в нём есть tkinter.
  if not IsPythonUsable(Exe) then
    // Выходим.
    Exit;
  // Запоминаем найденный Python.
  PythonExe := Exe;
  // И его «безоконный» вариант.
  PythonWExe := ExeW;
  // И название раздела.
  PythonTag := Tag;
  // Сообщаем в журнал.
  Log(Format('Найден подходящий Python %s (%s): %s', [Tag, RootName, Exe]));
  // Подошёл.
  Result := True;
end;

// Перебрать все версии Python в одной ветке реестра и запомнить самую новую рабочую.
procedure ScanRoot(const Root: HKEY; const RootName: String; var Found: Boolean; var BestVersion: Int64);
var
  // Имена разделов (3.11, 3.12-32 и т. п.).
  Tags: TArrayOfString;
  // Номер текущего раздела.
  I: Integer;
  // Версия текущего раздела.
  Version: Int64;
begin
  // Раздела PythonCore в этой ветке нет — значит, здесь Python не установлен.
  if not RegGetSubkeyNames(Root, PythonCoreKey, Tags) then
    // Выходим.
    Exit;
  // Перебираем все найденные версии.
  for I := 0 to GetArrayLength(Tags) - 1 do
  begin
    // Неподходящая (старая или экспериментальная) версия — пропускаем.
    if not ParsePythonTag(Tags[I], Version) then
      // Следующий раздел.
      Continue;
    // Уже нашли такую же или более новую — эту не проверяем.
    if Found and (ComparePackedVersion(Version, BestVersion) <= 0) then
      // Следующий раздел.
      Continue;
    // Проверяем Python из этого раздела.
    if TryPythonKey(Root, RootName, Tags[I]) then
    begin
      // Нашли рабочий Python.
      Found := True;
      // Запоминаем его версию для сравнения с остальными.
      BestVersion := Version;
    end;
  end;
end;

// Найти лучший установленный Python во всех ветках реестра. True — найден.
function DetectPython: Boolean;
var
  // Нашли ли хоть один подходящий.
  Found: Boolean;
  // Версия лучшего найденного.
  BestVersion: Int64;
begin
  // Сбрасываем прошлый результат.
  PythonExe := '';
  // Сбрасываем путь к pythonw.exe.
  PythonWExe := '';
  // Сбрасываем название.
  PythonTag := '';
  // Пока ничего не найдено.
  Found := False;
  // Начальная версия для сравнения.
  BestVersion := 0;
  // 64-битная Windows: реестр разделён на 64- и 32-битную части — смотрим обе.
  if IsWin64 then
  begin
    // Python, установленный «только для меня» (64-битный).
    ScanRoot(HKCU64, 'HKCU64', Found, BestVersion);
    // Python, установленный «только для меня» (32-битный).
    ScanRoot(HKCU32, 'HKCU32', Found, BestVersion);
    // Python, установленный «для всех пользователей» (64-битный).
    ScanRoot(HKLM64, 'HKLM64', Found, BestVersion);
    // Python, установленный «для всех пользователей» (32-битный).
    ScanRoot(HKLM32, 'HKLM32', Found, BestVersion);
  end
  else
  begin
    // 32-битная Windows: «только для меня».
    ScanRoot(HKCU, 'HKCU', Found, BestVersion);
    // 32-битная Windows: «для всех пользователей».
    ScanRoot(HKLM, 'HKLM', Found, BestVersion);
  end;
  // Возвращаем результат.
  Result := Found;
  // Ничего не нашли — пишем в журнал.
  if not Found then
    // Сообщение в журнал.
    Log('Подходящий Python (3.10+ с tkinter) не найден.');
end;


// ===================== Выбор установщика Python под процессор =====================

// Имя файла на python.org, его SHA-256 и название раздела реестра после установки.
procedure GetPythonInstallerInfo(var FileName, Sha256, RegistryTag: String);
begin
  // Обычные 64-битные компьютеры, а также Windows 11 на ARM (там x64 работает через эмуляцию,
  // а эта сборка Python — самая проверенная).
  if IsX64Compatible then
  begin
    // 64-битный установщик.
    FileName := 'python-' + PythonVersion + '-amd64.exe';
    // Его контрольная сумма.
    Sha256 := '{#PythonSha256Amd64}';
    // Раздел реестра: просто 3.12.
    RegistryTag := PythonBranch;
  end
  // Windows 10 на ARM (без эмуляции x64) — родная ARM64-сборка.
  else if IsArm64 then
  begin
    // ARM64-установщик.
    FileName := 'python-' + PythonVersion + '-arm64.exe';
    // Его контрольная сумма.
    Sha256 := '{#PythonSha256Arm64}';
    // Раздел реестра: 3.12-arm64.
    RegistryTag := PythonBranch + '-arm64';
  end
  // Старые 32-битные системы.
  else
  begin
    // 32-битный установщик.
    FileName := 'python-' + PythonVersion + '.exe';
    // Его контрольная сумма.
    Sha256 := '{#PythonSha256Win32}';
    // Раздел реестра: 3.12-32.
    RegistryTag := PythonBranch + '-32';
  end;
end;


// ===================== Скачивание Python =====================

// Вызывается встроенным загрузчиком примерно каждые 50 мс, пока идёт загрузка.
// Здесь работает «сторож»: если данные перестали приходить, прерываем загрузку,
// чтобы установщик никогда не «висел» бесконечно при пропавшем интернете.
function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
var
  // Текущее время в миллисекундах.
  TickNow: DWORD;
begin
  // Продолжаем загрузку, если не решим иначе.
  Result := True;
  // Узнаём текущее время.
  TickNow := GetTickCount;
  // Счётчик времени Windows переполнился (раз в 49 дней) — просто начинаем отсчёт заново.
  if TickNow < LastTick then
    // Новая точка отсчёта.
    LastTick := TickNow;
  // Пришли новые данные — запоминаем, сколько и когда.
  if Progress <> LastBytes then
  begin
    // Сколько скачано.
    LastBytes := Progress;
    // Когда пришли данные.
    LastTick := TickNow;
  end
  // Данные не приходят дольше допустимого — связь, похоже, пропала.
  else if TickNow - LastTick > StallTimeoutMs then
  begin
    // Отмечаем, что прервал сторож (сообщение будет про интернет, а не «отменено пользователем»).
    StallDetected := True;
    // Пишем в журнал.
    Log(Format('Загрузка остановилась: %d с без новых данных, прерываю.', [StallTimeoutMs div 1000]));
    // False — просим загрузчик прервать загрузку.
    Result := False;
  end;
end;

// Понятное объяснение ошибки загрузки для человека без технических знаний.
function DescribeDownloadError(const ErrorText: String): String;
var
  // Главная причина простыми словами.
  Reason: String;
begin
  // Сторож заметил, что данные перестали приходить.
  if StallDetected then
    // Объяснение «связь пропала».
    Reason := 'Скачивание остановилось: больше 45 секунд не пришло ни одного байта. Похоже, подключение к интернету прервалось или стало очень медленным.'
  // Не совпала контрольная сумма — файл повреждён или подменён.
  else if ContainsText(ErrorText, 'SHA') or ContainsText(ErrorText, 'hash') or ContainsText(ErrorText, 'хеш') or ContainsText(ErrorText, 'контрольн') then
    // Объяснение «файл испорчен».
    Reason := 'Файл скачался повреждённым (не совпала контрольная сумма), поэтому установщик не стал его запускать. Так бывает при нестабильном соединении.'
  // Типичные сетевые ошибки Windows: имя не найдено, нет соединения, тайм-аут.
  else if ContainsText(ErrorText, '12007') or ContainsText(ErrorText, '12029') or ContainsText(ErrorText, '12002') or ContainsText(ErrorText, '12030') or ContainsText(ErrorText, '12031') or ContainsText(ErrorText, 'resolve') or ContainsText(ErrorText, 'connect') or ContainsText(ErrorText, 'timed out') or ContainsText(ErrorText, 'timeout') then
    // Объяснение «нет интернета».
    Reason := 'Нет подключения к интернету, или сайт python.org сейчас недоступен.'
  else
    // Всё остальное — общее объяснение.
    Reason := 'Не удалось скачать установщик Python с сайта python.org.';
  // Собираем полный текст: причина, советы, техническая деталь (пригодится, если писать в поддержку).
  Result := Reason + CRLF + CRLF +
    'Что можно сделать:' + CRLF +
    '•  проверьте, что интернет работает (например, откройте любой сайт в браузере);' + CRLF +
    '•  в офисной сети загрузку может блокировать прокси-сервер или антивирус;' + CRLF +
    '•  нажмите «Повторить», чтобы попробовать ещё раз, или «Отмена», чтобы вернуться назад.' + CRLF + CRLF +
    'Техническая информация: ' + ErrorText;
end;

// Скачать официальный установщик Python. True — файл скачан и проверен; путь — в InstallerPath.
function DownloadPython(var InstallerPath: String): Boolean;
var
  // Имя файла на python.org.
  FileName: String;
  // Его контрольная сумма.
  Sha256: String;
  // Раздел реестра после установки (здесь не нужен, но процедура возвращает его вместе с остальным).
  RegistryTag: String;
  // Текст ошибки загрузки.
  ErrorText: String;
  // Загрузка прошла успешно.
  Success: Boolean;
  // Пользователь сам нажал «Прервать».
  Cancelled: Boolean;
  // Пора выходить из цикла повторов.
  Done: Boolean;
begin
  // По умолчанию — не скачано.
  Result := False;
  // Определяем, какой файл нужен этому компьютеру.
  GetPythonInstallerInfo(FileName, Sha256, RegistryTag);
  // Пока не решим выйти.
  Done := False;
  // Цикл повторов: пользователь может нажимать «Повторить» сколько угодно раз.
  repeat
    // Сбрасываем сторож загрузки.
    StallDetected := False;
    // Ещё ничего не скачано (-1, чтобы первый же вызов сторожа засчитался как «данные пришли»).
    LastBytes := -1;
    // Отсчёт времени — с этого момента.
    LastTick := GetTickCount;
    // Сбрасываем флаги попытки.
    Success := False;
    // Пользователь пока не отменял.
    Cancelled := False;
    // Ошибки пока нет.
    ErrorText := '';
    // Очищаем список загрузок страницы (обязательно перед добавлением файла).
    DownloadPage.Clear;
    // Добавляем файл: адрес, имя во временной папке, ожидаемая SHA-256 (проверяется автоматически).
    DownloadPage.Add(PythonDownloadUrl + FileName, FileName, Sha256);
    // Показываем страницу скачивания.
    DownloadPage.Show;
    // finally гарантирует, что страница скроется при любом исходе (иначе мастер «застрянет»).
    try
      // except ловит любые ошибки загрузки — установщик не падает.
      try
        // Скачиваем (окно при этом отзывчиво, работает кнопка «Прервать»).
        DownloadPage.Download;
        // Дошли сюда — файл скачан и контрольная сумма совпала.
        Success := True;
      except
        // Пользователь сам нажал «Прервать» (а не сторож).
        if DownloadPage.AbortedByUser and not StallDetected then
          // Запоминаем отмену.
          Cancelled := True
        else
          // Запоминаем текст ошибки.
          ErrorText := GetExceptionMessage;
      end;
    finally
      // Скрываем страницу скачивания.
      DownloadPage.Hide;
    end;
    // Успех.
    if Success then
    begin
      // Путь к скачанному файлу во временной папке установщика.
      InstallerPath := ExpandConstant('{tmp}\') + FileName;
      // Результат — успех.
      Result := True;
      // Выходим из цикла.
      Done := True;
    end
    // Пользователь отменил — тихо возвращаемся на страницу «Готово к установке».
    else if Cancelled then
    begin
      // Пишем в журнал.
      Log('Скачивание Python отменено пользователем.');
      // Выходим из цикла.
      Done := True;
    end
    // Ошибка — объясняем и предлагаем повторить (при тихой установке ответ по умолчанию — «Отмена»).
    else
    begin
      // Пишем техническую причину в журнал.
      Log('Ошибка скачивания Python: ' + ErrorText);
      // Вежливое сообщение с кнопками «Повторить» и «Отмена».
      if SuppressibleMsgBox(DescribeDownloadError(ErrorText), mbError, MB_RETRYCANCEL, IDCANCEL) <> IDRETRY then
        // Не «Повторить» — выходим из цикла.
        Done := True;
    end;
  until Done;
end;


// ===================== Тихая установка Python =====================

// Запустить скачанный установщик Python без окон. True — Python установлен и найден.
function InstallPython(const InstallerPath: String): Boolean;
var
  // Параметры установщика Python.
  Params: String;
  // Журнал установщика Python (во временной папке).
  LogPath: String;
  // Копия журнала, которая останется после закрытия мастера.
  SavedLog: String;
  // Текст сообщения об ошибке.
  Msg: String;
  // Ненужные здесь имя файла и контрольная сумма.
  FileName, Sha256: String;
  // Раздел реестра, где появится свежеустановленный Python.
  RegistryTag: String;
  // Код завершения установщика Python.
  ResultCode: Integer;
  // Удалось ли запустить установщик.
  Launched: Boolean;
  // Пора выходить из цикла повторов.
  Done: Boolean;
begin
  // По умолчанию — не установлен.
  Result := False;
  // Узнаём, в каком разделе реестра появится Python (3.12, 3.12-arm64 или 3.12-32).
  GetPythonInstallerInfo(FileName, Sha256, RegistryTag);
  // Журнал установщика Python — во временной папке мастера.
  LogPath := ExpandConstant('{tmp}\python-install.log');
  // Параметры тихой установки:
  //   /quiet               — без окон и вопросов (видна только полоса прогресса нашего мастера);
  //   InstallAllUsers=0    — только для текущего пользователя, без прав администратора;
  //   PrependPath=1        — добавить Python в PATH (команда python заработает в консоли);
  //   Include_tcltk=1      — обязательно с tkinter (на нём построен интерфейс Auto-Compiler);
  //   Include_pip=1        — с менеджером пакетов pip (нужен для установки библиотек);
  //   Include_launcher=0, AssociateFiles=0 — не ставить «py launcher»: если на компьютере уже есть
  //                          более новый, его установка завершается ошибкой, а нам он не нужен;
  //   Shortcuts=0, Include_doc=0, Include_test=0 — без лишних ярлыков, справки и тестов (быстрее);
  //   /log                 — подробный журнал на случай ошибки.
  Params := '/quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1 Include_launcher=0 AssociateFiles=0 Shortcuts=0 Include_doc=0 Include_test=0 /log "' + LogPath + '"';
  // Пока не решим выйти.
  Done := False;
  // Цикл повторов.
  repeat
    // Текст на странице установки.
    InstallPage.SetText('Устанавливаю Python ' + PythonVersion + '…', 'Обычно это занимает 1–3 минуты. Пожалуйста, не закрывайте окно.');
    // Показываем страницу с бегущей полосой.
    InstallPage.Show;
    // finally гарантирует, что страница скроется при любом исходе.
    try
      // Сразу даём окну перерисоваться.
      InstallPage.Animate;
      // Пока установка не запущена.
      Launched := False;
      // Запуск не должен ронять мастер.
      try
        // Пишем команду в журнал.
        Log('Запускаю: ' + InstallerPath + ' ' + Params);
        // Запускаем установщик Python и ждём окончания (окно мастера остаётся отзывчивым, полоса бежит).
        Launched := Exec(InstallerPath, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      except
        // Записываем ошибку в журнал.
        Log('Ошибка запуска установщика Python: ' + GetExceptionMessage);
        // Особый код «не удалось запустить».
        ResultCode := -1;
      end;
      // Пишем код завершения в журнал.
      Log(Format('Установщик Python завершился, код %d', [ResultCode]));
      // Python установлен (0 — успех, 3010 — успех, но Windows просит когда-нибудь перезагрузиться).
      if Launched and ((ResultCode = 0) or (ResultCode = 3010)) then
      begin
        // Сообщаем, что идёт проверка.
        InstallPage.SetText('Проверяю установленный Python…', '');
        // Сначала ищем именно только что установленный Python (3.12 «только для меня»)…
        if TryPythonKey(HKCU, 'HKCU', RegistryTag) then
          // …нашли его.
          Result := True
        else
          // …иначе — любой подходящий (например, если ставили «для всех пользователей»).
          Result := DetectPython;
      end;
    finally
      // Скрываем страницу установки.
      InstallPage.Hide;
    end;
    // Всё хорошо — выходим.
    if Result then
    begin
      // Выходим из цикла.
      Done := True;
    end
    else
    begin
      // Понятное объяснение по коду ошибки.
      if not Launched then
        // Не удалось даже запустить файл (например, его заблокировал антивирус).
        Msg := 'Не удалось запустить установщик Python. Возможно, его заблокировал антивирус.' + CRLF + 'Подробности: ' + SysErrorMessage(ResultCode)
      else if (ResultCode = 0) or (ResultCode = 3010) then
        // Установщик сказал «готово», но рабочего Python мы не нашли.
        Msg := 'Установщик Python завершился без ошибок, но рабочий Python с tkinter так и не появился.'
      else if ResultCode = 1602 then
        // Установку Python отменили.
        Msg := 'Установка Python была отменена.'
      else if ResultCode = 1618 then
        // Windows уже занята другой установкой (часто — обновления Windows).
        Msg := 'Сейчас в Windows уже идёт другая установка или обновление, а две установки одновременно невозможны.' + CRLF + 'Подождите несколько минут, пока она закончится, и нажмите «Повторить».'
      else if ResultCode = 1638 then
        // Уже стоит другая сборка той же ветки Python.
        Msg := 'На компьютере уже установлен Python ' + PythonBranch + ' другой сборки, и его нельзя заменить автоматически.' + CRLF + 'Удалите его в «Параметры → Приложения» (или переустановите, отметив компонент «tcl/tk and IDLE») и нажмите «Повторить».'
      else
        // Любой другой код.
        Msg := Format('Установщик Python завершился с ошибкой (код %d).', [ResultCode]);
      // Сохраняем журнал установщика Python в %TEMP%, чтобы его можно было посмотреть после закрытия мастера.
      SavedLog := AddBackslash(GetTempDir) + 'AutoCompiler-python-install.log';
      // Копируем, если журнал существует (CopyFile: False — перезаписать старую копию).
      if FileExists(LogPath) and CopyFile(LogPath, SavedLog, False) then
        // Добавляем путь к журналу в сообщение.
        Msg := Msg + CRLF + CRLF + 'Подробный журнал: ' + SavedLog;
      // Пишем в журнал мастера.
      Log('Ошибка установки Python: ' + Msg);
      // Предлагаем повторить (при тихой установке ответ по умолчанию — «Отмена»).
      if SuppressibleMsgBox(Msg + CRLF + CRLF + 'Нажмите «Повторить», чтобы попробовать ещё раз, или «Отмена», чтобы вернуться назад.', mbError, MB_RETRYCANCEL, IDCANCEL) <> IDRETRY then
        // Не «Повторить» — выходим из цикла.
        Done := True;
    end;
  until Done;
end;


// ===================== pip: установка библиотек (вызывается из секции [Run]) =====================

// Похожа ли строка вывода pip на проблему с интернетом.
function IsNetworkMessage(const Line: String): Boolean;
begin
  // Типичные сообщения pip/urllib3 при отсутствии сети, тайм-аутах, прокси и проблемах сертификатов.
  Result := ContainsText(Line, 'getaddrinfo failed') or ContainsText(Line, 'Failed to establish a new connection') or
    ContainsText(Line, 'Temporary failure in name resolution') or ContainsText(Line, 'Max retries exceeded') or
    ContainsText(Line, 'ConnectTimeout') or ContainsText(Line, 'ReadTimeout') or ContainsText(Line, 'Read timed out') or
    ContainsText(Line, 'Connection aborted') or ContainsText(Line, 'Connection reset') or ContainsText(Line, 'NewConnectionError') or
    ContainsText(Line, 'ProxyError') or ContainsText(Line, 'SSLError') or ContainsText(Line, 'CERTIFICATE_VERIFY_FAILED') or
    ContainsText(Line, 'No matching distribution found') or ContainsText(Line, 'Could not find a version that satisfies');
end;

// Перевести строку pip на понятный язык для подписи под полосой прогресса.
function FriendlyPipLine(const Line: String): String;
begin
  // pip ищет библиотеку.
  if Pos('Collecting ', Line) = 1 then
    // «Проверяю: customtkinter».
    Result := 'Проверяю: ' + Copy(Line, 12, Length(Line))
  // pip скачивает файл.
  else if Pos('Downloading ', Line) = 1 then
    // «Скачиваю: …».
    Result := 'Скачиваю: ' + Copy(Line, 13, Length(Line))
  // Файл уже есть в кэше pip.
  else if Pos('Using cached ', Line) = 1 then
    // «Беру из кэша: …».
    Result := 'Беру из кэша: ' + Copy(Line, 14, Length(Line))
  // Библиотека уже установлена.
  else if Pos('Requirement already satisfied: ', Line) = 1 then
    // «Уже установлено: …».
    Result := 'Уже установлено: ' + Copy(Line, 32, Length(Line))
  // pip устанавливает скачанное.
  else if Pos('Installing collected packages: ', Line) = 1 then
    // «Устанавливаю: …».
    Result := 'Устанавливаю: ' + Copy(Line, 32, Length(Line))
  // Всё установлено.
  else if Pos('Successfully installed ', Line) = 1 then
    // «Готово: …».
    Result := 'Готово: ' + Copy(Line, 24, Length(Line))
  else
    // Остальные строки показываем как есть.
    Result := Line;
  // Слишком длинную строку обрезаем, чтобы подпись не вылезала за окно.
  if Length(Result) > 90 then
    // Первые 87 символов и многоточие.
    Result := Copy(Result, 1, 87) + '…';
end;

// Получает КАЖДУЮ строку вывода pip (параметр OnLog в секции [Run] и повторные попытки из [Code]).
procedure PipOnLog(const S: String; const Error, FirstLine: Boolean);
var
  // Строка без пробелов по краям.
  Line: String;
begin
  // Записываем всё в журнал установки как есть.
  Log('pip: ' + S);
  // Ошибка чтения вывода (бывает крайне редко) — дальше не разбираем.
  if Error then
    // Выходим.
    Exit;
  // Убираем пробелы по краям.
  Line := Trim(S);
  // Пустые строки не интересны.
  if Line = '' then
    // Выходим.
    Exit;
  // Запоминаем строку для возможного сообщения об ошибке.
  AddToPipTail(Line);
  // Замечаем признаки проблем с интернетом.
  if IsNetworkMessage(Line) then
    // Запоминаем.
    PipNetworkError := True;
  // Показываем понятный ход установки под полосой прогресса.
  WizardForm.FilenameLabel.Caption := FriendlyPipLine(Line);
end;

// Параметры pip для повторных попыток из [Code] (те же, что и в секции [Run]).
function PipParameters: String;
begin
  // -m pip install … -r "<папка программы>\requirements.txt".
  Result := '-m pip install {#PipOptions} -r "' + ExpandConstant('{app}\requirements.txt') + '"';
end;

// Установлены ли библиотеки интерфейса на самом деле (проверяем импортом).
function LibrariesReady: Boolean;
var
  // Код завершения проверки.
  ResultCode: Integer;
begin
  // По умолчанию — нет.
  Result := False;
  // Проверка не должна ронять установщик.
  try
    // python -c "import customtkinter" — код 0, если библиотека на месте.
    if Exec(PythonExe, '-c "import {#VerifyImport}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      // Готово, только если код 0.
      Result := (ResultCode = 0);
  except
    // Пишем ошибку в журнал.
    Log('Ошибка проверки библиотек: ' + GetExceptionMessage);
  end;
  // Пишем результат в журнал.
  Log('Проверка библиотек ({#VerifyImport}): ' + IntToStr(Ord(Result)));
end;

// Перед pip (BeforeInstall в [Run]): сбрасываем состояние и убеждаемся, что pip у Python есть.
procedure BeforePipInstall;
var
  // Код завершения команд.
  ResultCode: Integer;
  // Есть ли pip.
  HasPip: Boolean;
begin
  // Очищаем «хвост» вывода прошлой попытки.
  PipTail := '';
  // Сбрасываем признак сетевой ошибки.
  PipNetworkError := False;
  // Пока не знаем, есть ли pip.
  HasPip := False;
  // Проверка не должна ронять установщик.
  try
    // python -m pip --version — код 0, если pip установлен.
    HasPip := Exec(PythonExe, '-m pip --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
    // pip нет (Python ставили без него) — ставим его из комплекта самого Python (интернет не нужен).
    if not HasPip then
    begin
      // Пишем в журнал.
      Log('pip не найден, запускаю ensurepip.');
      // Подсказка под полосой прогресса.
      WizardForm.FilenameLabel.Caption := 'Подготавливаю менеджер пакетов pip…';
      // python -m ensurepip --default-pip — встроенная установка pip.
      Exec(PythonExe, '-m ensurepip --default-pip', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  except
    // Пишем ошибку в журнал; pip install сам сообщит, если что-то не так.
    Log('Ошибка подготовки pip: ' + GetExceptionMessage);
  end;
end;

// После pip (AfterInstall в [Run]): проверяем результат и при неудаче вежливо предлагаем повторить.
procedure AfterPipInstall;
var
  // Текст сообщения.
  Msg: String;
  // Код завершения повторной попытки.
  ResultCode: Integer;
  // Пора выходить из цикла.
  Done: Boolean;
begin
  // Библиотеки уже на месте — всё хорошо.
  Done := LibrariesReady;
  // Цикл повторов, пока библиотеки не установятся или пользователь не решит пропустить.
  while not Done do
  begin
    // Главная причина простыми словами.
    if PipNetworkError then
      // Проблема с интернетом.
      Msg := 'Не удалось скачать библиотеки интерфейса: похоже, нет подключения к интернету (или его блокирует прокси/антивирус).'
    else
      // Другая проблема.
      Msg := 'Не удалось установить библиотеки интерфейса.';
    // Советы и последние строки pip (пригодятся, если писать в поддержку).
    Msg := Msg + CRLF + CRLF +
      'Нажмите «Повторить», когда интернет заработает, или «Отмена», чтобы пропустить этот шаг: программа всё равно установится и сама докачает библиотеки при первом запуске.' + CRLF + CRLF +
      'Последние сообщения pip:' + CRLF + PipTail;
    // Записываем причину в журнал установки (пригодится при разборе проблем).
    Log('Библиотеки не установлены. Сетевая ошибка: ' + IntToStr(Ord(PipNetworkError)));
    // Спрашиваем (при тихой установке ответ по умолчанию — «Отмена», то есть пропустить).
    if SuppressibleMsgBox(Msg, mbError, MB_RETRYCANCEL, IDCANCEL) = IDRETRY then
    begin
      // Очищаем «хвост» вывода.
      PipTail := '';
      // Сбрасываем признак сетевой ошибки.
      PipNetworkError := False;
      // Обновляем надпись над полосой прогресса.
      WizardForm.StatusLabel.Caption := 'Повторяю установку библиотек интерфейса…';
      // Повторный запуск не должен ронять установщик.
      try
        // Тот же pip install, вывод снова идёт в PipOnLog (консольное окно скрыто автоматически).
        ExecAndLogOutput(PythonExe, PipParameters, ExpandConstant('{app}'), SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode, @PipOnLog);
        // Пишем код в журнал.
        Log(Format('Повторный pip завершился, код %d', [ResultCode]));
      except
        // Пишем ошибку в журнал.
        Log('Ошибка повторного запуска pip: ' + GetExceptionMessage);
      end;
      // Проверяем результат.
      Done := LibrariesReady;
    end
    else
    begin
      // Пользователь решил пропустить — объясняем, что ничего страшного.
      Log('Установка библиотек пропущена пользователем.');
      // Выходим из цикла.
      Done := True;
    end;
  end;
end;


// ===================== Пути Python для секций [Icons] и [Run] =====================

// {code:GetPythonExe} — путь к python.exe.
function GetPythonExe(Param: String): String;
begin
  // Найденный или только что установленный Python.
  Result := PythonExe;
end;

// {code:GetPythonW} — путь к pythonw.exe (запуск без консольного окна).
function GetPythonW(Param: String): String;
begin
  // Найденный или только что установленный Python.
  Result := PythonWExe;
end;


// ===================== События мастера =====================

// Запуск установщика (ещё до появления окна): ищем Python.
function InitializeSetup: Boolean;
begin
  // Продолжаем установку в любом случае.
  Result := True;
  // Параметр /FORCEPYTHON=1 — всегда ставить свой Python (для автотестов).
  ForcePython := ExpandConstant('{param:FORCEPYTHON|0}') = '1';
  // Режим теста — поиск пропускаем.
  if ForcePython then
    // Пишем в журнал.
    Log('Параметр /FORCEPYTHON=1: Python ' + PythonVersion + ' будет скачан и установлен в любом случае.')
  else
    // Обычный режим — ищем подходящий Python в реестре.
    DetectPython;
end;

// Создание окна мастера: готовим страницы скачивания и установки Python.
procedure InitializeWizard;
begin
  // Страница скачивания (встроенная в Inno Setup): заголовок, пояснение, наш «сторож».
  DownloadPage := CreateDownloadPage('Скачивание Python', 'Скачиваю официальный установщик Python ' + PythonVersion + ' с сайта python.org (около 25 МБ)…', @OnDownloadProgress);
  // Показывать имя файла, а не длинный адрес.
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
  // Страница установки Python с бегущей полосой.
  InstallPage := CreateOutputMarqueeProgressPage('Установка Python', 'Python нужен для работы Auto-Compiler. Он устанавливается только для вас и не требует прав администратора.');
end;

// Текст на странице «Всё готово к установке»: честно говорим, что будет скачано.
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  // Папка установки.
  Result := MemoDirInfo + NewLine + NewLine;
  // Выбранные задачи (значок на рабочем столе).
  if MemoTasksInfo <> '' then
    // Добавляем их.
    Result := Result + MemoTasksInfo + NewLine + NewLine;
  // Заголовок про Python.
  Result := Result + 'Python:' + NewLine;
  // Python уже есть.
  if PythonExe <> '' then
    // Скачивать не нужно.
    Result := Result + Space + 'уже установлен (' + PythonTag + '), скачивать не нужно:' + NewLine + Space + PythonExe
  else
    // Будет скачан.
    Result := Result + Space + 'будет скачан с python.org (около 25 МБ) и установлен' + NewLine + Space + 'только для вас — Python ' + PythonVersion;
  // Про библиотеки.
  Result := Result + NewLine + NewLine + 'Библиотеки интерфейса:' + NewLine + Space + 'будут скачаны в конце установки (нужен интернет).';
end;

// Нажатие «Далее»/«Установить». На странице «Готово к установке» — ДО копирования файлов —
// скачиваем и ставим Python, если его нет. Неудача возвращает пользователя на эту же страницу.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  // Путь к скачанному установщику Python.
  InstallerPath: String;
begin
  // По умолчанию переходим дальше.
  Result := True;
  // Нас интересует только кнопка «Установить» и только если Python ещё не найден.
  if (CurPageID = wpReady) and (PythonExe = '') then
  begin
    // Пока считаем, что не получилось.
    Result := False;
    // Скачиваем установщик Python…
    if DownloadPython(InstallerPath) then
      // …и ставим его. Получилось — идём дальше, к копированию файлов программы.
      Result := InstallPython(InstallerPath);
    // Не получилось — остаёмся на странице «Готово к установке»; при тихой установке
    // Inno Setup в этом случае сам завершает работу с кодом ошибки (ничего не «висит»).
    if not Result then
      // Пишем в журнал.
      Log('Python не установлен — остаюсь на странице «Готово к установке».');
  end;
end;


// ===================== Удаление программы =====================

// Этапы удаления: в самом конце предлагаем убрать и рабочие файлы программы.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  // Папка рабочих файлов Auto-Compiler (кэш загрузок, временные файлы сборки).
  DataDir: String;
begin
  // Действуем только после удаления основных файлов.
  if CurUninstallStep = usPostUninstall then
  begin
    // %LOCALAPPDATA%\AutoCompiler.
    DataDir := ExpandConstant('{localappdata}\AutoCompiler');
    // Папка есть — спрашиваем (по умолчанию «Нет»; при тихом удалении тоже «Нет»).
    if DirExists(DataDir) then
      // Вопрос пользователю.
      if SuppressibleMsgBox('Удалить также рабочие файлы Auto-Compiler (кэш загрузок и временные файлы сборки)?' + CRLF + CRLF + DataDir + CRLF + CRLF + 'Ваши скрипты и собранные программы .exe не будут затронуты. Python тоже останется на компьютере.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
        // Удаляем папку целиком (со всеми вложенными папками).
        DelTree(DataDir, True, True, True);
  end;
end;
