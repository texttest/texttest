Documentation Summary:

    For those upgrading from previous versions of TextTest, migration notes are available for each version
    in the doc subdirectory. These list not only necessary migrations (which are now kept to a minimum) but 
    changes to the default behaviour of TextTest.

    There is also a ChangeLog detailing all changes since the previous release.

    Many people like to learn by example. There is a brief "quick start guide" based around reading the 
    self-tests, under source/doc/quickstart.txt

    The main documentation is however kept at www.texttest.org/TextTest/docs. At the bottom of this file is
    a brief summary of what TextTest is and what it can do for you.

Installation and System Requirements:

    Read the installation guide at http:/www.texttest.org/TextTest/docs/install.html
    The lightning summary is that you need Python, PyGTK, tkdiff which are probably already
    installed if you're on UNIX. On Windows you'll need to download them plus pstools -
    but they all have installers now!

    You now don't need to do anything to install TextTest itself as such. You can copy the contents
    of the source directory to anywhere at all or leave it where it is. Running TextTest is a matter
    of running source/bin/texttest.py with the above stuff installed.

    The Self Tests:
        TextTest comes with a large number of tests for itself (using itself, naturally!). If you plan
        to develop it you are strongly recommended to install these into your TEXTTEST_HOME so you can run
        them and test your changes. They also function as working examples as described above, read source/doc/quickstart.txt 
        for more details.

Known bugs:

    (1) TextTest drives the system under test partly by setting and unsetting environment variables. 
    However, some platforms and versions of Python do not support unsetting environment variables: you can 
    only set them to new values. The install script will warn you if this is the case with your system. If so, 
    when adding entries to environment files, be aware that they will never be cleaned. If this will cause problems 
    you will need to set them to harmless values elsewhere.

    (2) On Windows, TextTest relies on the pstools package for process management. These tools unfortunately require
    administration rights on your system. If you don't have these rights, TextTest will still work, but will
    tend to leak processes...

Bugs and Support:
    
    Contact the mailing list at texttest-users@lists.sourceforge.net

    You can also contact me directly if you want to...

    Geoff Bache

    <Geoff.Bache@carmensystems.com>


Other (non-standard) Open Source python modules used by TextTest and packaged with it:

    ndict.py                    : sequential dictionaries. (Wolfgang Grafen, v0.2)
    log4py.py                   : logging/diagnostic tool, of the kind you'll probably need in your programs 
                                  if you use TextTest. (Martin  Preishuber, v1.3.1)
    usecase.py,gtkusecase.py    : "PyUseCase", record/replay tool for PyGTK GUIs, of the kind you may well 
                                  need if you test GUIs (Geoff Bache, v1.2)
    HTMLgen.py,HTMLcolors.py,   : "HTMLGen", tool for generating HTML in Python, used for the historical report
    ImageH.py,ImagePaletteH.py,   webpages generated for batch runs (Robin Friedrich, v2.2.2)
    imgsize.py

Plugins included:

    sge.py      :   integration with Sun Grid Engine
    lsf.py      :   integration with LSF - note LSF is not free! (see www.platform.com)
    bugzilla.py :   integration with Bugzilla, using the Perl command-line interface program bugcli (Dennis Cox, v0.6)
                    See http:://www.bugzilla.org and http://quigley.durrow.com/bugzilla.html 
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


