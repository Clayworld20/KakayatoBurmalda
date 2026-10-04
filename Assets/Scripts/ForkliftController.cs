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
    /// они физически поднимают и толкают кубики.
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

        #endregion

        #region Ссылки

        [Header("Ссылки")]
        [Tooltip("Корень каретки с вилами. Обязательное поле: высота вил меняется у этого Transform.")]
        [SerializeField] private Transform forkCarriage;

        [Tooltip("Пустышка у днища корпуса для проверки заземления. Если пусто — берётся центр объекта.")]
        [SerializeField] private Transform groundCheck;

        [Tooltip("Шарнир наклона мачты (необязательно). Вращается по локальному X.")]
        [SerializeField] private Transform mastTiltPivot;

        [Tooltip("Точка возврата при сбросе погрузчика (клавиша R). Если пусто — позиция на момент старта.")]
        [SerializeField] private Transform resetPoint;

        [Tooltip("Слои, которые считаются «землёй» для проверки заземления. Оставьте «Everything» — при старте слой Ground будет найден по имени.")]
        [SerializeField] private LayerMask groundLayers = ~0;

        [SerializeField, Min(0.05f), Tooltip("Длина проверки заземления, м (сфера идёт вниз из GroundCheck).")]
        private float groundCheckDistance = 0.75f;

        [SerializeField, Min(0.01f), Tooltip("Радиус сферы проверки заземления, м.")]
        private float groundCheckRadius = 0.22f;

        [SerializeField, Tooltip("Если маска = «Everything», попробовать найти слой Ground по имени, чтобы никогда не цеплять корпус и кубики.")]
        private bool autoResolveGroundLayer = true;

        [Tooltip("Слои, на которых ищутся кубики при удержании на вилах.")]
        [SerializeField] private LayerMask cubeLayers = ~0;

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

        #region Удержание кубиков

        [Header("Удержание кубиков на вилах")]
        [SerializeField, Tooltip("Подмешивать скорость кубику, чтобы он не «съезжал» с вил на поворотах и кочках.")]
        private bool carryAssist = true;

        [SerializeField, Tooltip("Центр объёма захвата в локальных координатах каретки.")]
        private Vector3 carryVolumeCenter = new Vector3(0f, 0.3f, 0.3f);

        [SerializeField, Tooltip("Размер объёма захвата в локальных координатах каретки.")]
        private Vector3 carryVolumeSize = new Vector3(1.6f, 0.9f, 1.8f);

        [SerializeField, Min(0f), Tooltip("Сила подмешивания скорости кубика (1/с).")]
        private float carryAssistStrength = 9f;

        [SerializeField, Min(0f), Tooltip("Прижим кубика к вилам, м/с².")]
        private float carryAssistDownforce = 2.5f;

        [SerializeField, Min(0f), Tooltip("Гашение вращения кубика на вилах (1/с).")]
        private float carryAssistTorqueDamping = 5f;

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
        private readonly RaycastHit[] groundHitsBuffer = new RaycastHit[8];
        private readonly List<CubeProperty> carriedCubes = new List<CubeProperty>();

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
        private int carriedCubesInVolume;
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

        /// <summary>Есть ли кубик в объёме вил.</summary>
        public bool IsCarryingCube { get { return carriedCubesInVolume > 0; } }

        /// <summary>Текущая высота вил (локальная Y каретки).</summary>
        public float ForkHeight { get { return currentForkHeight; } }

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

        /// <summary>Transform каретки вил (для внешних систем, например крепления кубика).</summary>
        public Transform ForkCarriage { get { return forkCarriage; } }

        #endregion

        #region Unity-сообщения

        private void Awake()
        {
            body = GetComponent<Rigidbody>();
            body.interpolation = interpolation;

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
            UpdateCarryVolume(deltaTime);
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
            carriedCubes.Clear();
            carriedCubesInVolume = 0;
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

        /// <summary>Лежит ли конкретный кубик сейчас в объёме вил этого погрузчика.</summary>
        public bool IsCarrying(CubeProperty cube)
        {
            return cube != null && carriedCubes.Contains(cube);
        }

        /// <summary>Скопировать список кубиков, которые лежат на вилах сейчас.</summary>
        public void GetCarriedCubes(List<CubeProperty> results)
        {
            if (results == null)
            {
                return;
            }

            results.Clear();
            results.AddRange(carriedCubes);
        }

        /// <summary>Есть ли кубик на вилах хотя бы у одного погрузчика сцены. Используется зонами сортировки.</summary>
        public static bool IsCubeCarriedByAnyForklift(CubeProperty cube)
        {
            if (cube == null)
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

                if (forklift.IsCarrying(cube))
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
            // корпус) и кубики, даже если они случайно попали в маску.
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

                // Кубики — это груз, а не опора.
                if (hitCollider.GetComponentInParent<CubeProperty>() != null)
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
        /// собственный корпус и кубики.
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
        /// Ищем кубики в объёме вил. Помимо подсветки состояния (IsCarryingCube),
        /// опционально подмешиваем им скорость корпуса — иначе на поворотах груз улетает с вил.
        /// </summary>
        private void UpdateCarryVolume(float deltaTime)
        {
            carriedCubesInVolume = 0;
            carriedCubes.Clear();

            if (forkCarriage == null)
            {
                return;
            }

            Vector3 center = forkCarriage.TransformPoint(carryVolumeCenter);
            Vector3 halfExtents = carryVolumeSize * 0.5f;

            int count = Physics.OverlapBoxNonAlloc(
                center,
                halfExtents,
                overlapBuffer,
                forkCarriage.rotation,
                cubeLayers,
                QueryTriggerInteraction.Ignore);

            for (int i = 0; i < count; i++)
            {
                Collider other = overlapBuffer[i];
                if (other == null)
                {
                    continue;
                }

                CubeProperty cube = other.GetComponentInParent<CubeProperty>();
                if (cube == null || cube.IsSorted)
                {
                    continue;
                }

                carriedCubesInVolume++;
                carriedCubes.Add(cube);

                if (carryAssist)
                {
                    ApplyCarryAssist(cube, deltaTime);
                }
            }
        }

        private void ApplyCarryAssist(CubeProperty cube, float deltaTime)
        {
            Rigidbody cubeBody = cube.Body;
            if (cubeBody == null || cubeBody.isKinematic)
            {
                return;
            }

            float blend = Mathf.Clamp01(carryAssistStrength * deltaTime);

            // Горизонтальную скорость кубика подтягиваем к скорости погрузчика, вертикаль не трогаем —
            // кубик должен свободно ложиться на вилы и падать с них.
            Vector3 relativeVelocity = cubeBody.velocity - body.velocity;
            relativeVelocity.y = 0f;
            cubeBody.AddForce(-relativeVelocity * blend, ForceMode.VelocityChange);

            if (carryAssistDownforce > 0f)
            {
                cubeBody.AddForce(-transform.up * carryAssistDownforce, ForceMode.Acceleration);
            }

            if (carryAssistTorqueDamping > 0f)
            {
                float torqueBlend = Mathf.Clamp01(carryAssistTorqueDamping * deltaTime);
                Vector3 relativeAngular = cubeBody.angularVelocity - body.angularVelocity;
                cubeBody.angularVelocity = cubeBody.angularVelocity - relativeAngular * torqueBlend;
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
                "вилы={13:F2} м, FPS-физика={14:F0} Гц, кубиков на вилах={15}.",
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
                carriedCubesInVolume),
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
