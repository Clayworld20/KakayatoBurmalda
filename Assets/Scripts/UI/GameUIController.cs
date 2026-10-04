using System.Collections;
using UnityEngine;
using UnityEngine.UI;

#if TMP_PRESENT
using TMPro;
#endif

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// HUD симулятора погрузчика.
    ///
    /// Что делает:
    ///   * подписывается на события <see cref="GameManager"/> (OnScoreChanged, OnPalletSorted,
    ///     OnPalletMisplaced, OnLevelCompleted) и обновляет текстовые поля;
    ///   * показывает очки, «отсортировано X / N», сколько паллет с грузом осталось, счётчик ошибок
    ///     и таймер сессии в формате ММ:СС;
    ///   * по событию OnLevelCompleted плавно показывает панель «Уровень завершён»;
    ///   * корректно отписывается от событий в OnDisable (без утечек и «мёртвых» колбэков).
    ///
    /// Поддерживаются оба варианта текста:
    ///   * стандартный UnityEngine.UI.Text — работает всегда;
    ///   * TextMeshPro (TMP_Text) — если в проекте определена директива TMP_PRESENT
    ///     (Scripting Define Symbols в Project Settings → Player или version defines в asmdef).
    ///     Быстро включить: Tools → Kakayato → Forklift Demo Scene Generator → кнопка
    ///     «Включить поддержку TextMeshPro».
    ///
    /// Раскладка, которую создаёт генератор демо-сцены:
    ///   GameCanvas (Canvas + CanvasScaler + GameUIController)
    ///     ├── HudPanel
    ///     │     ├── ScoreText, SortedText, RemainingText, MistakesText, TimerText, HintText
    ///     └── LevelCompletedPanel (Image + CanvasGroup)  — изначально скрыта
    ///           ├── TitleText, SummaryText, RestartHintText
    /// </summary>
    [AddComponentMenu("Kakayato/Game UI Controller")]
    [DisallowMultipleComponent]
    public class GameUIController : MonoBehaviour
    {
        #region Вложенные типы

        /// <summary>
        /// Обёртка над текстовым полем: хранит ссылку либо на стандартный Unity UI Text,
        /// либо на TextMeshPro, либо на оба сразу (тогда текст пишется в обе метки).
        /// </summary>
        [System.Serializable]
        public class LabelBinding
        {
            [SerializeField, Tooltip("Стандартный UnityEngine.UI.Text.")]
            private Text legacyText;

#if TMP_PRESENT
            [SerializeField, Tooltip("TextMeshPro (TMP_Text).")]
            private TMP_Text tmpText;
#endif

            /// <summary>Назначена ли хотя бы одна текстовая ссылка.</summary>
            public bool IsAssigned
            {
                get
                {
                    if (legacyText != null)
                    {
                        return true;
                    }

#if TMP_PRESENT
                    if (tmpText != null)
                    {
                        return true;
                    }
#endif

                    return false;
                }
            }

            /// <summary>Записать текст во все назначенные метки.</summary>
            public void SetText(string value)
            {
                if (legacyText != null)
                {
                    legacyText.text = value;
                }

#if TMP_PRESENT
                if (tmpText != null)
                {
                    tmpText.text = value;
                }
#endif
            }

            /// <summary>Сменить цвет текста во всех назначенных метках.</summary>
            public void SetColor(Color value)
            {
                if (legacyText != null)
                {
                    legacyText.color = value;
                }

#if TMP_PRESENT
                if (tmpText != null)
                {
                    tmpText.color = value;
                }
#endif
            }

            /// <summary>Включить/выключить GameObject метки.</summary>
            public void SetActive(bool state)
            {
                if (legacyText != null)
                {
                    legacyText.gameObject.SetActive(state);
                }

#if TMP_PRESENT
                if (tmpText != null)
                {
                    tmpText.gameObject.SetActive(state);
                }
#endif
            }

            /// <summary>Назначить стандартный Unity UI Text.</summary>
            public void SetLegacyText(Text value)
            {
                legacyText = value;
            }

            /// <summary>Получить назначенный Unity UI Text (может быть null).</summary>
            public Text GetLegacyText()
            {
                return legacyText;
            }

#if TMP_PRESENT
            /// <summary>Назначить метку TextMeshPro.</summary>
            public void SetTmpText(TMP_Text value)
            {
                tmpText = value;
            }

            /// <summary>Получить назначенную метку TextMeshPro (может быть null).</summary>
            public TMP_Text GetTmpText()
            {
                return tmpText;
            }
#endif
        }

        #endregion

        #region Ссылки UI

        [Header("Метки HUD")]
        [SerializeField, Tooltip("Текущие очки.")]
        private LabelBinding scoreLabel = new LabelBinding();

        [SerializeField, Tooltip("Сколько паллет отсортировано (X из N).")]
        private LabelBinding sortedLabel = new LabelBinding();

        [SerializeField, Tooltip("Сколько паллет с грузом осталось на уровне.")]
        private LabelBinding remainingLabel = new LabelBinding();

        [SerializeField, Tooltip("Счётчик ошибок (паллет не в свою зону).")]
        private LabelBinding mistakesLabel = new LabelBinding();

        [SerializeField, Tooltip("Таймер сессии в формате ММ:СС.")]
        private LabelBinding timerLabel = new LabelBinding();

        [Header("Панель «Уровень завершён»")]
        [SerializeField, Tooltip("Панель, которая появляется после сортировки всего груза.")]
        private GameObject levelCompletedPanel;

        [SerializeField, Tooltip("CanvasGroup панели для плавного появления (если пусто — ищется на панели или создаётся).")]
        private CanvasGroup levelCompletedCanvasGroup;

        [SerializeField, Tooltip("Текст с итогами уровня на панели завершения.")]
        private LabelBinding levelCompletedSummaryLabel = new LabelBinding();

        [SerializeField, Tooltip("Скрывать панель завершения при старте сцены.")]
        private bool hideCompletedPanelOnStart = true;

        [SerializeField, Min(0f), Tooltip("Длительность плавного появления панели, сек (0 — мгновенно).")]
        private float completedPanelFadeDuration = 0.4f;

        [SerializeField, Range(0.5f, 1.5f), Tooltip("С какого масштаба «вырастает» панель (1 — без анимации масштаба).")]
        private float completedPanelStartScale = 0.92f;

        #endregion

        #region Форматирование и таймер

        [Header("Формат текста")]
        [SerializeField] private string scoreFormat = "Очки: {0}";
        [SerializeField] private string sortedFormat = "Отсортировано: {0} / {1}";
        [SerializeField] private string remainingFormat = "Осталось паллет: {0}";
        [SerializeField] private string mistakesFormat = "Ошибки: {0}";
        [SerializeField] private string timerFormat = "Время: {0}";
        [SerializeField]
        [Tooltip("Формат итоговой сводки. 0 — очки, 1 — отсортировано, 2 — ошибки, 3 — время.")]
        private string completedSummaryFormat = "Очки: {0}\nКубиков отсортировано: {1}\nОшибок: {2}\nВремя: {3}";

        [Header("Таймер")]
        [SerializeField, Tooltip("Показывать таймер сессии.")]
        private bool showTimer = true;

        [SerializeField, Tooltip("Считать время без учёта Time.timeScale (для пауз).")]
        private bool useUnscaledTime = false;

        [SerializeField, Tooltip("Останавливать таймер после завершения уровня.")]
        private bool freezeTimerOnLevelCompleted = true;

        [SerializeField, Min(0f), Tooltip("Начальное значение таймера, сек.")]
        private float timerStartSeconds = 0f;

        [Header("Отладка")]
        [SerializeField, Tooltip("Писать в консоль каждое событие менеджера (для проверки подписок).")]
        private bool logEvents = false;

        #endregion

        #region Состояние

        private GameManager subscribedManager;
        private Coroutine panelRoutine;
        private Transform panelTransform;
        private Vector3 panelBaseScale = Vector3.one;
        private float timerSeconds;
        private int lastTimerSecond = -1;
        private bool isLevelCompletedShown;

        /// <summary>Подписан ли контроллер на события GameManager.</summary>
        public bool IsSubscribedToManager { get { return subscribedManager != null; } }

        /// <summary>Сколько секунд показывал таймер в последний кадр.</summary>
        public float TimerSeconds { get { return timerSeconds; } }

        /// <summary>Показана ли панель завершения уровня.</summary>
        public bool IsLevelCompletedPanelVisible { get { return isLevelCompletedShown; } }

        #endregion

        #region Unity-сообщения

        private void Awake()
        {
            EnsureLabelBindings();

            panelTransform = levelCompletedPanel != null ? levelCompletedPanel.transform : null;
            panelBaseScale = panelTransform != null ? panelTransform.localScale : Vector3.one;

            if (levelCompletedPanel != null)
            {
                if (hideCompletedPanelOnStart)
                {
                    HideLevelCompletedPanel();
                }
                else
                {
                    levelCompletedPanel.SetActive(true);
                    CanvasGroup group = ResolvePanelCanvasGroup(true);
                    if (group != null)
                    {
                        group.alpha = 1f;
                    }
                }
            }

            WarnIfNothingAssigned();
        }

        private void OnEnable()
        {
            ResetTimer();
            TrySubscribe();
            RefreshAll();
        }

        private void Start()
        {
            // Страховка: если GameManager появился на сцене позже UI, подпишемся здесь.
            TrySubscribe();
            RefreshAll();
        }

        private void Update()
        {
            if (!IsSubscribedToManager)
            {
                TrySubscribe();
            }

            UpdateTimerLabel();
        }

        private void OnDisable()
        {
            Unsubscribe();

            if (panelRoutine != null)
            {
                StopCoroutine(panelRoutine);
                panelRoutine = null;
            }
        }

        private void OnDestroy()
        {
            // Дополнительная страховка от утечек: отписка даже при уничтожении объекта.
            Unsubscribe();
        }

        #endregion

        #region Подписка на GameManager

        private void TrySubscribe()
        {
            GameManager manager = GameManager.Instance;
            if (manager == null || manager == subscribedManager)
            {
                return;
            }

            Unsubscribe();

            subscribedManager = manager;
            subscribedManager.OnScoreChanged += HandleScoreChanged;
            subscribedManager.OnPalletSorted += HandlePalletSorted;
            subscribedManager.OnPalletMisplaced += HandlePalletMisplaced;
            subscribedManager.OnLevelCompleted += HandleLevelCompleted;

            if (logEvents)
            {
                Debug.Log("[GameUIController] Подписка на события GameManager выполнена.", this);
            }

            RefreshAll();
        }

        private void Unsubscribe()
        {
            if (subscribedManager == null)
            {
                return;
            }

            subscribedManager.OnScoreChanged -= HandleScoreChanged;
            subscribedManager.OnPalletSorted -= HandlePalletSorted;
            subscribedManager.OnPalletMisplaced -= HandlePalletMisplaced;
            subscribedManager.OnLevelCompleted -= HandleLevelCompleted;

            if (logEvents)
            {
                Debug.Log("[GameUIController] Отписка от событий GameManager выполнена.", this);
            }

            subscribedManager = null;
        }

        #endregion

        #region Обработчики событий

        private void HandleScoreChanged(int newScore, int delta)
        {
            if (logEvents)
            {
                Debug.Log(string.Format("[GameUIController] OnScoreChanged: очки {0} (дельта {1}).", newScore, delta), this);
            }

            UpdateScoreLabel();
            UpdateMistakesLabel();
        }

        private void HandlePalletSorted(CargoPallet pallet, SortingZone zone, int awardedScore)
        {
            if (logEvents)
            {
                Debug.Log(string.Format("[GameUIController] OnPalletSorted: {0} (+{1}).", pallet != null ? pallet.name : "null", awardedScore), this);
            }

            UpdateScoreLabel();
            UpdateSortedLabels();
        }

        private void HandlePalletMisplaced(CargoPallet pallet, SortingZone zone, int penalty)
        {
            if (logEvents)
            {
                Debug.Log(string.Format("[GameUIController] OnPalletMisplaced: {0} (-{1}).", pallet != null ? pallet.name : "null", penalty), this);
            }

            UpdateScoreLabel();
            UpdateMistakesLabel();
        }

        private void HandleLevelCompleted()
        {
            if (logEvents)
            {
                Debug.Log("[GameUIController] OnLevelCompleted: показываю панель завершения уровня.", this);
            }

            UpdateSortedLabels();
            ShowLevelCompletedPanel();
        }

        #endregion

        #region Обновление текстов

        /// <summary>Обновить все метки HUD из текущего состояния GameManager.</summary>
        public void RefreshAll()
        {
            UpdateScoreLabel();
            UpdateSortedLabels();
            UpdateMistakesLabel();
            UpdateTimerLabel(true);
        }

        private void UpdateScoreLabel()
        {
            scoreLabel.SetText(string.Format(scoreFormat, GetScore()));
        }

        private void UpdateSortedLabels()
        {
            sortedLabel.SetText(string.Format(sortedFormat, GetSortedPalletsCount(), GetTotalPalletsCount()));
            remainingLabel.SetText(string.Format(remainingFormat, GetRemainingPalletsCount()));
        }

        private void UpdateMistakesLabel()
        {
            mistakesLabel.SetText(string.Format(mistakesFormat, GetMistakesCount()));
        }

        private void UpdateTimerLabel(bool force = false)
        {
            if (!showTimer)
            {
                timerLabel.SetActive(false);
                return;
            }

            bool timerFrozen = freezeTimerOnLevelCompleted && isLevelCompletedShown;

            if (!timerFrozen)
            {
                timerSeconds += useUnscaledTime ? Time.unscaledDeltaTime : Time.deltaTime;
            }

            int wholeSeconds = Mathf.FloorToInt(timerSeconds);
            if (force || wholeSeconds != lastTimerSecond)
            {
                lastTimerSecond = wholeSeconds;
                timerLabel.SetText(string.Format(timerFormat, FormatTime(timerSeconds)));
            }
        }

        /// <summary>Сбросить таймер сессии (например, при рестарте уровня).</summary>
        public void ResetTimer()
        {
            timerSeconds = Mathf.Max(0f, timerStartSeconds);
            lastTimerSecond = -1;
        }

        /// <summary>Преобразовать секунды в строку ММ:СС.</summary>
        public static string FormatTime(float totalSeconds)
        {
            if (totalSeconds < 0f)
            {
                totalSeconds = 0f;
            }

            int wholeSeconds = Mathf.FloorToInt(totalSeconds);
            int minutes = wholeSeconds / 60;
            int seconds = wholeSeconds % 60;

            return string.Format("{0:00}:{1:00}", minutes, seconds);
        }

        #endregion

        #region Панель «Уровень завершён»

        /// <summary>Показать панель завершения уровня с плавным появлением.</summary>
        public void ShowLevelCompletedPanel()
        {
            if (isLevelCompletedShown)
            {
                return;
            }

            isLevelCompletedShown = true;
            UpdateCompletedSummary();

            if (levelCompletedPanel == null)
            {
                return;
            }

            if (!levelCompletedPanel.activeSelf)
            {
                levelCompletedPanel.SetActive(true);
            }

            CanvasGroup group = ResolvePanelCanvasGroup(true);
            if (panelTransform == null)
            {
                panelTransform = levelCompletedPanel.transform;
                panelBaseScale = panelTransform.localScale;
            }

            Vector3 startScale = panelBaseScale * completedPanelStartScale;
            float duration = Mathf.Max(0f, completedPanelFadeDuration);

            if (duration <= 0f)
            {
                if (group != null)
                {
                    group.alpha = 1f;
                    group.interactable = true;
                    group.blocksRaycasts = true;
                }

                panelTransform.localScale = panelBaseScale;
                return;
            }

            if (panelRoutine != null)
            {
                StopCoroutine(panelRoutine);
            }

            panelRoutine = StartCoroutine(AnimateLevelCompletedPanel(group, startScale, panelBaseScale, duration));
        }

        /// <summary>Скрыть панель завершения уровня (и сбросить флаг показа).</summary>
        public void HideLevelCompletedPanel()
        {
            isLevelCompletedShown = false;

            if (levelCompletedPanel != null)
            {
                levelCompletedPanel.SetActive(false);
            }

            CanvasGroup group = ResolvePanelCanvasGroup(false);
            if (group != null)
            {
                group.alpha = 0f;
                group.interactable = false;
                group.blocksRaycasts = false;
            }

            if (panelTransform != null)
            {
                panelTransform.localScale = panelBaseScale;
            }
        }

        private IEnumerator AnimateLevelCompletedPanel(CanvasGroup group, Vector3 fromScale, Vector3 toScale, float duration)
        {
            float elapsed = 0f;

            if (group != null)
            {
                group.alpha = 0f;
                group.interactable = false;
                group.blocksRaycasts = false;
            }

            if (panelTransform != null)
            {
                panelTransform.localScale = fromScale;
            }

            while (elapsed < duration)
            {
                elapsed += useUnscaledTime ? Time.unscaledDeltaTime : Time.deltaTime;
                float progress = Mathf.Clamp01(elapsed / duration);
                float smoothProgress = progress * progress * (3f - 2f * progress); // сглаживание (smoothstep)

                if (group != null)
                {
                    group.alpha = smoothProgress;
                }

                if (panelTransform != null)
                {
                    panelTransform.localScale = Vector3.LerpUnclamped(fromScale, toScale, smoothProgress);
                }

                yield return null;
            }

            if (group != null)
            {
                group.alpha = 1f;
                group.interactable = true;
                group.blocksRaycasts = true;
            }

            if (panelTransform != null)
            {
                panelTransform.localScale = toScale;
            }

            panelRoutine = null;
        }

        private void UpdateCompletedSummary()
        {
            levelCompletedSummaryLabel.SetText(string.Format(
                completedSummaryFormat,
                GetScore(),
                GetSortedPalletsCount(),
                GetMistakesCount(),
                FormatTime(timerSeconds)));
        }

        private CanvasGroup ResolvePanelCanvasGroup(bool createIfMissing)
        {
            if (levelCompletedCanvasGroup != null)
            {
                return levelCompletedCanvasGroup;
            }

            if (levelCompletedPanel == null)
            {
                return null;
            }

            levelCompletedCanvasGroup = levelCompletedPanel.GetComponent<CanvasGroup>();
            if (levelCompletedCanvasGroup == null)
            {
                levelCompletedCanvasGroup = levelCompletedPanel.GetComponentInChildren<CanvasGroup>(true);
            }

            if (levelCompletedCanvasGroup == null && createIfMissing)
            {
                levelCompletedCanvasGroup = levelCompletedPanel.AddComponent<CanvasGroup>();
            }

            return levelCompletedCanvasGroup;
        }

        #endregion

        #region Данные GameManager

        private GameManager GetManager()
        {
            return subscribedManager != null ? subscribedManager : GameManager.Instance;
        }

        private int GetScore()
        {
            GameManager manager = GetManager();
            return manager != null ? manager.Score : 0;
        }

        private int GetSortedPalletsCount()
        {
            GameManager manager = GetManager();
            return manager != null ? manager.SortedPalletsCount : 0;
        }

        private int GetTotalPalletsCount()
        {
            GameManager manager = GetManager();
            return manager != null ? manager.TotalPalletsSeen : 0;
        }

        private int GetRemainingPalletsCount()
        {
            GameManager manager = GetManager();
            return manager != null ? manager.RemainingPalletsCount : 0;
        }

        private int GetMistakesCount()
        {
            GameManager manager = GetManager();
            return manager != null ? manager.MisplacedCargoCount : 0;
        }

        #endregion

        #region Настройка из кода и страховки

        /// <summary>
        /// Настройка ссылок на стандартные Unity UI Text (используется генератором демо-сцены).
        /// </summary>
        public void ConfigureHudReferences(
            Text scoreText,
            Text sortedText,
            Text remainingText,
            Text mistakesText,
            Text timerText,
            GameObject completedPanel,
            Text completedSummaryText)
        {
            EnsureLabelBindings();

            scoreLabel.SetLegacyText(scoreText);
            sortedLabel.SetLegacyText(sortedText);
            remainingLabel.SetLegacyText(remainingText);
            mistakesLabel.SetLegacyText(mistakesText);
            timerLabel.SetLegacyText(timerText);
            levelCompletedSummaryLabel.SetLegacyText(completedSummaryText);

            levelCompletedPanel = completedPanel;
            levelCompletedCanvasGroup = null;
            panelTransform = levelCompletedPanel != null ? levelCompletedPanel.transform : null;
            panelBaseScale = panelTransform != null ? panelTransform.localScale : Vector3.one;

            ResolvePanelCanvasGroup(false);
        }

#if TMP_PRESENT
        /// <summary>
        /// Настройка ссылок на метки TextMeshPro (доступна, когда определена директива TMP_PRESENT).
        /// </summary>
        public void ConfigureHudReferencesTmp(
            TMP_Text scoreText,
            TMP_Text sortedText,
            TMP_Text remainingText,
            TMP_Text mistakesText,
            TMP_Text timerText,
            TMP_Text completedSummaryText)
        {
            EnsureLabelBindings();

            scoreLabel.SetTmpText(scoreText);
            sortedLabel.SetTmpText(sortedText);
            remainingLabel.SetTmpText(remainingText);
            mistakesLabel.SetTmpText(mistakesText);
            timerLabel.SetTmpText(timerText);
            levelCompletedSummaryLabel.SetTmpText(completedSummaryText);
        }
#endif

        private void EnsureLabelBindings()
        {
            if (scoreLabel == null)
            {
                scoreLabel = new LabelBinding();
            }

            if (sortedLabel == null)
            {
                sortedLabel = new LabelBinding();
            }

            if (remainingLabel == null)
            {
                remainingLabel = new LabelBinding();
            }

            if (mistakesLabel == null)
            {
                mistakesLabel = new LabelBinding();
            }

            if (timerLabel == null)
            {
                timerLabel = new LabelBinding();
            }

            if (levelCompletedSummaryLabel == null)
            {
                levelCompletedSummaryLabel = new LabelBinding();
            }
        }

        private void WarnIfNothingAssigned()
        {
            bool anyAssigned = scoreLabel.IsAssigned
                || sortedLabel.IsAssigned
                || remainingLabel.IsAssigned
                || mistakesLabel.IsAssigned
                || timerLabel.IsAssigned;

            if (!anyAssigned)
            {
                Debug.LogWarning("[GameUIController] Ни одна метка HUD не назначена — интерфейс ничего не покажет. " +
                                 "Назначьте текстовые поля в инспекторе или сгенерируйте демо-сцену (Tools → Generate Forklift Demo Scene).", this);
            }
        }

        private void OnValidate()
        {
            completedPanelFadeDuration = Mathf.Max(0f, completedPanelFadeDuration);
            timerStartSeconds = Mathf.Max(0f, timerStartSeconds);
        }

        #endregion
    }
}
