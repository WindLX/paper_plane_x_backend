import shutil
from io import BytesIO

import pytest
from PIL import Image

from paper_plane_x_backend.services.project.images import (
    ImageValidationError,
    image_content_type,
    is_image_extension,
    raster_to_png,
    sniff_image_kind,
    svg_to_png,
    validate_image,
)


def _raster(fmt: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (12, 34, 56)).save(buffer, format=fmt)
    return buffer.getvalue()


def _animated_gif() -> bytes:
    buffer = BytesIO()
    first = Image.new("RGB", (4, 4), (255, 0, 0))
    second = Image.new("RGB", (4, 4), (0, 0, 255))
    first.save(
        buffer, format="GIF", save_all=True, append_images=[second], duration=100
    )
    return buffer.getvalue()


_STATIC_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<circle cx="5" cy="5" r="4" fill="red"/></svg>'
)

requires_rsvg = pytest.mark.skipif(
    shutil.which("rsvg-convert") is None,
    reason="rsvg-convert is not installed",
)


@pytest.mark.parametrize(
    "fragment",
    [
        '<rect fill="url(https://example.invalid/a.svg)"/>',
        '<rect stroke="url(https://example.invalid/a.svg)"/>',
        '<rect filter="url(https://example.invalid/a.svg)"/>',
        "<style>rect {fill: u\\72l(https://example.invalid/a.svg)}</style>",
        '<style>@\\69mport "https://example.invalid/a.css";</style>',
        '<image href="data:image/svg+xml;base64,PHN2Zz4="/>',
        '<animate attributeName="fill" values="red;blue"/>',
        '<set attributeName="href" to="https://example.invalid/a.svg"/>',
    ],
)
def test_svg_static_policy_covers_presentation_attributes_and_css_escapes(fragment):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg">{fragment}</svg>'.encode()
    with pytest.raises(ImageValidationError):
        validate_image(".svg", svg)


def test_svg_accepts_internal_clip_paths_and_embedded_raster():
    import base64

    image = base64.b64encode(_raster("PNG")).decode()
    svg = f'<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="clip"><rect width="4" height="4"/></clipPath></defs><image clip-path="url(#clip)" href="data:image/png;base64,{image}"/></svg>'
    validate_image(".svg", svg.encode())


def test_sniff_and_validate_supported_formats() -> None:
    cases = {
        ".png": _raster("PNG"),
        ".jpg": _raster("JPEG"),
        ".jpeg": _raster("JPEG"),
        ".webp": _raster("WEBP"),
        ".gif": _raster("GIF"),
        ".svg": _STATIC_SVG.encode(),
    }

    for extension, content in cases.items():
        validate_image(extension, content)

    assert sniff_image_kind(cases[".png"]) == "png"
    assert sniff_image_kind(cases[".jpg"]) == "jpeg"
    assert sniff_image_kind(cases[".webp"]) == "webp"
    assert sniff_image_kind(cases[".gif"]) == "gif"
    assert sniff_image_kind(cases[".svg"]) == "svg"
    assert sniff_image_kind(b"not an image") is None


def test_image_extension_helpers() -> None:
    assert is_image_extension(".PNG") is True
    assert is_image_extension(".md") is False
    assert image_content_type(".jpeg") == "image/jpeg"
    assert image_content_type(".svg") == "image/svg+xml"
    assert image_content_type(".txt") is None


def test_validate_image_rejects_content_extension_mismatch() -> None:
    with pytest.raises(ImageValidationError) as exc_info:
        validate_image(".jpg", _raster("PNG"))

    assert exc_info.value.code == "image_content_mismatch"
    assert exc_info.value.status_code == 400


def test_validate_image_rejects_non_image_bytes() -> None:
    with pytest.raises(ImageValidationError) as exc_info:
        validate_image(".png", b"definitely not a png")

    assert exc_info.value.code == "invalid_image_content"


def test_validate_image_rejects_unsupported_extension() -> None:
    with pytest.raises(ImageValidationError) as exc_info:
        validate_image(".bmp", _raster("PNG"))

    assert exc_info.value.code == "unsupported_image_type"


@pytest.mark.parametrize(
    "payload",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil/a.png"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<use xlink:href="https://evil/a.svg#x"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]>'
        '<svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        '<?xml-stylesheet href="https://evil/x.css"?>'
        '<svg xmlns="http://www.w3.org/2000/svg"/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://evil/x)"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://evil/x.css);</style></svg>',
    ],
)
def test_validate_svg_rejects_non_static_documents(payload: str) -> None:
    with pytest.raises(ImageValidationError) as exc_info:
        validate_image(".svg", payload.encode())

    assert exc_info.value.code in {
        "svg_forbidden_element",
        "svg_event_handler",
        "svg_external_resource",
        "svg_forbidden_markup",
        "invalid_image_content",
    }


def test_validate_svg_allows_fragment_and_data_references() -> None:
    import base64

    image = base64.b64encode(_raster("PNG")).decode()
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<defs><linearGradient id="g"/></defs>'
        '<use xlink:href="#g"/>'
        f'<image href="data:image/png;base64,{image}"/>'
        "</svg>"
    )

    validate_image(".svg", payload.encode())


def test_raster_to_png_uses_first_frame_of_animated_gif() -> None:
    converted = raster_to_png(_animated_gif())

    with Image.open(BytesIO(converted)) as image:
        assert image.format == "PNG"
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)


@requires_rsvg
def test_svg_to_png_scales_by_three() -> None:
    converted = svg_to_png(_STATIC_SVG.encode())

    with Image.open(BytesIO(converted)) as image:
        assert image.size == (30, 30)
