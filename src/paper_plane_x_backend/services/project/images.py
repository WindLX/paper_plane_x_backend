"""Project 图片文件校验与转换服务.

项目沙箱允许保存 PNG/JPEG/WebP/GIF/SVG 图片。上传时按真实内容校验，而不是只看扩展名；
SVG 必须是静态自包含文档，不能包含脚本、事件处理器、外部资源、DTD、实体或 foreignObject。
导出 DOCX/PDF 时，把 Pandoc 渲染不一致的格式统一转换为 PNG：WebP/GIF 取首帧，
SVG 通过 rsvg-convert 以 3 倍比例栅格化。
"""

import base64
import binascii
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Literal, Protocol, cast
from xml.etree import ElementTree

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException
from PIL import Image, UnidentifiedImageError
from tinycss2 import (
    parse_component_value_list as _parse_css_tokens,  # pyright: ignore[reportUnknownVariableType]
)

logger = logging.getLogger(__name__)

ImageKind = Literal["png", "jpeg", "webp", "gif", "svg"]

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
)

IMAGE_CONTENT_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}

_EXTENSION_KINDS: dict[str, ImageKind] = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".gif": "gif",
    ".svg": "svg",
}

_KIND_FORMATS: dict[ImageKind, str] = {
    "png": "PNG",
    "jpeg": "JPEG",
    "webp": "WEBP",
    "gif": "GIF",
}

_SVG_FORBIDDEN_ELEMENTS: frozenset[str] = frozenset(
    {
        "script",
        "foreignobject",
        "animate",
        "animatemotion",
        "animatetransform",
        "set",
        "discard",
    }
)

SVG_PNG_SCALE = 3


