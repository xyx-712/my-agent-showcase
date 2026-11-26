import json
import os


PROFILE_PATH="data/profile_memory.json"



def load_profile(user_id:str):


    if not os.path.exists(
        PROFILE_PATH
    ):
        return {}



    with open(
        PROFILE_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        data=json.load(f)



    return data.get(
        user_id,
        {}
    )





def save_profile(
    user_id:str,
    key:str,
    value:str
):


    os.makedirs(
        "data",
        exist_ok=True
    )


    data={}



    if os.path.exists(
        PROFILE_PATH
    ):

        with open(
            PROFILE_PATH,
            "r",
            encoding="utf-8"
        ) as f:

            data=json.load(f)



    if user_id not in data:

        data[user_id]={}



    data[user_id][key]=value



    with open(
        PROFILE_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )