import base64
import logging
import mimetypes
import os
import re
import urllib.parse
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.http import parse_options_header

from constants import AUDIO_EXTENSIONS, DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from core.file import File, FileBelongsTo, FileTransferMethod, FileType, FileUploadConfig, helpers
from core.helper import ssrf_proxy
from extensions.ext_database import db
from models import MessageFile, ToolFile, UploadFile

logger = logging.getLogger(__name__)


def build_from_message_files(
    *,
    message_files: Sequence["MessageFile"],
    tenant_id: str,
    config: FileUploadConfig | None = None,
) -> Sequence[File]:
    results = [
        build_from_message_file(message_file=file, tenant_id=tenant_id, config=config)
        for file in message_files
        if file.belongs_to != FileBelongsTo.ASSISTANT
    ]
    return results


def build_from_message_file(
    *,
    message_file: "MessageFile",
    tenant_id: str,
    config: FileUploadConfig | None,
):
    mapping = {
        "transfer_method": message_file.transfer_method,
        "url": message_file.url,
        "type": message_file.type,
    }

    # Only include id if it exists (message_file has been committed to DB)
    if message_file.id:
        mapping["id"] = message_file.id

    # Set the correct ID field based on transfer method
    if message_file.transfer_method == FileTransferMethod.TOOL_FILE:
        mapping["tool_file_id"] = message_file.upload_file_id
    else:
        mapping["upload_file_id"] = message_file.upload_file_id

    return build_from_mapping(
        mapping=mapping,
        tenant_id=tenant_id,
        config=config,
    )


def build_from_mapping(
    *,
    mapping: Mapping[str, Any],
    tenant_id: str,
    config: FileUploadConfig | None = None,
    strict_type_validation: bool = False,
) -> File:
    transfer_method_value = mapping.get("transfer_method")
    if not transfer_method_value:
        raise ValueError("transfer_method is required in file mapping")
    transfer_method = FileTransferMethod.value_of(transfer_method_value)

    build_functions: dict[FileTransferMethod, Callable] = {
        FileTransferMethod.LOCAL_FILE: _build_from_local_file,
        FileTransferMethod.REMOTE_URL: _build_from_remote_url,
        FileTransferMethod.TOOL_FILE: _build_from_tool_file,
        FileTransferMethod.DATASOURCE_FILE: _build_from_datasource_file,
        FileTransferMethod.BASE64: _build_from_base64,
    }

    build_func = build_functions.get(transfer_method)
    if not build_func:
        raise ValueError(f"Invalid file transfer method: {transfer_method}")

    file: File = build_func(
        mapping=mapping,
        tenant_id=tenant_id,
        transfer_method=transfer_method,
        strict_type_validation=strict_type_validation,
    )

    if config and not _is_file_valid_with_config(
        input_file_type=mapping.get("type", FileType.CUSTOM),
        file_extension=file.extension or "",
        file_transfer_method=file.transfer_method,
        config=config,
    ):
        raise ValueError(f"File validation failed for file: {file.filename}")

    return file


def build_from_mappings(
    *,
    mappings: Sequence[Mapping[str, Any]],
    config: FileUploadConfig | None = None,
    tenant_id: str,
    strict_type_validation: bool = False,
) -> Sequence[File]:
    # TODO(QuantumGhost): Performance concern - each mapping triggers a separate database query.
    # Implement batch processing to reduce database load when handling multiple files.
    # Filter out None/empty mappings to avoid errors
    valid_mappings = [m for m in mappings if m and m.get("transfer_method")]
    files = [
        build_from_mapping(
            mapping=mapping,
            tenant_id=tenant_id,
            config=config,
            strict_type_validation=strict_type_validation,
        )
        for mapping in valid_mappings
    ]

    if (
        config
        # If image config is set.
        and config.image_config
        # And the number of image files exceeds the maximum limit
        and sum(1 for _ in (filter(lambda x: x.type == FileType.IMAGE, files))) > config.image_config.number_limits
    ):
        raise ValueError(f"Number of image files exceeds the maximum limit {config.image_config.number_limits}")
    if config and config.number_limits and len(files) > config.number_limits:
        raise ValueError(f"Number of files exceeds the maximum limit {config.number_limits}")

    return files


