import os

from zhiraf.ui import theme


def test_palette_is_the_spec_palette():
    assert theme.COLORS["error"] == "#b9524a" and theme.COLORS["check"] == "#d9a521"
    assert theme.COLORS["fixed"] == "#3f9a4e" and theme.COLORS["skipped"] == "#8792a2"
    assert theme.COLORS["sky"] == "#56708f" and theme.COLORS["paper"] == "#f6f3ec"
    assert theme.COLORS["ink"] == "#26303b" and theme.COLORS["moon"] == "#fbf7e9"
    assert len(theme.COLORS) == 8


def test_icons_render_for_every_status(qapp):
    for name in ("error", "check", "fixed", "skipped", "help"):
        pixmap = theme.icon(name, size=18).pixmap(18, 18)
        assert not pixmap.isNull()
        image = pixmap.toImage()
        assert any(image.pixelColor(x, y).alpha() > 0 for x in range(18) for y in range(18))


def test_art_path_finds_the_giraffe():
    assert os.path.isfile(theme.art_path("start.jpg"))
    assert os.path.isfile(theme.art_path("logo.png"))


def test_status_color_and_labels():
    assert theme.status_color("error") == theme.COLORS["error"]
    assert theme.LEVEL_LABEL == {"error": "Ошибка", "check": "Проверьте"}


def test_stylesheet_uses_palette():
    assert theme.COLORS["paper"] in theme.stylesheet()
