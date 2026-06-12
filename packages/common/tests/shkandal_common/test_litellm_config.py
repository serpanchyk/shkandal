from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parents[4]
CONFIG_PATH = PROJECT_ROOT / "infra" / "litellm" / "config.yaml.example"
PUBLIC_ALIASES = {
    "shkandal-article-card",
    "shkandal-case-resolution",
    "shkandal-entity-resolution",
    "shkandal-event-resolution",
    "shkandal-case-copy-update",
    "shkandal-repair",
}
PRIMARY_MODEL = "shkandal-lapatonia-primary"
FALLBACK_MODEL = "shkandal-bedrock-fallback"


def test_litellm_aliases_share_primary_cooldown_and_fallback() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text())

    model_list = config["model_list"]
    models_by_name = {model["model_name"]: model for model in model_list}
    assert set(models_by_name) == {PRIMARY_MODEL, FALLBACK_MODEL}
    assert models_by_name[PRIMARY_MODEL]["rpm"] == 60

    router_settings = config["router_settings"]
    assert router_settings["num_retries"] == 1
    assert router_settings["retry_policy"] == {
        "BadRequestErrorRetries": 0,
        "AuthenticationErrorRetries": 0,
        "TimeoutErrorRetries": 1,
        "RateLimitErrorRetries": 0,
        "ContentPolicyViolationErrorRetries": 0,
        "InternalServerErrorRetries": 1,
    }
    assert router_settings["allowed_fails"] == 3
    assert set(router_settings["allowed_fails_policy"].values()) == {3}
    assert router_settings["cooldown_time"] == 3600
    assert router_settings["model_group_alias"] == dict.fromkeys(PUBLIC_ALIASES, PRIMARY_MODEL)
    fallbacks = {
        alias: models
        for fallback in router_settings["fallbacks"]
        for alias, models in fallback.items()
    }
    assert fallbacks == {alias: [FALLBACK_MODEL] for alias in PUBLIC_ALIASES}
