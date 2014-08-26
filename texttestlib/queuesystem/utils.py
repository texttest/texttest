
"""
Utilities for both master and slave code
"""

def queueSystemName(app):
    return app.getConfigValue("queue_system_module")

def socketSerialise(test):
    return test.app.name + test.app.versionSuffix() + ":" + test.getRelPath()        

def socketParse(testString):
    # Test name might contain ":"
    return testString.strip().split(":", 1)
