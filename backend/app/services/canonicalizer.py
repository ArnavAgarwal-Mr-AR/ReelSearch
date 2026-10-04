import re
import uuid
import hashlib
from urllib.parse import urlparse
from typing import Tuple


class CanonicalizationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


ALLOWED_HOSTS = {
    "instagram.com",
    "www.instagram.com",
}

# Regex to strictly capture Instagram Reel paths: /reel/{shortcode}/ or /reel/{shortcode}
REEL_PATH_REGEX = re.compile(r"^/reel/(?P<shortcode>[A-Za-z0-9_-]+)/?$")

# Shortcode rules: typically base64-like characters, 3 to 100 chars
SHORTCODE_REGEX = re.compile(r"^[A-Za-z0-9_-]{3,100}$")


def canonicalize_instagram_reel(raw_url: str) -> Tuple[str, str, str]:
    """
    Validates and canonicalizes an Instagram Reel URL deterministically.
    
    Returns:
        Tuple of (canonical_url, shortcode, reel_id_uuid)
        
    Raises:
        CanonicalizationError with appropriate error code and message.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise CanonicalizationError(
            code="INVALID_URL",
            message="A valid Instagram Reel URL string is required."
        )

    clean_raw = raw_url.strip()
    if len(clean_raw) > 2048:
        raise CanonicalizationError(
            code="URL_TOO_LONG",
            message="Supplied URL exceeds maximum supported length."
        )

    try:
        parsed = urlparse(clean_raw)
    except Exception as e:
        raise CanonicalizationError(
            code="MALFORMED_URL",
            message=f"Failed to parse URL: {str(e)}"
        )

    # 1. Scheme normalization: only http/https
    if parsed.scheme.lower() not in {"http", "https"}:
        raise CanonicalizationError(
            code="INVALID_SCHEME",
            message="Only HTTP and HTTPS protocols are accepted."
        )

    # 2. Reject credentials or custom ports (SSRF protection)
    if parsed.username or parsed.password:
        raise CanonicalizationError(
            code="CREDENTIALS_IN_URL",
            message="URLs containing user credentials are not allowed."
        )

    if parsed.port and parsed.port not in {80, 443}:
        raise CanonicalizationError(
            code="INVALID_PORT",
            message="Custom ports are not permitted."
        )

    # 3. Host validation: exact match against allowed set
    if not parsed.hostname:
        raise CanonicalizationError(
            code="MISSING_HOSTNAME",
            message="URL is missing a valid hostname."
        )

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname not in ALLOWED_HOSTS:
        raise CanonicalizationError(
            code="INVALID_HOST",
            message="Only public Instagram domains (instagram.com, www.instagram.com) are supported."
        )

    # 4. Path validation: must match /reel/{shortcode}/
    path = parsed.path
    match = REEL_PATH_REGEX.fullmatch(path)
    if not match:
        raise CanonicalizationError(
            code="INVALID_REEL_PATH",
            message="URL does not point to a valid Instagram Reel path (/reel/{shortcode}/)."
        )

    shortcode = match.group("shortcode")

    # 5. Shortcode character and length validation
    if not SHORTCODE_REGEX.fullmatch(shortcode):
        raise CanonicalizationError(
            code="INVALID_SHORTCODE",
            message="Reel shortcode contains invalid characters or length."
        )

    # 6. Canonical URL generation: https, www.instagram.com, trailing slash, no query, no fragment
    canonical_url = f"https://www.instagram.com/reel/{shortcode}/"

    # 7. Deterministic UUID from canonical URL (RFC 4122 UUIDv5)
    reel_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_url))

    return canonical_url, shortcode, reel_id
