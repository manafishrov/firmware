cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(pico C CXX ASM)

pico_sdk_init()

add_executable(${CMAKE_PROJECT_NAME}
    main.c
    dshot.c
)

pico_generate_pio_header(${CMAKE_PROJECT_NAME} ${CMAKE_CURRENT_LIST_DIR}/dshot.pio)

target_link_libraries(${CMAKE_PROJECT_NAME}
    pico_stdlib
    pico_stdio_usb
    hardware_clocks
    hardware_pio
    hardware_pwm
)

pico_add_extra_outputs(${CMAKE_PROJECT_NAME})
