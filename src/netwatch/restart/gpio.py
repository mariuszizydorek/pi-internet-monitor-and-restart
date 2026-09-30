"""GPIO line held low unless a restart pulse is in progress."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class Pin:
    def open_low(self) -> None:
        raise NotImplementedError

    def drive_high(self) -> None:
        raise NotImplementedError

    def drive_low(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class NullPin(Pin):
    """Used while GPIO output is switched off in config."""

    def open_low(self) -> None:
        return None

    def drive_high(self) -> None:
        return None

    def drive_low(self) -> None:
        return None


class GpioPin(Pin):
    def __init__(self, chip: str, line: int) -> None:
        self.chip = chip
        self.line = line
        self._request = None

    def open_low(self) -> None:
        import gpiod
        from gpiod.line import Direction, Value

        self._request = gpiod.request_lines(
            self.chip,
            consumer="netwatch-restart",
            config={
                self.line: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.INACTIVE,
                )
            },
        )

    def drive_high(self) -> None:
        self._set(active=True)

    def drive_low(self) -> None:
        self._set(active=False)

    def _set(self, active: bool) -> None:
        if self._request is None:
            raise RuntimeError("GPIO line is not open")
        from gpiod.line import Value

        self._request.set_value(self.line, Value.ACTIVE if active else Value.INACTIVE)

    def close(self) -> None:
        if self._request is not None:
            self._request.release()
            self._request = None


def open_pin(enabled: bool, chip: str, line: int) -> Pin:
    if not enabled:
        log.info("GPIO output is off; restart decisions are recorded only")
        return NullPin()
    pin = GpioPin(chip, line)
    pin.open_low()
    log.info("GPIO %s line %s held low", chip, line)
    return pin
