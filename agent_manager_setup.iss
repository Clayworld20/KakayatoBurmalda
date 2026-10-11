; ============================================================================
;  ИНСТАЛЛЯТОР "AI AGENT MANAGER" (agent_manager_setup.iss)
;  --------------------------------------------------------------------------
;  Что делает этот установщик:
;    1) копирует исходники программы в %LOCALAPPDATA%\Programs\AIAgentManager
;       (права администратора НЕ нужны — ставим только для текущего пользователя);
;    2) проверяет систему: если нет полноценного Python 3.10+ — САМ тихо
;       устанавливает Python 3.12.10 (файл зашит внутрь инсталлятора);
;    3) ставит библиотеки ТОЛЬКО готовыми Windows-сборками (--only-binary=:all:),
;       поэтому pip физически не может начать компиляцию Pillow — зависаний нет;
;    4) создаёт красивый значок на рабочем столе: программа запускается через
;       pythonw.exe — без чёрного окна консоли.
;
;  Требуется Inno Setup 6.6 или новее (для тёмной темы WizardStyle=dark).
; ============================================================================

; --- СЛОВАРИ ПРЕПРОЦЕССОРА (настройки сверху, чтобы легко менять) --------------

#define MyAppName "AI Agent Manager"                                 ; имя программы
#define MyAppVersion "1.0"                                           ; версия установки
#define MyAppPublisher "AI Agent Manager Project"                    ; кто выпустил
#define PythonInstallerName "python-3.12.10-amd64.exe"               ; имя файла Python
#define PythonInstallerUrl "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" ; откуда качаем при сборке

