from src.memory.store import memory_store




def memory_load_node(state):


    user_id = state.get(
        "user_id",
        ""
    )


    memory = memory_store.get_memory_text(
        user_id
    )



    print(
        "===== MEMORY LOAD ====="
    )


    print(
        memory
    )



    return {


        "memory":

            memory


    }