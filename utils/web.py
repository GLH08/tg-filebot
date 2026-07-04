import os
import json
import logging
import base64
import hmac
from aiohttp import web

logger = logging.getLogger(__name__)

class WebDashboard:
    def __init__(self, download_manager, port: int = 8080, password: str = ''):
        self.download_manager = download_manager
        self.port = port
        self.password = password or ''
        middlewares = [self._make_auth_middleware()] if self.password else []
        self.app = web.Application(middlewares=middlewares)
        self.runner = None
        self.site = None
        if self.password:
            logger.info("Web Dashboard 已启用 HTTP Basic Auth 鉴权")
        self._setup_routes()

    def _make_auth_middleware(self):
        """构造 HTTP Basic Auth 中间件（仅当设置了 WEB_PASSWORD 时启用）。"""
        @web.middleware
        async def auth_middleware(request, handler):
            if not self._check_auth(request):
                return web.Response(
                    status=401,
                    headers={'WWW-Authenticate': 'Basic realm="TG-FileBot"'},
                    text='401 Unauthorized'
                )
            return await handler(request)
        return auth_middleware

    def _check_auth(self, request) -> bool:
        """校验请求的 Basic Auth 密码（用户名忽略，仅比对密码，常数时间比较）。"""
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        except Exception:
            return False
        _, _, password = decoded.partition(':')
        return hmac.compare_digest(password, self.password)

    def _setup_routes(self):
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/api/status', self.handle_api_status)

    async def start(self):
        """Start the web server."""
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
            await self.site.start()
            logger.info(f"Web Dashboard started on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start web server: {e}")

    async def stop(self):
        """Stop the web server."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Web Dashboard stopped")

    async def handle_index(self, request):
        """Serve the simple HTML dashboard."""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>TG-FileBot Dashboard</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f0f2f5; color: #333; }
                .card { background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
                h1 { color: #1a73e8; margin-top: 0;}
                .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;}
                .stat-box { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #eee;}
                .stat-value { font-size: 24px; font-weight: bold; color: #1a73e8; }
                .stat-label { font-size: 14px; color: #666; margin-top: 5px; }
                ul { list-style: none; padding: 0; }
                li { padding: 10px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;}
                li:last-child { border-bottom: none; }
                .progress-bar { width: 100%; background-color: #e0e0e0; border-radius: 4px; overflow: hidden; margin-top: 5px;}
                .progress-fill { height: 8px; background-color: #4caf50; transition: width 0.3s; }
                .text-muted { color: #777; font-size: 14px; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Tg-FileBot Dashboard</h1>
                <div class="stats-grid">
                    <div class="stat-box">
                        <div class="stat-value" id="active-count">0</div>
                        <div class="stat-label">Active Downloads</div>
                    </div>
                </div>
                
                <h3>Active Tasks</h3>
                <ul id="active-tasks">
                    <li class="text-muted">Loading...</li>
                </ul>
            </div>

            <script>
                function formatBytes(bytes, decimals = 2) {
                    if (!+bytes) return '0 Bytes';
                    const k = 1024;
                    const dm = decimals < 0 ? 0 : decimals;
                    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
                    const i = Math.floor(Math.log(bytes) / Math.log(k));
                    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
                }

                async function fetchStatus() {
                    try {
                        const response = await fetch('/api/status');
                        const data = await response.json();
                        
                        // Update active count
                        const activeList = data.active_downloads;
                        document.getElementById('active-count').innerText = activeList.length;
                        
                        // Render list
                        const ul = document.getElementById('active-tasks');
                        ul.innerHTML = '';
                        
                        if (activeList.length === 0) {
                            ul.innerHTML = '<li class="text-muted">No active downloads right now.</li>';
                            return;
                        }
                        
                        activeList.forEach(task => {
                            const li = document.createElement('li');
                            const percentage = task.total_size ? ((task.downloaded / task.total_size) * 100).toFixed(1) : 0;
                            const speedStr = formatBytes(task.speed) + '/s';
                            
                            let html = `
                                <div style="width: 100%;">
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                                        <strong>${task.filename || 'Unknown'}</strong>
                                        <span>${percentage}%</span>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #666; margin-bottom: 5px;">
                                        <span>${formatBytes(task.downloaded)} / ${formatBytes(task.total_size)}</span>
                                        <span>🚀 ${speedStr}</span>
                                    </div>
                                    <div class="progress-bar">
                                        <div class="progress-fill" style="width: ${percentage}%"></div>
                                    </div>
                                </div>
                            `;
                            li.innerHTML = html;
                            ul.appendChild(li);
                        });
                        
                    } catch (e) {
                        console.error('Failed to fetch status', e);
                    }
                }
                
                // Fetch immediately and poll every 2 seconds
                fetchStatus();
                setInterval(fetchStatus, 2000);
            </script>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')

    async def handle_api_status(self, request):
        """Return JSON status of active downloads."""
        active_list = []
        # Safe concurrent read of dictionary size/items by creating a snapshot 
        # to prevent "dictionary changed size during iteration" RuntimeError.
        active_snapshot = list(self.download_manager.active_downloads.items())
        
        for job_id, context in active_snapshot:
            active_list.append({
                'job_id': job_id,
                'filename': context.filename,
                'downloaded': context.downloaded,
                'total_size': context.size,
                'speed': context.speed,
                'status': 'downloading'
            })
            
        return web.json_response({
            'active_downloads': active_list,
            'total_active': len(active_list)
        })
