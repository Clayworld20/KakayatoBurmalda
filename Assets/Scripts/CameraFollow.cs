using System.Globalization;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>Готовые позы камеры, между которыми можно переключаться в меню (F1).</summary>
    public enum CameraPreset
    {
        /// <summary>Кабина водителя: вилы, скос и груз видны полностью — рабочая поза.</summary>
        Cabin,

        /// <summary>Сзади-сверху: видно машину целиком, вилы закрыты кабиной.</summary>
        Chase,

        /// <summary>Высокая: сверху видно и машину, и вилы, и площадку вокруг.</summary>
        High
    }

    /// <summary>
    /// Камера за погрузчиком. Живёт в корне сцены (не ребёнок погрузчика), поэтому её не трясёт
    /// от физики корпуса:
    ///
    ///   * позиция догоняется через <see cref="Vector3.SmoothDamp"/> по точке «смещение от базы»;
    ///   * курс плавно доворачивается за корпусом (<see cref="Mathf.SmoothDampAngle"/>);
    ///   * взгляд доворачивается через <see cref="Quaternion.Slerp"/> на точку перед погрузчиком;
    ///   * высота ограничена снизу, чтобы камера не уходила под землю.
    ///
    /// Поза по умолчанию — «кабина»: камера стоит у лобового стекла, над капотом. Из-за спины
    /// (сзади-сверху) вилы не видны: их закрывают корпус, кабина и защитная решётка — проверено
    /// расчётом по фактической геометрии модели (Tools/camera_check.py в репозитории). Поза по умолчанию —
    /// рабочая: камера сбоку над вилами, ось смотрит вперёд-вниз на кончики вил, поэтому обе вилы, паллета,
    /// груз и дорога остаются в кадре. Из-за спины (сзади-сверху) вилы не видны: их закрывают корпус,
    /// кабина и защитная решётка. Позу можно менять в игре по клавише F1
    /// (компонент <see cref="CameraSettingsMenu"/>, он вешается автоматически).
    ///
    /// Настройки, подобранные в меню, можно сохранить (кнопка «Сохранить»): в редакторе они
    /// кладутся в <c>EditorPrefs</c> и подхватываются при следующем запуске и при генерации сцены.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Kakayato/Camera Follow")]
    public class CameraFollow : MonoBehaviour
    {
        /// <summary>Префикс ключей EditorPrefs, в которых живут сохранённые настройки камеры.</summary>
        public const string EditorPrefsSettingsKey = "Kakayato.Forklift.Camera.Settings";

        [Header("Цель")]
        [SerializeField, Tooltip("Погрузчик, за которым следит камера. Если пусто — ищется на сцене при старте.")]
        private Transform target;

        [SerializeField, Tooltip("Искать погрузчик на сцене автоматически, если цель не назначена.")]
        private bool autoFindTarget = true;

        [Header("Позиция")]
        [SerializeField,
         Tooltip("Смещение камеры в системе координат курса погрузчика: X — вправо, Y — вверх, Z — вперёд (плюс) или назад (минус).\n" +
                 "По умолчанию — рабочая поза сбоку над вилами (1.6, 3.0, 0.6): видны обе вилы, паллета, груз и дорога.\n" +
                 "Классическая поза «сзади-сверху» (0, 4.6, -8.6) не подходит: вилы закрывает корпус с кабиной и решёткой.")]
        private Vector3 offset = new Vector3(1.6f, 3f, 0.6f);

        [SerializeField, Min(0f), Tooltip("Высота точки, вокруг которой вращается камера, м (0 — вокруг базы погрузчика).")]
        private float pivotHeight = 0f;

        [SerializeField, Min(0.01f), Tooltip("Время сглаживания позиции (SmoothDamp), с. Для рабочей позы — почти жёстко (0.03).")]
        private float positionSmoothTime = 0.03f;

        [SerializeField, Min(0.1f), Tooltip("Максимальная скорость догона позиции, м/с.")]
        private float maxFollowSpeed = 60f;

        [Header("Поворот")]
        [SerializeField, Min(0.01f), Tooltip("Время сглаживания доворота камеры вслед за курсом погрузчика, с.")]
        private float yawSmoothTime = 0.05f;

        [SerializeField, Min(0.1f), Tooltip("Резкость доворота взгляда (Quaternion.Slerp), 1/с.")]
        private float rotationSharpness = 9f;

        [SerializeField, Tooltip("Смещение точки взгляда от базы погрузчика. По умолчанию ось уходит вперёд-вниз-влево, " +
                                 "в район кончиков вил (0, 1.0, 4.0), поэтому вилы всегда в кадре.")]
        private Vector3 lookOffset = new Vector3(-1.6f, -2f, 3.4f);

        [Header("Ограничения")]
        [SerializeField, Min(0f), Tooltip("Минимальная высота камеры над землёй, м.")]
        private float minHeight = 1.2f;

        [SerializeField, Tooltip("Вертикальный FOV камеры. 0 — не трогать значение из сцены.")]
        private float fieldOfView = 62f;

        [SerializeField, Tooltip("Мгновенно встать на место при старте (без пролёта из начала координат).")]
        private bool snapOnStart = true;

        [Header("Сервис")]
        [SerializeField, Tooltip("Добавить меню настройки камеры (F1), если его нет на этом объекте.")]
        private bool createSettingsMenu = true;

        [SerializeField, Tooltip("В редакторе подхватывать настройки, сохранённые кнопкой «Сохранить» в меню F1.")]
        private bool useSavedEditorSettings = true;

        private float followYaw;
        private float yawVelocity;
        private Vector3 positionVelocity;
        private bool initialized;

        private Vector3 initialOffset;
        private float initialPivotHeight;
        private Vector3 initialLookOffset;
        private float initialPositionSmoothTime;
        private float initialYawSmoothTime;
        private float initialRotationSharpness;
        private float initialMinHeight;
        private float initialFieldOfView;
        private bool initialCaptured;

        #region Публичные свойства

        /// <summary>Текущая цель камеры (погрузчик).</summary>
        public Transform Target { get { return target; } }

        /// <summary>Смещение камеры в системе координат курса: X — вправо, Y — вверх, Z — вперёд/назад.</summary>
        public Vector3 Offset
        {
            get { return offset; }
            set
            {
                offset = new Vector3(
                    Mathf.Clamp(value.x, -30f, 30f),
                    Mathf.Clamp(value.y, -5f, 40f),
                    Mathf.Clamp(value.z, -40f, 40f));
            }
        }

        /// <summary>Высота точки, вокруг которой вращается камера, м.</summary>
        public float PivotHeight
        {
            get { return pivotHeight; }
            set { pivotHeight = Mathf.Clamp(value, 0f, 20f); }
        }

        /// <summary>Смещение точки взгляда от базы погрузчика.</summary>
        public Vector3 LookOffset
        {
            get { return lookOffset; }
            set
            {
                lookOffset = new Vector3(
                    Mathf.Clamp(value.x, -30f, 30f),
                    Mathf.Clamp(value.y, -20f, 20f),
                    Mathf.Clamp(value.z, -40f, 40f));
            }
        }

        /// <summary>Время сглаживания позиции, с.</summary>
        public float PositionSmoothTime
        {
            get { return positionSmoothTime; }
            set { positionSmoothTime = Mathf.Clamp(value, 0.01f, 5f); }
        }

        /// <summary>Время сглаживания доворота за курсом, с.</summary>
        public float YawSmoothTime
        {
            get { return yawSmoothTime; }
            set { yawSmoothTime = Mathf.Clamp(value, 0.01f, 5f); }
        }

        /// <summary>Резкость доворота взгляда, 1/с.</summary>
        public float RotationSharpness
        {
            get { return rotationSharpness; }
            set { rotationSharpness = Mathf.Clamp(value, 0.1f, 60f); }
        }

        /// <summary>Максимальная скорость догона позиции, м/с.</summary>
        public float MaxFollowSpeed
        {
            get { return maxFollowSpeed; }
            set { maxFollowSpeed = Mathf.Max(0.1f, value); }
        }

        /// <summary>Минимальная высота камеры над землёй, м.</summary>
        public float MinHeight
        {
            get { return minHeight; }
            set { minHeight = Mathf.Clamp(value, 0f, 50f); }
        }

        /// <summary>Вертикальный FOV камеры (0 — значение не применяется).</summary>
        public float FieldOfView
        {
            get { return fieldOfView; }
            set
            {
                fieldOfView = value <= 0f ? 0f : Mathf.Clamp(value, 20f, 120f);
                ApplyFieldOfView();
            }
        }

        #endregion

        #region Unity-сообщения

        private void Awake()
        {
            CaptureInitialSettings();

#if UNITY_EDITOR
            if (useSavedEditorSettings)
            {
                LoadSettingsFromEditorPrefs();
            }
#endif

            ApplyFieldOfView();
        }

        private void Start()
        {
            if (target == null && autoFindTarget)
            {
                ForkliftController forklift = FindObjectOfType<ForkliftController>();
                if (forklift != null)
                {
                    target = forklift.transform;
                }
            }

            EnsureSettingsMenu();

            if (snapOnStart)
            {
                SnapToTarget();
            }
        }

        private void LateUpdate()
        {
            if (target == null)
            {
                return;
            }

            float deltaTime = Time.deltaTime;

            if (deltaTime <= 0f)
            {
                return;
            }

            if (!initialized)
            {
                SnapToTarget();
                return;
            }

            // Курс камеры плавно догоняет курс погрузчика: без рывков на резких поворотах.
            float targetYaw = target.eulerAngles.y;
            followYaw = Mathf.SmoothDampAngle(followYaw, targetYaw, ref yawVelocity, yawSmoothTime, Mathf.Infinity, deltaTime);
            Quaternion yawRotation = Quaternion.Euler(0f, followYaw, 0f);

            Vector3 pivot = target.position + Vector3.up * pivotHeight;
            Vector3 desiredPosition = pivot + yawRotation * offset;

            if (desiredPosition.y < minHeight)
            {
                desiredPosition.y = minHeight;
            }

            transform.position = Vector3.SmoothDamp(
                transform.position,
                desiredPosition,
                ref positionVelocity,
                positionSmoothTime,
                maxFollowSpeed,
                deltaTime);

            // Взгляд мягко доворачивается на точку перед погрузчиком.
            Vector3 lookPoint = pivot + yawRotation * lookOffset;
            Vector3 lookDirection = lookPoint - transform.position;

            if (lookDirection.sqrMagnitude > 0.0001f)
            {
                Quaternion desiredRotation = Quaternion.LookRotation(lookDirection, Vector3.up);
                float blend = 1f - Mathf.Exp(-rotationSharpness * deltaTime);
                transform.rotation = Quaternion.Slerp(transform.rotation, desiredRotation, blend);
            }
        }

        #endregion

        #region Публичный API

        /// <summary>Назначить цель (например, после респавна или смены техники).</summary>
        public void SetTarget(Transform newTarget)
        {
            target = newTarget;
            initialized = false;
        }

        /// <summary>Мгновенно поставить камеру на расчётное место (старт, респавн, смена пресета).</summary>
        [ContextMenu("Привязаться к цели сейчас")]
        public void SnapToTarget()
        {
            if (target == null)
            {
                return;
            }

            followYaw = target.eulerAngles.y;
            yawVelocity = 0f;
            positionVelocity = Vector3.zero;

            Quaternion yawRotation = Quaternion.Euler(0f, followYaw, 0f);
            Vector3 pivot = target.position + Vector3.up * pivotHeight;
            Vector3 desiredPosition = pivot + yawRotation * offset;

            if (desiredPosition.y < minHeight)
            {
                desiredPosition.y = minHeight;
            }

            transform.position = desiredPosition;

            Vector3 lookPoint = pivot + yawRotation * lookOffset;
            Vector3 lookDirection = lookPoint - desiredPosition;

            if (lookDirection.sqrMagnitude > 0.0001f)
            {
                transform.rotation = Quaternion.LookRotation(lookDirection, Vector3.up);
            }

            initialized = true;
        }

        /// <summary>Применить готовую позу камеры (кнопки-пресеты в меню F1).</summary>
        public void ApplyPreset(CameraPreset preset)
        {
            switch (preset)
            {
                case CameraPreset.Cabin:
                    // Рабочий обзор (по умолчанию): камера сбоку над вилами, ось смотрит на кончики вил.
                    // Проверка расчётом: видны обе вилы, середина вил, паллета, верх груза и дорога.
                    offset = new Vector3(1.6f, 3f, 0.6f);
                    pivotHeight = 0f;
                    lookOffset = new Vector3(-1.6f, -2f, 3.4f);
                    positionSmoothTime = 0.03f;
                    yawSmoothTime = 0.05f;
                    rotationSharpness = 9f;
                    minHeight = 1.2f;
                    break;

                case CameraPreset.Chase:
                    // Классический вид сзади-сверху: видна машина целиком, но вилы закрыты корпусом,
                    // кабиной и защитной решёткой — для работы с грузом поза не подходит.
                    offset = new Vector3(0f, 4.6f, -7.2f);
                    pivotHeight = 1.5f;
                    lookOffset = new Vector3(0f, 0.9f, 3.2f);
                    positionSmoothTime = 0.3f;
                    yawSmoothTime = 0.45f;
                    rotationSharpness = 6f;
                    minHeight = 1.4f;
                    break;

                case CameraPreset.High:
                    // Высокая рабочая поза: та же сторона, что и «Рабочая», но выше — видно площадку
                    // вокруг и вилы; линия горизонта при этом уходит из кадра (камера смотрит вниз).
                    offset = new Vector3(1.6f, 4.6f, 1f);
                    pivotHeight = 0f;
                    lookOffset = new Vector3(-1.6f, -3.2f, 3.4f);
                    positionSmoothTime = 0.35f;
                    yawSmoothTime = 0.5f;
                    rotationSharpness = 6f;
                    minHeight = 1.5f;
                    break;
            }

            yawVelocity = 0f;
            positionVelocity = Vector3.zero;
            SnapToTarget();
        }

        /// <summary>Вернуть позу, которая была в сцене на момент запуска (кнопка «Сбросить» в меню F1).</summary>
        public void ResetToInitialSettings()
        {
            if (!initialCaptured)
            {
                return;
            }

            offset = initialOffset;
            pivotHeight = initialPivotHeight;
            lookOffset = initialLookOffset;
            positionSmoothTime = initialPositionSmoothTime;
            yawSmoothTime = initialYawSmoothTime;
            rotationSharpness = initialRotationSharpness;
            minHeight = initialMinHeight;
            fieldOfView = initialFieldOfView;

            ApplyFieldOfView();

            yawVelocity = 0f;
            positionVelocity = Vector3.zero;
            SnapToTarget();
        }

        #endregion

        #region Служебное

        private void CaptureInitialSettings()
        {
            initialOffset = offset;
            initialPivotHeight = pivotHeight;
            initialLookOffset = lookOffset;
            initialPositionSmoothTime = positionSmoothTime;
            initialYawSmoothTime = yawSmoothTime;
            initialRotationSharpness = rotationSharpness;
            initialMinHeight = minHeight;
            initialFieldOfView = fieldOfView;
            initialCaptured = true;

            if (initialFieldOfView <= 1f)
            {
                // Поле FOV не задано — берём текущее значение камеры, чтобы «Сбросить» вернуло его.
                Camera cameraComponent = GetComponent<Camera>();
                if (cameraComponent != null)
                {
                    initialFieldOfView = cameraComponent.fieldOfView;
                }
            }
        }

        private void EnsureSettingsMenu()
        {
            if (!createSettingsMenu)
            {
                return;
            }

            if (GetComponent<CameraSettingsMenu>() == null)
            {
                gameObject.AddComponent<CameraSettingsMenu>();
            }
        }

        private void ApplyFieldOfView()
        {
            if (fieldOfView <= 1f)
            {
                return;
            }

            Camera cameraComponent = GetComponent<Camera>();
            if (cameraComponent != null)
            {
                cameraComponent.fieldOfView = fieldOfView;
            }
        }

        #endregion

        #region Сохранение настроек (только в редакторе)

#if UNITY_EDITOR

        /// <summary>Есть ли сохранённые настройки камеры в EditorPrefs (кнопка «Сохранить» в меню F1).</summary>
        public static bool HasSavedSettings
        {
            get { return UnityEditor.EditorPrefs.HasKey(EditorPrefsSettingsKey); }
        }

        /// <summary>Сохранить текущую позу камеры в EditorPrefs — она подхватится при следующем запуске.</summary>
        public void SaveSettingsToEditorPrefs()
        {
            string[] parts = new string[12];
            parts[0] = offset.x.ToString("R", CultureInfo.InvariantCulture);
            parts[1] = offset.y.ToString("R", CultureInfo.InvariantCulture);
            parts[2] = offset.z.ToString("R", CultureInfo.InvariantCulture);
            parts[3] = pivotHeight.ToString("R", CultureInfo.InvariantCulture);
            parts[4] = lookOffset.x.ToString("R", CultureInfo.InvariantCulture);
            parts[5] = lookOffset.y.ToString("R", CultureInfo.InvariantCulture);
            parts[6] = lookOffset.z.ToString("R", CultureInfo.InvariantCulture);
            parts[7] = positionSmoothTime.ToString("R", CultureInfo.InvariantCulture);
            parts[8] = yawSmoothTime.ToString("R", CultureInfo.InvariantCulture);
            parts[9] = rotationSharpness.ToString("R", CultureInfo.InvariantCulture);
            parts[10] = minHeight.ToString("R", CultureInfo.InvariantCulture);
            parts[11] = fieldOfView.ToString("R", CultureInfo.InvariantCulture);

            UnityEditor.EditorPrefs.SetString(EditorPrefsSettingsKey, string.Join(";", parts));
        }

        /// <summary>Загрузить сохранённую позу камеры. Возвращает false, если сохранять было нечего.</summary>
        public bool LoadSettingsFromEditorPrefs()
        {
            float[] values;

            if (!TryReadSavedValues(out values))
            {
                return false;
            }

            offset = new Vector3(values[0], values[1], values[2]);
            pivotHeight = Mathf.Max(0f, values[3]);
            lookOffset = new Vector3(values[4], values[5], values[6]);
            positionSmoothTime = Mathf.Max(0.01f, values[7]);
            yawSmoothTime = Mathf.Max(0.01f, values[8]);
            rotationSharpness = Mathf.Max(0.1f, values[9]);
            minHeight = Mathf.Max(0f, values[10]);
            fieldOfView = values[11] <= 0f ? 0f : Mathf.Clamp(values[11], 20f, 120f);

            ApplyFieldOfView();
            return true;
        }

        /// <summary>Забыть сохранённые настройки камеры (кнопка «Очистить» в меню F1).</summary>
        public static void ClearSavedSettings()
        {
            UnityEditor.EditorPrefs.DeleteKey(EditorPrefsSettingsKey);
        }

        private static bool TryReadSavedValues(out float[] values)
        {
            values = null;

            if (!UnityEditor.EditorPrefs.HasKey(EditorPrefsSettingsKey))
            {
                return false;
            }

            string raw = UnityEditor.EditorPrefs.GetString(EditorPrefsSettingsKey, string.Empty);

            if (string.IsNullOrEmpty(raw))
            {
                return false;
            }

            string[] parts = raw.Split(';');

            if (parts.Length != 12)
            {
                return false;
            }

            float[] parsed = new float[12];

            for (int i = 0; i < 12; i++)
            {
                if (!float.TryParse(parts[i], NumberStyles.Float, CultureInfo.InvariantCulture, out parsed[i]))
                {
                    return false;
                }
            }

            values = parsed;
            return true;
        }

#endif

        #endregion
    }
}
