# -*- coding: utf-8 -*-
"""Статическая проверка Unity-проекта «KakayatoBurmalda» без компилятора.

Запуск:
    python3 Tools/validate_project.py              # проверить проект (папку Assets)
    python3 Tools/validate_project.py --selftest   # проверить сам валидатор (внедряет баги)
                                                                  # и убедиться, что он их ловит

Подход: комментарии и строковые литералы заменяются пробелами (маска той же длины),
поэтому позиции/номера строк совпадают с исходником, а структура и вызовы анализируются
без ложных срабатываний на текст внутри строк и комментариев. Имя сериализованного поля
читается из СЫРОГО текста внутри спанов, найденных по маске.

Проверки:
    1. Структура файлов: скобки, BOM, namespace, #region/#if, имя класса = имя файла.
    2. Имена сериализованных полей, которые генератор назначает через SerializedObject.
    3. Существование членов у типов проекта (X.Member), с учётом локальных переменных.
    4. Согласованность string.Format (число {N} и аргументов).
    5. Запрещённые атрибуты [Slider]/[IntSlider] — их нет в Unity API (Safe Mode).
    6. Undo.AddComponent<T>() принимает GameObject, а не Transform.
    7. Число и типы аргументов вызовов методов проекта + сигнатуры редакторного Unity API.
"""
import glob
import io
import contextlib
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT = os.path.join(PROJECT_ROOT, 'Assets')
GENERATOR = 'Editor/DemoSceneGenerator.cs'
TARGET_METHODS = {
    # метод генератора -> класс, чьи сериализованные поля он назначает
    'BuildForklift': 'ForkliftController',
    'BuildSortingZones': 'SortingZone',
    'BuildPallet': 'CargoPallet',
    'BuildHud': 'GameUIController',
    'AttachCameraToForklift': 'CameraFollow',
    'EnsureCameraSettingsMenu': 'CameraSettingsMenu',
}
TYPE_TAIL = r'[\w<>\[\],\.\?\s]+?'

UNITY_MEMBER_SOURCES = {
    'WheelVisual': ('ForkliftController', 'WheelVisual'),
    'LabelBinding': ('GameUIController', 'LabelBinding'),
}

# ---------------------------------------------------------------- лексическая маска

