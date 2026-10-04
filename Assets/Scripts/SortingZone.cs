using System;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Зона сортировки. Вешается на объект с коллайдером и галочкой IsTrigger.
    /// Хранит целевой тип груза (<see cref="CargoType"/>): если в зону попадает паллета
    /// с <see cref="CargoPallet"/> того же типа — груз засчитывается (очки + Debug.Log +
    /// уничтожение/отключение физики), груз чужого типа — отклоняется (штраф опционально,
    /// событие всегда).
    ///
    /// Раскладка объектов в сцене:
    ///   SortingZone_Boxes (BoxCollider, IsTrigger = true, SortingZone, подсветка зоны)
    ///   SortingZone_Barrels, SortingZone_Construction
    /// </summary>
    [AddComponentMenu("Kakayato/Sorting Zone")]
    public class SortingZone : MonoBehaviour
    {
        [Header("Целевой груз")]
        [SerializeField, Tooltip("Какой тип груза принимает зона. None — зона отключена и ничего не принимает.")]
        private CargoType targetType = CargoType.Boxes;

        [SerializeField, Tooltip("Очки за паллету. Если меньше или равно 0 — берётся ScoreValue самой паллеты.")]
        private int scorePerPallet = 10;

        [SerializeField, Tooltip("Уничтожать паллету после засчитывания (иначе только отключается физика — см. CargoPallet).")]
        private bool destroyPallet = true;

        [SerializeField, Tooltip("Принимать только паллеты, которые приносит погрузчик (груз зафиксирован на вилах). Выключено — принимаем любую паллету, заехавшую в зону.")]
        private bool requireForkliftDelivery = false;

        [Header("Ошибочный груз")]
        [SerializeField, Tooltip("Логировать паллеты неподходящего типа.")]
        private bool logRejectedCargo = true;

        [SerializeField, Tooltip("Штраф за паллету чужого типа (0 — без штрафа).")]
        private int wrongTypePenalty = 0;

        [SerializeField, Tooltip("Отбрасывать паллету чужого типа обратно (лёгкий импульс вверх/наружу от центра зоны).")]
        private bool pushWrongCargoBack = true;

        [SerializeField, Min(0f), Tooltip("Сила отбрасывания паллеты чужого типа.")]
        private float wrongCargoPushForce = 3f;

        [Header("Только для наглядности")]
        [SerializeField, Tooltip("Цвет подсветки зоны в Gizmos (в игре не используется).")]
        private Color gizmoColor = new Color(1f, 0.2f, 0.2f, 0.25f);

        [SerializeField, Tooltip("Считать паллету только один раз, даже если она остаётся в триггере.")]
        private bool countOncePerPallet = true;

        private int acceptedCount;
        private int rejectedCount;

        /// <summary>Fired после засчитывания груза. Аргументы: паллета, зона.</summary>
        public event Action<CargoPallet, SortingZone> CargoAccepted;

        /// <summary>Fired когда в зону попала паллета чужого типа. Аргументы: паллета, зона.</summary>
        public event Action<CargoPallet, SortingZone> CargoRejected;

        /// <summary>Целевой тип груза этой зоны.</summary>
        public CargoType TargetType { get { return targetType; } }

        /// <summary>Сколько паллет зона уже приняла.</summary>
        public int AcceptedCount { get { return acceptedCount; } }

        /// <summary>Сколько паллет зона отклонила.</summary>
        public int RejectedCount { get { return rejectedCount; } }

        #region Unity-сообщения

        private void Awake()
        {
            Collider zoneCollider = GetComponent<Collider>();
            if (zoneCollider == null)
            {
                Debug.LogError("[SortingZone] На объекте нет Collider — зона не будет работать. Добавьте BoxCollider (или другой) с галочкой IsTrigger.", this);
                enabled = false;
                return;
            }

            if (!zoneCollider.isTrigger)
            {
                zoneCollider.isTrigger = true;
                Debug.LogWarning("[SortingZone] Коллайдер зоны не был триггером — включил IsTrigger автоматически.", this);
            }

            if (targetType == CargoType.None)
            {
                Debug.LogWarning("[SortingZone] Целевой тип груза не назначен (None) — зона будет игнорировать все паллеты.", this);
            }
        }

        private void OnValidate()
        {
            Collider zoneCollider = GetComponent<Collider>();
            if (zoneCollider != null && !zoneCollider.isTrigger)
            {
                zoneCollider.isTrigger = true;
            }

            scorePerPallet = Mathf.Max(0, scorePerPallet);
            wrongTypePenalty = Mathf.Max(0, wrongTypePenalty);
        }

        /// <summary>
        /// Основная точка входа. Проверяем компонент паллеты и сравниваем типы груза.
        /// </summary>
        private void OnTriggerEnter(Collider other)
        {
            // Коллайдер может висеть на дочернем объекте — ищем CargoPallet вверх по иерархии.
            CargoPallet pallet = other.GetComponentInParent<CargoPallet>();
            if (pallet == null)
            {
                return;
            }

            if (countOncePerPallet && pallet.IsSorted)
            {
                return;
            }

            if (requireForkliftDelivery && !ForkliftController.IsCargoCarriedByAnyForklift(pallet))
            {
                return;
            }

            if (pallet.Cargo == targetType && targetType != CargoType.None)
            {
                AcceptPallet(pallet);
            }
            else
            {
                RejectPallet(pallet);
            }
        }

        /// <summary>
        /// Страховка: если паллета оказалась внутри зоны не через Rigidbody-перемещение
        /// (телепорт, спавн, ручное размещение), OnTriggerEnter мог не сработать.
        /// </summary>
        private void OnTriggerStay(Collider other)
        {
            CargoPallet pallet = other.GetComponentInParent<CargoPallet>();
            if (pallet == null || pallet.IsSorted)
            {
                return;
            }

            if (requireForkliftDelivery && !ForkliftController.IsCargoCarriedByAnyForklift(pallet))
            {
                return;
            }

            if (pallet.Cargo == targetType && targetType != CargoType.None)
            {
                AcceptPallet(pallet);
            }
        }

        #endregion

        #region Логика

        private void AcceptPallet(CargoPallet pallet)
        {
            acceptedCount++;

            int score = scorePerPallet > 0 ? scorePerPallet : pallet.ScoreValue;

            if (GameManager.Instance != null)
            {
                GameManager.Instance.ReportPalletSorted(pallet, this, score);
            }
            else
            {
                // Менеджера на сцене нет — игра не должна падать: считаем локально.
                Debug.Log(string.Format(
                    "[SortingZone:{0}] Паллета с грузом {1} засчитана (+{2} очков). GameManager отсутствует на сцене, счёт хранится в зоне. В зоне принято: {3}.",
                    name,
                    pallet.Cargo,
                    score,
                    acceptedCount),
                    pallet);
            }

            if (CargoAccepted != null)
            {
                CargoAccepted(pallet, this);
            }

            pallet.MarkAsSorted();

            if (!destroyPallet)
            {
                // Паллета остаётся в зоне как «зачётная»: физика уже отключена в CargoPallet.
                pallet.transform.position = GetStackPoint(acceptedCount - 1);
            }
        }

        private void RejectPallet(CargoPallet pallet)
        {
            rejectedCount++;

            if (logRejectedCargo)
            {
                Debug.LogWarning(string.Format(
                    "[SortingZone:{0}] Паллета с грузом {1} не подходит: зона принимает только {2}. Отклонено: {3}.",
                    name,
                    pallet.Cargo,
                    targetType,
                    rejectedCount),
                    pallet);
            }

            if (wrongTypePenalty > 0 && GameManager.Instance != null)
            {
                GameManager.Instance.ReportPalletMisplaced(pallet, this, wrongTypePenalty);
            }

            if (pushWrongCargoBack && pallet.Body != null && !pallet.Body.isKinematic && !pallet.IsLocked)
            {
                Vector3 away = pallet.transform.position - transform.position;
                away.y = 0f;
                if (away.sqrMagnitude < 0.0001f)
                {
                    away = -transform.forward;
                }

                pallet.Body.AddForce(away.normalized * wrongCargoPushForce + Vector3.up * (wrongCargoPushForce * 0.5f), ForceMode.Impulse);
            }

            if (CargoRejected != null)
            {
                CargoRejected(pallet, this);
            }
        }

        private Vector3 GetStackPoint(int index)
        {
            // Простая укладка «стопкой» для режима destroyPallet = false.
            Bounds bounds = GetComponent<Collider>().bounds;
            int perRow = 3;
            int column = index % perRow;
            int row = index / perRow;

            float step = Mathf.Max(0.05f, bounds.size.x / perRow);
            Vector3 point = transform.position;
            point.x += (column - (perRow - 1) * 0.5f) * step;
            point.y = bounds.min.y + 0.5f + row * step;
            return point;
        }

        #endregion

        #region Gizmos

        private void OnDrawGizmos()
        {
            Collider zoneCollider = GetComponent<Collider>();
            if (zoneCollider == null)
            {
                return;
            }

            Gizmos.color = gizmoColor;
            Gizmos.DrawCube(zoneCollider.bounds.center, zoneCollider.bounds.size);
            Gizmos.color = new Color(gizmoColor.r, gizmoColor.g, gizmoColor.b, 1f);
            Gizmos.DrawWireCube(zoneCollider.bounds.center, zoneCollider.bounds.size);
        }

        #endregion
    }
}
