using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

#if TMP_PRESENT
using TMPro;
#endif

namespace KakayatoBurmalda.Forklift.EditorTools
{
    /// <summary>
    /// Генератор демо-сцены симулятора погрузчика.
    ///
    /// Запуск: пункт меню <b>Tools → Generate Forklift Demo Scene</b> либо окно
    /// <b>Tools → Kakayato → Открыть окно генератора демо-сцены</b> (там же настройки).
    ///
    /// Что создаёт:
    ///   DemoScene
    ///     ├── Ground                     — площадка (BoxCollider + материал) и грунтовая дорога
    ///     ├── House                      — фермерский дом: кирпичный поясок, окна в рамах, козырёк, крыша с коньком
    ///     ├── Barn                       — амбар: дверная рама въезда, обшивка стен, каркас, сено
    ///     │     └── SortingZone_Boxes / _Barrels / _Construction — триггерные зоны по типу груза
    ///     ├── Forklift                   — корпус с Rigidbody, тег Forklift, скрипт ForkliftController
    ///     │     ├── Body/Counterweight/RearTank/Cabin/OverheadGuard/Mast (меши без коллайдеров)
    ///     │     ├── MastTiltPivot → ForkCarriage (вилы: коллайдеры, скос-заезд, меши)
    ///     │     ├── GroundCheck
    ///     │     └── Wheel_FL/FR/RL/RR → Tire + Rim + Hub + Tread (протектор)
    ///     ├── ForkliftResetPoint         — точка сброса погрузчика (клавиша R)
    ///     ├── CargoPallets/…             — паллеты с грузом (ящики, бочки, стройматериалы), CargoPallet + Rigidbody
    ///     ├── GameManager                — менеджер игры
    ///     ├── GameCanvas (опционально)   — HUD со скриптом GameUIController
    ///     └── Main Camera (опционально)  — CameraFollow: плавный вид от третьего лица
    ///
    /// Все ссылки в инспекторах (каретка вил, визуальные колёса, маски слоёв, целевые типы груза,
    /// настройки захвата, ссылки HUD и цель камеры) назначаются кодом через SerializedObject,
    /// поэтому сцена собирается в один клик. Создаваемые объекты регистрируются в Undo.
    /// </summary>
    public class DemoSceneGenerator : EditorWindow
    {
        #region Константы

        private const string MenuPath = "Tools/Generate Forklift Demo Scene";
        private const string RemoveMenuPath = "Tools/Kakayato/Удалить демо-объекты со сцены";
        private const string OpenWindowMenuPath = "Tools/Kakayato/Открыть окно генератора демо-сцены";
        private const string TextMeshProMenuPath = "Tools/Kakayato/Включить поддержку TextMeshPro в HUD";

        private const string UndoGroupName = "Generate Forklift Demo Scene";
        private const string DemoRootName = "DemoScene";
        private const string MaterialsFolder = "Assets/Demo/Materials";
        private const string PhysicsFolder = "Assets/Demo/Physics";
        private const string DefaultScenePath = "Assets/Scenes/ForkliftDemo.unity";

        // ── Раскладка уровня: ферма (дом у старта, амбар с зонами сортировки в глубине) ──

        private const float GroundSize = 90f;
        private const int DefaultPalletsPerType = 3;
        private const float WheelRadius = 0.3f;

        // Паллета: настил на подкладках (декор), физический коллайдер — один, на всю паллету с грузом.
        private const float PalletDeckHeight = 0.11f;
        private const float PalletSizeX = 1.25f;
        private const float PalletSizeZ = 1.05f;
        private const float PalletSlatHeight = 0.04f;

        /// <summary>Нижнее положение вил в демо-сцене (используется при расчёте геометрии скоса-заезда).</summary>
        private const float ForkMinHeight = 0.02f;

        /// <summary>Стартовая позиция погрузчика: лицом в +Z, к дому и амбару.</summary>
        private static readonly Vector3 ForkliftStartPosition = new Vector3(0f, 0f, -26f);

        /// <summary>Центр фермерского дома (декоративное здание слева от старта).</summary>
        private static readonly Vector3 HousePosition = new Vector3(-17f, 0f, -14f);

        private const float HouseWidth = 11f;   // по X
        private const float HouseDepth = 9f;    // по Z
        private const float HouseWallHeight = 4.4f;
        private const float HouseRoofHeight = 2.4f;

        /// <summary>Центр амбара — все три зоны сортировки стоят внутри него.</summary>
        private static readonly Vector3 BarnPosition = new Vector3(0f, 0f, 20f);

        private const float BarnWidth = 26f;            // по X
        private const float BarnDepth = 18f;            // по Z
        private const float BarnHeight = 7.5f;
        private const float BarnWallThickness = 0.5f;
        private const float BarnOpeningWidth = 8f;      // проём для погрузчика (в стену −Z)
        private const float BarnOpeningHeight = 6f;     // высота проёма: камера проходит под перекладиной
        private const float BarnGableHeight = 3.2f;     // высота двускатной крыши

        /// <summary>Локальные координаты зон сортировки внутри амбара.</summary>
        private static readonly Vector3[] SortingZoneLocalPositions =
        {
            new Vector3(-7.5f, 0f, 2.5f),
            new Vector3(0f, 0f, 2.5f),
            new Vector3(7.5f, 0f, 2.5f)
        };

        /// <summary>EditorPrefs-флаг: генерировать демо-сцену при первом открытии Unity (пустая сцена без демо-объектов).</summary>
        internal const string AutoGeneratePrefsKey = "Kakayato.Forklift.AutoGenerateOnFirstLoad";

        /// <summary>EditorPrefs-флаг: автогенерация уже выполнялась — повторно сцену не трогаем.</summary>
        internal const string AutoGenerateDonePrefsKey = "Kakayato.Forklift.AutoGenerateDone";

        #endregion

        #region Настройки генерации

        /// <summary>Параметры генерации демо-сцены (сериализуются в окне редактора).</summary>
        [Serializable]
        public class GenerationOptions
        {
            [Tooltip("Создать новую сцену (иначе сгенерировать объекты в текущей открытой сцене).")]
            public bool createNewScene = true;

            [Tooltip("Создавая новую сцену, оставить стандартный свет и камеру.")]
            public bool keepCameraAndLight = true;

            [Tooltip("Перед генерацией удалить ранее сгенерированные демо-объекты (DemoScene и объекты сцены).")]
            public bool clearExistingDemoObjects = true;

            [Tooltip("Добавить на камеру CameraFollow: плавный вид от третьего лица сзади-сверху.")]
            public bool attachCameraToForklift = true;

            [Range(-180f, 180f), Tooltip("Начальный поворот погрузчика по оси Y, градусы. 0 — вилы смотрят на паллеты и амбар (+Z).")]
            public float forkliftStartYaw = 0f;

            [Range(1, 4), Tooltip("Сколько паллет с грузом каждого типа создать (ящики, бочки, стройматериалы).")]
            public int palletsPerType = DefaultPalletsPerType;

            [Tooltip("Создать теги Forklift / Cargo / SortingZone / Ground / Barn.")]
            public bool createTags = true;

            [Tooltip("Создать слои Ground и Cargo (для корректных масок в контроллере).")]
            public bool createLayers = true;

            [Tooltip("Создать и назначить материалы (стандартный или URP-шейдер).")]
            public bool createMaterials = true;

            [Tooltip("Сгенерировать ферму: дом у старта и большой амбар, внутри которого стоят зоны сортировки.")]
            public bool createFarmBuildings = true;

            [Tooltip("Создать HUD (Canvas + GameUIController).")]
            public bool createHud = true;

            [Tooltip("Сохранить сцену в файл .unity.")]
            public bool saveSceneAsset = false;

            [Tooltip("Путь к файлу сцены, если включено сохранение.")]
            public string sceneAssetPath = DefaultScenePath;

#if TMP_PRESENT
            [Tooltip("Использовать TextMeshPro для текстов HUD (директива TMP_PRESENT определена).")]
            public bool useTextMeshPro = true;
#endif
        }

        #endregion

        #region Состояние окна

        private GenerationOptions options = new GenerationOptions();
        private Vector2 scrollPosition;
        private bool showAdvanced = true;

        #endregion

        #region Пункты меню

        [MenuItem(MenuPath, false, 10)]
        private static void GenerateDemoSceneFromMenu()
        {
            Generate(new GenerationOptions());
        }

        [MenuItem(OpenWindowMenuPath, false, 11)]
        private static void OpenGeneratorWindow()
        {
            DemoSceneGenerator window = GetWindow<DemoSceneGenerator>(false, "Демо-сцена", true);
            window.minSize = new Vector2(430f, 420f);
            window.Show();
        }

        [MenuItem(RemoveMenuPath, false, 12)]
        private static void RemoveDemoObjectsFromMenu()
        {
            int removed = RemoveDemoObjectsFromActiveScene();

            if (removed == 0)
            {
                Debug.Log("[DemoSceneGenerator] Демо-объектов на текущей сцене не найдено.");
            }
        }

        [MenuItem(TextMeshProMenuPath, false, 30)]
        private static void EnableTextMeshProSupportFromMenu()
        {
            EnableTextMeshProSupport();
        }

        #endregion

        #region Окно редактора

        private void OnGUI()
        {
            scrollPosition = EditorGUILayout.BeginScrollView(scrollPosition);

            EditorGUILayout.LabelField("Генератор демо-сцены погрузчика", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "Соберёт ферму: площадку с дорогой, дом у старта, амбар с тремя зонами сортировки внутри, " +
                "детализированный погрузчик с вилами, паллеты с грузом на улице (ящики, бочки, стройматериалы), " +
                "GameManager, HUD и следящую камеру. Все ссылки в инспекторах назначаются кодом, действия можно отменить (Ctrl+Z).",
                MessageType.Info);

            EditorGUILayout.Space(6f);
            EditorGUILayout.LabelField("Основные настройки", EditorStyles.boldLabel);

            options.createNewScene = EditorGUILayout.Toggle("Создать новую сцену", options.createNewScene);

            if (options.createNewScene)
            {
                options.keepCameraAndLight = EditorGUILayout.Toggle("Оставить свет и камеру", options.keepCameraAndLight);
            }
            else
            {
                options.clearExistingDemoObjects = EditorGUILayout.Toggle("Очистить объекты сцены", options.clearExistingDemoObjects);
            }

            options.attachCameraToForklift = EditorGUILayout.Toggle("Камера следует за погрузчиком", options.attachCameraToForklift);
            options.forkliftStartYaw = EditorGUILayout.Slider("Поворот погрузчика, °", options.forkliftStartYaw, -180f, 180f);
            options.palletsPerType = EditorGUILayout.IntSlider("Паллет каждого типа груза", options.palletsPerType, 1, 4);

            showAdvanced = EditorGUILayout.Foldout(showAdvanced, "Дополнительно", true);
            if (showAdvanced)
            {
                EditorGUI.indentLevel++;
                options.createFarmBuildings = EditorGUILayout.Toggle("Дом и амбар", options.createFarmBuildings);
                options.createTags = EditorGUILayout.Toggle("Создать теги", options.createTags);
                options.createLayers = EditorGUILayout.Toggle("Создать слои Ground/Cargo", options.createLayers);
                options.createMaterials = EditorGUILayout.Toggle("Создать материалы", options.createMaterials);
                options.createHud = EditorGUILayout.Toggle("Создать HUD (Canvas)", options.createHud);
                options.saveSceneAsset = EditorGUILayout.Toggle("Сохранить сцену в файл", options.saveSceneAsset);

                if (options.saveSceneAsset)
                {
                    options.sceneAssetPath = EditorGUILayout.TextField("Путь сцены", options.sceneAssetPath);
                }

#if TMP_PRESENT
                options.useTextMeshPro = EditorGUILayout.Toggle("Тексты HUD на TextMeshPro", options.useTextMeshPro);
#endif

                EditorGUI.indentLevel--;
            }

            EditorGUILayout.Space(6f);
            EditorGUILayout.LabelField("Автозапуск", EditorStyles.boldLabel);

            bool autoGenerate = EditorGUILayout.Toggle("Генерировать при первом запуске Unity", DemoSceneAutoBuilder.IsAutoGenerateEnabled);
            if (autoGenerate != DemoSceneAutoBuilder.IsAutoGenerateEnabled)
            {
                DemoSceneAutoBuilder.IsAutoGenerateEnabled = autoGenerate;
            }

            if (DemoSceneAutoBuilder.WasAutoGenerationDone)
            {
                EditorGUILayout.LabelField("Автогенерация уже выполнялась — сцена повторно не пересобирается.", EditorStyles.miniLabel);

                if (GUILayout.Button("Разрешить автогенерацию заново", GUILayout.Height(20f)))
                {
                    DemoSceneAutoBuilder.ResetAutoGenerationFlag();
                }
            }
            else
            {
                EditorGUILayout.LabelField("Сработает один раз на пустой несохранённой сцене.", EditorStyles.miniLabel);
            }

            EditorGUILayout.Space(8f);

            if (GUILayout.Button("Сгенерировать демо-сцену", GUILayout.Height(36f)))
            {
                Generate(options);
            }

            if (GUILayout.Button("Удалить демо-объекты со сцены", GUILayout.Height(24f)))
            {
                RemoveDemoObjectsFromActiveScene();
            }

            EditorGUILayout.Space(8f);
            EditorGUILayout.LabelField("TextMeshPro", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
#if TMP_PRESENT
                "Директива TMP_PRESENT определена — HUD может использовать TextMeshPro, а контроллер интерфейса показывает TMP-поля.",
#else
                "Директива TMP_PRESENT не определена, поэтому HUD использует стандартный UnityEngine.UI.Text. " +
                "Нажмите кнопку ниже, чтобы включить поддержку TextMeshPro (нужен установленный пакет TextMeshPro).",
#endif
                MessageType.None);

            if (GUILayout.Button("Включить поддержку TextMeshPro", GUILayout.Height(24f)))
            {
                EnableTextMeshProSupport();
            }

            EditorGUILayout.Space(8f);
            EditorGUILayout.LabelField(string.Format("Версия компонентов: {0} паллет с грузом, {1} зоны сортировки (ящики, бочки, стройматериалы).",
                options.palletsPerType * 3,
                3),
                EditorStyles.miniLabel);

            EditorGUILayout.EndScrollView();
        }

        #endregion

        #region Пайплайн генерации

        /// <summary>Сгенерировать демо-сцену с указанными настройками (со стандартным вопросом о сохранении текущей сцены).</summary>
        public static void Generate(GenerationOptions options)
        {
            Generate(options, true);
        }

        /// <summary>
        /// Сгенерировать демо-сцену.
        /// <paramref name="askToSaveCurrentScene"/> = false используется автозапуском,
        /// чтобы не показывать диалог сохранения на пустой сцене при старте редактора.
        /// </summary>
        public static void Generate(GenerationOptions options, bool askToSaveCurrentScene)
        {
            if (options == null)
            {
                options = new GenerationOptions();
            }

            if (askToSaveCurrentScene && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
            {
                Debug.Log("[DemoSceneGenerator] Генерация отменена: текущая сцена не сохранена.");
                return;
            }

            try
            {
                EditorUtility.DisplayProgressBar("Генерация демо-сцены",
                    options.createNewScene ? "Создание новой сцены..." : "Подготовка текущей сцены...",
                    0.05f);

                Scene scene;

                if (options.createNewScene)
                {
                    NewSceneSetup setup = options.keepCameraAndLight
                        ? NewSceneSetup.DefaultGameObjects
                        : NewSceneSetup.EmptyScene;

                    scene = EditorSceneManager.NewScene(setup, NewSceneMode.Single);
                }
                else
                {
                    scene = SceneManager.GetActiveScene();

                    if (options.clearExistingDemoObjects)
                    {
                        ClearSceneContent(scene);
                    }
                }

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Теги и слои...", 0.12f);
                PrepareTagsAndLayers(options, out string forkliftTag, out string cargoTag, out string zoneTag, out string groundTag,
                    out string buildingTag, out int groundLayer, out int cargoLayer);

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Материалы...", 0.2f);
                DemoMaterials materials = options.createMaterials ? CreateMaterials() : DemoMaterials.Empty;
                PhysicMaterial chassisMaterial = options.createMaterials ? CreateChassisPhysicMaterial() : null;

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Ферма и площадка...", 0.3f);
                GameObject demoRoot = CreateGameObject(DemoRootName, null, scene, Vector3.zero, Quaternion.identity);
                GameObject ground = BuildGround(demoRoot.transform, scene, materials, groundLayer, groundTag);

                GameObject house = null;

                if (options.createFarmBuildings)
                {
                    EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Дом...", 0.38f);
                    house = BuildHouse(demoRoot.transform, scene, materials);
                }

                GameObject barn = null;

                if (options.createFarmBuildings)
                {
                    EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Амбар...", 0.46f);
                    barn = BuildBarn(demoRoot.transform, scene, materials, buildingTag);
                }

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Погрузчик...", 0.56f);
                ForkliftController forkliftController;
                Transform resetPoint;
                GameObject forklift = BuildForklift(demoRoot.transform, scene, options, materials, chassisMaterial, groundLayer, cargoLayer,
                    out forkliftController, out resetPoint);

                if (!string.IsNullOrEmpty(forkliftTag))
                {
                    forklift.tag = forkliftTag;
                }

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Зоны сортировки в амбаре...", 0.7f);
                Transform zoneParent = barn != null ? barn.transform : demoRoot.transform;
                BuildSortingZones(zoneParent, scene, materials, zoneTag, options.createFarmBuildings);

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Паллеты с грузом на улице...", 0.8f);
                BuildPallets(demoRoot.transform, scene, options, materials, cargoLayer, cargoTag);

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "GameManager...", 0.88f);
                BuildGameManager(demoRoot.transform, scene);

                if (options.createHud)
                {
                    EditorUtility.DisplayProgressBar("Генерация демо-сцены", "HUD...", 0.92f);
                    BuildHud(demoRoot.transform, scene, options, GetFont());
                }

                if (options.attachCameraToForklift)
                {
                    EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Камера...", 0.96f);
                    AttachCameraToForklift(scene, forklift.transform);
                }

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Проверка сцены...", 0.98f);
                // Самопроверка принимает компонент, а не GameObject, поэтому берём ForkliftController
                // с созданного погрузчика.
                ValidateGeneratedScene(scene, options, forklift.GetComponent<ForkliftController>(), house, barn);

                EditorSceneManager.MarkSceneDirty(scene);
                AssetDatabase.SaveAssets();
                Selection.activeGameObject = forklift;
                EditorGUIUtility.PingObject(ground);

                if (SceneView.lastActiveSceneView != null)
                {
                    SceneView.lastActiveSceneView.FrameSelected();
                }

                if (options.saveSceneAsset && !string.IsNullOrEmpty(options.sceneAssetPath))
                {
                    EnsureFolder(GetDirectoryName(options.sceneAssetPath, "Assets/Scenes"));
                    EditorSceneManager.SaveScene(scene, options.sceneAssetPath);
                    AssetDatabase.Refresh();
                }

                Debug.Log(string.Format(
                    "[DemoSceneGenerator] Уровень готов: ферма с домом и амбаром, погрузчик, 3 зоны сортировки внутри амбара, {0} паллет с грузом на улице{1}. " +
                    "Задача: подобрать паллеты вилами (F — захват/отпускание) и развезти по зонам в амбаре: ящики, бочки, стройматериалы. " +
                    "Управление: W/S — газ, A/D — руль, Shift/Ctrl — вилы, Q/E — наклон мачты, F — захват/отпустить груз, Space — тормоз, R — сброс.",
                    options.palletsPerType * 3,
                    options.createHud ? ", HUD со счётом" : string.Empty));
            }
            catch (Exception exception)
            {
                Debug.LogError("[DemoSceneGenerator] Ошибка генерации демо-сцены: " + exception);
                throw;
            }
            finally
            {
                EditorUtility.ClearProgressBar();
            }
        }

