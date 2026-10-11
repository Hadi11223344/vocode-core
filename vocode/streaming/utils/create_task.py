import asyncio
import functools
import traceback

from loguru import logger

tasks_registry: list[asyncio.Task] = []

def _handle_task_result(task: asyncio.Task) -> None:
    try:
        tasks_registry.remove(task)
    except ValueError:
        pass
    
    if not task.cancelled():
        exc = task.exception()
        if exc:
            logger.error(f"Task {task.get_coro()} failed with exception: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)

def asyncio_create_task(
    *args,
    **kwargs,
) -> asyncio.Task:
    task = asyncio.create_task(*args, **kwargs)
    tasks_registry.append(task)
    task.add_done_callback(_handle_task_result)
    return task
