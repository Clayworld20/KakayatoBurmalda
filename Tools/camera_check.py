# -*- coding: utf-8 -*-
"""Проверка кабинной позы камеры по фактической геометрии модели (без Unity).

Запуск:  python3 Tools/camera_check.py           # отчёт по текущим дефолтам камеры
         python3 Tools/camera_check.py --search  # перебор поз по всей сетке

Что считается:
  1. Поза камеры (offset, pivotHeight, lookOffset, FOV) читается прямо из дефолтов
     Assets/Scripts/CameraFollow.cs — проверяются те числа, что реально в коде.
  2. Коробочная модель погрузчика построена по вызовам CreateDecorPrimitive в
     Assets/Scripts/Editor/DemoSceneGenerator.cs (координаты центра и localScale
     примитивов = полный размер; в скобках — номера строк генератора).
  3. Проверки: камера не внутри геометрии; расстояние до ближайшей поверхности;
     видимость контрольных точек (кончики вил, каретка, паллета с грузом перед вилами)
     методом пересечения отрезка камера→точка с коробками (slab-тест AABB).
"""
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, 'Assets/Scripts/Editor/DemoSceneGenerator.cs')
CAM = os.path.join(ROOT, 'Assets/Scripts/CameraFollow.cs')

# ---------------------------------------------------------------- модель погрузчика
# (имя, центр в системе погрузчика, полный размер) — из DemoSceneGenerator.cs
FORKLIFT_BOXES = [
    # корпус и кормовая часть
    ('Body',              (0.00, 1.05,  0.15), (1.50, 1.40, 2.30)),   # стр. 1756-1757
    ('Counterweight',     (0.00, 0.72, -1.30), (1.40, 1.00, 0.55)),   # стр. 1761-1762
    ('RearTank',          (0.00, 1.55, -1.30), (0.75, 0.84, 0.75)),   # стр. 1765-1766 (цилиндр: ось по Z)
    ('RearTankStrap_L',   (-0.30, 1.55, -1.30), (0.08, 0.78, 0.80)),  # стр. 1775-1777
    ('RearTankStrap_R',   (0.30, 1.55, -1.30), (0.08, 0.78, 0.80)),
    ('Exhaust',           (0.55, 2.20, -1.05), (0.12, 0.90, 0.12)),   # стр. 1781-1782
    # кабина и остекление
    ('Cabin',             (0.00, 2.05, -0.55), (1.25, 0.60, 1.10)),   # стр. 1786-1787
    ('CabinGlass_Front',  (0.00, 1.98,  0.03), (1.05, 0.52, 0.06)),   # стр. 1790-1791
    ('CabinGlass_L',      (-0.64, 1.98, -0.55), (0.06, 0.52, 0.95)),  # стр. 1796-1798
    ('CabinGlass_R',      (0.64, 1.98, -0.55), (0.06, 0.52, 0.95)),
    ('CabinPost_LF',      (-0.60, 2.10, -0.03), (0.10, 1.10, 0.10)),  # стр. 1806-1810
    ('CabinPost_RF',      (0.60, 2.10, -0.03), (0.10, 1.10, 0.10)),
    ('CabinPost_LB',      (-0.60, 2.10, -1.07), (0.10, 1.10, 0.10)),
    ('CabinPost_RB',      (0.60, 2.10, -1.07), (0.10, 1.10, 0.10)),
    # защитная решётка
    ('OverheadGuard',     (0.00, 2.62, -0.55), (1.42, 0.12, 1.32)),   # стр. 1816-1817
    ('GuardBar_1',        (-0.45, 2.55, -0.55), (0.08, 0.08, 1.48)),  # стр. 1822-1824
    ('GuardBar_2',        (0.00, 2.55, -0.55), (0.08, 0.08, 1.48)),
    ('GuardBar_3',        (0.45, 2.55, -0.55), (0.08, 0.08, 1.48)),
    # мачта
    ('MastRail_L',        (-0.52, 1.50, 1.20), (0.16, 2.60, 0.32)),   # стр. 1844-1846
    ('MastRail_R',        (0.52, 1.50, 1.20), (0.16, 2.60, 0.32)),
    ('MastCylinder_L',    (-0.30, 1.45, 1.30), (0.14, 2.20, 0.14)),   # стр. 1849-1851
    ('MastCylinder_R',    (0.30, 1.45, 1.30), (0.14, 2.20, 0.14)),
    ('MastTie_1',         (0.00, 0.45, 1.20), (1.14, 0.12, 0.36)),    # стр. 1857-1859
    ('MastTie_2',         (0.00, 1.45, 1.20), (1.14, 0.12, 0.36)),
    ('MastTie_3',         (0.00, 2.45, 1.20), (1.14, 0.12, 0.36)),
    ('Headlight_L',       (-0.45, 2.34, 1.32), (0.22, 0.22, 0.22)),   # стр. 1831-1833
    ('Headlight_R',       (0.45, 2.34, 1.32), (0.22, 0.22, 0.22)),
]
# каретка вил: MastTiltPivot (0, 0.12, 1.2) + ForkCarriage (0, currentForkHeight, 0);
# на старте currentForkHeight = forkMinHeight = 0.02  (ForkliftController, ApplyForkHeight)
MAST_PIVOT = (0.0, 0.12, 1.20)
CARRIAGE_BOXES = [
    ('CarriagePlate', (0.00, 0.50, 0.02), (1.30, 0.85, 0.12)),   # стр. 1883-1884
    ('Fork_Left',     (-0.42, 0.00, 0.70), (0.18, 0.12, 1.70)),  # стр. 1887-1888
    ('Fork_Right',    (0.42, 0.00, 0.70), (0.18, 0.12, 1.70)),   # стр. 1891-1892
]
FORK_START_HEIGHT = 0.02


