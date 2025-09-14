from typing import Dict
import json
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

sensor_websocket: WebSocket = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.client_states: Dict[WebSocket, Dict] = {}
        self.subscriber_count = 0

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.client_states[websocket] = {
            "subscribed": False
        }

    def disconnect(self, websocket: WebSocket):
        if websocket in self.client_states:
            if self.client_states[websocket]["subscribed"]:
                self.subscriber_count -= 1
                if self.subscriber_count == 0:
                    asyncio.create_task(self._notify_sensor_stop())
            del self.client_states[websocket]
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for conn in self.active_connections:
            if self.client_states[conn]["subscribed"]:
                try:
                    await conn.send_text(message)
                except WebSocketDisconnect:
                    self.disconnect(conn)

    def client_subscribe(self, websocket: WebSocket):
        state = self.client_states.get(websocket)
        if state and not state["subscribed"]:
            state["subscribed"] = True
            self.subscriber_count += 1
            if self.subscriber_count == 1:
                asyncio.create_task(self._notify_sensor_start())

    def client_unsubscribe(self, websocket: WebSocket):
        state = self.client_states.get(websocket)
        if state and state["subscribed"]:
            state["subscribed"] = False
            self.subscriber_count -= 1
            if self.subscriber_count == 0:
                asyncio.create_task(self._notify_sensor_stop())

    async def _notify_sensor_start(self):
        global sensor_websocket
        if sensor_websocket is not None:
            try:
                await sensor_websocket.send_text(
                    json.dumps({"jsonrpc": "2.0", "method": "start"})
                )
            except WebSocketDisconnect:
                sensor_websocket = None

    async def _notify_sensor_stop(self):
        global sensor_websocket
        if sensor_websocket is not None:
            try:
                await sensor_websocket.send_text(
                    json.dumps({"jsonrpc": "2.0", "method": "stop"})
                )
            except WebSocketDisconnect:
                sensor_websocket = None


manager = ConnectionManager()


@app.get("/client")
async def get_client():
    with open("client.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/client")
async def websocket_client(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                request = json.loads(data)
            except json.JSONDecodeError:
                await send_error(websocket, "Invalid JSON", -32700, None)
                continue
            if request.get("jsonrpc") != "2.0":
                await send_error(websocket, "Invalid JSON-RPC version", -32600, None)
                continue
            method = request.get("method")
            msg_id = request.get("id")

            if method == "start":
                if sensor_websocket is None:
                    await send_error(websocket, "No sensor connected", -32001, msg_id)
                else:
                    manager.client_subscribe(websocket)
            elif method == "stop":
                if sensor_websocket is None:
                    await send_error(websocket, "No sensor connected", -32001, msg_id)
                manager.client_unsubscribe(websocket)
            elif method == "disconnect":
                await send_success(websocket, "Disconnected", msg_id)
                await websocket.close()
                break
            else:
                await send_error(websocket, "Method not found", -32601, msg_id)
    except WebSocketDisconnect:
        print("Клиент отключился")
    finally:
        manager.disconnect(websocket)
        print('Подключение закрыто')


@app.websocket("/ws/sensor")
async def websocket_sensor(websocket: WebSocket):
    global sensor_websocket
    await websocket.accept()
    print("Датчик подключён")
    sensor_websocket = websocket
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                print("Некорректный JSON от датчика:", raw_data)
                continue
            if "result" in data and isinstance(data["result"], dict):
                result = data.get("result")
                await manager.broadcast(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "result": result,
                    })
                )
    except WebSocketDisconnect:
        print("Датчик отключён")
        sensor_websocket = None


async def send_success(websocket: WebSocket, result: any, msg_id: any):
    if msg_id is None:
        return
    await websocket.send_text(
        json.dumps({"jsonrpc": "2.0", "result": result, "id": msg_id})
    )


async def send_error(websocket: WebSocket, message: str, code: int, msg_id: any):
    response = {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": msg_id
    }
    await websocket.send_text(json.dumps(response))
