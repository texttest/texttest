"""

Python logging module - Version 1.1

Loglevels:

    LOGLEVEL_NONE, LOGLEVEL_ERROR, LOGLEVEL_NORMAL, LOGLEVEL_VERBOSE, LOGLEVEL_DEBUG

Format-Parameters:

    %C -- The name of the current class.
    %D -- Program duration since program start.
    %d -- Program duration for the last step (last output).
    %F -- The name of the current function.
    %L -- Log type (Error, Warning, Debug or Info)
    %M -- The actual message.
    %N -- The current line number.
    %T -- Current time.
    %x -- NDC (nested diagnostic contexts).

Pre-defined Formats:

    FMT_SHORT -- %M
    FMT_MEDIUM -- [ %C.%F ] %D: %M
    FMT_LONG -- %T %L %C [%F] %x%M
    FMT_DEBUG -- %T [%D (%d)] %L %C [%F (%N)] %x%M
    
"""

# Logging levels
LOGLEVEL_NONE = 1 << 0
LOGLEVEL_ERROR = 1 << 1
LOGLEVEL_NORMAL = 1 << 2
LOGLEVEL_VERBOSE = 1 << 3
LOGLEVEL_DEBUG = 1 << 4

# Pre-defined format strings
FMT_SHORT = "%M"
FMT_MEDIUM = "[ %C.%F ] %D: %M"
FMT_LONG = "%T %L %C [%F] %x%M"
FMT_DEBUG = "%T [%D (%d)] %L %C [%F (%N)] %x%M"

# Special logging targets
TARGET_MYSQL = "MySQL"
TARGET_POSTGRES = "Postgres"

# Configuration files
CONFIGURATION_FILES = {}
CONFIGURATION_FILES[1] = "log4py.conf"                    # local directory
CONFIGURATION_FILES[2] = "$HOME/.log4py.conf"             # hidden file in the home directory
CONFIGURATION_FILES[3] = "/etc/log4py.conf"               # system wide file

# The following constants are of internal interest only

# Message constants (used for ansi colors and for logtype %L)
MSG_DEBUG = 1 << 0
MSG_WARN = 1 << 1
MSG_ERROR = 1 << 2
MSG_INFO = 1 << 3

# Boolean constants
TRUE = "TRUE"
FALSE = "FALSE"

# Color constants
BLACK = 30
RED = 31
GREEN = 32
YELLOW = 33
BLUE = 34
PURPLE = 35
AQUA = 36
WHITE = 37

LOG_MSG = {MSG_DEBUG: "DEBUG", MSG_WARN: "WARNING", MSG_ERROR: "ERROR", MSG_INFO: "INFO"}
LOG_COLORS = {MSG_DEBUG: [WHITE, BLACK, FALSE], MSG_WARN: [WHITE, BLACK, FALSE], MSG_ERROR: [WHITE, BLACK, TRUE], MSG_INFO: [WHITE, BLACK, FALSE]}
LOG_LEVELS = { "DEBUG": LOGLEVEL_DEBUG, "VERBOSE": LOGLEVEL_VERBOSE, "NORMAL": LOGLEVEL_NORMAL, "NONE": LOGLEVEL_NONE, "ERROR": LOGLEVEL_ERROR }

SECTION_DEFAULT = "Default"

from time import time, strftime, localtime
from types import StringType, ClassType, InstanceType, FileType
from string import zfill, atoi, lower, upper, join, replace, split, strip
from re import sub
from ConfigParser import ConfigParser, NoOptionError

import sys
import traceback
import os
import copy
import socket

try:
    import MySQLdb
    mysql_available = TRUE
except:
    mysql_available = FALSE

