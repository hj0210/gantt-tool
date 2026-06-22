"""모델사별 LLM 클라이언트 래퍼.

WBS 파싱은 텍스트 프롬프트 + (선택) 이미지 1장을 보내 JSON 문자열을 받는
단순한 인터페이스만 필요하므로, 각 프로바이더 SDK를 lazy import 해서
공통 함수(text_completion / vision_completion / validate_key)로 감싼다.
SDK가 설치되지 않은 프로바이더를 고르면 설치 안내 메시지를 던진다.
"""
from __future__ import annotations

import base64

import config


class ProviderError(Exception):
    pass


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

def _anthropic_client(api_key: str):
    try:
        from anthropic import Anthropic
    except ImportError:
        raise ProviderError("anthropic 패키지가 설치되어 있지 않습니다. pip install anthropic")
    return Anthropic(api_key=api_key)


def _anthropic_validate(api_key: str) -> tuple[bool, str]:
    import anthropic

    client = _anthropic_client(api_key)
    try:
        client.messages.create(
            model=config.PROVIDERS["anthropic"]["model"],
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, ""
    except anthropic.AuthenticationError:
        return False, "API 키가 유효하지 않습니다."
    except anthropic.PermissionDeniedError as e:
        return False, f"모델 접근 권한이 없습니다: {e}"
    except anthropic.APIConnectionError:
        return False, "네트워크 연결을 확인해주세요."
    except Exception as e:  # noqa: BLE001
        return False, f"키 검증 중 오류: {e}"


def _anthropic_text(api_key: str, system: str, user_text: str) -> str:
    client = _anthropic_client(api_key)
    resp = client.messages.create(
        model=config.PROVIDERS["anthropic"]["model"],
        max_tokens=config.LLM_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _anthropic_vision(api_key: str, system: str, image_bytes: bytes, media_type: str, instruction: str) -> str:
    client = _anthropic_client(api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    resp = client.messages.create(
        model=config.PROVIDERS["anthropic"]["model"],
        max_tokens=config.LLM_MAX_TOKENS,
        system=system,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": instruction},
                ],
            }
        ],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# ---------------------------------------------------------------------------
# OpenAI (GPT)
# ---------------------------------------------------------------------------

def _openai_client(api_key: str):
    try:
        from openai import OpenAI
    except ImportError:
        raise ProviderError("openai 패키지가 설치되어 있지 않습니다. pip install openai")
    return OpenAI(api_key=api_key)


def _openai_validate(api_key: str) -> tuple[bool, str]:
    import openai

    client = _openai_client(api_key)
    try:
        client.chat.completions.create(
            model=config.PROVIDERS["openai"]["model"],
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, ""
    except openai.AuthenticationError:
        return False, "API 키가 유효하지 않습니다."
    except openai.PermissionDeniedError as e:
        return False, f"모델 접근 권한이 없습니다: {e}"
    except openai.APIConnectionError:
        return False, "네트워크 연결을 확인해주세요."
    except Exception as e:  # noqa: BLE001
        return False, f"키 검증 중 오류: {e}"


def _openai_text(api_key: str, system: str, user_text: str) -> str:
    client = _openai_client(api_key)
    resp = client.chat.completions.create(
        model=config.PROVIDERS["openai"]["model"],
        max_tokens=config.LLM_MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    )
    return resp.choices[0].message.content or ""


def _openai_vision(api_key: str, system: str, image_bytes: bytes, media_type: str, instruction: str) -> str:
    client = _openai_client(api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:{media_type};base64,{b64}"
    resp = client.chat.completions.create(
        model=config.PROVIDERS["openai"]["model"],
        max_tokens=config.LLM_MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Google (Gemini)
# ---------------------------------------------------------------------------

def _gemini_model(api_key: str, system: str):
    try:
        import google.generativeai as genai
    except ImportError:
        raise ProviderError(
            "google-generativeai 패키지가 설치되어 있지 않습니다. pip install google-generativeai"
        )
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(config.PROVIDERS["google"]["model"], system_instruction=system)


def _gemini_validate(api_key: str) -> tuple[bool, str]:
    try:
        model = _gemini_model(api_key, "ping test")
        model.generate_content("ping", generation_config={"max_output_tokens": 1})
        return True, ""
    except ProviderError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "API_KEY_INVALID" in msg or "API key not valid" in msg:
            return False, "API 키가 유효하지 않습니다."
        return False, f"키 검증 중 오류: {e}"


def _gemini_text(api_key: str, system: str, user_text: str) -> str:
    model = _gemini_model(api_key, system)
    resp = model.generate_content(user_text, generation_config={"max_output_tokens": config.LLM_MAX_TOKENS})
    return resp.text


def _gemini_vision(api_key: str, system: str, image_bytes: bytes, media_type: str, instruction: str) -> str:
    model = _gemini_model(api_key, system)
    resp = model.generate_content(
        [{"mime_type": media_type, "data": image_bytes}, instruction],
        generation_config={"max_output_tokens": config.LLM_MAX_TOKENS},
    )
    return resp.text


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

_BACKENDS = {
    "anthropic": {"validate": _anthropic_validate, "text": _anthropic_text, "vision": _anthropic_vision},
    "openai": {"validate": _openai_validate, "text": _openai_text, "vision": _openai_vision},
    "google": {"validate": _gemini_validate, "text": _gemini_text, "vision": _gemini_vision},
}


def validate_key(provider: str, api_key: str) -> tuple[bool, str]:
    if provider not in _BACKENDS:
        return False, f"알 수 없는 프로바이더: {provider}"
    try:
        return _BACKENDS[provider]["validate"](api_key)
    except ProviderError as e:
        return False, str(e)


def text_completion(provider: str, api_key: str, system: str, user_text: str) -> str:
    if provider not in _BACKENDS:
        raise ProviderError(f"알 수 없는 프로바이더: {provider}")
    return _BACKENDS[provider]["text"](api_key, system, user_text)


def vision_completion(provider: str, api_key: str, system: str, image_bytes: bytes, media_type: str, instruction: str) -> str:
    if provider not in _BACKENDS:
        raise ProviderError(f"알 수 없는 프로바이더: {provider}")
    return _BACKENDS[provider]["vision"](api_key, system, image_bytes, media_type, instruction)
