"""bin/download_from_huggingface.py: pinned revision, languages without a model."""

import os

import pytest
from click.testing import CliRunner

from bin import download_from_huggingface as script


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """A fake snapshot_download that serves an en and a de model, and records
    what it was asked for."""
    monkeypatch.chdir(tmp_path)
    calls = []

    def snapshot_download(repo_id, allow_patterns, cache_dir, revision=None):
        calls.append({"repo_id": repo_id, "revision": revision})
        snapshot = tmp_path / "snapshot"
        for lang in ("en", "de"):
            (snapshot / lang).mkdir(parents=True, exist_ok=True)
            (snapshot / lang / "model.safetensors").write_text("weights")
        return str(snapshot)

    monkeypatch.setattr(script, "snapshot_download", snapshot_download)
    return calls


def test_downloads_the_pinned_revision(hub):
    result = CliRunner().invoke(script.download, ["--lang", "en"])

    assert result.exit_code == 0, result.output
    assert hub == [
        {"repo_id": "witty-works/setfit-context-checker", "revision": script.REVISION}
    ]
    assert os.path.isfile("models/context_aware_model/en/model.safetensors")

