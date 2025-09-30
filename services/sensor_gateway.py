from fastapi import FastAPI, WebSocket
import json
import asyncio
import logging
from redis_client import redis
from metrics import ACTIVE_SENSORS

app = FastAPI()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sensor-gateway")


@app.websocket("/ws/sensor")
async def websocket_sensor(websocket: WebSocket):
    await websocket.accept()
    sensor_id = None
    try:
        init_message = await websocket.receive_text()
        data = json.loads(init_message)
        sensor_id = data.get("sensor_id")
        if not sensor_id:
            await websocket.close(reason="No sensor ID provided")
            logger.warning("Датчик не предоставил ID, подключение отклонено")
            return
        await redis.hset("connected_sensors", sensor_id, "1")
        ACTIVE_SENSORS.inc()
        logger.info(f"Датчик {sensor_id} подключен")

        async def listen_commands():
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"command:{sensor_id}")
            try:
                async for msg in pubsub.listen():
                    logger.info(f"MSG: {msg}")
                    if msg["type"] == "message":
                        try:
                            cmd_data = json.loads(msg["data"])
                            cmd = cmd_data.get("cmd")
                            if cmd in ("start", "stop"):
                                await websocket.send_text(json.dumps({
                                    "jsonrpc": "2.0",
                                    "method": cmd
                                }))
                        except Exception as e:
                            logger.error(f"Ошибка отправки команды {sensor_id}: {e}")
            finally:
                await pubsub.close()

        asyncio.create_task(listen_commands())

        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
                if msg.get("jsonrpc") == "2.0":
                    result = msg["result"]
                    if isinstance(result, dict):
                        result["sensor_id"] = sensor_id
                        await redis.publish("all_sensors", json.dumps({
                            "jsonrpc": "2.0",
                            "result": result
                        }))
                        # logger.info(f"Опубликовано в Redis: {result}")
                    else:
                        logger.warning(f"Неверный тип 'result': {type(result)} в сообщении: {raw_data}")
                else:
                    logger.warning(f"Неверный формат от {sensor_id}: {raw_data}")

            except json.JSONDecodeError:
                logger.warning(
                    f"Некорректный JSON от датчика "
                    f"{sensor_id}: {raw_data}"
                )
    except Exception as e:
        logger.error(f"Ошибка датчика {sensor_id}: {e}")
    finally:
        if sensor_id:
            await redis.hdel("connected_sensors", sensor_id)
            ACTIVE_SENSORS.dec()
            logger.info(f"Датчик {sensor_id} отключен")


if __name__ == "__main__":
    import uvicorn
    import os
    from dotenv import load_dotenv
    load_dotenv()

    host = os.getenv("SENSOR_GATEWAY_HOST")
    port = int(os.getenv("SENSOR_GATEWAY_PORT"))
    log_level = os.getenv("LOG_LEVEL", "info")

    uvicorn.run(
        "sensor_gateway:app",
        host=host,
        port=port,
        log_level=log_level.lower(),
        reload=True
    )