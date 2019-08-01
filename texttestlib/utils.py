
import socket
import os

def getPortListenErrorCode(ip, port):
    if "TEXTTEST_FAKE_USER" in os.environ:
        return 0
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    ret = s.connect_ex((ip, port))
    s.close()
    return ret


def getUserName():
    return os.getenv("TEXTTEST_FAKE_USER", os.getenv("USER", os.getenv("USERNAME"))) # Fake user id, useful for testing cloud interaction