        /// <summary>
        /// Самопроверка после генерации: считаем паллеты по типам груза и зоны, убеждаемся, что зоны
        /// стоят внутри амбара, а ссылки погрузчика и камеры назначены. Итог уходит в консоль, поэтому
        /// «одна кнопка» либо собирает корректный уровень, либо честно сообщает, что именно не так.
        /// </summary>
        private static void ValidateGeneratedScene(Scene scene, GenerationOptions options, ForkliftController forklift, GameObject house, GameObject barn)
        {
            List<string> issues = new List<string>();
            int expectedPallets = Mathf.Clamp(options.palletsPerType, 1, 4) * 3;

            // 1. Погрузчик и его ссылки.
            if (forklift == null)
            {
                issues.Add("погрузчик не создан");
            }
            else
            {
                if (forklift.Body == null)
                {
                    issues.Add("у погрузчика нет Rigidbody");
                }

                if (forklift.ForkCarriage == null)
                {
                    issues.Add("не назначена каретка вил (ForkCarriage)");
                }
            }

            // 2. Паллеты с грузом по типам.
            CargoPallet[] pallets = UnityEngine.Object.FindObjectsOfType<CargoPallet>();
            int[] palletsByType = new int[4];

            for (int i = 0; i < pallets.Length; i++)
            {
                int typeIndex = Mathf.Clamp((int)pallets[i].Cargo, 0, palletsByType.Length - 1);
                palletsByType[typeIndex]++;

                if (pallets[i].Cargo == CargoType.None)
                {
                    issues.Add("паллета «" + pallets[i].name + "» без типа груза (None) — в зонах не засчитается");
                }

                if (pallets[i].Body == null)
                {
                    issues.Add("у паллеты «" + pallets[i].name + "» нет Rigidbody");
                }
            }

            if (pallets.Length != expectedPallets)
            {
                issues.Add(string.Format("паллет в сцене {0}, ожидалось {1}", pallets.Length, expectedPallets));
            }

            // 3. Зоны сортировки: три штуки, у каждой свой тип груза, все внутри амбара.
            SortingZone[] zones = UnityEngine.Object.FindObjectsOfType<SortingZone>();

            if (zones.Length != 3)
            {
                issues.Add(string.Format("зон сортировки {0}, ожидалось 3", zones.Length));
            }

            int[] zoneTypes = new int[4];

            for (int i = 0; i < zones.Length; i++)
            {
                if (zones[i].TargetType == CargoType.None)
                {
                    issues.Add("у зоны " + zones[i].name + " не задан целевой тип груза");
                }
                else
                {
                    zoneTypes[Mathf.Clamp((int)zones[i].TargetType, 0, zoneTypes.Length - 1)]++;
                }

                if (barn != null)
                {
                    Vector3 local = barn.transform.InverseTransformPoint(zones[i].transform.position);
                    float halfWidth = BarnWidth * 0.5f - 2.5f;
                    float halfDepth = BarnDepth * 0.5f - 2.5f;

                    if (Mathf.Abs(local.x) > halfWidth || Mathf.Abs(local.z) > halfDepth)
                    {
                        issues.Add(string.Format("зона {0} стоит вне амбара (локальные координаты {1})", zones[i].name, local));
                    }
                }
            }

            for (int typeIndex = 1; typeIndex < zoneTypes.Length; typeIndex++)
            {
                if (zoneTypes[typeIndex] == 0)
                {
                    issues.Add("нет зоны сортировки для типа " + ((CargoType)typeIndex));
                }
            }

            // 4. Менеджер игры, слои и следящая камера.
            if (UnityEngine.Object.FindObjectOfType<GameManager>() == null)
            {
                issues.Add("на сцене нет GameManager — очки не будут считаться");
            }

            if (LayerMask.NameToLayer("Ground") < 0)
            {
                issues.Add("нет слоя Ground — погрузчик будет считать землёй всю общую маску");
            }

            if (options.attachCameraToForklift && UnityEngine.Object.FindObjectOfType<CameraFollow>() == null)
            {
                issues.Add("камера не получила CameraFollow — обзор не будет следовать за погрузчиком");
            }

            string summary = string.Format(
                "[DemoSceneGenerator] Проверка сцены: паллет {0} (ящики {1}, бочки {2}, стройматериалы {3}), зон сортировки {4}, дом {5}, амбар {6}, HUD {7}.",
                pallets.Length,
                palletsByType[(int)CargoType.Boxes],
                palletsByType[(int)CargoType.Barrels],
                palletsByType[(int)CargoType.Construction],
                zones.Length,
                house != null ? "есть" : "нет",
                barn != null ? "есть" : "нет",
                options.createHud ? "есть" : "нет");

            if (issues.Count == 0)
            {
                Debug.Log(summary + " Замечаний нет.");
            }
            else
            {
                Debug.LogWarning(summary + " Замечания: " + string.Join("; ", issues.ToArray()) + ".");
            }
        }

        /// <summary>Удалить ранее созданные демо-объекты из активной сцены. Возвращает число удалённых корневых объектов.</summary>
        public static int RemoveDemoObjectsFromActiveScene()
        {
            List<GameObject> rootsToRemove = new List<GameObject>();
            Scene scene = SceneManager.GetActiveScene();
            GameObject[] roots = scene.GetRootGameObjects();

            for (int i = 0; i < roots.Length; i++)
            {
                GameObject root = roots[i];
                if (root == null)
                {
                    continue;
                }

                if (root.name == DemoRootName || root.GetComponentInChildren<ForkliftController>(true) != null)
                {
                    rootsToRemove.Add(root);
                }
            }

            for (int i = 0; i < rootsToRemove.Count; i++)
            {
                Undo.DestroyObjectImmediate(rootsToRemove[i]);
            }

            if (rootsToRemove.Count > 0)
            {
                EditorSceneManager.MarkSceneDirty(scene);
                Debug.Log(string.Format("[DemoSceneGenerator] Удалено демо-объектов: {0}.", rootsToRemove.Count));
            }

            return rootsToRemove.Count;
        }

        /// <summary>Полностью очистить сцену от пользовательских объектов, оставив свет и камеру.</summary>
        private static void ClearSceneContent(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            List<GameObject> rootsToRemove = new List<GameObject>();

            for (int i = 0; i < roots.Length; i++)
            {
                GameObject root = roots[i];
                if (root == null)
                {
                    continue;
                }

                bool isCamera = root.GetComponentInChildren<Camera>(true) != null;
                bool isLight = root.GetComponentInChildren<Light>(true) != null;

                if (isCamera || isLight)
                {
                    continue;
                }

                rootsToRemove.Add(root);
            }

            for (int i = 0; i < rootsToRemove.Count; i++)
            {
                Undo.DestroyObjectImmediate(rootsToRemove[i]);
            }

            EnsureCameraAndLight(scene);
        }

        #endregion

        #region Теги, слои, камера

        private static void PrepareTagsAndLayers(
            GenerationOptions options,
            out string forkliftTag,
            out string cargoTag,
            out string zoneTag,
            out string groundTag,
            out string buildingTag,
            out int groundLayer,
            out int cargoLayer)
        {
            forkliftTag = null;
            cargoTag = null;
            zoneTag = null;
            groundTag = null;
            buildingTag = null;
            groundLayer = 0;
            cargoLayer = 0;

            if (options.createTags)
            {
                forkliftTag = EnsureTag("Forklift");
                cargoTag = EnsureTag("Cargo");
                zoneTag = EnsureTag("SortingZone");
                groundTag = EnsureTag("Ground");
                buildingTag = EnsureTag("Barn");
            }

            if (options.createLayers)
            {
                groundLayer = EnsureLayer("Ground");
                cargoLayer = EnsureLayer("Cargo");
            }
        }

        /// <summary>Создать тег, если его нет. Возвращает имя тега или null, если создать не удалось.</summary>
        private static string EnsureTag(string tagName)
        {
            if (TagExists(tagName))
            {
                return tagName;
            }

            UnityEngine.Object[] tagManagerAssets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/TagManager.asset");
            if (tagManagerAssets == null || tagManagerAssets.Length == 0)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не удалось открыть ProjectSettings/TagManager.asset для создания тега " + tagName);
                return null;
            }

            SerializedObject tagManager = new SerializedObject(tagManagerAssets[0]);
            SerializedProperty tags = tagManager.FindProperty("tags");

            if (tags == null || !tags.isArray)
            {
                Debug.LogWarning("[DemoSceneGenerator] В TagManager нет массива тегов, тег " + tagName + " не создан.");
                return null;
            }

            tags.InsertArrayElementAtIndex(tags.arraySize);
            tags.GetArrayElementAtIndex(tags.arraySize - 1).stringValue = tagName;
            tagManager.ApplyModifiedPropertiesWithoutUndo();

            if (!TagExists(tagName))
            {
                Debug.LogWarning("[DemoSceneGenerator] Тег " + tagName + " не удалось создать — объекты останутся с тегом Untagged.");
                return null;
            }

            return tagName;
        }

