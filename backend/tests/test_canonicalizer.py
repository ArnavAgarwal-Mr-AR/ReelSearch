import pytest
from app.services.canonicalizer import canonicalize_instagram_reel, CanonicalizationError


class TestInstagramCanonicalizer:
    def test_standard_reel_url(self):
        url = "https://www.instagram.com/reel/Cxyz123/"
        canonical, shortcode, reel_id = canonicalize_instagram_reel(url)
        assert canonical == "https://www.instagram.com/reel/Cxyz123/"
        assert shortcode == "Cxyz123"
        assert len(reel_id) == 36  # Valid UUID format

    def test_url_without_trailing_slash(self):
        url = "https://www.instagram.com/reel/Cxyz123"
        canonical, shortcode, _ = canonicalize_instagram_reel(url)
        assert canonical == "https://www.instagram.com/reel/Cxyz123/"
        assert shortcode == "Cxyz123"

    def test_strip_query_parameters(self):
        variants = [
            "https://www.instagram.com/reel/Cxyz123/?utm_source=ig_web_copy_link",
            "https://www.instagram.com/reel/Cxyz123/?igsh=MWQ1ZGUxMzBkMA==",
            "https://www.instagram.com/reel/Cxyz123/?utm_medium=share_sheet&utm_campaign=reel",
        ]
        expected_canonical = "https://www.instagram.com/reel/Cxyz123/"
        for v in variants:
            canonical, shortcode, _ = canonicalize_instagram_reel(v)
            assert canonical == expected_canonical
            assert shortcode == "Cxyz123"

    def test_strip_fragment(self):
        url = "https://www.instagram.com/reel/Cxyz123/#comments"
        canonical, shortcode, _ = canonicalize_instagram_reel(url)
        assert canonical == "https://www.instagram.com/reel/Cxyz123/"
        assert shortcode == "Cxyz123"

    def test_scheme_normalization(self):
        url = "http://instagram.com/reel/Cxyz123/"
        canonical, shortcode, _ = canonicalize_instagram_reel(url)
        assert canonical == "https://www.instagram.com/reel/Cxyz123/"

    def test_identity_determinism(self):
        u1 = "https://www.instagram.com/reel/Cxyz123/?utm_source=a"
        u2 = "http://instagram.com/reel/Cxyz123/#section"
        _, _, id1 = canonicalize_instagram_reel(u1)
        _, _, id2 = canonicalize_instagram_reel(u2)
        assert id1 == id2  # Identical canonical identity

    def test_reject_subdomain_takeover_or_attacker_host(self):
        malicious_urls = [
            "https://instagram.com.evil.example/reel/Cxyz123/",
            "https://attackerinstagram.com/reel/Cxyz123/",
            "https://www.evil-instagram.com/reel/Cxyz123/",
            "https://google.com/reel/Cxyz123/"
        ]
        for bad_url in malicious_urls:
            with pytest.raises(CanonicalizationError) as exc_info:
                canonicalize_instagram_reel(bad_url)
            assert exc_info.value.code == "INVALID_HOST"

    def test_reject_non_reel_paths(self):
        non_reels = [
            "https://www.instagram.com/p/Cxyz123/",          # standard post
            "https://www.instagram.com/stories/username/123", # stories
            "https://www.instagram.com/natgeo/",            # profile
            "https://www.instagram.com/explore/",           # explore
        ]
        for bad_url in non_reels:
            with pytest.raises(CanonicalizationError) as exc_info:
                canonicalize_instagram_reel(bad_url)
            assert exc_info.value.code == "INVALID_REEL_PATH"

    def test_reject_credentials_and_ports(self):
        bad_urls = [
            "https://user:password@www.instagram.com/reel/Cxyz123/",
            "https://www.instagram.com:8080/reel/Cxyz123/",
        ]
        for bad_url in bad_urls:
            with pytest.raises(CanonicalizationError):
                canonicalize_instagram_reel(bad_url)
