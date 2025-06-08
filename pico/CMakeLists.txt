cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(pico C CXX ASM)

pico_sdk_init()

add_executable(${CMAKE_PROJECT_NAME}
    main.c
    dshot.c
)

pico_generate_pio_header(${CMAKE_PROJECT_NAME} ${CMAKE_CURRENT_SOURCE_DIR}/dshot.pio)

target_link_libraries(${CMAKE_PROJECT_NAME}
    pico_stdlib
    pico_stdio_usb
    hardware_pio
    hardware_clocks
    hardware_pwm
)

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

pico_add_extra_outputs(${CMAKE_PROJECT_NAME})
