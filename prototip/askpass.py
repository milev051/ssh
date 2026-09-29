"""Windows OpenSSH askpass helper; secret arrives only through an inherited pipe."""

import ctypes
import os
import sys

value = bytearray()
handle = ctypes.c_void_p(int(os.environ["SSH_UI_SECRET_FD"]))
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
while True:
    chunk = ctypes.create_string_buffer(1)
    read = ctypes.c_ulong()
    if not kernel32.ReadFile(handle, chunk, 1, ctypes.byref(read), None) or not read.value:
        break
    if chunk.raw == b"\n":
        break
    value.extend(chunk.raw)
sys.stdout.buffer.write(value)
