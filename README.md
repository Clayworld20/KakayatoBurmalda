# KakayatoBurmalda — робот-погрузчик и сортировка кубиков

Физический симулятор на Unity 2022.3: робот-погрузчик ездит по площадке, поднимает
цветные кубики вилами и раскладывает их по зонам сортировки. За правильный кубик
начисляются очки, за неправильный — ошибка (и опционально штраф).

## Скрипты

| Файл | Назначение |
| --- | --- |
| `Assets/Scripts/ForkliftController.cs` | Физический контроллер погрузчика: движение (`Rigidbody` + силовое рулевое управление), подъём/опускание вил, наклон мачты, удержание кубиков на вилах, визуальные колёса. |
| `Assets/Scripts/CubeProperty.cs` | Свойства кубика: `enum CubeColor` (Red/Green/Blue/Yellow), очки, регистрация в менеджере, пометка «отсортирован», удаление/отключение физики. |
| `Assets/Scripts/SortingZone.cs` | Зона сортировки (`IsTrigger`): целевой тип кубика, зачёт в `OnTriggerEnter`, отклонение чужого кубика, события для VFX/звука. |
| `Assets/Scripts/GameManager.cs` | Единый менеджер: счётчик отсортированных кубиков и очки в консоль, реестр кубиков, ошибки, события для UI, конец уровня. |
| `Assets/Scripts/UI/GameUIController.cs` | HUD: очки, «отсортировано X / N», остаток кубиков, счётчик ошибок, таймер ММ:СС и панель «Уровень завершён». Работает со стандартным Unity UI Text и (опционально) с TextMeshPro. |
| `Assets/Scripts/Editor/DemoSceneGenerator.cs` | Генератор демо-сцены (`EditorWindow` + пункт меню): собирает площадку, погрузчик с вилами, 3 зоны сортировки, кубики, `GameManager` и HUD, автоматически назначая все ссылки в инспекторах. |

Рантайм-скрипты лежат в пространстве имён `KakayatoBurmalda.Forklift`,
редакторный генератор — в `KakayatoBurmalda.Forklift.EditorTools`.

## Быстрый старт

1. Откройте проект в Unity **2022.3 LTS**.
2. Меню **Tools → Generate Forklift Demo Scene** — сцена соберётся в один клик
   (создаётся новая сцена с площадкой, погрузчиком, 9 кубиками, 3 зонами, `GameManager` и HUD).
3. Нажмите **Play**.

Тонкая настройка — в окне **Tools → Kakayato → Открыть окно генератора демо-сцены**:
создавать ли новую сцену, сколько кубиков каждого цвета, теги/слои/материалы/HUD,
сохранение сцены в файл (`Assets/Scenes/ForkliftDemo.unity` по умолчанию) и привязка камеры
к погрузчику. Всё, что создаёт генератор, зарегистрировано в Undo (Ctrl+Z), а пункт
**Tools → Kakayato → Удалить демо-объекты со сцены** убирает сгенерированное.

Что создаёт генератор:

```
DemoScene
  ├── Ground                      — площадка 60×60 (BoxCollider + материал, слой Ground)
  ├── Forklift                    — Rigidbody + BoxCollider + ForkliftController, тег Forklift
  │     ├── Body / Cabin / OverheadGuard / Mast   — декоративные меши без коллайдеров
  │     ├── MastTiltPivot → ForkCarriage          — каретка вил (2 BoxCollider) + меши вил
  │     ├── GroundCheck                           — точка проверки заземления
  │     └── Wheel_FL/FR/RL/RR → Tire              — визуальные колёса (цилиндры)
  ├── ForkliftResetPoint          — точка сброса погрузчика (клавиша R)
  ├── SortingZone_Red / _Green / _Blue — триггерные зоны 5×1.6×5 с материалами цвета
  ├── Cubes                       — 9 кубиков (по 3 цвета): Rigidbody + BoxCollider + CubeProperty
  ├── GameManager                 — менеджер игры
  └── GameCanvas                  — HUD с GameUIController (Canvas + CanvasScaler)
        ├── ScoreText / SortedText / RemainingText / MistakesText / TimerText / HintText
        └── LevelCompletedPanel (скрыта до конца уровня)
```

Материалы сохраняются в `Assets/Demo/Materials` (шейдер выбирается автоматически:
URP/Lit → Standard). Теги (`Forklift`, `Cube`, `SortingZone`, `Ground`) и слои
(`Ground`, `Cube`) создаются автоматически, если их нет.

## Управление (по умолчанию)

| Клавиша | Действие |
| --- | --- |
| `W` / `S` | вперёд / назад |
| `A` / `D` | поворот влево / вправо |
| `LeftShift` / `LeftCtrl` | подъём / опускание вил |
| `Q` / `E` | наклон мачты вперёд (вилы вниз) / назад (вилы вверх) |
| `Space` | ручной тормоз |
| `R` | сброс погрузчика (выровнять и вернуть на стартовую точку) |

Ввод читается старым `Input Manager`. Если в проекте включён только новый Input System
(`Project Settings → Player → Active Input Handling = Input System Package`), клавиатура не
читается — в контроллере есть API для внешнего ввода: `SetInput(throttle, steer, lift, tilt, handbrake)`,
`SetLiftInput(lift)`, `ClearInput()`. Рекомендуется поставить `Both`.

## HUD и TextMeshPro

