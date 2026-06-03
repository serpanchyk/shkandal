from pathlib import Path

from shkandal_common.config import BaseServiceConfig


class ExampleConfig(BaseServiceConfig):
    service_name: str = "default"


def test_init_settings_override_defaults() -> None:
    settings = ExampleConfig(service_name="backend")

    assert settings.service_name == "backend"


def test_loads_yaml_config(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.yaml").write_text("service_name: backend\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    settings = ExampleConfig()

    assert settings.service_name == "backend"
