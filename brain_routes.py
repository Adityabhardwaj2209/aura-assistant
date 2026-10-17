"""Knowledge controls attached to the existing local FastAPI app."""
import asyncio
from pathlib import Path
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from aura_brain import documents, import_document, delete_document, search, MAX_BYTES


def install(app, require, token):
    @app.get('/brain')
    def brain_page():
        html = Path(__file__).with_name('brain.html').read_text(encoding='utf-8')
        return HTMLResponse(html.replace('__TOKEN__', token), headers={'Cache-Control':'no-store'})

    @app.get('/api/brain/documents')
    async def list_documents(request: Request):
        require(request)
        return {'documents': await asyncio.to_thread(documents)}

    @app.post('/api/brain/import')
    async def upload_document(request: Request):
        require(request)
        form = await request.form()
        file = form.get('file')
        if file is None or not hasattr(file, 'read'):
            raise HTTPException(400, 'Choose a document first.')
        raw = await file.read(MAX_BYTES+1)
        try:
            return await asyncio.to_thread(import_document, file.filename or '', raw)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.post('/api/brain/delete')
    async def remove_document(request: Request):
        require(request)
        data = await request.json()
        try:
            doc_id = int(data['id'])
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Choose a valid document.')
        await asyncio.to_thread(delete_document, doc_id)
        return {'ok':True}

    @app.post('/api/brain/search')
    async def find_passages(request: Request):
        require(request)
        data = await request.json()
        query = str(data.get('query','')).strip()
        if not query or len(query)>6000:
            raise HTTPException(400, 'Enter a question below 6000 characters.')
        return {'passages':await asyncio.to_thread(search, query)}
