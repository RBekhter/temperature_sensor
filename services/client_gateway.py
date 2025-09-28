from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json
import os
from pathlib import Path
import asyncio
import logging
from services.redis_client import redis

app = FastAPI()


client_connections = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("client-gateway")

BASE_DIR = Path(__file__).resolve().parent.parent

@app.get("/client")
async def get_client():
    file_path = os.path.join(BASE_DIR, "client.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/client")
async def websocket_client(websocket: WebSocket):
    await websocket.accept()
    client_id = None
    try:
        init_data = await websocket.receive_text()
        try:
            init_msg = json.loads(init_data)
            if init_msg.get("method") != "init":
                await send_error(websocket, "First message must be 'init'", -32600, init_msg.get("id"))
                return
            client_id = init_msg.get("params", {}).get("client_id")
            if not client_id:
                await send_error(websocket, "Missing 'client_id' in init", -32602, init_msg.get("id"))
                return
        except json.JSONDecodeError:
            await websocket.close(code=1003, reason="Invalid init JSON")
            return

        client_connections[client_id] = websocket
        logger.info(f"[Client#{client_id}] подключен")

        while True:
            data = await websocket.receive_text()
            # logger.info(f"[Client#{client_id}] получено: '{data}'")
            logger.debug(f"[Client#{client_id}] получено: '{data}'")
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
            is_connected = await redis.hexists("connected_sensors", sensor_id)
            if not is_connected:
                logger.warning(f"Датчик {sensor_id} не подключен")
                await send_error(websocket, f"Sensor '{sensor_id}' not connected", -32001, msg_id)
                continue
            logger.info(f"{client_id} отправил {method} датчику: {sensor_id}")
            if method == "start":
                already_subscribed = await redis.sismember(f"client:{client_id}:subscriptions", sensor_id)
                if not already_subscribed:
                    await redis.sadd(f"client:{client_id}:subscriptions", sensor_id)
                    await redis.sadd(f"sensor:{sensor_id}:subscribers", client_id)
                    count = await redis.hincrby("subscriber_counts", sensor_id, 1)
                    logger.info(f"Подписчиков на {sensor_id}: {count}")
                    if count == 1:
                        await redis.publish(f"command:{sensor_id}", json.dumps({"cmd": "start"}))
                await send_success(
                    websocket,
                    f"Subscribed to sensor {sensor_id}",
                    msg_id
                )
            elif method == "stop":
                is_subscribed = await redis.sismember(f"client:{client_id}:subscriptions", sensor_id)
                if is_subscribed:
                    await redis.srem(f"client:{client_id}:subscriptions", sensor_id)
                    await redis.srem(f"sensor:{sensor_id}:subscribers", client_id)
                    current = await redis.hget("subscriber_counts", sensor_id)
                    if current and int(current) > 0:
                        count = await redis.hincrby("subscriber_counts", sensor_id, -1)
                        logger.info(f"Подписчиков на {sensor_id}: {count}")
                        if count == 0:
                            await redis.publish(f"command:{sensor_id}", json.dumps({"cmd": "stop"}))
            else:
                logger.warning(f"Неизвестная команда '{method}'")
                await send_error(websocket, "Method not found", -32601, msg_id)
    except WebSocketDisconnect:
        logger.info(f"Клиент {client_id} отключился")
    finally:
        if client_id:
            subscriptions = await redis.smembers(f"client:{client_id}:subscriptions")
            for sensor_id in subscriptions:
                # Удаляем из обратного индекса
                await redis.srem(f"sensor:{sensor_id}:subscribers", client_id)
                # Уменьшаем счётчик
                current = await redis.hget("subscriber_counts", sensor_id)
                if current and int(current) > 0:
                    count = await redis.hincrby("subscriber_counts", sensor_id, -1)
                    if count == 0:
                        await redis.publish(f"command:{sensor_id}", json.dumps({"cmd": "stop"}))

            await redis.delete(f"client:{client_id}:subscriptions")
            client_connections.pop(client_id, None)
            logger.info(f"Подключение с {client_id} закрыто")


@app.on_event("startup")
async def start_sensor_listener():
    pubsub = redis.pubsub()
    await pubsub.subscribe("all_sensors")

    async def listen():
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    # logger.info(f"Получено из Redis: {message['data']}")
                    data = json.loads(message["data"])
                    sensor_id = data.get("result", {}).get("sensor_id")
                    if not sensor_id:
                        logger.warning(f"Ошибка в sensor ID {sensor_id}: {e}")
                        continue
                    subscribers = await redis.smembers(f"sensor:{sensor_id}:subscribers")
                    for client_id in subscribers:
                        ws = client_connections.get(client_id)
                        if ws:
                            try:
                                await ws.send_text(json.dumps({
                                    "jsonrpc": "2.0",
                                    "result": data
                                }))
                            except Exception as e:
                                logger.warning(f"Ошибка отправки клиенту {client_id}: {e}")
                except Exception as e:
                    logger.error(f"Ошибка обработки сообщения: {e}")

    asyncio.create_task(listen())


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