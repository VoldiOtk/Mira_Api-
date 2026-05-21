import sys
sys.path.append('.')
try:
    from backend.app import app
    print("Success loading app!")
except Exception as e:
    import traceback
    traceback.print_exc()
