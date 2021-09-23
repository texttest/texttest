Documentation Summary:

    There is some stuff in texttestlib/doc here in this download, but the main documentation is kept at 
    http://texttest.sourceforge.net currently. A new site is under construction at http://www.texttest.org. 
    At the bottom of this file there is also a brief summary of what TextTest is and what it can do for you.

    In texttestlib/doc, you can find :
       a) For those upgrading from previous versions of TextTest, migration notes are available for each 
          version. These list not only necessary migrations (which are now kept to a minimum) but also
          changes to the default behaviour of TextTest. These can also be viewed from the Help menu
          in TextTest.

       b) A ChangeLog detailing all changes since the previous release (and all releases).

       c) Many people like to learn by example. There are some tips on getting started, and also learning about
          features you haven't used before, under source/doc/quick_start.txt 

       d) A directory Upgrade_PyGTK_Enterprise_Linux, especially for people working on an Enterprise Linux
          system such as Red Hat or SuSE, who are stuck with an old version of Python or PyGTK. This is basically 
          a guide to building PyGTK from source on Linux.

Installation and System Requirements:

    Read the online installation guide at http://www.texttest.org. Click on the "TextTest/docs" button
    and then the "Installation Guide" at the top-left of the table.
    The lightning summary is that you need Python, PyGTK, tkdiff which are probably already
    installed if you're on UNIX. On Windows there is a Windows installer available on the sourceforge page.

    To install TextTest itself, you can just run "sudo pip install texttest", or "sudo easy_install texttest" on
    UNIX platforms.

TEXTTEST_HOME and the Self-Tests:

    TextTest will read and write tests under the location specified by TEXTTEST_HOME. It is usually a good idea
    to create an empty directory and point the environment variable at this location in some persistent way when starting out.

    The self-tests also function as working examples as described above, read texttestlib/doc/quickstart.txt for more 
    details.

Bugs and Support:
    
    Contact the mailing list at texttest-users@lists.sourceforge.net

    You can also contact me directly if you really want to...

    Geoff Bache

    <geoff.bache@pobox.com>

Other (non-standard) Open Source python modules used by TextTest and packaged with it:

    ordereddict.py              : sequential dictionaries. (Raymond Hettinger, v1.1)
    source/storytext            : "StoryText", record/replay tool for PyGTK GUIs, of the kind you may well 
                                  need if you test GUIs (Geoff Bache, v3.7)
    HTMLgen.py,HTMLcolors.py,   : "HTMLGen", tool for generating HTML in Python, used for the historical report
    ImageH.py,ImagePaletteH.py,   webpages generated for batch runs (Robin Friedrich, v2.2.2)
    imgsize.py

Plugins included:

    cvs.py            :   integration with CVS for version control
    bzr.py            :   integration with Bazaar for version control
    hg.py             :   integration with Mercurial for version control
    sge.py            :   integration with Grid Engine for distributing tests
    lsf.py            :   integration with LSF for distributing tests - note LSF is not free! (see www.platform.com)
    ec2cloud.py       :   integration with EC2 cloud for running tests in parallel.
    bugzilla.py       :   integration with Bugzilla version 3.x, using its native webservice API (see www.bugzilla.org)
    bugzillav2.py     :   integration with Bugzilla version 2.x, using the command-line interface program bugcli (Dennis Cox, v0.6)
    trac.py           :   integration with Trac for bug tracking
    jira.py           :   integration with Atlassian Jira for bug tracking - which isn't free either
    virtualdisplay.py :   integration with Xvfb, UNIX virtual display tool, useful for stopping tested GUIs popping up all the time.

Summary of Texttest (see www.texttest.org for more info):

TextTest is an application-independent tool for text-based functional testing. In other words, it
provides support for regression testing by means of comparing program output files against a 
specified "gold standard" of what they should look like.

It is both a standalone tool for this sort of testing, and a Python framework that users plug 
their own tools, custom comparators, reports etc. into. (Framework-wise, it is composed of a 
core engine for handling the text files consituting a test suite, and various extendable configurations
that actually do things with them).

As is, it will allow the user to define various runs of particular executables using command line 
options, environment variables and standard input redirects, along with standard results for 
those runs. These are then the testcases.  It then provides means to subselect these testcases, and 
compare the files produced (by default using line-based comparators such as 'diff'), to ensure that 
behaviour changes in the target binary can be controlled. 

It is currently supported on all flavours of UNIX and Windows. Development is funded by Jeppesen AB.

It has integration with Amazon's EC2 cloud in order to support running tests in parallel there.

A configuration for the load balancing software Grid Engine (formerly the open source Sun Grid Engine, which now comes in several
descendant versions, some of which are open source) and LSF, available for a fee from Platform Computing, is also available. 
This will enable the tests to be run in parallel over a network. Unfortunately only LSF is supported on Windows.

There is a text-based console interface and two related GUI interfaces, the 'static GUI' for test creation
and management, and the 'dynamic GUI' for running tests and examining failures. It is recommended
that you install this as the text interface is not actively developed any more. The GUIs use the
Python library PyGTK, which is directly available in most Linux distributions. If you aren't using Linux, 
it is freely available for download, see online installation instructions.

To test GUIs, you need some simulation tool. We have also developed "StoryText", which is such a tool
for Python and Java GUIs, which relies on a record/replay layer between the application and the GUI library. 
There is also "NUseCase" for .net GUIs. TextTest integrates with these, and includes 
StoryText as it uses it for its own testing. If you want to use it for your own GUIs you are however recommended 
to download it separately from its own page.


