# Mathematical equivalence verification

Coordinator rerun: **25 passed in 8.42 seconds**, including 22 tests that execute
actual C and three frozen-source integrity checks. No C oracle tests were
skipped in this run.

From the firmware development environment:

```sh
PICO_CONTROLLER_SOURCE=/path/to/mcu-firmware/src/control/controller.c \
  uv run pytest tests/test_pico_differential.py -q
```

Tested `controller.c` SHA256:
`81bc2409c2f4bf12303c8a41281fed8d781f1c10838047032da6731cfd62b34f`.

The frozen references were also independently compared with `git show` of the
original firmware baseline `b62cbee`, not just hashes embedded in the tests:

| Baseline source | Matching SHA256 |
| --- | --- |
| `constants.py` | `6c97cae92e9c17e516b87c904df8c6f9f9b8add126547c911dca285968b1f772` |
| `regulator.py` | `79d27b42808e1d147e8393633f5d2e7afb0d6b6907819b1ec62d16756a40686d` |
| `thrusters.py` | `acf72977edc41e07130830f29fac31e07b537c3b5296a0f42a99b78800862d35` |

See `tests/reference/README.md`, `tests/test_pico_differential.py` and
`HANDOFF.md` for the oracle structure, scenarios and timing adaptations.
Quaternion/integral comparisons permit `3e-5` rad/units; motor and work outputs
permit one integer LSB at float32 truncation boundaries. These are bounded
numerical comparisons, not a claim of bitwise equivalence.

## Sensor conversion provenance

Read-only inspection of the actual installed Pi package matched the local
BMI270 0.4.3 sources byte-for-byte:

- `definitions.py`: `5df117580a084bd102f533f4c14a93fbc5e95085dc5b423e656e87425857fded`
- `BMI270.py`: `86f0685d047b5cb94794aab1354f38e75e846ba360642cd0c564776df82eb59a`

The original range is `2 * 9.81288` m/s², not `2 * 9.80665`. Gyro range is
1000 degrees/s, converted to radians/s. Temperature uses `0.001952594 * raw +
23`, not exactly `raw / 512 + 23`. The SPI driver preserves these constants and
axis signs `[+1, -1, -1]`.

The sensor stream deliberately changes from I²C/200 Hz ODR to SPI/800 Hz ODR.
Portable numerical tests do not certify physical sensor response, loaded
closed-loop behavior, runtime safety, or real 500 Hz execution. Those require
separate evidence against the final integrated firmware.
