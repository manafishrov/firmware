.PHONY: lint format typecheck test-imu test-pressure-sensor test-thrusters test-packages-available mock-websocket-server mock-websocket-server-local

lint:
	ruff check

format:
	ruff format

typecheck:
	basedpyright

test-imu:
	python -m scripts.test_imu

test-pressure-sensor:
	python -m scripts.test_pressure_sensor

test-thrusters:
	python -m scripts.test_thrusters

test-packages-available:
	python -m scripts.test_packages_available

mock-websocket-server:
	python -m scripts.mock_websocket_server

mock-websocket-server-local:
	python -m scripts.mock_websocket_server --local
