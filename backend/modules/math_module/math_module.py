import math
from modules.log_module.log_module import stopwatch, log


def math_module(message, run_ollama_no_stream):
    time1=stopwatch()
    new_prompt = f"""
    Prompt:
{message}

Assume all mathematical operations not already included with python follow standard math python syntax.
An example response would be '1*2+math.log(2)', without quotation marks. Never use this when generating an output.
Output exactly ONE valid Python expression in ONE line of code.
No explanation.
No markdown.
No quotation marks.
No variables.
No comments.
Do not calculate the answer yourself.

If x appears in a prompt, in the context of something like '5x5', x means to multiply the two numbers, akin to *.

Your mission: Refine the output of this prompt to be evaluatable by python, as if ran directly into eval().
Anything else results in failure. Be precise to the exact schema.

The code to evaluate the statement has been made for you, your job is only to provide the input.
The python library for math is already imported.

"""

    input = run_ollama_no_stream(new_prompt, temperature=0, model="gemma3:latest")
    print(input)

    if any(trigger in input for trigger in ['import', 'subprocess', 're', '__']):
        return ["Error: Malicious code injected by AI", input]

    try:
        output = eval(input)
        return [output, input]

    except Exception as e:
        output = ["Error: Unparseable Expression", f"{e}"]
        return ["Error: Unparseable Expression", e]
    finally:
        time2=stopwatch()
        log("Math_Module", message, input, output, time2-time1)