class ImageValidationError(Exception):
    """图片内容校验或转换失败。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class _CssNode(Protocol):
    type: str


class _CssValue(_CssNode, Protocol):
    value: str


class _CssFunction(_CssNode, Protocol):
    lower_name: str
    arguments: list[_CssNode]


class _CssBlock(_CssNode, Protocol):
    content: list[_CssNode]


# tinycss2 does not annotate its AST. These protocols describe the documented
# token variants only at the parser boundary, including CSS escape decoding.
_parse_css = cast(Callable[[str], list[_CssNode]], _parse_css_tokens)


def is_image_extension(extension: str) -> bool:
    """判断扩展名是否为受支持的图片类型。"""
    return extension.lower() in IMAGE_EXTENSIONS


def image_content_type(extension: str) -> str | None:
    """返回图片扩展名对应的 MIME 类型。"""
    return IMAGE_CONTENT_TYPES.get(extension.lower())


def sniff_image_kind(content: bytes) -> ImageKind | None:
    """按文件头识别图片真实类型，无法识别时返回 None。"""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    if _looks_like_svg(content):
        return "svg"
    return None


def _looks_like_svg(content: bytes) -> bool:
    head = content.lstrip()
    if head[:3] == b"\xef\xbb\xbf":
        head = head[3:].lstrip()
    return (
        head.startswith(b"<?xml")
        or head.startswith(b"<svg")
        or head.startswith(b"<!--")
    )


def validate_image(extension: str, content: bytes) -> None:
    """校验图片真实内容与扩展名一致.

    Raises:
        ImageValidationError: 内容无法识别、与扩展名不符、或 SVG 不是静态自包含文档。
    """
    expected = _EXTENSION_KINDS.get(extension.lower())
    if expected is None:
        raise ImageValidationError(
            "unsupported_image_type",
            f"Unsupported image extension: {extension}",
        )
    detected = sniff_image_kind(content)
    if detected is None:
        raise ImageValidationError(
            "invalid_image_content",
            f"File content is not a recognized image: {extension}",
        )
    if detected != expected:
        raise ImageValidationError(
            "image_content_mismatch",
            (
                f"Image content ({detected}) does not match extension "
                f"{extension} ({expected})"
            ),
        )
    if expected == "svg":
        _validate_static_svg(content)
        return
    _validate_raster_image(content, expected, extension)


def _validate_raster_image(content: bytes, kind: ImageKind, extension: str) -> None:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
            detected_format = image.format
    except Image.DecompressionBombError as exc:
        raise ImageValidationError(
            "image_too_large",
            f"Image exceeds the supported pixel budget: {extension}",
            413,
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageValidationError(
            "invalid_image_content",
            f"Failed to decode image: {extension}",
        ) from exc
    if detected_format != _KIND_FORMATS[kind]:
        raise ImageValidationError(
            "image_content_mismatch",
            (
                f"Image content ({detected_format}) does not match extension "
                f"{extension} ({_KIND_FORMATS[kind]})"
            ),
        )


def _validate_static_svg(content: bytes) -> None:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImageValidationError(
            "invalid_image_content",
            "SVG is not valid UTF-8 text",
        ) from exc
    _reject_svg_declarations(text)
    try:
        root = DefusedElementTree.fromstring(content)
    except DefusedXmlException as exc:
        raise ImageValidationError(
            "svg_forbidden_markup",
            f"SVG uses forbidden XML markup: {type(exc).__name__}",
        ) from exc
    except ElementTree.ParseError as exc:
        raise ImageValidationError(
            "invalid_image_content",
            f"Invalid SVG document: {exc}",
        ) from exc

    if _local_name(root.tag) != "svg":
        raise ImageValidationError(
            "invalid_image_content",
            f"SVG root element must be <svg>, got <{_local_name(root.tag)}>",
        )

    for element in root.iter():
        name = _local_name(element.tag)
        if name in _SVG_FORBIDDEN_ELEMENTS:
            raise ImageValidationError(
                "svg_forbidden_element",
                f"SVG contains forbidden element: <{name}>",
            )
        for attribute, value in element.attrib.items():
            _check_svg_attribute(_local_name(attribute), value)
        if name == "style" and element.text:
            validate_self_contained_css(element.text)


def _reject_svg_declarations(text: str) -> None:
    lowered = text.lower()
    for marker in ("<!doctype", "<!entity"):
        if marker in lowered:
            raise ImageValidationError(
                "svg_forbidden_markup",
                f"SVG contains forbidden markup: {marker}>",
            )
    cursor = 0
    while True:
        index = text.find("<?", cursor)
        if index < 0:
            return
        head = text[index : index + 5]
        following = text[index + 5 : index + 6]
        if head != "<?xml" or following not in (" ", "?"):
            raise ImageValidationError(
                "svg_external_resource",
                "SVG contains a processing instruction",
            )
        cursor = index + 2


def _check_svg_attribute(attribute: str, value: str) -> None:
    if attribute.startswith("on") and len(attribute) > 2:
        raise ImageValidationError(
            "svg_event_handler",
            f"SVG contains event handler attribute: {attribute}",
        )
    if attribute == "href":
        _check_svg_resource(value)
    # Resource functions also occur in presentation attributes such as fill,
    # stroke, filter and clip-path, not only in inline style declarations.
    validate_self_contained_css(value)


def _check_svg_resource(value: str) -> None:
    target = value.strip()
    if target.startswith("#"):
        return
    embedded = {
        "data:image/png;base64": ".png",
        "data:image/jpeg;base64": ".jpg",
        "data:image/webp;base64": ".webp",
        "data:image/gif;base64": ".gif",
    }
    header, separator, payload = target.partition(",")
    if separator and header.lower() in embedded:
        try:
            content = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ImageValidationError(
                "invalid_image_content", "SVG embedded image is not valid base64"
            ) from exc
        validate_image(embedded[header.lower()], content)
        return
    raise ImageValidationError(
        "svg_external_resource",
        f"SVG resource must be a fragment or embedded raster image: {target}",
    )


def validate_self_contained_css(value: str) -> None:
    """Reject CSS fetches; allow fragment and verified embedded raster resources."""
    pending = _parse_css(value)
    while pending:
        token = pending.pop()
        if token.type == "url":
            _check_svg_resource(cast(_CssValue, token).value)
        elif (
            token.type == "at-keyword"
            and cast(_CssValue, token).value.lower() == "import"
        ):
            raise ImageValidationError(
                "svg_external_resource", "SVG CSS contains @import"
            )
        elif token.type == "function":
            function = cast(_CssFunction, token)
            if function.lower_name == "url":
                arguments = [
                    argument
                    for argument in function.arguments
                    if argument.type not in ("whitespace", "comment")
                ]
                if len(arguments) != 1 or arguments[0].type != "string":
                    raise ImageValidationError(
                        "svg_external_resource", "Invalid SVG CSS resource"
                    )
                _check_svg_resource(cast(_CssValue, arguments[0]).value)
            else:
                pending.extend(function.arguments)
        elif token.type in ("{} block", "[] block", "() block"):
            pending.extend(cast(_CssBlock, token).content)
        elif token.type == "error":
            raise ImageValidationError(
                "svg_external_resource", "Invalid SVG CSS syntax"
            )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def raster_to_png(content: bytes) -> bytes:
    """把动图或非 PNG 位图转换为 PNG，动图只取首帧。"""
    try:
        with Image.open(BytesIO(content)) as image:
            image.seek(0)
            buffer = BytesIO()
            image.convert("RGBA").save(buffer, format="PNG")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageValidationError(
            "image_conversion_failed",
            f"Failed to convert image to PNG: {exc}",
            500,
        ) from exc
    return buffer.getvalue()


def svg_to_png(content: bytes, *, scale: int = SVG_PNG_SCALE) -> bytes:
    """通过 rsvg-convert 把 SVG 栅格化为 PNG。"""
    executable = shutil.which("rsvg-convert")
    if executable is None:
        raise ImageValidationError(
            "rsvg_not_available",
            "rsvg-convert is required to export SVG images",
            500,
        )
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "input.svg"
        target = Path(tmpdir) / "output.png"
        source.write_bytes(content)
        command = [executable, "--zoom", str(scale), "-o", str(target), str(source)]
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("rsvg-convert failed: stderr=%s", exc.stderr)
            raise ImageValidationError(
                "image_conversion_failed",
                f"rsvg-convert failed: {exc.stderr or 'unknown error'}",
                500,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ImageValidationError(
                "image_conversion_failed",
                "rsvg-convert timeout (60s)",
                500,
            ) from exc
        return target.read_bytes()
