; ============================================================================
;  ИНСТАЛЛЯТОР "AI AGENT MANAGER" (agent_manager_setup.iss) — версия 2, надежная
;  --------------------------------------------------------------------------
;  Что делает установщик:
;    1) копирует программу в %LOCALAPPDATA%\Programs\AIAgentManager (без админа);
;    2) если нет Python 3.10+ — тихо ставит Python 3.12.10, который ЛЕЖИТ ВНУТРИ
;       установщика (файл bootstrap\python-3.12.10-amd64.exe — его при сборке
;       кладет GitHub Actions, скачав с python.org);
;    3) ставит библиотеки только готовыми сборками (--only-binary=:all:) —
;       компиляция Pillow и зависания невозможны;
;    4) создает значок на рабочем столе, запуск через pythonw.exe (без консоли).
; ============================================================================

; --- НАСТРОЙКИ (без комментариев в строке — препроцессор их не любит) -----------

#define MyAppName "AI Agent Manager"
#define MyAppVersion "1.1"
#define MyAppPublisher "AI Agent Manager Project"

[Setup]
; --- Идентификация программы ---
AppId={{8F1E9C42-6B7D-4E3A-9A21-C5D4B0A7F123}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultGroupName={#MyAppName}
; --- Установка в папку пользователя, БЕЗ прав администратора ---
DefaultDirName={localappdata}\Programs\AIAgentManager
PrivilegesRequired=none
; --- ТЕМНАЯ тема Windows 11 (требуется Inno Setup 6.6+) ---
WizardStyle=modern dark
DisableProgramGroupPage=yes
; --- Значки и имя файла на выходе ---
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
OutputBaseFilename=AI-Agent-Manager-Setup
; --- Сжатие и журнал ---
Compression=lzma2
SolidCompression=yes
SetupLogging=yes

; --- Вопросы пользователю: только значок на рабочий стол ---
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

; --- Файлы внутри установщика ---
[Files]
; Сама программа
Source: "main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "theme.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
; Папки со вкладками и сервисами (без служебного __pycache__)
Source: "pages\*"; DestDir: "{app}\pages"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
Source: "services\*"; DestDir: "{app}\services"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
; Значок
Source: "assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
; Установщик Python: обычный ЛОКАЛЬНЫЙ файл из папки bootstrap.
; Распаковывается во временную папку и удаляется после установки.
Source: "bootstrap\python-3.12.10-amd64.exe"; DestDir: "{tmp}"; DestName: "python-3.12.10-amd64.exe"; Flags: ignoreversion deleteafterinstall

; --- Ярлыки ---
[Icons]
; На рабочий стол (если пользователь оставил галочку); pythonw.exe = без консоли
Name: "{userdesktop}\{#MyAppName}"; Filename: "{code:PythonWExe}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Comment: "Центр управления нейросетями и роботом-помощником"; Tasks: desktopicon
; В меню "Пуск"
Name: "{group}\{#MyAppName}"; Filename: "{code:PythonWExe}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Comment: "Центр управления нейросетями и роботом-помощником"
; Удаление программы
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"

; --- Шаги установки (выполняются строго сверху вниз) ---
[Run]
; ШАГ 1: если Python 3.10+ не найден — тихо ставим свой Python в профиль пользователя
Filename: "{tmp}\python-3.12.10-amd64.exe"; \
  Parameters: "/quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_test=0"; \
  StatusMsg: "Устанавливаю Python 3.12, это займет одну-две минуты..."; \
  Flags: runhidden; \
  Check: NeedInstallPython

; ШАГ 2: библиотеки — только готовые Windows-сборки, флаг --user ставит их
; в папку пользователя, поэтому не нужны права администратора
Filename: "{code:PythonExe}"; \
  Parameters: "-m pip install --disable-pip-version-check --user --only-binary=:all: -r ""{app}\requirements.txt"""; \
  StatusMsg: "Скачиваю библиотеки программы (готовые сборки, без компиляции)..."; \
  Flags: runhidden

; ШАГ 3: галочка "Запустить программу" на финише
Filename: "{code:PythonWExe}"; \
  Parameters: """{app}\main.py"""; \
  WorkingDir: "{app}"; \
  Description: "{cm:LaunchProgram,{#MyAppName}}"; \
  Flags: nowait postinstall skipifsilent

; --- Русские тексты мастера установки ---
[Messages]
WelcomeLabel2=Эта программа установит AI Agent Manager — центр управления нейросетями и роботом-помощником.%n%nУстановщик сам настроит Python и все библиотеки, если их нет. От вас — только нажимать «Далее».
ReadyLabel2a=Проверьте настройки и нажмите «Установить».%n%nЕсли в системе нет Python 3.10+, он будет установлен автоматически (файл уже внутри установщика, интернет нужен только для библиотек).
FinishedHeadingLabel=Всё готово!
FinishedLabelNoIcons=AI Agent Manager установлен.%n%nЗапустите его с ярлыка на рабочем столе.
FinishedLabel=AI Agent Manager установлен.%n%nЗапустите его с ярлыка на рабочем столе.

[CustomMessages]
CreateDesktopIcon=Создать значок на &рабочем столе
AdditionalIcons=Дополнительные значки:
LaunchProgram=Запустить %1

; ============================================================================
;  КОД НА PASCAL: ищем подходящий Python (в [Code] комментарии только //)
; ============================================================================
[Code]
// NeedPython — True, если свой Python надо ставить; FoundPython — путь к найденному
var
  NeedPython: Boolean;
  FoundPython: string;

// Проверяем один python.exe: файл существует и внутри есть pip (import pip = 0)
function IsWorkingPython(const PythonExe: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not FileExists(PythonExe) then
    Exit;
  Result := Exec(PythonExe, '-c "import pip"', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

// Ищем Python в известных местах: наша прошлая установка и системные папки.
// Имена папок уже гарантируют версии 3.10-3.12, поэтому проверяем только pip.
function FindGoodPython(): string;
var
  Candidates: array of string;
  I: Integer;
begin
  Result := '';
  SetArrayLength(Candidates, 6);
  // Наш Python из прошлой установки этой же программы
  Candidates[0] := ExpandConstant('{localappdata}') + '\Programs\Python\Python312\python.exe';
  Candidates[1] := ExpandConstant('{localappdata}') + '\Programs\Python\Python311\python.exe';
  Candidates[2] := ExpandConstant('{localappdata}') + '\Programs\Python\Python310\python.exe';
  // Системные установки (старый стиль установки "для всех пользователей")
  Candidates[3] := ExpandConstant('{sd}') + '\Windows\Python312\python.exe';
  Candidates[4] := ExpandConstant('{sd}') + '\Windows\Python311\python.exe';
  Candidates[5] := ExpandConstant('{sd}') + '\Windows\Python310\python.exe';
  for I := 0 to 5 do
  begin
    if IsWorkingPython(Candidates[I]) then
    begin
      Result := Candidates[I];
      Exit;
    end;
  end;
end;

// Заполняем переменные ДО начала установки (работает и для тихого режима)
procedure DetectPython();
begin
  FoundPython := FindGoodPython();
  NeedPython := (FoundPython = '');
end;

// Страница "Готов к установке": решаем про Python и показываем это человеку
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: string): string;
begin
  DetectPython();
  Result := MemoDirInfo + NewLine;
  if NeedPython then
    Result := Result + Space + 'Python 3.12 будет установлен автоматически (файл уже внутри установщика).' + NewLine
  else
    Result := Result + Space + 'Подходящий Python уже есть в системе — ставить его не будем.' + NewLine;
  Result := Result + NewLine + Space + 'Библиотеки установятся из готовых сборок — быстро и без компиляции.' + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + NewLine + MemoTasksInfo;
end;

// Для тихой установки (/SILENT): страницы Ready нет, определяем перед копированием
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    DetectPython();
end;

// Проверка для [Run]: устанавливать ли наш Python
function NeedInstallPython(Param: string): Boolean;
begin
  Result := NeedPython;
end;

// Путь к python.exe (наш свежий или найденный в системе)
function PythonExe(Param: string): string;
begin
  if NeedPython then
    Result := ExpandConstant('{localappdata}') + '\Programs\Python\Python312\python.exe'
  else
    Result := FoundPython;
end;

// Путь к pythonw.exe — тот же Python, но без окна консоли (для ярлыков)
function PythonWExe(Param: string): string;
begin
  Result := PythonExe('');
  StringChangeEx(Result, 'python.exe', 'pythonw.exe', True);
end;
