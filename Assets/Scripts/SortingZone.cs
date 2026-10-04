using System;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Зона сортировки. Вешается на объект с коллайдером и галочкой IsTrigger.
    /// Хранит целевой тип кубика: если в зону попадает кубик с <see cref="CubeProperty"/>
    /// того же типа — кубик засчитывается (очки + Debug.Log + уничтожение/отключение физики),
    /// кубик чужого типа — отклоняется (штраф опционально, событие всегда).
    ///
    /// Раскладка объектов в сцене:
    ///   SortingZone_Red (BoxCollider, IsTrigger = true, SortingZone, материал зоны)
    ///   SortingZone_Green, SortingZone_Blue ...
    /// </summary>
    [AddComponentMenu("Kakayato/Sorting Zone")]
    public class SortingZone : MonoBehaviour
    {
        [Header("Целевой тип")]
        [SerializeField, Tooltip("Какой тип кубика принимает зона. None — зона отключена и ничего не принимает.")]
        private CubeColor targetType = CubeColor.Red;

        [SerializeField, Tooltip("Очки за кубик. Если меньше или равно 0 — берётся ScoreValue самого кубика.")]
        private int scorePerCube = 10;

        [SerializeField, Tooltip("Уничтожать кубик после засчитывания (иначе только отключается физика — см. CubeProperty).")]
        private bool destroyCube = true;

        [SerializeField, Tooltip("Принимать только кубики, которые приносит погрузчик (кубик лежит в объёме вил). Выключено — принимаем любой кубик, заехавший в зону.")]
        private bool requireForkliftDelivery = false;

        [Header("Ошибочный кубик")]
        [SerializeField, Tooltip("Логировать кубики неподходящего типа.")]
        private bool logRejectedCubes = true;

        [SerializeField, Tooltip("Штраф за кубик чужого типа (0 — без штрафа).")]
        private int wrongTypePenalty = 0;

        [SerializeField, Tooltip("Отбрасывать кубик чужого типа обратно (лёгкий импульс вверх/наружу от центра зоны).")]
        private bool pushWrongCubeBack = true;

        [SerializeField, Min(0f), Tooltip("Сила отбрасывания кубика чужого типа.")]
        private float wrongCubePushForce = 3f;

        [Header("Только для наглядности")]
        [SerializeField, Tooltip("Цвет подсветки зоны в Gizmos (в игре не используется).")]
        private Color gizmoColor = new Color(1f, 0.2f, 0.2f, 0.25f);

        [SerializeField, Tooltip("Считать кубик только один раз, даже если он остаётся в триггере.")]
        private bool countOncePerCube = true;

        private int acceptedCount;
        private int rejectedCount;

        /// <summary>Fired после засчитывания кубика. Аргументы: кубик, зона.</summary>
        public event Action<CubeProperty, SortingZone> CubeAccepted;

        /// <summary>Fired когда в зону попал кубик чужого типа. Аргументы: кубик, зона.</summary>
        public event Action<CubeProperty, SortingZone> CubeRejected;

        /// <summary>Целевой тип кубика этой зоны.</summary>
        public CubeColor TargetType { get { return targetType; } }

        /// <summary>Сколько кубиков зона уже приняла.</summary>
        public int AcceptedCount { get { return acceptedCount; } }

        /// <summary>Сколько кубиков зона отклонила.</summary>
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

            if (targetType == CubeColor.None)
            {
                Debug.LogWarning("[SortingZone] Целевой тип кубика не назначен (None) — зона будет игнорировать все кубики.", this);
            }
        }

        private void OnValidate()
        {
            Collider zoneCollider = GetComponent<Collider>();
            if (zoneCollider != null && !zoneCollider.isTrigger)
            {
                zoneCollider.isTrigger = true;
            }

            scorePerCube = Mathf.Max(0, scorePerCube);
            wrongTypePenalty = Mathf.Max(0, wrongTypePenalty);
        }

        /// <summary>
        /// Основная точка входа. Проверяем компонент кубика и сравниваем типы.
        /// </summary>
        private void OnTriggerEnter(Collider other)
        {
            // Коллайдер может висеть на дочернем объекте — ищем CubeProperty вверх по иерархии.
            CubeProperty cube = other.GetComponentInParent<CubeProperty>();
            if (cube == null)
            {
                return;
            }

            if (countOncePerCube && cube.IsSorted)
            {
                return;
            }

            if (requireForkliftDelivery && !ForkliftController.IsCubeCarriedByAnyForklift(cube))
            {
                return;
            }

            if (cube.CubeType == targetType && targetType != CubeColor.None)
            {
                AcceptCube(cube);
            }
            else
            {
                RejectCube(cube);
            }
        }

        /// <summary>
        /// Страховка: если кубик оказался внутри зоны не через Rigidbody-перемещение
        /// (телепорт, спавн, ручное размещение), OnTriggerEnter мог не сработать.
        /// </summary>
        private void OnTriggerStay(Collider other)
        {
            CubeProperty cube = other.GetComponentInParent<CubeProperty>();
            if (cube == null || cube.IsSorted)
            {
                return;
            }

            if (requireForkliftDelivery && !ForkliftController.IsCubeCarriedByAnyForklift(cube))
            {
                return;
            }

            if (cube.CubeType == targetType && targetType != CubeColor.None)
            {
                AcceptCube(cube);
            }
        }

        #endregion

        #region Логика

        private void AcceptCube(CubeProperty cube)
        {
            acceptedCount++;

            int score = scorePerCube > 0 ? scorePerCube : cube.ScoreValue;

            if (GameManager.Instance != null)
            {
                GameManager.Instance.ReportCubeSorted(cube, this, score);
            }
            else
            {
                // Менеджера на сцене нет — игра не должна падать: считаем локально.
                Debug.Log(string.Format(
                    "[SortingZone:{0}] Кубик {1} засчитан (+{2} очков). GameManager отсутствует на сцене, счёт хранится в зоне. В зоне принято: {3}.",
                    name,
                    cube.CubeType,
                    score,
                    acceptedCount),
                    cube);
            }

            if (CubeAccepted != null)
            {
                CubeAccepted(cube, this);
            }

            cube.MarkAsSorted();

            if (!destroyCube)
            {
                // Кубик остаётся в зоне как «зачётный»: физика уже отключена в CubeProperty.
                cube.transform.position = GetStackPoint(acceptedCount - 1);
            }
        }

        private void RejectCube(CubeProperty cube)
        {
            rejectedCount++;

            if (logRejectedCubes)
            {
                Debug.LogWarning(string.Format(
                    "[SortingZone:{0}] Кубик типа {1} не подходит: зона принимает только {2}. Отклонено: {3}.",
                    name,
                    cube.CubeType,
                    targetType,
                    rejectedCount),
                    cube);
            }

            if (wrongTypePenalty > 0 && GameManager.Instance != null)
            {
                GameManager.Instance.ReportCubeMisplaced(cube, this, wrongTypePenalty);
            }

            if (pushWrongCubeBack && cube.Body != null && !cube.Body.isKinematic)
            {
                Vector3 away = cube.transform.position - transform.position;
                away.y = 0f;
                if (away.sqrMagnitude < 0.0001f)
                {
                    away = -transform.forward;
                }

                cube.Body.AddForce(away.normalized * wrongCubePushForce + Vector3.up * (wrongCubePushForce * 0.5f), ForceMode.Impulse);
            }

            if (CubeRejected != null)
            {
                CubeRejected(cube, this);
            }
        }

        private Vector3 GetStackPoint(int index)
        {
            // Простая укладка «стопкой» для режима destroyCube = false.
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