def _build_from_local_file(
    *,
    mapping: Mapping[str, Any],
    tenant_id: str,
    transfer_method: FileTransferMethod,
    strict_type_validation: bool = False,
) -> File:
    upload_file_id = mapping.get("upload_file_id")
    if not upload_file_id:
        raise ValueError("Invalid upload file id")
    # check if upload_file_id is a valid uuid
    try:
        uuid.UUID(upload_file_id)
    except ValueError:
        raise ValueError("Invalid upload file id format")
    stmt = select(UploadFile).where(
        UploadFile.id == upload_file_id,
        UploadFile.tenant_id == tenant_id,
    )

    row = db.session.scalar(stmt)
    if row is None:
        raise ValueError("Invalid upload file")

    detected_file_type = _standardize_file_type(extension="." + row.extension, mime_type=row.mime_type)
    specified_type = mapping.get("type", "custom")

    if strict_type_validation and detected_file_type.value != specified_type:
        raise ValueError("Detected file type does not match the specified type. Please verify the file.")

    if specified_type and specified_type != "custom":
        file_type = FileType(specified_type)
    else:
        file_type = detected_file_type

    return File(
        id=mapping.get("id"),
        filename=row.name,
        extension="." + row.extension,
        mime_type=row.mime_type,
        tenant_id=tenant_id,
        type=file_type,
        transfer_method=transfer_method,
        remote_url=row.source_url,
        related_id=mapping.get("upload_file_id"),
        size=row.size,
        storage_key=row.key,
    )


def _build_from_remote_url(
    *,
    mapping: Mapping[str, Any],
    tenant_id: str,
    transfer_method: FileTransferMethod,
    strict_type_validation: bool = False,
) -> File:
    upload_file_id = mapping.get("upload_file_id")
    if upload_file_id:
        try:
            uuid.UUID(upload_file_id)
        except ValueError:
            raise ValueError("Invalid upload file id format")
        stmt = select(UploadFile).where(
            UploadFile.id == upload_file_id,
            UploadFile.tenant_id == tenant_id,
        )

        upload_file = db.session.scalar(stmt)
        if upload_file is None:
            raise ValueError("Invalid upload file")

        detected_file_type = _standardize_file_type(
            extension="." + upload_file.extension, mime_type=upload_file.mime_type
        )

        specified_type = mapping.get("type")

        if strict_type_validation and specified_type and detected_file_type.value != specified_type:
            raise ValueError("Detected file type does not match the specified type. Please verify the file.")

        if specified_type and specified_type != "custom":
            file_type = FileType(specified_type)
        else:
            file_type = detected_file_type

        return File(
            id=mapping.get("id"),
            filename=upload_file.name,
            extension="." + upload_file.extension,
            mime_type=upload_file.mime_type,
            tenant_id=tenant_id,
            type=file_type,
            transfer_method=transfer_method,
            remote_url=helpers.get_signed_file_url(upload_file_id=str(upload_file_id)),
            related_id=mapping.get("upload_file_id"),
            size=upload_file.size,
            storage_key=upload_file.key,
        )
    url = mapping.get("url") or mapping.get("remote_url")
    if not url:
        raise ValueError("Invalid file url")

    mime_type, filename, file_size = _get_remote_file_info(url)
    extension = mimetypes.guess_extension(mime_type) or ("." + filename.split(".")[-1] if "." in filename else ".bin")

    detected_file_type = _standardize_file_type(extension=extension, mime_type=mime_type)
    specified_type = mapping.get("type")

    if strict_type_validation and specified_type and detected_file_type.value != specified_type:
        raise ValueError("Detected file type does not match the specified type. Please verify the file.")

    if specified_type and specified_type != "custom":
        file_type = FileType(specified_type)
    else:
        file_type = detected_file_type

    return File(
        id=mapping.get("id"),
        filename=filename,
        tenant_id=tenant_id,
        type=file_type,
        transfer_method=transfer_method,
        remote_url=url,
        mime_type=mime_type,
        extension=extension,
        size=file_size,
        storage_key="",
    )