`GameUIController` подписывается на события `GameManager` в `OnEnable`/`Start`
(`OnScoreChanged`, `OnCubeSorted`, `OnCubeMisplaced`, `OnLevelCompleted`) и обязательно
отписывается в `OnDisable`/`OnDestroy`. Обновляемые поля: очки, «отсортировано X / N»,
сколько кубиков осталось, счётчик ошибок и таймер в формате ММ:СС (таймер замирает
после завершения уровня). Панель «Уровень завершён» появляется по событию с плавным
затуханием через `CanvasGroup`.

Поддерживаются оба варианта текста:

* **UnityEngine.UI.Text** — работает всегда;
* **TextMeshPro** — включается директивой `TMP_PRESENT`. В проекте без asmdef Unity не
  определяет её автоматически, поэтому проще всего нажать кнопку
  **Tools → Kakayato → Включить поддержку TextMeshPro в HUD** (или `Tools → Generate Forklift
  Demo Scene` → та же кнопка в окне): директива добавится в Scripting Define Symbols и
  `GameUIController` покажет поля TMP, а генератор создаст HUD на TMP. Вручную то же самое
  делается в `Project Settings → Player → Other Settings → Scripting Define Symbols`.

Поля ссылок в инспекторе — это `LabelBinding`, поэтому у каждой метки можно назначить
и `Text`, и `TMP_Text` одновременно (текст пишется в оба).

## Сборка сцены вручную

Если генератор не нужен, объекты собираются руками:

1. **Forklift** — пустышка с `Rigidbody` (mass ≈ 900, drag ≈ 0.05, angular drag ≈ 4,
   collision detection = Continuous Speculative) + `BoxCollider` корпуса + `ForkliftController`.
   * `Body` — меш корпуса.
   * `GroundCheck` — пустышка у днища корпуса → поле **Ground Check**.
   * `Mast` → `MastTiltPivot` (шарнир в нижней части мачты) → `ForkCarriage` (вилы: `BoxCollider`'ы +
     меши вил). Полю **Fork Carriage** — каретку, **Mast Tilt Pivot** — шарнир.
   * `Wheel_FL/FR/RL/RR` — визуальные колёса (Rigidbody не нужен) → массив **Wheel Visuals**.
   * Диапазон высоты вил: **Fork Min Height / Fork Max Height** (локальный Y каретки).
2. **Cube** — `Rigidbody` + `BoxCollider` + `CubeProperty`. В инспекторе выбрать **Cube Type**
   (Red/Green/Blue/Yellow) и **Score Value**. Кубики с типом `None` не засчитываются нигде.
3. **Зоны** — `SortingZone_Red`, `SortingZone_Green`, …: `BoxCollider` с галочкой **Is Trigger**
   и компонент `SortingZone` с полем **Target Type**. По желанию: **Score Per Cube**
   (0 = брать очки из кубика), **Require Forklift Delivery** (зачёт только если кубик на вилах),
   **Wrong Type Penalty** (штраф за чужой кубик).
4. **GameManager** — пустышка `GameManager` с одноимённым компонентом.

## Как это работает

* **Движение.** Один динамический `Rigidbody` на корне. Тяга — `AddForce(ForceMode.Acceleration)`
  с линейным падением к максимальной скорости, поворот — прямая запись `angularVelocity.y` с
  ограничением ускорения, боковое скольжение гасится «сцеплением колёс», от опрокидывания
  работают прижимная сила от скорости и выравнивающий момент. Задний ход инвертирует руль,
  на месте погрузчик разворачивается медленнее.
* **Вилы.** Высоту хранит каретка: цель меняется с постоянной скоростью (`forkSpeed`), текущее
  значение догоняет её кадронезависимым `Lerp` и пишется в `localPosition.y` с ограничением
  `[forkMinHeight, forkMaxHeight]`. У каретки есть `BoxCollider`, поэтому вилы реально поднимают
  кубики физикой, а не «приклеивают» их скриптом.
* **Кубики на вилах.** В `FixedUpdate` контроллер ищет кубики в объёме вил
  (`Physics.OverlapBoxNonAlloc`) и подмешивает им горизонтальную скорость корпуса, чтобы груз
  не слетал на поворотах. Флаг `IsCarryingCube` / `IsCarrying(cube)` доступен снаружи,
  а `ForkliftController.IsCubeCarriedByAnyForklift(cube)` использует зона сортировки.
* **Зона сортировки.** `OnTriggerEnter` находит `CubeProperty` (в том числе на дочерних
  коллайдерах), сверяет тип. Совпал — кубик засчитывается (`GameManager.ReportCubeSorted`),
  помечается `MarkAsSorted()`, его физика отключается и объект уничтожается (либо
  деактивируется — настраивается в `CubeProperty`). Не совпал — `Debug.LogWarning`,
  событие и опциональные штраф/отбрасывание.
* **Менеджер.** `GameManager.Instance` — синглтон с событиями `OnScoreChanged`, `OnCubeSorted`,
  `OnCubeMisplaced`, `OnLevelCompleted`. Счётчик правильно отсортированных кубиков:
  `SortedCubesCount`, остаток — `RemainingCubesCount`.

## Требования

* Unity **2022.3 LTS** (скрипты используют `Rigidbody.velocity`, `Physics.OverlapBoxNonAlloc`
  и старый `Input Manager` — всё актуально для 2022 LTS).
* Пакеты не требуются: `GameManager`, зоны, кубики и контроллер компилируются в сборке по
  умолчанию (`Assembly-CSharp`). Для HUD нужен модуль UI (входит в стандартный манифест),
  TextMeshPro — опционален.
* Все файлы сохранены в UTF-8 с BOM (важно для кириллицы в строках `Debug.Log` на Windows).

---

Вот такой хаммам мам мам я банан нан нан чемодан дан дан ам ам ам ам ам
