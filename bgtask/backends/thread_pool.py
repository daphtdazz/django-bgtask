from concurrent.futures import ThreadPoolExecutor


SHARED_THREAD_POOL = None


def dispatch(func, bg_task, *args, **kwargs):
    global SHARED_THREAD_POOL
    if SHARED_THREAD_POOL is None:
        SHARED_THREAD_POOL = ThreadPoolExecutor()

    SHARED_THREAD_POOL.submit(func, bg_task, *args, **kwargs)
