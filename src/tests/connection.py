# This script mocks the websocket server for the Manafish App. Run it to check that you can connect to it sucessfully via websockets.

import asyncio
import json
import time
import websockets
import math
import signal

clients = set()
shutdown = False

pitch_stabilization = False
roll_stabilization = False
depth_stabilization = False

on_going_thruster_tests = {}
on_going_regulator_autotune = None

rov_config = {
    "fluidType": "saltwater",
    "thrusterPinSetup": {
        "identifiers": [5, 4, 3, 1, 2, 7, 6, 8],
        "spinDirections": [1, -1, 1, -1, 1, -1, 1, -1],
    },
    "thrusterAllocation": [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    ],
    "regulator": {
        "turnSpeed": 40,
        "pitch": {"kp": 1, "ki": 0.0, "kd": 0.0},
        "roll": {"kp": 5, "ki": 0.0, "kd": 0.0},
        "depth": {"kp": 8, "ki": 2.8, "kd": 0.0},
    },
    "movementCoefficients": {
        "horizontal": 0.0,
        "strafe": 0.0,
        "vertical": 0.0,
        "pitch": 0.0,
        "yaw": 0.0,
        "roll": 0.0,
    },
    "power": {
        "userMaxPower": 1.0,
        "regulatorMaxPower": 1.0,
        "batteryMinVoltage": 10.0,
        "batteryMaxVoltage": 16.8,
    },
}


async def log(level, message):
    log_msg = {
        "type": "logMessage",
        "payload": {"origin": "firmware", "level": level, "message": str(message)},
    }
    if clients:
        await asyncio.gather(
            *[client.send(json.dumps(log_msg)) for client in clients],
            return_exceptions=True,
        )
    else:
        print(f"[{level}] {message}")


async def toast(id, toast_type, message, description, cancel):
    toast_msg = {
        "type": "showToast",
        "payload": {
            "id": id,
            "toastType": toast_type,
            "message": message,
            "description": description,
            "cancel": cancel,
        },
    }
    if clients:
        await asyncio.gather(
            *[client.send(json.dumps(toast_msg)) for client in clients],
            return_exceptions=True,
        )


