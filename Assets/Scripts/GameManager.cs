using System;
using System.Collections.Generic;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Менеджер игры: считает правильно отсортированные кубики, очки и ошибки,
    /// ведёт реестр активных кубиков и сообщает о конце уровня.
    ///
    /// Все данные доступны через инспектор (для отладки) и через события (для UI/звука):
    ///   OnScoreChanged    — изменился счёт (новое значение, дельта)
    ///   OnCubeSorted      — кубик правильно отсортирован (кубик, зона, начислено)
    ///   OnCubeMisplaced   — кубик принесён в неправильную зону (кубик, зона, штраф)
    ///   OnLevelCompleted  — все зарегистрированные кубики отсортированы
    ///
    /// Скрипт ставится на пустышку «GameManager» (или на любой объект сцены) — ровно один на сцену.
    /// </summary>
    [DefaultExecutionOrder(-100)]
    [AddComponentMenu("Kakayato/Game Manager")]
    public class GameManager : MonoBehaviour
    {
        [Header("Синглтон")]
        [SerializeField, Tooltip("Не уничтожать менеджер при загрузке новой сцены.")]
        private bool keepBetweenScenes = false;

        [Header("Счёт")]
        [SerializeField, Tooltip("Стартовое значение счёта.")]
        private int startingScore = 0;

        [SerializeField, Tooltip("Выводить в консоль итог после каждого засчитанного кубика.")]
        private bool logEverySort = true;

        [SerializeField, Tooltip("Выводить в консоль сводку по завершении уровня.")]
        private bool logSummary = true;

        private readonly HashSet<CubeProperty> activeCubes = new HashSet<CubeProperty>();
        private readonly HashSet<CubeProperty> sortedCubes = new HashSet<CubeProperty>();

        private float sessionStartTime;
        private bool isLevelCompleted;

        #region Синглтон

        /// <summary>Единственный экземпляр менеджера на сцене (null, если его нет).</summary>
        public static GameManager Instance { get; private set; }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Debug.LogWarning("[GameManager] На сцене больше одного GameManager — лишний экземпляр отключён.", this);
                enabled = false;
                return;
            }

            Instance = this;

            if (keepBetweenScenes)
            {
                DontDestroyOnLoad(gameObject);
            }
        }

        private void OnEnable()
        {
            if (Instance != this)
            {
                return;
            }

            ResetSession();
        }

        private void OnDisable()
        {
            if (Instance == this)
            {
                Instance = null;
            }
        }

        #endregion

        #region Публичные свойства (состояние уровня)

        /// <summary>Текущий счёт.</summary>
        public int Score { get; private set; }

        /// <summary>Сколько кубиков правильно отсортировано (целевой счётчик из ТЗ).</summary>
        public int SortedCubesCount { get { return sortedCubes.Count; } }

        /// <summary>Сколько кубиков попало не в свою зону.</summary>
        public int MisplacedCubesCount { get; private set; }

        /// <summary>Сколько кубиков сейчас на сцене и зарегистрировано в менеджере.</summary>
        public int ActiveCubesCount { get { return activeCubes.Count; } }

        /// <summary>Сколько кубиков было зарегистрировано за сессию (включая отсортированные).</summary>
        public int TotalCubesSeen { get; private set; }

        /// <summary>Сколько кубиков осталось отсортировать.</summary>
        public int RemainingCubesCount
        {
            get
            {
                int remaining = TotalCubesSeen - SortedCubesCount;
                return remaining > 0 ? remaining : 0;
            }
        }

        /// <summary>Сколько секунд длится сессия.</summary>
        public float ElapsedSeconds { get { return Time.time - sessionStartTime; } }

        /// <summary>Все зарегистрированные кубики отсортированы, и кубики вообще есть.</summary>
        public bool IsLevelCompleted { get { return isLevelCompleted; } }

        #endregion

        #region События

        /// <summary>Счёт изменился. Аргументы: новое значение счёта, дельта.</summary>
        public event Action<int, int> OnScoreChanged;

        /// <summary>Кубик правильно отсортирован. Аргументы: кубик, зона, начисленные очки.</summary>
        public event Action<CubeProperty, SortingZone, int> OnCubeSorted;

        /// <summary>Кубик принесён в неправильную зону. Аргументы: кубик, зона, снятые очки.</summary>
        public event Action<CubeProperty, SortingZone, int> OnCubeMisplaced;

        /// <summary>Уровень завершён: все кубики разложены по своим зонам.</summary>
        public event Action OnLevelCompleted;

        #endregion

        #region Реестр кубиков

        /// <summary>Вызывается из <see cref="CubeProperty"/> при появлении кубика на сцене.</summary>
        public void RegisterCube(CubeProperty cube)
        {
            if (cube == null || activeCubes.Contains(cube))
            {
                return;
            }

            activeCubes.Add(cube);
            TotalCubesSeen++;

            // Если все кубики уже разложены, а в игру добавили новый — уровень снова активен.
            if (isLevelCompleted && !cube.IsSorted)
            {
                isLevelCompleted = false;
            }
        }

        /// <summary>Вызывается из <see cref="CubeProperty"/> при удалении/выключении кубика.</summary>
        public void UnregisterCube(CubeProperty cube)
        {
            if (cube == null)
            {
                return;
            }

            activeCubes.Remove(cube);
        }

        /// <summary>Снимок зарегистрированных кубиков (без создания мусора, если передать свой список).</summary>
        public void GetActiveCubes(List<CubeProperty> results)
        {
            if (results == null)
            {
                return;
            }

            results.Clear();
            results.AddRange(activeCubes);
        }

        #endregion

        #region Учёт результатов

        /// <summary>
        /// Кубик попал в правильную зону: +очки, +счётчик, лог в консоль.
        /// Вызывается из <see cref="SortingZone.AcceptCube"/>.
        /// </summary>
        public void ReportCubeSorted(CubeProperty cube, SortingZone zone, int score)
        {
            if (cube == null)
            {
                return;
            }

            bool alreadyCounted = sortedCubes.Contains(cube);
            sortedCubes.Add(cube);

            if (!alreadyCounted)
            {
                AddScore(score);
            }

            string zoneName = zone != null ? zone.name : "неизвестная зона";
            string cubeName = cube.name;

            Debug.Log(string.Format(
                "[GameManager] Кубик «{0}» ({1}) правильно отсортирован в зоне «{2}». +{3} очков. Отсортировано: {4} из {5}. Осталось: {6}.",
                cubeName,
                cube.CubeType,
                zoneName,
                score,
                SortedCubesCount,
                TotalCubesSeen,
                RemainingCubesCount),
                cube);

            if (OnCubeSorted != null)
            {
                OnCubeSorted(cube, zone, score);
            }

            if (logEverySort)
            {
                LogState();
            }

            CheckLevelCompletion();
        }

        /// <summary>
        /// Кубик попал в чужую зону: списываем штраф (если он больше нуля) и записываем ошибку.
        /// Вызывается из <see cref="SortingZone.RejectCube"/>.
        /// </summary>
        public void ReportCubeMisplaced(CubeProperty cube, SortingZone zone, int penalty)
        {
            MisplacedCubesCount++;

            if (penalty > 0)
            {
                AddScore(-penalty);
            }

            string zoneName = zone != null ? zone.name : "неизвестная зона";
            string expected = zone != null ? zone.TargetType.ToString() : "?";

            Debug.LogWarning(string.Format(
                "[GameManager] Кубик «{0}» типа {1} положен в зону «{2}», которая принимает {3}. Ошибок: {4}.",
                cube != null ? cube.name : "null",
                cube != null ? cube.CubeType.ToString() : "Unknown",
                zoneName,
                expected,
                MisplacedCubesCount),
                cube);

            if (OnCubeMisplaced != null)
            {
                OnCubeMisplaced(cube, zone, penalty);
            }
        }

        /// <summary>Добавить очки (отрицательная дельта — штраф). Счёт не уходит ниже нуля.</summary>
        public void AddScore(int delta)
        {
            if (delta == 0)
            {
                return;
            }

            int newScore = Mathf.Max(0, Score + delta);
            int appliedDelta = newScore - Score;
            Score = newScore;

            if (OnScoreChanged != null)
            {
                OnScoreChanged(Score, appliedDelta);
            }
        }

        /// <summary>Сбросить счёт и счётчики (не трогая зарегистрированные кубики).</summary>
        public void ResetScore()
        {
            int previousScore = Score;
            Score = Mathf.Max(0, startingScore);
            sortedCubes.Clear();
            MisplacedCubesCount = 0;
            isLevelCompleted = false;
            sessionStartTime = Time.time;

            if (OnScoreChanged != null)
            {
                OnScoreChanged(Score, Score - previousScore);
            }

            Debug.Log(string.Format("[GameManager] Счёт сброшен. Очки: {0}, отсортировано: 0.", Score));
        }

        /// <summary>Полный сброс сессии: счёт, счётчики и реестр кубиков.</summary>
        public void ResetSession()
        {
            activeCubes.Clear();
            ResetScore();
            TotalCubesSeen = 0;

            Debug.Log("[GameManager] Сессия начата.");
        }

        #endregion

        #region Служебное

        private void CheckLevelCompletion()
        {
            if (isLevelCompleted || TotalCubesSeen <= 0 || SortedCubesCount < TotalCubesSeen)
            {
                return;
            }

            isLevelCompleted = true;

            if (logSummary)
            {
                LogState();
                Debug.Log(string.Format(
                    "[GameManager] УРОВЕНЬ ПРОЙДЕН! Кубиков отсортировано: {0}. Ошибок: {1}. Итоговый счёт: {2}. Время: {3:F1} с.",
                    SortedCubesCount,
                    MisplacedCubesCount,
                    Score,
                    ElapsedSeconds));
            }

            if (OnLevelCompleted != null)
            {
                OnLevelCompleted();
            }
        }

        /// <summary>Вывести текущее состояние в консоль — удобно для отладки без UI.</summary>
        public void LogState()
        {
            Debug.Log(string.Format(
                "[GameManager] Очки: {0} | Отсортировано: {1}/{2} | Осталось: {3} | Ошибок: {4} | Кубиков на сцене: {5} | Время: {6:F1} с.",
                Score,
                SortedCubesCount,
                TotalCubesSeen,
                RemainingCubesCount,
                MisplacedCubesCount,
                ActiveCubesCount,
                ElapsedSeconds));
        }

        #endregion
    }
}
