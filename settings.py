"""사용자별 로컬 설정 파일(프로바이더별 API 키 등) 저장/로드.

Windows 기준 %LOCALAPPDATA%\\GanttTool\\config.json 에 평문 저장한다.
%APPDATA%(Roaming)가 아니라 %LOCALAPPDATA%를 쓰는 이유: Roaming 폴더는
백업/EDR 에이전트나 그룹정책에 의해 동기화되는 환경이 흔해서, API 키 같은
민감 정보가 의도치 않게 클라우드/백업 어딘가에 같이 남을 수 있다.
LOCALAPPDATA는 이 PC를 떠나지 않는 로컬 전용 캐시 영역이라 비밀값 저장에 더 적합하다.
exe로 패키징해도 사용자 계정 단위로 분리되어 저장되며, 다른 OS에서는
홈 디렉터리(~/.gantt-tool/config.json)로 대체된다.

프로바이더(Anthropic/OpenAI/Google 등)별로 키를 따로 저장하고,
마지막으로 선택한 프로바이더도 함께 기억한다.
"""
import json
import os
from pathlib import Path

import config

_APP_DIR_NAME = "GanttTool"


def _config_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path.home() / ".gantt-tool"
    return base / _APP_DIR_NAME if local_appdata else base


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _load_raw() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict) -> None:
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_provider() -> str:
    return _load_raw().get("active_provider", config.DEFAULT_PROVIDER)


def set_active_provider(provider: str) -> None:
    data = _load_raw()
    data["active_provider"] = provider
    _save_raw(data)


def load_api_key(provider: str | None = None) -> str | None:
    provider = provider or get_active_provider()
    data = _load_raw()
    return data.get("api_keys", {}).get(provider) or None


def save_api_key(provider: str, key: str) -> None:
    data = _load_raw()
    data.setdefault("api_keys", {})[provider] = key
    data["active_provider"] = provider
    _save_raw(data)


def get_config_path_str() -> str:
    return str(_config_path())


def clear_api_key(provider: str | None = None) -> None:
    """저장된 키 1개 삭제. provider=None이면 전체 키를 삭제."""
    data = _load_raw()
    if provider is None:
        data["api_keys"] = {}
    else:
        data.get("api_keys", {}).pop(provider, None)
    _save_raw(data)


def clear_all() -> None:
    """설정 파일 자체를 삭제. 개발용 키를 패키징 전 완전히 제거할 때 사용."""
    path = _config_path()
    if path.exists():
        path.unlink()
