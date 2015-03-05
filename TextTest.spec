#
# spec file for package python-TextTest
#
# Copyright (c) 2015 Geoff Bache
#

Name:           python-TextTest
Version:        trunk
Release:        0
Url:            http://www.texttest.org
Summary:        A tool for text-based Approval Testing
License:        LGPL
Group:          Development/Languages/Python
Source:         https://pypi.python.org/packages/source/T/TextTest/TextTest-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python-devel
Requires:       python-ordereddict

%description
TextTest is a tool for text-based Approval Testing, which is an approach to acceptance testing/functional testing. In other words, it provides support for regression testing by means of comparing program output files against a specified approved versions of what they should look like.

%prep
%setup -q -n TextTest-%{version}

%build
env FROM_RPM=1 python setup.py build

%install
env FROM_RPM=1 python setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc readme.txt
%{_bindir}/texttest
%{_bindir}/filter_rundependent.py
%{_bindir}/filter_fpdiff.py
%{_bindir}/interpretcore
%{python_sitelib}/*

%changelog
