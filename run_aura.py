"""Launch AURA Brain + Web with connection diagnostics and an isolated avatar."""
import importlib
import threading
import time
import urllib.request
import webbrowser
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    required = ['phase3_web.py', 'aura_brain.py', 'aura_web.py',
                'brain_routes.py', 'brain.html', 'phase2_fixed.html', 'worklet.js']
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit('Missing files: '+', '.join(missing)+'\nExtract the fix into your existing aura-assistant folder.')
    import uvicorn
    from fastapi.responses import HTMLResponse
    from fastapi.routing import APIRoute
    server = importlib.import_module('phase3_web')
    server.initialize()
    server.initialize_brain()

    def fixed_index():
        html = (ROOT/'phase2_fixed.html').read_text(encoding='utf-8')
        return HTMLResponse(html.replace('__TOKEN__', server.TOKEN), headers={'Cache-Control':'no-store'})

    # Give the fixed frontend precedence without modifying the original files.
    server.app.router.routes.insert(0, APIRoute('/', fixed_index, methods=['GET']))

    @server.app.get('/api/health')
    def health():
        return {'ok': True, 'version': 'aura-connection-fix-1'}

    ready = threading.Event()
    ready.set()

    def open_when_ready():
        if not ready.wait(30):
            return
        url = 'http://127.0.0.1:8511'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(20):
            try:
                with opener.open(url+'/api/health', timeout=2) as result:
                    if result.status == 200:
                        webbrowser.open(url+('/workspace' if os.environ.get('AURA_WORKSPACE')=='1' else ('/body' if os.environ.get('AURA_BODY_LAB')=='1' else '')))
                        return
            except Exception:
                time.sleep(.25)

    threading.Thread(target=open_when_ready, daemon=True).start()
    print('AURA Brain + Web • http://127.0.0.1:8511')
    print('Keep this CMD window open. Browser opens after the server is ready.')
    print('If port 8511 is already occupied, stop the previous AURA window with Ctrl+C.')
    uvicorn.run(server.app, host='127.0.0.1', port=8511, access_log=False)


if __name__ == '__main__':
    main()