def boxes_now(fork_height=FORK_START_HEIGHT):
    boxes = list(FORKLIFT_BOXES)
    for name, center, size in CARRIAGE_BOXES:
        boxes.append((name,
                      (MAST_PIVOT[0] + center[0],
                       MAST_PIVOT[1] + fork_height + center[1],
                       MAST_PIVOT[2] + center[2]),
                      size))
    return boxes


# ---------------------------------------------------------------- дефолты камеры

def read_camera_defaults():
    text = open(CAM, encoding='utf-8-sig').read()
    out = {}

    def vec(field):
        m = re.search(re.escape(field) + r'\s*=\s*new Vector3\(([^)]*)\)', text)
        if not m:
            return None
        return tuple(float(x.strip().rstrip('f')) for x in m.group(1).split(','))

    def num(field):
        m = re.search(re.escape(field) + r'\s*=\s*([-\d\.]+)f?\s*;', text)
        return float(m.group(1)) if m else None

    out['offset'] = vec('offset')
    out['pivotHeight'] = num('pivotHeight')
    out['lookOffset'] = vec('lookOffset')
    out['fieldOfView'] = num('fieldOfView')
    out['minHeight'] = num('minHeight')
    return out


# ---------------------------------------------------------------- геометрия

def inside(box, point, margin=0.0):
    _, center, size = box
    for axis in range(3):
        half = size[axis] * 0.5 + margin
        if abs(point[axis] - center[axis]) > half:
            return False
    return True


def distance_to_surface(box, point):
    _, center, size = box
    d = 0.0
    for axis in range(3):
        half = size[axis] * 0.5
        d += max(0.0, abs(point[axis] - center[axis]) - half) ** 2
    return math.sqrt(d)


def segment_hits_box(box, a, b, eps=0.02, eps_end=0.98):
    """slab-тест: пересекает ли отрезок a→b коробку при параметре t из (eps, eps_end)."""
    _, center, size = box
    t_min, t_max = eps, eps_end
    for axis in range(3):
        lo = center[axis] - size[axis] * 0.5
        hi = center[axis] + size[axis] * 0.5
        start, end = a[axis], b[axis]
        delta = end - start
        if abs(delta) < 1e-9:
            if start < lo or start > hi:
                return False
            continue
        t1 = (lo - start) / delta
        t2 = (hi - start) / delta
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
        if t_min > t_max:
            return False
    return True


# ---------------------------------------------------------------- пирамида обзора

ASPECT = 16.0 / 9.0


