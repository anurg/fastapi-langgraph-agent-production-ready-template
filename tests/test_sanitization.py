"""Tests for input sanitization helpers."""

import pytest

from app.utils.sanitization import (
    sanitize_dict,
    sanitize_email,
    sanitize_list,
    sanitize_string,
    validate_password_strength,
)


class TestSanitizeString:
    def test_escapes_html_so_markup_cannot_render(self) -> None:
        assert sanitize_string("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

    def test_strips_escaped_script_tags_entirely(self) -> None:
        assert sanitize_string("<script>alert(1)</script>") == ""

    def test_strips_multiline_script_bodies(self) -> None:
        assert sanitize_string("a<script>\nalert(1)\n</script>b") == "ab"

    def test_removes_null_bytes(self) -> None:
        assert "\0" not in sanitize_string("bad\0value")

    def test_coerces_non_strings(self) -> None:
        assert sanitize_string(42) == "42"  # pyright: ignore[reportArgumentType]

    def test_leaves_ordinary_text_untouched(self) -> None:
        assert sanitize_string("a normal sentence") == "a normal sentence"


class TestSanitizeEmail:
    def test_lowercases_valid_address(self) -> None:
        assert sanitize_email("User@Example.COM") == "user@example.com"

    @pytest.mark.parametrize("bad", ["not-an-email", "@example.com", "user@", "user@example", ""])
    def test_rejects_malformed_addresses(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid email format"):
            sanitize_email(bad)

    def test_rejects_address_that_only_looks_valid_before_escaping(self) -> None:
        # HTML-escaping runs first, so an embedded quote breaks the format check
        # rather than slipping through.
        with pytest.raises(ValueError):
            sanitize_email('"<script>"@example.com')


class TestSanitizeContainers:
    def test_sanitizes_nested_dict_values(self) -> None:
        result = sanitize_dict({"outer": {"inner": "<b>x</b>"}})
        assert result == {"outer": {"inner": "&lt;b&gt;x&lt;/b&gt;"}}

    def test_sanitizes_strings_inside_lists(self) -> None:
        assert sanitize_list(["<b>", 1, None]) == ["&lt;b&gt;", 1, None]

    def test_preserves_non_string_scalars(self) -> None:
        result = sanitize_dict({"n": 1, "f": 1.5, "b": True, "none": None})
        assert result == {"n": 1, "f": 1.5, "b": True, "none": None}

    def test_sanitizes_dicts_nested_in_lists(self) -> None:
        assert sanitize_list([{"k": "<i>"}]) == [{"k": "&lt;i&gt;"}]

    def test_leaves_keys_alone(self) -> None:
        # Only values are sanitized — documenting the current contract.
        assert sanitize_dict({"<key>": "v"}) == {"<key>": "v"}


class TestPasswordStrength:
    def test_accepts_a_strong_password(self) -> None:
        assert validate_password_strength("Str0ng!Pass") is True

    @pytest.mark.parametrize(
        ("password", "reason"),
        [
            ("Sh0rt!", "at least 8 characters"),
            ("lowercase1!", "uppercase letter"),
            ("UPPERCASE1!", "lowercase letter"),
            ("NoDigits!!", "at least one number"),
            ("NoSpecial123", "special character"),
        ],
    )
    def test_rejects_weak_passwords_with_a_reason(self, password: str, reason: str) -> None:
        with pytest.raises(ValueError, match=reason):
            validate_password_strength(password)
