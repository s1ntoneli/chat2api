from contextvars import ContextVar
send_stage = ContextVar("send_stage", default=None)