        private static bool TagExists(string tagName)
        {
            try
            {
                return UnityEditorInternal.InternalEditorUtility.tags != null
                    && Array.IndexOf(UnityEditorInternal.InternalEditorUtility.tags, tagName) >= 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Создать пользовательский слой, если его нет. Возвращает индекс слоя (0, если создать не удалось).</summary>
        private static int EnsureLayer(string layerName)
        {
            int existingLayer = LayerMask.NameToLayer(layerName);
            if (existingLayer >= 0)
            {
                return existingLayer;
            }

            int freeLayer = FindFreeUserLayer();
            if (freeLayer < 0)
            {
                Debug.LogWarning("[DemoSceneGenerator] Нет свободных пользовательских слоёв, слой " + layerName + " не создан (используется Default).");
                return 0;
            }

            UnityEngine.Object[] tagManagerAssets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/TagManager.asset");
            if (tagManagerAssets == null || tagManagerAssets.Length == 0)
            {
                return 0;
            }

            SerializedObject tagManager = new SerializedObject(tagManagerAssets[0]);
            SerializedProperty layers = tagManager.FindProperty("layers");

            if (layers == null || !layers.isArray || freeLayer >= layers.arraySize)
            {
                return 0;
            }

            layers.GetArrayElementAtIndex(freeLayer).stringValue = layerName;
            tagManager.ApplyModifiedPropertiesWithoutUndo();

            int result = LayerMask.NameToLayer(layerName);
            return result >= 0 ? result : 0;
        }

        private static int FindFreeUserLayer()
        {
            for (int layerIndex = 8; layerIndex <= 31; layerIndex++)
            {
                if (string.IsNullOrEmpty(LayerMask.LayerToName(layerIndex)))
                {
                    return layerIndex;
                }
            }

            return -1;
        }

        private static void EnsureCameraAndLight(Scene scene)
        {
            Camera camera = FindActiveComponentInScene<Camera>(scene);
            if (camera == null)
            {
                GameObject cameraObject = CreateGameObject("Main Camera", null, scene, new Vector3(0f, 6f, -12f), Quaternion.Euler(20f, 0f, 0f),
                    typeof(Camera), typeof(AudioListener));
                cameraObject.tag = "MainCamera";
                camera = cameraObject.GetComponent<Camera>();
            }

            Light directionalLight = FindDirectionalLight(scene);
            if (directionalLight == null)
            {
                CreateGameObject("Directional Light", null, scene, new Vector3(0f, 8f, 0f), Quaternion.Euler(50f, -30f, 0f), typeof(Light));
            }
        }

        private static T FindActiveComponentInScene<T>(Scene scene) where T : Component
        {
            GameObject[] roots = scene.GetRootGameObjects();

            for (int i = 0; i < roots.Length; i++)
            {
                T component = roots[i].GetComponentInChildren<T>(false);
                if (component != null)
                {
                    return component;
                }
            }

            return null;
        }

        private static Light FindDirectionalLight(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();

            for (int i = 0; i < roots.Length; i++)
            {
                Light[] lights = roots[i].GetComponentsInChildren<Light>(false);
                for (int j = 0; j < lights.Length; j++)
                {
                    if (lights[j].type == LightType.Directional)
                    {
                        return lights[j];
                    }
                }
            }

            return null;
        }

        /// <summary>
        /// Навесить на камеру слежение от третьего лица (<see cref="CameraFollow"/>).
        /// Камера остаётся в корне сцены: её не трясёт физика погрузчика, а позицию и взгляд
        /// ведёт CameraFollow (SmoothDamp по позиции, Slerp по взгляду).
        /// </summary>
        private static void AttachCameraToForklift(Scene scene, Transform forklift)
        {
            Camera camera = FindActiveComponentInScene<Camera>(scene);
            if (camera == null)
            {
                return;
            }

            Transform cameraTransform = camera.transform;

            // Камера не должна быть ребёнком погрузчика: иначе её трясёт вместе с корпусом.
            if (cameraTransform.parent != null)
            {
                Undo.SetTransformParent(cameraTransform, null, "Detach camera from forklift");
            }

            CameraFollow follow = cameraTransform.GetComponent<CameraFollow>();

            if (follow == null)
            {
                follow = Undo.AddComponent<CameraFollow>(cameraTransform);
            }

            ApplySerializedChanges(follow, serializedObject =>
            {
                SetObjectReference(serializedObject, "target", forklift);
                SetVector3(serializedObject, "offset", new Vector3(0f, 4.6f, -8.6f));
                SetFloat(serializedObject, "pivotHeight", 1.5f);
                SetFloat(serializedObject, "positionSmoothTime", 0.3f);
                SetFloat(serializedObject, "yawSmoothTime", 0.45f);
                SetFloat(serializedObject, "rotationSharpness", 6f);
                SetVector3(serializedObject, "lookOffset", new Vector3(0f, 1.3f, 1.8f));
                SetFloat(serializedObject, "minHeight", 1.5f);
                SetBool(serializedObject, "snapOnStart", true);
            });

            camera.fieldOfView = 62f;
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 500f;

            // Сразу ставим камеру на место: кадр виден ещё до запуска игры.
            follow.SnapToTarget();
        }

        #endregion

        #region Материалы

        /// <summary>Набор материалов демо-сцены (может быть пустым, если материалы отключены).</summary>
        private class DemoMaterials
        {
            public static readonly DemoMaterials Empty = new DemoMaterials();

            // Земля и дорога
            public Material Ground;
            public Material Dirt;

            // Погрузчик: крашеная сталь, тёмный металл, стекло, хром, резина, фара
            public Material ForkliftBody;
            public Material ForkliftAccent;
            public Material ForkliftGlass;
            public Material ForkliftChrome;
            public Material Wheel;
            public Material WheelRim;
            public Material Headlight;

            // Зоны сортировки (по типу груза)
            public Material ZoneBoxes;
            public Material ZoneBarrels;
            public Material ZoneConstruction;

            // Паллеты и груз
            public Material PalletWood;
            public Material PalletWoodDark;
            public Material Cardboard;
            public Material Tape;
            public Material BarrelMetal;
            public Material BarrelHoop;
            public Material Concrete;
            public Material ConcreteDark;

            // Дом
            public Material HouseWall;
            public Material HouseWallBrick;
            public Material HouseRoof;
            public Material HouseRoofRidge;
            public Material WindowFrame;
            public Material Window;
            public Material Wood;
            public Material WoodDark;
            public Material Stone;

            // Амбар
            public Material BarnWall;
            public Material BarnRoof;
            public Material BarnFrame;
            public Material BarnDoorFrame;
            public Material BarnFloor;
            public Material Hay;
            public Material Warning;

            /// <summary>Материал зоны по типу груза.</summary>
            public Material GetZoneMaterial(CargoType cargoType)
            {
                switch (cargoType)
                {
                    case CargoType.Boxes: return ZoneBoxes;
                    case CargoType.Barrels: return ZoneBarrels;
                    case CargoType.Construction: return ZoneConstruction;
                    default: return null;
                }
            }

            /// <summary>Материал груза по типу — для значков зон и мелких деталей.</summary>
            public Material GetCargoMaterial(CargoType cargoType)
            {
                switch (cargoType)
                {
                    case CargoType.Boxes: return Cardboard;
                    case CargoType.Barrels: return BarrelMetal;
                    case CargoType.Construction: return Concrete;
                    default: return null;
                }
            }
        }

        /// <summary>
        /// Материалы сцены. Для металла поднимаем metallic/smoothness (крашеный корпус, хром, обручи),
        /// дерево, картон и бетон оставляем матовыми — так примитивы читаются как разные материалы.
        /// </summary>
        private static DemoMaterials CreateMaterials()
        {
            EnsureFolder(MaterialsFolder);

            DemoMaterials materials = new DemoMaterials
            {
                // Земля: трава и грунтовая дорога (матовые).
                Ground = FindOrCreateMaterial("Demo_Ground", new Color(0.22f, 0.30f, 0.16f), 0.08f, 0f, false),
                Dirt = FindOrCreateMaterial("Demo_Dirt", new Color(0.42f, 0.34f, 0.24f), 0.05f, 0f, false),

                // Погрузчик: оранжевая крашеная сталь, графитовый металл, стекло, хром, резина.
                ForkliftBody = FindOrCreateMaterial("Demo_Forklift_Body", new Color(0.95f, 0.55f, 0.08f), 0.55f, 0.45f, false),
                ForkliftAccent = FindOrCreateMaterial("Demo_Forklift_Accent", new Color(0.17f, 0.17f, 0.19f), 0.62f, 0.75f, false),
                ForkliftGlass = FindOrCreateMaterial("Demo_Forklift_Glass", new Color(0.55f, 0.72f, 0.85f, 0.35f), 0.92f, 0.1f, true),
                ForkliftChrome = FindOrCreateMaterial("Demo_Forklift_Chrome", new Color(0.78f, 0.79f, 0.82f), 0.85f, 0.95f, false),
                Wheel = FindOrCreateMaterial("Demo_Wheel", new Color(0.05f, 0.05f, 0.06f), 0.12f, 0f, false),
                WheelRim = FindOrCreateMaterial("Demo_Wheel_Rim", new Color(0.72f, 0.73f, 0.76f), 0.7f, 0.85f, false),
                Headlight = FindOrCreateMaterial("Demo_Headlight", new Color(0.98f, 0.95f, 0.75f), 0.9f, 0.1f, false),

                // Зоны сортировки: полупрозрачные площадки по типу груза.
                ZoneBoxes = FindOrCreateMaterial("Demo_Zone_Boxes", new Color(0.86f, 0.66f, 0.34f, 0.55f), 0.15f, 0f, true),
                ZoneBarrels = FindOrCreateMaterial("Demo_Zone_Barrels", new Color(0.24f, 0.52f, 0.86f, 0.55f), 0.25f, 0.2f, true),
                ZoneConstruction = FindOrCreateMaterial("Demo_Zone_Construction", new Color(0.92f, 0.50f, 0.14f, 0.55f), 0.2f, 0f, true),

                // Паллеты и груз: дерево, картон, стальные бочки, бетон.
                PalletWood = FindOrCreateMaterial("Demo_Pallet_Wood", new Color(0.62f, 0.46f, 0.26f), 0.16f, 0f, false),
                PalletWoodDark = FindOrCreateMaterial("Demo_Pallet_Wood_Dark", new Color(0.42f, 0.30f, 0.17f), 0.14f, 0f, false),
                Cardboard = FindOrCreateMaterial("Demo_Cardboard", new Color(0.72f, 0.55f, 0.34f), 0.05f, 0f, false),
                Tape = FindOrCreateMaterial("Demo_Tape", new Color(0.35f, 0.26f, 0.16f), 0.08f, 0f, false),
                BarrelMetal = FindOrCreateMaterial("Demo_Barrel_Metal", new Color(0.30f, 0.45f, 0.62f), 0.5f, 0.65f, false),
                BarrelHoop = FindOrCreateMaterial("Demo_Barrel_Hoop", new Color(0.66f, 0.66f, 0.70f), 0.75f, 0.9f, false),
                Concrete = FindOrCreateMaterial("Demo_Concrete", new Color(0.66f, 0.66f, 0.64f), 0.08f, 0f, false),
                ConcreteDark = FindOrCreateMaterial("Demo_Concrete_Dark", new Color(0.45f, 0.45f, 0.44f), 0.07f, 0f, false),

                // Дом: штукатурка и кирпич матовые, черепица чуть блестит, окна — стекло в белой раме.
                HouseWall = FindOrCreateMaterial("Demo_House_Wall", new Color(0.90f, 0.86f, 0.76f), 0.07f, 0f, false),
                HouseWallBrick = FindOrCreateMaterial("Demo_House_Brick", new Color(0.56f, 0.28f, 0.21f), 0.08f, 0f, false),
                HouseRoof = FindOrCreateMaterial("Demo_House_Roof", new Color(0.45f, 0.17f, 0.13f), 0.24f, 0.05f, false),
                HouseRoofRidge = FindOrCreateMaterial("Demo_House_Roof_Ridge", new Color(0.28f, 0.12f, 0.10f), 0.2f, 0f, false),
                WindowFrame = FindOrCreateMaterial("Demo_Window_Frame", new Color(0.92f, 0.92f, 0.88f), 0.25f, 0f, false),
                Window = FindOrCreateMaterial("Demo_Window", new Color(0.45f, 0.68f, 0.82f, 0.45f), 0.92f, 0.12f, true),
                Wood = FindOrCreateMaterial("Demo_Wood", new Color(0.45f, 0.30f, 0.16f), 0.16f, 0f, false),
                WoodDark = FindOrCreateMaterial("Demo_Wood_Dark", new Color(0.26f, 0.16f, 0.09f), 0.14f, 0f, false),
                Stone = FindOrCreateMaterial("Demo_Stone", new Color(0.45f, 0.44f, 0.42f), 0.09f, 0f, false),

                // Амбар: крашеная доска, тёмная металлическая крыша, деревянный каркас, сено, конусы.
                BarnWall = FindOrCreateMaterial("Demo_Barn_Wall", new Color(0.60f, 0.17f, 0.13f), 0.18f, 0.03f, false),
                BarnRoof = FindOrCreateMaterial("Demo_Barn_Roof", new Color(0.25f, 0.25f, 0.27f), 0.35f, 0.55f, false),
                BarnFrame = FindOrCreateMaterial("Demo_Barn_Frame", new Color(0.34f, 0.24f, 0.15f), 0.15f, 0f, false),
                BarnDoorFrame = FindOrCreateMaterial("Demo_Barn_Door_Frame", new Color(0.28f, 0.19f, 0.11f), 0.14f, 0f, false),
                BarnFloor = FindOrCreateMaterial("Demo_Barn_Floor", new Color(0.48f, 0.44f, 0.38f), 0.08f, 0f, false),
                Hay = FindOrCreateMaterial("Demo_Hay", new Color(0.86f, 0.72f, 0.28f), 0.05f, 0f, false),
                Warning = FindOrCreateMaterial("Demo_Warning", new Color(0.95f, 0.42f, 0.05f), 0.25f, 0f, false)
            };

            AssetDatabase.SaveAssets();
            return materials;
        }

        /// <summary>
        /// Низкофрикционный PhysicMaterial для днища погрузчика: без него 900 кг «прилипают»
        /// к полу (трение покоя > тяги) и машина не срывается с места.
        /// </summary>
        private static PhysicMaterial CreateChassisPhysicMaterial()
        {
            EnsureFolder(PhysicsFolder);

            string assetPath = PhysicsFolder + "/Demo_Chassis_Slippery.physicMaterial";
            PhysicMaterial material = AssetDatabase.LoadAssetAtPath<PhysicMaterial>(assetPath);

            if (material == null)
            {
                material = new PhysicMaterial("Demo_Chassis_Slippery");
                AssetDatabase.CreateAsset(material, assetPath);
            }

            material.dynamicFriction = 0.2f;
            material.staticFriction = 0.2f;
            material.bounciness = 0f;
            material.frictionCombine = PhysicMaterialCombine.Minimum;
            material.bounceCombine = PhysicMaterialCombine.Minimum;

            EditorUtility.SetDirty(material);
            AssetDatabase.SaveAssets();
            return material;
        }

        private static Material FindOrCreateMaterial(string materialName, Color color, float smoothness, float metallic, bool transparent)
        {
            Shader shader = FindSuitableShader();
            if (shader == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найден подходящий шейдер — материалы не созданы.");
                return null;
            }

            string assetPath = MaterialsFolder + "/" + materialName + ".mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);

            if (material == null)
            {
                material = new Material(shader);
                AssetDatabase.CreateAsset(material, assetPath);
            }

            material.shader = shader;
            SetMaterialColor(material, color);
            SetMaterialFloatIfPresent(material, "_Glossiness", smoothness);
            SetMaterialFloatIfPresent(material, "_Smoothness", smoothness);
            SetMaterialFloatIfPresent(material, "_Metallic", metallic);
            SetMaterialFloatIfPresent(material, "_SpecularHighlights", 1f);
            SetMaterialFloatIfPresent(material, "_EnvironmentReflections", 1f);

            if (transparent)
            {
                SetMaterialTransparent(material);
            }

            EditorUtility.SetDirty(material);
            return material;
        }

        private static Shader FindSuitableShader()
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader != null)
            {
                return shader;
            }

            shader = Shader.Find("Standard");
            if (shader != null)
            {
                return shader;
            }

            shader = Shader.Find("HDRP/Lit");
            if (shader != null)
            {
                return shader;
            }

            return Shader.Find("Unlit/Color");
        }