def in_frustum(cam, look, fov, point, margin_deg=1.0):
    """Попадает ли точка в кадр: Unity Camera.fieldOfView — угол по вертикали.

    Кадр строим в собственном базисе камеры: forward = ось взгляда, right = forward x worldUp,
    up = right x forward. Углы считаем через atan2, поэтому точка «позади» камеры сразу даёт >90°.
    """
    axis = tuple(look[i] - cam[i] for i in range(3))
    aim = tuple(point[i] - cam[i] for i in range(3))
    length_axis = math.sqrt(sum(c * c for c in axis))
    length_aim = math.sqrt(sum(c * c for c in aim))
    if length_axis < 1e-6 or length_aim < 1e-6:
        return True
    axis = tuple(c / length_axis for c in axis)
    aim = tuple(c / length_aim for c in aim)

    world_up = (0.0, 1.0, 0.0) if abs(axis[1]) < 0.999 else (1.0, 0.0, 0.0)
    right = (axis[1] * world_up[2] - axis[2] * world_up[1],
             axis[2] * world_up[0] - axis[0] * world_up[2],
             axis[0] * world_up[1] - axis[1] * world_up[0])
    norm_right = math.sqrt(sum(c * c for c in right))
    right = tuple(c / norm_right for c in right)
    up = (right[1] * axis[2] - right[2] * axis[1],
          right[2] * axis[0] - right[0] * axis[2],
          right[0] * axis[1] - right[1] * axis[0])

    forward_dot = sum(aim[i] * axis[i] for i in range(3))
    vertical = math.degrees(math.atan2(sum(aim[i] * up[i] for i in range(3)), forward_dot))
    horizontal = math.degrees(math.atan2(sum(aim[i] * right[i] for i in range(3)), forward_dot))

    half_vertical = fov * 0.5
    half_horizontal = math.degrees(math.atan(math.tan(math.radians(fov * 0.5)) * ASPECT))
    return (abs(vertical) <= half_vertical - margin_deg and
            abs(horizontal) <= half_horizontal - margin_deg)


# ---------------------------------------------------------------- контрольные точки

def targets(fork_height=FORK_START_HEIGHT):
    carriage_y = MAST_PIVOT[1] + fork_height
    blade_y = carriage_y
    # паллета, стоящая прямо перед вилами (поддон 1.25 x 0.11 x 1.05, груз до 0.95)
    pallet_z0 = 2.95
    pallet_z1 = pallet_z0 + 1.05
    return [
        ('кончик вилы L',        (-0.42, blade_y, 2.72)),
        ('кончик вилы R',        (0.42, blade_y, 2.72)),
        ('середина вилы L',      (-0.42, blade_y, 1.90)),
        ('планка каретки низ',   (0.00, carriage_y + 0.10, 1.22)),
        ('планка каретки верх',  (0.00, carriage_y + 0.90, 1.22)),
        ('паллета перед вилами', (0.00, 0.11 + 0.02, pallet_z0 + 0.5)),
        ('верх груза (ящики)',   (0.00, 0.11 + 0.95, pallet_z1 - 0.2)),
    ]


def evaluate(offset, pivot_height, look_offset, fov, label, verbose=True):
    """Возвращает (видимых, всего, заметки)."""
    cam = tuple(offset)
    boxes = boxes_now()
    visible, notes = 0, []

    if verbose:
        print('поза «%s»: offset=(%.2f, %.2f, %.2f) pivot=%.2f look=(%.2f, %.2f, %.2f) FOV=%.0f'
              % (label, offset[0], offset[1], offset[2], pivot_height,
                 look_offset[0], look_offset[1], look_offset[2], fov))

    intruders = [b[0] for b in boxes if inside(b, cam)]
    if intruders:
        print('   ВНУТРИ геометрии: %s' % ', '.join(intruders))
    near = sorted(((distance_to_surface(b, cam), b[0]) for b in boxes))[:3]
    print('   ближайшие поверхности: %s' % ', '.join('%s %.2f м' % (n, d) for d, n in near))

    look = tuple(cam[i] + look_offset[i] for i in range(3))
    for name, point in targets():
        # коробка, в которой лежит сама контрольная точка, — не перекрыватель (это сам объект)
        blockers = [b[0] for b in boxes
                    if not inside(b, point, margin=0.02) and segment_hits_box(b, cam, point)]
        if blockers:
            notes.append('%s — закрыто: %s' % (name, ', '.join(blockers[:3])))
        elif not in_frustum(cam, look, fov, point):
            notes.append('%s — перекрытий нет, но ВНЕ КАДРА' % name)
        else:
            visible += 1
            notes.append('%s — видно в кадре' % name)

    if verbose:
        for note in notes:
            print('   - %s' % note)
        print('   итог: видно %d из %d точек, направление взгляда (%.2f, %.2f, %.2f)\n'
              % (visible, len(notes), look[0], look[1], look[2]))
    return visible, len(notes), intruders


