import logging

import app

logger = logging.getLogger(__name__)


@app.celery.task(queue="dataset")
def clean_orphaned_files():
    """
    Scheduled task to clean orphaned files

    Runs daily at 3:00 AM to clean files that:
    - Were uploaded more than 24 hours ago
    - Are not marked as used (used=False)
    - Are not associated with any entity (Message, Document, etc.)
    - Were created after the deployment time (if ORPHANED_FILE_CLEANUP_START_TIME is set)
    """
    from tasks.clean_orphaned_files_task import clean_orphaned_files_task

    logger.info("Starting scheduled orphaned files cleanup")

    try:
        result = clean_orphaned_files_task()
        logger.info(
            "Scheduled orphaned files cleanup completed: checked=%d, cleaned=%d",
            result.get('checked', 0),
            result.get('cleaned', 0)
        )
        return result
    except Exception as e:
        logger.exception("Scheduled orphaned files cleanup failed")
        raise
