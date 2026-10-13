from app.agent.bot import AgentContext, get_agent
from app.memory.long_term import store_context
from app.memory.short_term import checkpointer_context


def chat():
    user_id = input(
        "请输入用户 ID，直接回车使用 demo-user："
    ).strip()

    if not user_id:
        user_id = "demo-user"

    thread_id = input(
        "请输入会话 ID，直接回车使用 conversation-001："
    ).strip()

    if not thread_id:
        thread_id = "conversation-001"

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    context = AgentContext(user_id=user_id)

    print("开始聊天，输入 quit 退出。")

    with checkpointer_context() as checkpointer:
        with store_context() as store:
            agent = get_agent(checkpointer, store)

            while True:
                user_input = input("\n你：").strip()

                if user_input.lower() in {"quit", "exit", "退出"}:
                    print("聊天结束。")
                    break

                if not user_input:
                    continue

                print("\nAgent：", end="", flush=True)
                for chunk, _meta in agent.stream(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": user_input,
                            }
                        ]
                    },
                    config,
                    context=context,
                    stream_mode="messages",
                ):
                    if chunk.content:
                        print(chunk.content, end="", flush=True)
                print()


if __name__ == "__main__":
    chat()