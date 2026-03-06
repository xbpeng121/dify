from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings


class OrphanedFileCleanupConfig(BaseSettings):
    """
    Configuration for orphaned file cleanup
    """

    ORPHANED_FILE_CLEANUP_ENABLED: bool = Field(
        description="Enable or disable automatic orphaned file cleanup",
        default=True,
    )

    ORPHANED_FILE_CLEANUP_THRESHOLD_HOURS: PositiveInt = Field(
        description="Wait window in hours before cleaning orphaned files (unified for all users)",
        default=168,  # 7 days = 7 * 24 hours
    )

    ORPHANED_FILE_CLEANUP_BATCH_SIZE: PositiveInt = Field(
        description="Maximum number of files to process in a single cleanup task run",
        default=1000,
    )

    ORPHANED_FILE_CLEANUP_START_TIME: str | None = Field(
        description="ISO format timestamp (e.g., '2024-03-05 00:00:00') - only clean files created after this time. "
        "If not set, will be auto-set to current time on first cleanup task run. "
        "Historical files should be cleaned manually using CLI command.",
        default=None,
    )

    ORPHANED_FILE_CLEANUP_ALERT_ENABLED: bool = Field(
        description="Enable or disable alerts for orphaned file cleanup",
        default=True,
    )

    ORPHANED_FILE_CLEANUP_ALERT_THRESHOLD_CLEANED: PositiveInt = Field(
        description="Alert threshold - log WARNING when single cleanup exceeds this many files",
        default=5000,
    )

    ORPHANED_FILE_CLEANUP_ALERT_THRESHOLD_CHECKED: PositiveInt = Field(
        description="Alert threshold - log WARNING when single cleanup checks this many files",
        default=50000,
    )
