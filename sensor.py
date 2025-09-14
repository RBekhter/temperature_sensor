import asyncio
import websockets
import json
import datetime
import random


running = False


async def generate_data(websocket):
    while True:
        if running:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rate = random.choice([-1, 0, 1])
            value = 150 + rate
            data = {
                'timestamp': now,
                'value': value
            }
            try:
                await websocket.send(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "result": data
                    })
                )
                print(f"Отправлено: {data}")
            except websockets.exceptions.ConnectionClosed:
                break
        await asyncio.sleep(1)


async def listen_for_commands(websocket):
    global running
    while True:
        try:
            message = await websocket.recv()
            try:
                cmd = json.loads(message)
                if cmd.get("jsonrpc") != "2.0":
                    continue
                method = cmd.get("method")
                msg_id = cmd.get("id", None)
                if method == "start":
                    running = True
                    print("Датчик запущен")
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
                    print("Датчик остановлен")
            except json.JSONDecodeError:
                print("Ошибка парсинга JSON")
        except (websockets.exceptions.ConnectionClosed, json.JSONDecodeError):
            break


async def run():
    uri = "ws://localhost:8000/ws/sensor"
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("Датчик подключился к серверу")
                await asyncio.gather(
                    listen_for_commands(websocket),
                    generate_data(websocket)
                )
        except Exception as e:
            print(f"Потеряно соединение с сервером: {e}. Повторное подключение через 3 сек...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Датчик остановлен")
