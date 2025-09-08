from typing import Dict
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

sensor_websocket: WebSocket = None


@app.get("/client")
async def get_client():
    with open("client.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.client_states: Dict[WebSocket, Dict] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.client_states[websocket] = {
            "subscribed": None
        }

    def disconnect(self, websocket: WebSocket):
        if websocket in self.client_states:
            del self.client_states[websocket]
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except WebSocketDisconnect:
                self.disconnect(conn)


manager = ConnectionManager()


@app.websocket("/ws/client")
async def websocket_client(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg_id = 1
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
                    await sensor_websocket.send_text(
                        json.dumps({
                            "jsonrpc": "2.0",
                            "method": "start",
                            "id": 1
                        })
                    )
                    cmd = {"jsonrpc": "2.0", "method": "start", "id": 1}
                    await websocket.send_text(json.dumps(cmd))
                    manager.client_states[websocket]["subscribed"] = True
                    await send_success(websocket, "Start command sent", msg_id)
            elif method == "stop":
                if sensor_websocket is None:
                    await send_error(websocket, "No sensor connected", -32001, msg_id)
                else:
                    await sensor_websocket.send_text(
                        json.dumps({
                            "jsonrpc": "2.0",
                            "method": "stop",
                            "id": 1
                        })
                    )
                    cmd = {"jsonrpc": "2.0", "method": "stop", "id": 1}
                    await sensor_websocket.send_text(json.dumps(cmd))
                    manager.client_states[websocket]["subscribed"] = False
                    await send_success(websocket, "Stop command sent", msg_id)
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
    """Датчик подключается сюда и отправляет данные"""
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
                # msg_id = data.get("id")
                msg_id = 1
                result = data.get("result")
                await manager.broadcast(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": msg_id
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