def mask_code(src):
    """Маска той же длины: комментарии и литералы (включая кавычки) заменены пробелами, переводы строк сохранены."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = ' '
            i = j
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if src[k] != '\n':
                    out[k] = ' '
            i = j
            continue
        if c == '@' and i + 1 < n and src[i + 1] == '"':
            i += 1
            out[i] = ' '
            i += 1
            while i < n:
                if src[i] == '"':
                    if i + 1 < n and src[i + 1] == '"':
                        i += 2
                        continue
                    out[i] = ' '
                    i += 1
                    break
                if src[i] != '\n':
                    out[i] = ' '
                i += 1
            continue
        if c == '"':
            out[i] = ' '
            i += 1
            while i < n:
                if src[i] == '\\':
                    out[i] = ' '
                    if i + 1 < n:
                        out[i + 1] = ' '
                    i += 2
                    continue
                if src[i] == '"':
                    out[i] = ' '
                    i += 1
                    break
                if src[i] != '\n':
                    out[i] = ' '
                i += 1
            continue
        if c == "'":
            out[i] = ' '
            i += 1
            while i < n:
                if src[i] == '\\':
                    out[i] = ' '
                    if i + 1 < n:
                        out[i + 1] = ' '
                    i += 2
                    continue
                out[i] = ' '
                if src[i] == "'":
                    i += 1
                    break
                i += 1
            continue
        i += 1
    return ''.join(out)


def line_of(code, pos):
    return code.count('\n', 0, pos) + 1


# ---------------------------------------------------------------- утилиты разбора

def split_top(s):
    if not s.strip():
        return []
    parts, depth, cur = [], 0, ''
    for ch in s:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def close_of(code, open_idx):
    depth, i = 0, open_idx
    while i < len(code):
        if code[i] in '([{':
            depth += 1
        elif code[i] in ')]}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def class_body(mask, class_name):
    match = re.search(r'\bclass\s+' + class_name + r'\b[^{]*\{', mask)
    if not match:
        match = re.search(r'\benum\s+' + class_name + r'\b[^{]*\{', mask)
    if not match:
        return ''
    start = match.end() - 1
    end = close_of(mask, start)
    return mask[start + 1:end] if end > start else ''


def method_span(mask, method_name):
    match = re.search(r'\b' + method_name + r'\s*\([^)]*\)\s*\{', mask)
    if not match:
        return None
    start = match.end() - 1
    end = close_of(mask, start)
    return (start, end) if end > start else None


def serialized_fields(raw_body, mask_body):
    """Имена serialized-полей: [SerializeField,] private T name; и public T name; (свойства и методы не считаются)."""
    names = set()
    for m in re.finditer(r'\[SerializeField\b[^\]]*\]\s*(?:\[[^\]]*\]\s*)*'
                         r'(?:public|private|protected|internal)\s+'
                         r'(?:(?:static|readonly|const)\s+)*'
                         r'([\w<>\[\],\.\?\s]*?)\s+(\w+)\s*(?:=|;)',
                         mask_body, re.S):
        names.add(m.group(2))
    for m in re.finditer(r'^\s*(?:\[[^\]]*\]\s*)*public\s+'
                         r'(?!static|const|event|class|enum|struct|interface|delegate|override|virtual|abstract|sealed|void|partial)'
                         r'([\w<>\[\],\.\?\s]*?)\s+(\w+)\s*(?:=|;)',
                         mask_body, re.M):
        names.add(m.group(2))
    for m in re.finditer(r'\b(?:struct|class)\s+(\w+)', mask_body):
        names.add(m.group(1))
    return names


# ---------------------------------------------------------------- типы проекта

PROJECT_TYPES = {}


def collect_project_types(files):
    main_files = {}
    for path in files:
        mask = mask_code(open(path, encoding='utf-8-sig').read())
        main_files[path] = mask
        for m in re.finditer(r'\bclass\s+(\w+)|\benum\s+(\w+)', mask):
            name = m.group(1) or m.group(2)
            body = class_body(mask, name)
            members = set()
            for mm in re.finditer(r'\b(?:public|private|protected|internal)\s+'
                                  r'(?:static\s+|readonly\s+|const\s+|virtual\s+|override\s+|sealed\s+|'
                                  r'new\s+|abstract\s+|partial\s+|event\s+)*'
                                  r'([\w<>\[\],\.\?\s]*?)\s+(\w+)\s*(?:\(|\{|=>|=|;)',
                                  body):
                members.add(mm.group(2))
            for mm in re.finditer(r'\b(?:struct|class|enum)\s+(\w+)', body):
                members.add(mm.group(1))
            if m.group(2) is not None:
                # значения перечисления: Name = 1, / Name,
                for mm in re.finditer(r'^\s*(\w+)\s*(?:=\s*[^,\n]+)?,?\s*$', body, re.M):
                    members.add(mm.group(1))
            members.add(name)
            base = None
            if m.group(2) is None:
                bm = re.search(r'\bclass\s+' + name + r'\s*:\s*([\w\.<>]+)', mask)
                if bm:
                    base = bm.group(1).split('.')[-1]
            PROJECT_TYPES[name] = {'members': members, 'file': path, 'base': base,
                                   'is_enum': m.group(2) is not None}
    return main_files


# ---------------------------------------------------------------- страж ложных типов

UNITY_TYPES = {
    'Object', 'GameObject', 'Component', 'Behaviour', 'MonoBehaviour', 'ScriptableObject',
    'Transform', 'RectTransform', 'Rigidbody', 'Rigidbody2D', 'Collider', 'BoxCollider',
    'SphereCollider', 'CapsuleCollider', 'MeshCollider', 'CharacterController', 'Joint',
    'FixedJoint', 'HingeJoint', 'PhysicMaterial', 'PhysicsMaterial', 'Material', 'Shader',
    'Renderer', 'MeshRenderer', 'MeshFilter', 'SkinnedMeshRenderer', 'Camera', 'Light',
    'AudioSource', 'Canvas', 'CanvasGroup', 'CanvasScaler', 'GraphicRaycaster', 'Image',
    'Text', 'Shadow', 'Outline', 'Button', 'Slider', 'Toggle', 'Dropdown', 'ScrollRect',
    'TextMeshProUGUI', 'TMP_Text', 'TextMesh', 'EventSystem', 'StandaloneInputModule',
    'Font', 'Texture', 'Texture2D', 'Sprite', 'Vector2', 'Vector3', 'Vector4', 'Quaternion',
    'Color', 'Color32', 'Rect', 'Ray', 'RaycastHit', 'RaycastHit2D', 'LayerMask', 'Scene',
    'KeyCode', 'Mathf', 'Physics', 'Time', 'Debug', 'Screen', 'Cursor', 'CursorLockMode',
    'Application', 'Input', 'Random', 'PlayerPrefs', 'Resources', 'SceneManager',
    'EditorSceneManager', 'Undo', 'EditorPrefs', 'SerializedObject', 'SerializedProperty',
    'EditorWindow', 'EditorUtility', 'EditorGUIUtility', 'EditorGUI', 'EditorGUILayout',
    'EditorStyles', 'Selection', 'SceneView', 'AssetDatabase', 'TagManager',
    'QueryTriggerInteraction', 'CollisionDetectionMode', 'RigidbodyInterpolation', 'ForceMode',
    'PrimitiveType', 'GUI', 'GUILayout', 'GUIStyle', 'GUISkin', 'GUIContent', 'GUIStyleState',
    'GUILayoutOption', 'FontStyle', 'TextAnchor', 'Event', 'Space', 'MonoScript', 'SystemInfo',
    'CultureInfo', 'NumberStyles', 'Exception', 'System', 'String', 'StringComparison',
    'Convert', 'Type', 'Activator', 'Enum', 'IEnumerator', 'List', 'Dictionary', 'HashSet',
    'Array', 'Tuple', 'StringBuilder', 'UnityEngine', 'SceneManagement', 'SerializableAttribute',
    'Color32', 'IList', 'IDictionary', 'Math', 'Regex', 'GUIUtility', 'GUIEventType',
}
UNITY_BASE_MEMBERS = {
    'transform', 'gameObject', 'name', 'enabled', 'isActiveAndEnabled', 'tag', 'hideFlags',
    'GetComponent', 'GetComponentInChildren', 'GetComponentInParent', 'GetComponents',
    'GetComponentsInChildren', 'GetComponentsInParent', 'TryGetComponent', 'CompareTag',
    'StartCoroutine', 'StopCoroutine', 'StopAllCoroutines', 'Invoke', 'InvokeRepeating',
    'CancelInvoke', 'SendMessage', 'SendMessageUpwards', 'BroadcastMessage', 'Equals',
    'GetHashCode', 'GetType', 'ToString', 'isActive', 'AddComponent', 'GetInstanceID',
    'SetActive', 'root', 'parent', 'position', 'rotation', 'localPosition', 'localRotation',
    'localScale', 'lossyScale', 'up', 'right', 'forward', 'childCount', 'Find', 'GetChild',
    'localEulerAngles', 'eulerAngles', 'SetParent', 'DetachChildren', 'SetAsLastSibling',
    'SetSiblingIndex', 'GetSiblingIndex', 'DontDestroyOnLoad', 'ScheduleUpdate',
    'Awake', 'Start', 'Update', 'LateUpdate', 'FixedUpdate', 'OnEnable', 'OnDisable',
    'OnDestroy', 'OnValidate', 'OnGUI', 'OnDrawGizmos', 'OnCollisionEnter', 'OnTriggerEnter',
    'OnTriggerExit', 'OnTriggerStay', 'OnCollisionStay', 'OnCollisionExit', 'OnMouseDown',
}
UNITY_BASE_API = {
    'EditorWindow': {
        'minSize', 'maxSize', 'Show', 'ShowUtility', 'ShowModalUtility', 'ShowAsDropDown',
        'ShowPopup', 'Close', 'Repaint', 'Focus', 'position', 'titleContent', 'hasFocus',
        'wantsMouseMove', 'wantsMouseEnterLeaveWindow', 'autoRepaintOnSceneChange',
        'GetWindow', 'SendEvent', 'rootVisualElement', 'OnSelectionChange',
    },
    'ScriptableObject': {
        'CreateInstance', 'hideFlags', 'name',
    },
}


def allowed_members(type_name):
    info = PROJECT_TYPES[type_name]
    allowed = set(info['members']) | UNITY_BASE_MEMBERS
    base = info.get('base')
    if base:
        allowed |= UNITY_BASE_API.get(base, set())
    return allowed


# ---------------------------------------------------------------- 1. структура

def check_structure(files):
    problems = []
    print('--- 1. Структура файлов ---')
    for path, mask in files.items():
        raw = open(path, encoding='utf-8-sig').read()
        has_bom = open(path, 'rb').read().startswith(b'\xef\xbb\xbf')
        braces = mask.count('{') - mask.count('}')
        parens = mask.count('(') - mask.count(')')
        brackets = mask.count('[') - mask.count(']')
        regions = len(re.findall(r'#region\b', mask))
        end_regions = len(re.findall(r'#endregion\b', mask))
        ifs = len(re.findall(r'^\s*#if\b', mask, re.M))
        endifs = len(re.findall(r'^\s*#endif\b', mask, re.M))
        namespace = re.search(r'namespace\s+(KakayatoBurmalda[\w\.]*)', mask)
        file_name = os.path.splitext(os.path.basename(path))[0]
        classes = re.findall(r'\bclass\s+(\w+)', mask)
        name_ok = (file_name in classes) or not classes
        ok = (braces == 0 and parens == 0 and brackets == 0 and has_bom and
              regions == end_regions and ifs == endifs and namespace is not None and name_ok)
        print('%-4s %-50s строк=%4d скобки=%+d/%+d/%+d BOM=%-3s ns=%-3s R=%d/%d I=%d/%d' % (
            'OK' if ok else 'FAIL', os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
            raw.count('\n') + 1, braces, parens, brackets,
            'да' if has_bom else 'НЕТ', 'да' if namespace else 'НЕТ',
            regions, end_regions, ifs, endifs))
        if not has_bom:
            problems.append('%s: нет BOM (кириллица сломается на Windows)' % path)
        for label, value in (('фигурные', braces), ('круглые', parens), ('квадратные', brackets)):
            if value != 0:
                problems.append('%s: несбалансированные %s скобки (%+d)' % (path, label, value))
        if regions != end_regions:
            problems.append('%s: #region %d != #endregion %d' % (path, regions, end_regions))
        if ifs != endifs:
            problems.append('%s: #if %d != #endif %d' % (path, ifs, endifs))
        if namespace is None:
            problems.append('%s: нет namespace KakayatoBurmalda.*' % path)
        if not name_ok:
            problems.append('%s: имя файла не совпадает с классами %s' % (path, classes))
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- 2. поля генератора

def check_generator_fields(files, raws):
    problems = []
    print()
    print('--- 2. Поля, которые генератор назначает через SerializedObject ---')
    generator_path = next((p for p in files if p.endswith(GENERATOR)), None)
    if generator_path is None:
        print('  - ПРОБЛЕМА: не найден генератор', GENERATOR)
        return False

    by_class = {}
    for name in set(TARGET_METHODS.values()) | set(v[0] for v in UNITY_MEMBER_SOURCES.values()):
        for path in files:
            if os.path.splitext(os.path.basename(path))[0] == name:
                by_class[name] = path
    fields = {}
    for name, path in by_class.items():
        fields[name] = serialized_fields(raws[path], files[path])
    for alias, (cls, nested) in UNITY_MEMBER_SOURCES.items():
        fields[alias] = serialized_fields(raws[by_class[cls]], class_body(files[by_class[cls]], nested))

    mask = files[generator_path]
    raw = raws[generator_path]
    generator_menu = os.path.basename(generator_path).replace('.cs', '')

    checked = 0
    for method, target in TARGET_METHODS.items():
        span = method_span(mask, method)
        if span is None:
            problems.append('не найдено тело метода %s' % method)
            continue
        raw_body = raw[span[0]:span[1]]
        used = set(re.findall(r'Set\w+(?:<[^>]+>)?\(\s*\w+\s*,\s*"([^"]+)"', raw_body))
        used |= set(re.findall(r'FindProperty\("([^"]+)"\)', raw_body))
        for field in sorted(used):
            checked += 1
            if field not in fields.get(target, set()):
                problems.append('%s: у %s нет serialized-поля "%s"' % (method, target, field))

    relative = set(re.findall(r'FindPropertyRelative\("([^"]+)"\)', raw))
    for field in sorted(relative):
        checked += 1
        if field not in fields.get('LabelBinding', set()) and field not in fields.get('WheelVisual', set()):
            problems.append('FindPropertyRelative: неизвестное поле "%s"' % field)

    print('проверено полей: %d (генератор %s)' % (checked, generator_menu))
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- 3. члены типов

MEMBER_USE = re.compile(r'(?<![\w.])([A-Za-z_]\w*)\.(\w+)')


def parse_methods(mask):
    """[(имя, (popen,pclose), (bopen,bclose), required, max, [(имя, тип)])]"""
    methods = []
    for m in re.finditer(r'(?:public|private|protected|internal)\s+'
                         r'(?:static\s+|virtual\s+|override\s+|sealed\s+|new\s+|readonly\s+|partial\s+)*'
                         r'[\w<>\[\],\.\?]+\s+(\w+)\s*\(', mask):
        name, popen = m.group(1), m.end() - 1
        pclose = close_of(mask, popen)
        if pclose < 0:
            continue
        k = pclose + 1
        while k < len(mask) and mask[k] in ' \t\r\n':
            k += 1
        if k >= len(mask) or mask[k] != '{':
            continue
        bclose = close_of(mask, k)
        if bclose < 0:
            continue
        params, required, has_params, optional = [], 0, False, False
        for raw_param in split_top(mask[popen + 1:pclose]):
            clean = raw_param.split('=')[0].strip()
            tokens = [t for t in clean.split() if t not in ('out', 'ref', 'in', 'params', 'this')]
            if not tokens:
                continue
            params.append((tokens[-1], tokens[-2] if len(tokens) > 1 else '?'))
            if raw_param.strip().startswith('params '):
                has_params = True
                continue
            if '=' in raw_param:
                optional = True
            elif not optional:
                required += 1
        methods.append((name, (popen, pclose), (k, bclose), required,
                        float('inf') if has_params else len(params), params))
    return methods


def file_scope(mask):
    """Типы всех полей файла: нужно, чтобы поля класса тоже выводились по типу."""
    scope = {}
    for m in re.finditer(r'(?<![\w.])([A-Z]\w*)\s+(\w+)\s*(?==|;|,|\))', mask):
        scope.setdefault(m.group(2), set()).add(m.group(1))
    return scope


def scope_of(mask, methods, pos):
    scope = {k: set(v) for k, v in file_scope(mask).items()}
    best = None
    for mname, _, body, _, _, params in methods:
        if body[0] <= pos <= body[1] and (best is None or body[0] >= best[0]):
            best = (body, params)
    if best is None:
        return scope
    body, params = best
    for pname, ptype in params:
        if ptype != '?':
            scope.setdefault(pname, set()).add(ptype)
    inner = mask[body[0]:body[1]]
    for mm in re.finditer(r'(?<![\w.])([A-Z]\w*)\s+(\w+)\s*(?==|;|,|\))', inner):
        scope.setdefault(mm.group(2), set()).add(mm.group(1))
    return scope


def check_members(files):
    problems = []
    print()
    print('--- 3. Члены типов проекта (X.Member) ---')
    checked = 0
    for path, mask in files.items():
        methods = parse_methods(mask)
        for m in MEMBER_USE.finditer(mask):
            owner = m.group(1)
            member = m.group(2)
            if owner in ('this', 'base'):
                continue
            span = scope_of(mask, methods, m.start())
            if owner in UNITY_TYPES:
                continue
            if owner in PROJECT_TYPES:
                checked += 1
                if member not in allowed_members(owner):
                    problems.append('%s:%d: у типа %s нет члена «%s»' % (
                        os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                        line_of(mask, m.start()), owner, member))
                continue
            types = span.get(owner)
            if not types or len(types) != 1:
                continue
            type_name = next(iter(types))
            if type_name in UNITY_TYPES or type_name not in PROJECT_TYPES:
                continue
            checked += 1
            if member not in allowed_members(type_name):
                problems.append('%s:%d: %s (%s) — нет члена «%s»' % (
                    os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                    line_of(mask, m.start()), owner, type_name, member))
    print('проверено обращений: %d' % checked)
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- 4. string.Format

def check_string_format(files, raws):
    problems = []
    print()
    print('--- 4. Согласованность string.Format ---')
    checked = 0
    for path, mask in files.items():
        raw = raws[path]
        for m in re.finditer(r'string\.Format\s*\(', mask):
            popen = m.end() - 1
            pclose = close_of(mask, popen)
            if pclose < 0:
                continue
            spans = split_top(mask[popen + 1:pclose])
            if len(spans) < 2:
                continue
            # позиции аргументов в маске не дают границ; берём сырой текст по числу аргументов:
            # литералы в маске пустые, поэтому идём по маске и собираем границы вручную
            args = split_top_spans(mask, popen + 1, pclose, raw)
            if len(args) < 2:
                continue
            fmt_raw = raw[args[0][0]:args[0][1]]
            placeholders = set(int(x) for x in re.findall(r'\{(\d+)', fmt_raw))
            actual = len(args) - 1
            if '"' not in fmt_raw:
                continue  # формат — переменная: число мест статически неизвестно
            checked += 1
            highest = max(placeholders) if placeholders else -1
            if highest >= actual:
                problems.append('%s:%d: мест {%s} = %d, аргументов %d' % (
                    os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                    line_of(mask, m.start()),
                    ','.join(str(x) for x in sorted(placeholders)), len(placeholders), actual))
    print('вызовов проверено: %d' % checked)
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


def split_top_spans(mask, start, end, raw=None):
    """Как split_top, но возвращает пары (начало, конец) каждого аргумента."""
    spans, depth, cur = [], 0, start
    i = start
    while i < end:
        ch = mask[i]
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ',' and depth == 0:
            spans.append((cur, i))
            cur = i + 1
        i += 1
    spans.append((cur, end))
    if len(spans) == 1:
        # маска стирает литералы: пустой в маске span может быть настоящей строкой в коде,
        # поэтому «нет аргументов» определяем по сырому тексту
        probe = raw[spans[0][0]:spans[0][1]] if raw is not None else mask[spans[0][0]:spans[0][1]]
        if not probe.strip():
            return []
    return spans


# ---------------------------------------------------------------- 5. атрибуты

def check_attributes(files):
    problems = []
    print()
    print('--- 5. Несуществующие атрибуты Unity ([Slider]/[IntSlider]) ---')
    for path, mask in files.items():
        for m in re.finditer(r'\[(Slider|IntSlider)\s*[\(\]]', mask):
            problems.append('%s:%d: атрибут [%s] не существует в Unity API (нужен [Range])' % (
                os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                line_of(mask, m.start()), m.group(1)))
    if not problems:
        print('не найдено — ок')
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- 6. Undo.AddComponent

def check_undo_add_component(files):
    problems = []
    print()
    print('--- 6. Undo.AddComponent<T>() получает GameObject, а не Transform ---')
    checked = 0
    for path, mask in files.items():
        methods = parse_methods(mask)
        for m in re.finditer(r'Undo\.AddComponent<([^>]+)>\(([^)]*)\)', mask):
            checked += 1
            arg = m.group(2).strip()
            if arg == 'gameObject' or arg.endswith('.gameObject'):
                continue
            actual = infer_type(arg, scope_of(mask, methods, m.start()))
            if actual is None:
                continue  # тип неизвестен — статически не проверить
            if not assignable(actual, 'GameObject'):
                problems.append('%s:%d: Undo.AddComponent<%s>(%s) — нужен GameObject, а не %s' % (
                    os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                    line_of(mask, m.start()), m.group(1), arg, actual))
    print('проверено вызовов: %d' % checked)
    if checked == 0:
        problems.append('не найдено вызовов Undo.AddComponent — проверьте якорь поиска')
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- 7. вызовы

HIERARCHY = {
    'GameObject': ['UnityEngine.Object', 'object'],
    'Component': ['UnityEngine.Object', 'object'],
    'Behaviour': ['Component'],
    'MonoBehaviour': ['Behaviour'],
    'Transform': ['Component'],
    'RectTransform': ['Transform'],
    'Rigidbody': ['Component'],
    'Collider': ['Component'],
    'BoxCollider': ['Collider'],
    'SphereCollider': ['Collider'],
    'CapsuleCollider': ['Collider'],
    'MeshCollider': ['Collider'],
    'Renderer': ['Component'],
    'MeshRenderer': ['Renderer'],
    'MeshFilter': ['Component'],
    'Camera': ['Behaviour'],
    'Light': ['Behaviour'],
    'Canvas': ['Behaviour'],
    'CanvasGroup': ['Behaviour'],
    'Image': ['Behaviour'],
    'Text': ['Behaviour'],
    'Shadow': ['Behaviour'],
    'Outline': ['Behaviour'],
    'Button': ['Behaviour'],
    'Slider': ['Behaviour'],
    'AudioSource': ['Behaviour'],
    'ScriptableObject': ['UnityEngine.Object'],
    'EditorWindow': ['ScriptableObject'],
    'UnityEngine.Object': ['object'],
    'object': [],
}
BASE_TYPES = {'UnityEngine.Object', 'object'}

# Члены внешних типов, которые проект действительно использует (иначе — опечатка вроде Debug.LogNoSuch).
KNOWN_UNITY_MEMBERS = {
    'Application': {'isPlaying'},
    'Array': {'IndexOf', 'Length', 'GetLength', 'GetValue', 'SetValue', 'Sort', 'Reverse'},
    'AssetDatabase': {'CreateAsset', 'CreateFolder', 'IsValidFolder', 'LoadAllAssetsAtPath',
                      'LoadAssetAtPath', 'Refresh', 'SaveAssets'},
    'BoxCollider': {'center', 'size', 'isTrigger', 'material', 'sharedMaterial', 'enabled', 'bounds'},
    'Camera': {'fieldOfView', 'nearClipPlane', 'farClipPlane', 'depth', 'orthographic',
               'orthographicSize', 'main', 'allCameras', 'ScreenPointToRay', 'WorldToScreenPoint',
               'transform', 'gameObject', 'enabled', 'name'},
    'CanvasScaler': {'ScaleMode', 'ScreenMatchMode', 'uiScaleMode', 'referenceResolution',
                     'screenMatchMode', 'matchWidthOrHeight', 'referencePixelsPerUnit'},
    'Collider': {'isTrigger', 'material', 'sharedMaterial', 'enabled', 'bounds', 'attachedRigidbody'},
    'CollisionDetectionMode': {'ContinuousSpeculative', 'Continuous', 'ContinuousDynamic', 'Discrete'},
    'Color': {'white', 'black', 'gray', 'grey', 'red', 'green', 'blue', 'yellow', 'cyan',
              'magenta', 'clear', 'Lerp', 'a', 'r', 'g', 'b'},
    'Convert': {'ToInt32', 'ToSingle', 'ToString', 'ToBoolean'},
    'CultureInfo': {'InvariantCulture'},
    'Cursor': {'lockState', 'visible'},
    'CursorLockMode': {'Locked', 'None', 'Confined'},
    'Debug': {'Log', 'LogError', 'LogWarning', 'LogFormat', 'LogException', 'Assert'},
    'EditorGUI': {'indentLevel', 'BeginChangeCheck', 'EndChangeCheck', 'LabelField',
                  'PropertyField', 'Slider'},
    'EditorGUILayout': {'BeginScrollView', 'EndScrollView', 'Foldout', 'HelpBox', 'IntSlider',
                        'LabelField', 'Slider', 'Space', 'TextField', 'Toggle', 'BeginHorizontal',
                        'EndHorizontal', 'BeginVertical', 'EndVertical', 'Label', 'ObjectField',
                        'PropertyField', 'Separator', 'ToggleLeft'},
    'EditorGUIUtility': {'PingObject', 'currentViewWidth', 'labelWidth', 'singleLineHeight'},
    'EditorPrefs': {'GetBool', 'SetBool', 'GetFloat', 'SetFloat', 'GetInt', 'SetInt',
                    'GetString', 'SetString', 'HasKey', 'DeleteKey'},
    'EditorSceneManager': {'MarkSceneDirty', 'MoveGameObjectToScene', 'NewScene',
                           'SaveCurrentModifiedScenesIfUserWantsTo', 'SaveScene', 'OpenScene',
                           'SaveOpenScenes', 'GetSceneManagerSetup'},
    'EditorStyles': {'boldLabel', 'miniLabel', 'label', 'helpBox', 'textField', 'foldout'},
    'EditorUtility': {'ClearProgressBar', 'DisplayDialog', 'DisplayProgressBar', 'SetDirty',
                      'DisplayCancelableProgressBar', 'SaveFilePanelInProject'},
    'Font': {'CreateDynamicFontFromOSFont', 'GetOSInstalledFontNames'},
    'FontStyle': {'Bold', 'Normal', 'Italic', 'BoldAndItalic'},
    'ForceMode': {'Acceleration', 'Force', 'Impulse', 'VelocityChange'},
    'GUI': {'DragWindow', 'skin', 'Label', 'Button', 'Box', 'color'},
    'GUILayout': {'BeginHorizontal', 'BeginScrollView', 'Button', 'EndHorizontal', 'EndScrollView',
                  'Height', 'HorizontalSlider', 'Label', 'Space', 'Toggle', 'Width', 'Window',
                  'BeginVertical', 'EndVertical', 'FlexibleSpace', 'LabelField', 'TextField'},
    'GameObject': {'CreatePrimitive', 'SetActive', 'activeSelf', 'activeInHierarchy', 'AddComponent',
                   'GetComponent', 'GetComponentInChildren', 'GetComponentInParent',
                   'GetComponentsInChildren', 'GetComponents', 'CompareTag', 'transform', 'name',
                   'tag', 'layer', 'Find', 'FindWithTag', 'FindGameObjectsWithTag'},
    'Image': {'sprite', 'color', 'raycastTarget', 'type', 'fillAmount', 'enabled'},
    'Input': {'GetKey', 'GetKeyDown', 'GetKeyUp', 'GetAxis', 'GetAxisRaw', 'GetButton',
              'GetMouseButton', 'mousePosition'},
    'KeyCode': {'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P',
                'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'Space', 'Escape', 'Return',
                'LeftShift', 'RightShift', 'LeftControl', 'RightControl', 'LeftAlt', 'RightAlt',
                'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
                'UpArrow', 'DownArrow', 'LeftArrow', 'RightArrow', 'None', 'Tab', 'Backspace'},
    'LayerMask': {'LayerToName', 'NameToLayer', 'GetMask', 'value'},
    'Material': {'color', 'mainTexture', 'SetColor', 'SetFloat', 'SetTexture', 'shader', 'name',
                 'EnableKeyword', 'DisableKeyword'},
    'Mathf': {'Abs', 'Approximately', 'Atan2', 'Ceil', 'CeilToInt', 'Clamp', 'Clamp01', 'Cos',
              'Deg2Rad', 'Exp', 'Floor', 'FloorToInt', 'Infinity', 'Lerp', 'LerpAngle',
              'LerpUnclamped', 'Log', 'Max', 'Min', 'MoveTowards', 'MoveTowardsAngle',
              'NegativeInfinity', 'PI', 'PingPong', 'Pow', 'Rad2Deg', 'Repeat', 'Round',
              'RoundToInt', 'Sign', 'Sin', 'SmoothDamp', 'SmoothDampAngle', 'SmoothStep', 'Sqrt',
              'Tan', 'DeltaAngle', 'Epsilon'},
    'NumberStyles': {'Float', 'Integer', 'Any', 'Number'},
    'Physics': {'IgnoreCollision', 'OverlapBoxNonAlloc', 'SphereCastNonAlloc', 'Raycast',
                'RaycastAll', 'OverlapSphere', 'OverlapBox', 'OverlapSphereNonAlloc', 'gravity',
                'defaultContactOffset', 'queriesHitTriggers'},
    'PlayerPrefs': {'GetInt', 'SetInt', 'GetFloat', 'SetFloat', 'GetString', 'SetString',
                    'HasKey', 'DeleteKey', 'Save'},
    'PrimitiveType': {'Cube', 'Cylinder', 'Sphere', 'Capsule', 'Plane', 'Quad'},
    'Quaternion': {'AngleAxis', 'Euler', 'LookRotation', 'Slerp', 'RotateTowards', 'identity',
                   'Inverse', 'Lerp', 'eulerAngles'},
    'QueryTriggerInteraction': {'Ignore', 'Collide', 'UseGlobal'},
    'Resources': {'GetBuiltinResource', 'Load'},
    'Rigidbody': {'mass', 'drag', 'angularDrag', 'useGravity', 'isKinematic', 'constraints',
                  'centerOfMass', 'ResetCenterOfMass', 'velocity', 'angularVelocity', 'AddForce',
                  'AddRelativeForce', 'AddTorque', 'AddRelativeTorque', 'AddExplosionForce',
                  'AddForceAtPosition', 'MovePosition', 'MoveRotation', 'Sleep', 'WakeUp',
                  'interpolation', 'collisionDetectionMode', 'position', 'rotation',
                  'freezeRotation', 'maxAngularVelocity', 'detectCollisions', 'GetPointVelocity',
                  'ClosestPointOnBounds', 'SweepTest', 'SweepTestAll'},
    'RigidbodyInterpolation': {'Interpolate', 'None', 'Extrapolate'},
    'SceneManager': {'GetActiveScene', 'LoadScene', 'sceneCount', 'GetSceneAt'},
    'SceneView': {'lastActiveSceneView', 'currentDrawingCamera'},
    'Screen': {'height', 'width', 'fullScreen', 'SetResolution'},
    'Selection': {'activeGameObject', 'activeTransform', 'objects', 'gameObjects'},
    'Shader': {'Find'},
    'StringComparison': {'Ordinal', 'OrdinalIgnoreCase', 'InvariantCulture'},
    'System': {'Collections', 'Globalization', 'Random', 'Serializable', 'IO'},
    'TextAnchor': {'LowerCenter', 'LowerLeft', 'LowerRight', 'MiddleCenter', 'MiddleLeft',
                   'MiddleRight', 'UpperCenter', 'UpperLeft', 'UpperRight'},
    'Text': {'text', 'font', 'fontSize', 'color', 'alignment', 'raycastTarget', 'enabled',
             'fontStyle', 'horizontalOverflow', 'verticalOverflow', 'resizeTextForBestFit',
             'supportRichText', 'lineSpacing', 'preferredWidth', 'preferredHeight'},
    'Time': {'deltaTime', 'fixedDeltaTime', 'fixedTime', 'time', 'unscaledDeltaTime',
             'unscaledTime', 'timeScale', 'frameCount', 'realtimeSinceStartup'},
    'Transform': {'position', 'rotation', 'localPosition', 'localRotation', 'localScale',
                  'eulerAngles', 'localEulerAngles', 'forward', 'right', 'up', 'parent',
                  'root', 'childCount', 'SetParent', 'Find', 'GetChild', 'GetSiblingIndex',
                  'SetSiblingIndex', 'SetAsLastSibling', 'SetAsFirstSibling', 'InverseTransformPoint',
                  'TransformPoint', 'InverseTransformDirection', 'TransformDirection', 'LookAt',
                  'Rotate', 'Translate', 'DetachChildren', 'localToWorldMatrix', 'worldToLocalMatrix',
                  'gameObject', 'name', 'lossyScale'},
    'Type': {'GetType', 'Name', 'FullName'},
    'Undo': {'AddComponent', 'DestroyObjectImmediate', 'RecordObject', 'RegisterCreatedObjectUndo',
             'SetTransformParent', 'RegisterCompleteObjectUndo', 'RevertAllDownToGroup'},
    'UnityEngine': {'Object', 'Rendering', 'SceneManagement', 'UI', 'AI', 'Audio'},
    'Vector2': {'zero', 'one', 'up', 'down', 'left', 'right', 'x', 'y', 'magnitude',
                'sqrMagnitude', 'normalized', 'Dot', 'Distance', 'Lerp', 'Set'},
    'Vector3': {'Cross', 'Dot', 'Lerp', 'LerpUnclamped', 'SmoothDamp', 'down', 'forward', 'one',
                'right', 'up', 'zero', 'left', 'back', 'x', 'y', 'z', 'magnitude', 'sqrMagnitude',
                'normalized', 'Distance', 'Angle', 'Project', 'ProjectOnPlane', 'Scale', 'Set',
                'MoveTowards', 'ClampMagnitude'},
    'string': {'Format', 'Join', 'IsNullOrEmpty', 'IsNullOrWhiteSpace', 'Concat', 'Compare',
               'CompareTo', 'Contains', 'StartsWith', 'EndsWith', 'Split', 'Substring', 'IndexOf',
               'LastIndexOf', 'Replace', 'Trim', 'TrimStart', 'TrimEnd', 'ToUpper', 'ToLower',
               'ToCharArray', 'Length', 'Empty', 'Intern', 'Copy', 'Remove', 'Insert',
               'PadLeft', 'PadRight', 'Normalize'},
    'Object': {'Instantiate', 'Destroy', 'DestroyImmediate', 'FindObjectOfType',
               'FindObjectsOfType', 'DontDestroyOnLoad', 'name'},
}


def ancestors(t):
    if t not in HIERARCHY:
        info = PROJECT_TYPES.get(t)
        base = info.get('base') if info else None
        if not base:
            return None
        chain = ancestors(base)
        return (chain if chain is not None else set()) | {base}
    seen, stack = set(), [t]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(HIERARCHY.get(cur, []))
    return seen


def assignable(actual, expected):
    if actual is None or expected is None:
        return True
    if actual == expected or expected in BASE_TYPES:
        return True
    chain = ancestors(actual)
    return chain is not None and expected in chain


UNITY_API = {
    'Undo.AddComponent': ['GameObject'],
    'Undo.SetTransformParent': ['Transform', 'Transform', None],
    'Undo.RegisterCreatedObjectUndo': ['UnityEngine.Object', None],
    'Undo.DestroyObjectImmediate': ['UnityEngine.Object'],
    'Undo.RecordObject': ['UnityEngine.Object', None],
    'Undo.RegisterCompleteObjectUndo': ['UnityEngine.Object', None],
    'EditorSceneManager.MoveGameObjectToScene': ['GameObject', 'Scene'],
}
RECEIVER_RULES = {
    'AddComponent': {'GameObject'},
    'GetComponent': {'GameObject', 'Component'},
    'GetComponentInChildren': {'GameObject', 'Component'},
    'GetComponentInParent': {'GameObject', 'Component'},
}
CALL = re.compile(r'(?<![\w.])([A-Za-z_]\w*(?:\.\w+)*)\s*(?:<[^<>()]*>)?\s*\(')


def infer_type(arg, scope):
    arg = arg.strip()
    if not arg:
        return None
    if re.fullmatch(r'\w+', arg):
        types = scope.get(arg)
        if types and len(types) == 1:
            return next(iter(types))
        return None
    if arg.endswith('.gameObject'):
        return 'GameObject'
    if arg.endswith('.transform'):
        return 'Transform'
    if arg.startswith('new '):
        head = arg[4:].split('(')[0].split('{')[0].split('[')[0].strip()
        if re.fullmatch(r'[\w\.]+', head):
            return head.split('.')[-1]
    return None


def check_calls(files, raws):
    problems = []
    print()
    print('--- 7. Вызовы: число/типы аргументов, редакторный Unity API ---')
    total = 0
    for path, mask in files.items():
        methods = parse_methods(mask)
        name_sigs = {}
        for name, _, _, req, mx, _ in methods:
            name_sigs.setdefault(name, []).append((req, mx))
        param_spans = [(a, b) for _, (a, b), _, _, _, _ in methods]

        for m in CALL.finditer(mask):
            full = m.group(1)
            name = full.split('.')[-1]
            popen = m.end() - 1
            if any(a - 2 <= popen <= b for a, b in param_spans):
                continue
            pclose = close_of(mask, popen)
            if pclose < 0:
                continue
            args = [mask[a:b].strip() for a, b in split_top_spans(mask, popen + 1, pclose, raws[path])]
            where = '%s:%d' % (os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                               line_of(mask, m.start()))
            scope = scope_of(mask, methods, m.start())

            if '.' not in full and name in name_sigs:
                total += 1
                if not any(req <= len(args) <= mx for req, mx in name_sigs[name]):
                    variants = ', '.join(str(r) if r == x else '%d..%s' % (r, 'inf' if x == float('inf') else x)
                                         for r, x in name_sigs[name])
                    problems.append('%s: %s(): передано %d, ожидается [%s]' % (where, name, len(args), variants))
                for mname, span, _, _, _, params in methods:
                    if mname != name or span[0] != popen:
                        continue
                    for arg, (pname, ptype) in zip(args, params):
                        actual = infer_type(arg, scope)
                        if actual and not assignable(actual, ptype):
                            problems.append('%s: %s(%s): передаётся %s, ожидается %s' % (
                                where, name, arg, actual, ptype))

            if full in UNITY_API:
                total += 1
                for arg, expected in zip(args, UNITY_API[full]):
                    if expected is None:
                        continue
                    actual = infer_type(arg, scope)
                    if actual and not assignable(actual, expected):
                        problems.append('%s: %s(%s): передаётся %s, ожидается %s' % (
                            where, full, arg, actual, expected))

            if '.' in full and name in RECEIVER_RULES:
                receiver = full.rsplit('.', 1)[0].split('.')[-1]
                actual = infer_type(receiver, scope)
                if actual:
                    if not any(assignable(actual, a) for a in RECEIVER_RULES[name]):
                        problems.append('%s: %s.%s(): получатель %s, ожидается %s' % (
                            where, receiver, name, actual, ' или '.join(sorted(RECEIVER_RULES[name]))))

    print('проверено вызовов: %d' % total)
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- 8. члены Unity-типов

def check_unity_members(files):
    problems = []
    print()
    print('--- 8. Члены внешних типов (Mathf, Debug, Input, Vector3, string, ...) ---')
    checked = 0
    for path, mask in files.items():
        methods = parse_methods(mask)
        for m in MEMBER_USE.finditer(mask):
            owner, member = m.group(1), m.group(2)
            if owner in ('this', 'base'):
                continue
            type_name = None
            if owner in KNOWN_UNITY_MEMBERS:
                type_name = owner
            else:
                types = scope_of(mask, methods, m.start()).get(owner)
                if types and len(types) == 1:
                    candidate = next(iter(types))
                    if candidate in KNOWN_UNITY_MEMBERS:
                        type_name = candidate
            if type_name is None:
                continue
            checked += 1
            if member not in KNOWN_UNITY_MEMBERS[type_name] and member not in UNITY_BASE_MEMBERS:
                problems.append('%s:%d: у внешнего типа %s нет члена «%s»' % (
                    os.path.relpath(path, os.path.dirname(os.path.dirname(path))),
                    line_of(mask, m.start()), type_name, member))
    print('проверено обращений: %d' % checked)
    for p in problems:
        print('  - ПРОБЛЕМА:', p)
    return not problems


# ---------------------------------------------------------------- запуск

def load(root):
    files, raws = {}, {}
    for path in sorted(glob.glob(os.path.join(root, '**', '*.cs'), recursive=True)):
        raw = open(path, encoding='utf-8-sig').read()
        raws[path] = raw
        files[path] = mask_code(raw)
    return files, raws


def run(files, raws):
    PROJECT_TYPES.clear()
    collect_project_types(files)
    results = [
        check_structure(files),
        check_generator_fields(files, raws),
        check_members(files),
        check_string_format(files, raws),
        check_attributes(files),
        check_undo_add_component(files),
        check_calls(files, raws),
        check_unity_members(files),
    ]
    print()
    print('ИТОГ:', 'ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ' if all(results) else 'ЕСТЬ ПРОБЛЕМЫ')
    return all(results)


SELFTEST_BUGS = [
    ('Undo.AddComponent<CameraSettingsMenu>(camera.gameObject)',
     'Undo.AddComponent<CameraSettingsMenu>(camera.transform)',
     'Undo.AddComponent<CameraSettingsMenu>(camera.transform) — нужен GameObject, а не Transform'),
    ('cameraFollow.ApplyPreset(CameraPreset.Cabin)',
     'cameraFollow.ApplyPresetNoSuchMethod(CameraPreset.Cabin)',
     'ApplyPresetNoSuchMethod'),
    ('[Range(1, 4), Tooltip("Сколько паллет',
     '[IntSlider(1, 4), Tooltip("Сколько паллет',
     'атрибут [IntSlider]'),
    ('Проверка сцены: паллет {0} (ящики {1}',
     'Проверка сцены: паллет {0} (ящики {1} {99}',
     'аргументов 9'),
    ('Debug.Log(string.Format(',
     'Debug.LogNoSuch(string.Format(',
     'нет члена «LogNoSuch»'),
    ('SetInt(serializedObject, "toggleKey", (int)KeyCode.F1);',
     'SetInt(serializedObject, "toggleKeyNoSuchField", (int)KeyCode.F1);',
     'у CameraSettingsMenu нет serialized-поля "toggleKeyNoSuchField"'),
]


def selftest(root):
    print('=== САМОПРОВЕРКА ВАЛИДАТОРА: внедряю баги, каждая проверка должна их поймать ===')
    files, raws = load(root)
    backup = {}
    for old, new, expected in SELFTEST_BUGS:
        target = None
        for path, raw in raws.items():
            if old in raw:
                target = path
                backup[path] = raw
                open(path, 'w', encoding='utf-8-sig', newline='').write(raw.replace(old, new, 1))
                break
        if target is None:
            print('  - НЕ НАЙДЕН якорь:', old[:60])
            continue
        changed, changed_raw = load(root)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            run(changed, changed_raw)
        text = buffer.getvalue()
        caught = expected in text
        print('%-4s внедрено «%s»\n       ожидалось «%s» → %s' % (
            'OK' if caught else 'FAIL', new[:60], expected, 'поймано' if caught else 'ПРОПУЩЕНО'))
        open(target, 'w', encoding='utf-8-sig', newline='').write(backup[target])
    print('файлы восстановлены')
    return 0


def main(argv):
    root = DEFAULT_ROOT
    for arg in argv[1:]:
        if arg.startswith('--root='):
            root = arg.split('=', 1)[1]
    if not os.path.isdir(root):
        print('нет каталога', root)
        return 2
    files, raws = load(root)
    if not files:
        print('НЕ НАЙДЕНЫ .cs-файлы в', root)
        return 2
    print('файлов к проверке: %d (%s)' % (len(files), root))
    if '--selftest' in argv:
        return selftest(root)
    return 0 if run(files, raws) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
