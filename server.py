from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import random
import json
import datetime

app = FastAPI()


html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
    </head>
    <body>
        <h1>Датчик температуры</h1>
        <text>Используйте команды для управлением передачей данных:<br>
        start - чтобы начать<br>
        stop - чтобы остановить
        </text>
        <form action="" onsubmit="sendMessage(event)">
            <input type="text" id="messageText" autocomplete="off"/>
            <button>Send</button>
        </form>
        <ul id='messages'>
        </ul>
        <script>
            var ws = new WebSocket("ws://localhost:8000/ws");
            ws.onmessage = function(event) {
                var messages = document.getElementById('messages')
                var message = document.createElement('li')
                var content = document.createTextNode(event.data)
                message.appendChild(content)
                messages.appendChild(message)
            };
            function sendMessage(event) {
                var input = document.getElementById("messageText")
                ws.send(input.value)
                input.value = ''
                event.preventDefault()
            }
        </script>
    </body>
</html>
"""


async def generate_data():
    """Симулирует датчик темературы"""
    ids = 0
    while True:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rate = random.choice([-1, 1])
        value = 150 + rate
        data = {
            'time': now,
            'value': value
        }
        ids += 1
        yield data, ids
        await asyncio.sleep(1)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


@app.get("/")
async def get():
    return HTMLResponse(html)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    generator_task = None
    try:
        while True:
            data = await websocket.receive_text()
            json_data = {
                "jsonrpc": "2.0",
                "method": data,
                "params": "",
                "id": 5
            }
            data = json.dumps(json_data)
            try:
                data = json.loads(data)
                jsonrpc_version = data.get("jsonrpc")
                method = data.get("method")
                params = data.get("params")
                message_id = data.get("id")

                if jsonrpc_version != "2.0":
                    await send_error_response(websocket, "Invalid JSON-RPC version", -32600,
                                              message_id)
                    continue

                if method == 'start':
                    if generator_task and not generator_task.done():
                        await send_error_response(websocket, "Generator already running", -32602,
                                                  message_id)
                        continue

                    async def send_data():
                        try:
                            async for data in generate_data():
                                response = {
                                    "jsonrpc": "2.0",
                                    "result": data,
                                    "id": message_id
                                }
                                await websocket.send_text(json.dumps(response))
                        except asyncio.CancelledError:
                            print('Датчик не передает показания')
                        except WebSocketDisconnect:
                            print('Подключение разорвано')

                    generator_task = asyncio.create_task(send_data())

                elif method == 'stop':
                    if generator_task:
                        generator_task.cancel()
                        try:
                            await generator_task
                        except asyncio.CancelledError:
                            pass
                        generator_task = None
                    else:
                        await send_error_response(websocket,
                                                  "Generator not running", -32602,
                                                  message_id
                                                  )
                        
                else:
                    await send_error_response(websocket, "Method not found", -32601,
                                              message_id)
         
            except json.JSONDecodeError:
                await send_error_response(websocket, "Invalid JSON", -32700,
                                          None)
            except WebSocketDisconnect:
                print("Client disconnected")
                break

    finally:
        if generator_task:
            generator_task.cancel()
            try:
                await generator_task
            except asyncio.CancelledError:
                pass
        print('Подключение закрыто')


async def send_success_response(websocket: WebSocket, result: any, id: any):
    """Отправляет успешный JSON-RPC ответ."""
    response = {
        "jsonrpc": "2.0",
        "result": result,
        "id": id
    }
    await websocket.send_text(json.dumps(response))


async def send_error_response(websocket: WebSocket, message: str, code: int, id: any):
    """Отправляет JSON-RPC ответ с ошибкой."""
    response = {
        "jsonrpc": "2.0",
        "error": {
            "code": code,
            "message": message
        },
        "id": id
    }
    await websocket.send_text(json.dumps(response))