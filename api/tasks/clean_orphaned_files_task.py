import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import String, cast

from configs import dify_config
from extensions.ext_database import db
from models.account import Account, Tenant
from models.dataset import Dataset, DocumentSegment, SegmentAttachmentBinding
from models.dataset import Document as DatasetDocument
from models.model import App, Site, UploadFile
from models.tools import ToolFile
from models.workflow import WorkflowDraftVariableFile

logger = logging.getLogger(__name__)

# Path to store the auto-set boundary time
BOUNDARY_TIME_FILE = Path(__file__).parent.parent / "storage" / "orphaned_file_cleanup_boundary.txt"


def _get_boundary_time() -> str | None:
    """
    Get the boundary time from config or file.
    Priority: ENV variable > File
    """
    # First check environment variable
    if dify_config.ORPHANED_FILE_CLEANUP_START_TIME:
        return dify_config.ORPHANED_FILE_CLEANUP_START_TIME

    # Then check file
    if BOUNDARY_TIME_FILE.exists():
        try:
            boundary_time = BOUNDARY_TIME_FILE.read_text().strip()
            if boundary_time:
                logger.info("Loaded boundary time from file: %s", boundary_time)
                return boundary_time
        except Exception:
            logger.exception("Failed to read boundary time file")

    return None


def _set_boundary_time(boundary_time: str) -> bool:
    """
    Save the boundary time to file.
    Returns True if successful, False otherwise.
    """
    try:
        # Ensure storage directory exists
        BOUNDARY_TIME_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Write boundary time to file
        BOUNDARY_TIME_FILE.write_text(boundary_time)
        logger.info("Saved boundary time to file: %s", BOUNDARY_TIME_FILE)
        return True
    except Exception:
        logger.exception("Failed to save boundary time to file")
        return False


def clean_orphaned_files_task():
    """
    Clean orphaned files (files uploaded but never used)

    Strategy:
    1. All uploaded files wait 24 hours
    2. Files older than 24 hours without associations are considered orphaned
    3. Multiple checks before deletion
    4. Only clean files created after deployment time
    5. Auto-set deployment boundary on first run if not configured
    """

    logger.info("Starting orphaned files cleanup task")

    # Unified wait window: 24 hours
    hours_threshold = dify_config.ORPHANED_FILE_CLEANUP_THRESHOLD_HOURS
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)

    total_cleaned = 0
    total_checked = 0

    # Build query
    query = db.session.query(UploadFile).filter(
        UploadFile.created_at < cutoff_time,
        UploadFile.used == False,
    )

    # Check if deployment boundary is set
    start_time_str = _get_boundary_time()
    if start_time_str:
        try:
            start_time = datetime.fromisoformat(start_time_str)
            query = query.filter(UploadFile.created_at >= start_time)
            logger.info("Only cleaning files created after %s", start_time_str)
        except ValueError:
            logger.exception("Invalid boundary time format: %s", start_time_str)
    else:
        # Auto-set boundary to current time on first run and save to file
        current_time = datetime.utcnow().isoformat()
        logger.info("Boundary time not set, auto-setting to %s", current_time)

        # Save to file for future runs
        if _set_boundary_time(current_time):
            logger.info("Boundary time saved successfully. Future runs will clean files created after this time.")
        else:
            logger.warning(
                "Failed to save boundary time to file. Please set ORPHANED_FILE_CLEANUP_START_TIME manually."
            )

        logger.info("No files will be cleaned in this run.")
        return {
            "checked": 0,
            "cleaned": 0,
            "boundary_set": current_time,
        }

    # Find candidate files
    batch_size = dify_config.ORPHANED_FILE_CLEANUP_BATCH_SIZE
    candidate_files = query.limit(batch_size).all()

    logger.info("Found %d candidate files older than %d hours", len(candidate_files), hours_threshold)

    for file in candidate_files:
        total_checked += 1

        # Verify file is orphaned
        if _is_file_orphaned(file):
            try:
                # Delete file
                from services.file_service import FileService

                FileService.delete_file_by_id(file.id)
                total_cleaned += 1
                logger.info(
                    "Cleaned orphaned file: id=%s, name=%s, role=%s, age_hours=%.1f",
                    file.id,
                    file.name,
                    file.created_by_role,
                    (datetime.utcnow() - file.created_at).total_seconds() / 3600,
                )
            except Exception as e:
                logger.exception("Failed to delete file %s", file.id)

    # Alert if cleanup count exceeds threshold
    alert_threshold = dify_config.ORPHANED_FILE_CLEANUP_ALERT_THRESHOLD_CLEANED
    if total_cleaned > alert_threshold:
        logger.warning("High cleanup count detected: %s files deleted (threshold: %s)", total_cleaned, alert_threshold)

    logger.info("Orphaned files cleanup completed: checked=%s, cleaned=%s", total_checked, total_cleaned)

    return {
        "checked": total_checked,
        "cleaned": total_cleaned,
    }


def _is_file_orphaned(file: UploadFile) -> bool:
    """
    Verify file is orphaned with multiple checks

    Checks 10 association points (excluding MessageFile - temporary files):
    1. Document table
    2. WorkflowDraftVariableFile table
    3. ToolFile table
    4. SegmentAttachmentBinding table
    5. Account.avatar field
    6. App.icon field
    7. Site.icon field
    8. Tenant.custom_config field
    9. DocumentSegment.content field
    10. Dataset.icon_info field
    """

    # Check 1: Document
    if (
        db.session.query(DatasetDocument.id)
        .filter(
            DatasetDocument.data_source_type == "upload_file",
            cast(DatasetDocument.data_source_info, String).contains(file.id),
        )
        .first()
    ):
        return False

    # Check 2: WorkflowDraftVariableFile
    if (
        db.session.query(WorkflowDraftVariableFile.id)
        .filter(WorkflowDraftVariableFile.upload_file_id == file.id)
        .first()
    ):
        return False

    # Check 3: ToolFile
    if db.session.query(ToolFile.id).filter(ToolFile.file_key.contains(file.id)).first():
        return False

    # Check 4: SegmentAttachmentBinding
    if db.session.query(SegmentAttachmentBinding.id).filter(SegmentAttachmentBinding.attachment_id == file.id).first():
        return False

    # Check 5: Account.avatar
    if db.session.query(Account.id).filter(Account.avatar == file.id).first():
        return False

    # Check 6: App.icon
    if db.session.query(App.id).filter(App.icon_type == "image", App.icon == file.id).first():
        return False

    # Check 7: Site.icon
    if db.session.query(Site.id).filter(Site.icon_type == "image", Site.icon == file.id).first():
        return False

    # Check 8: Tenant.custom_config
    if db.session.query(Tenant.id).filter(cast(Tenant.custom_config, String).contains(file.id)).first():
        return False

    # Check 9: DocumentSegment.content
    if db.session.query(DocumentSegment.id).filter(DocumentSegment.content.contains(file.id)).first():
        return False

    # Check 10: Dataset.icon_info
    if db.session.query(Dataset.id).filter(cast(Dataset.icon_info, String).contains(file.id)).first():
        return False

    # All checks passed, file is orphaned
    return True
