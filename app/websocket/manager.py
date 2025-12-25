"""WebSocket connection manager for real-time features."""
from typing import Dict, Set
from fastapi import WebSocket
import json


class ConnectionManager:
    """
    Manages WebSocket connections for real-time chat and notifications.
    
    Connection Flow:
    1. Client connects with JWT token in query params
    2. Server validates token and registers connection
    3. Server can send messages to specific users
    4. On disconnect, connection is cleaned up
    """
    
    def __init__(self):
        # Map user_id -> set of WebSocket connections (supports multiple tabs/devices)
        self.active_connections: Dict[int, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        """Register user connection (websocket already accepted)."""
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
    
    def disconnect(self, websocket: WebSocket, user_id: int):
        """Remove connection for user."""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
    
    def is_online(self, user_id: int) -> bool:
        """Check if user has any active connections."""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0
    
    async def send_personal_message(self, user_id: int, message: dict):
        """Send message to all connections of a specific user."""
        if user_id in self.active_connections:
            message_text = json.dumps(message)
            dead_connections = set()
            
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message_text)
                except Exception:
                    dead_connections.add(connection)
            
            # Clean up dead connections
            for conn in dead_connections:
                self.active_connections[user_id].discard(conn)
    
    async def broadcast_to_users(self, user_ids: list, message: dict):
        """Send message to multiple users."""
        for user_id in user_ids:
            await self.send_personal_message(user_id, message)
    
    def get_online_users(self, user_ids: list) -> list:
        """Get list of online users from given user IDs."""
        return [uid for uid in user_ids if self.is_online(uid)]


# Global connection manager instance
manager = ConnectionManager()