# This is the main class for the logging module
class Logger:

    cache = {}
    instance = None
    configfiles = []
    hostname = socket.gethostname()

    def __init__(self, useconfigfiles = TRUE, customconfigfiles = None):
        """ **(private)** Class initalization & customization. """
        if (customconfigfiles):
            if (type(customconfigfiles) == StringType):
                customconfigfiles = [customconfigfiles]
            Logger.configfiles = customconfigfiles

        if (not Logger.instance):
            self.__Logger_setdefaults()
            if (useconfigfiles == TRUE):
                self.__Logger_appendconfigfiles(Logger.configfiles)
                # read the default options
                self.__Logger_parse_options()

            self.__Logger_timeinit = time()
            self.__Logger_timelaststep = self.__Logger_timeinit

            Logger.instance = self

            if (useconfigfiles == TRUE):
                # read and pre-cache settings for named classids
                self.__Logger_cache_options()

    def get_root(self):
        """ Provides a way to change the base logger object's properties. """
        return Logger.instance

    def get_instance(self, classid = "Main"):
        """ Either get the cached logger instance or create a new one

        Note that this is safe, even if you have your target set to sys.stdout
        or sys.stderr
        """

        cache = Logger.cache

        if (type(classid) == ClassType):
            classid = classid.__name__
        elif (type(classid) == InstanceType):
            classid = classid.__class__.__name__

        # classid has to be lowercase, because the ConfigParser returns sections lowercase
        classid = lower(classid)

        if (cache.has_key(classid)):
            cat = Logger.cache[classid]
        else:
            instance = Logger.instance

            # test for targets which won't deep copy
            targets = instance.__Logger_targets
            deepcopyable = TRUE
            for i in range(len(targets)):
                if (type(targets[i]) == FileType):
                    deepcopyable = FALSE
            if (deepcopyable == FALSE):
                # swap the non-copyable target out for a moment
                del instance.__Logger_targets
                cat = copy.deepcopy(instance)
                instance.__Logger_targets = targets
                cat.__Logger_targets = targets
            else:
                cat = copy.deepcopy(instance)

            cat.__Logger_classname = classid
            # new categories have their own private Nested Diagnostic Contexts
            self.__Logger_ndc = []
            self.__Logger_classid = classid

            cache[classid] = cat

        return cat

    # Log-target handling (add, remove, set, remove_all)
    def add_target(self, target, *args):
        """ Add a target to the logger targets. """
        if (not target in self.__Logger_targets):
            if (target == TARGET_MYSQL):
                if (mysql_available == TRUE):
                    # Required parameters: dbhost, dbname, dbuser, dbpass, dbtable
                    try:
                        self.__Logger_mysql_connection = MySQLdb.connect(host=args[0], db=args[1], user=args[2], passwd=args[3])
                        self.__Logger_mysql_cursor = self.__Logger_mysql_connection.cursor()
                        self.__Logger_mysql_tablename = args[4]
                        self.__Logger_targets.append(target)
                    except MySQLdb.OperationalError, detail:
                        self.error("MySQL connection failed: %s" % detail)
                else:
                    self.error("MySQL target not added - Python-mysql not available")
            else:
                self.__Logger_targets.append(target)

    def remove_target(self, target):
        """ Remove a target from the logger targets. """
        if (target in self.__Logger_targets):
            if (target == TARGET_MYSQL):
                self.__Logger_mysql_connection.close()
            self.__Logger_targets.remove(target)

    def set_target(self, target):
        """ Set a single target. """
        self.__Logger_targets = [target]

    def remove_all_targets(self):
        """ Remove all targets from the logger targets. """
        self.__Logger_targets=[]

    # Methods to set properties
    def set_loglevel(self, loglevel):
        """ Set the loglevel for the current instance. """
        self.__Logger_loglevel = loglevel

    def set_formatstring(self, formatstring):
        """ Set a format string. """
        self.__Logger_formatstring = formatstring

    def set_use_ansi_codes(self, useansicodes):
        """ Use ansi codes for output to the console (TRUE or FALSE). """
        self.__Logger_useansicodes = useansicodes

    def set_time_format(self, timeformat):
        """ Set the time format (default: %d.%m.%Y %H:%M:%S). """
        self.__Logger_timeformat = timeformat

    # Method to get properties
    def get_loglevel(self):
        """ Returns the current loglevel. """
        return self.__Logger_loglevel

    def get_formatstring(self):
        """ Returns the current format string. """
        return self.__Logger_formatstring

    def get_use_ansi_codes(self):
        """ Returns, wether ansi codes are being used or not. """
        return self.__Logger_useansicodes

    def get_time_format(self):
        """ Returns the current time format. """
        return self.__Logger_timeformat

    def get_targets(self):
        """ Returns the current targets. """
        return self.__Logger_targets

    # Methods to push and pop trace messages for nested contexts
    def push(self, message):
        """ Add a trace message. """
        self.__Logger_ndc.append(message)

    def pop(self):
        """ Remove the topmost trace message. """
        ct = len(self.__Logger_ndc)
        if (ct):
            del(self.__Logger_ndc[ct-1])

    def clear_ndc(self):
        """ Clears all NDC messages. """
        self.__Logger_ndc = []

    # Methods to actually print messages
    def debug(self, message):
        """ Write a debug message. """
        if (self.__Logger_loglevel >= LOGLEVEL_DEBUG):
            self.__Logger_showmessage(message, MSG_DEBUG)

    def warn(self, message):
        """ Write a warning message. """
        if (self.__Logger_loglevel >= LOGLEVEL_VERBOSE):
            self.__Logger_showmessage(message, MSG_WARN)

    def error(self, message):
        """ Write a error message. """
        if (self.__Logger_loglevel >= LOGLEVEL_ERROR):
            self.__Logger_showmessage(message, MSG_ERROR)

    def info(self, message):
        """ Write a info message. """
        if (self.__Logger_loglevel >= LOGLEVEL_NORMAL):
            self.__Logger_showmessage(message, MSG_INFO)

    # Private method of the Logger class - you never have to use those directly
    def __Logger_tracestack(self):
        """ **(private)** Analyze traceback stack and set linenumber and functionname. """
        stack = traceback.extract_stack()
        self.__Logger_linenumber = stack[-4][1]
        self.__Logger_functionname = stack[-4][2]
        if (self.__Logger_functionname == "?"):
            self.__Logger_functionname = "Main"

    def __Logger_setdefaults(self):
        """ **(private)** Set default values for internal variables. """
        self.__Logger_classid = None
        self.__Logger_targets = [ "sys.stdout" ]            # default target = sys.stdout
        self.__Logger_formatstring = FMT_LONG
        self.__Logger_loglevel = LOGLEVEL_NORMAL
        self.__Logger_useansicodes = FALSE
        self.__Logger_functionname = ""
        self.__Logger_linenumber = -1
        self.__Logger_timeformat = "%d.%m.%Y %H:%M:%S"
        self.__Logger_classname = None
        self.__Logger_configfilename = ""
        self.__Logger_ndc = []                              # ndc = Nested Diagnostic Context

    def __Logger_find_config(self):
        """ **(private)** Search for configuration files. """
        if (not self.__Logger_configfilename):
            priorities = CONFIGURATION_FILES.keys()
            priorities.sort()
            configfilename = ""
            for i in range(len(priorities)):
                filename = CONFIGURATION_FILES[priorities[i]]
                if (sys.platform == "win32"):
                    if (os.environ.has_key("USERPROFILE")):
                        home_directory = os.environ["USERPROFILE"]
                    else:
                        home_directory = "C:\\"
                else:
                    home_directory = os.environ["HOME"]
                if (os.sep == "\\"):
                    home_directory = replace(home_directory, "\\", "\\\\")
                filename = sub("\$HOME", home_directory, filename)
                if (os.path.exists(filename)):
                    configfilename = filename
                    break
            self.__Logger_configfilename = configfilename
        return self.__Logger_configfilename

    def __Logger_parse_options(self, section = SECTION_DEFAULT):
        """ **(private)** Parse main options from config file. """
        configfilename = self.__Logger_find_config()

        if (configfilename != ""):
            parser = ConfigParser()
            parser.read(configfilename)
            self.__Logger_set_instance_options(parser, section, self)
        return TRUE

    def __Logger_set_instance_options(self, parser, section, instance):
        """ **(private)** Set the options for a given instance from the parser section """

        for i in range(len(parser.options(section))):
            option = lower(parser.options(section)[i])
            value = parser.get(section, option)
            if (option == "format"):
                instance.set_formatstring(value)
            elif (option == "timeformat"):
                instance.set_time_format(value)
            elif (option == "ansi"):
                instance.set_use_ansi_codes(upper(value))
            elif (option == "loglevel"):
                instance.set_loglevel(LOG_LEVELS[upper(value)])
            elif (option == "target"):
                splitted = split(value, ",")
                instance.remove_all_targets()
                for i in range(len(splitted)):
                    instance.add_target(strip(splitted[i]))

    def __Logger_cache_options(self):
        """ **(private)** Read and cache debug levels for categories from config file. """
        configfilename = self.__Logger_find_config()

        if (configfilename != ""):
            parser = ConfigParser()
            parser.read(configfilename)

            for i in range(len(parser.sections())):
                section = parser.sections()[i]
                if (section != SECTION_DEFAULT):
                    instance = self.get_instance(section)
                    self.__Logger_set_instance_options(parser, section, instance)
        return TRUE

    def __Logger_appendconfigfiles(self, filenames):
        """ **(private)** Append a filename to the list of configuration files. """
        filenames.reverse()
        for i in range(len(filenames)):
            keys = CONFIGURATION_FILES.keys()
            CONFIGURATION_FILES[min(keys) - 1] = filenames[i]

    def __Logger_get_ndc(self):
        """ **(private)** Returns the NDC (nested diagnostic context) joined with single-spaces. """
        if (len(self.__Logger_ndc)):
            return join(self.__Logger_ndc)
        else:
            return ""

    def __Logger_showmessage(self, message, messagesource):
        """ **(private)** Writes a message to all targets set. """
        currenttime = time()
        self.__Logger_tracestack()
        timedifference = "%.3f" % (currenttime - self.__Logger_timeinit)
        timedifflaststep = "%.3f" % (currenttime - self.__Logger_timelaststep)
        self.__Logger_timelaststep = currenttime
        milliseconds = int(round((currenttime - long(currenttime)) * 1000))
        timeformat = sub("%S", "%S." + (zfill(milliseconds, 3)), self.__Logger_timeformat)
        currentformattedtime = strftime(timeformat, localtime(currenttime))

        line = self.__Logger_formatstring
        line = sub("%C", str(self.__Logger_classname), line)
        line = sub("%D", timedifference, line)
        line = sub("%d", timedifflaststep, line)
        line = sub("%F", self.__Logger_functionname, line)
        ndc = self.__Logger_get_ndc()
        if (ndc != ""):
            line = sub("%x", "%s - " % ndc, line)
        else:
            line = sub("%x", "", line)
        message = replace(message, "\\", "\\\\")
        if (self.__Logger_useansicodes == TRUE):
            line = sub("%L", self.__Logger_ansi(LOG_MSG[messagesource], messagesource), line)
            line = sub("%M", self.__Logger_ansi(message, messagesource), line)
        else:
            line = sub("%L", LOG_MSG[messagesource], line)
            line = sub("%M", message, line)
        line = sub("%N", str(self.__Logger_linenumber), line)
        line = sub("%T", currentformattedtime, line)

        for i in range(len(self.__Logger_targets)):
            target = self.__Logger_targets[i]
            if (target == TARGET_MYSQL):
                sqltime = strftime("'%Y-%m-%d', '%H:%M:%S'", localtime(currenttime))
                sqlStatement = "INSERT INTO %s (host, facility, level, date, time, program, msg) VALUES ('%s', '%s', '%s', %s, '%s', '%s')" % (self.__Logger_mysql_tablename, self.hostname, self.__Logger_functionname, LOG_MSG[messagesource], sqltime, str(self.__Logger_classname), sub("'", "`", message + " " + ndc))
                self.__Logger_mysql_cursor.execute(sqlStatement)
            elif (target == sys.stdout) or (lower(target) == "stdout") or (lower(target) == "sys.stdout"):
                sys.stdout.write("%s\n" % line)
            elif (target == sys.stderr) or (lower(target) == "stderr") or (lower(target) == "sys.stderr"):
                sys.stdout.write("%s\n" % line)
            elif (type(target) == FileType):
                target.write("%s\n" % line)
            else:
                file = open(target, "a")
                file.write("%s\n" % line)
                file.close()

    def __Logger_ansi(self, text, messagesource):
        """ **(private)** Converts plain text to ansi text. """
        bold = LOG_COLORS[messagesource][2]
        fg = str(LOG_COLORS[messagesource][0])
        bg = LOG_COLORS[messagesource][1]
        if (bold == TRUE):
            fg = "%s;1" % fg
        bg = bg + 10
        text = "\033[%d;%sm%s\033[0m" % (bg, fg, text)
        return text
