from pathlib import Path
from fastapi import UploadFile, HTTPException
import structlog
import hashlib

logger = structlog.get_logger("app.core.upload_utils")

async def stream_upload_safely(file: UploadFile, dest_path: Path, max_bytes: int = 10 * 1024 * 1024) -> str:
    """
    Safely stream an UploadFile to disk in chunks to strictly enforce file size limits 
    without causing MemoryError (OOM) or blocking the async event loop.
    Returns the SHA-256 hash of the uploaded file.
    """
    # 1. Fast-fail if the native Starlette spool size is already calculated and oversized
    if getattr(file, 'size', 0) and file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large ({max_bytes // (1024 * 1024)}MB max).")

    bytes_written = 0
    hasher = hashlib.sha256()
    try:
        import asyncio
        # 2. Open file in threadpool to prevent blocking the event loop
        buffer = await asyncio.to_thread(dest_path.open, "wb")
        try:
            # 3. Read in strict 1MB chunks to keep RAM footprint low and deterministic
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File too large ({max_bytes // (1024 * 1024)}MB max).")
                hasher.update(chunk)
                # 4. Write to disk via threadpool to maintain concurrency
                await asyncio.to_thread(buffer.write, chunk)
        finally:
            await asyncio.to_thread(buffer.close)
            
        return hasher.hexdigest()
    except Exception:
        # 3. Aggressive cleanup on any interruption (network drop, timeout, or size limit)
        dest_path.unlink(missing_ok=True)
        raise
