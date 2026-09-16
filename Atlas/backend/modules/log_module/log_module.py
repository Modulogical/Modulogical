import json
from datetime import datetime
import time
from pathlib import Path

ATLAS_DIR = Path(__file__).resolve().parents[3]
LOG_DIR = ATLAS_DIR / "data" / "logs"

def stopwatch():
    return time.perf_counter()

def log(module, user_input, model_input, output, time):
    file = LOG_DIR / f"{module}_logs.json"
    filename = f"{module}_logs.json"
    if file.exists():
        with open(file, "r") as ReadLog:
            data_logged=json.load(ReadLog)
            data_logged["i/o"].append({"User Input" : user_input,
                                       "Model Refinement" : model_input,
                                       "Module Output" : output,
                                       "Time Elapsed" : round(time, 2)
                                        })
            data_logged["avg_time_array"].append(round(time, 2))
            new_avg_time_elapsed = round(sum(data_logged["avg_time_array"])/len(data_logged["avg_time_array"]), 2)
            data_logged.update({"avg_time_elapsed" : new_avg_time_elapsed})
            with open(file, "w") as WriteLog:
                json.dump(data_logged, WriteLog, indent=4)
    else:
        with open(file, "w") as Create:
            Log={
                "i/o" : [{
                    "User Input" : user_input,
                    "Model Refinement" : model_input,
                    "Module Output" : output,
                    "Time Elapsed" : round(time, 2)
                }],
                "avg_time_array" : [round(time, 2)],
                "avg_time_elapsed" : round(time, 2)
            }
            json.dump(Log, Create, indent=4)

