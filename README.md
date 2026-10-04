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

Все скрипты лежат в пространстве имён `KakayatoBurmalda.Forklift`.

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

## Сборка сцены

1. **Forklift** — пустышка с `Rigidbody` (mass ≈ 900, drag ≈ 0, angular drag ≈ 4,
   collision detection = Continuous Speculative) + `BoxCollider` корпуса + `ForkliftController`.
   * `Body` — меш корпуса.
   * `GroundCheck` — пустышка у самого днища (чуть ниже коллайдера корпуса) → поле **Ground Check**.
   * `Mast` → `MastTiltPivot` (шарнир в нижней части мачты) → `ForkCarriage` (вилы: `BoxCollider` +
     меш вил). Полю **Fork Carriage** — каретку, **Mast Tilt Pivot** — шарнир.
   * `Wheel_FL/FR/RL/RR` — визуальные колёса (Rigidbody не нужен) → массив **Wheel Visuals**
     (для передних включите `Steerable`, укажите радиус).
   * Диапазон высоты вил: **Fork Min Height / Fork Max Height** (локальный Y каретки).
2. **Cube** — `Rigidbody` + `BoxCollider` + `CubeProperty`. В инспекторе выбрать **Cube Type**
   (Red/Green/Blue/Yellow) и **Score Value**. Кубики, которым не назначен тип (`None`),
   не засчитываются нигде.
3. **Зоны** — три-четыре объекта `SortingZone_Red`, `SortingZone_Green`, …:
   * `BoxCollider` с галочкой **Is Trigger**;
   * компонент `SortingZone`, поле **Target Type** = соответствующий цвет;
   * по желанию: **Score Per Cube** (0 = брать очки из кубика), **Require Forklift Delivery**
     (зачёт только если кубик лежит на вилах), **Wrong Type Penalty** (штраф за чужой кубик).
4. **GameManager** — пустышка `GameManager` с одноимённым компонентом. Счёт и статистика
   видны в инспекторе, дублируются в консоль (`Debug.Log`) после каждого кубика и в конце уровня.

## Как это работает

* **Движение.** Один динамический `Rigidbody` на корне. Тяга — `AddForce(ForceMode.Acceleration)`
  с линейным падением к максимальной скорости, поворот — прямая запись `angularVelocity.y` с
  ограничением ускорения, боковое скольжение гасится «сцеплением колёс», от опрокидывания
  работают прижимная сила от скорости и выравнивающий момент. Задний ход инвертирует руль,
  на месте погрузчик разворачивается медленнее.
* **Вилы.** Высоту хранит каретка: цель меняется с постоянной скоростью (`forkSpeed`), текущее
  значение догоняет её кадронезависимым `Lerp` и пишется в `localPosition.y` с ограничением
  `[forkMinHeight, forkMaxHeight]`. Так как у каретки есть `BoxCollider`, вилы реально поднимают
  кубики физикой.
* **Кубики на вилах.** В `FixedUpdate` контроллер ищет кубики в объёме вил
  (`Physics.OverlapBoxNonAlloc`) и подмешивает им горизонтальную скорость корпуса, чтобы груз
  не слетал на поворотах. Флаг `IsCarryingCube` / `IsCarrying(cube)` доступен снаружи,
  а `ForkliftController.IsCubeCarriedByAnyForklift(cube)` использует зона сортировки.
* **Зона сортировки.** `OnTriggerEnter` находит `CubeProperty` (в том числе на дочерних
  коллайдерах), сверяет тип. Совпал — кубик засчитывается (`GameManager.ReportCubeSorted`),
  помечается `MarkAsSorted()`, его физика отключается и объект уничтожается (либо
  деактивируется — настраивается в `CubeProperty`). Не совпал — `Debug.LogWarning`,
  событие и опциональный штраф/отбрасывание.
* **Менеджер.** `GameManager.Instance` — синглтон с событиями `OnScoreChanged`, `OnCubeSorted`,
  `OnCubeMisplaced`, `OnLevelCompleted`. Счётчик правильно отсортированных кубиков:
  `SortedCubesCount`, остаток — `RemainingCubesCount`.

## Требования

* Unity **2022.3 LTS** (скрипты используют `Rigidbody.velocity`, `Physics.OverlapBoxNonAlloc`
  и старый `Input Manager` — всё актуально для 2022 LTS).
* Пакеты не требуются, скрипты компилируются в сборке по умолчанию (`Assembly-CSharp`).

---

Вот такой хаммам мам мам я банан нан нан чемодан дан дан ам ам ам ам ам
