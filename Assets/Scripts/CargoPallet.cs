using System;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Тип груза на паллете. Значение None (0) означает «тип не назначен»:
    /// такие паллеты зоны сортировки не принимают.
    /// </summary>
    public enum CargoType
    {
        None = 0,
        Boxes = 1,
        Barrels = 2,
        Construction = 3
    }

    /// <summary>
    /// Вешается на паллету с грузом. Хранит тип груза и отдаёт наружу удобные данные:
    /// регистрацию в <see cref="GameManager"/>, состояние захвата вилами погрузчика
    /// и событие «паллета засчитана».
    ///
    /// Физику паллеты не трогает — только состояние захвата: <see cref="LockTo"/> переводит
    /// Rigidbody в kinematic (паллета становится физическим ребёнком каретки вил),
    /// <see cref="ReleaseFromLock"/> возвращает обычную физику, чтобы груз можно было выгрузить.
    ///
    /// Порядок объектов: CargoPallet (Rigidbody + BoxCollider + CargoPallet) с декором внутри.
    /// </summary>
    [DisallowMultipleComponent]
    [RequireComponent(typeof(Rigidbody))]
    [AddComponentMenu("Kakayato/Cargo Pallet")]
    public class CargoPallet : MonoBehaviour
    {
        [Header("Груз")]
        [SerializeField, Tooltip("Тип груза на паллете (ящики / бочки / стройматериалы). None — тип не назначен.")]
        private CargoType cargoType = CargoType.None;

        [Header("Физика и учёт")]
        [SerializeField, Tooltip("Начисляемые очки за правильную сортировку. Зона может переопределить своё значение.")]
        private int scoreValue = 10;

        [SerializeField, Tooltip("Толкается ли паллета погрузчиком и другими объектами.")]
        private bool isPushable = true;

        [SerializeField, Tooltip("Масса паллеты вместе с грузом, кг.")]
        private float mass = 30f;

        [Header("Поведение")]
        [SerializeField, Tooltip("Автоматически регистрироваться в GameManager при старте (нужно для подсчёта оставшихся паллет).")]
        private bool autoRegisterInGameManager = true;

        [SerializeField, Tooltip("Уничтожать объект после правильной сортировки.")]
        private bool destroyAfterSorting = true;

        [SerializeField, Tooltip("Если объект не уничтожается — отключать коллайдеры и физику, чтобы паллета не мешала.")]
        private bool disablePhysicsAfterSorting = true;

        [SerializeField, Tooltip("Пометить объект уничтоженным (SetActive(false)) вместо Destroy — например, для будущего пула объектов.")]
        private bool deactivateInsteadOfDestroy = false;

        private Rigidbody body;
        private Collider[] colliders;

        private bool isSorted;
        private bool wasRegistered;
        private bool isLocked;
        private ForkliftController carrier;
        private float lastReleaseTime = -1000f;
        private Vector3 homePosition;
        private Quaternion homeRotation;
        private Transform homeParent;

        /// <summary>Тип груза на паллете.</summary>
        public CargoType Cargo { get { return cargoType; } }

        /// <summary>Очки за правильную сортировку.</summary>
        public int ScoreValue { get { return scoreValue; } }

        /// <summary>Масса паллеты вместе с грузом, кг.</summary>
        public float Mass { get { return mass; } }

        /// <summary>Rigidbody паллеты (может быть null, если тело удалено).</summary>
        public Rigidbody Body { get { return body; } }

        /// <summary>Паллета уже засчитана в какой-либо зоне.</summary>
        public bool IsSorted { get { return isSorted; } }

        /// <summary>Паллета зарегистрирована в GameManager.</summary>
        public bool IsRegistered { get { return wasRegistered; } }

        /// <summary>Паллета захвачена вилами (kinematic и следует за кареткой).</summary>
        public bool IsLocked { get { return isLocked; } }

        /// <summary>Погрузчик, который сейчас держит паллету (null, если паллета свободна).</summary>
        public ForkliftController Carrier { get { return carrier; } }

        /// <summary>Время (Time.time) последнего отпускания паллеты вилами.</summary>
        public float LastReleaseTime { get { return lastReleaseTime; } }

        /// <summary>Родитель, в котором паллета жила до захвата (для возврата после выгрузки).</summary>
        public Transform HomeParent { get { return homeParent; } }

        /// <summary>
        /// Расстояние от точки объекта до низа его коллайдеров, м. Нужно погрузчику,
        /// чтобы посадить паллету низом ровно на верхнюю плоскость вил.
        /// </summary>
        public float BottomOffset
        {
            get
            {
                if (colliders == null || colliders.Length == 0)
                {
                    return 0f;
                }

                float minY = float.MaxValue;
                bool anyCollider = false;

                for (int i = 0; i < colliders.Length; i++)
                {
                    Collider collider = colliders[i];
                    if (collider == null || !collider.enabled)
                    {
                        continue;
                    }

                    anyCollider = true;

                    if (collider.bounds.min.y < minY)
                    {
                        minY = collider.bounds.min.y;
                    }
                }

                return anyCollider ? Mathf.Max(0f, transform.position.y - minY) : 0f;
            }
        }

        /// <summary>Fired после правильной сортировки. Аргумент — эта паллета.</summary>
        public event Action<CargoPallet> Sorted;

        private void Awake()
        {
            body = GetComponent<Rigidbody>();
            colliders = GetComponentsInChildren<Collider>(true);

            if (body != null)
            {
                body.isKinematic = !isPushable;
                body.mass = Mathf.Max(1f, mass);
            }

            homePosition = transform.position;
            homeRotation = transform.rotation;
            homeParent = transform.parent;
        }

        private void OnEnable()
        {
            RegisterInManager();
        }

        private void OnDisable()
        {
            if (isLocked)
            {
                // Паллету выключили/удалили, пока её держали вилы — снимаем захват,
                // чтобы погрузчик не тянул за собой мёртвую ссылку.
                ReleaseFromLock();
            }

            if (wasRegistered && GameManager.Instance != null)
            {
                GameManager.Instance.UnregisterPallet(this);
                wasRegistered = false;
            }
        }

        #region Публичный API

        /// <summary>Сменить тип груза на лету (например, при генерации уровня).</summary>
        public void SetCargoType(CargoType newType)
        {
            cargoType = newType;
        }

        /// <summary>Сменить очки за паллету.</summary>
        public void SetScoreValue(int value)
        {
            scoreValue = Mathf.Max(0, value);
        }

        /// <summary>Включить/выключить толкаемость (переводит Rigidbody в kinematic / обратно, если паллета не на вилах).</summary>
        public void SetPushable(bool value)
        {
            isPushable = value;

            if (body != null && !isLocked)
            {
                body.isKinematic = !value;
            }
        }

        /// <summary>Зарегистрировать паллету в GameManager, если она этого ещё не сделала.</summary>
        public void RegisterInManager()
        {
            if (!autoRegisterInGameManager || wasRegistered || isSorted)
            {
                return;
            }

            if (GameManager.Instance != null)
            {
                GameManager.Instance.RegisterPallet(this);
                wasRegistered = true;
            }
        }

        /// <summary>
        /// Взять паллету на вилы: Rigidbody становится kinematic, паллета помечается захваченной.
        /// Позицию/родителя назначает вызывающий (ForkliftController) — он единственный,
        /// кто знает про каретку и её систему координат.
        /// </summary>
        public void LockTo(ForkliftController owner)
        {
            if (isLocked || isSorted)
            {
                return;
            }

            if (body != null)
            {
                body.velocity = Vector3.zero;
                body.angularVelocity = Vector3.zero;
                body.isKinematic = true;
                body.detectCollisions = true;
            }

            isLocked = true;
            carrier = owner;
        }

        /// <summary>
        /// Отпустить паллету: обычная физика возвращается, запоминается время отпускания
        /// (погрузчик использует его как паузу перед повторным захватом).
        /// </summary>
        public void ReleaseFromLock()
        {
            isLocked = false;
            carrier = null;
            lastReleaseTime = Time.time;

            if (body != null && !isSorted)
            {
                body.isKinematic = !isPushable;
            }
        }

        /// <summary>Паллету держит другой погрузчик (не тот, что спрашивает).</summary>
        public bool IsLockedByOther(ForkliftController owner)
        {
            return isLocked && carrier != null && carrier != owner;
        }

        /// <summary>Правильная сортировка: очки, событие, отключение физики/уничтожение. Вызывается из <see cref="SortingZone"/>.</summary>
        public void MarkAsSorted()
        {
            if (isSorted)
            {
                return;
            }

            isSorted = true;

            if (isLocked)
            {
                ReleaseFromLock();
            }

            if (body != null)
            {
                body.isKinematic = true;
                body.detectCollisions = false;
                body.velocity = Vector3.zero;
                body.angularVelocity = Vector3.zero;
            }

            // Сначала событие — внешние системы (VFX, звук, UI) успевают отреагировать до удаления.
            if (Sorted != null)
            {
                Sorted(this);
            }

            if (disablePhysicsAfterSorting)
            {
                if (colliders != null)
                {
                    for (int i = 0; i < colliders.Length; i++)
                    {
                        if (colliders[i] != null)
                        {
                            colliders[i].enabled = false;
                        }
                    }
                }
            }

            if (destroyAfterSorting)
            {
                if (deactivateInsteadOfDestroy)
                {
                    gameObject.SetActive(false);
                }
                else
                {
                    Destroy(gameObject, 0.05f);
                }
            }
        }

        /// <summary>Вернуть паллету в стартовое положение (не считаясь отсортированной). Только если она ещё не уничтожена.</summary>
        public void ResetToHome()
        {
            isSorted = false;

            if (isLocked)
            {
                ReleaseFromLock();
            }

            if (colliders != null)
            {
                for (int i = 0; i < colliders.Length; i++)
                {
                    if (colliders[i] != null)
                    {
                        colliders[i].enabled = true;
                    }
                }
            }

            transform.SetParent(homeParent, true);
            transform.SetPositionAndRotation(homePosition, homeRotation);

            if (body != null)
            {
                body.detectCollisions = true;
                body.isKinematic = !isPushable;
                body.velocity = Vector3.zero;
                body.angularVelocity = Vector3.zero;
                body.position = homePosition;
                body.rotation = homeRotation;
            }
        }

        #endregion

        private void OnValidate()
        {
            scoreValue = Mathf.Max(0, scoreValue);
            mass = Mathf.Max(1f, mass);
        }
    }
}
