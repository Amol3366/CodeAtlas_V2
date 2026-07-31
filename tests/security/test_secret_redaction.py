"""Secrets must not reach a provider.

Gate condition 6. This is the one Phase 7 failure that cannot be undone: a
vector can be deleted and a budget can be refunded, but a credential posted to
a third party is disclosed permanently, and the user who typed it into a `.env`
never agreed to that.

So the tests here are adversarial rather than illustrative. They ask what a real
repository contains — committed keys, private key blocks, connection strings
with passwords in them — and require that none of it survives the boundary.

The second half is the opposite failure, and it matters just as much: a detector
that fires on ordinary code would redact the repository into uselessness while
looking like it was working. `password = get_password()` is not a secret.
"""

from __future__ import annotations

import pytest

from codeatlas.semantic.redaction import PLACEHOLDER, redact

# --- what must never survive ---------------------------------------------


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("aws access key id", "AKIAIOSFODNN7EXAMPLE"),
        ("github personal token", "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"),
        ("slack bot token", "xoxb-" + "123456789012-1234567890123-abcdefghijklmnop"),
        ("openai key", "sk-" + "a" * 48),
        ("google api key", "AIza" + "SyD-1234567890abcdefghijklmnopqrstu"),
        (
            "private key block",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n-----END RSA PRIVATE KEY-----",
        ),
        (
            "connection string with password",
            "postgres://admin:hunter2@db.internal:5432/orders",
        ),
        ("assigned api key", 'API_KEY = "9f8e7d6c5b4a39281706f5e4d3c2b1a0"'),
        ("assigned password", "password: 's3cr3t-p4ssw0rd-value'"),
        ("bearer token", "Authorization: Bearer abcdef1234567890abcdef1234567890"),
    ],
)
def test_a_secret_does_not_survive_redaction(label: str, text: str) -> None:
    result = redact(text)

    assert result.redacted_count >= 1, label
    assert PLACEHOLDER in result.text, label


def test_the_secret_value_itself_is_gone_from_the_output() -> None:
    """Not merely "a placeholder appeared" — the bytes must be absent."""
    secret = "ghp_" + "z9Y8x7W6v5U4t3S2r1Q0p9O8n7M6l5K4j3I2"

    result = redact(f"token = {secret}\nprint(token)")

    assert secret not in result.text


def test_every_occurrence_is_removed_not_just_the_first() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"

    result = redact(f"{secret}\nand again {secret}\n")

    assert secret not in result.text
    assert result.redacted_count == 2


def test_a_secret_inside_a_larger_document_leaves_the_rest_readable() -> None:
    """Redaction must not destroy the chunk. An embedding of nothing but
    placeholders would be worse than not embedding the chunk at all."""
    text = (
        "def connect():\n"
        '    """Open the primary database."""\n'
        '    dsn = "postgres://admin:hunter2@db.internal:5432/orders"\n'
        "    return psycopg.connect(dsn)\n"
    )

    result = redact(text)

    assert "hunter2" not in result.text
    assert "def connect():" in result.text
    assert "Open the primary database." in result.text


def test_what_was_found_is_reported_as_kinds_never_as_values() -> None:
    """Telemetry and warnings quote this. A field holding the matched text
    would move the secret from the provider into the logs."""
    result = redact("AKIAIOSFODNN7EXAMPLE")

    assert result.kinds
    assert all(
        "AKIA" not in kind and "EXAMPLE" not in kind for kind in result.kinds
    )


# --- what must survive untouched -----------------------------------------


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("a call, not a literal", "password = get_password()"),
        ("a variable reference", "api_key = settings.api_key"),
        ("an environment read", 'token = os.environ["GITHUB_TOKEN"]'),
        ("a type annotation", "def login(password: str) -> None: ..."),
        ("a docstring mentioning secrets", '"""Never log the password."""'),
        ("a short placeholder", 'password = "changeme"'),
        ("a dsn without credentials", "postgres://db.internal:5432/orders"),
        ("prose", "The service listens on the configured port."),
        ("a hex colour", 'colour = "#a1b2c3"'),
    ],
)
def test_ordinary_code_is_left_alone(label: str, text: str) -> None:
    """A detector that fires here would redact the repository into
    uselessness while appearing to work."""
    result = redact(text)

    assert result.redacted_count == 0, label
    assert result.text == text, label


def test_text_with_no_secret_is_returned_identically() -> None:
    text = "def total_for(order):\n    return subtotal(order)\n"

    assert redact(text).text == text


def test_empty_text_is_handled() -> None:
    assert redact("").text == ""
    assert redact("").redacted_count == 0
