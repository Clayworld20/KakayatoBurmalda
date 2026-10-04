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
    ///     ├── Ground                     — площадка (BoxCollider + материал)
    ///     ├── Forklift                   — корпус с Rigidbody, тег Forklift, скрипт ForkliftController
    ///     │     ├── Body/Cabin/OverheadGuard/Mast (меши без коллайдеров)
    ///     │     ├── MastTiltPivot → ForkCarriage (вилы: коллайдеры + меши)
    ///     │     ├── GroundCheck
    ///     │     └── Wheel_FL/FR/RL/RR → Tire (цилиндры)
    ///     ├── ForkliftResetPoint         — точка сброса погрузчика (клавиша R)
    ///     ├── SortingZone_Red/Green/Blue — триггерные зоны с материалами
    ///     ├── Cubes/…                    — 9 кубиков (по 3 цвета) с CubeProperty и Rigidbody
    ///     ├── GameManager                — менеджер игры
    ///     └── GameCanvas (опционально)   — HUD со скриптом GameUIController
    ///
    /// Все ссылки в инспекторах (каретка вил, визуальные колёса, маски слоёв, целевые типы зон,
    /// типы кубиков, ссылки HUD) назначаются кодом через SerializedObject, поэтому сцена
    /// собирается в один клик. Создаваемые объекты регистрируются в Undo.
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
        private const string DefaultScenePath = "Assets/Scenes/ForkliftDemo.unity";

        private const float GroundSize = 60f;
        private const float CubeSize = 0.8f;
        private const float ForkliftStartZ = -14f;
        private const int DefaultCubesPerColor = 3;

        private const float WheelRadius = 0.3f;

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

            [Tooltip("Прикрепить камеру к погрузчику сзади (вид от третьего лица).")]
            public bool attachCameraToForklift = true;

            [Slider(-180f, 180f), Tooltip("Начальный поворот погрузчика по оси Y, градусы. 0 — вилы смотрят на кубики и зоны (+Z).")]
            public float forkliftStartYaw = 0f;

            [IntSlider(1, 6), Tooltip("Сколько кубиков каждого цвета создать.")]
            public int cubesPerColor = DefaultCubesPerColor;

            [Tooltip("Создать теги Forklift / Cube / SortingZone / Ground.")]
            public bool createTags = true;

            [Tooltip("Создать слои Ground и Cube (для корректных масок в контроллере).")]
            public bool createLayers = true;

            [Tooltip("Создать и назначить материалы (стандартный или URP-шейдер).")]
            public bool createMaterials = true;

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
                "Соберёт площадку, погрузчик с вилами, три зоны сортировки, кубики, GameManager и (опционально) HUD. " +
                "Все ссылки в инспекторах назначаются кодом, действия можно отменить (Ctrl+Z).",
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
            options.cubesPerColor = EditorGUILayout.IntSlider("Кубиков каждого цвета", options.cubesPerColor, 1, 6);

            showAdvanced = EditorGUILayout.Foldout(showAdvanced, "Дополнительно", true);
            if (showAdvanced)
            {
                EditorGUI.indentLevel++;
                options.createTags = EditorGUILayout.Toggle("Создать теги", options.createTags);
                options.createLayers = EditorGUILayout.Toggle("Создать слои Ground/Cube", options.createLayers);
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
            EditorGUILayout.LabelField(string.Format("Версия компонентов: {0} кубиков, {1} зоны (красная, зелёная, синяя).",
                options.cubesPerColor * 3,
                3),
                EditorStyles.miniLabel);

            EditorGUILayout.EndScrollView();
        }

        #endregion

        #region Пайплайн генерации

        /// <summary>Сгенерировать демо-сцену с указанными настройками.</summary>
        public static void Generate(GenerationOptions options)
        {
            if (options == null)
            {
                options = new GenerationOptions();
            }

            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
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

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Теги и слои...", 0.15f);
                PrepareTagsAndLayers(options, out string forkliftTag, out string cubeTag, out string zoneTag, out string groundTag,
                    out int groundLayer, out int cubeLayer);

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Материалы...", 0.3f);
                DemoMaterials materials = options.createMaterials ? CreateMaterials() : DemoMaterials.Empty;

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Площадка...", 0.4f);
                GameObject demoRoot = CreateGameObject(DemoRootName, null, scene, Vector3.zero, Quaternion.identity);
                GameObject ground = BuildGround(demoRoot.transform, scene, materials, groundLayer, groundTag);

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Погрузчик...", 0.55f);
                ForkliftController forkliftController;
                Transform resetPoint;
                GameObject forklift = BuildForklift(demoRoot.transform, scene, options, materials, groundLayer, cubeLayer,
                    out forkliftController, out resetPoint);

                if (!string.IsNullOrEmpty(forkliftTag))
                {
                    forklift.tag = forkliftTag;
                }

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Зоны сортировки...", 0.7f);
                BuildSortingZones(demoRoot.transform, scene, materials, zoneTag);

                EditorUtility.DisplayProgressBar("Генерация демо-сцены", "Кубики...", 0.8f);
                BuildCubes(demoRoot.transform, scene, options, materials, cubeLayer, cubeTag);

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
                    "[DemoSceneGenerator] Демо-сцена готова: площадка, погрузчик, 3 зоны сортировки, {0} кубиков{1}. " +
                    "Управление: W/S — газ, A/D — руль, Shift/Ctrl — вилы, Q/E — наклон мачты, Space — тормоз, R — сброс.",
                    options.cubesPerColor * 3,
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
            out string cubeTag,
            out string zoneTag,
            out string groundTag,
            out int groundLayer,
            out int cubeLayer)
        {
            forkliftTag = null;
            cubeTag = null;
            zoneTag = null;
            groundTag = null;
            groundLayer = 0;
            cubeLayer = 0;

            if (options.createTags)
            {
                forkliftTag = EnsureTag("Forklift");
                cubeTag = EnsureTag("Cube");
                zoneTag = EnsureTag("SortingZone");
                groundTag = EnsureTag("Ground");
            }

            if (options.createLayers)
            {
                groundLayer = EnsureLayer("Ground");
                cubeLayer = EnsureLayer("Cube");
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

        private static void AttachCameraToForklift(Scene scene, Transform forklift)
        {
            Camera camera = FindActiveComponentInScene<Camera>(scene);
            if (camera == null)
            {
                return;
            }

            Transform cameraTransform = camera.transform;

            Undo.SetTransformParent(cameraTransform, forklift, "Attach camera to forklift");
            Undo.RecordObject(cameraTransform, "Attach camera to forklift");

            cameraTransform.localPosition = new Vector3(0f, 4.2f, -7.5f);
            cameraTransform.localRotation = Quaternion.Euler(16f, 0f, 0f);
            cameraTransform.localScale = Vector3.one;

            camera.fieldOfView = 60f;
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 500f;
        }

        #endregion

        #region Материалы

        /// <summary>Набор материалов демо-сцены (может быть пустым, если материалы отключены).</summary>
        private class DemoMaterials
        {
            public static readonly DemoMaterials Empty = new DemoMaterials();

            public Material Ground;
            public Material ForkliftBody;
            public Material ForkliftAccent;
            public Material Wheel;
            public Material ZoneRed;
            public Material ZoneGreen;
            public Material ZoneBlue;
            public Material CubeRed;
            public Material CubeGreen;
            public Material CubeBlue;
            public Material CubeYellow;

            /// <summary>Материал зоны по цвету кубика.</summary>
            public Material GetZoneMaterial(CubeColor color)
            {
                switch (color)
                {
                    case CubeColor.Red: return ZoneRed;
                    case CubeColor.Green: return ZoneGreen;
                    case CubeColor.Blue: return ZoneBlue;
                    default: return null;
                }
            }

            /// <summary>Материал кубика по его цвету.</summary>
            public Material GetCubeMaterial(CubeColor color)
            {
                switch (color)
                {
                    case CubeColor.Red: return CubeRed;
                    case CubeColor.Green: return CubeGreen;
                    case CubeColor.Blue: return CubeBlue;
                    case CubeColor.Yellow: return CubeYellow;
                    default: return null;
                }
            }
        }

        private static DemoMaterials CreateMaterials()
        {
            EnsureFolder(MaterialsFolder);

            DemoMaterials materials = new DemoMaterials
            {
                Ground = FindOrCreateMaterial("Demo_Ground", new Color(0.18f, 0.19f, 0.17f), 0.1f, 0f, false),
                ForkliftBody = FindOrCreateMaterial("Demo_Forklift_Body", new Color(0.95f, 0.55f, 0.08f), 0.45f, 0.2f, false),
                ForkliftAccent = FindOrCreateMaterial("Demo_Forklift_Accent", new Color(0.16f, 0.16f, 0.17f), 0.5f, 0.6f, false),
                Wheel = FindOrCreateMaterial("Demo_Wheel", new Color(0.06f, 0.06f, 0.07f), 0.25f, 0f, false),
                ZoneRed = FindOrCreateMaterial("Demo_Zone_Red", new Color(0.85f, 0.18f, 0.16f, 0.55f), 0.2f, 0f, true),
                ZoneGreen = FindOrCreateMaterial("Demo_Zone_Green", new Color(0.20f, 0.72f, 0.24f, 0.55f), 0.2f, 0f, true),
                ZoneBlue = FindOrCreateMaterial("Demo_Zone_Blue", new Color(0.16f, 0.42f, 0.85f, 0.55f), 0.2f, 0f, true),
                CubeRed = FindOrCreateMaterial("Demo_Cube_Red", new Color(0.85f, 0.18f, 0.16f), 0.35f, 0f, false),
                CubeGreen = FindOrCreateMaterial("Demo_Cube_Green", new Color(0.20f, 0.72f, 0.24f), 0.35f, 0f, false),
                CubeBlue = FindOrCreateMaterial("Demo_Cube_Blue", new Color(0.16f, 0.42f, 0.85f), 0.35f, 0f, false),
                CubeYellow = FindOrCreateMaterial("Demo_Cube_Yellow", new Color(0.95f, 0.80f, 0.15f), 0.35f, 0f, false)
            };

            AssetDatabase.SaveAssets();
            return materials;
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

            return ground;
        }

        #endregion

        #region Погрузчик

        private static GameObject BuildForklift(
            Transform parent,
            Scene scene,
            GenerationOptions options,
            DemoMaterials materials,
            int groundLayer,
            int cubeLayer,
            out ForkliftController forkliftController,
            out Transform resetPoint)
        {
            Vector3 forkliftPosition = new Vector3(0f, 0f, ForkliftStartZ);
            Quaternion forkliftRotation = Quaternion.Euler(0f, options.forkliftStartYaw, 0f);

            GameObject forklift = CreateGameObject("Forklift", parent, scene, forkliftPosition, forkliftRotation,
                typeof(Rigidbody), typeof(BoxCollider), typeof(ForkliftController));

            forkliftController = forklift.GetComponent<ForkliftController>();

            // Корпус: коллайдер и меш совпадают, низ корпуса приподнят на высоту колёс.
            BoxCollider bodyCollider = forklift.GetComponent<BoxCollider>();
            bodyCollider.center = new Vector3(0f, 1.05f, 0.15f);
            bodyCollider.size = new Vector3(1.5f, 1.4f, 2.3f);

            Rigidbody body = forklift.GetComponent<Rigidbody>();
            body.mass = 900f;
            body.drag = 0.05f;
            body.angularDrag = 4f;
            body.interpolation = RigidbodyInterpolation.Interpolate;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;

            GameObject bodyMesh = CreateDecorPrimitive("Body", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 1.05f, 0.15f), Quaternion.identity);
            bodyMesh.transform.localScale = new Vector3(1.5f, 1.4f, 2.3f);
            ApplyMaterial(bodyMesh, materials.ForkliftBody);

            GameObject cabin = CreateDecorPrimitive("Cabin", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 2.05f, -0.55f), Quaternion.identity);
            cabin.transform.localScale = new Vector3(1.25f, 0.6f, 1.1f);
            ApplyMaterial(cabin, materials.ForkliftBody);

            GameObject guard = CreateDecorPrimitive("OverheadGuard", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 2.42f, -0.55f), Quaternion.identity);
            guard.transform.localScale = new Vector3(1.4f, 0.1f, 1.25f);
            ApplyMaterial(guard, materials.ForkliftAccent);

            GameObject mast = CreateDecorPrimitive("Mast", PrimitiveType.Cube, forklift.transform, scene, new Vector3(0f, 1.5f, 1.2f), Quaternion.identity);
            mast.transform.localScale = new Vector3(0.14f, 2.6f, 0.45f);
            ApplyMaterial(mast, materials.ForkliftAccent);

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
            int cubeMask = 1 << cubeLayer;

            ApplySerializedChanges(forkliftController, serializedObject =>
            {
                SetObjectReference(serializedObject, "forkCarriage", carriageTransform);
                SetObjectReference(serializedObject, "groundCheck", groundCheckTransform);
                SetObjectReference(serializedObject, "mastTiltPivot", mastPivotTransform);
                SetObjectReference(serializedObject, "resetPoint", resetTransform);
                SetInt(serializedObject, "groundLayers", groundMask);
                SetInt(serializedObject, "cubeLayers", cubeMask);
                SetVector3(serializedObject, "carryVolumeCenter", new Vector3(0f, 0.35f, 0.45f));
                SetVector3(serializedObject, "carryVolumeSize", new Vector3(1.6f, 1.0f, 1.3f));
                SetFloat(serializedObject, "groundCheckDistance", 0.6f);

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

            return wheelRoot.transform;
        }

        #endregion

        #region Зоны сортировки

        private static void BuildSortingZones(Transform parent, Scene scene, DemoMaterials materials, string zoneTag)
        {
            CubeColor[] colors = { CubeColor.Red, CubeColor.Green, CubeColor.Blue };
            float[] xPositions = { -7f, 0f, 7f };

            for (int i = 0; i < colors.Length; i++)
            {
                CubeColor color = colors[i];
                string zoneName = "SortingZone_" + color;
                Vector3 position = new Vector3(xPositions[i], 0f, 9f);

                GameObject zone = CreateGameObject(zoneName, parent, scene, position, Quaternion.identity, typeof(BoxCollider), typeof(SortingZone));

                if (!string.IsNullOrEmpty(zoneTag))
                {
                    zone.tag = zoneTag;
                }

                BoxCollider trigger = zone.GetComponent<BoxCollider>();
                trigger.isTrigger = true;
                trigger.center = new Vector3(0f, 0.8f, 0f);
                trigger.size = new Vector3(5f, 1.6f, 5f);

                // Площадка зоны: плоский декор без коллайдера, чтобы физика зоны шла только через триггер.
                GameObject pad = CreateDecorPrimitive("Pad", PrimitiveType.Cube, zone.transform, scene, new Vector3(0f, 0.01f, 0f), Quaternion.identity);
                pad.transform.localScale = new Vector3(5f, 0.02f, 5f);
                ApplyMaterial(pad, SafeMaterial(materials, color));

                // Табличка цвета зоны.
                GameObject sign = CreateDecorPrimitive("Sign", PrimitiveType.Cube, zone.transform, scene, new Vector3(0f, 2.4f, -2.4f), Quaternion.identity);
                sign.transform.localScale = new Vector3(2.6f, 0.5f, 0.1f);
                ApplyMaterial(sign, SafeMaterial(materials, color));

                SortingZone sortingZone = zone.GetComponent<SortingZone>();

                ApplySerializedChanges(sortingZone, serializedObject =>
                {
                    SetEnum<CubeColor>(serializedObject, "targetType", color);
                });
            }
        }

        private static Material SafeMaterial(DemoMaterials materials, CubeColor color)
        {
            Material zoneMaterial = materials.GetZoneMaterial(color);
            return zoneMaterial != null ? zoneMaterial : materials.GetCubeMaterial(color);
        }

        #endregion

        #region Кубики

        private static void BuildCubes(Transform parent, Scene scene, GenerationOptions options, DemoMaterials materials, int cubeLayer, string cubeTag)
        {
            CubeColor[] colors = { CubeColor.Red, CubeColor.Green, CubeColor.Blue };
            int cubesPerColor = Mathf.Clamp(options.cubesPerColor, 1, 6);
            int totalCubes = colors.Length * cubesPerColor;

            GameObject cubesRoot = CreateGameObject("Cubes", parent, scene, Vector3.zero, Quaternion.identity);
            List<Vector3> positions = BuildCubeScatterPositions(totalCubes);

            int cubeIndex = 0;
            System.Random random = new System.Random(20240607);

            for (int colorIndex = 0; colorIndex < colors.Length; colorIndex++)
            {
                CubeColor color = colors[colorIndex];

                for (int i = 0; i < cubesPerColor; i++)
                {
                    Vector3 position = positions[cubeIndex];
                    Quaternion rotation = Quaternion.Euler(0f, NextFloat(random, 0f, 360f), 0f);
                    string cubeName = string.Format("Cube_{0}_{1:00}", color, i + 1);

                    GameObject cube = CreatePrimitive(cubeName, PrimitiveType.Cube, cubesRoot.transform, scene, position, rotation);
                    cube.transform.localScale = Vector3.one * CubeSize;
                    ApplyMaterial(cube, materials.GetCubeMaterial(color));

                    if (cubeLayer > 0)
                    {
                        cube.layer = cubeLayer;
                    }

                    if (!string.IsNullOrEmpty(cubeTag))
                    {
                        cube.tag = cubeTag;
                    }

                    Rigidbody cubeBody = cube.AddComponent<Rigidbody>();
                    cubeBody.mass = 2f;
                    cubeBody.drag = 0.05f;
                    cubeBody.angularDrag = 0.6f;
                    cubeBody.interpolation = RigidbodyInterpolation.Interpolate;
                    cubeBody.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;

                    CubeProperty cubeProperty = cube.AddComponent<CubeProperty>();

                    ApplySerializedChanges(cubeProperty, serializedObject =>
                    {
                        SetEnum<CubeColor>(serializedObject, "cubeType", color);
                        SetInt(serializedObject, "scoreValue", 10);
                        SetFloat(serializedObject, "mass", 2f);
                    });

                    cubeIndex++;
                }
            }
        }

        /// <summary>Позиции кубиков: сетка перед погрузчиком со случайным смещением (без пересечений).</summary>
        private static List<Vector3> BuildCubeScatterPositions(int totalCubes)
        {
            List<Vector3> positions = new List<Vector3>(totalCubes);

            int columns = Mathf.Max(1, Mathf.CeilToInt(Mathf.Sqrt(totalCubes)));
            int rows = Mathf.CeilToInt((float)totalCubes / columns);
            float columnSpacing = 2.2f;
            float rowSpacing = 2.4f;
            float startZ = 0.5f;

            System.Random random = new System.Random(1337);
            int index = 0;

            for (int row = 0; row < rows && index < totalCubes; row++)
            {
                for (int column = 0; column < columns && index < totalCubes; column++)
                {
                    float x = (column - (columns - 1) * 0.5f) * columnSpacing + NextFloat(random, -0.35f, 0.35f);
                    float z = startZ + row * rowSpacing + NextFloat(random, -0.35f, 0.35f);

                    positions.Add(new Vector3(x, CubeSize * 0.5f + 0.05f, z));
                    index++;
                }
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
                "W/S — газ, A/D — руль, Shift/Ctrl — вилы, Q/E — наклон мачты, Space — тормоз, R — сброс",
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

            // Пишем целочисленное значение напрямую: у CubeColor есть None = -1, поэтому индекс
            // в enumNames не совпадает со значением и enumValueIndex использовать нельзя.
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
}
