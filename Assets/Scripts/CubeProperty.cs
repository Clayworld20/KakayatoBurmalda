using System;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Цвет/тип кубика. Значение по умолчанию (None = -1) означает «тип не назначен»
    /// и используется проверками как «пустое» значение.
    /// </summary>
    public enum CubeColor
    {
        None = -1,
        Red = 0,
        Green = 1,
        Blue = 2,
        Yellow = 3
    }

    /// <summary>
    /// Вешается на кубик. Хранит тип кубика и отдаёт наружу удобные данные:
    /// регистрацию в <see cref="GameManager"/>, исходную позицию/родителя (для респавна)
    /// и событие «кубик засчитан».
    ///
    /// Компонент сам ничего не делает в физике — только данные и учёт.
    /// Порядок объектов: Cube (Rigidbody + BoxCollider + CubeProperty).
    /// </summary>
    [DisallowMultipleComponent]
    [RequireComponent(typeof(Rigidbody))]
    [AddComponentMenu("Kakayato/Cube Property")]
    public class CubeProperty : MonoBehaviour
    {
        [Header("Тип кубика")]
        [SerializeField, Tooltip("Тип/цвет кубика. None = тип не назначен, такие кубики в зонах не засчитываются.")]
        private CubeColor cubeType = CubeColor.None;

        [Header("Физика и учёт")]
        [SerializeField, Tooltip("Начисляемые очки за правильную сортировку. GameManager может переопределить своё значение.")]
        private int scoreValue = 10;

        [SerializeField, Tooltip("Толкается ли кубик погрузчиком и другими кубиками.")]
        private bool isPushable = true;

        [SerializeField, Tooltip("Стартовая масса кубика, кг.")]
        private float mass = 2f;

        [Header("Поведение")]
        [SerializeField, Tooltip("Автоматически регистрироваться в GameManager при старте (нужно для подсчёта оставшихся кубиков).")]
        private bool autoRegisterInGameManager = true;

        [SerializeField, Tooltip("Уничтожать объект после правильной сортировки.")]
        private bool destroyAfterSorting = true;

        [SerializeField, Tooltip("Если объект не уничтожается — отключать коллайдеры и физику, чтобы кубик не мешал.")]
        private bool disablePhysicsAfterSorting = true;

        [SerializeField, Tooltip("Пометить объект уничтоженным (SetActive(false)) вместо Destroy — например, для будущего пула объектов.")]
        private bool deactivateInsteadOfDestroy = false;

        private Rigidbody body;
        private Collider[] colliders;

        private bool isSorted;
        private bool wasRegistered;
        private Vector3 homePosition;
        private Quaternion homeRotation;
        private Transform homeParent;

        /// <summary>Тип/цвет кубика.</summary>
        public CubeColor CubeType { get { return cubeType; } }

        /// <summary>Очки за правильную сортировку.</summary>
        public int ScoreValue { get { return scoreValue; } }

        /// <summary>Rigidbody кубика (может быть null, если тело удалено).</summary>
        public Rigidbody Body { get { return body; } }

        /// <summary>Кубик уже засчитан в какой-либо зоне.</summary>
        public bool IsSorted { get { return isSorted; } }

        /// <summary>Кубик зарегистрирован в GameManager.</summary>
        public bool IsRegistered { get { return wasRegistered; } }

        /// <summary>Fired после правильной сортировки. Аргумент — этот кубик.</summary>
        public event Action<CubeProperty> Sorted;

        private void Awake()
        {
            body = GetComponent<Rigidbody>();
            colliders = GetComponentsInChildren<Collider>(true);

            if (body != null)
            {
                body.isKinematic = !isPushable;
                body.mass = Mathf.Max(0.05f, mass);
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
            if (wasRegistered && GameManager.Instance != null)
            {
                GameManager.Instance.UnregisterCube(this);
                wasRegistered = false;
            }
        }

        #region Публичный API

        /// <summary>Сменить тип кубика на лету (например, при генерации уровня).</summary>
        public void SetCubeType(CubeColor newType)
        {
            cubeType = newType;
        }

        /// <summary>Сменить очки за кубик.</summary>
        public void SetScoreValue(int value)
        {
            scoreValue = Mathf.Max(0, value);
        }

        /// <summary>Включить/выключить толкаемость (переводит Rigidbody в kinematic / обратно).</summary>
        public void SetPushable(bool value)
        {
            isPushable = value;
            if (body != null)
            {
                body.isKinematic = !value;
            }
        }

        /// <summary>Зарегистрировать кубик в GameManager, если он этого ещё не сделал.</summary>
        public void RegisterInManager()
        {
            if (!autoRegisterInGameManager || wasRegistered || isSorted)
            {
                return;
            }

            if (GameManager.Instance != null)
            {
                GameManager.Instance.RegisterCube(this);
                wasRegistered = true;
            }
        }

        /// <summary>Правильная сортировка: очки, событие, отключение физики/уничтожение. Вызывается из <see cref="SortingZone"/>.</summary>
        public void MarkAsSorted()
        {
            if (isSorted)
            {
                return;
            }

            isSorted = true;

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

        /// <summary>Вернуть кубик в стартовое положение (не считаясь отсортированным). Только если он ещё не уничтожен.</summary>
        public void ResetToHome()
        {
            isSorted = false;
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

            if (body != null)
            {
                body.detectCollisions = true;
                body.isKinematic = !isPushable;
            }

            transform.SetParent(homeParent, true);
            transform.SetPositionAndRotation(homePosition, homeRotation);

            if (body != null)
            {
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
            mass = Mathf.Max(0.05f, mass);
        }
    }
}
