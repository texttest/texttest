#!/usr/bin/env /carm/master/Products/standard_gpc/CARMSYS/bin/carmrunner

import sys, os
try:
    from carmensystems.dave import DMF,GenModel
except:
    import DMF,GenModel
    
class DaveContext:
    """ base class contains common utility methods"""
    def __init__(self, firebirdFile):
        self.data_schema = os.path.basename(firebirdFile).split(".")[0]
        fileRef = os.path.join(os.path.dirname(firebirdFile), self.data_schema)
        # Hardcode until we have reason to believe this might not work...
        self.data_conn = "firebird:sysdba/flamenco@" + fileRef
        self.entities = self.getEntities()

    def getEntities(self):
        conn = DMF.EntityConnection()
        conn.open(self.data_conn,self.data_schema)
        try:
            return conn.getEntityList().split(",")
        finally:
            conn.close()
        
    def dumpMsg(self,fn,msg):
        """ write a message to dump file """
        f = open(fn,'a')
        f.write(msg + os.linesep)
        f.close()
        
    def dump(self, fn):
        try:
            m = GenModel.Model(self.data_conn, self.data_schema, 1, False)
            try:
                # add tables
                for e in self.entities:
                    m.addTable(e)
                if m.tableCount() < 1:
                    # empty model
                    self.dumpMsg(fn,"no enties found")
                    return
                # load data
                m.load(0, False)
                # dump
                m.dump(fn, 0)
            finally:
                m.finish()
        except:
            et,ev,tb = sys.exc_info()
            self.dumpMsg(fn,"ERROR during dump %s(%s)" %(et,ev))

            
firebirdFile = sys.argv[1]

dataContext = DaveContext(firebirdFile)
sys.stdout.close()
dataContext.dump("database.studio")
