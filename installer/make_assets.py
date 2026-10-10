# -*- coding: utf-8 -*-
"""
Генератор оформления установщика Auto-Compiler (значок и картинки мастера Inno Setup).

Запуск (нужна библиотека Pillow: pip install Pillow):
    python installer/make_assets.py

Что создаётся в папке installer/:
    autocompiler.ico          — значок: установщик, ярлыки, «Приложения и возможности»;
    assets/wizard-*.png       — большая картинка слева на первой и последней страницах мастера;
    assets/wizard-small-*.png — маленькая картинка в правом верхнем углу остальных страниц.

Готовые файлы уже лежат в репозитории; скрипт нужен, только если вы захотите изменить дизайн.
Цвета взяты из autocompiler/config.py, чтобы установщик выглядел так же, как сама программа.
"""

# Аннотации типов в новом стиле в любой версии Python 3.
from __future__ import annotations

# Path — удобная работа с путями к файлам.
from pathlib import Path

# Image — холст, ImageDraw — рисование фигур, ImageFilter — размытие, ImageFont — шрифты.
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Папка, где лежит этот скрипт (installer/).
HERE = Path(__file__).resolve().parent
# Папка для картинок мастера.
ASSETS = HERE / "assets"

# Тёмный фон программы (BACKGROUND в config.py).
BACKGROUND = (13, 17, 23)
# Цвет панелей (SURFACE в config.py).
SURFACE = (22, 27, 34)
# Фирменный фиолетовый (ACCENT в config.py).
ACCENT = (109, 93, 252)
# Более светлый оттенок акцента — для градиента.
ACCENT_LIGHT = (155, 140, 255)
# Более тёмный оттенок акцента (ACCENT_HOVER в config.py).
ACCENT_DARK = (89, 72, 224)
# Основной цвет текста (TEXT в config.py).
TEXT = (230, 237, 243)
# Приглушённый текст (TEXT_MUTED в config.py).
TEXT_MUTED = (139, 148, 158)

# Во сколько раз рисуем крупнее, чтобы после уменьшения края были гладкими (сглаживание).
SUPERSAMPLE = 4

# Размеры большой картинки мастера для масштабов экрана 100/125/150/175/200 % (из справки Inno Setup 7).
WIZARD_SIZES = [(202, 386), (269, 515), (336, 643), (403, 772), (430, 824)]
# Размеры маленькой картинки для тех же масштабов.
SMALL_SIZES = [58, 77, 97, 116, 124]
# Размеры внутри файла .ico (Windows сама выберет подходящий).
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Плавный переход между двумя цветами: t=0 — цвет a, t=1 — цвет b."""
    # Смешиваем каждый канал (красный, зелёный, синий) отдельно.
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Прямоугольник с вертикальным градиентом сверху вниз."""
    # Ширина и высота.
    width, height = size
    # Полоска шириной 1 пиксель — быстро заполняем построчно.
    strip = Image.new("RGB", (1, height))
    # Проходим по всем строкам полоски.
    for y in range(height):
        # Цвет строки — смесь верхнего и нижнего цветов.
        strip.putpixel((0, y), lerp(top, bottom, y / max(1, height - 1)))
    # Растягиваем полоску на всю ширину.
    return strip.resize((width, height))


