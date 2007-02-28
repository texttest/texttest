Migration notes from TextTest 2.x
=================================

The new config file format
--------------------------

For TextTest versions up to version 2.0, the types of config file entries
have been inferred from the config files. This has been changed in version 3.0
to the more robust approach of declaring what type is expected in the configuration
via the setConfigDefault method, and print errors if the wrong type, or unrecognised
entries, are found in the config file.

Config file strings, integers and lists are written as before:

my_integer:0

my_string:hello

my_list:first_entry
my_list:second_entry

However, there has not so far been a standard format for dictionary entries. For example,
run-dependent text entries have been written

output:today's date is

Recipients for batch mode have been written

nightjob_recipients:geoff

where 'nighjob' is the name of the batch session

while file collation has been written

collate_file:source_pattern->target_name

This was deemed confusing. Therefore all of these have been standardised to be written in "section format".
So the above examples in TextTest 3.0 should be written as follows:

[run_dependent_text]
output:today's date is
[end]

[batch_recipients]
nightjob:geoff
[end]

[collate_file]
target_name:source_pattern
[end]

Please note: in the case of collate_file, the source and target have turned around, for consistency with run_dependent_text!
(The [end] is also optional if followed by a new section header)

Here is a list of the config file dictionaries that are recognised, and hence need to be written in the
new format:

                        Valid   Format in 2.x
test_colours            All     n/A
file_colours            All     n/A
collate_file            All     collate_file:<source>-><target>
run_dependent_text      All     <target>:<text>
unordered_text          All     n/A
batch_recipients        UNIX    <session>_recipients:<recipients>
batch_timelimit         UNIX    <session>_timelimit:<timelimit>
batch_use_collection    UNIX    <session>_use_collection:true|false
batch_version           UNIX    <session>_version:<version>

Framework API (only relevant if you've written your own configuration)
-------------

(1) API for command line options.

The old methods getSwitches() and getArgumentOptions() are replaced by a new method, addToOptionGroup(), as a method
of declaring what command line options are supported. These switches and options are placed in certain groups, depending on
how they should be shown in the static GUI. In general, each should only be placed in one group.

View an example, for example default.py.

(2) API for config file entries

As indicated above, we now force configurations to announce their config settings in advance and provide default values. 
Therefore, a configuration should call setConfigDefault on each one from the configuration function setApplicationDefault(). 
Types are inferred when reading the config file from the type of default values. app.getConfigList is deprecated, it is 
replaced by app.getConfigValue which returns a wide variety of types.
