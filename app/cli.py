from pathlib import Path
from sqlalchemy import func
import typer
from loguru import logger
from app.db.session import SessionLocal
from app.config import settings

app = typer.Typer(help="Bill Retrieval Chatbot — ETL commands")


def build_ingestion_status(db) -> dict:
    from app.db import models

    total_bills = db.query(models.Bill).count()
    failed = db.query(models.ParseFailure).count()
    embedded = db.query(models.Bill).filter(models.Bill.embedding.isnot(None)).count()
    checkpoints = {
        row.pipeline: row.last_processed
        for row in db.query(models.IngestCheckpoint).order_by(models.IngestCheckpoint.pipeline).all()
    }
    top_failures = [
        {"reason": reason or "unknown", "count": count}
        for reason, count in db.query(
            models.ParseFailure.error_message,
            func.count(models.ParseFailure.id),
        ).group_by(models.ParseFailure.error_message).order_by(func.count(models.ParseFailure.id).desc()).limit(5).all()
    ]
    latest_daily = db.query(models.IngestCheckpoint).filter_by(pipeline="daily").first()
    return {
        "bills_parsed": total_bills,
        "bills_failed": failed,
        "embedding_coverage_percent": round((embedded / total_bills) * 100, 2) if total_bills else 0,
        "checkpoints": checkpoints,
        "top_failures": top_failures,
        "latest_daily_checkpoint": latest_daily.last_processed if latest_daily else None,
    }


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


@app.command()
def status():
    """Show ingestion progress, checkpoints, and embedding coverage."""
    with SessionLocal() as db:
        report = build_ingestion_status(db)

    typer.echo(f"Bills parsed: {report['bills_parsed']}")
    typer.echo(f"Bills failed: {report['bills_failed']}")
    typer.echo(f"Embedding coverage: {report['embedding_coverage_percent']}%")
    typer.echo(f"Latest daily checkpoint: {report['latest_daily_checkpoint'] or 'none'}")
    typer.echo("Checkpoints:")
    for pipeline, marker in report["checkpoints"].items():
        typer.echo(f"  {pipeline}: {marker or 'none'}")
    typer.echo("Top parse failures:")
    for failure in report["top_failures"]:
        typer.echo(f"  {failure['count']}: {failure['reason']}")


@app.command()
def embed_bills(
    batch_size: int = typer.Option(settings.ETL_BATCH_SIZE, help="Bills per encoding batch"),
    model: str = typer.Option(settings.EMBEDDING_MODEL, help="SentenceTransformer model name"),
):
    """Generate and store embeddings for bills with null embedding."""
    from app.ingestion.embedding_pipeline import EmbeddingPipeline

    logger.info(f"Starting embedding pipeline (batch_size={batch_size}, model={model})")
    with SessionLocal() as db:
        pipeline = EmbeddingPipeline(db=db, model_name=model, batch_size=batch_size)
        stats = pipeline.run()

    typer.echo(f"Done: {stats}")


if __name__ == "__main__":
    app()