        private static void SetMaterialColor(Material material, Color color)
        {
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }

            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }

            if (material.HasProperty("_UnlitColor"))
            {
                material.SetColor("_UnlitColor", color);
            }
        }

        private static void SetMaterialFloatIfPresent(Material material, string propertyName, float value)
        {
            if (material.HasProperty(propertyName))
            {
                material.SetFloat(propertyName, value);
            }
        }

        private static void SetMaterialTransparent(Material material)
        {
            bool isStandardShader = material.HasProperty("_Mode") && material.HasProperty("_SrcBlend");
            bool isUniversalShader = material.HasProperty("_Surface") && material.HasProperty("_Blend");

            if (isStandardShader)
            {
                material.SetFloat("_Mode", 3f); // 3 = Transparent (режим рендеринга у Standard-шейдера)
            }
            else if (isUniversalShader)
            {
                material.SetFloat("_Surface", 1f); // 1 = Transparent (URP/Lit)
                material.SetFloat("_Blend", 0f);   // 0 = Alpha
                SetMaterialFloatIfPresent(material, "_AlphaClip", 0f);
                material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            }

            if (material.HasProperty("_SrcBlend"))
            {
                material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            }

            if (material.HasProperty("_DstBlend"))
            {
                material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            }

            if (material.HasProperty("_ZWrite"))
            {
                material.SetInt("_ZWrite", 0);
            }

            material.DisableKeyword("_ALPHATEST_ON");
            material.EnableKeyword("_ALPHABLEND_ON");
            material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
        }

        private static void EnsureFolder(string folderPath)
        {
            if (string.IsNullOrEmpty(folderPath) || AssetDatabase.IsValidFolder(folderPath))
            {
                return;
            }

            string[] parts = folderPath.Split('/');
            string current = parts[0];

            for (int i = 1; i < parts.Length; i++)
            {
                string next = current + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next))
                {
                    AssetDatabase.CreateFolder(current, parts[i]);
                }

                current = next;
            }
        }

        private static string GetDirectoryName(string path, string fallback)
        {
            if (string.IsNullOrEmpty(path))
            {
                return fallback;
            }

            int lastSlash = path.LastIndexOf('/');
            return lastSlash > 0 ? path.Substring(0, lastSlash) : fallback;
        }

        #endregion

        #region Площадка

        private static GameObject BuildGround(Transform parent, Scene scene, DemoMaterials materials, int groundLayer, string groundTag)
        {
            GameObject ground = CreatePrimitive("Ground", PrimitiveType.Cube, parent, scene, new Vector3(0f, -0.5f, 0f), Quaternion.identity);
            ground.transform.localScale = new Vector3(GroundSize, 1f, GroundSize);

            if (groundLayer > 0)
            {
                ground.layer = groundLayer;
            }

            if (!string.IsNullOrEmpty(groundTag))
            {
                ground.tag = groundTag;
            }

            if (materials.Ground != null)
            {
                ground.GetComponent<MeshRenderer>().sharedMaterial = materials.Ground;
            }

            // Грунтовая дорога от старта к амбару (декор без коллайдера — колесо не спотыкается).
            GameObject road = CreateDecorPrimitive("Road", PrimitiveType.Cube, parent, scene, new Vector3(0f, 0.004f, -4f), Quaternion.identity);
            road.transform.localScale = new Vector3(9f, 0.008f, 58f);
            ApplyMaterial(road, materials.Dirt);

            return ground;
        }

        /// <summary>
        /// Фермерский дом из примитивов: коробка стен (один коллайдер на всё здание),
        /// двускатная крыша, труба, дверь, окна, крыльцо и бочки. Стоит слева от старта.
        /// </summary>
        /// <summary>
        /// Окно: стекло + рама из четырёх брусков, стойка-переплёт и подоконник.
        /// Так окно читается как проём в стене, а не как цветной квадрат.
        /// </summary>
        private static void BuildWindow(Transform parent, Scene scene, DemoMaterials materials, string objectName,
            Vector3 localPosition, float width, float height, bool thinAlongX)
        {
            const float glassDepth = 0.14f;
            const float bar = 0.1f;

            GameObject glass = CreateDecorPrimitive(objectName + "_Glass", PrimitiveType.Cube, parent, scene, localPosition, Quaternion.identity);
            glass.transform.localScale = thinAlongX
                ? new Vector3(glassDepth, height, width)
                : new Vector3(width, height, glassDepth);
            ApplyMaterial(glass, materials.Window);

            // Верхний и нижний бруски + боковые стойки.
            Vector3 horizontalScale = thinAlongX
                ? new Vector3(glassDepth + 0.05f, bar, width + bar * 2f)
                : new Vector3(width + bar * 2f, bar, glassDepth + 0.05f);

            Vector3 verticalScale = thinAlongX
                ? new Vector3(glassDepth + 0.05f, height + bar, bar)
                : new Vector3(bar, height + bar, glassDepth + 0.05f);

            GameObject topBar = CreateDecorPrimitive(objectName + "_FrameTop", PrimitiveType.Cube, parent, scene,
                localPosition + new Vector3(0f, height * 0.5f, 0f), Quaternion.identity);
            topBar.transform.localScale = horizontalScale;
            ApplyMaterial(topBar, materials.WindowFrame);

            GameObject bottomBar = CreateDecorPrimitive(objectName + "_FrameBottom", PrimitiveType.Cube, parent, scene,
                localPosition + new Vector3(0f, -height * 0.5f, 0f), Quaternion.identity);
            bottomBar.transform.localScale = horizontalScale;
            ApplyMaterial(bottomBar, materials.WindowFrame);

            for (int side = -1; side <= 1; side += 2)
            {
                Vector3 offset = thinAlongX
                    ? new Vector3(0f, 0f, side * width * 0.5f)
                    : new Vector3(side * width * 0.5f, 0f, 0f);

                GameObject post = CreateDecorPrimitive(objectName + "_Frame_" + (side > 0 ? "R" : "L"), PrimitiveType.Cube, parent, scene,
                    localPosition + offset, Quaternion.identity);
                post.transform.localScale = verticalScale;
                ApplyMaterial(post, materials.WindowFrame);
            }

            // Переплёт посередине: делит стекло на две створки.
            GameObject mullion = CreateDecorPrimitive(objectName + "_Frame_Mid", PrimitiveType.Cube, parent, scene, localPosition, Quaternion.identity);
            mullion.transform.localScale = thinAlongX
                ? new Vector3(glassDepth + 0.05f, height, bar * 0.7f)
                : new Vector3(bar * 0.7f, height, glassDepth + 0.05f);
            ApplyMaterial(mullion, materials.WindowFrame);

            // Подоконник.
            Vector3 sillOffset = thinAlongX
                ? new Vector3(0f, -height * 0.5f - 0.09f, 0f)
                : new Vector3(0f, -height * 0.5f - 0.09f, 0f);

            GameObject sill = CreateDecorPrimitive(objectName + "_Sill", PrimitiveType.Cube, parent, scene, localPosition + sillOffset, Quaternion.identity);
            sill.transform.localScale = thinAlongX
                ? new Vector3(glassDepth + 0.28f, 0.09f, width + 0.36f)
                : new Vector3(width + 0.36f, 0.09f, glassDepth + 0.28f);
            ApplyMaterial(sill, materials.Wood);
        }

        private static GameObject BuildHouse(Transform parent, Scene scene, DemoMaterials materials)
        {
            GameObject house = CreateGameObject("House", parent, scene, HousePosition, Quaternion.identity);

            // Один коллайдер на всё здание — погрузчик не проезжает дом насквозь.
            BoxCollider houseCollider = house.AddComponent<BoxCollider>();
            houseCollider.center = new Vector3(0f, HouseWallHeight * 0.5f, 0f);
            houseCollider.size = new Vector3(HouseWidth, HouseWallHeight, HouseDepth);

            GameObject walls = CreateDecorPrimitive("Walls", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, HouseWallHeight * 0.5f, 0f), Quaternion.identity);
            walls.transform.localScale = new Vector3(HouseWidth, HouseWallHeight, HouseDepth);
            ApplyMaterial(walls, materials.HouseWall);

            // Кирпичный поясок по низу и угловые брёвна: дом перестаёт быть однотонным кубом.
            GameObject brickBand = CreateDecorPrimitive("BrickBand", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, 0.42f, 0f), Quaternion.identity);
            brickBand.transform.localScale = new Vector3(HouseWidth + 0.06f, 0.45f, HouseDepth + 0.06f);
            ApplyMaterial(brickBand, materials.HouseWallBrick);

            for (int cornerX = -1; cornerX <= 1; cornerX += 2)
            {
                for (int cornerZ = -1; cornerZ <= 1; cornerZ += 2)
                {
                    GameObject cornerBeam = CreateDecorPrimitive(
                        string.Format("CornerBeam_{0}{1}", cornerX > 0 ? "R" : "L", cornerZ > 0 ? "B" : "F"),
                        PrimitiveType.Cube, house.transform, scene,
                        new Vector3(cornerX * (HouseWidth * 0.5f - 0.1f), HouseWallHeight * 0.5f, cornerZ * (HouseDepth * 0.5f - 0.1f)),
                        Quaternion.identity);
                    cornerBeam.transform.localScale = new Vector3(0.3f, HouseWallHeight, 0.3f);
                    ApplyMaterial(cornerBeam, materials.Wood);
                }
            }

            GameObject foundation = CreateDecorPrimitive("Foundation", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, 0.12f, 0f), Quaternion.identity);
            foundation.transform.localScale = new Vector3(HouseWidth + 0.3f, 0.24f, HouseDepth + 0.3f);
            ApplyMaterial(foundation, materials.Stone);

            // Двускатная крыша: две наклонные плиты вокруг конька по оси X.
            float roofHalfSpan = HouseDepth * 0.5f + 0.6f;
            float roofSlope = Mathf.Sqrt(roofHalfSpan * roofHalfSpan + HouseRoofHeight * HouseRoofHeight);
            float roofAngle = Mathf.Atan2(HouseRoofHeight, roofHalfSpan) * Mathf.Rad2Deg;
            float roofCenterHeight = HouseWallHeight + HouseRoofHeight * 0.5f;

            GameObject roofBack = CreateDecorPrimitive("Roof_Back", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, roofCenterHeight, roofHalfSpan * 0.5f), Quaternion.Euler(roofAngle, 0f, 0f));
            roofBack.transform.localScale = new Vector3(HouseWidth + 1f, 0.25f, roofSlope);
            ApplyMaterial(roofBack, materials.HouseRoof);

            GameObject roofFront = CreateDecorPrimitive("Roof_Front", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, roofCenterHeight, -roofHalfSpan * 0.5f), Quaternion.Euler(-roofAngle, 0f, 0f));
            roofFront.transform.localScale = new Vector3(HouseWidth + 1f, 0.25f, roofSlope);
            ApplyMaterial(roofFront, materials.HouseRoof);

            // Конёк и подшивка свесов — крыша выглядит собранной, а не двумя одинаковыми плитами.
            GameObject houseRidge = CreateDecorPrimitive("Roof_Ridge", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, HouseWallHeight + HouseRoofHeight + 0.02f, 0f), Quaternion.identity);
            houseRidge.transform.localScale = new Vector3(HouseWidth + 1.2f, 0.24f, 0.55f);
            ApplyMaterial(houseRidge, materials.HouseRoofRidge);

            for (int eaveSide = -1; eaveSide <= 1; eaveSide += 2)
            {
                GameObject eave = CreateDecorPrimitive("Roof_Eave_" + (eaveSide > 0 ? "Back" : "Front"), PrimitiveType.Cube, house.transform, scene,
                    new Vector3(0f, HouseWallHeight - 0.06f, eaveSide * (HouseDepth * 0.5f + 0.55f)), Quaternion.identity);
                eave.transform.localScale = new Vector3(HouseWidth + 1.3f, 0.18f, 0.5f);
                ApplyMaterial(eave, materials.WoodDark);
            }

            GameObject chimney = CreateDecorPrimitive("Chimney", PrimitiveType.Cube, house.transform, scene,
                new Vector3(HouseWidth * 0.25f, HouseWallHeight + HouseRoofHeight + 0.6f, -1f), Quaternion.identity);
            chimney.transform.localScale = new Vector3(0.9f, 2.6f, 0.9f);
            ApplyMaterial(chimney, materials.Stone);

            // Дверь и крыльцо со стороны двора (+Z).
            GameObject door = CreateDecorPrimitive("Door", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, HouseWallHeight * 0.5f, HouseDepth * 0.5f + 0.03f), Quaternion.identity);
            door.transform.localScale = new Vector3(1.4f, HouseWallHeight * 0.62f, 0.12f);
            ApplyMaterial(door, materials.WoodDark);

            // Дверная рама: стойки, перекладина и козырёк над крыльцом.
            float houseDoorHeight = HouseWallHeight * 0.62f;

            for (int side = -1; side <= 1; side += 2)
            {
                GameObject doorPost = CreateDecorPrimitive("DoorFrame_Post_" + (side > 0 ? "R" : "L"), PrimitiveType.Cube, house.transform, scene,
                    new Vector3(side * 0.82f, houseDoorHeight * 0.5f, HouseDepth * 0.5f + 0.06f), Quaternion.identity);
                doorPost.transform.localScale = new Vector3(0.22f, houseDoorHeight + 0.25f, 0.2f);
                ApplyMaterial(doorPost, materials.WindowFrame);
            }

            GameObject doorLintel = CreateDecorPrimitive("DoorFrame_Lintel", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, houseDoorHeight + 0.16f, HouseDepth * 0.5f + 0.06f), Quaternion.identity);
            doorLintel.transform.localScale = new Vector3(1.9f, 0.22f, 0.22f);
            ApplyMaterial(doorLintel, materials.WindowFrame);

            GameObject doorCanopy = CreateDecorPrimitive("DoorCanopy", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, houseDoorHeight + 0.45f, HouseDepth * 0.5f + 0.65f), Quaternion.Euler(-12f, 0f, 0f));
            doorCanopy.transform.localScale = new Vector3(2.2f, 0.12f, 1.4f);
            ApplyMaterial(doorCanopy, materials.HouseRoof);

            GameObject porch = CreateDecorPrimitive("Porch", PrimitiveType.Cube, house.transform, scene,
                new Vector3(0f, 0.1f, HouseDepth * 0.5f + 0.9f), Quaternion.identity);
            porch.transform.localScale = new Vector3(3.2f, 0.2f, 1.8f);
            ApplyMaterial(porch, materials.Wood);

            // Окна: два на фасаде и два на боковой стене — стекло в раме с переплётом и подоконником.
            float houseWindowY = HouseWallHeight * 0.58f;
            BuildWindow(house.transform, scene, materials, "Window_Front_1",
                new Vector3(-3.2f, houseWindowY, HouseDepth * 0.5f + 0.01f), 1.8f, 1.3f, false);
            BuildWindow(house.transform, scene, materials, "Window_Front_2",
                new Vector3(3.2f, houseWindowY, HouseDepth * 0.5f + 0.01f), 1.8f, 1.3f, false);
            BuildWindow(house.transform, scene, materials, "Window_Side_1",
                new Vector3(HouseWidth * 0.5f + 0.01f, houseWindowY, -1.8f), 1.8f, 1.3f, true);
            BuildWindow(house.transform, scene, materials, "Window_Side_2",
                new Vector3(HouseWidth * 0.5f + 0.01f, houseWindowY, 1.8f), 1.8f, 1.3f, true);

            // Бочки во дворе — мелкий декор.
            for (int i = 0; i < 2; i++)
            {
                GameObject barrel = CreateDecorPrimitive("Barrel_" + (i + 1), PrimitiveType.Cylinder, house.transform, scene,
                    new Vector3(-HouseWidth * 0.5f - 1.2f + i * 0.95f, 0.5f, HouseDepth * 0.5f - 0.6f), Quaternion.identity);
                barrel.transform.localScale = new Vector3(0.85f, 0.5f, 0.85f);
                ApplyMaterial(barrel, materials.Wood);
            }

            return house;
        }

        /// <summary>
        /// Большой амбар: стены с коллайдерами, широкий открытый въезд под перекладиной,
        /// двускатная крыша, внутренние стойки, сено и пол. Проём всегда обращён к старту (−Z),
        /// поэтому погрузчик заезжает внутрь по прямой. Зоны сортировки стоят внутри амбара.
        /// </summary>
        private static GameObject BuildBarn(Transform parent, Scene scene, DemoMaterials materials, string barnTag)
        {
            GameObject barn = CreateGameObject("Barn", parent, scene, BarnPosition, Quaternion.identity);

            if (!string.IsNullOrEmpty(barnTag))
            {
                barn.tag = barnTag;
            }

            float halfWidth = BarnWidth * 0.5f;
            float halfDepth = BarnDepth * 0.5f;
            float wallThickness = BarnWallThickness;
            float halfWall = wallThickness * 0.5f;

            // Пол амбара — декор без коллайдера, чтобы не создавать ступеньку под колёсами.
            GameObject floor = CreateDecorPrimitive("Floor", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, 0.005f, 0f), Quaternion.identity);
            floor.transform.localScale = new Vector3(BarnWidth - wallThickness, 0.01f, BarnDepth - wallThickness);
            ApplyMaterial(floor, materials.BarnFloor);

            // Боковые стены (по X) — с коллайдерами.
            CreateBarnWall("Wall_Left", barn.transform, scene, materials,
                new Vector3(-halfWidth + halfWall, BarnHeight * 0.5f, 0f),
                new Vector3(wallThickness, BarnHeight, BarnDepth));

            CreateBarnWall("Wall_Right", barn.transform, scene, materials,
                new Vector3(halfWidth - halfWall, BarnHeight * 0.5f, 0f),
                new Vector3(wallThickness, BarnHeight, BarnDepth));

            // Дальняя стена (Z+).
            CreateBarnWall("Wall_Back", barn.transform, scene, materials,
                new Vector3(0f, BarnHeight * 0.5f, halfDepth - halfWall),
                new Vector3(BarnWidth - wallThickness * 2f, BarnHeight, wallThickness));

            // Передняя стена (Z−) с проёмом: две секции по бокам плюс перекладина сверху.
            float sideSegmentWidth = (BarnWidth - BarnOpeningWidth) * 0.5f;

            CreateBarnWall("Wall_Front_Left", barn.transform, scene, materials,
                new Vector3(-BarnOpeningWidth * 0.5f - sideSegmentWidth * 0.5f, BarnHeight * 0.5f, -halfDepth + halfWall),
                new Vector3(sideSegmentWidth, BarnHeight, wallThickness));

            CreateBarnWall("Wall_Front_Right", barn.transform, scene, materials,
                new Vector3(BarnOpeningWidth * 0.5f + sideSegmentWidth * 0.5f, BarnHeight * 0.5f, -halfDepth + halfWall),
                new Vector3(sideSegmentWidth, BarnHeight, wallThickness));

            float headerHeight = BarnHeight - BarnOpeningHeight;

            CreateBarnWall("Wall_Front_Header", barn.transform, scene, materials,
                new Vector3(0f, BarnHeight - headerHeight * 0.5f, -halfDepth + halfWall),
                new Vector3(BarnOpeningWidth, headerHeight, wallThickness));

            // Дверная рама въезда: стойки, перекладина и табличка над проёмом.
            for (int side = -1; side <= 1; side += 2)
            {
                GameObject openingPost = CreateDecorPrimitive("DoorFrame_Post_" + (side > 0 ? "R" : "L"), PrimitiveType.Cube, barn.transform, scene,
                    new Vector3(side * (BarnOpeningWidth * 0.5f + 0.22f), BarnOpeningHeight * 0.5f, -halfDepth + halfWall), Quaternion.identity);
                openingPost.transform.localScale = new Vector3(0.4f, BarnOpeningHeight, 0.6f);
                ApplyMaterial(openingPost, materials.BarnDoorFrame);
            }

            GameObject openingLintel = CreateDecorPrimitive("DoorFrame_Lintel", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, BarnOpeningHeight + 0.22f, -halfDepth + halfWall), Quaternion.identity);
            openingLintel.transform.localScale = new Vector3(BarnOpeningWidth + 0.85f, 0.45f, 0.6f);
            ApplyMaterial(openingLintel, materials.BarnDoorFrame);

            GameObject barnSign = CreateDecorPrimitive("Sign_Plate", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, BarnOpeningHeight + 0.95f, -halfDepth - 0.07f), Quaternion.identity);
            barnSign.transform.localScale = new Vector3(3.4f, 0.7f, 0.12f);
            ApplyMaterial(barnSign, materials.Warning);

            // Вертикальная обшивка боковых стен и наискось поставленные укосины спереди.
            for (int side = -1; side <= 1; side += 2)
            {
                for (int i = 0; i < 3; i++)
                {
                    float slatZ = -halfDepth + 2.6f + i * 5.6f;
                    GameObject slat = CreateDecorPrimitive("WallSlat_" + (side > 0 ? "R" : "L") + "_" + (i + 1), PrimitiveType.Cube, barn.transform, scene,
                        new Vector3(side * (halfWidth - wallThickness - 0.07f), BarnHeight * 0.5f, slatZ), Quaternion.identity);
                    slat.transform.localScale = new Vector3(0.14f, BarnHeight, 0.3f);
                    ApplyMaterial(slat, materials.BarnFrame);
                }
            }

            for (int side = -1; side <= 1; side += 2)
            {
                float segmentCenterX = side * (BarnOpeningWidth * 0.5f + sideSegmentWidth * 0.5f);
                GameObject brace = CreateDecorPrimitive("FrontBrace_" + (side > 0 ? "R" : "L"), PrimitiveType.Cube, barn.transform, scene,
                    new Vector3(segmentCenterX, BarnHeight * 0.5f, -halfDepth - 0.03f), Quaternion.Euler(0f, 0f, side * 32f));
                brace.transform.localScale = new Vector3(0.22f, Mathf.Sqrt(sideSegmentWidth * sideSegmentWidth + BarnHeight * BarnHeight) * 0.92f, 0.16f);
                ApplyMaterial(brace, materials.BarnFrame);
            }

            // Двускатная крыша вокруг конька по оси X (декор: погрузчик до неё не достаёт).
            float roofHalfSpan = halfDepth + 0.9f;
            float roofSlope = Mathf.Sqrt(roofHalfSpan * roofHalfSpan + BarnGableHeight * BarnGableHeight);
            float roofAngle = Mathf.Atan2(BarnGableHeight, roofHalfSpan) * Mathf.Rad2Deg;
            float roofCenterHeight = BarnHeight + BarnGableHeight * 0.5f;

            GameObject roofBack = CreateDecorPrimitive("Roof_Back", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, roofCenterHeight, roofHalfSpan * 0.5f), Quaternion.Euler(roofAngle, 0f, 0f));
            roofBack.transform.localScale = new Vector3(BarnWidth + 1.6f, 0.3f, roofSlope);
            ApplyMaterial(roofBack, materials.BarnRoof);

            GameObject roofFront = CreateDecorPrimitive("Roof_Front", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, roofCenterHeight, -roofHalfSpan * 0.5f), Quaternion.Euler(-roofAngle, 0f, 0f));
            roofFront.transform.localScale = new Vector3(BarnWidth + 1.6f, 0.3f, roofSlope);
            ApplyMaterial(roofFront, materials.BarnRoof);

            GameObject ridge = CreateDecorPrimitive("Roof_Ridge", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, BarnHeight + BarnGableHeight, 0f), Quaternion.identity);
            ridge.transform.localScale = new Vector3(BarnWidth + 1.6f, 0.35f, 0.5f);
            ApplyMaterial(ridge, materials.BarnFrame);

            for (int eaveSide = -1; eaveSide <= 1; eaveSide += 2)
            {
                GameObject eave = CreateDecorPrimitive("Eave_" + (eaveSide > 0 ? "Back" : "Front"), PrimitiveType.Cube, barn.transform, scene,
                    new Vector3(0f, BarnHeight - 0.12f, eaveSide * (halfDepth + 0.75f)), Quaternion.identity);
                eave.transform.localScale = new Vector3(BarnWidth + 1.9f, 0.22f, 0.55f);
                ApplyMaterial(eave, materials.BarnFrame);
            }

            // Деревянные стойки и балка внутри — визуальный каркас амбара.
            for (int i = -1; i <= 1; i += 2)
            {
                GameObject post = CreateDecorPrimitive("Post_" + (i > 0 ? "Right" : "Left"), PrimitiveType.Cube, barn.transform, scene,
                    new Vector3(i * (halfWidth - 1.2f), BarnHeight * 0.5f - 0.4f, 0f), Quaternion.identity);
                post.transform.localScale = new Vector3(0.3f, BarnHeight - 0.8f, 0.3f);
                ApplyMaterial(post, materials.BarnFrame);
            }

            GameObject beam = CreateDecorPrimitive("Beam_Cross", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, BarnHeight - 0.6f, 0f), Quaternion.identity);
            beam.transform.localScale = new Vector3(BarnWidth - wallThickness * 2f, 0.35f, 0.35f);
            ApplyMaterial(beam, materials.BarnFrame);

            // Вторая балка и средние стойки: внутри амбара читается каркас.
            GameObject midBeam = CreateDecorPrimitive("Beam_Mid", PrimitiveType.Cube, barn.transform, scene,
                new Vector3(0f, BarnHeight - 0.6f, halfDepth * 0.35f), Quaternion.identity);
            midBeam.transform.localScale = new Vector3(BarnWidth - wallThickness * 2f, 0.28f, 0.28f);
            ApplyMaterial(midBeam, materials.BarnFrame);

            for (int side = -1; side <= 1; side += 2)
            {
                GameObject midPost = CreateDecorPrimitive("Post_Mid_" + (side > 0 ? "Right" : "Left"), PrimitiveType.Cube, barn.transform, scene,
                    new Vector3(side * (halfWidth - 1.2f), BarnHeight * 0.5f - 0.4f, halfDepth * 0.35f), Quaternion.identity);
                midPost.transform.localScale = new Vector3(0.26f, BarnHeight - 0.8f, 0.26f);
                ApplyMaterial(midPost, materials.BarnFrame);
            }

            // Сено в углу.
            for (int i = 0; i < 3; i++)
            {
                GameObject hay = CreateDecorPrimitive("HayBale_" + (i + 1), PrimitiveType.Cube, barn.transform, scene,
                    new Vector3(halfWidth - 2.2f, 0.45f, -halfDepth + 2f + i * 1.15f), Quaternion.Euler(0f, 12f, 0f));
                hay.transform.localScale = new Vector3(1.5f, 0.9f, 1.1f);
                ApplyMaterial(hay, materials.Hay);
            }

            // Конусы у въезда — ориентир для водителя.
            for (int i = -1; i <= 1; i += 2)
            {
                GameObject cone = CreateDecorPrimitive("Cone_" + (i > 0 ? "Right" : "Left"), PrimitiveType.Cylinder, barn.transform, scene,
                    new Vector3(i * (BarnOpeningWidth * 0.5f + 0.9f), 0.35f, -halfDepth - 1.4f), Quaternion.identity);
                cone.transform.localScale = new Vector3(0.55f, 0.35f, 0.55f);
                ApplyMaterial(cone, materials.Warning);
            }

            return barn;
        }

        /// <summary>Стена амбара: с коллайдером (по умолчанию) либо чисто декоративная балка.</summary>
        private static GameObject CreateBarnWall(string objectName, Transform parent, Scene scene, DemoMaterials materials,
            Vector3 localPosition, Vector3 localScale, bool decorative = false)
        {
            GameObject wall = decorative
                ? CreateDecorPrimitive(objectName, PrimitiveType.Cube, parent, scene, localPosition, Quaternion.identity)
                : CreatePrimitive(objectName, PrimitiveType.Cube, parent, scene, localPosition, Quaternion.identity);

            wall.transform.localScale = localScale;
            ApplyMaterial(wall, decorative ? materials.BarnFrame : materials.BarnWall);
            return wall;
        }

        #endregion

        #region Погрузчик

        private static GameObject BuildForklift(
            Transform parent,
            Scene scene,
            GenerationOptions options,
            DemoMaterials materials,
            PhysicMaterial chassisMaterial,
            int groundLayer,
            int cargoLayer,
            out ForkliftController forkliftController,
            out Transform resetPoint)
        {
            Vector3 forkliftPosition = ForkliftStartPosition;
            Quaternion forkliftRotation = Quaternion.Euler(0f, options.forkliftStartYaw, 0f);

            GameObject forklift = CreateGameObject("Forklift", parent, scene, forkliftPosition, forkliftRotation,
                typeof(Rigidbody), typeof(BoxCollider), typeof(ForkliftController));

            forkliftController = forklift.GetComponent<ForkliftController>();

            // Днище корпуса опускаем до низа колёс (y ≈ 0.025 при радиусе колеса 0.3):
            // 900 кг опираются на пол всей площадью, визуально колёса стоят на земле.
            BoxCollider bodyCollider = forklift.GetComponent<BoxCollider>();
            bodyCollider.center = new Vector3(0f, 0.92f, 0.15f);
            bodyCollider.size = new Vector3(1.5f, 1.79f, 2.3f);

            // Низкофрикционный материал: без него машина не срывается с места на малой тяге.
            if (chassisMaterial != null)
            {
                bodyCollider.sharedMaterial = chassisMaterial;
            }

            Rigidbody body = forklift.GetComponent<Rigidbody>();
            body.mass = 900f;
            body.drag = 0.05f;
            body.angularDrag = 4f;
            body.interpolation = RigidbodyInterpolation.Interpolate;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;

            GameObject bodyMesh = CreateDecorPrimitive("Body", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 1.05f, 0.15f), Quaternion.identity);
            bodyMesh.transform.localScale = new Vector3(1.5f, 1.4f, 2.3f);
            ApplyMaterial(bodyMesh, materials.ForkliftBody);

            // Задний противовес, топливный бак с хомутами и выхлопная труба.
            GameObject counterweight = CreateDecorPrimitive("Counterweight", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 0.72f, -1.3f), Quaternion.identity);
            counterweight.transform.localScale = new Vector3(1.4f, 1.0f, 0.55f);
            ApplyMaterial(counterweight, materials.ForkliftAccent);

            GameObject rearTank = CreateDecorPrimitive("RearTank", PrimitiveType.Cylinder, forklift.transform, scene, new Vector3(0f, 1.55f, -1.3f), Quaternion.Euler(90f, 0f, 0f));
            rearTank.transform.localScale = new Vector3(0.75f, 0.42f, 0.75f);
            ApplyMaterial(rearTank, materials.ForkliftChrome);

            GameObject tankCap = CreateDecorPrimitive("RearTankCap", PrimitiveType.Cylinder, forklift.transform, scene, new Vector3(0.32f, 1.92f, -1.3f), Quaternion.identity);
            tankCap.transform.localScale = new Vector3(0.18f, 0.06f, 0.18f);
            ApplyMaterial(tankCap, materials.ForkliftAccent);

            for (int strapSide = -1; strapSide <= 1; strapSide += 2)
            {
                GameObject tankStrap = CreateDecorPrimitive("RearTankStrap_" + (strapSide > 0 ? "R" : "L"), PrimitiveType.Cube, forklift.transform, scene,
                    new Vector3(strapSide * 0.3f, 1.55f, -1.3f), Quaternion.identity);
                tankStrap.transform.localScale = new Vector3(0.08f, 0.78f, 0.8f);
                ApplyMaterial(tankStrap, materials.ForkliftAccent);
            }

            GameObject exhaust = CreateDecorPrimitive("Exhaust", PrimitiveType.Cylinder, forklift.transform, scene, new Vector3(0.55f, 2.2f, -1.05f), Quaternion.identity);
            exhaust.transform.localScale = new Vector3(0.12f, 0.45f, 0.12f);
            ApplyMaterial(exhaust, materials.ForkliftChrome);

            // Кабина: коробка, остекление по трём сторонам и стойки.
            GameObject cabin = CreateDecorPrimitive("Cabin", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 2.05f, -0.55f), Quaternion.identity);
            cabin.transform.localScale = new Vector3(1.25f, 0.6f, 1.1f);
            ApplyMaterial(cabin, materials.ForkliftBody);

            GameObject cabinGlassFront = CreateDecorPrimitive("CabinGlass_Front", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 1.98f, 0.03f), Quaternion.identity);
            cabinGlassFront.transform.localScale = new Vector3(1.05f, 0.52f, 0.06f);
            ApplyMaterial(cabinGlassFront, materials.ForkliftGlass);

            for (int glassSide = -1; glassSide <= 1; glassSide += 2)
            {
                GameObject cabinGlass = CreateDecorPrimitive("CabinGlass_" + (glassSide > 0 ? "R" : "L"), PrimitiveType.Cube, forklift.transform, scene,
                    new Vector3(glassSide * 0.64f, 1.98f, -0.55f), Quaternion.identity);
                cabinGlass.transform.localScale = new Vector3(0.06f, 0.52f, 0.95f);
                ApplyMaterial(cabinGlass, materials.ForkliftGlass);
            }

            for (int postX = -1; postX <= 1; postX += 2)
            {
                for (int postZ = -1; postZ <= 1; postZ += 2)
                {
                    GameObject cabinPost = CreateDecorPrimitive(
                        string.Format("CabinPost_{0}{1}", postX > 0 ? "R" : "L", postZ > 0 ? "B" : "F"),
                        PrimitiveType.Cube, forklift.transform, scene,
                        new Vector3(postX * 0.6f, 2.1f, -0.55f + postZ * 0.52f), Quaternion.identity);
                    cabinPost.transform.localScale = new Vector3(0.1f, 1.1f, 0.1f);
                    ApplyMaterial(cabinPost, materials.ForkliftAccent);
                }
            }

            // Защитная решётка над кабиной: рама и три продольных прута.
            GameObject guardFrame = CreateDecorPrimitive("OverheadGuard", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 2.62f, -0.55f), Quaternion.identity);
            guardFrame.transform.localScale = new Vector3(1.42f, 0.12f, 1.32f);
            ApplyMaterial(guardFrame, materials.ForkliftAccent);

            for (int guardBar = -1; guardBar <= 1; guardBar++)
            {
                GameObject bar = CreateDecorPrimitive("GuardBar_" + (guardBar + 2), PrimitiveType.Cube, forklift.transform, scene,
                    new Vector3(guardBar * 0.45f, 2.55f, -0.55f), Quaternion.identity);
                bar.transform.localScale = new Vector3(0.08f, 0.08f, 1.48f);
                ApplyMaterial(bar, materials.ForkliftChrome);
            }

            // Фары спереди (на мачте) и габаритный огонь сзади.
            for (int headSide = -1; headSide <= 1; headSide += 2)
            {
                GameObject headlight = CreateDecorPrimitive("Headlight_" + (headSide > 0 ? "R" : "L"), PrimitiveType.Sphere, forklift.transform, scene,
                    new Vector3(headSide * 0.45f, 2.34f, 1.32f), Quaternion.identity);
                headlight.transform.localScale = Vector3.one * 0.22f;
                ApplyMaterial(headlight, materials.Headlight);
            }

            GameObject rearLight = CreateDecorPrimitive("RearLight", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 2.48f, -1.18f), Quaternion.identity);
            rearLight.transform.localScale = new Vector3(0.5f, 0.16f, 0.1f);
            ApplyMaterial(rearLight, materials.Warning);

            // Мачта: две направляющие, поперечины и гидроцилиндры.
            for (int mastSide = -1; mastSide <= 1; mastSide += 2)
            {
                GameObject mastRail = CreateDecorPrimitive("MastRail_" + (mastSide > 0 ? "R" : "L"), PrimitiveType.Cube, forklift.transform, scene,
                    new Vector3(mastSide * 0.52f, 1.5f, 1.2f), Quaternion.identity);
                mastRail.transform.localScale = new Vector3(0.16f, 2.6f, 0.32f);
                ApplyMaterial(mastRail, materials.ForkliftAccent);

                GameObject mastCylinder = CreateDecorPrimitive("MastCylinder_" + (mastSide > 0 ? "R" : "L"), PrimitiveType.Cylinder, forklift.transform, scene,
                    new Vector3(mastSide * 0.3f, 1.45f, 1.3f), Quaternion.identity);
                mastCylinder.transform.localScale = new Vector3(0.14f, 1.1f, 0.14f);
                ApplyMaterial(mastCylinder, materials.ForkliftChrome);
            }

            for (int tie = 0; tie < 3; tie++)
            {
                GameObject mastTie = CreateDecorPrimitive("MastTie_" + (tie + 1), PrimitiveType.Cube, forklift.transform, scene,
                    new Vector3(0f, 0.45f + tie * 1.0f, 1.2f), Quaternion.identity);
                mastTie.transform.localScale = new Vector3(1.14f, 0.12f, 0.36f);
                ApplyMaterial(mastTie, materials.ForkliftAccent);
            }

            // Шарнир наклона мачты: вокруг него наклоняются мачта и вилы.
            GameObject mastTiltPivot = CreateGameObject("MastTiltPivot", forklift.transform, scene, new Vector3(0f, 0.12f, 1.2f), Quaternion.identity);

            // Каретка вил: два коллайдера (вилы + вертикальная планка) и меши.
            GameObject forkCarriage = CreateGameObject("ForkCarriage", mastTiltPivot.transform, scene, new Vector3(0f, 0.02f, 0f), Quaternion.identity);

            BoxCollider forkCollider = forkCarriage.AddComponent<BoxCollider>();
            forkCollider.center = new Vector3(0f, 0f, 0.7f);
            forkCollider.size = new Vector3(1.3f, 0.14f, 1.7f);

            BoxCollider carriagePlateCollider = forkCarriage.AddComponent<BoxCollider>();
            carriagePlateCollider.center = new Vector3(0f, 0.5f, 0.02f);
            carriagePlateCollider.size = new Vector3(1.3f, 0.85f, 0.12f);

            GameObject carriagePlate = CreateDecorPrimitive("CarriagePlate", PrimitiveType.Cube, forkCarriage.transform, scene, new Vector3(0f, 0.5f, 0.02f), Quaternion.identity);
            carriagePlate.transform.localScale = new Vector3(1.3f, 0.85f, 0.12f);
            ApplyMaterial(carriagePlate, materials.ForkliftAccent);

            GameObject leftFork = CreateDecorPrimitive("Fork_Left", PrimitiveType.Cube, forkCarriage.transform, scene, new Vector3(-0.42f, 0f, 0.7f), Quaternion.identity);
            leftFork.transform.localScale = new Vector3(0.18f, 0.12f, 1.7f);
            ApplyMaterial(leftFork, materials.ForkliftAccent);

            GameObject rightFork = CreateDecorPrimitive("Fork_Right", PrimitiveType.Cube, forkCarriage.transform, scene, new Vector3(0.42f, 0f, 0.7f), Quaternion.identity);
            rightFork.transform.localScale = new Vector3(0.18f, 0.12f, 1.7f);
            ApplyMaterial(rightFork, materials.ForkliftAccent);

            // Скос-заезд на кончиках вил. Кубик стоит на земле, и под плоские вилы он физически
            // не поддевается — только толкается. Наклонная пластина работает пандусом: при наезде
            // кубик сам поднимается по ней и остаётся лежать на вилах.
            // Геометрия считается от фактических размеров вил: передняя кромка скоса лежит на земле
            // (когда вилы опущены в нижнее положение), задняя — чуть выше верхней плоскости вил.
            const float rampAngle = 10f;
            const float rampLength = 0.9f;
            const float rampThickness = 0.03f;
            // 4,5 см запаса: корпус в покое «садится» на 2,5 см (днище коллайдера на 0.025 выше нуля),
            // и кромка скоса не должна врезаться в землю.
            const float rampGroundClearance = 0.045f;

            // Нижнее положение вил берём из самого компонента — контроллер остаётся источником правды,
            // а не строковое имя поля. Демо-значение записываем до расчёта геометрии, чтобы прочитать
            // из компонента ровно ту высоту, с которой он будет работать в игре.
            ApplySerializedChanges(forkliftController, serializedObject =>
            {
                SetFloat(serializedObject, "forkMinHeight", ForkMinHeight);
                SetFloat(serializedObject, "startForkHeight", ForkMinHeight);
            });

            float forkMinHeight = forkliftController != null ? forkliftController.ForkMinHeight : ForkMinHeight;

            float rampAngleRadians = rampAngle * Mathf.Deg2Rad;
            float carriageLocalHeight = mastTiltPivot.transform.localPosition.y + forkMinHeight;
            float rampCenterLocalY = (rampGroundClearance - carriageLocalHeight)
                + rampLength * 0.5f * Mathf.Sin(rampAngleRadians)
                + rampThickness * 0.5f * Mathf.Cos(rampAngleRadians);
            float rampCenterLocalZ = forkCollider.center.z + forkCollider.size.z * 0.5f - rampLength * 0.5f;

            GameObject forkRamp = CreateGameObject("ForkRamp", forkCarriage.transform, scene,
                new Vector3(0f, rampCenterLocalY, rampCenterLocalZ), Quaternion.Euler(rampAngle, 0f, 0f));

            BoxCollider rampCollider = forkRamp.AddComponent<BoxCollider>();
            rampCollider.size = new Vector3(forkCollider.size.x, rampThickness, rampLength);

            if (chassisMaterial != null)
            {
                // Низкое трение: кубик должен скользить вверх по скосу, а не упираться в него.
                rampCollider.sharedMaterial = chassisMaterial;
            }

            // Точка проверки заземления — чуть выше днища корпуса.
            GameObject groundCheck = CreateGameObject("GroundCheck", forklift.transform, scene, new Vector3(0f, 0.4f, -0.5f), Quaternion.identity);

            // Визуальные колёса: пустышка (руль + качение) и цилиндр внутри неё.
            Transform[] wheels = new Transform[4];
            wheels[0] = CreateWheel("Wheel_FL", forklift.transform, scene, new Vector3(-0.75f, WheelRadius, 0.95f), materials);
            wheels[1] = CreateWheel("Wheel_FR", forklift.transform, scene, new Vector3(0.75f, WheelRadius, 0.95f), materials);
            wheels[2] = CreateWheel("Wheel_RL", forklift.transform, scene, new Vector3(-0.75f, WheelRadius, -0.8f), materials);
            wheels[3] = CreateWheel("Wheel_RR", forklift.transform, scene, new Vector3(0.75f, WheelRadius, -0.8f), materials);

            // Точка сброса (клавиша R) — отдельный корневой объект у стартовой позиции.
            GameObject resetPointObject = CreateGameObject("ForkliftResetPoint", parent, scene, forkliftPosition, forkliftRotation);
            resetPoint = resetPointObject.transform;

            // Автоназначение ссылок в инспекторе.
            Transform carriageTransform = forkCarriage.transform;
            Transform groundCheckTransform = groundCheck.transform;
            Transform mastPivotTransform = mastTiltPivot.transform;
            Transform resetTransform = resetPointObject.transform;
            int groundMask = 1 << groundLayer;
            int cargoMask = 1 << cargoLayer;

            ApplySerializedChanges(forkliftController, serializedObject =>
            {
                SetObjectReference(serializedObject, "forkCarriage", carriageTransform);
                SetObjectReference(serializedObject, "groundCheck", groundCheckTransform);
                SetObjectReference(serializedObject, "mastTiltPivot", mastPivotTransform);
                SetObjectReference(serializedObject, "resetPoint", resetTransform);
                SetInt(serializedObject, "groundLayers", groundMask);
                SetInt(serializedObject, "cargoLayers", cargoMask);
                SetObjectReference(serializedObject, "forkCollider", forkCollider);
                SetVector3(serializedObject, "carryVolumeCenter", new Vector3(0f, 0.3f, 0.45f));
                SetVector3(serializedObject, "carryVolumeSize", new Vector3(1.6f, 0.9f, 1.7f));
                // Захват груза: паллета фиксируется на вилах (kinematic + ребёнок каретки) и
                // плавно садится на место; F — взять/отпустить, опускание вил тоже отпускает груз.
                SetBool(serializedObject, "autoLockCargo", true);
                SetInt(serializedObject, "grabKey", (int)KeyCode.F);
                SetFloat(serializedObject, "lockAlignDuration", 0.22f);
                SetFloat(serializedObject, "relockDelay", 0.5f);
                SetBool(serializedObject, "autoReleaseWhenLowered", true);
                SetFloat(serializedObject, "autoReleaseLiftHeight", 0.3f);
                SetBool(serializedObject, "applyCargoWeight", true);
                SetFloat(serializedObject, "groundCheckDistance", 0.9f);
                SetFloat(serializedObject, "forkMinHeight", ForkMinHeight);
                SetFloat(serializedObject, "startForkHeight", ForkMinHeight);
                // Наклон вперёд в демо-сцене запрещён: на нижнем положении вил скос-заезд
                // упирается в землю, и физика начинает «выталкивать» погрузчик.
                SetFloat(serializedObject, "mastMinTilt", 0f);
                SetFloat(serializedObject, "mastMaxTilt", 20f);
                SetFloat(serializedObject, "groundCheckRadius", 0.22f);
                SetFloat(serializedObject, "forwardMotorForce", 16000f);
                SetFloat(serializedObject, "reverseMotorForce", 10000f);
                SetFloat(serializedObject, "brakeForce", 8000f);
                SetFloat(serializedObject, "handbrakeForce", 24000f);

                SerializedProperty wheelVisuals = serializedObject.FindProperty("wheelVisuals");
                if (wheelVisuals != null)
                {
                    wheelVisuals.arraySize = 4;

                    for (int i = 0; i < 4; i++)
                    {
                        SerializedProperty element = wheelVisuals.GetArrayElementAtIndex(i);
                        element.FindPropertyRelative("wheel").objectReferenceValue = wheels[i];
                        element.FindPropertyRelative("steerable").boolValue = i < 2;
                        element.FindPropertyRelative("radius").floatValue = WheelRadius;
                    }
                }
            });

            return forklift;
        }

        /// <summary>
        /// Визуальное колесо: пустышка (её крутит ForkliftController — руль и качение) и цилиндр-шина внутри.
        /// Передние колёса делаются рулевыми в настройке wheelVisuals ниже.
        /// </summary>
        private static Transform CreateWheel(string wheelName, Transform parent, Scene scene, Vector3 localPosition, DemoMaterials materials)
        {
            GameObject wheelRoot = CreateGameObject(wheelName, parent, scene, localPosition, Quaternion.identity);

            GameObject tire = CreateDecorPrimitive("Tire", PrimitiveType.Cylinder, wheelRoot.transform, scene, Vector3.zero, Quaternion.Euler(0f, 0f, 90f));
            tire.transform.localScale = new Vector3(WheelRadius * 2f, 0.175f, WheelRadius * 2f);
            ApplyMaterial(tire, materials.Wheel);

            // Металлический диск и ступица: колесо читается как колесо, а не как чёрный цилиндр.
            GameObject rim = CreateDecorPrimitive("Rim", PrimitiveType.Cylinder, wheelRoot.transform, scene, Vector3.zero, Quaternion.Euler(0f, 0f, 90f));
            rim.transform.localScale = new Vector3(WheelRadius * 1.3f, 0.185f, WheelRadius * 1.3f);
            ApplyMaterial(rim, materials.WheelRim);

            GameObject hub = CreateDecorPrimitive("Hub", PrimitiveType.Cylinder, wheelRoot.transform, scene, Vector3.zero, Quaternion.Euler(0f, 0f, 90f));
            hub.transform.localScale = new Vector3(WheelRadius * 0.45f, 0.2f, WheelRadius * 0.45f);
            ApplyMaterial(hub, materials.ForkliftAccent);

            // Протектор: шесть грунтозацепов по ободу.
            for (int tread = 0; tread < 6; tread++)
            {
                float angle = tread * 60f;
                float radians = angle * Mathf.Deg2Rad;
                Vector3 treadPosition = new Vector3(0f, Mathf.Cos(radians) * WheelRadius, Mathf.Sin(radians) * WheelRadius);

                GameObject treadBlock = CreateDecorPrimitive("Tread_" + (tread + 1), PrimitiveType.Cube, wheelRoot.transform, scene,
                    treadPosition, Quaternion.Euler(angle, 0f, 0f));
                treadBlock.transform.localScale = new Vector3(0.3f, 0.06f, 0.1f);
                ApplyMaterial(treadBlock, materials.Wheel);
            }

            return wheelRoot.transform;
        }

        #endregion

        #region Зоны сортировки

        /// <summary>
        /// Три зоны сортировки внутри амбара: ящики, бочки, стройматериалы.
        /// Зона читает тип груза (<see cref="CargoType"/>) и принимает только «свои» паллеты.
        /// </summary>
        private static void BuildSortingZones(Transform zoneParent, Scene scene, DemoMaterials materials, string zoneTag, bool insideBarn)
        {
            CargoType[] types = { CargoType.Boxes, CargoType.Barrels, CargoType.Construction };

            for (int i = 0; i < types.Length; i++)
            {
                CargoType cargoType = types[i];
                string zoneName = "SortingZone_" + cargoType;

                // Зоны стоят ВНУТРИ амбара: локальные координаты относительно его корня.
                // Если здания отключены в настройках — раскладываем зоны во дворе.
                Vector3 position = insideBarn
                    ? SortingZoneLocalPositions[Mathf.Clamp(i, 0, SortingZoneLocalPositions.Length - 1)]
                    : new Vector3(-8f + i * 8f, 0f, 2.5f);

                GameObject zone = CreateGameObject(zoneName, zoneParent, scene, position, Quaternion.identity, typeof(BoxCollider), typeof(SortingZone));

                if (!string.IsNullOrEmpty(zoneTag))
                {
                    zone.tag = zoneTag;
                }

                BoxCollider trigger = zone.GetComponent<BoxCollider>();
                trigger.isTrigger = true;
                trigger.center = new Vector3(0f, 0.9f, 0f);
                trigger.size = new Vector3(5f, 1.8f, 5f);

                Material zoneMaterial = SafeMaterial(materials, cargoType);

                // Площадка зоны: плоский декор без коллайдера, чтобы физика зоны шла только через триггер.
                GameObject pad = CreateDecorPrimitive("Pad", PrimitiveType.Cube, zone.transform, scene, new Vector3(0f, 0.012f, 0f), Quaternion.identity);
                pad.transform.localScale = new Vector3(5f, 0.02f, 5f);
                ApplyMaterial(pad, zoneMaterial);

                // Рамка по периметру: зона читается сверху и не сливается с полом амбара.
                for (int side = -1; side <= 1; side += 2)
                {
                    GameObject borderX = CreateDecorPrimitive("Border_X_" + (side > 0 ? "P" : "M"), PrimitiveType.Cube, zone.transform, scene,
                        new Vector3(0f, 0.05f, side * 2.35f), Quaternion.identity);
                    borderX.transform.localScale = new Vector3(5f, 0.1f, 0.3f);
                    ApplyMaterial(borderX, zoneMaterial);

                    GameObject borderZ = CreateDecorPrimitive("Border_Z_" + (side > 0 ? "P" : "M"), PrimitiveType.Cube, zone.transform, scene,
                        new Vector3(side * 2.35f, 0.05f, 0f), Quaternion.identity);
                    borderZ.transform.localScale = new Vector3(0.3f, 0.1f, 5f);
                    ApplyMaterial(borderZ, zoneMaterial);
                }

                // Указатель типа груза — виден из глубины амбара и со въезда.
                GameObject sign = CreateDecorPrimitive("Sign", PrimitiveType.Cube, zone.transform, scene, new Vector3(0f, 2.7f, -2.5f), Quaternion.identity);
                sign.transform.localScale = new Vector3(3f, 0.55f, 0.12f);
                ApplyMaterial(sign, zoneMaterial);

                BuildZoneCargoIcon(zone.transform, scene, materials, cargoType);

                SortingZone sortingZone = zone.GetComponent<SortingZone>();

                ApplySerializedChanges(sortingZone, serializedObject =>
                {
                    SetEnum<CargoType>(serializedObject, "targetType", cargoType);
                });
            }
        }

        /// <summary>Значок груза на указателе зоны: ящики, бочки или бетонная плита.</summary>
        private static void BuildZoneCargoIcon(Transform zone, Scene scene, DemoMaterials materials, CargoType cargoType)
        {
            Vector3 signPoint = new Vector3(0f, 2.7f, -2.42f);

            switch (cargoType)
            {
                case CargoType.Boxes:
                    for (int i = 0; i < 2; i++)
                    {
                        GameObject iconBox = CreateDecorPrimitive("SignIcon_Box_" + (i + 1), PrimitiveType.Cube, zone, scene,
                            signPoint + new Vector3(i * 0.42f - 0.21f, 0f, -0.12f), Quaternion.identity);
                        iconBox.transform.localScale = new Vector3(0.34f, 0.34f, 0.34f);
                        ApplyMaterial(iconBox, materials.Cardboard);
                    }
                    break;

                case CargoType.Barrels:
                    for (int i = 0; i < 2; i++)
                    {
                        GameObject iconBarrel = CreateDecorPrimitive("SignIcon_Barrel_" + (i + 1), PrimitiveType.Cylinder, zone, scene,
                            signPoint + new Vector3(i * 0.36f - 0.18f, 0f, -0.12f), Quaternion.identity);
                        iconBarrel.transform.localScale = new Vector3(0.28f, 0.17f, 0.28f);
                        ApplyMaterial(iconBarrel, materials.BarrelMetal);
                    }
                    break;

                case CargoType.Construction:
                    GameObject iconSlab = CreateDecorPrimitive("SignIcon_Slab", PrimitiveType.Cube, zone, scene,
                        signPoint + new Vector3(0f, 0f, -0.12f), Quaternion.identity);
                    iconSlab.transform.localScale = new Vector3(0.8f, 0.22f, 0.3f);
                    ApplyMaterial(iconSlab, materials.Concrete);
                    break;
            }
        }

        private static Material SafeMaterial(DemoMaterials materials, CargoType cargoType)
        {
            Material zoneMaterial = materials.GetZoneMaterial(cargoType);
            return zoneMaterial != null ? zoneMaterial : materials.GetCargoMaterial(cargoType);
        }

        #endregion

        #region Паллеты с грузом

        /// <summary>
        /// Паллеты с грузом на улице между домом и амбаром. Паллета — деревянный поддон из тонких
        /// реек (декор) с одним BoxCollider на всю паллету и грузом своего типа сверху:
        /// ящики, бочки или стройматериалы. Погрузчик фиксирует паллету на вилах (см. ForkliftController).
        /// </summary>
        private static void BuildPallets(Transform parent, Scene scene, GenerationOptions options, DemoMaterials materials, int cargoLayer, string cargoTag)
        {
            CargoType[] types = { CargoType.Boxes, CargoType.Barrels, CargoType.Construction };
            int perType = Mathf.Clamp(options.palletsPerType, 1, 4);
            int totalPallets = types.Length * perType;

            GameObject palletsRoot = CreateGameObject("CargoPallets", parent, scene, Vector3.zero, Quaternion.identity);
            List<Vector3> positions = BuildPalletScatterPositions(totalPallets);

            int palletIndex = 0;
            System.Random random = new System.Random(20240607);

            for (int typeIndex = 0; typeIndex < types.Length; typeIndex++)
            {
                CargoType cargoType = types[typeIndex];

                for (int i = 0; i < perType; i++)
                {
                    Vector3 position = positions[palletIndex];
                    Quaternion rotation = Quaternion.Euler(0f, NextFloat(random, 0f, 360f), 0f);

                    BuildPallet(palletsRoot.transform, scene, materials, cargoType, palletIndex, position, rotation, cargoLayer, cargoTag);
                    palletIndex++;
                }
            }
        }

        /// <summary>Одна паллета: поддон, груз по типу, коллайдер на всю паллету и компонент CargoPallet.</summary>
        private static GameObject BuildPallet(Transform parent, Scene scene, DemoMaterials materials, CargoType cargoType,
            int palletIndex, Vector3 position, Quaternion rotation, int cargoLayer, string cargoTag)
        {
            string palletName = string.Format("Pallet_{0}_{1:00}", cargoType, palletIndex + 1);

            GameObject pallet = CreateGameObject(palletName, parent, scene, position, rotation);

            Vector3 cargoSize = GetCargoSize(cargoType);
            float totalHeight = PalletDeckHeight + cargoSize.y;

            BoxCollider palletCollider = pallet.AddComponent<BoxCollider>();
            palletCollider.center = new Vector3(0f, totalHeight * 0.5f, 0f);
            palletCollider.size = new Vector3(
                Mathf.Max(PalletSizeX, cargoSize.x),
                totalHeight,
                Mathf.Max(PalletSizeZ, cargoSize.z));

            BuildPalletDeck(pallet.transform, scene, materials);
            BuildCargo(pallet.transform, scene, materials, cargoType, cargoSize);

            if (cargoLayer > 0)
            {
                pallet.layer = cargoLayer;
            }

            if (!string.IsNullOrEmpty(cargoTag))
            {
                pallet.tag = cargoTag;
            }

            Rigidbody palletBody = pallet.AddComponent<Rigidbody>();
            palletBody.mass = GetCargoMass(cargoType);
            palletBody.drag = 0.05f;
            palletBody.angularDrag = 0.8f;
            palletBody.interpolation = RigidbodyInterpolation.Interpolate;
            palletBody.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;

            CargoPallet cargoPallet = pallet.AddComponent<CargoPallet>();

            ApplySerializedChanges(cargoPallet, serializedObject =>
            {
                SetEnum<CargoType>(serializedObject, "cargoType", cargoType);
                SetInt(serializedObject, "scoreValue", GetCargoScore(cargoType));
                SetFloat(serializedObject, "mass", GetCargoMass(cargoType));
                SetBool(serializedObject, "isPushable", true);
                SetBool(serializedObject, "destroyAfterSorting", true);
                SetBool(serializedObject, "disablePhysicsAfterSorting", true);
            });

            return pallet;
        }

        /// <summary>Деревянный поддон: три подкладки снизу и настил из тонких реек сверху.</summary>
        private static void BuildPalletDeck(Transform parent, Scene scene, DemoMaterials materials)
        {
            float runnerHeight = PalletDeckHeight - PalletSlatHeight;

            for (int runner = -1; runner <= 1; runner++)
            {
                GameObject bottomBoard = CreateDecorPrimitive("Pallet_Runner_" + (runner + 2), PrimitiveType.Cube, parent, scene,
                    new Vector3(runner * (PalletSizeX * 0.5f - 0.12f), runnerHeight * 0.5f, 0f), Quaternion.identity);
                bottomBoard.transform.localScale = new Vector3(0.18f, runnerHeight, PalletSizeZ);
                ApplyMaterial(bottomBoard, materials.PalletWoodDark);
            }

            const int slats = 7;
            float slatPitch = PalletSizeZ / slats;

            for (int slat = 0; slat < slats; slat++)
            {
                float z = -PalletSizeZ * 0.5f + slatPitch * (slat + 0.5f);

                GameObject deckBoard = CreateDecorPrimitive("Pallet_Slat_" + (slat + 1), PrimitiveType.Cube, parent, scene,
                    new Vector3(0f, PalletDeckHeight - PalletSlatHeight * 0.5f, z), Quaternion.identity);
                deckBoard.transform.localScale = new Vector3(PalletSizeX, PalletSlatHeight, slatPitch * 0.78f);
                ApplyMaterial(deckBoard, materials.PalletWood);
            }
        }

        /// <summary>Габариты груза по типу (ширина, высота, глубина) — по ним строится коллайдер паллеты.</summary>
        private static Vector3 GetCargoSize(CargoType cargoType)
        {
            switch (cargoType)
            {
                case CargoType.Boxes: return new Vector3(1.12f, 0.95f, 0.98f);
                case CargoType.Barrels: return new Vector3(1.16f, 0.86f, 1.16f);
                case CargoType.Construction: return new Vector3(1.1f, 0.74f, 0.82f);
                default: return new Vector3(1f, 0.6f, 1f);
            }
        }

        /// <summary>Очки за правильную сортировку груза по типу.</summary>
        private static int GetCargoScore(CargoType cargoType)
        {
            switch (cargoType)
            {
                case CargoType.Boxes: return 10;
                case CargoType.Barrels: return 15;
                case CargoType.Construction: return 20;
                default: return 5;
            }
        }

        /// <summary>Масса паллеты с грузом, кг: тяжёлые плиты ощущаются на разгоне.</summary>
        private static float GetCargoMass(CargoType cargoType)
        {
            switch (cargoType)
            {
                case CargoType.Boxes: return 35f;
                case CargoType.Barrels: return 110f;
                case CargoType.Construction: return 160f;
                default: return 30f;
            }
        }

        private static void BuildCargo(Transform parent, Scene scene, DemoMaterials materials, CargoType cargoType, Vector3 cargoSize)
        {
            switch (cargoType)
            {
                case CargoType.Boxes:
                    BuildBoxesCargo(parent, scene, materials);
                    break;

                case CargoType.Barrels:
                    BuildBarrelsCargo(parent, scene, materials);
                    break;

                case CargoType.Construction:
                    BuildConstructionCargo(parent, scene, materials);
                    break;
            }
        }

        /// <summary>Ящики: картонные коробки в два слоя, верхние — со скотчем.</summary>
        private static void BuildBoxesCargo(Transform parent, Scene scene, DemoMaterials materials)
        {
            const float boxSize = 0.46f;
            float firstLayer = PalletDeckHeight + boxSize * 0.5f;
            float secondLayer = PalletDeckHeight + boxSize * 1.5f;

            for (int x = -1; x <= 1; x += 2)
            {
                for (int z = -1; z <= 1; z += 2)
                {
                    GameObject box = CreateDecorPrimitive(
                        string.Format("Cargo_Box_{0}{1}", x > 0 ? "R" : "L", z > 0 ? "B" : "F"),
                        PrimitiveType.Cube, parent, scene,
                        new Vector3(x * 0.28f, firstLayer, z * 0.26f), Quaternion.Euler(0f, x * z * 2.5f, 0f));
                    box.transform.localScale = new Vector3(boxSize, boxSize, boxSize * 0.92f);
                    ApplyMaterial(box, materials.Cardboard);
                }
            }

            for (int top = 0; top < 2; top++)
            {
                float offsetX = top == 0 ? -0.2f : 0.22f;
                float offsetZ = top == 0 ? -0.12f : 0.14f;
                Quaternion topRotation = Quaternion.Euler(0f, top == 0 ? 6f : -7f, 0f);

                GameObject box = CreateDecorPrimitive("Cargo_Box_Top_" + (top + 1), PrimitiveType.Cube, parent, scene,
                    new Vector3(offsetX, secondLayer, offsetZ), topRotation);
                box.transform.localScale = new Vector3(boxSize, boxSize, boxSize * 0.92f);
                ApplyMaterial(box, materials.Cardboard);

                GameObject tape = CreateDecorPrimitive("Cargo_Tape_" + (top + 1), PrimitiveType.Cube, parent, scene,
                    new Vector3(offsetX, secondLayer + boxSize * 0.5f + 0.014f, offsetZ), topRotation);
                tape.transform.localScale = new Vector3(boxSize * 0.28f, 0.028f, boxSize * 0.95f);
                ApplyMaterial(tape, materials.Tape);
            }
        }

        /// <summary>Бочки: четыре стальные бочки с обручами и крышками.</summary>
        private static void BuildBarrelsCargo(Transform parent, Scene scene, DemoMaterials materials)
        {
            const float barrelRadius = 0.27f;
            const float barrelHeight = 0.8f;
            float barrelCenterY = PalletDeckHeight + barrelHeight * 0.5f;

            int barrelIndex = 0;

            for (int x = -1; x <= 1; x += 2)
            {
                for (int z = -1; z <= 1; z += 2)
                {
                    barrelIndex++;
                    Vector3 center = new Vector3(x * 0.29f, barrelCenterY, z * 0.29f);

                    GameObject barrel = CreateDecorPrimitive("Cargo_Barrel_" + barrelIndex, PrimitiveType.Cylinder, parent, scene, center, Quaternion.identity);
                    barrel.transform.localScale = new Vector3(barrelRadius * 2f, barrelHeight * 0.5f, barrelRadius * 2f);
                    ApplyMaterial(barrel, materials.BarrelMetal);

                    for (int hoop = -1; hoop <= 1; hoop += 2)
                    {
                        GameObject ring = CreateDecorPrimitive("Cargo_BarrelHoop_" + barrelIndex + "_" + (hoop > 0 ? "Top" : "Bottom"),
                            PrimitiveType.Cylinder, parent, scene, center + new Vector3(0f, hoop * barrelHeight * 0.28f, 0f), Quaternion.identity);
                        ring.transform.localScale = new Vector3(barrelRadius * 2.12f, 0.03f, barrelRadius * 2.12f);
                        ApplyMaterial(ring, materials.BarrelHoop);
                    }

                    GameObject cap = CreateDecorPrimitive("Cargo_BarrelCap_" + barrelIndex, PrimitiveType.Cylinder, parent, scene,
                        center + new Vector3(0f, barrelHeight * 0.5f + 0.02f, 0f), Quaternion.identity);
                    cap.transform.localScale = new Vector3(barrelRadius * 1.8f, 0.02f, barrelRadius * 1.8f);
                    ApplyMaterial(cap, materials.BarrelHoop);
                }
            }
        }

        /// <summary>Стройматериалы: бетонные плиты стопкой и пара блоков поверх.</summary>
        private static void BuildConstructionCargo(Transform parent, Scene scene, DemoMaterials materials)
        {
            const float slabHeight = 0.14f;

            for (int slab = 0; slab < 3; slab++)
            {
                GameObject plate = CreateDecorPrimitive("Cargo_Slab_" + (slab + 1), PrimitiveType.Cube, parent, scene,
                    new Vector3(0.02f * (slab - 1), PalletDeckHeight + slabHeight * (slab + 0.5f), 0.02f * (slab - 1)),
                    Quaternion.Euler(0f, slab * 3f - 3f, 0f));
                plate.transform.localScale = new Vector3(1.02f, slabHeight, 0.74f);
                ApplyMaterial(plate, slab == 1 ? materials.ConcreteDark : materials.Concrete);
            }

            for (int block = 0; block < 2; block++)
            {
                float offsetX = block == 0 ? -0.24f : 0.26f;
                float offsetZ = block == 0 ? -0.16f : 0.18f;

                GameObject cinderBlock = CreateDecorPrimitive("Cargo_Block_" + (block + 1), PrimitiveType.Cube, parent, scene,
                    new Vector3(offsetX, PalletDeckHeight + slabHeight * 3f + 0.15f, offsetZ), Quaternion.Euler(0f, block * 8f, 0f));
                cinderBlock.transform.localScale = new Vector3(0.42f, 0.3f, 0.28f);
                ApplyMaterial(cinderBlock, materials.ConcreteDark);
            }
        }

        /// <summary>
        /// Позиции паллет: улица между домом и амбаром. Старт погрузчика — южнее,
        /// зоны сортировки — внутри амбара севернее, поэтому все паллеты лежат «по пути».
        /// </summary>
        private static List<Vector3> BuildPalletScatterPositions(int totalPallets)
        {
            const int columns = 3;
            const float columnSpacing = 3.8f;
            const float rowSpacing = 4.6f;
            const float streetStartZ = -9f;

            List<Vector3> positions = new List<Vector3>(totalPallets);
            System.Random random = new System.Random(1337);

            for (int index = 0; index < totalPallets; index++)
            {
                int column = index % columns;
                int row = index / columns;

                float x = (column - (columns - 1) * 0.5f) * columnSpacing + NextFloat(random, -0.5f, 0.5f);
                float z = streetStartZ + row * rowSpacing + NextFloat(random, -0.6f, 0.6f);

                positions.Add(new Vector3(x, 0.02f, z));
            }

            return positions;
        }

        private static float NextFloat(System.Random random, float min, float max)
        {
            return min + (float)random.NextDouble() * (max - min);
        }

        #endregion

        #region GameManager и HUD

        private static void BuildGameManager(Transform parent, Scene scene)
        {
            CreateGameObject("GameManager", parent, scene, Vector3.zero, Quaternion.identity, typeof(GameManager));
        }

        private static void BuildHud(Transform parent, Scene scene, GenerationOptions options, Font font)
        {
#if TMP_PRESENT
            bool useTextMeshPro = options.useTextMeshPro && TMP_Settings.defaultFontAsset != null;

            if (options.useTextMeshPro && TMP_Settings.defaultFontAsset == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] TextMeshPro установлен, но не импортированы TMP Essential Resources " +
                                 "(Window → TextMeshPro → Import TMP Essential Resources). HUD будет создан на стандартном UI Text.");
            }
