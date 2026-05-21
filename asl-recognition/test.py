import traceback
import sys

try:
    import backend.app
    print("Import successful")
except Exception as e:
    print("Caught Exception")
    with open("err.txt", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("Wrote to err.txt")
except BaseException as e:
    print("Caught BaseException")
    with open("err.txt", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("Wrote to err.txt")
