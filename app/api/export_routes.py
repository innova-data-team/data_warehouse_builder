"""Export endpoints — assemble per-batch artifact bundles."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_metadata_session
from app.services.export_service import ExportService
from app.services.powerbi_export_service import PowerBIExportService
from app.services.sql_generator_service import SQLGeneratorService
from app.services.zakaadash_export_service import ZakaaDashExportService

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/{batch_id}/powerbi")
def export_powerbi(
    batch_id: str, session: Session = Depends(get_metadata_session),
) -> dict[str, str]:
    path = PowerBIExportService(session).export(batch_id)
    return {"batch_id": batch_id, "path": str(path)}


@router.get("/{batch_id}/zakaadash")
def export_zakaadash(
    batch_id: str, session: Session = Depends(get_metadata_session),
) -> dict[str, str]:
    path = ZakaaDashExportService(session).export(batch_id)
    return {"batch_id": batch_id, "path": str(path)}


@router.get("/{batch_id}/sql")
def export_sql(
    batch_id: str, session: Session = Depends(get_metadata_session),
) -> dict[str, str]:
    files = SQLGeneratorService(session).generate_all(batch_id)
    return {k: str(v) for k, v in files.items()}


@router.get("/{batch_id}/final-files")
def export_final_files(
    batch_id: str, session: Session = Depends(get_metadata_session),
) -> dict[str, object]:
    artifacts = ExportService(session).export_all(batch_id)
    return {"batch_id": batch_id, "artifacts": artifacts}
