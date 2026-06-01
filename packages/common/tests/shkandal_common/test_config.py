from shkandal_common.config import BaseServiceConfig


class ExampleConfig(BaseServiceConfig):
    service_name: str = "default"


def test_init_settings_override_defaults() -> None:
    settings = ExampleConfig(service_name="backend")

    assert settings.service_name == "backend"
