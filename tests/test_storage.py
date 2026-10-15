"""图片存储校验测试：魔术字节、iPhone 的 HEIC / HEIF 转 JPEG。"""

import io

import pytest
from PIL import Image

from app.core.exceptions import BusinessError
from app.core.storage import heif_to_jpeg, is_heif, looks_like_image

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)
# 1x1 JPEG
JPG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffc2000b080001000101011100ffc400140001000000000000"
    "00000000000000000009ffda0008010100003f00d2cf20ffd9"
)


def _heic_bytes(size: tuple[int, int] = (48, 32)) -> bytes:
    """造一张真正的 HEIC（iPhone 相机那个格式）。"""
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()

    buffer = io.BytesIO()
    Image.new("RGB", size, (12, 34, 56)).save(buffer, format="HEIF")
    return buffer.getvalue()


def test_looks_like_image_accepts_common_formats():
    assert looks_like_image(PNG, "png")
    assert looks_like_image(JPG, "jpg")
    assert not looks_like_image(b"#!/bin/sh\necho hi", "jpg")


def test_looks_like_image_accepts_heic():
    """HEIC 靠 ISO-BMFF 的 `ftyp` + 品牌代号识别（后缀不改也能认出来）。"""
    content = _heic_bytes()
    assert content[4:8] == b"ftyp"
    assert is_heif(content)
    assert looks_like_image(content, "heic")
    assert looks_like_image(content, "heif")


def test_heif_to_jpeg_produces_real_jpeg():
    """转出来的必须是 JPEG：浏览器与 Flutter 都渲染不了 HEIC。"""
    jpeg = heif_to_jpeg(_heic_bytes())
    assert jpeg.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.format == "JPEG"
        assert image.size == (48, 32)


def test_heif_to_jpeg_rejects_broken_file():
    with pytest.raises(BusinessError):
        heif_to_jpeg(b"ftypheic" + b"\x00" * 64)
