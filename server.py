import asyncio
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

connected_sensors: Dict[str, WebSocket] = {}

handler = TimedRotatingFileHandler(
    "server.log",
    when="midnight",
    interval=1
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s: %(message)s',
    handlers=[
        handler,
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("Server")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.client_states: Dict[WebSocket, Dict] = {}
        self.subscriber_counts: Dict[str, int] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.client_states[websocket] = {
            "subscribed_to": set()
        }

    def disconnect(self, websocket: WebSocket):
        if websocket not in self.client_states:
            return
        state = self.client_states.get(websocket)
        if state:
            subscribed_sensors = list(state.get("subscribed_to", set()))
            for sensor_id in subscribed_sensors:
                self.client_unsubscribe(websocket, sensor_id)
        self.client_states.pop(websocket, None)
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    @staticmethod
    async def send_message(message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, sensor_id: str, message: str):
        for conn in self.active_connections:
            state = self.client_states.get(conn)
            if not state:
                continue
            if sensor_id in state.get("subscribed_to", set()):
                try:
                    await conn.send_text(message)
                except WebSocketDisconnect:
                    self.disconnect(conn)

    def client_subscribe(self, websocket: WebSocket, sensor_id: str):
        state = self.client_states.get(websocket)
        if not state:
            return
        if sensor_id in state["subscribed_to"]:
            return
        state["subscribed_to"].add(sensor_id)
        self.subscriber_counts[sensor_id] = (
            self.subscriber_counts.get(sensor_id, 0) + 1
        )
        current_count = self.subscriber_counts[sensor_id]
        logger.info(f"На датчик {sensor_id} подписано: {current_count}")
        if current_count == 1:
            asyncio.create_task(self._notify_sensor_start(sensor_id))

    def client_unsubscribe(self, websocket: WebSocket, sensor_id: str):
        state = self.client_states.get(websocket)
        if not state:
            return
        if sensor_id not in state["subscribed_to"]:
            return
        state["subscribed_to"].discard(sensor_id)
        self.subscriber_counts[sensor_id] = (
            max(0, self.subscriber_counts.get(sensor_id, 0) - 1)
        )
        current_count = self.subscriber_counts[sensor_id]
        logger.info(f"На датчик {sensor_id} подписано: {current_count}")
        if current_count == 0:
            asyncio.create_task(self._notify_sensor_stop(sensor_id))

    @staticmethod
    async def _notify_sensor_start(sensor_id: str):
        global connected_sensors
        sensor_ws = connected_sensors.get(sensor_id)
        if sensor_ws is None:
            logger.warning(
                f"Невозможно отправить start: датчик {sensor_id} не подключен"
            )
            return
        try:
            await sensor_ws.send_text(
                json.dumps({"jsonrpc": "2.0", "method": "start"})
            )
        except WebSocketDisconnect:
            connected_sensors.pop(sensor_id, None)

    @staticmethod
    async def _notify_sensor_stop(sensor_id: str):
        global connected_sensors
        sensor_ws = connected_sensors.get(sensor_id)
        if sensor_ws is None:
            return
        try:
            await sensor_ws.send_text(
                json.dumps({"jsonrpc": "2.0", "method": "stop"})
            )
        except WebSocketDisconnect:
            connected_sensors.pop(sensor_id, None)


manager = ConnectionManager()


@app.get("/client")
async def get_client():
    with open("client.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/client")
async def websocket_client(websocket: WebSocket):
    global connected_sensors
    client_id = id(websocket)
    await manager.connect(websocket)
    logger.info(f"[Client#{client_id}] подключен")
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"[Client#{client_id}] получено: '{data}'")
            try:
                request = json.loads(data)
            except json.JSONDecodeError:
                await send_error(websocket, "Invalid JSON", -32700, None)
                continue
            if request.get("jsonrpc") != "2.0":
                await send_error(
                    websocket,
                    "Invalid JSON-RPC version",
                    -32600,
                    None
                )
                continue
            method = request.get("method")
            msg_id = request.get("id")
            params = request.get("params", {})
            sensor_id = params.get("sensor_id")
            if not sensor_id:
                await send_error(
                    websocket,
                    "Missing 'sensor_id' in params",
                    -32602,
                    msg_id
                )
                continue
            if connected_sensors.get(sensor_id) is None:
                logger.warning(
                    f"Невозможно отправить команду start: "
                    f"датчик {sensor_id} не подключен"
                )
                await send_error(
                    websocket,
                    f"Sensor '{sensor_id}' not connected",
                    -32001,
                    msg_id
                )
                continue
            logger.info(f"{client_id} отправил {method} датчику: {sensor_id}")
            if method == "start":
                manager.client_subscribe(websocket, sensor_id)
                await send_success(
                    websocket,
                    f"Subscribed to sensor {sensor_id}",
                    msg_id
                )
            elif method == "stop":
                manager.client_unsubscribe(websocket, sensor_id)
            else:
                logger.warning(f"Неизвестная команда '{method}'")
                await send_error(websocket, "Method not found", -32601, msg_id)
    except WebSocketDisconnect:
        logger.info(f"Клиент {client_id} отключился")
    finally:
        manager.disconnect(websocket)
        logger.info(f"Подключение с {client_id} закрыто")


@app.websocket("/ws/sensor")
async def websocket_sensor(websocket: WebSocket):
    global connected_sensors
    await websocket.accept()
    try:
        init_message = await websocket.receive_text()
        data = json.loads(init_message)
        sensor_id = data.get("sensor_id")
        if not sensor_id:
            await websocket.close(reason="No sensor ID provided")
            logger.warning("Датчик не предоставил ID, подключение отклонено")
            return
        connected_sensors[sensor_id] = websocket
        logger.info(f"Датчик {sensor_id} подключен")
        try:
            while True:
                raw_data = await websocket.receive_text()
                try:
                    data = json.loads(raw_data)
                    data["sensor_id"] = sensor_id
                except json.JSONDecodeError:
                    logger.warning(
                        f"Некорректные данные от датчика "
                        f"{sensor_id}: {raw_data}"
                    )
                    continue
                if "result" in data and isinstance(data["result"], dict):
                    result = data.get("result")
                    message = json.dumps({
                            "jsonrpc": "2.0",
                            "result": result,
                        })
                    await manager.broadcast(
                        sensor_id, message
                    )
        except WebSocketDisconnect:
            if sensor_id in connected_sensors:
                del connected_sensors[sensor_id]
            logger.info(f"Датчик {sensor_id} отключен")

    except Exception as e:
        logger.error(f"Ошибка в соединении с датчиком: {e}")


async def send_success(websocket: WebSocket, result: any, msg_id: any):
    if msg_id is None:
        return
    await websocket.send_text(
        json.dumps({"jsonrpc": "2.0", "result": result, "id": msg_id})
    )


async def send_error(
        websocket: WebSocket,
        message: str,
        code: int,
        msg_id: any):
    response = {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": msg_id
    }
    await websocket.send_text(json.dumps(response))
