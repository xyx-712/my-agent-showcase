"""Cooperative request deadline; never abandon a running synchronous call."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import math
import os
import time

from fastapi import HTTPException

deadline = ContextVar('request_deadline', default=None)


class RequestTimeout(HTTPException):
    def __init__(self):
        super().__init__(504, '本轮执行已超时并停止后续步骤；已保存的进度保留，请使用新的「继续任务」消息核对，勿重放原请求。')


def check_budget():
    end = deadline.get()
    if end is not None and time.monotonic() >= end:
        raise RequestTimeout()


@contextmanager
def request_budget():
    seconds = float(os.environ.get('MY_AGENT_REQUEST_SECONDS', '180'))
    if not math.isfinite(seconds) or not 0 < seconds <= 3600:
        raise ValueError('MY_AGENT_REQUEST_SECONDS must be > 0 and <= 3600')
    # Nested workflows share the original deadline rather than resetting it.
    token = deadline.set(deadline.get() if deadline.get() is not None else time.monotonic() + seconds)
    try:
        check_budget()
        yield
        check_budget()
    finally:
        deadline.reset(token)


def budgeted_step(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        check_budget()
        return function(*args, **kwargs)
    return guarded


def invoke_model(model, messages):
    check_budget()
    try:
        result = model.invoke(messages)
    except Exception:
        check_budget()
        raise
    check_budget()  # The call has actually ended; do not start another step.
    return result