#else
            const bool useTextMeshPro = false;
#endif

            GameObject canvasObject = CreateGameObject("GameCanvas", parent, scene, Vector3.zero, Quaternion.identity,
                typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster), typeof(GameUIController));

            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 0;

            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 0.5f;

            // Верхний левый угол: очки и статистика.
            HudLabel scoreLabel = CreateHudLabel("ScoreText", canvasObject.transform, scene, "Очки: 0",
                new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(24f, -20f), new Vector2(600f, 44f),
                34, TextAnchor.UpperLeft, Color.white, font, true, useTextMeshPro);

            HudLabel sortedLabel = CreateHudLabel("SortedText", canvasObject.transform, scene, "Отсортировано: 0 / 0",
                new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(24f, -70f), new Vector2(600f, 36f),
                26, TextAnchor.UpperLeft, new Color(0.9f, 0.92f, 0.95f), font, true, useTextMeshPro);

            HudLabel remainingLabel = CreateHudLabel("RemainingText", canvasObject.transform, scene, "Осталось кубиков: 0",
                new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(24f, -106f), new Vector2(600f, 36f),
                26, TextAnchor.UpperLeft, new Color(0.9f, 0.92f, 0.95f), font, true, useTextMeshPro);

            HudLabel mistakesLabel = CreateHudLabel("MistakesText", canvasObject.transform, scene, "Ошибки: 0",
                new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(24f, -142f), new Vector2(600f, 36f),
                26, TextAnchor.UpperLeft, new Color(1f, 0.78f, 0.4f), font, true, useTextMeshPro);

            // Правый верхний угол: таймер.
            HudLabel timerLabel = CreateHudLabel("TimerText", canvasObject.transform, scene, "Время: 00:00",
                new Vector2(1f, 1f), new Vector2(1f, 1f), new Vector2(1f, 1f), new Vector2(-24f, -20f), new Vector2(320f, 44f),
                34, TextAnchor.UpperRight, Color.white, font, true, useTextMeshPro);

            // Подсказка по управлению.
            CreateHudLabel("HintText", canvasObject.transform, scene,
                "W/S — газ, A/D — руль, Shift/Ctrl — вилы, Q/E — наклон мачты, Space — тормоз, R — сброс. Отвезите кубики в амбар!",
                new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(24f, 18f), new Vector2(1200f, 30f),
                22, TextAnchor.LowerLeft, new Color(0.85f, 0.88f, 0.92f), font, true, useTextMeshPro);

            // Панель «Уровень завершён» (скрыта до события OnLevelCompleted).
            GameObject panel = CreateUiObject("LevelCompletedPanel", canvasObject.transform, scene,
                new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(840f, 520f));

            Image panelImage = panel.AddComponent<Image>();
            panelImage.color = new Color(0.05f, 0.06f, 0.08f, 0.82f);
            panelImage.raycastTarget = true;

            CanvasGroup panelGroup = panel.AddComponent<CanvasGroup>();
            panelGroup.alpha = 0f;
            panelGroup.interactable = false;
            panelGroup.blocksRaycasts = false;

            CreateHudLabel("TitleText", panel.transform, scene, "УРОВЕНЬ ЗАВЕРШЁН!",
                new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0f, 170f), new Vector2(760f, 90f),
                54, TextAnchor.MiddleCenter, new Color(0.55f, 1f, 0.6f), font, true, useTextMeshPro);

            HudLabel summaryLabel = CreateHudLabel("SummaryText", panel.transform, scene, "Очки: 0",
                new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0f, 20f), new Vector2(760f, 220f),
                30, TextAnchor.MiddleCenter, Color.white, font, false, useTextMeshPro);

            CreateHudLabel("RestartHintText", panel.transform, scene, "Чтобы сыграть снова — перезапустите сцену.",
                new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0f, -180f), new Vector2(760f, 40f),
                24, TextAnchor.MiddleCenter, new Color(0.8f, 0.84f, 0.9f), font, false, useTextMeshPro);

            panel.SetActive(false);

            // Назначение ссылок контроллеру интерфейса.
            GameUIController uiController = canvasObject.GetComponent<GameUIController>();

            ApplySerializedChanges(uiController, serializedObject =>
            {
                AssignLabelBinding(serializedObject.FindProperty("scoreLabel"), scoreLabel);
                AssignLabelBinding(serializedObject.FindProperty("sortedLabel"), sortedLabel);
                AssignLabelBinding(serializedObject.FindProperty("remainingLabel"), remainingLabel);
                AssignLabelBinding(serializedObject.FindProperty("mistakesLabel"), mistakesLabel);
                AssignLabelBinding(serializedObject.FindProperty("timerLabel"), timerLabel);
                AssignLabelBinding(serializedObject.FindProperty("levelCompletedSummaryLabel"), summaryLabel);

                SetObjectReference(serializedObject, "levelCompletedPanel", panel);
                SetObjectReference(serializedObject, "levelCompletedCanvasGroup", panelGroup);
                SetFloat(serializedObject, "completedPanelFadeDuration", 0.4f);
                SetFloat(serializedObject, "completedPanelStartScale", 0.92f);
                SetBool(serializedObject, "hideCompletedPanelOnStart", true);
            });
        }

        /// <summary>Записать ссылки (Unity UI Text и/или TMP) в сериализованное поле-обёртку LabelBinding.</summary>
        private static void AssignLabelBinding(SerializedProperty bindingProperty, HudLabel label)
        {
            if (bindingProperty == null)
            {
                return;
            }

            SerializedProperty legacyText = bindingProperty.FindPropertyRelative("legacyText");
            if (legacyText != null)
            {
                legacyText.objectReferenceValue = label.Legacy;
            }

#if TMP_PRESENT
            SerializedProperty tmpText = bindingProperty.FindPropertyRelative("tmpText");
            if (tmpText != null)
            {
                tmpText.objectReferenceValue = label.Tmp;
            }
#endif
        }

        /// <summary>Данные созданной текстовой метки: стандартный UI Text и/или TextMeshPro.</summary>
        private struct HudLabel
        {
            public Text Legacy;
#if TMP_PRESENT
            public TMP_Text Tmp;
#endif
        }

        private static HudLabel CreateHudLabel(
            string objectName,
            Transform parent,
            Scene scene,
            string content,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Vector2 pivot,
            Vector2 anchoredPosition,
            Vector2 sizeDelta,
            int fontSize,
            TextAnchor alignment,
            Color color,
            Font font,
            bool addShadow,
            bool useTextMeshPro)
        {
            GameObject labelObject = CreateUiObject(objectName, parent, scene, anchorMin, anchorMax, pivot, anchoredPosition, sizeDelta);
            HudLabel label = new HudLabel();

#if TMP_PRESENT
            if (useTextMeshPro && TMP_Settings.defaultFontAsset != null)
            {
                TextMeshProUGUI tmp = labelObject.AddComponent<TextMeshProUGUI>();
                tmp.text = content;
                tmp.fontSize = fontSize;
                tmp.alignment = ConvertToTmpAlignment(alignment);
                tmp.color = color;
                tmp.raycastTarget = false;
                tmp.enableWordWrapping = false;
                tmp.overflowMode = TextOverflowModes.Overflow;
                label.Tmp = tmp;
                return label;
            }
#endif

            Text text = labelObject.AddComponent<Text>();
            text.font = font;
            text.text = content;
            text.fontSize = fontSize;
            text.alignment = alignment;
            text.color = color;
            text.raycastTarget = false;
            text.horizontalOverflow = HorizontalWrapMode.Overflow;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            text.supportRichText = true;
            label.Legacy = text;

            if (addShadow)
            {
                Shadow shadow = labelObject.AddComponent<Shadow>();
                shadow.effectColor = new Color(0f, 0f, 0f, 0.75f);
                shadow.effectDistance = new Vector2(1.5f, -1.5f);
            }

            return label;
        }

