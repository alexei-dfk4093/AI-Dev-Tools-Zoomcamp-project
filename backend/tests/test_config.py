from app.core.config import DEFAULT_OPENROUTER_MODEL, get_settings


def test_default_model_options_are_all_free(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)

    settings = get_settings()

    assert settings.openrouter_model == DEFAULT_OPENROUTER_MODEL
    assert settings.openrouter_model == "openrouter/free"
    assert all(
        model == "openrouter/free" or model.endswith(":free")
        for model in settings.openrouter_models
    )


def test_paid_environment_models_are_ignored(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENROUTER_MODEL", "z-ai/glm-5.3")
    monkeypatch.setenv(
        "OPENROUTER_MODELS",
        "z-ai/glm-5.3,google/gemma-4-31b-it:free",
    )

    settings = get_settings()

    assert settings.openrouter_model == "openrouter/free"
    assert settings.openrouter_models == (
        "openrouter/free",
        "google/gemma-4-31b-it:free",
    )
    assert "Ignoring paid OPENROUTER_MODEL" in caplog.text
    assert "Ignoring paid models in OPENROUTER_MODELS" in caplog.text
