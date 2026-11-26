import json
import os



MEMORY_PATH = "data/memory.json"



def load_memory(user_id:str):


    if not os.path.exists(
        MEMORY_PATH
    ):

        return []



    with open(
        MEMORY_PATH,
        "r",
        encoding="utf-8"
    ) as f:


        data = json.load(f)



    return data.get(
        user_id,
        []
    )





def save_memory(
    user_id:str,
    message:str,
    response:str
):


    os.makedirs(
        "data",
        exist_ok=True
    )


    data={}


    if os.path.exists(
        MEMORY_PATH
    ):

        with open(
            MEMORY_PATH,
            "r",
            encoding="utf-8"
        ) as f:

            data=json.load(f)



    if user_id not in data:

        data[user_id]=[]



    data[user_id].append({

        "user":
            message,


        "assistant":
            response

    })



    with open(
        MEMORY_PATH,
        "w",
        encoding="utf-8"
    ) as f:


        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )