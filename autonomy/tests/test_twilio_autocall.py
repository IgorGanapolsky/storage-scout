from __future__ import annotations

from autonomy.tools.twilio_autocall import (
    load_twilio_config,
    map_twilio_call_to_outcome,
    normalize_us_phone_e164,
)


def test_normalize_us_phone_e164() -> None:
    assert normalize_us_phone_e164("") is None
    assert normalize_us_phone_e164("954-621-1439") == "+19546211439"
    assert normalize_us_phone_e164("(954) 621-1439") == "+19546211439"
    assert normalize_us_phone_e164("+1 (954) 621-1439") == "+19546211439"
    assert normalize_us_phone_e164("1 954 621 1439") == "+19546211439"
    assert normalize_us_phone_e164("9546211439") == "+19546211439"
    assert normalize_us_phone_e164("011 954 621 1439") is None


def test_map_twilio_call_to_outcome() -> None:
    assert map_twilio_call_to_outcome({"status": "no-answer"})[0] == "no_answer"
    assert map_twilio_call_to_outcome({"status": "busy"})[0] == "no_answer"
    assert map_twilio_call_to_outcome({"status": "failed", "error_code": 21211})[0] == "wrong_number"
    assert map_twilio_call_to_outcome({"status": "failed"})[0] == "no_answer"
    assert map_twilio_call_to_outcome({"status": "completed", "answered_by": "machine_start"})[0] == "voicemail"
    assert map_twilio_call_to_outcome({"status": "completed", "answered_by": "human"})[0] == "spoke"
    assert map_twilio_call_to_outcome({"status": "completed"})[0] == "spoke"


def test_load_twilio_config_requires_e164_from_number() -> None:
    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "9546211439",  # invalid (missing +)
    }
    assert load_twilio_config(env) is None

    env["TWILIO_FROM_NUMBER"] = "+19546211439"
    cfg = load_twilio_config(env)
    assert cfg is not None
    assert cfg.from_number == "+19546211439"