def _extract_filename(url_path: str, content_disposition: str | None) -> str | None:
    filename: str | None = None
    # Try to extract from Content-Disposition header first
    if content_disposition:
        # Manually extract filename* parameter since parse_options_header doesn't support it
        filename_star_match = re.search(r"filename\*=([^;]+)", content_disposition)
        if filename_star_match:
            raw_star = filename_star_match.group(1).strip()
            # Remove trailing quotes if present
            raw_star = raw_star.removesuffix('"')
            # format: charset'lang'value
            try:
                parts = raw_star.split("'", 2)
                charset = (parts[0] or "utf-8").lower() if len(parts) >= 1 else "utf-8"
                value = parts[2] if len(parts) == 3 else parts[-1]
                filename = urllib.parse.unquote(value, encoding=charset, errors="replace")
            except Exception:
                # Fallback: try to extract value after the last single quote
                if "''" in raw_star:
                    filename = urllib.parse.unquote(raw_star.split("''")[-1])
                else:
                    filename = urllib.parse.unquote(raw_star)

        if not filename:
            # Fallback to regular filename parameter
            _, params = parse_options_header(content_disposition)
            raw = params.get("filename")
            if raw:
                # Strip surrounding quotes and percent-decode if present
                if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                    raw = raw[1:-1]
                filename = urllib.parse.unquote(raw)
    # Fallback to URL path if no filename from header
    if not filename:
        candidate = os.path.basename(url_path)
        filename = urllib.parse.unquote(candidate) if candidate else None
    # Defense-in-depth: ensure basename only
    if filename:
        filename = os.path.basename(filename)
        # Return None if filename is empty or only whitespace
        if not filename or not filename.strip():
            filename = None
    return filename or None


def _guess_mime_type(filename: str) -> str:
    """Guess MIME type from filename, returning empty string if None."""
    guessed_mime, _ = mimetypes.guess_type(filename)
    return guessed_mime or ""


def _get_remote_file_info(url: str):
    file_size = -1
    parsed_url = urllib.parse.urlparse(url)
    url_path = parsed_url.path
    filename = os.path.basename(url_path)

    # Initialize mime_type from filename as fallback
    mime_type = _guess_mime_type(filename)

    resp = ssrf_proxy.head(url, follow_redirects=True)
    if resp.status_code == httpx.codes.OK:
        content_disposition = resp.headers.get("Content-Disposition")
        extracted_filename = _extract_filename(url_path, content_disposition)
        if extracted_filename:
            filename = extracted_filename
            mime_type = _guess_mime_type(filename)
        file_size = int(resp.headers.get("Content-Length", file_size))
        # Fallback to Content-Type header if mime_type is still empty
        if not mime_type:
            mime_type = resp.headers.get("Content-Type", "").split(";")[0].strip()

    if not filename:
        extension = mimetypes.guess_extension(mime_type) or ".bin"
        filename = f"{uuid.uuid4().hex}{extension}"
        if not mime_type:
            mime_type = _guess_mime_type(filename)

    return mime_type, filename, file_size


