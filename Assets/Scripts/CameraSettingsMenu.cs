using UnityEngine;

namespace KakayatoBurmalda.Forklift
{
    /// <summary>
    /// Меню настройки камеры по клавише <b>F1</b> (окно IMGUI, работает в Play-режиме).
    ///
    ///   * открывается/закрывается по <see cref="toggleKey"/> (по умолчанию F1), закрывается и по Escape;
    ///   * при открытии курсор освобождается (<c>Cursor.lockState = None</c>) — ползунки можно тянуть мышью,
    ///     а пока меню открыто, погрузчик не читает клавиатуру и не уезжает;
    ///   * при закрытии курсор возвращается в «игровой» режим (см. <see cref="lockCursorDuringPlay"/>);
    ///   * ползунки меняют позу камеры вживую: смещение, высота точки вращения, точка взгляда, сглаживания, FOV;
    ///   * кнопки-пресеты: «Рабочая» (вилы и груз в кадре), «Сзади-сверху», «Высокая»;
    ///   * «Сохранить» и «Очистить» работают в редакторе и пишут настройки в <c>EditorPrefs</c> —
    ///     поза подхватывается при следующем запуске и при генерации сцены.
    ///
    /// Меню не требует EventSystem и Canvas: это служебное окно разработчика, а не игровой HUD.
    /// Компонент вешается на камеру рядом с <see cref="CameraFollow"/> (в демо-сцене это делает
    /// генератор, а <see cref="CameraFollow"/> добавляет его сам, если его нет).
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Kakayato/Camera Settings Menu")]
    public class CameraSettingsMenu : MonoBehaviour
    {
        #region Настройки

        [SerializeField, Tooltip("Клавиша открытия/закрытия меню (по умолчанию F1).")]
        private KeyCode toggleKey = KeyCode.F1;

        [SerializeField, Tooltip("Открыть меню сразу при старте — удобно, когда камеру только подбирают.")]
        private bool openOnStart = false;

        [SerializeField, Tooltip("Держать курсор захваченным в игре и отпускать его, пока открыто меню.")]
        private bool lockCursorDuringPlay = true;

        [SerializeField, Tooltip("Пока меню открыто, погрузчик не читает клавиатуру — камера настраивается спокойно.")]
        private bool lockForkliftWhileOpen = true;

        [SerializeField, Min(280f), Tooltip("Ширина окна меню, пиксели.")]
        private float panelWidth = 470f;

        [SerializeField, Min(220f), Tooltip("Высота окна меню, пиксели.")]
        private float panelHeight = 540f;

        #endregion

        #region Состояние

        private CameraFollow cameraFollow;
        private Camera targetCamera;
        private ForkliftController forklift;
        private Rect panelRect;
        private bool rectInitialized;
        private bool isOpen;
        private Vector2 scrollPosition;
        private GUIStyle headerStyle;
        private GUIStyle valueStyle;
        private GUIStyle hintStyle;
        private string statusMessage = string.Empty;
        private float statusTime = -100f;

        /// <summary>Меню открыто прямо сейчас.</summary>
        public bool IsOpen { get { return isOpen; } }

        /// <summary>Клавиша открытия/закрытия меню.</summary>
        public KeyCode ToggleKey
        {
            get { return toggleKey; }
            set { toggleKey = value; }
        }

        #endregion

        #region Unity-сообщения

        private void Awake()
        {
            cameraFollow = GetComponent<CameraFollow>();
            targetCamera = GetComponent<Camera>();
        }

        private void Start()
        {
            if (cameraFollow == null)
            {
                cameraFollow = FindObjectOfType<CameraFollow>();
            }

            if (targetCamera == null && cameraFollow != null)
            {
                targetCamera = cameraFollow.GetComponent<Camera>();
            }

            forklift = FindObjectOfType<ForkliftController>();
            ApplyCursorState();

            if (openOnStart)
            {
                SetOpen(true);
            }
        }

        private void Update()
        {
#if ENABLE_LEGACY_INPUT_MANAGER
            if (Input.GetKeyDown(toggleKey))
            {
                SetOpen(!isOpen);
                return;
            }

            if (isOpen && Input.GetKeyDown(KeyCode.Escape))
            {
                SetOpen(false);
            }
#endif
        }

        private void OnApplicationFocus(bool hasFocus)
        {
            if (hasFocus && !isOpen)
            {
                ApplyCursorState();
            }
        }

        private void OnDisable()
        {
            // Не оставляем ни захваченный курсор, ни заблокированное управление после выключения объекта.
            isOpen = false;
            EnableForkliftControl();
            ReleaseCursor();
        }

