
""" Traffic classes for capturing client-server interaction """

import traffic, commandlinetraffic, socket, sys

class ClientSocketTraffic(traffic.Traffic):
    destination = None
    direction = "<-"
    typeId = "CLI"
    def forwardToDestination(self):
        if self.destination:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(self.destination)
            sock.sendall(self.text)
            try:
                sock.shutdown(socket.SHUT_WR)
                response = sock.makefile().read()
                sock.close()
                return [ ServerTraffic(response, self.responseFile) ]
            except socket.error:
                sys.stderr.write("WARNING: Server process reset the connection while TextTest's 'fake client' was trying to read a response from it!\n")
                sys.stderr.write("(while running test at " +
                                 commandlinetraffic.CommandLineTraffic.currentTestPath + ")\n")
                sock.close()
        return []


class ServerTraffic(traffic.Traffic):
    typeId = "SRV"
    direction = "->"

class ServerStateTraffic(ServerTraffic):
    def __init__(self, inText, responseFile):
        ServerTraffic.__init__(self, inText, responseFile)
        if not ClientSocketTraffic.destination:
            lastWord = inText.strip().split()[-1]
            host, port = lastWord.split(":")
            ClientSocketTraffic.destination = host, int(port)
            # If we get a server state message, switch the order around
            ClientSocketTraffic.direction = "->"
            ServerTraffic.direction = "<-"
    def forwardToDestination(self):
        return []
