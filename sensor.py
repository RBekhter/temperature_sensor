import asyncio
import websockets
import json
import datetime
import random


running = False
SENSOR_ID = "123"


async def generate_data(websocket, sensor_id):
    while True:
        if running:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rate = random.choice([-1, 0, 1])
            value = 150 + rate
            data = {
                'timestamp': now,
                'value': value,
                "sensor_id": sensor_id
            }
            await websocket.send(
                json.dumps({
                    "jsonrpc": "2.0",
                    "result": data
                })
            )
            print(f"Отправлено: {data}")
        await asyncio.sleep(1)


async def listen_for_commands(websocket):
    global running
    while True:
        message = await websocket.recv()
        try:
            cmd = json.loads(message)
            if cmd.get("jsonrpc") != "2.0":
                continue
            method = cmd.get("method")
            msg_id = cmd.get("id", None)
            if method == "start":
                running = True
                print(f"Датчик {SENSOR_ID} запущен")
                await websocket.send(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "result": "Sensor started",
                        "id": msg_id
                    })
                )
            elif method == "stop":
                running = False
                await websocket.send(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "result": "Sensor stopped",
                        "id": msg_id
                    })
                )
                print(f"Датчик {SENSOR_ID} остановлен")
        except json.JSONDecodeError:
            print("Ошибка парсинга JSON")


async def run():
    uri = "ws://localhost:8000/ws/sensor"
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                await websocket.send(json.dumps({"sensor_id": SENSOR_ID}))
                print(f"Датчик {SENSOR_ID} подключился к серверу")
                await asyncio.gather(
                    listen_for_commands(websocket),
                    generate_data(websocket, SENSOR_ID)
                )
        except Exception as e:
            print(f"Потеряно соединение с сервером: {e}. "
                  f"Повторное подключение через 3 сек...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Датчик остановлен")
