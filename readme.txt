Documentation Summary:

    There is some stuff in source/doc here in this download, but the main documentation is kept at 
    www.texttest.org/TextTest/docs. At the bottom of this file there is also
    a brief summary of what TextTest is and what it can do for you.

    In source/doc, you can find :
       a) For those upgrading from previous versions of TextTest, migration notes are available for each 
          version. These list not only necessary migrations (which are now kept to a minimum) but also
          changes to the default behaviour of TextTest.

       b) A ChangeLog detailing all changes since the previous release (and all releases).

       c) Many people like to learn by example. There is a brief "quick start guide" based around reading the 
          self-tests, under source/doc/quickstart.txt 

       d) A directory RHEL_upgrade, especially for people working on Red Hat Enterprise Linux
          who are stuck with an old version of Python or PyGTK and a sysadmin group unwilling to
          upgrade the central version.

Installation and System Requirements:

    Read the installation guide at http:/www.texttest.org/TextTest/docs/install.html
    The lightning summary is that you need Python, PyGTK, tkdiff which are probably already
    installed if you're on UNIX. On Windows you'll probably need to download them. However
    you don't need special process management tools any more and it's sufficient to run PyGTK's installer
    and then tkdiff's installer!

    You now don't need to do anything to install TextTest itself as such. You can copy the contents
    of the source directory to anywhere at all or leave it where it is. Running TextTest is a matter
    of running source/bin/texttest.py with the above stuff installed.

TEXTTEST_HOME and the Self-Tests:

    The tests subdirectory is a sketch of what a basic test repository looks like. You can move this
    to anywhere at all or leave it where it is, but wherever it ends up you should point the environment
    variable TEXTTEST_HOME at it. It contains configuration for how to get debug information out of TextTest 
    and also a large number of tests for itself (using itself, naturally!) under the texttest subdirectory. 
    Your tests should be placed in product-specific subdirectories alongside the "texttest" and "Diagnostics"
    directories.

    The expected results provided are those from my own environment (RHEL4 Linux, currently). Unless your 
    environment is identical you should transform the test suite to be suited to the environment and OS 
    you are running in by running the script configure_tests.py which is included with these tests 
    (under tests/texttest).

    Note that the self-tests expect that Java is installed on your machine (it mostly is by default) and also
    a couple of tests rely on the "optional" baretail program on Windows.

    If you plan to change the code you are strongly recommended to run the self-tests and test your changes. 
    They also function as working examples as described above, read source/doc/quickstart.txt for more 
    details.

Known bugs:

    (1) When testing GUIs on Windows, TextTest hides the window as it does via the virtual DISPLAY on UNIX. However,
    this isn't recursive so any dialogs, other windows, other apps etc. started by the test will still pop up. This
    is very obvious if you run the self-tests on Windows...

    (2) Windows Vista has an annoying habit of not setting up the automatic file handling for Python correctly so
    that command-line arguments are lost. If this happens (for example the TrafficInterception self-tests fail), 
    you need to run the registry editor and add "%*" to the end of the line for Python. Hopefully M$ will fix it soon... 

Bugs and Support:
    
    Contact the mailing list at texttest-users@lists.sourceforge.net

    You can also contact me directly if you really want to...

    Geoff Bache

    <Geoff.Bache@jeppesen.com>


Other (non-standard) Open Source python modules used by TextTest and packaged with it:

    ndict.py                    : sequential dictionaries. (Wolfgang Grafen, v0.2)
    log4py.py                   : logging/diagnostic tool (Martin  Preishuber, v1.3.1)
                                  Python now has a builtin "logging" module which is probably why this
                                  has been abandoned. I haven't yet migrated away from it though and
a                                 am currently maintaining my own version of it.
    usecase.py,gtkusecase.py    : "PyUseCase", record/replay tool for PyGTK GUIs, of the kind you may well 
                                  need if you test GUIs (Geoff Bache, v1.3)
    HTMLgen.py,HTMLcolors.py,   : "HTMLGen", tool for generating HTML in Python, used for the historical report
    ImageH.py,ImagePaletteH.py,   webpages generated for batch runs (Robin Friedrich, v2.2.2)
    imgsize.py

Plugins included:

    cvs.py      :   integration with CVS for version control
    sge.py      :   integration with Sun Grid Engine
    lsf.py      :   integration with LSF - note LSF is not free! (see www.platform.com)
    bugzilla.py :   integration with Bugzilla, using the Perl command-line interface program bugcli (Dennis Cox, v0.6)
                    See http:://www.bugzilla.org and http://quigley.durrow.com/bugzilla.html 
                    Bugcli also appears to have been abandoned but I haven't had any trouble with it...
    unixonly.py :   integration with Xvfb, UNIX virtual display tool, useful for stopping tested GUIs 
                    popping up all the time.

Summary of Texttest:

TextTest is an application-independent tool for text-based functional testing. In other words, it
provides support for regression testing by means of comparing program output files against a 
specified "gold standard" of what they should look like.

It is both a standalone tool for this sort of testing, and a Python framework that users plug 
their own tools, custom comparators, reports etc. into. (Framework-wise, it is composed of a 
core engine for handling the text files consituting a test suite, and various extendable configurations
that actually do things with them).

As is, it will allow the user to define various runs of particular binaries using command line 
options, environment variables and standard input redirects, along with standard results for 
those runs. These are then the testcases.  It then provides means to subselect these testcases, and 
compare the files produced (by default using line-based comparators such as 'diff'), to ensure that 
behaviour changes in the target binary can be controlled. 

It is currently supported on all flavours of UNIX and Windows XP.

A configuration for the load balancing software Sun Grid Engine (which is free and open source) and LSF, 
available for a fee from Platform Computing, is also available. This will enable the tests to be run in 
parallel over a network. Unfortunately only LSF is supported on Windows.

There is a text-based console interface and two related GUI interfaces, the 'static GUI' for test creation
and management, and the 'dynamic GUI' for running tests and examining failures. It is recommended
that you install this as the text interface is not actively developed any more. The GUIs use the
Python library PyGTK, which is a part of Red Hat's Linux distribution. If you aren't using Linux, 
it is freely available for download, see below.

To test GUIs, you need some simulation tool. We have also developed "PyUseCase", which is such a tool
for PyGTK GUIs, which relies on a record/replay layer between the application and the GUI library, and 
"JUseCase", which performs a similar role for Java Swing GUIs. TextTest integrates with these, and includes 
PyUseCase as it uses it for its own testing. If you want to use it for your
own GUIs you are however recommended to download it separately from its own page.


