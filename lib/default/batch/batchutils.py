import plugins
import datetime

def calculateBatchDate():
    # Batch mode uses a standardised date that give a consistent answer for night-jobs.
    # Hence midnight is a bad cutover point. The day therefore starts and ends at 8am :)
    timeToUse = plugins.globalStartTime - datetime.timedelta(hours=8)
    return timeToUse.strftime("%d%b%Y")