        private void OnGUI()
        {
            if (!isOpen)
            {
                return;
            }

            EnsureStyles();

            if (!rectInitialized)
            {
                panelRect = CreateCenteredRect();
                rectInitialized = true;
            }

            panelRect = GUILayout.Window(
                GetInstanceID(),
                panelRect,
                DrawWindow,
                "Настройки камеры — F1",
                GUILayout.Width(panelWidth),
                GUILayout.Height(panelHeight));

            panelRect.x = Mathf.Clamp(panelRect.x, 0f, Mathf.Max(0f, Screen.width - panelRect.width));
            panelRect.y = Mathf.Clamp(panelRect.y, 0f, Mathf.Max(0f, Screen.height - panelRect.height));
        }

        #endregion

        #region Публичный API

        /// <summary>Открыть/закрыть меню (курсор и управление погрузчиком переключаются автоматически).</summary>
        public void SetOpen(bool open)
        {
            if (isOpen == open)
            {
                return;
            }

            isOpen = open;

            if (isOpen)
            {
                ReleaseCursor();
                DisableForkliftControl();
            }
            else
            {
                EnableForkliftControl();
                ApplyCursorState();
            }
        }

        /// <summary>Переключить меню (удобно вешать на кнопку UI или внешний ввод).</summary>
        public void Toggle()
        {
            SetOpen(!isOpen);
        }

        #endregion

        #region Отрисовка окна

        private void DrawWindow(int windowId)
        {
            scrollPosition = GUILayout.BeginScrollView(scrollPosition);

            if (cameraFollow == null)
            {
                GUILayout.Label("CameraFollow на этой камере не найден — настраивать нечего.");
                GUILayout.Space(6f);

                if (GUILayout.Button("Закрыть (F1)"))
                {
                    SetOpen(false);
                }

                GUILayout.EndScrollView();
                GUI.DragWindow(new Rect(0f, 0f, 10000f, 22f));
                return;
            }

            GUILayout.Label("Готовые позы", headerStyle);
            GUILayout.BeginHorizontal();

            if (GUILayout.Button("Рабочая (видно вилы)"))
            {
                cameraFollow.ApplyPreset(CameraPreset.Cabin);
                SetStatus("Рабочая поза: вилы, паллета и груз в кадре.");
            }

            if (GUILayout.Button("Сзади-сверху"))
            {
                cameraFollow.ApplyPreset(CameraPreset.Chase);
                SetStatus("Поза «Сзади-сверху»: видна машина, вилы закрыты кабиной.");
            }

            if (GUILayout.Button("Высокая"))
            {
                cameraFollow.ApplyPreset(CameraPreset.High);
                SetStatus("Поза «Высокая»: сверху видно машину, вилы и площадку.");
            }

            GUILayout.EndHorizontal();

            GUILayout.Space(4f);
            GUILayout.Label("Позиция камеры (X — вбок, Y — вверх, Z — вперёд)", headerStyle);

            Vector3 cameraOffset = cameraFollow.Offset;
            cameraOffset.x = Slider("Вбок", cameraOffset.x, -8f, 8f);
            cameraOffset.y = Slider("Высота", cameraOffset.y, -1f, 14f);
            cameraOffset.z = Slider("Вперёд/назад", cameraOffset.z, -16f, 4f);
            cameraFollow.Offset = cameraOffset;

            cameraFollow.PivotHeight = Slider("Точка вращения", cameraFollow.PivotHeight, 0f, 4f);

            GUILayout.Space(4f);
            GUILayout.Label("Куда смотрит камера (от базы погрузчика)", headerStyle);

            Vector3 lookOffset = cameraFollow.LookOffset;
            lookOffset.x = Slider("Взгляд вбок", lookOffset.x, -6f, 6f);
            lookOffset.y = Slider("Взгляд вверх", lookOffset.y, -2f, 6f);
            lookOffset.z = Slider("Взгляд вперёд", lookOffset.z, -4f, 14f);
            cameraFollow.LookOffset = lookOffset;

            GUILayout.Space(4f);
            GUILayout.Label("Плавность и обзор", headerStyle);

            cameraFollow.PositionSmoothTime = Slider("Сглаживание позиции", cameraFollow.PositionSmoothTime, 0.01f, 1.5f);
            cameraFollow.YawSmoothTime = Slider("Сглаживание курса", cameraFollow.YawSmoothTime, 0.01f, 1.5f);
            cameraFollow.RotationSharpness = Slider("Резкость взгляда", cameraFollow.RotationSharpness, 0.5f, 25f);
            cameraFollow.MinHeight = Slider("Мин. высота над землёй", cameraFollow.MinHeight, 0f, 8f);
            cameraFollow.FieldOfView = Slider("Обзор (FOV)", cameraFollow.FieldOfView, 30f, 90f);

            GUILayout.Space(6f);
            GUILayout.BeginHorizontal();

            if (GUILayout.Button("Сбросить к сцене"))
            {
                cameraFollow.ResetToInitialSettings();
                SetStatus("Вернул позу, которая была записана в сцене.");
            }

#if UNITY_EDITOR
            if (GUILayout.Button("Сохранить"))
            {
                cameraFollow.SaveSettingsToEditorPrefs();
                SetStatus("Сохранил: поза подхватится при следующем запуске и при генерации сцены.");
            }

            if (CameraFollow.HasSavedSettings && GUILayout.Button("Очистить сохранённое"))
            {
                CameraFollow.ClearSavedSettings();
                SetStatus("Сохранённые настройки камеры удалены.");
            }
#endif

            if (GUILayout.Button("Закрыть (F1)"))
            {
                SetOpen(false);
            }

            GUILayout.EndHorizontal();

            GUILayout.Space(6f);

            bool newLockCursor = GUILayout.Toggle(lockCursorDuringPlay, " Держать курсор захваченным в игре (F1 отпускает)");

            if (newLockCursor != lockCursorDuringPlay)
            {
                lockCursorDuringPlay = newLockCursor;
                ApplyCursorState();
            }

            bool newLockForklift = GUILayout.Toggle(lockForkliftWhileOpen, " Не давать погрузчику ехать, пока меню открыто");

            if (newLockForklift != lockForkliftWhileOpen)
            {
                lockForkliftWhileOpen = newLockForklift;

                if (isOpen)
                {
                    if (lockForkliftWhileOpen)
                    {
                        DisableForkliftControl();
                    }
                    else
                    {
                        EnableForkliftControl();
                    }
                }
            }

            GUILayout.Space(4f);

            if (!string.IsNullOrEmpty(statusMessage) && Time.unscaledTime - statusTime < 6f)
            {
                GUILayout.Label(statusMessage, hintStyle);
            }

            GUILayout.Label("Мышью тяните ползунки, окно можно перетащить за заголовок. " +
                            "Из-за спины вилы не видны: их закрывают корпус, кабина и защитная решётка — поэтому " +
                            "поза по умолчанию кабинная.", hintStyle);

            GUILayout.EndScrollView();
            GUI.DragWindow(new Rect(0f, 0f, 10000f, 22f));
        }

