import json
from modules.log_module.log_module import stopwatch, log
import random

def revision_module(message, run_ollama_no_stream):
    time1=stopwatch()
    with open("revision.json", "r") as get_revision:
        revision_data=json.load(get_revision)
        prompt_engineering=f"""
Prompt: {message}

This is a Study Module. It's designed to help users revise for exams.
Your mission is to refine this prompt and output a json object. #change

REVISION DATABASE FILE STRUCTURE:
Enter when complete.
"""
        revision_details=run_ollama_no_stream(prompt_engineering, temperature=0, model="gemma3:latest")
        exam_board=revision_details["exam_board"]
        subject=revision_details["subject"]
        topic=revision_details["topic"]
        marks=revision_details["marks"]
        qnumber=random.randint(1, len(list(revision_details[exam_board][subject][topic][marks])))
        try:
            user_input = message
            module_input = list(revision_details[exam_board][subject][topic][marks])[qnumber]
            module_output = eval(module_input)
            return [user_input, module_input, message]
        except Exception as e:
            return ["Error: Unparseable input", e]
        finally:
            time2=stopwatch()
            log("Revision_module", user_input, module_input, module_output, time2-time1)


