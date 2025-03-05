import asyncio
import websockets

async def handle_client(websocket):
    print(f"Client connected from {websocket.remote_address}!")
    
    async def send_heartbeat():
        counter = 0
        while True:
            try:
                await websocket.send("heartbeat")
                print(f"Sent heartbeat #{counter}")
                counter += 1
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                break

    try:
        heartbeat_task = asyncio.create_task(send_heartbeat())
        async for message in websocket:
            print(f"Received raw message: {message}")
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    finally:
        heartbeat_task.cancel()

async def main():
    try:
        server = await websockets.serve(
            handle_client,
            "10.10.10.10",
            5000
        )
        print("WebSocket server started on ws://10.10.10.10:5000")
        await server.wait_closed()
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
