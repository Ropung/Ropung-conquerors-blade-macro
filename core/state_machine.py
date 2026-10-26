from enum import Enum
import threading
import time


class Stopped(Exception):
    pass


class SafetyError(Exception):
    pass


class State(str, Enum):
    IDLE = "대기"
    CHECKING = "시작 전 확인"
    PURCHASING = "구매"
    REGISTERING = "분해 등록"
    DISMANTLING = "분해"
    PAUSED = "일시정지"
    STOPPED = "중지"
    ERROR = "오류 중지"


def batches(quantity):
    if type(quantity) is not int or not 1 <= quantity <= 20:
        raise ValueError("quantity must be 1..20")
    return [min(15, quantity - offset) for offset in range(0, quantity, 15)]


class RunControl:
    def __init__(self):
        self.revision = 0
        self.stopped = threading.Event()
        self.running = threading.Event()
        self.running.set()

    def stop(self):
        self.stopped.set()
        self.running.set()

    def pause(self):
        self.revision += 1
        self.running.clear()

    def resume(self):
        self.running.set()

    def checkpoint(self):
        while not self.running.wait(0.025):
            if self.stopped.is_set():
                raise Stopped()
        if self.stopped.is_set():
            raise Stopped()

    def delay(self, seconds):
        # Paused time does not consume the action delay or completion timeout.
        remaining = seconds
        while remaining > 0:
            self.checkpoint()
            start = time.monotonic()
            if self.stopped.wait(min(remaining, 0.025)):
                raise Stopped()
            remaining -= time.monotonic() - start
