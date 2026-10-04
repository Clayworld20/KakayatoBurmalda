using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Камера от третьего лица для погрузчика. Живёт в корне сцены (не ребёнок погрузчика),
    /// поэтому её не трясёт от физики и поворотов корпуса:
    ///
    ///   * позиция догоняется через <see cref="Vector3.SmoothDamp"/> по точке «за спиной и выше»;
    ///   * курс камеры плавно доворачивается за направлением движения робота
    ///     (<see cref="Mathf.SmoothDampAngle"/>), а взгляд — через <see cref="Quaternion.Slerp"/>;
    ///   * высота ограничена снизу, чтобы камера не уходила под землю.
    ///
    /// Скрипт не читает ввод — мышь/геймпад можно добавить снаружи через <see cref="SetTarget"/>
    /// и публичные поля-настройки.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Kakayato/Camera Follow")]
    public class CameraFollow : MonoBehaviour
    {
        [Header("Цель")]
        [SerializeField, Tooltip("Погрузчик, за которым следит камера. Если пусто — ищется на сцене при старте.")]
        private Transform target;

        [SerializeField, Tooltip("Искать погрузчик на сцене автоматически, если цель не назначена.")]
        private bool autoFindTarget = true;

        [Header("Позиция")]
        [SerializeField, Tooltip("Смещение камеры в системе координат курса: X — вправо, Y — вверх, Z — назад.")]
        private Vector3 offset = new Vector3(0f, 4.6f, -8.6f);

        [SerializeField, Min(0f), Tooltip("Высота точки, вокруг которой вращается камера (примерно кабина погрузчика), м.")]
        private float pivotHeight = 1.5f;

        [SerializeField, Min(0.01f), Tooltip("Время сглаживания позиции (SmoothDamp), с.")]
        private float positionSmoothTime = 0.3f;

        [SerializeField, Min(0.1f), Tooltip("Максимальная скорость догона позиции, м/с.")]
        private float maxFollowSpeed = 60f;

        [Header("Поворот")]
        [SerializeField, Min(0.05f), Tooltip("Время сглаживания доворота камеры вслед за курсом погрузчика, с.")]
        private float yawSmoothTime = 0.45f;

        [SerializeField, Min(0.1f), Tooltip("Резкость доворота взгляда (Quaternion.Slerp), 1/с.")]
        private float rotationSharpness = 6f;

        [SerializeField, Tooltip("Смещение точки взгляда от базы погрузчика: чуть выше и вперёд — видно вилы и груз.")]
        private Vector3 lookOffset = new Vector3(0f, 1.3f, 1.8f);

        [Header("Ограничения")]
        [SerializeField, Min(0f), Tooltip("Минимальная высота камеры над землёй, м.")]
        private float minHeight = 1.4f;

        [SerializeField, Tooltip("Мгновенно встать на место при старте (без пролёта из начала координат).")]
        private bool snapOnStart = true;

        private float followYaw;
        private float yawVelocity;
        private Vector3 positionVelocity;
        private bool initialized;

        /// <summary>Текущая цель камеры (погрузчик).</summary>
        public Transform Target { get { return target; } }

        /// <summary>Назначить цель (например, после респавна или смены техники).</summary>
        public void SetTarget(Transform newTarget)
        {
            target = newTarget;
            initialized = false;
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

        /// <summary>Мгновенно поставить камеру на расчётное место (старт, респавн, генерация сцены).</summary>
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
    }
}
