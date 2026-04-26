from pathlib import Path
import typer
from loguru import logger
from app.db.session import SessionLocal
from app.config import settings

app = typer.Typer(help="Bill Retrieval Chatbot — ETL commands")


@app.command()
def universe_dl(
    corpus_dir: Path = typer.Argument(..., help="Path to the unzipped BILLSTATUS corpus"),
    batch_size: int = typer.Option(settings.ETL_BATCH_SIZE, help="Files per batch"),
    resume: bool = typer.Option(True, help="Resume from last checkpoint if available"),
):
    """Run the Universe DL bulk ingestion pipeline."""
    from app.ingestion.universe_dl import UniverseDL

    if not corpus_dir.exists():
        typer.echo(f"Error: {corpus_dir} does not exist.", err=True)
        raise typer.Exit(1)

    logger.info(f"Starting Universe DL from {corpus_dir} (batch_size={batch_size})")
    with SessionLocal() as db:
        if not resume:
            from app.db import models
            db.query(models.IngestCheckpoint).filter_by(pipeline="universe").delete()
            db.commit()
        dl = UniverseDL(db=db, corpus_dir=corpus_dir, batch_size=batch_size)
        stats = dl.run()

    typer.echo(f"Done: {stats}")


@app.command()
def daily_dl(
    repo_path: Path = typer.Argument(..., help="Path to the local unitedstates/congress repo"),
):
    """Run the Daily DL incremental pipeline using git diff."""
    from app.ingestion.daily_dl import DailyDL

    if not (repo_path / ".git").exists():
        typer.echo(f"Error: {repo_path} is not a git repository.", err=True)
        raise typer.Exit(1)

    logger.info(f"Starting Daily DL from {repo_path}")
    with SessionLocal() as db:
        dl = DailyDL(db=db, repo_path=repo_path)
        stats = dl.run()

    typer.echo(f"Done: {stats}")


if __name__ == "__main__":
    app()
