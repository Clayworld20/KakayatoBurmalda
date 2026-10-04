using System;
using System.Collections.Generic;
using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Менеджер игры: считает правильно отсортированные паллеты с грузом, очки и ошибки,
    /// ведёт реестр активных паллет и сообщает о конце уровня.
    ///
    /// Все данные доступны через инспектор (для отладки) и через события (для UI/звука):
    ///   OnScoreChanged    — изменился счёт (новое значение, дельта)
    ///   OnPalletSorted      — груз правильно отсортирован (паллета, зона, начислено)
    ///   OnPalletMisplaced   — груз привезён в неправильную зону (паллета, зона, штраф)
    ///   OnLevelCompleted  — все зарегистрированные паллеты отсортированы
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

        [SerializeField, Tooltip("Выводить в консоль итог после каждой засчитанной паллеты.")]
        private bool logEverySort = true;

        [SerializeField, Tooltip("Выводить в консоль сводку по завершении уровня.")]
        private bool logSummary = true;

        private readonly HashSet<CargoPallet> activePallets = new HashSet<CargoPallet>();
        private readonly HashSet<CargoPallet> sortedPallets = new HashSet<CargoPallet>();

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

        /// <summary>Сколько паллет правильно отсортировано (целевой счётчик из ТЗ).</summary>
        public int SortedPalletsCount { get { return sortedPallets.Count; } }

        /// <summary>Сколько паллет попало не в свою зону.</summary>
        public int MisplacedCargoCount { get; private set; }

        /// <summary>Сколько паллет сейчас на сцене и зарегистрировано в менеджере.</summary>
        public int ActivePalletsCount { get { return activePallets.Count; } }

        /// <summary>Сколько паллет было зарегистрировано за сессию (включая отсортированные).</summary>
        public int TotalPalletsSeen { get; private set; }

        /// <summary>Сколько паллет осталось отсортировать.</summary>
        public int RemainingPalletsCount
        {
            get
            {
                int remaining = TotalPalletsSeen - SortedPalletsCount;
                return remaining > 0 ? remaining : 0;
            }
        }

        /// <summary>Сколько секунд длится сессия.</summary>
        public float ElapsedSeconds { get { return Time.time - sessionStartTime; } }

        /// <summary>Все зарегистрированные паллеты отсортированы, и паллеты вообще есть.</summary>
        public bool IsLevelCompleted { get { return isLevelCompleted; } }

        #endregion

        #region События

        /// <summary>Счёт изменился. Аргументы: новое значение счёта, дельта.</summary>
        public event Action<int, int> OnScoreChanged;

        /// <summary>Груз правильно отсортирован. Аргументы: паллета, зона, начисленные очки.</summary>
        public event Action<CargoPallet, SortingZone, int> OnPalletSorted;

        /// <summary>Груз привезён в неправильную зону. Аргументы: паллета, зона, снятые очки.</summary>
        public event Action<CargoPallet, SortingZone, int> OnPalletMisplaced;

        /// <summary>Уровень завершён: весь груз разложен по своим зонам.</summary>
        public event Action OnLevelCompleted;

        #endregion

        #region Реестр паллет

        /// <summary>Вызывается из <see cref="CargoPallet"/> при появлении паллеты на сцене.</summary>
        public void RegisterPallet(CargoPallet pallet)
        {
            if (pallet == null || activePallets.Contains(pallet))
            {
                return;
            }

            activePallets.Add(pallet);
            TotalPalletsSeen++;

            // Если весь груз уже разложен, а в игру добавили новую паллету — уровень снова активен.
            if (isLevelCompleted && !pallet.IsSorted)
            {
                isLevelCompleted = false;
            }
        }

        /// <summary>Вызывается из <see cref="CargoPallet"/> при удалении/выключении паллеты.</summary>
        public void UnregisterPallet(CargoPallet pallet)
        {
            if (pallet == null)
            {
                return;
            }

            activePallets.Remove(pallet);
        }

        /// <summary>Снимок зарегистрированных паллет (без создания мусора, если передать свой список).</summary>
        public void GetActivePallets(List<CargoPallet> results)
        {
            if (results == null)
            {
                return;
            }

            results.Clear();
            results.AddRange(activePallets);
        }

        #endregion

        #region Учёт результатов

        /// <summary>
        /// Паллета попала в правильную зону: +очки, +счётчик, лог в консоль.
        /// Вызывается из <see cref="SortingZone.AcceptPallet"/>.
        /// </summary>
        public void ReportPalletSorted(CargoPallet pallet, SortingZone zone, int score)
        {
            if (pallet == null)
            {
                return;
            }

            bool alreadyCounted = sortedPallets.Contains(pallet);
            sortedPallets.Add(pallet);

            if (!alreadyCounted)
            {
                AddScore(score);
            }

            string zoneName = zone != null ? zone.name : "неизвестная зона";
            string palletName = pallet.name;

            Debug.Log(string.Format(
                "[GameManager] Паллета «{0}» с грузом {1} правильно отсортирована в зоне «{2}». +{3} очков. Отсортировано: {4} из {5}. Осталось: {6}.",
                palletName,
                pallet.Cargo,
                zoneName,
                score,
                SortedPalletsCount,
                TotalPalletsSeen,
                RemainingPalletsCount),
                pallet);

            if (OnPalletSorted != null)
            {
                OnPalletSorted(pallet, zone, score);
            }

            if (logEverySort)
            {
                LogState();
            }

            CheckLevelCompletion();
        }

        /// <summary>
        /// Паллета попала в чужую зону: списываем штраф (если он больше нуля) и записываем ошибку.
        /// Вызывается из <see cref="SortingZone.RejectPallet"/>.
        /// </summary>
        public void ReportPalletMisplaced(CargoPallet pallet, SortingZone zone, int penalty)
        {
            MisplacedCargoCount++;

            if (penalty > 0)
            {
                AddScore(-penalty);
            }

            string zoneName = zone != null ? zone.name : "неизвестная зона";
            string expected = zone != null ? zone.TargetType.ToString() : "?";

            Debug.LogWarning(string.Format(
                "[GameManager] Паллета «{0}» с грузом {1} привезена в зону «{2}», которая принимает {3}. Ошибок: {4}.",
                pallet != null ? pallet.name : "null",
                pallet != null ? pallet.Cargo.ToString() : "Unknown",
                zoneName,
                expected,
                MisplacedCargoCount),
                pallet);

            if (OnPalletMisplaced != null)
            {
                OnPalletMisplaced(pallet, zone, penalty);
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

        /// <summary>Сбросить счёт и счётчики (не трогая зарегистрированные паллеты).</summary>
        public void ResetScore()
        {
            int previousScore = Score;
            Score = Mathf.Max(0, startingScore);
            sortedPallets.Clear();
            MisplacedCargoCount = 0;
            isLevelCompleted = false;
            sessionStartTime = Time.time;

            if (OnScoreChanged != null)
            {
                OnScoreChanged(Score, Score - previousScore);
            }

            Debug.Log(string.Format("[GameManager] Счёт сброшен. Очки: {0}, отсортировано: 0.", Score));
        }

        /// <summary>Полный сброс сессии: счёт, счётчики и реестр паллет.</summary>
        public void ResetSession()
        {
            activePallets.Clear();
            ResetScore();
            TotalPalletsSeen = 0;

            Debug.Log("[GameManager] Сессия начата.");
        }

        #endregion

        #region Служебное

        private void CheckLevelCompletion()
        {
            if (isLevelCompleted || TotalPalletsSeen <= 0 || SortedPalletsCount < TotalPalletsSeen)
            {
                return;
            }

            isLevelCompleted = true;

            if (logSummary)
            {
                LogState();
                Debug.Log(string.Format(
                    "[GameManager] УРОВЕНЬ ПРОЙДЕН! Паллет отсортировано: {0}. Ошибок: {1}. Итоговый счёт: {2}. Время: {3:F1} с.",
                    SortedPalletsCount,
                    MisplacedCargoCount,
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
                "[GameManager] Очки: {0} | Отсортировано: {1}/{2} | Осталось: {3} | Ошибок: {4} | Паллет на сцене: {5} | Время: {6:F1} с.",
                Score,
                SortedPalletsCount,
                TotalPalletsSeen,
                RemainingPalletsCount,
                MisplacedCargoCount,
                ActivePalletsCount,
                ElapsedSeconds));
        }

        #endregion
    }
}