#if TMP_PRESENT
        private static TextAlignmentOptions ConvertToTmpAlignment(TextAnchor anchor)
        {
            switch (anchor)
            {
                case TextAnchor.UpperLeft: return TextAlignmentOptions.TopLeft;
                case TextAnchor.UpperCenter: return TextAlignmentOptions.Top;
                case TextAnchor.UpperRight: return TextAlignmentOptions.TopRight;
                case TextAnchor.MiddleLeft: return TextAlignmentOptions.Left;
                case TextAnchor.MiddleCenter: return TextAlignmentOptions.Center;
                case TextAnchor.MiddleRight: return TextAlignmentOptions.Right;
                case TextAnchor.LowerLeft: return TextAlignmentOptions.BottomLeft;
                case TextAnchor.LowerCenter: return TextAlignmentOptions.Bottom;
                case TextAnchor.LowerRight: return TextAlignmentOptions.BottomRight;
                default: return TextAlignmentOptions.Center;
            }
        }
#endif

        /// <summary>Шрифт для стандартного UI Text: LegacyRuntime.ttf (Arial.ttf в Unity 2022+ невалиден).</summary>
        private static Font GetFont()
        {
            try
            {
                Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                if (font != null)
                {
                    return font;
                }
            }
            catch (Exception)
            {
                // Встроенный шрифт может отсутствовать (например, в тестовом окружении) — уходим на системный.
            }

            try
            {
                string[] systemFonts = Font.GetOSInstalledFontNames();
                if (systemFonts != null && systemFonts.Length > 0)
                {
                    return Font.CreateDynamicFontFromOSFont(systemFonts[0], 16);
                }
            }
            catch (Exception)
            {
                // Игнорируем: останется шрифт по умолчанию (текст может быть не виден).
            }

            Debug.LogWarning("[DemoSceneGenerator] Не удалось получить шрифт для UI Text — назначьте шрифт вручную.");
            return null;
        }

        #endregion

        #region Хелперы создания объектов

        private static GameObject CreateGameObject(string objectName, Transform parent, Scene scene, Vector3 localPosition, Quaternion localRotation, params Type[] components)
        {
            GameObject created = (components != null && components.Length > 0)
                ? new GameObject(objectName, components)
                : new GameObject(objectName);

            if (parent != null)
            {
                created.transform.SetParent(parent, false);
            }

            created.transform.localPosition = localPosition;
            created.transform.localRotation = localRotation;

            Undo.RegisterCreatedObjectUndo(created, UndoGroupName);

            if (parent == null)
            {
                EditorSceneManager.MoveGameObjectToScene(created, scene);
            }

            return created;
        }

        /// <summary>
        /// Декоративный примитив: меш без коллайдера (корпус, мачта, вилы, таблички).
        /// Физику считают только коллайдер корпуса и коллайдеры каретки вил.
        /// </summary>
        private static GameObject CreateDecorPrimitive(string objectName, PrimitiveType primitiveType, Transform parent, Scene scene, Vector3 localPosition, Quaternion localRotation)
        {
            GameObject primitive = CreatePrimitive(objectName, primitiveType, parent, scene, localPosition, localRotation);
            RemoveComponentImmediate<Collider>(primitive);
            return primitive;
        }

        private static GameObject CreatePrimitive(string objectName, PrimitiveType primitiveType, Transform parent, Scene scene, Vector3 localPosition, Quaternion localRotation)
        {
            GameObject primitive = GameObject.CreatePrimitive(primitiveType);
            primitive.name = objectName;

            if (parent != null)
            {
                primitive.transform.SetParent(parent, false);
            }

            primitive.transform.localPosition = localPosition;
            primitive.transform.localRotation = localRotation;

            Undo.RegisterCreatedObjectUndo(primitive, UndoGroupName);

            if (parent == null)
            {
                EditorSceneManager.MoveGameObjectToScene(primitive, scene);
            }

            return primitive;
        }

        private static GameObject CreateUiObject(string objectName, Transform parent, Scene scene, Vector2 anchorMin, Vector2 anchorMax, Vector2 pivot, Vector2 anchoredPosition, Vector2 sizeDelta)
        {
            GameObject created = new GameObject(objectName, typeof(RectTransform));
            created.transform.SetParent(parent, false);

            RectTransform rectTransform = created.GetComponent<RectTransform>();
            rectTransform.anchorMin = anchorMin;
            rectTransform.anchorMax = anchorMax;
            rectTransform.pivot = pivot;
            rectTransform.anchoredPosition = anchoredPosition;
            rectTransform.sizeDelta = sizeDelta;
            rectTransform.localScale = Vector3.one;

            Undo.RegisterCreatedObjectUndo(created, UndoGroupName);

            return created;
        }

        private static void ApplyMaterial(GameObject target, Material material)
        {
            if (target == null || material == null)
            {
                return;
            }

            MeshRenderer renderer = target.GetComponent<MeshRenderer>();
            if (renderer != null)
            {
                renderer.sharedMaterial = material;
            }
        }

        private static void RemoveComponentImmediate<T>(GameObject target) where T : Component
        {
            if (target == null)
            {
                return;
            }

            T component = target.GetComponent<T>();
            if (component != null)
            {
                Undo.DestroyObjectImmediate(component);
            }
        }

        #endregion

        #region Назначение сериализованных полей

        private static void ApplySerializedChanges(UnityEngine.Object target, Action<SerializedObject> changes)
        {
            if (target == null || changes == null)
            {
                return;
            }

            SerializedObject serializedObject = new SerializedObject(target);
            Undo.RecordObject(target, UndoGroupName);
            changes(serializedObject);
            serializedObject.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(target);
        }

        private static void SetObjectReference(SerializedObject serializedObject, string propertyPath, UnityEngine.Object value)
        {
            SerializedProperty property = serializedObject.FindProperty(propertyPath);
            if (property == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найдено поле " + propertyPath + " у " + serializedObject.targetObject.GetType().Name);
                return;
            }

            property.objectReferenceValue = value;
        }

        private static void SetVector3(SerializedObject serializedObject, string propertyPath, Vector3 value)
        {
            SerializedProperty property = serializedObject.FindProperty(propertyPath);
            if (property == null || property.propertyType != SerializedPropertyType.Vector3)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найдено векторное поле " + propertyPath + " у " + serializedObject.targetObject.GetType().Name);
                return;
            }

            property.vector3Value = value;
        }

        private static void SetFloat(SerializedObject serializedObject, string propertyPath, float value)
        {
            SerializedProperty property = serializedObject.FindProperty(propertyPath);
            if (property == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найдено числовое поле " + propertyPath + " у " + serializedObject.targetObject.GetType().Name);
                return;
            }

            property.floatValue = value;
        }

        private static void SetInt(SerializedObject serializedObject, string propertyPath, int value)
        {
            SerializedProperty property = serializedObject.FindProperty(propertyPath);
            if (property == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найдено целочисленное поле " + propertyPath + " у " + serializedObject.targetObject.GetType().Name);
                return;
            }

            if (property.propertyType == SerializedPropertyType.Integer || property.propertyType == SerializedPropertyType.LayerMask)
            {
                property.intValue = value;
            }
        }

        private static void SetBool(SerializedObject serializedObject, string propertyPath, bool value)
        {
            SerializedProperty property = serializedObject.FindProperty(propertyPath);
            if (property == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найдено логическое поле " + propertyPath + " у " + serializedObject.targetObject.GetType().Name);
                return;
            }

            property.boolValue = value;
        }

        private static void SetEnum<TEnum>(SerializedObject serializedObject, string propertyPath, TEnum value) where TEnum : struct, IConvertible
        {
            SerializedProperty property = serializedObject.FindProperty(propertyPath);
            if (property == null)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не найдено enum-поле " + propertyPath + " у " + serializedObject.targetObject.GetType().Name);
                return;
            }

            if (property.propertyType != SerializedPropertyType.Enum && property.propertyType != SerializedPropertyType.Integer)
            {
                Debug.LogWarning("[DemoSceneGenerator] Поле " + propertyPath + " не является enum (" + property.propertyType + ").");
                return;
            }

            // Пишем целочисленное значение напрямую: enumValueIndex зависит от порядка имён
            // в списке, а intValue всегда равен значению enum (CargoType.None = 0 и далее).
            property.intValue = Convert.ToInt32(value);
        }

        #endregion

        #region Поддержка TextMeshPro

        /// <summary>
        /// Добавить директиву TMP_PRESENT в Scripting Define Symbols активной платформы,
        /// чтобы игра включила поддержку TextMeshPro (поля TMP в GameUIController и HUD).
        /// </summary>
        public static void EnableTextMeshProSupport()
        {
            bool packagePresent = Type.GetType("TMPro.TMP_Text, Unity.TextMeshPro") != null
                || Type.GetType("TMPro.TMP_Text, Unity.TextMeshPro.Editor") != null;

            if (!packagePresent)
            {
                EditorUtility.DisplayDialog(
                    "TextMeshPro не найден",
                    "В проекте нет пакета TextMeshPro.\n\nУстановите его: Window → Package Manager → Unity Registry → TextMeshPro → Install, " +
                    "после чего импортируйте TMP Essential Resources (Window → TextMeshPro → Import TMP Essential Resources).",
                    "Понятно");
                return;
            }

            try
            {
                NamedBuildTarget buildTarget = NamedBuildTarget.FromBuildTargetGroup(BuildPipeline.GetBuildTargetGroup(EditorUserBuildSettings.activeBuildTarget));
                string defines = PlayerSettings.GetScriptingDefineSymbols(buildTarget) ?? string.Empty;

                if (ContainsDefine(defines, "TMP_PRESENT"))
                {
                    EditorUtility.DisplayDialog(
                        "TextMeshPro уже включён",
                        "Директива TMP_PRESENT уже определена для активной платформы. HUD и GameUIController готовы работать с TextMeshPro.",
                        "Отлично");
                    return;
                }

                bool confirmed = EditorUtility.DisplayDialog(
                    "Включить поддержку TextMeshPro",
                    "Директива TMP_PRESENT будет добавлена в Scripting Define Symbols платформы «" + buildTarget + "».\n\n" +
                    "Unity перекомпилирует скрипты, после чего в GameUIController появятся поля TextMeshPro, " +
                    "а генератор сможет создавать HUD на TMP.",
                    "Добавить директиву",
                    "Отмена");

                if (!confirmed)
                {
                    return;
                }

                string newDefines = string.IsNullOrEmpty(defines) ? "TMP_PRESENT" : defines.TrimEnd(';') + ";TMP_PRESENT";
                PlayerSettings.SetScriptingDefineSymbols(buildTarget, newDefines);

                Debug.Log("[DemoSceneGenerator] Директива TMP_PRESENT добавлена в Scripting Define Symbols. Ожидайте перекомпиляцию скриптов.");
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[DemoSceneGenerator] Не удалось изменить Scripting Define Symbols автоматически (" + exception.Message + "). " +
                                 "Добавьте TMP_PRESENT вручную: Project Settings → Player → Other Settings → Scripting Define Symbols.");
            }
        }

        private static bool ContainsDefine(string defines, string define)
        {
            if (string.IsNullOrEmpty(defines))
            {
                return false;
            }

            string[] parts = defines.Split(';');
            for (int i = 0; i < parts.Length; i++)
            {
                if (string.Equals(parts[i].Trim(), define, StringComparison.Ordinal))
                {
                    return true;
                }
            }

            return false;
        }

        #endregion
    }

    /// <summary>
    /// Автозапуск генератора при открытии Unity.
    ///
    /// Срабатывает ровно один раз и только на «чистой» сцене, поэтому ничего не ломает:
    ///   * активная сцена не сохранена в файл (untitled) — открытые файлы сцен не трогаем;
    ///   * в ней нет пользовательских объектов (кроме стандартных камеры и света);
    ///   * автогенерация ещё ни разу не выполнялась (флаг в EditorPrefs);
    ///   * редактор не компилирует скрипты, не играет и не собирает билд.
    ///
    /// Отключается галочкой «Генерировать при первом запуске Unity» в окне генератора.
    /// Обычная генерация в один клик всегда доступна через Tools → Generate Forklift Demo Scene.
    /// </summary>
    [InitializeOnLoad]
    internal static class DemoSceneAutoBuilder
    {
        /// <summary>Автогенерация включена (EditorPrefs, по умолчанию включена).</summary>
        internal static bool IsAutoGenerateEnabled
        {
            get { return EditorPrefs.GetBool(DemoSceneGenerator.AutoGeneratePrefsKey, true); }
            set { EditorPrefs.SetBool(DemoSceneGenerator.AutoGeneratePrefsKey, value); }
        }

        /// <summary>Автогенерация уже выполнялась когда-либо.</summary>
        internal static bool WasAutoGenerationDone
        {
            get { return EditorPrefs.GetBool(DemoSceneGenerator.AutoGenerateDonePrefsKey, false); }
        }

        /// <summary>Разрешить автогенерацию заново (кнопка в окне генератора).</summary>
        internal static void ResetAutoGenerationFlag()
        {
            EditorPrefs.SetBool(DemoSceneGenerator.AutoGenerateDonePrefsKey, false);
            Debug.Log("[DemoSceneAutoBuilder] Флаг автогенерации сброшен: при следующем запуске Unity пустая сцена будет собрана заново.");
        }

        static DemoSceneAutoBuilder()
        {
            // delayCall: к этому моменту редактор уже загрузил сцену и готов работать с объектами.
            EditorApplication.delayCall += TryAutoGenerate;
        }

        private static void TryAutoGenerate()
        {
            if (!IsAutoGenerateEnabled || WasAutoGenerationDone)
            {
                return;
            }

            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling || EditorApplication.isUpdating)
            {
                return;
            }

            if (BuildPipeline.isBuildingPlayer)
            {
                return;
            }

            Scene activeScene = SceneManager.GetActiveScene();

            // Открыт реальный файл сцены — не трогаем его никогда.
            if (!string.IsNullOrEmpty(activeScene.path))
            {
                return;
            }

            if (HasUserContent(activeScene))
            {
                return;
            }

            // Флаг ставим до генерации: даже при ошибке сцену повторно не пересобираем.
            EditorPrefs.SetBool(DemoSceneGenerator.AutoGenerateDonePrefsKey, true);

            Debug.Log("[DemoSceneAutoBuilder] Обнаружена пустая сцена — собираю демо-сцену погрузчика. " +
                      "Отключается галочкой в окне Tools → Kakayato → Открыть окно генератора демо-сцены.");

            try
            {
                DemoSceneGenerator.GenerationOptions options = new DemoSceneGenerator.GenerationOptions();
                options.createNewScene = false;         // работаем с уже открытой пустой сценой
                options.keepCameraAndLight = true;
                options.clearExistingDemoObjects = false;
                options.saveSceneAsset = false;

                DemoSceneGenerator.Generate(options, false);
            }
            catch (Exception exception)
            {
                Debug.LogError("[DemoSceneAutoBuilder] Автогенерация не удалась — сцену можно собрать вручную " +
                               "через Tools → Generate Forklift Demo Scene. Ошибка: " + exception);
            }
        }

        /// <summary>Есть ли в сцене что-то, кроме камеры, света и демо-объектов.</summary>
        private static bool HasUserContent(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();

            for (int i = 0; i < roots.Length; i++)
            {
                GameObject root = roots[i];
                if (root == null)
                {
                    continue;
                }

                if (root.GetComponentInChildren<Camera>(true) != null)
                {
                    continue;
                }

                if (root.GetComponentInChildren<Light>(true) != null)
                {
                    continue;
                }

                // Демо-сцена уже собрана — ничего не делаем.
                if (root.GetComponentInChildren<ForkliftController>(true) != null)
                {
                    return false;
                }

                return true;
            }

            return false;
        }
    }
}