def diagonal_gradient(size: int, start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    """Квадрат с диагональным градиентом (из левого верхнего угла в правый нижний)."""
    # Маленький квадрат 64×64: градиент плавный, потом растягиваем.
    small = Image.new("RGB", (64, 64))
    # Проходим по всем пикселям маленького квадрата.
    for y in range(64):
        # Каждый столбец строки.
        for x in range(64):
            # Доля пути по диагонали (0..1).
            small.putpixel((x, y), lerp(start, end, (x + y) / 126))
    # Растягиваем до нужного размера с плавной интерполяцией.
    return small.resize((size, size), Image.Resampling.BICUBIC)


def draw_cube(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, line: float) -> None:
    """Нарисовать белый изометрический «кубик-посылку» — символ упакованной программы."""
    # Половина ширины грани по горизонтали (изометрия: cos 30° ≈ 0.866).
    dx = r * 0.866
    # Половина высоты ромба верхней грани.
    dy = r * 0.5
    # Верхняя вершина кубика.
    top = (cx, cy - r)
    # Правая верхняя вершина.
    right_top = (cx + dx, cy - dy)
    # Правая нижняя вершина.
    right_bottom = (cx + dx, cy + dy)
    # Нижняя вершина.
    bottom = (cx, cy + r)
    # Левая нижняя вершина.
    left_bottom = (cx - dx, cy + dy)
    # Левая верхняя вершина.
    left_top = (cx - dx, cy - dy)
    # Центр (ближний угол кубика).
    center = (cx, cy)
    # Верхняя грань — самая светлая (как будто освещена сверху).
    draw.polygon([top, right_top, center, left_top], fill=(255, 255, 255, 255))
    # Левая грань — чуть темнее.
    draw.polygon([left_top, center, bottom, left_bottom], fill=(255, 255, 255, 215))
    # Правая грань — ещё темнее.
    draw.polygon([center, right_top, right_bottom, bottom], fill=(255, 255, 255, 170))
    # Цвет «ленты» на посылке — фирменный тёмно-фиолетовый.
    tape = ACCENT_DARK + (255,)
    # Лента поперёк верхней грани (от середины левого ребра к середине правого).
    draw.line([((left_top[0] + top[0]) / 2, (left_top[1] + top[1]) / 2),
               ((center[0] + right_top[0]) / 2, (center[1] + right_top[1]) / 2)], fill=tape, width=round(line))
    # Лента спускается по левой грани вниз.
    draw.line([((center[0] + right_top[0]) / 2, (center[1] + right_top[1]) / 2),
               ((bottom[0] + right_bottom[0]) / 2, (bottom[1] + right_bottom[1]) / 2)], fill=tape, width=round(line))


def make_icon_image(size: int) -> Image.Image:
    """Квадратный значок: фиолетовая скруглённая плашка с белым кубиком."""
    # Рисуем в увеличенном масштабе.
    big = size * SUPERSAMPLE
    # Прозрачный холст.
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    # Градиентная заливка плашки.
    gradient = diagonal_gradient(big, ACCENT_LIGHT, ACCENT_DARK)
    # Маска со скруглёнными углами (форма плашки).
    mask = Image.new("L", (big, big), 0)
    # Радиус скругления — 22 % размера (как у современных значков Windows 11).
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * 0.22), fill=255)
    # Накладываем градиент по маске.
    canvas.paste(gradient, (0, 0), mask)
    # Отдельный слой для кубика (чтобы полупрозрачные грани смешивались правильно).
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    # Рисуем кубик по центру, радиус — 34 % размера.
    draw_cube(ImageDraw.Draw(layer), big / 2, big / 2 + big * 0.02, big * 0.34, max(1, big * 0.035))
    # Совмещаем слой с плашкой.
    canvas = Image.alpha_composite(canvas, layer)
    # Уменьшаем до нужного размера с качественным сглаживанием.
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Шрифт для надписей: DejaVu Sans (есть в Linux), Segoe UI (Windows) или встроенный."""
    # Кандидаты по порядку предпочтения.
    candidates = (
        ["DejaVuSans-Bold.ttf", "segoeuib.ttf", "arialbd.ttf"] if bold else ["DejaVuSans.ttf", "segoeui.ttf", "arial.ttf"]
    )
    # Пробуем каждый шрифт.
    for name in candidates:
        # Шрифт может отсутствовать — тогда просто пробуем следующий.
        try:
            # Pillow ищет шрифт в системных папках.
            return ImageFont.truetype(name, size)
        # Нет такого шрифта.
        except OSError:
            continue
    # Крайний случай — встроенный шрифт Pillow.
    return ImageFont.load_default()


def make_wizard_image(width: int, height: int) -> Image.Image:
    """Большая картинка мастера: тёмный градиент, фиолетовое свечение, значок и название."""
    # Рисуем в увеличенном масштабе.
    w, h = width * SUPERSAMPLE, height * SUPERSAMPLE
    # Фон: от цвета панелей вверху к фону программы внизу.
    canvas = vertical_gradient((w, h), SURFACE, BACKGROUND).convert("RGBA")
    # Слой мягкого свечения за значком.
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # Центр значка — на 36 % высоты.
    cy = h * 0.36
    # Радиус свечения.
    gr = w * 0.55
    # Полупрозрачный фиолетовый круг.
    ImageDraw.Draw(glow).ellipse([w / 2 - gr, cy - gr, w / 2 + gr, cy + gr], fill=ACCENT + (90,))
    # Сильно размываем — получается мягкое сияние.
    glow = glow.filter(ImageFilter.GaussianBlur(w * 0.18))
    # Накладываем свечение на фон.
    canvas = Image.alpha_composite(canvas, glow)
    # Размер значка — 52 % ширины.
    icon_size = round(w * 0.52)
    # Сам значок (рисуем сразу в увеличенном размере).
    icon = make_icon_image(icon_size)
    # Ставим значок по центру по горизонтали.
    canvas.alpha_composite(icon, (round((w - icon_size) / 2), round(cy - icon_size / 2)))
    # Инструмент рисования текста.
    draw = ImageDraw.Draw(canvas)
    # Крупный жирный шрифт для названия (размер подбираем от ширины картинки).
    title_font = load_font(round(w * 0.092), bold=True)
    # Шрифт подписи.
    sub_font = load_font(round(w * 0.062))
    # Название программы под значком.
    draw.text((w / 2, cy + icon_size * 0.72), "Auto-Compiler", font=title_font, fill=TEXT, anchor="mm")
    # Подпись: что делает программа.
    draw.text((w / 2, cy + icon_size * 0.72 + w * 0.13), "Python  →  .exe", font=sub_font, fill=ACCENT_LIGHT, anchor="mm")
    # Тонкая фиолетовая полоса внизу — акцент в стиле программы.
    draw.rectangle([0, h - round(h * 0.012), w, h], fill=ACCENT)
    # Уменьшаем до нужного размера и убираем прозрачность (фон полностью непрозрачный).
    return canvas.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")


def make_small_image(size: int) -> Image.Image:
    """Маленькая картинка в углу мастера: значок на прозрачном фоне с небольшими полями."""
    # Прозрачный холст нужного размера.
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Значок занимает 88 % (по краям — небольшие поля).
    inner = round(size * 0.88)
    # Рисуем значок.
    icon = make_icon_image(inner)
    # Ставим по центру.
    canvas.alpha_composite(icon, ((size - inner) // 2, (size - inner) // 2))
    # Готово.
    return canvas


def main() -> None:
    """Создать все файлы оформления."""
    # Создаём папку assets (если её ещё нет).
    ASSETS.mkdir(parents=True, exist_ok=True)
    # Значок максимального размера — из него Pillow сделает все остальные размеры .ico.
    icon = make_icon_image(256)
    # Сохраняем .ico со всеми размерами сразу.
    icon.save(HERE / "autocompiler.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    # Сообщаем о готовом файле.
    print("autocompiler.ico")
    # Большие картинки мастера для всех масштабов экрана.
    for width, height in WIZARD_SIZES:
        # Имя файла с размером (Inno Setup выберет лучший по размеру).
        name = f"wizard-{width}x{height}.png"
        # Рисуем и сохраняем с максимальным сжатием.
        make_wizard_image(width, height).save(ASSETS / name, optimize=True)
        # Сообщаем о готовом файле.
        print(f"assets/{name}")
    # Маленькие картинки мастера.
    for size in SMALL_SIZES:
        # Имя файла с размером.
        name = f"wizard-small-{size}.png"
        # Рисуем и сохраняем.
        make_small_image(size).save(ASSETS / name, optimize=True)
        # Сообщаем о готовом файле.
        print(f"assets/{name}")


# Запуск напрямую: python installer/make_assets.py
if __name__ == "__main__":
    # Создаём оформление.
    main()
