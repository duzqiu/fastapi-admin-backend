"""个人网站访问密码的哈希与校验。

bcrypt 只处理前 72 个字节，中文一个字占 3 字节，直接哈希长中文密码会被截断。
这里先用 SHA-256 把任意长度密码压成 64 个 ASCII 字符，再交给 bcrypt；
新哈希带 `sha256$` 前缀，老数据（没有前缀）仍按原来的 bcrypt 方式校验。
"""

import hashlib

from app.core.security import hash_password, verify_password

_SITE_PASSWORD_PREFIX = "sha256$"


def _prehash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_site_password(password: str) -> str:
    """生成支持中文 / 长密码的站点访问密码哈希。"""
    return f"{_SITE_PASSWORD_PREFIX}{hash_password(_prehash(password))}"


def verify_site_password(password: str, stored_hash: str) -> bool:
    """校验站点密码；兼容升级前没有前缀的 bcrypt 哈希。"""
    if not stored_hash:
        return False
    if stored_hash.startswith(_SITE_PASSWORD_PREFIX):
        return verify_password(
            _prehash(password),
            stored_hash[len(_SITE_PASSWORD_PREFIX) :],
        )
    # 老数据：升级前直接对原文做 bcrypt
    return verify_password(password, stored_hash)


__all__ = ["hash_site_password", "verify_site_password"]
