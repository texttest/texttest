#!/usr/bin/env /carm/master/nightjob/standard_gpc/CARMSYS/bin/carmrunner

import sys, os, subprocess
            
firebirdFile = sys.argv[1]

data_schema = os.path.basename(firebirdFile).split(".")[0]
fileRef = os.path.join(os.path.dirname(firebirdFile), data_schema)
# Hardcode until we have reason to believe this might not work...
data_conn = "firebird:sysdba/flamenco@" + fileRef
davedelta = os.path.join(os.getenv("CARMSYS"), "bin", "davedelta")
subprocess.call([ davedelta, data_conn, data_schema, os.getenv("DAVE_INITIAL_COMMIT_ID") ])
