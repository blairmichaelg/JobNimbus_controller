from typing import List
from fastapi import WebSocket
import structlog

logger = structlog.get_logger("app.core.notifications")

class Notifier:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("websocket_client_connected", active_count=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("websocket_client_disconnected", active_count=len(self.active_connections))

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("websocket_broadcast_failed", error=str(e))
                dead_connections.append(connection)
                
        # Clean up any dead connections
        for dead in dead_connections:
            self.disconnect(dead)

# Global singleton
notifier = Notifier()
