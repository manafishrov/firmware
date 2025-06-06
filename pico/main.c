#include <stdio.h>
#include "pico/stdlib.h"

int main() {
    stdio_init_all();

    const uint LED_PIN = PICO_DEFAULT_LED_PIN;

    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);

    while (true) {
        printf("Hello from Raspberry Pi Pico! LED is ON.\n");
        gpio_put(LED_PIN, 1);
        sleep_ms(500);
        printf("LED is OFF.\n");
        gpio_put(LED_PIN, 0);
        sleep_ms(500);
    }

    return 0;
}