async def handle_client(websocket):
    global rov_config, pitch_stabilization, roll_stabilization, depth_stabilization
    last_movement_command = None
    await log(
        "info", f"Client connected from Manafish App at {websocket.remote_address}!"
    )
    clients.add(websocket)

    async def send_telemetry():
        while not shutdown:
            try:
                current_time = time.time()

                pitch = 20 * math.sin(current_time / 2)
                roll = 15 * math.cos(current_time / 3)
                desired_pitch = 25 * math.sin(current_time / 2)
                desired_roll = 20 * math.cos(current_time / 3)
                depth = 10 + 5 * math.sin(current_time / 4)
                temperature = 20 + 5 * math.cos(current_time / 5)
                thruster_erpm_values = [0, 937, 1875, 3750, 7500, 15000, 30000, 60000]

                status_msg = {
                    "type": "telemetry",
                    "payload": {
                        "pitch": round(pitch, 2),
                        "roll": round(roll, 2),
                        "desiredPitch": round(desired_pitch, 2),
                        "desiredRoll": round(desired_roll, 2),
                        "depth": round(depth, 2),
                        "temperature": round(temperature, 2),
                        "thrusterErpms": thruster_erpm_values,
                    },
                }
                await websocket.send(json.dumps(status_msg))
                await asyncio.sleep(1 / 60)
            except Exception as e:
                if not shutdown:
                    await log("Error", f"Telemetry error: {e}")
                break

    async def send_status_update():
        while not shutdown:
            try:
                current_time = time.time()
                battery_percentage = int((math.sin(current_time / 5) + 1) * 50)
                states_msg = {
                    "type": "statusUpdate",
                    "payload": {
                        "pitchStabilization": pitch_stabilization,
                        "rollStabilization": roll_stabilization,
                        "depthStabilization": depth_stabilization,
                        "batteryPercentage": battery_percentage,
                    },
                }
                await websocket.send(json.dumps(states_msg))
                await asyncio.sleep(0.5)
            except Exception as e:
                if not shutdown:
                    await log("error", f"Status update error: {e}")
                break

    telemetry_task = asyncio.create_task(send_telemetry())
    status_task = asyncio.create_task(send_status_update())

    try:
        await asyncio.sleep(5)

        firmware_msg = {
            "type": "firmwareVersion",
            "payload": "0.6.9",
        }
        await websocket.send(json.dumps(firmware_msg))

        config_msg = {
            "type": "config",
            "payload": rov_config,
        }
        await websocket.send(json.dumps(config_msg))

        async for message in websocket:
            if shutdown:
                break
            try:
                msg_data = json.loads(message)
                msg_type = msg_data.get("type")
                payload = msg_data.get("payload")

                if msg_type == "movementCommand":
                    if (
                        last_movement_command is not None
                        and payload != last_movement_command
                    ):
                        await log(
                            "info",
                            f"MovementCommand changed: old={last_movement_command}, new={payload}",
                        )
                    last_movement_command = payload
                elif msg_type == "getConfig":
                    await log("info", "Sending full ROV config")
                    config_msg = {
                        "type": "config",
                        "payload": rov_config,
                    }
                    await websocket.send(json.dumps(config_msg))
                elif msg_type == "setConfig":
                    rov_config = payload
                    await log("info", f"ROV config updated: {rov_config}")
                    await toast(
                        None, "success", "ROV config set successfully", None, None
                    )
                elif msg_type == "startThrusterTest":
                    thruster_id = payload

                    async def test_thruster_task(thruster_id):
                        try:
                            await log(
                                "info",
                                f"Testing thruster with identifier: {thruster_id}",
                            )
                            for i in range(1, 11):
                                progress = i * 10
                                await toast(
                                    "test",
                                    "loading",
                                    f"Testing thruster {thruster_id} {progress}%",
                                    None,
                                    {
                                        "command": "cancelThrusterTest",
                                        "payload": thruster_id,
                                    },
                                )
                                if i < 10:
                                    await asyncio.sleep(1)
                            await toast(
                                "test",
                                "success",
                                f"Finished testing thruster {thruster_id}",
                                None,
                                None,
                            )
                        except asyncio.CancelledError:
                            pass
                        finally:
                            on_going_thruster_tests.pop(thruster_id, None)

                    existing = on_going_thruster_tests.get(thruster_id)
                    if existing:
                        existing.cancel()
                    task = asyncio.create_task(test_thruster_task(thruster_id))
                    on_going_thruster_tests[thruster_id] = task
                elif msg_type == "cancelThrusterTest":
                    thruster_id = payload
                    task = on_going_thruster_tests.get(thruster_id)
                    if task:
                        task.cancel()
                elif msg_type == "startRegulatorAutoTuning":
                    global on_going_regulator_autotune
                    if on_going_regulator_autotune:
                        on_going_regulator_autotune.cancel()

                    async def regulator_autotune_task():
                        try:
                            await log("info", "Auto-tuning started")
                            for i in range(1, 11):
                                progress = i * 10
                                await toast(
                                    "autotune",
                                    "loading",
                                    f"Regulator auto-tuning {progress}%",
                                    None,
                                    {"command": "cancelRegulatorAutoTuning"},
                                )
                                if i < 10:
                                    await asyncio.sleep(1)
                            await toast(
                                "autotune",
                                "success",
                                "Regulator auto-tuning finished",
                                None,
                                None,
                            )
                            suggestions = {
                                "pitch": {"kp": 0.65, "ki": 0.18, "kd": 0.09},
                                "roll": {"kp": 0.5, "ki": 0.15, "kd": 0.07},
                                "depth": {"kp": 0.8, "ki": 0.22, "kd": 0.11},
                            }
                            regulator_msg = {
                                "type": "regulatorSuggestions",
                                "payload": suggestions,
                            }
                            if clients:
                                await asyncio.gather(
                                    *[
                                        client.send(json.dumps(regulator_msg))
                                        for client in clients
                                    ],
                                    return_exceptions=True,
                                )
                        except asyncio.CancelledError:
                            pass
                        finally:
                            global on_going_regulator_autotune
                            on_going_regulator_autotune = None

                    on_going_regulator_autotune = asyncio.create_task(
                        regulator_autotune_task()
                    )
                elif msg_type == "cancelRegulatorAutoTuning":
                    if on_going_regulator_autotune:
                        on_going_regulator_autotune.cancel()
                    await log("info", "Auto-tuning cancelled")
                elif msg_type == "runAction1":
                    await log("info", "Run Action 1 triggered")
                elif msg_type == "runAction2":
                    await log("info", "Run Action 2 triggered")
                elif msg_type == "togglePitchStabilization":
                    pitch_stabilization = not pitch_stabilization
                    await log(
                        "info", f"Pitch stabilization set to {pitch_stabilization}"
                    )
                elif msg_type == "toggleRollStabilization":
                    roll_stabilization = not roll_stabilization
                    await log("info", f"Roll stabilization set to {roll_stabilization}")
                elif msg_type == "toggleDepthStabilization":
                    depth_stabilization = not depth_stabilization
                    await log(
                        "info", f"Depth stabilization set to {depth_stabilization}"
                    )
                else:
                    await log(
                        "warn",
                        f"Unhandled message type: {msg_type} with payload: {payload}",
                    )
            except json.JSONDecodeError:
                await log("warn", f"Received non-JSON message: {message}")

    except Exception as e:
        if not shutdown:
            await log("info", f"Client disconnected: {e}")
    finally:
        clients.remove(websocket)
        telemetry_task.cancel()
        status_task.cancel()


async def shutdown_server(server):
    global shutdown
    shutdown = True
    if clients:
        await log("info", "Closing client connections...")
        await asyncio.gather(*(ws.close() for ws in clients))
    await log("info", "Stopping server...")
    server.close()
    await server.wait_closed()


async def main():
    server = None
    shutdown_event = asyncio.Event()

    def signal_handler():
        if not clients:
            print("[info] Shutdown signal received")
        else:
            asyncio.create_task(log("info", "Shutdown signal received"))
        shutdown_event.set()

    try:
        server = await websockets.serve(handle_client, "10.10.10.10", 9000)
        if not clients:
            print("[info] Test server running on 10.10.10.10:9000")
        else:
            await log("info", "Test server running on 10.10.10.10:9000")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        await shutdown_event.wait()
        await shutdown_server(server)
    except Exception as e:
        if not clients:
            print(f"[error] Server error: {e}")
        else:
            await log("error", f"Server error: {e}")
    finally:
        if server and not shutdown:
            await shutdown_server(server)
        if not clients:
            print("[info] Server shutdown complete")
        else:
            await log("info", "Server shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        import asyncio

        if not clients:
            print("[info] Exiting...")
        else:
            asyncio.run(log("info", "Exiting..."))
