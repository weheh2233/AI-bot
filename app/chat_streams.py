import asyncio
import threading
from dataclasses import dataclass, field


# 暂停时模型可能还会多产出一些 token；队列有上限，满了就反压模型迭代，避免一直占内存。
STREAM_QUEUE_SIZE = 256
# 恢复播放时，队列里每条积压片段之间的最小间隔（秒）。只在队列还有积压时生效，
# 避免恢复的一瞬间把几十条片段灌进同一帧；排空后立刻恢复全速。调大更慢更"打字机"。
STREAM_REPLAY_INTERVAL = 0.02
CANCELLED_EVENT = {"type": "cancelled"}


@dataclass
class ChatRun:
    user_id: int
    thread_id: str
    turn_id: str
    # 模型生产 token、SSE 发送 token 是两个协程，用队列把它们接起来。
    queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=STREAM_QUEUE_SIZE)
    )
    # set 表示允许向浏览器发送；clear 后只暂停发送，不会立刻停止模型生成。
    resumed: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    producer: asyncio.Task | None = None #保存的是负责运行模型并持续生产文本片段的异步任务。None：模型生成任务还没启动。asyncio.Task：模型正在生成，或者任务已经结束/取消。

    state: str = "queued"
    # 已经发给浏览器的 SSE 序号；目前用于反馈进度，不代表服务器支持断线续传。
    last_sent_seq: int = 0

    def __post_init__(self):
        self.resumed.set()


class ChatStreamRegistry:
    """仅当前 Python 进程可见的流式任务状态，不写入数据库。"""

    def __init__(self):
        # turn_id 归属到用户，避免不同用户用相同 id 操作彼此的任务。
        self._runs: dict[tuple[int, str], ChatRun] = {} #- _runs：按 turn_id 找任务，服务暂停、继续、取消接口。-键是(user_id, turn_id)。
        self._active: dict[tuple[int, str], ChatRun] = {}  # _active：按 thread_id 找当前任务，防止同一会话并发生成。键是(user_id, thread_id)。    任务结束后，两处引用都会在 finish() 中移除。
        # 同一用户的同一会话一次只允许一个模型任务改写 checkpoint。
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._registry_lock = threading.Lock()

    def register(self, run: ChatRun) -> None:
        key = (run.user_id, run.turn_id)
        with self._registry_lock:
            if key in self._runs:
                raise ValueError("turn_id 已被使用")
            self._runs[key] = run

    def get(self, user_id: int, turn_id: str) -> ChatRun | None:
        with self._registry_lock:
            return self._runs.get((user_id, turn_id))

    async def acquire_conversation(self, user_id: int, thread_id: str) -> asyncio.Lock:
        key = (user_id, thread_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        await lock.acquire()
        return lock

    async def activate(self, run: ChatRun) -> asyncio.Lock:
        conversation_key = (run.user_id, run.thread_id)
        lock = self._locks.setdefault(conversation_key, asyncio.Lock())
        while True:
            active = self._active.get(conversation_key)
            if active is not None and active is not run:
                # 同一会话发来新一轮时，先取消旧轮，避免两轮同时写同一份对话历史。
                self.cancel(active)
                await active.finished.wait()#等旧任务真正清理完。wait():屏蔽,直到内部标志为真(直到finish为true才发现这个函数)

            await lock.acquire()
            active = self._active.get(conversation_key)
            if active is None or active is run:
                self._active[conversation_key] = run
                run.state = "running"
                return lock
            lock.release()

    def pause(self, run: ChatRun) -> dict:
        if run.finished.is_set() or run.cancelled:
            return {"status": run.state, "last_sent_seq": run.last_sent_seq}
        # 只关掉 SSE 消费端的闸门；生产端会继续填队列，填满后自然停在 queue.put。
        run.state = "paused"
        run.resumed.clear()
        return {"status": run.state, "last_sent_seq": run.last_sent_seq}
#resume：恢复
    def resume(self, run: ChatRun) -> dict:
        if run.finished.is_set() or run.cancelled:
            return {"status": run.state, "last_sent_seq": run.last_sent_seq}
        run.state = "running"
        run.resumed.set()
        return {"status": run.state, "last_sent_seq": run.last_sent_seq}
#取消
    def cancel(self, run: ChatRun) -> dict:
        if run.finished.is_set() or run.cancelled:
            return {"status": run.state, "last_sent_seq": run.last_sent_seq}
        run.cancelled = True #任务的取消标志
        run.state = "cancelled" #任务状态
        run.resumed.set()#这就是和暂停交叉的地方：如果任务正卡在暂停闸门（resumed.wait()），这一步把它唤醒，否则它会一直挂着不退出。
        # 丢弃尚未发送的 token，并唤醒正在等队列或暂停闸门的协程。
        while not run.queue.empty():
            try:
                #队列对象的非阻塞取数据方法
                # 如果 run.queue 里现在有数据：立刻取出并返回。如果队列是空的：不等待，立刻抛异常
                run.queue.get_nowait()#这里取了但并没有存起来，所以相当于丢弃了
            except asyncio.QueueEmpty:
                break
        run.queue.put_nowait(CANCELLED_EVENT)#往队列里放一个 【取消事件】
        if run.producer is not None and not run.producer.done():#如果 run.producer 存在，并且这个生产者任务还没有结束，那么就进入 if 分支
            # 取消 Python 异步任务，让 LangGraph 关闭当前流；模型供应商是否立刻停止计费由其实现决定。
            run.producer.cancel()
        return {"status": run.state, "last_sent_seq": run.last_sent_seq}
#完成状态
    def finish(self, run: ChatRun, lock: asyncio.Lock | None = None) -> None:
        conversation_key = (run.user_id, run.thread_id)
        run.state = "cancelled" if run.cancelled else "completed"#如果不是取消那状态就是完成了
        run.finished.set()
        if self._active.get(conversation_key) is run:
            self._active.pop(conversation_key, None)
        with self._registry_lock:
            if self._runs.get((run.user_id, run.turn_id)) is run:
                self._runs.pop((run.user_id, run.turn_id), None)
        # 释放会话锁，后续新一轮才能写 checkpoint。
        if lock is not None and lock.locked():
            lock.release()
