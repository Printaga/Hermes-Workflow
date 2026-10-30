"""Throwaway: inspect the interpreter context a plain file-run gets (not shipped, not a test)."""
import sys
print("executable:", sys.executable)
print("argv:", sys.argv)
for name in ("fastapi",):
    try:
        __import__(name)
        print(name, "ok")
    except ImportError as exc:
        print(name, "MISSING:", exc)
