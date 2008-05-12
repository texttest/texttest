#!/usr/bin/env /usr/local/share/texttest/bin/ttpython

import sys, os
    
class DaveContext:
    def __init__(self, firebirdFile):
        self.data_schema = os.path.basename(firebirdFile).split(".")[0]
        fileRef = os.path.join(os.path.dirname(firebirdFile), self.data_schema)
        # Hardcode until we have reason to believe this might not work...
        self.data_conn = "firebird:sysdba/flamenco@" + fileRef
                
    def dump(self, fn):
        daveDelta = os.path.join(os.getenv("CARMSYS"), "bin", "davedelta")
        # Hardcode the current commit ID for now!
        args = [ daveDelta, self.data_conn, self.data_schema, "14" ]
        os.system(" ".join(args))

            
firebirdFile = sys.argv[1]

delta = DaveDelta(firebirdFile)
delta.dump()
