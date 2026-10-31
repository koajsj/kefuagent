"""Optional bounded event sink, absent on regular JSON requests."""


def notify(request, phase):
    queue = getattr(request.state, "stream_events", None)
    if queue is not None:
        queue.put_nowait(("stage", {"phase": phase}))
