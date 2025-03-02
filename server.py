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
    while True:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rate = random.choice([-1, 1])
        value = 150 + rate
        data = {
            'time': now,
            'value': value
        }
        yield json.dumps(data)
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
    while True:
        data = await websocket.receive_text()

        if data == 'start':
            async def send_data():
                async for data in generate_data():
                    await websocket.send_text(f'data: {data}')

            generator_task = asyncio.create_task(send_data())
            await websocket.send_text("Началась передача показаний")

        elif data == "stop":
            if generator_task:
                generator_task.cancel()
                try:
                    await generator_task
                except asyncio.CancelledError:
                    pass
                    await websocket.send_text("Передача остановлена")
                    generator_task = None
            else:
                await websocket.send_text("Передача показаний не запущена")

        else:
            await websocket.send_text(
                f'Ваша команда: {data}. Используйте start/stop для управления')