REQUIRED_POINTS = [
    ('кончик вилы L',      (-0.42, 0.14, 2.72)),
    ('кончик вилы R',      (0.42, 0.14, 2.72)),
    ('вила L (середина)',  (-0.42, 0.14, 2.30)),
    ('вила R (середина)',  (0.42, 0.14, 2.30)),
    ('паллета перед вилами', (0.0, 0.13, 3.45)),
    ('верх груза',          (0.0, 1.06, 3.80)),
]


def box_corners(box):
    _, center, size = box
    return [(center[0] + sx * size[0] * 0.5, center[1] + sy * size[1] * 0.5, center[2] + sz * size[2] * 0.5)
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def near_in_frame(boxes, cam, look, fov, limit=1.0):
    """Объекты ближе limit метров, попавшие в кадр: крупные помехи перед объективом."""
    hits = []
    for box in boxes:
        if distance_to_surface(box, cam) > limit:
            continue
        if any(in_frustum(cam, look, fov, corner, margin_deg=0.0) for corner in box_corners(box)):
            hits.append(box[0])
    return hits


def pose_report(cam, look_offset, fov=62.0, verbose=True):
    boxes = boxes_now()
    look = tuple(cam[i] + look_offset[i] for i in range(3))
    visible, details = 0, []
    for name, point in REQUIRED_POINTS:
        blockers = [b[0] for b in boxes
                    if not inside(b, point, margin=0.02) and segment_hits_box(b, cam, point)]
        if blockers:
            details.append('%s: нет (%s)' % (name, blockers[0]))
        elif not in_frustum(cam, look, fov, point):
            details.append('%s: вне кадра' % name)
        else:
            visible += 1
            details.append('%s: видно' % name)
    horizon_point = (0.0, cam[1], cam[2] + 60.0)
    horizon_ok = (in_frustum(cam, look, fov, horizon_point) and
                  not any(segment_hits_box(b, cam, horizon_point) for b in boxes))
    clearance = min(distance_to_surface(b, cam) for b in boxes)
    inside_names = [b[0] for b in boxes if inside(b, cam, margin=0.02)]
    close_ups = near_in_frame(boxes, cam, look, fov)
    if verbose:
        print('поза offset=(%.2f, %.2f, %.2f), ось взгляда: %.2f, %.2f, %.2f (FOV %.0f)'
              % (cam[0], cam[1], cam[2], look[0] - cam[0], look[1] - cam[1], look[2] - cam[2], fov))
        print('   внутри геометрии: %s; зазор до ближайшей поверхности: %.2f м; горизонт в кадре: %s'
              % (', '.join(inside_names) if inside_names else 'нет', clearance,
                 'да' if horizon_ok else 'нет'))
        if close_ups:
            print('   крупные помехи вблизи объектива: %s' % ', '.join(close_ups))
        for line in details:
            print('   - %s' % line)
        print('   ИТОГ: видно %d из %d обязательных точек\n' % (visible, len(REQUIRED_POINTS)))
    return visible, horizon_ok, inside_names, close_ups, clearance


def search():
    """Перебор поз: камера над/перед машиной, ось наводится в район вил."""
    boxes = boxes_now()
    rows = []
    for ox10 in range(-16, 17, 4):
        for oy10 in range(18, 39, 2):
            for oz10 in range(4, 27, 2):
                cam = (ox10 / 10.0, oy10 / 10.0, oz10 / 10.0)
                if any(inside(b, cam, margin=0.05) for b in boxes):
                    continue
                clearance = min(distance_to_surface(b, cam) for b in boxes)
                if clearance < 0.35:
                    continue
                for aim_y in (0.14, 0.5, 0.9, 1.4):
                    for aim_z in (1.6, 2.2, 2.8, 3.4, 4.0):
                        look_off = (0.0 - cam[0], aim_y - cam[1], aim_z - cam[2])
                        visible, horizon_ok, inside_names, close_ups, clearance = pose_report(
                            cam, look_off, verbose=False)
                        if inside_names or close_ups:
                            continue
                        rows.append((visible, int(horizon_ok), clearance,
                                     abs(cam[0]), -cam[1], -cam[2], cam, look_off))
    rows.sort(key=lambda r: (-r[0], -r[1], -r[2], r[3], r[4], r[5]))
    print('=== Поиск позы: обязательных точек %d, фильтр — зазор ≥ 0.35 м и никаких объектов в кадре ближе 1 м ===' % len(REQUIRED_POINTS))
    shown = set()
    for visible, horizon_ok, clearance, _, _, _, cam, look_off in rows:
        key = (round(cam[0], 1), round(cam[1], 1), round(cam[2], 1))
        if key in shown:
            continue
        shown.add(key)
        print('   точек %d/%d | горизонт %-3s | зазор %.2f | offset=(%.1f, %.1f, %.1f) | lookOffset=(%.2f, %.2f, %.2f)'
              % (visible, len(REQUIRED_POINTS), 'да' if horizon_ok else 'нет', clearance,
                 cam[0], cam[1], cam[2], look_off[0], look_off[1], look_off[2]))
        if len(shown) >= 12:
            break
    return rows


def read_presets():
    """Пресеты читаются из самого ApplyPreset, чтобы проверялись числа из кода, а не их копии."""
    text = open(CAM, encoding='utf-8-sig').read()
    body = text[text.index('public void ApplyPreset'):]
    body = body[:body.index('yawVelocity = 0f;')]
    presets = []
    for chunk in body.split('case CameraPreset.')[1:]:
        name = chunk.split(':')[0].strip()
        offset = re.search(r'offset\s*=\s*new Vector3\(([^)]*)\)', chunk)
        pivot = re.search(r'pivotHeight\s*=\s*([-\d\.]+)f', chunk)
        look = re.search(r'lookOffset\s*=\s*new Vector3\(([^)]*)\)', chunk)
        if not (offset and pivot and look):
            continue
        parse = lambda raw: tuple(float(x.strip().rstrip('f')) for x in raw.split(','))
        presets.append((name, parse(offset.group(1)), float(pivot.group(1)), parse(look.group(1))))
    return presets


def main():
    defaults = read_camera_defaults()
    print('=== Дефолты CameraFollow.cs ===')
    print('offset = %s, pivotHeight = %s, lookOffset = %s, fieldOfView = %s, minHeight = %s\n'
          % (defaults['offset'], defaults['pivotHeight'], defaults['lookOffset'],
             defaults['fieldOfView'], defaults['minHeight']))

    print('=== 1. Текущая поза из кода ===')
    v_new, hz_new, inside_new, close_new, clr_new = pose_report(
        defaults['offset'], defaults['lookOffset'], defaults['fieldOfView'])

    print('=== 2. Прежняя поза (сзади-сверху, до правки №7) ===')
    v_old, hz_old, inside_old, close_old, clr_old = pose_report((0.0, 4.6, -8.6), (0.0, 1.3, 1.8), 62.0)

    print('=== 3. Пресеты CameraFollow.ApplyPreset (читаются из кода) ===')
    for name, offset, pivot, look in read_presets():
        print('--- пресет %s (pivotHeight %.2f) ---' % (name, pivot))
        pose_report(offset, look, 62.0)

    print('=== ИТОГ ===')
    print('текущая поза:  видно %d/%d обязательных точек, горизонт %s, внутри геометрии %s'
          % (v_new, len(REQUIRED_POINTS), 'да' if hz_new else 'нет', inside_new or 'нет'))
    print('прежняя поза:  видно %d/%d обязательных точек, горизонт %s, внутри геометрии %s'
          % (v_old, len(REQUIRED_POINTS), 'да' if hz_old else 'нет', inside_old or 'нет'))
    return 0 if (v_new >= 5 and not inside_new and not close_new) else 1


if __name__ == '__main__':
    if '--search' in sys.argv:
        search()
        sys.exit(0)
    sys.exit(main())
