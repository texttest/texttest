
import socket, os

# Method name used by CaptureMock - need to change in tests also if this is renamed!
def getPortListenErrorCode(ip, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    ret = s.connect_ex((ip, port))
    s.close()
    return ret

def getUserName():
    return os.getenv("USER", os.getenv("USERNAME"))
