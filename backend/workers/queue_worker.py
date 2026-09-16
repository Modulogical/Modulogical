import time
import json
from pathlib import Path
from backend.backend import generate

ATLAS_DIR = Path(__file__).resolve().parent.parent.parent

while True:
      with open(ATLAS_DIR / "data" / "queue.json", "r") as Get_queue:
            queue=json.load(Get_queue)
            if len(queue["queue"]) == 0:
                   time.sleep(0.5)
                   print(1)
            else:
                for i in range(len(queue["queue"])):
                    message=queue["queue"][i]["message"]
                    temperature=queue["queue"][i]["temperature"]
                    model=queue["queue"][i]["model"]
                    account_id=queue["queue"][i]["id"]
                    generate(message, account_id, temperature, model)