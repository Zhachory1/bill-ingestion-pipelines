"""CLI command tests using Typer's CliRunner.

Pipeline classes are mocked so no real DB/filesystem/model is needed.
Tests verify: argument validation, option forwarding, exit codes, output messages.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from app.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# universe-dl
# ---------------------------------------------------------------------------

def test_universe_dl_exits_1_when_dir_missing(tmp_path):
    result = runner.invoke(app, ["universe-dl", str(tmp_path / "nonexistent")])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_universe_dl_runs_pipeline(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    mock_dl = MagicMock()
    mock_dl.run.return_value = {"processed": 10, "failed": 0, "skipped": 0}
    with patch("app.cli.SessionLocal") as mock_session, \
         patch("app.ingestion.universe_dl.UniverseDL", return_value=mock_dl) as MockDL:
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        result = runner.invoke(app, ["universe-dl", str(corpus)])
    assert result.exit_code == 0
    assert "Done" in result.output


def test_universe_dl_forwards_batch_size(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    mock_dl = MagicMock()
    mock_dl.run.return_value = {"processed": 0, "failed": 0, "skipped": 0}
    with patch("app.cli.SessionLocal") as mock_session, \
         patch("app.ingestion.universe_dl.UniverseDL", return_value=mock_dl) as MockDL:
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        runner.invoke(app, ["universe-dl", str(corpus), "--batch-size", "50"])
    call_kwargs = MockDL.call_args[1]
    assert call_kwargs["batch_size"] == 50


# ---------------------------------------------------------------------------
# daily-dl
# ---------------------------------------------------------------------------

def test_daily_dl_exits_1_when_not_a_git_repo(tmp_path):
    not_a_repo = tmp_path / "not_git"
    not_a_repo.mkdir()
    result = runner.invoke(app, ["daily-dl", str(not_a_repo)])
    assert result.exit_code == 1
    assert "not a git repository" in result.output


def test_daily_dl_runs_pipeline(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    mock_dl = MagicMock()
    mock_dl.run.return_value = {"inserted": 5, "updated": 2, "failed": 0}
    with patch("app.cli.SessionLocal") as mock_session, \
         patch("app.ingestion.daily_dl.DailyDL", return_value=mock_dl):
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        result = runner.invoke(app, ["daily-dl", str(repo)])
    assert result.exit_code == 0
    assert "Done" in result.output


# ---------------------------------------------------------------------------
# embed-bills
# ---------------------------------------------------------------------------

def test_embed_bills_runs_pipeline():
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = {"embedded": 42}
    with patch("app.cli.SessionLocal") as mock_session, \
         patch("app.ingestion.embedding_pipeline.EmbeddingPipeline", return_value=mock_pipeline):
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        result = runner.invoke(app, ["embed-bills"])
    assert result.exit_code == 0
    assert "Done" in result.output


def test_embed_bills_forwards_batch_size():
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = {"embedded": 0}
    with patch("app.cli.SessionLocal") as mock_session, \
         patch("app.ingestion.embedding_pipeline.EmbeddingPipeline", return_value=mock_pipeline) as MockPipeline:
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        runner.invoke(app, ["embed-bills", "--batch-size", "32"])
    call_kwargs = MockPipeline.call_args[1]
    assert call_kwargs["batch_size"] == 32


def test_embed_bills_forwards_model():
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = {"embedded": 0}
    with patch("app.cli.SessionLocal") as mock_session, \
         patch("app.ingestion.embedding_pipeline.EmbeddingPipeline", return_value=mock_pipeline) as MockPipeline:
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        runner.invoke(app, ["embed-bills", "--model", "paraphrase-multilingual-MiniLM-L12-v2"])
    call_kwargs = MockPipeline.call_args[1]
    assert call_kwargs["model_name"] == "paraphrase-multilingual-MiniLM-L12-v2"
