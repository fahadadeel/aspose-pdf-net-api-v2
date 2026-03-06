"""
routers/files.py — File upload endpoints.

POST /api/upload-files
"""

from pathlib import Path
from typing import List

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter()

APP_ROOT = Path(__file__).resolve().parent.parent


@router.post("/api/upload-files")
async def api_upload_files(files: List[UploadFile] = File(...)):
    """Upload test files to the workspace root directory."""
    if not files:
        return JSONResponse({"error": "No files selected"}, status_code=400)

    uploaded_count = 0
    for file in files:
        if file and file.filename:
            filename = Path(file.filename).name
            filepath = APP_ROOT / filename
            try:
                content = await file.read()
                filepath.write_bytes(content)
                uploaded_count += 1
                print(f"Uploaded file: {filepath}")
            except Exception as e:
                print(f"Failed to upload {filename}: {e}")
                return JSONResponse({"error": f"Failed to upload {filename}: {e}"}, status_code=500)

    return {"count": uploaded_count, "message": f"{uploaded_count} file(s) uploaded successfully"}
