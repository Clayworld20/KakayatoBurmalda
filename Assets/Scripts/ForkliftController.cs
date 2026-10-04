using System.Collections.Generic;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Физический контроллер робота-погрузчика.
    ///
    /// Модель движения: ОДИН динамический Rigidbody на корне погрузчика (compound collider).
    /// Крутящий момент поворота задаётся через angularVelocity, разгон — через AddForce(ForceMode.Acceleration),
    /// боковое проскальзывание гасится «сцеплением колёс», плюс есть антиопрокидывающий момент.
    /// Вилы (fork carriage) — дочерний Transform: высота меняется Lerp-ом по localPosition.y
    /// с ограничением по высоте. Так как вилы входят в compound collider корневого Rigidbody,
    /// они физически поднимают паллеты с грузом.
    ///
    /// Раскладка объектов в сцене (пример):
    ///   Forklift (Rigidbody + этот скрипт + BoxCollider на корпус)
    ///     ├── Body (меш корпуса)
    ///     ├── GroundCheck (пустышка у днища)
    ///     ├── Mast (меш мачты)
    ///     │     └── MastTiltPivot (шарнир наклона мачты)
    ///     │           └── ForkCarriage (вилы: BoxCollider'ы + меш вил)
    ///     └── Wheels / Wheel_FL, Wheel_FR, Wheel_RL, Wheel_RR (визуальные колёса)
    ///
    /// Управление по умолчанию (старый Input Manager, Unity 2022):
    ///   W / S      — вперёд / назад
    ///   A / D      — поворот влево / вправо
    ///   LeftShift  — подъём вил (работает и RightShift)
    ///   LeftCtrl   — опускание вил (работает и RightCtrl)
    ///   Q / E      — наклон мачты вперёд / назад
    ///   Space      — ручной тормоз
    ///   R          — сброс погрузчика (выровнять, снять скорости)
    ///
    /// Если в проекте включён только новый Input System (Active Input Handling = Input System Package),
    /// клавиатура не читается — управление подаётся снаружи через SetInput() / SetLiftInput().
    /// </summary>
    [RequireComponent(typeof(Rigidbody))]
    [AddComponentMenu("Kakayato/Forklift Controller")]
    public class ForkliftController : MonoBehaviour
    {
        #region Вложенные типы

        /// <summary>Визуальное колесо: крутится по скорости движения и (опционально) поворачивается как рулевое.</summary>
        [System.Serializable]
        public class WheelVisual
        {
            [Tooltip("Корень меша колеса.")]
            public Transform wheel;

            [Tooltip("Поворачивается ли колесо вместе с рулём.")]
            public bool steerable = true;

            [Tooltip("Радиус колеса в метрах — нужен для расчёта скорости вращения.")]
            [Min(0.02f)] public float radius = 0.3f;

            [HideInInspector] public float rollAngle;
            [HideInInspector] public Quaternion baseRotation = Quaternion.identity;
            [HideInInspector] public bool initialized;
        }

        /// <summary>Состояние одной паллеты, зафиксированной на вилах (для плавной доводки на место).</summary>
        private struct LockedCargoState
        {
            public CargoPallet pallet;
            public float lockTime;
            public Vector3 startLocalPosition;
            public Quaternion startLocalRotation;
            public Vector3 targetLocalPosition;
            public Quaternion targetLocalRotation;
        }

        #endregion

        #region Ссылки

        [Header("Ссылки")]
        [Tooltip("Корень каретки с вилами. Обязательное поле: высота вил меняется у этого Transform.")]
        [SerializeField] private Transform forkCarriage;

        [Tooltip("Пустышка у днища корпуса для проверки заземления. Если пусто — берётся центр объекта.")]
        [SerializeField] private Transform groundCheck;

        [Tooltip("Шарнир наклона мачты (необязательно). Вращается по локальному X.")]
        [SerializeField] private Transform mastTiltPivot;

        [Tooltip("Коллайдер вил: по нему считается посадочное место паллеты. Если пусто — берётся первый BoxCollider каретки.")]
        [SerializeField] private BoxCollider forkCollider;

        [Tooltip("Точка возврата при сбросе погрузчика (клавиша R). Если пусто — позиция на момент старта.")]
        [SerializeField] private Transform resetPoint;

        [Tooltip("Слои, которые считаются «землёй» для проверки заземления. Оставьте «Everything» — при старте слой Ground будет найден по имени.")]
        [SerializeField] private LayerMask groundLayers = ~0;

        [SerializeField, Min(0.05f), Tooltip("Длина проверки заземления, м (сфера идёт вниз из GroundCheck).")]
        private float groundCheckDistance = 0.75f;

        [SerializeField, Min(0.01f), Tooltip("Радиус сферы проверки заземления, м.")]
        private float groundCheckRadius = 0.22f;

        [SerializeField, Tooltip("Если маска = «Everything», попробовать найти слой Ground по имени, чтобы никогда не цеплять корпус и груз.")]
        private bool autoResolveGroundLayer = true;

        [Tooltip("Слои, на которых ищутся паллеты с грузом при захвате вилами.")]
        [SerializeField] private LayerMask cargoLayers = ~0;

        [Tooltip("Визуальные колёса (не влияют на физику — физику считает Rigidbody).")]
        [SerializeField] private WheelVisual[] wheelVisuals;

        #endregion

        #region Настройки движения

        [Header("Движение (силы в ньютонах, штатная масса погрузчика 900 кг)")]
        [SerializeField, Min(0f), Tooltip("Сила тяги вперёд, Н. 16 000 Н даёт ≈17 м/с² для 900 кг — уверенно срывает машину с места.")]
        private float forwardMotorForce = 16000f;

        [SerializeField, Min(0f), Tooltip("Сила тяги назад, Н.")]
        private float reverseMotorForce = 10000f;

        [SerializeField, Min(0f), Tooltip("Максимальная скорость вперёд, м/с.")]
        private float maxForwardSpeed = 7f;

        [SerializeField, Min(0f), Tooltip("Максимальная скорость назад, м/с.")]
        private float maxReverseSpeed = 3.5f;

        [SerializeField, Min(0f), Tooltip("Сила торможения двигателем при отпущенном газе, Н.")]
        private float brakeForce = 8000f;

        [SerializeField, Min(0f), Tooltip("Сила ручного тормоза (Space), Н.")]
        private float handbrakeForce = 24000f;

        [SerializeField, Range(0f, 1f), Tooltip("Доля тяги в воздухе (0 — полёт без управления, 1 — полный контроль). " +
                                                 "Ненулевое значение гарантирует, что погрузчик поедет, даже если проверка заземления дала сбой.")]
        private float airControl = 0.25f;

        [SerializeField, Min(0.05f), Tooltip("Скорость отклика мотора, 1/с (плавность нажатия и сброса газа).")]
        private float motorResponse = 6f;

        [SerializeField, Range(0f, 0.5f), Tooltip("Мёртвая зона газа и руля (0 — без мёртвой зоны).")]
        private float throttleDeadZone = 0.02f;

        [SerializeField, Tooltip("Автоматически ограничивать угловую скорость корпуса, чтобы погрузчик не «юзал».")]
        private bool limitBodyPitchAndRoll = true;

        [SerializeField, Min(0f), Tooltip("Предел скорости кувыркания корпуса (тангаж/крен), град/с.")]
        private float maxTumbleRate = 120f;

        [SerializeField, Tooltip("Следить за «залипанием»: если газ нажат, а машина не движется — один раз объяснить причину в консоли.")]
        private bool logMovementDiagnostics = true;

        #endregion

        #region Настройки поворота

        [Header("Поворот")]
        [SerializeField, Tooltip("Максимальная скорость поворота корпуса, град/с.")]
        private float maxTurnRate = 80f;

        [SerializeField, Tooltip("Ускорение разгона/остановки поворота, град/с².")]
        private float turnAcceleration = 240f;

        [SerializeField, Range(0f, 1f), Tooltip("Доля управляемости на месте (робот может разворачиваться на месте).")]
        private float turnAuthorityAtStandstill = 0.5f;

        [SerializeField, Tooltip("Скорость, на которой управляемость считается максимальной, м/с.")]
        private float turnSpeedReference = 3f;

        [SerializeField, Tooltip("Скорость, ниже которой задний ход не инвертирует руль, м/с.")]
        private float steerInvertThreshold = 0.2f;

        [SerializeField, Range(0f, 90f), Tooltip("Максимальный угол поворота визуальных колёс, град.")]
        private float maxVisualSteerAngle = 24f;

        #endregion

        #region Настройки сцепления и устойчивости

        [Header("Сцепление и устойчивость")]
        [SerializeField, Min(0f), Tooltip("Жёсткость гашения бокового скольжения (чем больше — тем сильнее «держит» дорогу).")]
        private float lateralGrip = 7f;

        [SerializeField, Min(0f), Tooltip("Порог боковой скорости, ниже которого сцепление не вмешивается, м/с.")]
        private float minLateralSlip = 0.05f;

        [SerializeField, Min(0f), Tooltip("Прижимная сила от скорости, м/с² на 1 м/с.")]
        private float speedDownforce = 1.2f;

        [SerializeField, Min(0f), Tooltip("Предел прижимной силы, м/с².")]
        private float maxDownforce = 8f;

        [SerializeField, Min(0f), Tooltip("Момент, выравнивающий корпус, когда он заваливается на бок.")]
        private float uprightTorque = 45f;

        [SerializeField, Min(0f), Tooltip("Момент переворота «с крыши на колёса».")]
        private float flipRecoveryTorque = 160f;

        [SerializeField, Tooltip("Сместить центр масс от расчётного (ниже и назад = устойчивее).")]
        private bool overrideCenterOfMass = true;

        [SerializeField, Tooltip("Смещение центра масс в локальных координатах корпуса.")]
        private Vector3 centerOfMassOffset = new Vector3(0f, -0.35f, 0.1f);

        [SerializeField, Tooltip("Интерполяция Rigidbody — обязательна для плавной картинки на физике.")]
        private RigidbodyInterpolation interpolation = RigidbodyInterpolation.Interpolate;

        #endregion

        #region Настройки вил

        [Header("Вилa (fork lift)")]
        [SerializeField, Tooltip("Минимальная высота каретки в локальных координатах мачты.")]
        private float forkMinHeight = 0.02f;

        [SerializeField, Tooltip("Максимальная высота каретки в локальных координатах мачты.")]
        private float forkMaxHeight = 2.4f;

        [SerializeField, Min(0f), Tooltip("Скорость подъёма/опускания вил, м/с.")]
        private float forkSpeed = 1.1f;

        [SerializeField, Min(0.01f), Tooltip("Сглаживание движения вил (больше = резче). Линейный Lerp с ограничением по высоте.")]
        private float forkSmoothing = 14f;

        [SerializeField, Tooltip("Стартовая высота вил.")]
        private float startForkHeight = 0.02f;

        #endregion

        #region Настройки наклона мачты

        [Header("Наклон мачты")]
        [SerializeField, Min(0f), Tooltip("Скорость наклона мачты, град/с.")]
        private float mastTiltSpeed = 35f;

        [SerializeField, Min(0.01f), Tooltip("Сглаживание наклона мачты.")]
        private float mastTiltSmoothing = 10f;

        [SerializeField, Tooltip("Максимальный наклон вперёд (вилы вниз), град.")]
        private float mastMinTilt = -8f;

        [SerializeField, Tooltip("Максимальный наклон назад (вилы вверх), град.")]
        private float mastMaxTilt = 20f;

        #endregion

        #region Захват груза (Locking Mechanism)

        [Header("Захват груза на вилах")]
        [SerializeField, Tooltip("Центр объёма захвата в локальных координатах каретки: паллета в этом объёме считается «на вилах».")]
        private Vector3 carryVolumeCenter = new Vector3(0f, 0.3f, 0.45f);

        [SerializeField, Tooltip("Размер объёма захвата в локальных координатах каретки.")]
        private Vector3 carryVolumeSize = new Vector3(1.6f, 0.9f, 1.7f);

        [SerializeField, Tooltip("Автоматически фиксировать паллету, коснувшуюся вил (иначе только по клавише захвата).")]
        private bool autoLockCargo = true;

        [SerializeField, Tooltip("Клавиша «захватить / отпустить груз».")]
        private KeyCode grabKey = KeyCode.F;

        [SerializeField, Min(0.02f), Tooltip("За сколько секунд паллета плавно «садится» на вилы после захвата.")]
        private float lockAlignDuration = 0.22f;

        [SerializeField, Min(0f), Tooltip("Пауза перед повторным захватом той же паллеты после отпускания, с.")]
        private float relockDelay = 0.5f;

        [SerializeField, Tooltip("Отпускать груз, когда вилы опущены в нижнее положение (после того как груз хотя бы раз подняли).")]
        private bool autoReleaseWhenLowered = true;

        [SerializeField, Min(0f), Tooltip("Высота подъёма (м), после которой начинает работать автоотпускание при опускании вил.")]
        private float autoReleaseLiftHeight = 0.25f;

        [SerializeField, Tooltip("Учитывать массу груза: с паллетой на вилах погрузчик тяжелее.")]
        private bool applyCargoWeight = true;

        #endregion

        #region Ввод

        [Header("Ввод")]
        [SerializeField, Tooltip("Читать клавиатуру через старый Input Manager. Отключите, если ввод подаёт внешний адаптер.")]
        private bool readKeyboardInput = true;

        [SerializeField, Tooltip("Клавиша «вперёд».")]
        private KeyCode forwardKey = KeyCode.W;

        [SerializeField, Tooltip("Клавиша «назад».")]
        private KeyCode backwardKey = KeyCode.S;

        [SerializeField, Tooltip("Клавиша «поворот влево».")]
        private KeyCode turnLeftKey = KeyCode.A;

        [SerializeField, Tooltip("Клавиша «поворот вправо».")]
        private KeyCode turnRightKey = KeyCode.D;

        [SerializeField, Tooltip("Клавиша «подъём вил».")]
        private KeyCode liftUpKey = KeyCode.LeftShift;

        [SerializeField, Tooltip("Клавиша «опускание вил».")]
        private KeyCode liftDownKey = KeyCode.LeftControl;

        [SerializeField, Tooltip("Клавиша «наклон мачты вперёд».")]
        private KeyCode tiltForwardKey = KeyCode.Q;

        [SerializeField, Tooltip("Клавиша «наклон мачты назад».")]
        private KeyCode tiltBackwardKey = KeyCode.E;

        [SerializeField, Tooltip("Клавиша ручного тормоза.")]
        private KeyCode handbrakeKey = KeyCode.Space;

        [SerializeField, Tooltip("Клавиша сброса погрузчика в исходное положение.")]
        private KeyCode resetKey = KeyCode.R;

        #endregion

        #region Состояние (не сериализуется)

        /// <summary>Все живые погрузчики на сцене — нужны зонам сортировки для проверки «груз на вилах».</summary>
        private static readonly List<ForkliftController> ActiveForklifts = new List<ForkliftController>();

        private Rigidbody body;
        private Collider[] overlapBuffer = new Collider[16];
        private Collider[] forkliftColliders = new Collider[0];
        private readonly RaycastHit[] groundHitsBuffer = new RaycastHit[8];
        private readonly List<LockedCargoState> lockedCargo = new List<LockedCargoState>();
        private readonly HashSet<CargoPallet> cargoInVolume = new HashSet<CargoPallet>();
        private readonly HashSet<CargoPallet> mustExitBeforeRelock = new HashSet<CargoPallet>();
        private readonly List<CargoPallet> cargoCleanupBuffer = new List<CargoPallet>();

        private float throttleInput;
        private float steerInput;
        private float liftInput;
        private float tiltInput;
        private bool handbrakeInput;

        private float externalThrottle;
        private float externalSteer;
        private float externalLift;
        private float externalTilt;
        private bool externalHandbrake;

        private float currentForkHeight;
        private float targetForkHeight;
        private float currentMastTilt;
        private float targetMastTilt;
        private float currentYawRate;
        private float currentVisualSteerAngle;
        private float currentMotor;
        private int cargoInVolumeCount;
        private float baseMass;
        private bool grabRequested;
        private bool releaseRequested;
        private bool liftedSinceLock;
        private bool resetRequested;
        private float stalledTime;
        private bool stallWarningLogged;

        private Vector3 startPosition;
        private Quaternion startRotation;

        #endregion

        #region Публичные свойства

        /// <summary>Погрузчик стоит на земле (проверка сферой под днищем).</summary>
        public bool IsGrounded { get; private set; }

        /// <summary>Текущая скорость вперёд (со знаком), м/с.</summary>
        public float ForwardSpeed { get; private set; }

        /// <summary>Скорость по модулю, м/с.</summary>
        public float Speed { get; private set; }

        /// <summary>Есть ли груз на вилах.</summary>
        public bool IsCarryingCargo { get { return lockedCargo.Count > 0; } }

        /// <summary>Сколько паллет зафиксировано на вилах сейчас.</summary>
        public int CarriedCargoCount { get { return lockedCargo.Count; } }

        /// <summary>Сколько паллет находится в объёме захвата (включая зафиксированные).</summary>
        public int CargoInVolumeCount { get { return cargoInVolumeCount; } }

        /// <summary>Текущая высота вил (локальная Y каретки).</summary>
        public float ForkHeight { get { return currentForkHeight; } }

        /// <summary>Нижнее положение вил в локальных координатах мачты, м (единый источник правды).</summary>
        public float ForkMinHeight { get { return forkMinHeight; } }

        /// <summary>Высота вил в диапазоне 0..1 — удобно для UI.</summary>
        public float ForkHeightNormalized
        {
            get
            {
                float range = Mathf.Max(0.0001f, forkMaxHeight - forkMinHeight);
                return Mathf.Clamp01((currentForkHeight - forkMinHeight) / range);
            }
        }

        /// <summary>Текущий вход газа (после смешивания клавиатуры и внешнего ввода).</summary>
        public float ThrottleInput { get { return throttleInput; } }

        /// <summary>Текущий вход руля (после смешивания клавиатуры и внешнего ввода).</summary>
        public float SteerInput { get { return steerInput; } }

        /// <summary>Текущая отдача мотора (-1..1) — сглаженное значение газа, которое реально идёт в физику.</summary>
        public float CurrentMotor { get { return currentMotor; } }

        /// <summary>Нормаль поверхности под погрузчиком (Vector3.up, если опоры нет).</summary>
        public Vector3 GroundNormal { get; private set; }

        /// <summary>Рабочая маска слоёв земли (после автоопределения слоя Ground).</summary>
        public LayerMask GroundLayers { get { return groundLayers; } }

        /// <summary>Rigidbody корпуса (кэш).</summary>
        public Rigidbody Body { get { return body; } }

        /// <summary>Transform каретки вил (для внешних систем, например крепления груза).</summary>
        public Transform ForkCarriage { get { return forkCarriage; } }

        #endregion

        #region Unity-сообщения

        private void Awake()
        {
            body = GetComponent<Rigidbody>();
            body.interpolation = interpolation;
            baseMass = Mathf.Max(1f, body.mass);
            forkliftColliders = GetComponentsInChildren<Collider>(true);

            if (forkCollider == null && forkCarriage != null)
            {
                forkCollider = forkCarriage.GetComponent<BoxCollider>();
            }

            // Стартовое состояние ввода — строго нулевое: ручник выключен, газ/руль/вилы в покое.
            throttleInput = 0f;
            steerInput = 0f;
            liftInput = 0f;
            tiltInput = 0f;
            handbrakeInput = false;
            currentMotor = 0f;
            externalThrottle = 0f;
            externalSteer = 0f;
            externalLift = 0f;
            externalTilt = 0f;
            externalHandbrake = false;
            stalledTime = 0f;
            stallWarningLogged = false;

            GroundNormal = Vector3.up;
            ResolveGroundLayers();

            if (IsLayerInMask(gameObject.layer, groundLayers) && groundCheck == null)
            {
                // Если Ground Check не назначен, луч идёт из центра корпуса и маска земли,
                // включающая слой самого погрузчика, может давать ложные срабатывания.
                Debug.LogWarning("[ForkliftController] Маска земли включает слой самого погрузчика, а Ground Check не назначен. " +
                                 "Проверка заземления игнорирует собственные коллайдеры, но лучше назначить Ground Check под днищем.", this);
            }

            if (body.mass < 1f)
            {
                Debug.LogWarning("[ForkliftController] Масса Rigidbody меньше 1 кг — тяга рассчитана на тяжёлую технику (900 кг).", this);
            }

            if (overrideCenterOfMass)
            {
                // Считаем центр масс по коллайдерам и смещаем его вниз/назад — так погрузчик устойчивее.
                body.ResetCenterOfMass();
                body.centerOfMass += centerOfMassOffset;
            }

            startPosition = transform.position;
            startRotation = transform.rotation;

            currentForkHeight = Mathf.Clamp(startForkHeight, forkMinHeight, forkMaxHeight);
            targetForkHeight = currentForkHeight;
            currentMastTilt = 0f;
            targetMastTilt = 0f;

            InitializeWheelVisuals();
            ApplyForkHeight();

            if (!ActiveForklifts.Contains(this))
            {
                ActiveForklifts.Add(this);
            }

#if !ENABLE_LEGACY_INPUT_MANAGER
            if (readKeyboardInput)
            {
                Debug.LogWarning("[ForkliftController] Старый Input Manager выключен (Active Input Handling = Input System Package). " +
                                 "Клавиатура недоступна: подавайте ввод через SetInput()/SetLiftInput() или включите Both в Project Settings → Player.", this);
            }
#endif
        }

        private void Update()
        {
            ReadInput();

#if ENABLE_LEGACY_INPUT_MANAGER
            if (readKeyboardInput && Input.GetKeyDown(resetKey))
            {
                RequestReset();
            }

            // F — взять груз на вилы либо отпустить уже зафиксированный.
            if (readKeyboardInput && Input.GetKeyDown(grabKey))
            {
                grabRequested = true;
            }
#endif
        }

        private void FixedUpdate()
        {
            float deltaTime = Time.fixedDeltaTime;

            if (resetRequested)
            {
                resetRequested = false;
                PerformReset();
            }

            UpdateGroundedState();
            UpdateForkHeight(deltaTime);
            UpdateMastTilt(deltaTime);
            UpdateCargoGrab();
            ApplyDrive(deltaTime);
            ApplySteering(deltaTime);
            ApplyLateralGrip(deltaTime);
            ApplyStabilization();
            LimitTumbling();
            UpdateWheelVisuals(deltaTime);
            UpdateMovementDiagnostics(deltaTime);
        }

        private void OnDisable()
        {
            ActiveForklifts.Remove(this);
            ReleaseAllCargo();
            cargoInVolume.Clear();
            mustExitBeforeRelock.Clear();
            cargoInVolumeCount = 0;
        }

        private void OnValidate()
        {
            forkMinHeight = Mathf.Max(0f, forkMinHeight);
            forkMaxHeight = Mathf.Max(forkMinHeight, forkMaxHeight);
            startForkHeight = Mathf.Clamp(startForkHeight, forkMinHeight, forkMaxHeight);
            carryVolumeSize = new Vector3(
                Mathf.Max(0.05f, carryVolumeSize.x),
                Mathf.Max(0.05f, carryVolumeSize.y),
                Mathf.Max(0.05f, carryVolumeSize.z));
            mastMinTilt = Mathf.Min(mastMinTilt, mastMaxTilt);
            lockAlignDuration = Mathf.Max(0.02f, lockAlignDuration);
            relockDelay = Mathf.Max(0f, relockDelay);
            autoReleaseLiftHeight = Mathf.Max(0f, autoReleaseLiftHeight);
        }

        #endregion

        #region Публичный API

        /// <summary>
        /// Задать ввод снаружи (адаптер нового Input System, AI, сетевой игрок).
        /// Вызывайте каждый кадр; для отпускания используйте ClearInput().
        /// Значения клавиатуры (если включена) складываются с внешними и ограничиваются [-1..1].
        /// </summary>
        public void SetInput(float throttle, float steer, float lift = 0f, float tilt = 0f, bool handbrake = false)
        {
            externalThrottle = Mathf.Clamp(throttle, -1f, 1f);
            externalSteer = Mathf.Clamp(steer, -1f, 1f);
            externalLift = Mathf.Clamp(lift, -1f, 1f);
            externalTilt = Mathf.Clamp(tilt, -1f, 1f);
            externalHandbrake = handbrake;
        }

        /// <summary>Только подъём/опускание вил (если движением управляет другой скрипт).</summary>
        public void SetLiftInput(float lift)
        {
            externalLift = Mathf.Clamp(lift, -1f, 1f);
        }

        /// <summary>Только наклон мачты.</summary>
        public void SetTiltInput(float tilt)
        {
            externalTilt = Mathf.Clamp(tilt, -1f, 1f);
        }

        /// <summary>Обнулить внешний ввод.</summary>
        public void ClearInput()
        {
            externalThrottle = 0f;
            externalSteer = 0f;
            externalLift = 0f;
            externalTilt = 0f;
            externalHandbrake = false;
        }

        /// <summary>Мгновенно поставить вилы на нужную высоту (например, при респавне).</summary>
        public void SetForkHeight(float height, bool immediate = true)
        {
            targetForkHeight = Mathf.Clamp(height, forkMinHeight, forkMaxHeight);
            if (immediate)
            {
                currentForkHeight = targetForkHeight;
                ApplyForkHeight();
            }
        }

        /// <summary>Зафиксирована ли конкретная паллета на вилах этого погрузчика.</summary>
        public bool IsCarrying(CargoPallet pallet)
        {
            if (pallet == null)
            {
                return false;
            }

            for (int i = 0; i < lockedCargo.Count; i++)
            {
                if (lockedCargo[i].pallet == pallet)
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>Скопировать список паллет, зафиксированных на вилах сейчас.</summary>
        public void GetCarriedCargo(List<CargoPallet> results)
        {
            if (results == null)
            {
                return;
            }

            results.Clear();

            for (int i = 0; i < lockedCargo.Count; i++)
            {
                if (lockedCargo[i].pallet != null)
                {
                    results.Add(lockedCargo[i].pallet);
                }
            }
        }

        /// <summary>Взять груз с вил (запрос извне: кнопка UI, адаптер ввода, AI).</summary>
        public void GrabCargo()
        {
            grabRequested = true;
        }

        /// <summary>Отпустить груз с вил (запрос извне: кнопка UI, адаптер ввода, AI).</summary>
        public void ReleaseCargo()
        {
            releaseRequested = true;
        }

        /// <summary>Есть ли паллета на вилах хотя бы у одного погрузчика сцены. Используется зонами сортировки.</summary>
        public static bool IsCargoCarriedByAnyForklift(CargoPallet pallet)
        {
            if (pallet == null)
            {
                return false;
            }

            for (int i = ActiveForklifts.Count - 1; i >= 0; i--)
            {
                ForkliftController forklift = ActiveForklifts[i];
                if (forklift == null)
                {
                    ActiveForklifts.RemoveAt(i);
                    continue;
                }

                if (forklift.IsCarrying(pallet))
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>Запросить сброс погрузчика: выровнять корпус, снять скорости, вернуть на точку старта.</summary>
        public void RequestReset()
        {
            resetRequested = true;
        }

        #endregion

        #region Чтение ввода

        private void ReadInput()
        {
            float keyboardThrottle = 0f;
            float keyboardSteer = 0f;
            float keyboardLift = 0f;
            float keyboardTilt = 0f;
            bool keyboardHandbrake = false;

#if ENABLE_LEGACY_INPUT_MANAGER
            if (readKeyboardInput)
            {
                if (Input.GetKey(forwardKey)) keyboardThrottle += 1f;
                if (Input.GetKey(backwardKey)) keyboardThrottle -= 1f;

                if (Input.GetKey(turnRightKey)) keyboardSteer += 1f;
                if (Input.GetKey(turnLeftKey)) keyboardSteer -= 1f;

                // Shift/Ctrl удобно жать с любой стороны — учитываем оба варианта.
                bool liftUp = Input.GetKey(liftUpKey) || (liftUpKey == KeyCode.LeftShift && Input.GetKey(KeyCode.RightShift));
                bool liftDown = Input.GetKey(liftDownKey) || (liftDownKey == KeyCode.LeftControl && Input.GetKey(KeyCode.RightControl));

                if (liftUp) keyboardLift += 1f;
                if (liftDown) keyboardLift -= 1f;

                if (Input.GetKey(tiltBackwardKey)) keyboardTilt += 1f;
                if (Input.GetKey(tiltForwardKey)) keyboardTilt -= 1f;

                keyboardHandbrake = Input.GetKey(handbrakeKey);
            }
#endif

            throttleInput = Mathf.Clamp(keyboardThrottle + externalThrottle, -1f, 1f);
            steerInput = Mathf.Clamp(keyboardSteer + externalSteer, -1f, 1f);
            liftInput = Mathf.Clamp(keyboardLift + externalLift, -1f, 1f);
            tiltInput = Mathf.Clamp(keyboardTilt + externalTilt, -1f, 1f);
            handbrakeInput = keyboardHandbrake || externalHandbrake;

            if (Mathf.Abs(throttleInput) < throttleDeadZone) throttleInput = 0f;
            if (Mathf.Abs(steerInput) < throttleDeadZone) steerInput = 0f;
            if (Mathf.Abs(liftInput) < throttleDeadZone) liftInput = 0f;
            if (Mathf.Abs(tiltInput) < throttleDeadZone) tiltInput = 0f;
        }

        #endregion

        #region Земля, вила, мачта

        private void UpdateGroundedState()
        {
            // Сфера вниз из GroundCheck. Маска слоёв отсекает всё лишнее ещё на уровне физики,
            // а фильтр по иерархии/rigidbody выбрасывает коллайдеры самого погрузчика (вилы, каретка,
            // корпус) и груз, даже если они случайно попали в маску.
            Vector3 origin = groundCheck != null ? groundCheck.position : transform.position + Vector3.up * 0.25f;
            float radius = Mathf.Max(0.01f, groundCheckRadius);
            float distance = Mathf.Max(0.05f, groundCheckDistance);

            // Начинаем сферу чуть выше точки проверки, чтобы она не «застревала» внутри пола.
            Vector3 castOrigin = origin + Vector3.up * radius * 0.5f;

            int hitCount = Physics.SphereCastNonAlloc(
                castOrigin,
                radius,
                Vector3.down,
                groundHitsBuffer,
                distance + radius * 0.5f,
                groundLayers,
                QueryTriggerInteraction.Ignore);

            IsGrounded = false;
            GroundNormal = Vector3.up;

            for (int i = 0; i < hitCount; i++)
            {
                Collider hitCollider = groundHitsBuffer[i].collider;
                if (hitCollider == null)
                {
                    continue;
                }

                // Свой корпус, мачта, каретка, вилы — не земля.
                if (hitCollider.transform.IsChildOf(transform))
                {
                    continue;
                }

                Rigidbody hitBody = hitCollider.attachedRigidbody;
                if (hitBody == body || (hitBody != null && hitBody.transform.IsChildOf(transform)))
                {
                    continue;
                }

                // Паллеты с грузом — это груз, а не опора.
                if (hitCollider.GetComponentInParent<CargoPallet>() != null)
                {
                    continue;
                }

                IsGrounded = true;
                GroundNormal = groundHitsBuffer[i].normal;

                // Отбрасываем заведомо «боковые» контакты (например, стена амбара рядом с вилами).
                if (GroundNormal.y < 0.1f)
                {
                    IsGrounded = false;
                }

                break;
            }
        }

        /// <summary>
        /// Определить рабочую маску земли. Если пользователь оставил «Everything»,
        /// пробуем найти слой Ground по имени — тогда проверка гарантированно не цепляет
        /// собственный корпус и груз.
        /// </summary>
        private void ResolveGroundLayers()
        {
            if (!autoResolveGroundLayer)
            {
                return;
            }

            if (groundLayers.value != ~0)
            {
                return;
            }

            int groundLayerIndex = LayerMask.NameToLayer("Ground");
            if (groundLayerIndex < 0)
            {
                return;
            }

            groundLayers = 1 << groundLayerIndex;
            Debug.Log(string.Format(
                "[ForkliftController] Маска земли не задана — использую слой «Ground» (индекс {0}).",
                groundLayerIndex), this);
        }

        private static bool IsLayerInMask(int layer, LayerMask mask)
        {
            return (mask.value & (1 << layer)) != 0;
        }

        /// <summary>
        /// Подъём/опускание вил: цель меняется с постоянной скоростью, текущая высота догоняет её
        /// через Lerp (кадронезависимый), результат пишется в localPosition каретки.
        /// </summary>
        private void UpdateForkHeight(float deltaTime)
        {
            if (forkCarriage == null)
            {
                return;
            }

            if (Mathf.Abs(liftInput) > 0.001f)
            {
                targetForkHeight = Mathf.Clamp(targetForkHeight + liftInput * forkSpeed * deltaTime, forkMinHeight, forkMaxHeight);
            }

            float blend = 1f - Mathf.Exp(-forkSmoothing * deltaTime);
            currentForkHeight = Mathf.Lerp(currentForkHeight, targetForkHeight, blend);

            if (Mathf.Abs(currentForkHeight - targetForkHeight) < 0.0005f)
            {
                currentForkHeight = targetForkHeight;
            }

            ApplyForkHeight();
        }

        private void ApplyForkHeight()
        {
            if (forkCarriage == null)
            {
                return;
            }

            Vector3 localPosition = forkCarriage.localPosition;
            localPosition.y = currentForkHeight;
            forkCarriage.localPosition = localPosition;
        }

        /// <summary>Наклон мачты вокруг локального X: минус — вперёд (вилы вниз), плюс — назад.</summary>
        private void UpdateMastTilt(float deltaTime)
        {
            if (mastTiltPivot == null)
            {
                return;
            }

            if (Mathf.Abs(tiltInput) > 0.001f)
            {
                targetMastTilt = Mathf.Clamp(targetMastTilt + tiltInput * mastTiltSpeed * deltaTime, mastMinTilt, mastMaxTilt);
            }

            float blend = 1f - Mathf.Exp(-mastTiltSmoothing * deltaTime);
            currentMastTilt = Mathf.Lerp(currentMastTilt, targetMastTilt, blend);
            mastTiltPivot.localRotation = Quaternion.Euler(currentMastTilt, 0f, 0f);
        }

        /// <summary>
        /// Захват груза вилами. Паллета, коснувшаяся вил, по клавише (или автоматически) фиксируется:
        /// Rigidbody становится kinematic, паллета становится ребёнком каретки и плавно доводится до
        /// посадочного места на вилах. Взаимные столкновения с погрузчиком выключаются, поэтому
        /// груз не дрожит и не соскальзывает на поворотах.
        /// </summary>
        private void UpdateCargoGrab()
        {
            UpdateLockedCargoAlignment();
            RefreshCargoVolume();
            CleanupLockedCargo();

            if (forkCarriage == null)
            {
                grabRequested = false;
                releaseRequested = false;
                return;
            }

            bool manualGrab = grabRequested;
            bool manualRelease = releaseRequested;
            grabRequested = false;
            releaseRequested = false;

            if (manualRelease || (manualGrab && lockedCargo.Count > 0))
            {
                ReleaseAllCargo();
                return;
            }

            if (lockedCargo.Count == 0)
            {
                if (manualGrab || autoLockCargo)
                {
                    CargoPallet candidate = FindGrabCandidate(manualGrab);

                    if (candidate != null)
                    {
                        LockCargo(candidate);
                    }
                }

                return;
            }

            // Груз на вилах: помним, что его поднимали, и слушаем автоотпускание при опускании.
            if (currentForkHeight > forkMinHeight + autoReleaseLiftHeight)
            {
                liftedSinceLock = true;
            }

            if (autoReleaseWhenLowered && liftedSinceLock && liftInput <= 0.001f &&
                currentForkHeight <= forkMinHeight + 0.05f)
            {
                ReleaseAllCargo();
            }
        }

        /// <summary>Посадить паллету на вилы: kinematic + ребёнок каретки + плавная доводка до места.</summary>
        private void LockCargo(CargoPallet pallet)
        {
            if (pallet == null || pallet.IsSorted || pallet.IsLocked)
            {
                return;
            }

            if (pallet.Body != null)
            {
                pallet.Body.velocity = Vector3.zero;
                pallet.Body.angularVelocity = Vector3.zero;
            }

            SetCollisionsWithForklift(pallet, false);
            pallet.LockTo(this);
            pallet.transform.SetParent(forkCarriage, true);

            LockedCargoState state = default(LockedCargoState);
            state.pallet = pallet;
            state.lockTime = Time.fixedTime;
            state.startLocalPosition = pallet.transform.localPosition;
            state.startLocalRotation = pallet.transform.localRotation;
            state.targetLocalPosition = ComputeForkSlotPosition(pallet);
            state.targetLocalRotation = Quaternion.identity;
            lockedCargo.Add(state);

            liftedSinceLock = false;
            UpdateCarryMass();
        }

        /// <summary>Отпустить весь груз: физика возвращается, паллета остаётся на месте выгрузки.</summary>
        private void ReleaseAllCargo()
        {
            if (lockedCargo.Count == 0)
            {
                return;
            }

            for (int i = lockedCargo.Count - 1; i >= 0; i--)
            {
                CargoPallet pallet = lockedCargo[i].pallet;
                lockedCargo.RemoveAt(i);

                if (pallet == null)
                {
                    continue;
                }

                pallet.transform.SetParent(pallet.HomeParent, true);
                SetCollisionsWithForklift(pallet, true);
                pallet.ReleaseFromLock();

                if (pallet.Body != null && !pallet.Body.isKinematic)
                {
                    // Груз наследует скорость погрузчика — выгрузка на ходу выглядит естественно.
                    pallet.Body.velocity = body != null ? body.velocity : Vector3.zero;
                    pallet.Body.angularVelocity = Vector3.zero;
                }

                // Пока паллета не вышла из объёма захвата, автоматически её больше не берём:
                // иначе выгруженный груз мгновенно «прилипал» бы обратно к вилам.
                mustExitBeforeRelock.Add(pallet);
            }

            liftedSinceLock = false;
            UpdateCarryMass();
        }

        /// <summary>Плавная доводка зафиксированных паллет до посадочного места на вилах.</summary>
        private void UpdateLockedCargoAlignment()
        {
            if (lockedCargo.Count == 0)
            {
                return;
            }

            float duration = Mathf.Max(0.02f, lockAlignDuration);

            for (int i = 0; i < lockedCargo.Count; i++)
            {
                LockedCargoState state = lockedCargo[i];
                CargoPallet pallet = state.pallet;

                if (pallet == null)
                {
                    continue;
                }

                float raw = Mathf.Clamp01((Time.fixedTime - state.lockTime) / duration);
                float smooth = raw * raw * (3f - 2f * raw);

                if (raw >= 1f)
                {
                    state.startLocalPosition = state.targetLocalPosition;
                    state.startLocalRotation = state.targetLocalRotation;
                }

                Transform palletTransform = pallet.transform;
                palletTransform.localPosition = Vector3.Lerp(state.startLocalPosition, state.targetLocalPosition, smooth);
                palletTransform.localRotation = Quaternion.Slerp(state.startLocalRotation, state.targetLocalRotation, smooth);
                lockedCargo[i] = state;
            }
        }

        /// <summary>Посадочное место паллеты: её низ ложится на верхнюю плоскость вил, центр — по центру вил.</summary>
        private Vector3 ComputeForkSlotPosition(CargoPallet pallet)
        {
            float forkTopLocalY = forkCollider != null
                ? forkCollider.center.y + forkCollider.size.y * 0.5f
                : 0.07f;

            float slotLocalZ = forkCollider != null ? forkCollider.center.z : 0.7f;
            float bottomOffset = pallet != null ? pallet.BottomOffset : 0f;

            return new Vector3(0f, forkTopLocalY + bottomOffset + 0.01f, slotLocalZ);
        }

        /// <summary>Обновить список паллет в объёме захвата и снять правило «сначала выйти из объёма» с тех, кто уже вышел.</summary>
        private void RefreshCargoVolume()
        {
            cargoInVolume.Clear();
            cargoInVolumeCount = 0;

            if (forkCarriage == null)
            {
                mustExitBeforeRelock.Clear();
                return;
            }

            Vector3 center = forkCarriage.TransformPoint(carryVolumeCenter);
            Vector3 halfExtents = carryVolumeSize * 0.5f;

            int count = Physics.OverlapBoxNonAlloc(
                center,
                halfExtents,
                overlapBuffer,
                forkCarriage.rotation,
                cargoLayers,
                QueryTriggerInteraction.Ignore);

            for (int i = 0; i < count; i++)
            {
                Collider other = overlapBuffer[i];
                if (other == null)
                {
                    continue;
                }

                CargoPallet pallet = other.GetComponentInParent<CargoPallet>();
                if (pallet == null || pallet.IsSorted || pallet.IsLocked)
                {
                    continue;
                }

                cargoInVolume.Add(pallet);
                cargoInVolumeCount++;
            }

            if (mustExitBeforeRelock.Count == 0)
            {
                return;
            }

            cargoCleanupBuffer.Clear();

            foreach (CargoPallet pallet in mustExitBeforeRelock)
            {
                if (pallet == null || !cargoInVolume.Contains(pallet))
                {
                    cargoCleanupBuffer.Add(pallet);
                }
            }

            for (int i = 0; i < cargoCleanupBuffer.Count; i++)
            {
                mustExitBeforeRelock.Remove(cargoCleanupBuffer[i]);
            }
        }

        /// <summary>Убрать из списка зафиксированных уничтоженные или уже засчитанные паллеты.</summary>
        private void CleanupLockedCargo()
        {
            if (lockedCargo.Count == 0)
            {
                return;
            }

            bool massChanged = false;

            for (int i = lockedCargo.Count - 1; i >= 0; i--)
            {
                CargoPallet pallet = lockedCargo[i].pallet;

                if (pallet != null && !pallet.IsSorted)
                {
                    continue;
                }

                if (pallet != null)
                {
                    // Паллету засчитали прямо на вилах: возвращаем её в исходного родителя,
                    // чтобы она не уехала вместе с кареткой (и не исчезла в амбаре вместе с погрузчиком).
                    pallet.transform.SetParent(pallet.HomeParent, true);
                    SetCollisionsWithForklift(pallet, true);
                }

                lockedCargo.RemoveAt(i);
                massChanged = true;
            }

            if (massChanged)
            {
                UpdateCarryMass();
            }
        }

        /// <summary>Кандидат на захват: ближайшая паллета в объёме вил, ещё не занятая и не «только что отпущенная».</summary>
        private CargoPallet FindGrabCandidate(bool manualGrab)
        {
            if (cargoInVolume.Count == 0)
            {
                return null;
            }

            CargoPallet best = null;
            float bestDistance = float.MaxValue;
            Vector3 carriagePosition = forkCarriage.position;

            foreach (CargoPallet pallet in cargoInVolume)
            {
                if (pallet == null || pallet.IsSorted || pallet.IsLocked || pallet.IsLockedByOther(this))
                {
                    continue;
                }

                if (manualGrab)
                {
                    // Ручной захват: паллету можно взять сразу после отпускания (небольшая пауза от дребезга).
                    if (Time.time - pallet.LastReleaseTime < relockDelay)
                    {
                        continue;
                    }
                }
                else if (mustExitBeforeRelock.Contains(pallet))
                {
                    // Автозахват: сначала паллета должна покинуть объём вил, иначе выгруженный груз липнет обратно.
                    continue;
                }

                float distance = (pallet.transform.position - carriagePosition).sqrMagnitude;

                if (distance < bestDistance)
                {
                    bestDistance = distance;
                    best = pallet;
                }
            }

            return best;
        }

        /// <summary>
        /// Включить/выключить взаимные столкновения паллеты и погрузчика: на вилах они не должны
        /// толкать друг друга (иначе kinematic-груз «выстреливает» динамический корпус).
        /// </summary>
        private void SetCollisionsWithForklift(CargoPallet pallet, bool ignore)
        {
            if (pallet == null || forkliftColliders == null || forkliftColliders.Length == 0)
            {
                return;
            }

            Collider[] palletColliders = pallet.GetComponentsInChildren<Collider>(true);

            for (int i = 0; i < palletColliders.Length; i++)
            {
                Collider palletCollider = palletColliders[i];
                if (palletCollider == null)
                {
                    continue;
                }

                for (int j = 0; j < forkliftColliders.Length; j++)
                {
                    Collider forkliftCollider = forkliftColliders[j];
                    if (forkliftCollider == null)
                    {
                        continue;
                    }

                    Physics.IgnoreCollision(palletCollider, forkliftCollider, ignore);
                }
            }
        }

        /// <summary>Масса погрузчика с учётом груза на вилах (тяжёлая паллета ухудшает разгон).</summary>
        private void UpdateCarryMass()
        {
            if (body == null || !applyCargoWeight)
            {
                return;
            }

            float cargoMass = 0f;

            for (int i = 0; i < lockedCargo.Count; i++)
            {
                CargoPallet pallet = lockedCargo[i].pallet;

                if (pallet != null && pallet.Body != null)
                {
                    cargoMass += pallet.Body.mass;
                }
            }

            float targetMass = baseMass + cargoMass;

            if (!Mathf.Approximately(body.mass, targetMass))
            {
                body.mass = targetMass;
            }
        }

        #endregion

        #region Физика движения

        private void ApplyDrive(float deltaTime)
        {
            ForwardSpeed = Vector3.Dot(GetFlatVelocity(), transform.forward);

            // Тяга есть всегда: на земле — полная, в воздухе — доля airControl.
            // Именно поэтому погрузчик поедет даже при сбое проверки заземления.
            float traction = IsGrounded ? 1f : Mathf.Clamp01(airControl);

            // Плавный отклик мотора (без рывка при мгновенном нажатии клавиши).
            currentMotor = Mathf.MoveTowards(currentMotor, throttleInput, motorResponse * deltaTime);

            if (Mathf.Abs(currentMotor) > 0.001f)
            {
                bool drivingForward = currentMotor >= 0f;
                float motorForce = drivingForward ? forwardMotorForce : reverseMotorForce;
                float maxSpeed = drivingForward ? maxForwardSpeed : maxReverseSpeed;

                // Гасим тягу по мере набора скорости — плавный выход на «крейсер».
                float speedFactor = Mathf.Clamp01(1f - Mathf.Abs(ForwardSpeed) / Mathf.Max(0.5f, maxSpeed));

                // Если машина катится в обратную сторону, сначала гасим инерцию — тягу не режем.
                if (Mathf.Abs(ForwardSpeed) > 0.5f && Mathf.Sign(ForwardSpeed) != Mathf.Sign(currentMotor))
                {
                    speedFactor = 1f;
                }

                // AddRelativeForce прикладывает силу вдоль ЛОКАЛЬНОЙ оси forward корпуса —
                // направление всегда совпадает с «носом» погрузчика, независимо от его поворота.
                Vector3 localDirection = Vector3.forward * Mathf.Sign(currentMotor);
                float appliedForce = motorForce * Mathf.Abs(currentMotor) * speedFactor * traction;

                body.AddRelativeForce(localDirection * appliedForce, ForceMode.Force);
            }
            else
            {
                ApplyBrake(brakeForce, deltaTime, traction);
            }

            if (handbrakeInput)
            {
                ApplyBrake(handbrakeForce, deltaTime, traction);
            }
        }

        /// <summary>
        /// Торможение силой (Н). Сила ограничивается так, чтобы за один шаг физики скорость
        /// не «перелетела» через ноль и машина не дёргалась назад.
        /// </summary>
        private void ApplyBrake(float brakeNewtons, float deltaTime, float traction)
        {
            float forwardSpeed = Vector3.Dot(GetFlatVelocity(), transform.forward);
            if (Mathf.Abs(forwardSpeed) < 0.02f)
            {
                return;
            }

            float maxUsefulForce = Mathf.Abs(forwardSpeed) * Mathf.Max(1f, body.mass) / Mathf.Max(deltaTime, 0.0001f);
            float appliedForce = Mathf.Min(brakeNewtons * traction, maxUsefulForce);

            body.AddRelativeForce(Vector3.forward * (-Mathf.Sign(forwardSpeed) * appliedForce), ForceMode.Force);
        }

        /// <summary>
        /// Диагностика «газ нажат, а машина стоит»: один раз объясняем в консоли, что проверить.
        /// Помогает не гадать, почему погрузчик не едет на новом проекте.
        /// </summary>
        private void UpdateMovementDiagnostics(float deltaTime)
        {
            if (!logMovementDiagnostics || stallWarningLogged)
            {
                return;
            }

            bool tryingToMove = Mathf.Abs(throttleInput) > 0.5f && !handbrakeInput;

            if (!tryingToMove || Mathf.Abs(ForwardSpeed) > 0.05f)
            {
                stalledTime = 0f;
                return;
            }

            stalledTime += deltaTime;
            if (stalledTime < 1f)
            {
                return;
            }

            stallWarningLogged = true;

#if ENABLE_LEGACY_INPUT_MANAGER
            const string inputState = "старый Input Manager доступен";
#else
            const string inputState = "старый Input Manager ВЫКЛЮЧЕН (Project Settings → Player → Active Input Handling = Input System Package) — " +
                                      "клавиатура не читается, подайте ввод через SetInput() или включите Both";
#endif

            Debug.LogWarning(string.Format(
                "[ForkliftController] Газ нажат, но погрузчик не движется. Состояние: заземлён = {0}, ручник = {1}, " +
                "масса = {2:F0} кг, тяга вперёд = {3:F0} Н, маска земли = {4}, отдача мотора = {5:F2}, скорость = {6:F2} м/с. " +
                "Причины по частоте: {7}; слишком высокое трение коллайдера корпуса о пол (нужен низкофрикционный PhysicMaterial); " +
                "погрузчик упёрся в препятствие.",
                IsGrounded,
                handbrakeInput,
                body.mass,
                forwardMotorForce,
                groundLayers.value,
                currentMotor,
                ForwardSpeed,
                inputState),
                this);
        }

        /// <summary>Ручная диагностика из контекстного меню компонента (правая кнопка мыши в инспекторе).</summary>
        [ContextMenu("Диагностика движения (в консоль)")]
        private void LogMovementDiagnosticsNow()
        {
            Debug.Log(string.Format(
                "[ForkliftController:{0}] заземлён={1} (нормаль {2}), маска земли={3} (Ground = {4}), ручник={5}, газ={6:F2}, " +
                "руль={7:F2}, мотор={8:F2}, скорость вперёд={9:F2} м/с, масса={10:F0} кг, тяга={11:F0}/{12:F0} Н, " +
                "вилы={13:F2} м, FPS-физика={14:F0} Гц, груза зафиксировано={15}, паллет в объёме захвата={16}.",
                name,
                IsGrounded,
                GroundNormal,
                groundLayers.value,
                LayerMask.NameToLayer("Ground"),
                handbrakeInput,
                throttleInput,
                steerInput,
                currentMotor,
                ForwardSpeed,
                body != null ? body.mass : 0f,
                forwardMotorForce,
                reverseMotorForce,
                currentForkHeight,
                1f / Mathf.Max(0.0001f, Time.fixedDeltaTime),
                lockedCargo.Count,
                cargoInVolumeCount),
                this);
        }

        private void ApplySteering(float deltaTime)
        {
            float forwardSpeed = Vector3.Dot(GetFlatVelocity(), transform.forward);
            float traction = IsGrounded ? 1f : Mathf.Clamp01(airControl);

            float speedFactor = Mathf.Clamp01(Mathf.Abs(forwardSpeed) / Mathf.Max(0.01f, turnSpeedReference));
            float authority = Mathf.Lerp(turnAuthorityAtStandstill, 1f, speedFactor) * traction;

            // Задним ходом машина рулит «в обратную сторону» — как настоящий автомобиль.
            float direction = 1f;
            if (Mathf.Abs(forwardSpeed) > steerInvertThreshold)
            {
                direction = Mathf.Sign(forwardSpeed);
            }

            float targetYawRate = steerInput * maxTurnRate * authority * direction;
            currentYawRate = Mathf.MoveTowards(currentYawRate, targetYawRate, turnAcceleration * deltaTime);

            // Переписываем только Y — крены и тангаж остаются на попечении физики.
            Vector3 angularVelocity = body.angularVelocity;
            angularVelocity.y = currentYawRate * Mathf.Deg2Rad;
            body.angularVelocity = angularVelocity;

            float targetVisualSteer = steerInput * maxVisualSteerAngle;
            currentVisualSteerAngle = Mathf.MoveTowards(currentVisualSteerAngle, targetVisualSteer, maxVisualSteerAngle * 6f * deltaTime);
        }

        /// <summary>Простое «сцепление колёс»: убираем часть боковой скорости, иначе погрузчик скользит как шайба.</summary>
        private void ApplyLateralGrip(float deltaTime)
        {
            if (!IsGrounded)
            {
                return;
            }

            Vector3 velocity = body.velocity;
            Vector3 flatVelocity = new Vector3(velocity.x, 0f, velocity.z);
            Vector3 right = transform.right;

            float lateralSpeed = Vector3.Dot(flatVelocity, right);
            if (Mathf.Abs(lateralSpeed) < minLateralSlip)
            {
                return;
            }

            float grip = 1f - Mathf.Exp(-lateralGrip * deltaTime);
            Vector3 corrected = flatVelocity - right * (lateralSpeed * grip);
            body.velocity = new Vector3(corrected.x, velocity.y, corrected.z);
        }

        /// <summary>Прижимная сила от скорости + выравнивающий момент, чтобы погрузчик не заваливался на поворотах.</summary>
        private void ApplyStabilization()
        {
            Vector3 flatVelocity = GetFlatVelocity();
            Speed = flatVelocity.magnitude;

            if (IsGrounded && Speed > 0.1f && maxDownforce > 0f)
            {
                float downforce = Mathf.Min(speedDownforce * Speed, maxDownforce);
                body.AddForce(-transform.up * downforce, ForceMode.Acceleration);
            }

            float uprightness = Vector3.Dot(transform.up, Vector3.up);
            if (uprightness < 0.999f)
            {
                Vector3 axis = Vector3.Cross(transform.up, Vector3.up);
                if (axis.sqrMagnitude > 0.0001f)
                {
                    float misalignment = 1f - Mathf.Clamp(uprightness, -1f, 1f);
                    float torque = uprightness >= 0f ? uprightTorque : flipRecoveryTorque;
                    body.AddTorque(axis.normalized * (torque * misalignment), ForceMode.Acceleration);
                }
            }
        }

        /// <summary>Ограничиваем «кувыркание» корпуса на быстрых поворотах (тангаж и крен), не мешая авариям на кочках.</summary>
        private void LimitTumbling()
        {
            if (!limitBodyPitchAndRoll || !IsGrounded)
            {
                return;
            }

            Vector3 angularVelocity = body.angularVelocity;
            float maxTumble = maxTumbleRate * Mathf.Deg2Rad;
            angularVelocity.x = Mathf.Clamp(angularVelocity.x, -maxTumble, maxTumble);
            angularVelocity.z = Mathf.Clamp(angularVelocity.z, -maxTumble, maxTumble);
            body.angularVelocity = angularVelocity;
        }

        private Vector3 GetFlatVelocity()
        {
            Vector3 velocity = body.velocity;
            return new Vector3(velocity.x, 0f, velocity.z);
        }

        #endregion

        #region Сброс и визуальные колёса

        private void PerformReset()
        {
            body.velocity = Vector3.zero;
            body.angularVelocity = Vector3.zero;

            Vector3 position = resetPoint != null ? resetPoint.position : startPosition;
            float yaw = resetPoint != null ? resetPoint.eulerAngles.y : startRotation.eulerAngles.y;

            body.position = position + Vector3.up * 0.1f;
            body.rotation = Quaternion.Euler(0f, yaw, 0f);

            currentYawRate = 0f;
            SetForkHeight(startForkHeight);
        }

        private void InitializeWheelVisuals()
        {
            if (wheelVisuals == null)
            {
                return;
            }

            for (int i = 0; i < wheelVisuals.Length; i++)
            {
                WheelVisual wheel = wheelVisuals[i];
                if (wheel == null || wheel.wheel == null)
                {
                    continue;
                }

                wheel.baseRotation = wheel.wheel.localRotation;
                wheel.rollAngle = 0f;
                wheel.initialized = true;
            }
        }

        private void UpdateWheelVisuals(float deltaTime)
        {
            if (wheelVisuals == null)
            {
                return;
            }

            float forwardSpeed = Vector3.Dot(GetFlatVelocity(), transform.forward);

            for (int i = 0; i < wheelVisuals.Length; i++)
            {
                WheelVisual wheel = wheelVisuals[i];
                if (wheel == null || wheel.wheel == null)
                {
                    continue;
                }

                if (!wheel.initialized)
                {
                    wheel.baseRotation = wheel.wheel.localRotation;
                    wheel.initialized = true;
                }

                float angleDelta = (forwardSpeed / Mathf.Max(0.02f, wheel.radius)) * Mathf.Rad2Deg * deltaTime;
                wheel.rollAngle = Mathf.Repeat(wheel.rollAngle + angleDelta, 360f);

                float steerAngle = wheel.steerable ? currentVisualSteerAngle : 0f;
                wheel.wheel.localRotation =
                    wheel.baseRotation *
                    Quaternion.AngleAxis(steerAngle, Vector3.up) *
                    Quaternion.AngleAxis(wheel.rollAngle, Vector3.right);
            }
        }

        #endregion
    }
}
