from src.config import debug_print
import re
import ast
import operator



DEBUG_CALCULATOR = True





# ==========================
# 安全计算
# ==========================


operators = {

    ast.Add: operator.add,

    ast.Sub: operator.sub,

    ast.Mult: operator.mul,

    ast.Div: operator.truediv,

    ast.Pow: operator.pow,

}





def safe_eval(expression):


    """
    安全数学表达式计算
    """

    node = ast.parse(

        expression,

        mode="eval"

    ).body



    return _eval_node(node)







def _eval_node(node):


    if isinstance(
        node,
        ast.Constant
    ):


        if isinstance(
            node.value,
            (int,float)
        ):

            return node.value



    if isinstance(
        node,
        ast.BinOp
    ):


        left = _eval_node(

            node.left

        )


        right = _eval_node(

            node.right

        )


        op = operators.get(

            type(node.op)

        )


        if not op:

            raise Exception(
                "不支持的运算"
            )


        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 10**12):
            raise ValueError("乘方超过计算范围")

        return op(

            left,

            right

        )



    raise Exception(

        "非法表达式"

    )








# ==========================
# Calculator Tool
# ==========================


def calculator(

    expression:str

):


    try:


        if DEBUG_CALCULATOR:


            debug_print()

            debug_print(
                "===== CALCULATOR ====="
            )

            debug_print(
                "INPUT:",
                expression
            )





        if not expression:


            return {

                "success":False,

                "error":
                    "表达式为空"

            }







        # ======================
        # 中文转换
        # ======================


        expression=(

            expression


            .replace(
                "帮我计算",
                ""
            )


            .replace(
                "计算",
                ""
            )


            .replace(
                "多少",
                ""
            )


            .replace(
                "等于多少",
                ""
            )


            .replace(
                "乘以",
                "*"
            )


            .replace(
                "乘",
                "*"
            )


            .replace(
                "×",
                "*"
            )


            .replace(
                "加",
                "+"
            )


            .replace(
                "减去",
                "-"
            )


            .replace(
                "减",
                "-"
            )


            .replace(
                "除以",
                "/"
            )


            .replace(
                "除",
                "/"
            )


            .replace(
                "÷",
                "/"
            )

        )







        # ======================
        # 提取数学字符
        # ======================


        expression=re.sub(

            r"[^0-9+\-*/().]",

            "",

            expression

        )





        if not expression:


            return {


                "success":False,


                "error":

                    "没有有效数字"

            }







        # ======================
        # 计算
        # ======================


        result=safe_eval(

            expression

        )





        if DEBUG_CALCULATOR:


            debug_print(

                "EXPRESSION:",

                expression

            )


            debug_print(

                "RESULT:",

                result

            )


            debug_print(
                "===================="
            )







        return {


            "success":True,


            "expression":

                expression,


            "result":

                result

        }







    except ZeroDivisionError:


        return {


            "success":False,


            "error":

                "除数不能为0"

        }





    except Exception as e:


        return {


            "success":False,


            "error":

                str(e)

        }