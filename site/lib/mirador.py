import ravebased

def getConfig(optionMap):
    return ModelServerConfig(optionMap)

class ModelServerConfig(ravebased.Config):

    def defaultBuildRules(self): return True

    def _getRuleSetNames(self, test):
        opts = test.getWordsInFile("options")
        if opts and len(opts) > 3 and opts[2] == '-r':
            return [opts[3]]
        return []
