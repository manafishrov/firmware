project(pwm_firmware C CXX ASM)

pico_sdk_init()

add_executable(pwm_firmware main.c pwm.c)

target_link_libraries(pwm_firmware pico_stdlib pico_stdio_usb hardware_clocks hardware_pwm)

pico_add_extra_outputs(pwm_firmware)