        private float Slider(string label, float value, float min, float max)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(label, GUILayout.Width(180f));

            float result = GUILayout.HorizontalSlider(value, min, max, GUILayout.Width(190f));
            GUILayout.Label(result.ToString("0.00"), valueStyle, GUILayout.Width(52f));

            GUILayout.EndHorizontal();
            return result;
        }

        private void EnsureStyles()
        {
            if (headerStyle != null)
            {
                return;
            }

            headerStyle = new GUIStyle(GUI.skin.label);
            headerStyle.fontStyle = FontStyle.Bold;

            valueStyle = new GUIStyle(GUI.skin.label);
            valueStyle.alignment = TextAnchor.MiddleRight;

            hintStyle = new GUIStyle(GUI.skin.label);
            hintStyle.wordWrap = true;
            hintStyle.fontSize = Mathf.Max(10, GUI.skin.label.fontSize - 1);
        }

        private Rect CreateCenteredRect()
        {
            return new Rect(
                Mathf.Max(0f, (Screen.width - panelWidth) * 0.5f),
                Mathf.Max(0f, (Screen.height - panelHeight) * 0.5f),
                panelWidth,
                panelHeight);
        }

        private void SetStatus(string message)
        {
            statusMessage = message;
            statusTime = Time.unscaledTime;
        }

        #endregion

        #region Курсор и управление погрузчиком

        private void ApplyCursorState()
        {
            if (lockCursorDuringPlay && Application.isPlaying)
            {
                Cursor.lockState = CursorLockMode.Locked;
                Cursor.visible = false;
            }
            else
            {
                ReleaseCursor();
            }
        }

        private void ReleaseCursor()
        {
            Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
        }

        private void DisableForkliftControl()
        {
            if (!lockForkliftWhileOpen)
            {
                return;
            }

            if (forklift == null)
            {
                forklift = FindObjectOfType<ForkliftController>();
            }

            if (forklift != null)
            {
                forklift.SetControlEnabled(false);
            }
        }

        private void EnableForkliftControl()
        {
            if (forklift != null)
            {
                forklift.SetControlEnabled(true);
            }
        }

        #endregion
    }
}