def _build_from_tool_file(
    *,
    mapping: Mapping[str, Any],
    tenant_id: str,
    transfer_method: FileTransferMethod,
    strict_type_validation: bool = False,
) -> File:
    # Backward/interop compatibility: allow tool_file_id to come from related_id or URL
    tool_file_id = mapping.get("tool_file_id")

    if not tool_file_id:
        raise ValueError(f"ToolFile {tool_file_id} not found")
    tool_file = db.session.scalar(
        select(ToolFile).where(
            ToolFile.id == tool_file_id,
            ToolFile.tenant_id == tenant_id,
        )
    )

    if tool_file is None:
        raise ValueError(f"ToolFile {tool_file_id} not found")

    extension = "." + tool_file.file_key.split(".")[-1] if "." in tool_file.file_key else ".bin"

    detected_file_type = _standardize_file_type(extension=extension, mime_type=tool_file.mimetype)

    specified_type = mapping.get("type")

    if strict_type_validation and specified_type and detected_file_type.value != specified_type:
        raise ValueError("Detected file type does not match the specified type. Please verify the file.")

    if specified_type and specified_type != "custom":
        file_type = FileType(specified_type)
    else:
        file_type = detected_file_type

    return File(
        id=mapping.get("id"),
        tenant_id=tenant_id,
        filename=tool_file.name,
        type=file_type,
        transfer_method=transfer_method,
        remote_url=tool_file.original_url,
        related_id=tool_file.id,
        extension=extension,
        mime_type=tool_file.mimetype,
        size=tool_file.size,
        storage_key=tool_file.file_key,
    )


def _build_from_datasource_file(
    *,
    mapping: Mapping[str, Any],
    tenant_id: str,
    transfer_method: FileTransferMethod,
    strict_type_validation: bool = False,
) -> File:
    datasource_file_id = mapping.get("datasource_file_id")
    if not datasource_file_id:
        raise ValueError(f"DatasourceFile {datasource_file_id} not found")
    datasource_file = (
        db.session.query(UploadFile)
        .where(
            UploadFile.id == datasource_file_id,
            UploadFile.tenant_id == tenant_id,
        )
        .first()
    )

    if datasource_file is None:
        raise ValueError(f"DatasourceFile {mapping.get('datasource_file_id')} not found")

    extension = "." + datasource_file.key.split(".")[-1] if "." in datasource_file.key else ".bin"

    detected_file_type = _standardize_file_type(extension="." + extension, mime_type=datasource_file.mime_type)

    specified_type = mapping.get("type")

    if strict_type_validation and specified_type and detected_file_type.value != specified_type:
        raise ValueError("Detected file type does not match the specified type. Please verify the file.")

    if specified_type and specified_type != "custom":
        file_type = FileType(specified_type)
    else:
        file_type = detected_file_type

    return File(
        id=mapping.get("datasource_file_id"),
        tenant_id=tenant_id,
        filename=datasource_file.name,
        type=file_type,
        transfer_method=FileTransferMethod.TOOL_FILE,
        remote_url=datasource_file.source_url,
        related_id=datasource_file.id,
        extension=extension,
        mime_type=datasource_file.mime_type,
        size=datasource_file.size,
        storage_key=datasource_file.key,
        url=datasource_file.source_url,
    )


