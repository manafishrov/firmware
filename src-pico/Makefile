BUILD_DIR = build
CMAKE_FLAGS = -DCMAKE_BUILD_TYPE=Release

.PHONY: all build build-dshot build-pwm flash-dshot flash-pwm copy clean format lint help

all: build

build: build-dshot build-pwm

build-dshot:
	mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && cmake .. $(CMAKE_FLAGS) -DFIRMWARE_TYPE=dshot
	cmake --build $(BUILD_DIR) --target dshot_firmware

build-pwm:
	mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && cmake .. $(CMAKE_FLAGS) -DFIRMWARE_TYPE=pwm
	cmake --build $(BUILD_DIR) --target pwm_firmware

flash-dshot: build-dshot
	picotool load $(BUILD_DIR)/dshot/dshot_firmware.uf2 -f

flash-pwm: build-pwm
	picotool load $(BUILD_DIR)/pwm/pwm_firmware.uf2 -f

copy: build
	cp $(BUILD_DIR)/dshot/dshot_firmware.uf2 ../src/microcontroller_firmware/dshot.uf2
	cp $(BUILD_DIR)/pwm/pwm_firmware.uf2 ../src/microcontroller_firmware/pwm.uf2

clean:
	rm -rf $(BUILD_DIR)

format:
	find . -name "*.c" -o -name "*.h" | xargs clang-format -i

lint:
	find . -name "*.c" | xargs clang-tidy

help:
	@echo "Available targets:"
	@echo "  build         - Build all firmware"
	@echo "  build-dshot   - Build dshot firmware"
	@echo "  build-pwm     - Build pwm firmware"
	@echo "  flash-dshot   - Build and flash dshot"
	@echo "  flash-pwm     - Build and flash pwm"
	@echo "  copy          - Build and copy uf2 to main firmware"
	@echo "  clean         - Clean build dir"
	@echo "  format        - Format C code"
	@echo "  lint          - Lint C code"
	@echo "  help          - Show this help"
