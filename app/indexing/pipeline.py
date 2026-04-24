from io import BytesIO

import httpx
from pypdf import PdfReader

from app.config import get_settings
from app.db.client import get_single_row, insert_row, insert_rows_bulk
from app.indexing.chunking import split_into_chunks
from app.models import IndexDataRequest


def _insert_chunks(*, tenant_id: str, document_id: str, title: str, content: str) -> int:
    chunks = split_into_chunks(content)
    if not chunks:
        raise ValueError("No text chunks produced from content")

    rows = [
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "chunk_index": i,
            "chunk_text": chunk,
            "metadata": {"title": title},
            "embedding": None,
        }
        for i, chunk in enumerate(chunks)
    ]
    insert_rows_bulk("knowledge_chunks", rows)
    return len(chunks)


def process_text_index_job(payload: IndexDataRequest) -> int:
    """Chunk text and insert knowledge_chunks (embedding null; retrieval uses pg_trgm).

    If payload.source_ref is provided, it is treated as an existing knowledge_base_documents.id.
    Otherwise, a new knowledge_base_documents row is created (dashboard text-ingest path).
    """
    raw = payload.payload or {}
    content = (raw.get("content") or "").strip()
    if not content:
        raise ValueError("payload.content is required for text indexing")

    title = (raw.get("title") or "FAQ / policy").strip()[:200]
    document_id = (payload.source_ref or "").strip() or None

    if not document_id:
        file_name = f"{title}.txt"
        doc = insert_row(
            "knowledge_base_documents",
            {
                "tenant_id": payload.tenant_id,
                "file_name": file_name,
                "file_type": "text",
                "storage_path": None,
                "status": "ready",
                "file_size_bytes": len(content.encode("utf-8")),
                "content_json": {"title": title, "source": "chaster_brain_dashboard"},
            },
        )
        if not doc or not doc.get("id"):
            raise RuntimeError("Failed to insert knowledge_base_documents row")
        document_id = doc["id"]

    return _insert_chunks(
        tenant_id=payload.tenant_id,
        document_id=document_id,
        title=title,
        content=content,
    )


def _download_storage_file_bytes(storage_path: str) -> bytes:
    settings = get_settings()
    url = f"{settings.supabase_url}/storage/v1/object/knowledge-base/{storage_path}"
    response = httpx.get(
        url,
        headers={
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.content


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        pages.append((page.extract_text() or "").strip())
    return "\n\n".join(p for p in pages if p).strip()


def process_document_index_job(payload: IndexDataRequest) -> int:
    document_id = (payload.source_ref or "").strip()
    if not document_id:
        raise ValueError("source_ref (knowledge_base_documents.id) is required for document indexing")

    doc = get_single_row(
        "knowledge_base_documents",
        "id,tenant_id,file_name,file_type,storage_path",
        {"id": document_id, "tenant_id": payload.tenant_id},
    )
    if not doc:
        raise ValueError("Document not found for this tenant")
    storage_path = (doc.get("storage_path") or "").strip()
    if not storage_path:
        raise ValueError("Document has no storage_path")

    file_type = (doc.get("file_type") or "").strip().lower()
    file_name = str(doc.get("file_name") or "document")

    if file_type == "pdf":
        raw_bytes = _download_storage_file_bytes(storage_path)
        content = _extract_pdf_text(raw_bytes)
    elif file_type in {"txt", "text", "md"}:
        raw_bytes = _download_storage_file_bytes(storage_path)
        content = raw_bytes.decode("utf-8", errors="replace").strip()
    else:
        raise ValueError(f"Unsupported document type for indexing: {file_type}")

    if not content:
        raise ValueError("No extractable text found in document")

    return _insert_chunks(
        tenant_id=payload.tenant_id,
        document_id=document_id,
        title=file_name,
        content=content,
    )