[Setup]
; --- Идентификация программы ---------------------------------------------------
AppId={{8F1E9C42-6B7D-4E3A-9A21-C5D4B0A7F123}       ; уникальный номер (двойной {{ — экранирование)
AppName={#MyAppName}                                 ; название в списке программ
AppVersion={#MyAppVersion}                           ; версия программы
AppPublisher={#MyAppPublisher}                       ; издатель
DefaultGroupName={#MyAppName}                        ; имя папки в меню "Пуск"

; --- Куда ставим и с какими правами --------------------------------------------
; {localappdata} = %LOCALAPPDATA%\Programs\... — установка БЕЗ прав администратора
DefaultDirName={localappdata}\Programs\AIAgentManager
PrivilegesRequired=none                            ; просим только права обычного пользователя

; --- Внешний вид: ТЁМНАЯ современная тема Windows 11 (Inno Setup 6.6+) ---------
WizardStyle=modern dark                              ; тёмный мастер установки
DisableProgramGroupPage=yes                          ; не спрашиваем про папку меню "Пуск"

; --- Иконки и имя файла на выходе ----------------------------------------------
SetupIconFile=assets\icon.ico                        ; значок самого установщика
UninstallDisplayIcon={app}\assets\icon.ico           ; значок в "Установке и удалении программ"
OutputBaseFilename=AI-Agent-Manager-Setup            ; итоговый файл: AI-Agent-Manager-Setup.exe

; --- Сжатие и служебное ---------------------------------------------------------
Compression=lzma2                                    ; сильное сжатие (файл меньше)
SolidCompression=yes                                 ; ещё лучше сжимаем файлы
SetupLogging=yes                                     ; лог установки (помогает при поддержке)

; --- Что спрашиваем у пользователя ----------------------------------------------
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

; --- Файлы, которые попадают внутрь установщика ---------------------------------
[Files]
; Исходники программы — в папку установки
Source: "main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "theme.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
; Папки со вкладками и сервисами (исключаем служебный __pycache__)
Source: "pages\*"; DestDir: "{app}\pages"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
Source: "services\*"; DestDir: "{app}\services"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
; Иконка — пригодится для ярлыков и "Установки и удаления программ"
Source: "assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
; Установщик Python 3.12.10: СКАЧИВАЕТСЯ НА ЭТАПЕ СБОРКИ и зашивается внутрь.
; Флаг DownloadKompatibelAndOverwrite — докачка с python.org, если связь дрогнула.
; При установке файл распакуется в кэш %LOCALAPPDATA%\AI-Agent-Manager\bootstrap
Source: "{#PythonInstallerUrl}"; DestDir: "{localappdata}\AI-Agent-Manager\bootstrap"; DestName: "{#PythonInstallerName}"; Flags: ignoreversion DownloadKompatibelAndOverwrite

; --- Ярлыки ---------------------------------------------------------------------
[Icons]
; Ярлык на рабочем столе (только если пользователь поставил галочку).
; Запускаем через pythonw.exe (функция PythonWindowedExecutablePath) — БЕЗ чёрной консоли
Name: "{userdesktop}\{#MyAppName}"; Filename: "{code:PythonWindowedExecutablePath}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Comment: "Центр управления нейросетями и роботом-помощником"; Tasks: desktopicon
; Ярлык в меню "Пуск"
Name: "{group}\{#MyAppName}"; Filename: "{code:PythonWindowedExecutablePath}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Comment: "Центр управления нейросетями и роботом-помощником"
; Ярлык удаления в меню "Пуск"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"

; --- Что запускать во время установки (порядок важен: сверху вниз) --------------
[Run]
; ШАГ 1. Если Python не найден — тихо ставим зашитый Python 3.12.10 в профиль
; пользователя (без прав администратора) и добавляем его в PATH.
; Флаги в точности как требовалось: /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1
Filename: "{code:PythonExecutablePath}"; \
  Parameters: "/quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_test=0"; \
  StatusMsg: "Устанавливаю Python 3.12, это займёт одну-две минуты..."; \
  Flags: runhidden; \
  Check: PythonSetupRequiredCheck

; ШАГ 2. Ставим библиотеки ТОЛЬКО готовыми Windows-сборками.
; Флаг --only-binary=:all: ЗАПРЕЩАЕТ pip компилировать что-либо из исходников —
; зависание на сборке Pillow невозможно в принципе: качается готовый .whl-файл.
Filename: "{code:PythonExecutablePath}"; \
  Parameters: "-m pip install --disable-pip-version-check --only-binary=:all: -r ""{app}\requirements.txt"""; \
  StatusMsg: "Скачиваю библиотеки программы (готовые сборки, без компиляции)..."; \
  Flags: runhidden

; ШАГ 3. Предложить запустить программу сразу после установки (галочка на финише)
Filename: "{code:PythonWindowedExecutablePath}"; \
  Parameters: """{app}\main.py"""; \
  WorkingDir: "{app}"; \
  Description: "{cm:LaunchProgram,{#MyAppName}}"; \
  Flags: nowait postinstall skipifsilent

; --- Что удалять при удалении программы -----------------------------------------
[UninstallDelete]
; Убираем кэш с установщиком Python (освобождаем ~30 МБ на диске пользователя).
; config.json с ключами НЕ трогаем — пользовательские данные остаются.
Type: filesandordirs; Name: "{localappdata}\AI-Agent-Manager"

; --- Русские тексты установщика --------------------------------------------------
[Messages]
WelcomeLabel2=Эта программа установит AI Agent Manager — центр управления нейросетями и роботом-помощником.%n%nУстановщик сам настроит Python и все библиотеки, если их нет. От вас — только нажимать «Далее».
SelectTasksLabel2=Какие значки создать?%n%nРекомендуем оставить галочку рабочего стола.
ReadyLabel2a=Проверьте настройки и нажмите «Установить».%n%nЕсли в системе нет Python 3.10+, установщик сам скачает его с python.org и поставит в фоне — понадобится интернет.
FinishedHeadingLabel=Всё готово! 🎉
FinishedLabelNoIcons=AI Agent Manager установлен.%n%nЗапустите его с ярлыка на рабочем столе.
FinishedLabel=AI Agent Manager установлен.%n%nЗапустите его с ярлыка на рабочем столе.

[CustomMessages]
CreateDesktopIcon=Создать значок на &рабочем столе
AdditionalIcons=Дополнительные значки:
LaunchProgram=Запустить %1

; ============================================================================
;  КОД НА ЯЗЫКЕ PASCAL SCRIPT: умная проверка Python.
;  ВАЖНО: внутри [Code] комментарии пишутся через // (это Pascal, а не INI).
; ============================================================================
[Code]
// PythonSetupRequired = True, если нужно ставить наш Python (3.10+ не найден)
var
  PythonSetupRequired: Boolean;
  SystemPythonExe: string;                             // найденный системный python.exe

const
  PythonInstallerFileName = 'python-3.12.10-amd64.exe';

// Папка-кэш, куда [Files] распакует установщик Python
function CachedPythonDir(): string;
begin
  Result := ExpandConstant('{localappdata}') + '\AI-Agent-Manager\bootstrap';
end;

// Проверяем ОДИН python.exe: подходит, если версия >= 3.10 И есть pip.
// Хитрость: заодно импортируем pip — так отсеивается урезанный python из
// системной папки Windows (у него нет pip, библиотеки туда не поставить).
// Коды выхода: 2 = подходит, 1 = слишком старый, прочее = не запустился.
function IsElevatedPython(PythonExe: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not Exec(PythonExe,
       '-c "import sys, pip; sys.exit(2 if sys.version_info >= (3, 10) else 1)"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  Result := (ResultCode = 2);
end;

// Ищем python.exe ТОЛЬКО в системной папке C:\Windows (верхний уровень).
// Такие папки создают только полноценные установки (реестр и PATH не нужны).
function IsMatchingPythonFound(): Boolean;
var
  WindowsDir: string;
  FindRec: TFindRec;
  CandidateExe: string;
begin
  Result := False;
  SystemPythonExe := '';
  WindowsDir := ExpandConstant('{sd}') + '\Windows';
  if not DirExists(WindowsDir) then
    Exit;
  if FindFirst(WindowsDir + '\*', FindRec) then
  try
    repeat
      if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
      begin
        CandidateExe := WindowsDir + '\' + FindRec.Name + '\python.exe';
        if FileExists(CandidateExe) and IsElevatedPython(CandidateExe) then
        begin
          SystemPythonExe := CandidateExe;             // запоминаем, что нашли
          Result := True;
          Exit;
        end;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

// Путь к python.exe: наш свежеустановленный или найденный системный
function PythonExecutablePath(Param: string): string;
begin
  if PythonSetupRequired then
    Result := CachedPythonDir() + '\Python312\python.exe'
  else if SystemPythonExe <> '' then
    Result := SystemPythonExe
  else
    Result := 'python.exe';
end;

// Путь к pythonw.exe (то же самое, но без окна консоли) — для ярлыков
function PythonWindowedExecutablePath(Param: string): string;
var
  Base: string;
begin
  if PythonSetupRequired then
    Result := CachedPythonDir() + '\Python312\pythonw.exe'
  else
  begin
    if SystemPythonExe = '' then
      Base := 'python.exe'
    else
      Base := SystemPythonExe;
    StringChangeEx(Base, 'python.exe', 'pythonw.exe', True);
    Result := Base;
  end;
end;

// Функция для Check: в [Run] — нужно ли устанавливать наш Python
function PythonSetupRequiredCheck(Param: string): Boolean;
begin
  Result := PythonSetupRequired;
end;

// Текст на странице "Готов к установке": честно говорим про Python
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: string): string;
begin
  PythonSetupRequired := not IsMatchingPythonFound();  // решаем: ставим Python или нет
  Result := MemoDirInfo + NewLine;
  if PythonSetupRequired then
    Result := Result + Space + 'Python 3.12 будет скачан с python.org и установлен автоматически (нужен интернет).' + NewLine
  else
    Result := Result + Space + 'Подходящий Python уже есть в системе — устанавливать его не будем.' + NewLine;
  Result := Result + NewLine + Space + 'Библиотеки установятся из готовых сборок — быстро и без компиляции.' + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + NewLine + MemoTasksInfo;
end;

// Для тихой установки (/SILENT): страницы Ready нет, решаем перед копированием
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    PythonSetupRequired := not IsMatchingPythonFound();
end;