def _decode_base64_header(base64_str: str, header_size: int = 64) -> bytes:
    """Decode only the first N bytes of a base64 string for efficient MIME type detection.

    This function decodes only the header portion of a base64 string, which is sufficient
    for file type detection using magic bytes, while avoiding the overhead of decoding
    large files (up to 15MB).

    Args:
        base64_str: Base64 encoded string (without Data URL prefix)
        header_size: Number of bytes to decode (default: 64 bytes, enough for all common formats)

    Returns:
        Decoded header bytes (up to header_size bytes)

    Raises:
        ValueError: If base64 string is invalid
    """
    # Base64 encoding: every 4 characters = 3 bytes
    # To get N bytes, we need ceil(N * 4 / 3) characters
    chars_needed = (header_size * 4 + 2) // 3  # Round up

    # Ensure it's a multiple of 4 (base64 requirement)
    chars_needed = ((chars_needed + 3) // 4) * 4

    # Handle case where base64 string is shorter than needed
    if len(base64_str) < chars_needed:
        # Decode entire string if it's shorter than header size
        try:
            return base64.b64decode(base64_str)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {str(e)}")

    # Extract header portion
    header_base64 = base64_str[:chars_needed]

    # Add padding if needed (shouldn't be necessary if chars_needed is multiple of 4)
    padding_needed = (4 - len(header_base64) % 4) % 4
    if padding_needed:
        header_base64 += "=" * padding_needed

    try:
        decoded = base64.b64decode(header_base64)
        return decoded[:header_size]  # Return only requested bytes
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {str(e)}")


def _estimate_decoded_size(base64_str: str) -> int:
    """Estimate the decoded size of a base64 string without full decoding.

    This provides a fast size estimation with accuracy within 1-2 bytes,
    which is sufficient for size limit checks.

    Args:
        base64_str: Base64 encoded string (without Data URL prefix)

    Returns:
        Estimated decoded size in bytes
    """
    base64_len = len(base64_str)

    # Base calculation: every 4 characters = 3 bytes
    estimated_size = (base64_len * 3) // 4

    # Adjust for padding
    if base64_str.endswith("=="):
        estimated_size -= 2
    elif base64_str.endswith("="):
        estimated_size -= 1

    return estimated_size


def _build_from_base64(
    *,
    mapping: Mapping[str, Any],
    tenant_id: str,
    transfer_method: FileTransferMethod,
    strict_type_validation: bool = False,
) -> File:
    """Build a File object from base64-encoded data.

    The file is kept in memory only and not persisted to storage.
    It will be used during workflow execution and discarded after.

    Supports both plain base64 and Data URL format:
    - Plain: "iVBORw0KGgoAAAANSUhEUgA..."
    - Data URL: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgA..."

    Note: The base64_data stored in File object is always plain base64 without Data URL prefix.

    Performance optimization: Only decodes the first 64 bytes for MIME type detection,
    avoiding full decoding of large files (up to 15MB).
    """
    base64_data = mapping.get("base64_data")
    if not base64_data:
        raise ValueError("Missing base64_data for base64 transfer method")

    # Parse Data URL format if present
    mime_type_from_dataurl = None
    if base64_data.startswith("data:"):
        # Format: data:[<mediatype>][;base64],<data>
        try:
            # Split by comma to separate header and data
            header, data_part = base64_data.split(",", 1)
            # Store only the pure base64 data without Data URL prefix
            base64_data = data_part

            # Parse header to extract MIME type
            # Remove "data:" prefix
            header = header[5:]  # Remove "data:"

            # Check if it contains ";base64"
            if ";base64" in header:
                mime_type_from_dataurl = header.replace(";base64", "").strip()
            else:
                mime_type_from_dataurl = header.strip()

            # If MIME type is empty, set to None
            if not mime_type_from_dataurl:
                mime_type_from_dataurl = None
        except ValueError:
            raise ValueError("Invalid Data URL format. Expected format: data:[<mediatype>][;base64],<data>")

    # Decode only the header (first 64 bytes) for MIME type detection and validation
    # This is much faster than decoding the entire file (which could be up to 15MB)
    try:
        header_bytes = _decode_base64_header(base64_data, header_size=64)
    except ValueError as e:
        raise ValueError(f"Invalid base64 data: {str(e)}")

    # Detect MIME type from file header (magic bytes)
    detected_mime_type = _detect_mime_type_from_data(header_bytes)

    # Determine final MIME type
    # If Data URL provided a MIME type, verify it matches detection
    # If mismatch, use detected type (security: trust file content over declaration)
    if mime_type_from_dataurl:
        # Check if declared and detected types are compatible
        declared_main = mime_type_from_dataurl.split("/")[0]
        detected_main = detected_mime_type.split("/")[0]

        if declared_main != detected_main:
            # Major type mismatch (e.g., image vs video) - use detected type
            logger.warning(
                "MIME type mismatch: Data URL declared '%s' but file header indicates '%s'. Using detected type.",
                mime_type_from_dataurl,
                detected_mime_type,
            )
            mime_type = detected_mime_type
        else:
            # Same major type, use declared (more specific)
            mime_type = mime_type_from_dataurl
    else:
        mime_type = detected_mime_type

    # Estimate file size without full decoding (fast, accuracy within 1-2 bytes)
    file_size = _estimate_decoded_size(base64_data)

    # Check file size limit (15MB)
    max_size = 15 * 1024 * 1024  # 15MB in bytes
    if file_size > max_size:
        raise ValueError(f"Decoded file size ({file_size} bytes) exceeds maximum limit of {max_size} bytes (15MB)")

    # Get filename from mapping or generate one
    filename = mapping.get("filename")
    if not filename:
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = mimetypes.guess_extension(mime_type) or ".bin"
        filename = f"file_{timestamp}{extension}"

    # Determine extension
    extension = mapping.get("extension")
    if not extension:
        if "." in filename:
            extension = "." + filename.split(".")[-1]
        else:
            extension = mimetypes.guess_extension(mime_type) or ".bin"

    # Ensure extension starts with dot
    if extension and not extension.startswith("."):
        extension = "." + extension

    # Detect file type
    detected_file_type = _standardize_file_type(extension=extension, mime_type=mime_type)
    specified_type = mapping.get("type")

    if strict_type_validation and specified_type and detected_file_type.value != specified_type:
        raise ValueError("Detected file type does not match the specified type. Please verify the file.")

    if specified_type and specified_type != "custom":
        file_type = FileType(specified_type)
    else:
        file_type = detected_file_type

    # Create File object with pure base64_data (without Data URL prefix)
    # Note: storage_key is empty as file is not persisted
    return File(
        id=mapping.get("id"),
        tenant_id=tenant_id,
        filename=filename,
        type=file_type,
        transfer_method=transfer_method,
        base64_data=base64_data,  # Always store pure base64 without Data URL prefix
        extension=extension,
        mime_type=mime_type,
        size=file_size,
        storage_key="",
    )


def _detect_mime_type_from_data(data: bytes) -> str:
    """Detect MIME type from file data using magic bytes."""
    # Check common file signatures (magic bytes)
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    elif data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    elif data.startswith(b"%PDF"):
        return "application/pdf"
    elif data.startswith(b"PK\x03\x04"):
        # ZIP-based formats (docx, xlsx, etc.)
        return "application/zip"
    elif data.startswith(b"\x00\x00\x00\x18ftypmp4") or data.startswith(b"\x00\x00\x00\x1cftypisom"):
        return "video/mp4"
    elif data.startswith(b"ID3") or data.startswith(b"\xff\xfb"):
        return "audio/mpeg"
    else:
        # Default to binary if unknown
        return "application/octet-stream"


def _is_file_valid_with_config(
    *,
    input_file_type: str,
    file_extension: str,
    file_transfer_method: FileTransferMethod,
    config: FileUploadConfig,
) -> bool:
    # FIXME(QIN2DIM): Always allow tool files (files generated by the assistant/model)
    # These are internally generated and should bypass user upload restrictions
    if file_transfer_method == FileTransferMethod.TOOL_FILE:
        return True

    if (
        config.allowed_file_types
        and input_file_type not in config.allowed_file_types
        and input_file_type != FileType.CUSTOM
    ):
        return False

    if (
        input_file_type == FileType.CUSTOM
        and config.allowed_file_extensions is not None
        and file_extension not in config.allowed_file_extensions
    ):
        return False

    if input_file_type == FileType.IMAGE:
        if (
            config.image_config
            and config.image_config.transfer_methods
            and file_transfer_method not in config.image_config.transfer_methods
        ):
            return False
    elif config.allowed_file_upload_methods and file_transfer_method not in config.allowed_file_upload_methods:
        return False

    return True


def _standardize_file_type(*, extension: str = "", mime_type: str = "") -> FileType:
    """
    Infer the possible actual type of the file based on the extension and mime_type
    """
    guessed_type = None
    if extension:
        guessed_type = _get_file_type_by_extension(extension)
    if guessed_type is None and mime_type:
        guessed_type = _get_file_type_by_mimetype(mime_type)
    return guessed_type or FileType.CUSTOM


def _get_file_type_by_extension(extension: str) -> FileType | None:
    extension = extension.lstrip(".")
    if extension in IMAGE_EXTENSIONS:
        return FileType.IMAGE
    elif extension in VIDEO_EXTENSIONS:
        return FileType.VIDEO
    elif extension in AUDIO_EXTENSIONS:
        return FileType.AUDIO
    elif extension in DOCUMENT_EXTENSIONS:
        return FileType.DOCUMENT
    return None


def _get_file_type_by_mimetype(mime_type: str) -> FileType | None:
    if "image" in mime_type:
        file_type = FileType.IMAGE
    elif "video" in mime_type:
        file_type = FileType.VIDEO
    elif "audio" in mime_type:
        file_type = FileType.AUDIO
    elif "text" in mime_type or "pdf" in mime_type:
        file_type = FileType.DOCUMENT
    else:
        file_type = FileType.CUSTOM
    return file_type


def get_file_type_by_mime_type(mime_type: str) -> FileType:
    return _get_file_type_by_mimetype(mime_type) or FileType.CUSTOM


class StorageKeyLoader:
    """FileKeyLoader load the storage key from database for a list of files.
    This loader is batched, the database query count is constant regardless of the input size.
    """

    def __init__(self, session: Session, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    def _load_upload_files(self, upload_file_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, UploadFile]:
        stmt = select(UploadFile).where(
            UploadFile.id.in_(upload_file_ids),
            UploadFile.tenant_id == self._tenant_id,
        )

        return {uuid.UUID(i.id): i for i in self._session.scalars(stmt)}

    def _load_tool_files(self, tool_file_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, ToolFile]:
        stmt = select(ToolFile).where(
            ToolFile.id.in_(tool_file_ids),
            ToolFile.tenant_id == self._tenant_id,
        )
        return {uuid.UUID(i.id): i for i in self._session.scalars(stmt)}

    def load_storage_keys(self, files: Sequence[File]):
        """Loads storage keys for a sequence of files by retrieving the corresponding
        `UploadFile` or `ToolFile` records from the database based on their transfer method.

        This method doesn't modify the input sequence structure but updates the `_storage_key`
        property of each file object by extracting the relevant key from its database record.

        Performance note: This is a batched operation where database query count remains constant
        regardless of input size. However, for optimal performance, input sequences should contain
        fewer than 1000 files. For larger collections, split into smaller batches and process each
        batch separately.
        """

        upload_file_ids: list[uuid.UUID] = []
        tool_file_ids: list[uuid.UUID] = []
        for file in files:
            related_model_id = file.related_id
            if file.related_id is None:
                raise ValueError("file id should not be None.")
            if file.tenant_id != self._tenant_id:
                err_msg = (
                    f"invalid file, expected tenant_id={self._tenant_id}, "
                    f"got tenant_id={file.tenant_id}, file_id={file.id}, related_model_id={related_model_id}"
                )
                raise ValueError(err_msg)
            model_id = uuid.UUID(related_model_id)

            if file.transfer_method in (FileTransferMethod.LOCAL_FILE, FileTransferMethod.REMOTE_URL):
                upload_file_ids.append(model_id)
            elif file.transfer_method == FileTransferMethod.TOOL_FILE:
                tool_file_ids.append(model_id)

        tool_files = self._load_tool_files(tool_file_ids)
        upload_files = self._load_upload_files(upload_file_ids)
        for file in files:
            model_id = uuid.UUID(file.related_id)
            if file.transfer_method in (FileTransferMethod.LOCAL_FILE, FileTransferMethod.REMOTE_URL):
                upload_file_row = upload_files.get(model_id)
                if upload_file_row is None:
                    raise ValueError(f"Upload file not found for id: {model_id}")
                file.storage_key = upload_file_row.key
            elif file.transfer_method == FileTransferMethod.TOOL_FILE:
                tool_file_row = tool_files.get(model_id)
                if tool_file_row is None:
                    raise ValueError(f"Tool file not found for id: {model_id}")
                file.storage_key = tool_file_row.file_key
