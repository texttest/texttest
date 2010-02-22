import plugins
import time

def calculateBatchDate():
    # Batch mode uses a standardised date that give a consistent answer for night-jobs.
    # Hence midnight is a bad cutover point. The day therefore starts and ends at 8am :)
    timeinseconds = plugins.globalStartTime - 8*60*60
    return time.strftime("%d%b%Y", time.localtime(timeinseconds))
