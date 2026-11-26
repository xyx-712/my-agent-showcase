from pydantic import BaseModel, Field




# =========================
# calculator 参数
# =========================

class CalculatorArgs(BaseModel):

    expression: str = Field(

        ...,

        description="数学表达式，例如 123+456"

    )





# =========================
# time 参数
# =========================

class TimeArgs(BaseModel):

    timezone: str = Field(

        default="Asia/Shanghai",

        description="时区，例如 Asia/Shanghai"

    )