from src.config import debug_print
from langchain_core.messages import HumanMessage, AIMessage
from src.agent.context import prepare_messages





DEBUG_HISTORY = True







def history_node(state):


    messages = state.get(

        "messages",

        []

    )



    messages = prepare_messages(messages)
    history=[]





    # =====================================
    # 从当前 messages 构造历史
    # =====================================


    for message in messages:


        if isinstance(
            message,
            HumanMessage
        ):


            history.append(

                {

                    "role":"user",

                    "content":message.content

                }

            )




        elif isinstance(
            message,
            AIMessage
        ):


            history.append(

                {

                    "role":"assistant",

                    "content":message.content

                }

            )







    # =====================================
    # 限制长度
    # =====================================


    # Whole-turn selection is centralized in context.prepare_messages above.






    if DEBUG_HISTORY:


        debug_print()

        debug_print(
            "===== HISTORY ====="
        )


        for item in history:

            debug_print(

                item["role"],

                ":",

                item["content"]

            )


        debug_print(
            "==================="
        )







    return {


        "history":

            history

    }
