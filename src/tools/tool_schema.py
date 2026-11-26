from src.tools.registry import get_tools_info



def get_tool_schema():

    tools = get_tools_info()


    result = []


    for name, info in tools.items():

        result.append(info)


    return result