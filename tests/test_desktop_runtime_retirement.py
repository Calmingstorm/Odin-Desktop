"""Normal profile serving upgrades do not import or rewrite alongside state."""

from src.config.schema import load_config


def test_profile_runtime_retirement_preserves_yaml(tmp_path):
    path = tmp_path / "config.yml"
    source = "openai_codex:\n  model: gpt-5.5\n"
    path.write_text(source)
    config = load_config(path)
    assert config.openai_codex.model != "gpt-5.5"
    assert path.read_text() == source
