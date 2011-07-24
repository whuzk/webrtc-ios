#!/usr/bin/python

# Copyright (c) 2009 Google Inc. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
TestGyp.py:  a testing framework for GYP integration tests.
"""

import os
import re
import shutil
import stat
import sys

import TestCommon
from TestCommon import __all__

__all__.extend([
  'TestGyp',
])


class TestGypBase(TestCommon.TestCommon):
  """
  Class for controlling end-to-end tests of gyp generators.

  Instantiating this class will create a temporary directory and
  arrange for its destruction (via the TestCmd superclass) and
  copy all of the non-gyptest files in the directory hierarchy of the
  executing script.

  The default behavior is to test the 'gyp' or 'gyp.bat' file in the
  current directory.  An alternative may be specified explicitly on
  instantiation, or by setting the TESTGYP_GYP environment variable.

  This class should be subclassed for each supported gyp generator
  (format).  Various abstract methods below define calling signatures
  used by the test scripts to invoke builds on the generated build
  configuration and to run executables generated by those builds.
  """

  build_tool = None
  build_tool_list = []

  _exe = TestCommon.exe_suffix
  _obj = TestCommon.obj_suffix
  shobj_ = TestCommon.shobj_prefix
  _shobj = TestCommon.shobj_suffix
  lib_ = TestCommon.lib_prefix
  _lib = TestCommon.lib_suffix
  dll_ = TestCommon.dll_prefix
  _dll = TestCommon.dll_suffix

  # Constants to represent different targets.
  ALL = '__all__'
  DEFAULT = '__default__'

  # Constants for different target types.
  EXECUTABLE = '__executable__'
  STATIC_LIB = '__static_lib__'
  SHARED_LIB = '__shared_lib__'

  def __init__(self, gyp=None, *args, **kw):
    self.origin_cwd = os.path.abspath(os.path.dirname(sys.argv[0]))

    if not gyp:
      gyp = os.environ.get('TESTGYP_GYP')
      if not gyp:
        if sys.platform == 'win32':
          gyp = 'gyp.bat'
        else:
          gyp = 'gyp'
    self.gyp = os.path.abspath(gyp)

    self.initialize_build_tool()

    if not kw.has_key('match'):
      kw['match'] = TestCommon.match_exact

    if not kw.has_key('workdir'):
      # Default behavior:  the null string causes TestCmd to create
      # a temporary directory for us.
      kw['workdir'] = ''

    formats = kw.get('formats', [])
    if kw.has_key('formats'):
      del kw['formats']

    super(TestGypBase, self).__init__(*args, **kw)

    excluded_formats = set([f for f in formats if f[0] == '!'])
    included_formats = set(formats) - excluded_formats
    if ('!'+self.format in excluded_formats or
        included_formats and self.format not in included_formats):
      msg = 'Invalid test for %r format; skipping test.\n'
      self.skip_test(msg % self.format)

    self.copy_test_configuration(self.origin_cwd, self.workdir)
    self.set_configuration(None)

  def built_file_must_exist(self, name, type=None, **kw):
    """
    Fails the test if the specified built file name does not exist.
    """
    return self.must_exist(self.built_file_path(name, type, **kw))

  def built_file_must_not_exist(self, name, type=None, **kw):
    """
    Fails the test if the specified built file name exists.
    """
    return self.must_not_exist(self.built_file_path(name, type, **kw))

  def built_file_must_match(self, name, contents, **kw):
    """
    Fails the test if the contents of the specified built file name
    do not match the specified contents.
    """
    return self.must_match(self.built_file_path(name, **kw), contents)

  def built_file_must_not_match(self, name, contents, **kw):
    """
    Fails the test if the contents of the specified built file name
    match the specified contents.
    """
    return self.must_not_match(self.built_file_path(name, **kw), contents)

  def copy_test_configuration(self, source_dir, dest_dir):
    """
    Copies the test configuration from the specified source_dir
    (the directory in which the test script lives) to the
    specified dest_dir (a temporary working directory).

    This ignores all files and directories that begin with
    the string 'gyptest', and all '.svn' subdirectories.
    """
    for root, dirs, files in os.walk(source_dir):
      if '.svn' in dirs:
        dirs.remove('.svn')
      dirs = [ d for d in dirs if not d.startswith('gyptest') ]
      files = [ f for f in files if not f.startswith('gyptest') ]
      for dirname in dirs:
        source = os.path.join(root, dirname)
        destination = source.replace(source_dir, dest_dir)
        os.mkdir(destination)
        if sys.platform != 'win32':
          shutil.copystat(source, destination)
      for filename in files:
        source = os.path.join(root, filename)
        destination = source.replace(source_dir, dest_dir)
        shutil.copy2(source, destination)

  def initialize_build_tool(self):
    """
    Initializes the .build_tool attribute.

    Searches the .build_tool_list for an executable name on the user's
    $PATH.  The first tool on the list is used as-is if nothing is found
    on the current $PATH.
    """
    for build_tool in self.build_tool_list:
      if not build_tool:
        continue
      if os.path.isabs(build_tool):
        self.build_tool = build_tool
        return
      build_tool = self.where_is(build_tool)
      if build_tool:
        self.build_tool = build_tool
        return

    if self.build_tool_list:
      self.build_tool = self.build_tool_list[0]

  def relocate(self, source, destination):
    """
    Renames (relocates) the specified source (usually a directory)
    to the specified destination, creating the destination directory
    first if necessary.

    Note:  Don't use this as a generic "rename" operation.  In the
    future, "relocating" parts of a GYP tree may affect the state of
    the test to modify the behavior of later method calls.
    """
    destination_dir = os.path.dirname(destination)
    if not os.path.exists(destination_dir):
      self.subdir(destination_dir)
    os.rename(source, destination)

  def report_not_up_to_date(self):
    """
    Reports that a build is not up-to-date.

    This provides common reporting for formats that have complicated
    conditions for checking whether a build is up-to-date.  Formats
    that expect exact output from the command (make, scons) can
    just set stdout= when they call the run_build() method.
    """
    print "Build is not up-to-date:"
    print self.banner('STDOUT ')
    print self.stdout()
    stderr = self.stderr()
    if stderr:
      print self.banner('STDERR ')
      print stderr

  def run_gyp(self, gyp_file, *args, **kw):
    """
    Runs gyp against the specified gyp_file with the specified args.
    """
    # TODO:  --depth=. works around Chromium-specific tree climbing.
    args = ('--depth=.', '--format='+self.format, gyp_file) + args
    return self.run(program=self.gyp, arguments=args, **kw)

  def run(self, *args, **kw):
    """
    Executes a program by calling the superclass .run() method.

    This exists to provide a common place to filter out keyword
    arguments implemented in this layer, without having to update
    the tool-specific subclasses or clutter the tests themselves
    with platform-specific code.
    """
    if kw.has_key('SYMROOT'):
      del kw['SYMROOT']
    super(TestGypBase, self).run(*args, **kw)

  def set_configuration(self, configuration):
    """
    Sets the configuration, to be used for invoking the build
    tool and testing potential built output.
    """
    self.configuration = configuration

  def configuration_dirname(self):
    if self.configuration:
      return self.configuration.split('|')[0]
    else:
      return 'Default'

  def configuration_buildname(self):
    if self.configuration:
      return self.configuration
    else:
      return 'Default'

  #
  # Abstract methods to be defined by format-specific subclasses.
  #

  def build(self, gyp_file, target=None, **kw):
    """
    Runs a build of the specified target against the configuration
    generated from the specified gyp_file.

    A 'target' argument of None or the special value TestGyp.DEFAULT
    specifies the default argument for the underlying build tool.
    A 'target' argument of TestGyp.ALL specifies the 'all' target
    (if any) of the underlying build tool.
    """
    raise NotImplementedError

  def built_file_path(self, name, type=None, **kw):
    """
    Returns a path to the specified file name, of the specified type.
    """
    raise NotImplementedError

  def built_file_basename(self, name, type=None, **kw):
    """
    Returns the base name of the specified file name, of the specified type.

    A bare=True keyword argument specifies that prefixes and suffixes shouldn't
    be applied.
    """
    if not kw.get('bare'):
      if type == self.EXECUTABLE:
        name = name + self._exe
      elif type == self.STATIC_LIB:
        name = self.lib_ + name + self._lib
      elif type == self.SHARED_LIB:
        name = self.dll_ + name + self._dll
    return name

  def run_built_executable(self, name, *args, **kw):
    """
    Runs an executable program built from a gyp-generated configuration.

    The specified name should be independent of any particular generator.
    Subclasses should find the output executable in the appropriate
    output build directory, tack on any necessary executable suffix, etc.
    """
    raise NotImplementedError

  def up_to_date(self, gyp_file, target=None, **kw):
    """
    Verifies that a build of the specified target is up to date.

    The subclass should implement this by calling build()
    (or a reasonable equivalent), checking whatever conditions
    will tell it the build was an "up to date" null build, and
    failing if it isn't.
    """
    raise NotImplementedError


class TestGypGypd(TestGypBase):
  """
  Subclass for testing the GYP 'gypd' generator (spit out the
  internal data structure as pretty-printed Python).
  """
  format = 'gypd'


class TestGypMake(TestGypBase):
  """
  Subclass for testing the GYP Make generator.
  """
  format = 'make'
  build_tool_list = ['make']
  ALL = 'all'
  def build(self, gyp_file, target=None, **kw):
    """
    Runs a Make build using the Makefiles generated from the specified
    gyp_file.
    """
    arguments = kw.get('arguments', [])[:]
    if self.configuration:
      arguments.append('BUILDTYPE=' + self.configuration)
    if target not in (None, self.DEFAULT):
      arguments.append(target)
    # Sub-directory builds provide per-gyp Makefiles (i.e.
    # Makefile.gyp_filename), so use that if there is no Makefile.
    chdir = kw.get('chdir', '')
    if not os.path.exists(os.path.join(chdir, 'Makefile')):
      print "NO Makefile in " + os.path.join(chdir, 'Makefile')
      arguments.insert(0, '-f')
      arguments.insert(1, os.path.splitext(gyp_file)[0] + '.Makefile')
    kw['arguments'] = arguments
    return self.run(program=self.build_tool, **kw)
  def up_to_date(self, gyp_file, target=None, **kw):
    """
    Verifies that a build of the specified Make target is up to date.
    """
    if target in (None, self.DEFAULT):
      message_target = 'all'
    else:
      message_target = target
    kw['stdout'] = "make: Nothing to be done for `%s'.\n" % message_target
    return self.build(gyp_file, target, **kw)
  def run_built_executable(self, name, *args, **kw):
    """
    Runs an executable built by Make.
    """
    configuration = self.configuration_dirname()
    libdir = os.path.join('out', configuration, 'lib')
    # TODO(piman): when everything is cross-compile safe, remove lib.target
    os.environ['LD_LIBRARY_PATH'] = libdir + '.host:' + libdir + '.target'
    # Enclosing the name in a list avoids prepending the original dir.
    program = [self.built_file_path(name, type=self.EXECUTABLE, **kw)]
    return self.run(program=program, *args, **kw)
  def built_file_path(self, name, type=None, **kw):
    """
    Returns a path to the specified file name, of the specified type,
    as built by Make.

    Built files are in the subdirectory 'out/{configuration}'.
    The default is 'out/Default'.

    A chdir= keyword argument specifies the source directory
    relative to which  the output subdirectory can be found.

    "type" values of STATIC_LIB or SHARED_LIB append the necessary
    prefixes and suffixes to a platform-independent library base name.

    A libdir= keyword argument specifies a library subdirectory other
    than the default 'obj.target'.
    """
    result = []
    chdir = kw.get('chdir')
    if chdir:
      result.append(chdir)
    configuration = self.configuration_dirname()
    result.extend(['out', configuration])
    if type == self.STATIC_LIB:
      result.append(kw.get('libdir', 'obj.target'))
    elif type == self.SHARED_LIB:
      result.append(kw.get('libdir', 'lib.target'))
    result.append(self.built_file_basename(name, type, **kw))
    return self.workpath(*result)


class TestGypMSVS(TestGypBase):
  """
  Subclass for testing the GYP Visual Studio generator.
  """
  format = 'msvs'

  u = r'=== Build: 0 succeeded, 0 failed, (\d+) up-to-date, 0 skipped ==='
  up_to_date_re = re.compile(u, re.M)

  # Initial None element will indicate to our .initialize_build_tool()
  # method below that 'devenv' was not found on %PATH%.
  #
  # Note:  we must use devenv.com to be able to capture build output.
  # Directly executing devenv.exe only sends output to BuildLog.htm.
  build_tool_list = [None, 'devenv.com']

  def initialize_build_tool(self):
    """ Initializes the Visual Studio .build_tool and .uses_msbuild parameters.

    We use the value specified by GYP_MSVS_VERSION.  If not specified, we
    search %PATH% and %PATHEXT% for a devenv.{exe,bat,...} executable.
    Failing that, we search for likely deployment paths.
    """
    super(TestGypMSVS, self).initialize_build_tool()
    possible_roots = ['C:\\Program Files (x86)', 'C:\\Program Files']
    possible_paths = {
        '2010': r'Microsoft Visual Studio 10.0\Common7\IDE\devenv.com',
        '2008': r'Microsoft Visual Studio 9.0\Common7\IDE\devenv.com',
        '2005': r'Microsoft Visual Studio 8\Common7\IDE\devenv.com'}
    msvs_version = os.environ.get('GYP_MSVS_VERSION', 'auto')
    if msvs_version in possible_paths:
      # Check that the path to the specified GYP_MSVS_VERSION exists.
      path = possible_paths[msvs_version]
      for r in possible_roots:
        bt = os.path.join(r, path)
        if os.path.exists(bt):
          self.build_tool = bt
          self.uses_msbuild = msvs_version >= '2010'
          return
      else:
        print ('Warning: Environment variable GYP_MSVS_VERSION specifies "%s" '
               'but corresponding "%s" was not found.' % (msvs_version, path))
    if self.build_tool:
      # We found 'devenv' on the path, use that and try to guess the version.
      for version, path in possible_paths.iteritems():
        if self.build_tool.find(path) >= 0:
          self.uses_msbuild = version >= '2010'
          return
      else:
        # If not, assume not MSBuild.
        self.uses_msbuild = False
      return
    # Neither GYP_MSVS_VERSION nor the path help us out.  Iterate through
    # the choices looking for a match.
    for version, path in possible_paths.iteritems():
      for r in possible_roots:
        bt = os.path.join(r, path)
        if os.path.exists(bt):
          self.build_tool = bt
          self.uses_msbuild = msvs_version >= '2010'
          return
    print 'Error: could not find devenv'
    sys.exit(1)
  def build(self, gyp_file, target=None, rebuild=False, **kw):
    """
    Runs a Visual Studio build using the configuration generated
    from the specified gyp_file.
    """
    configuration = self.configuration_buildname()
    if rebuild:
      build = '/Rebuild'
    else:
      build = '/Build'
    arguments = kw.get('arguments', [])[:]
    arguments.extend([gyp_file.replace('.gyp', '.sln'),
                      build, configuration])
    # Note:  the Visual Studio generator doesn't add an explicit 'all'
    # target, so we just treat it the same as the default.
    if target not in (None, self.ALL, self.DEFAULT):
      arguments.extend(['/Project', target])
    if self.configuration:
      arguments.extend(['/ProjectConfig', self.configuration])
    kw['arguments'] = arguments
    return self.run(program=self.build_tool, **kw)
  def up_to_date(self, gyp_file, target=None, **kw):
    """
    Verifies that a build of the specified Visual Studio target is up to date.

    Beware that VS2010 will behave strangely if you build under
    C:\USERS\yourname\AppData\Local. It will cause needless work.  The ouptut
    will be "1 succeeded and 0 up to date".  MSBuild tracing reveals that:
    "Project 'C:\Users\...\AppData\Local\...vcxproj' not up to date because
    'C:\PROGRAM FILES (X86)\MICROSOFT VISUAL STUDIO 10.0\VC\BIN\1033\CLUI.DLL'
    was modified at 02/21/2011 17:03:30, which is newer than '' which was
    modified at 01/01/0001 00:00:00.
    
    The workaround is to specify a workdir when instantiating the test, e.g.
    test = TestGyp.TestGyp(workdir='workarea')
    """
    result = self.build(gyp_file, target, **kw)
    if not result:
      stdout = self.stdout()

      m = self.up_to_date_re.search(stdout)
      up_to_date = m and m.group(1) == '1'
      if not up_to_date:
        self.report_not_up_to_date()
        self.fail_test()
    return result
  def run_built_executable(self, name, *args, **kw):
    """
    Runs an executable built by Visual Studio.
    """
    configuration = self.configuration_dirname()
    # Enclosing the name in a list avoids prepending the original dir.
    program = [self.built_file_path(name, type=self.EXECUTABLE, **kw)]
    return self.run(program=program, *args, **kw)
  def built_file_path(self, name, type=None, **kw):
    """
    Returns a path to the specified file name, of the specified type,
    as built by Visual Studio.

    Built files are in a subdirectory that matches the configuration
    name.  The default is 'Default'.

    A chdir= keyword argument specifies the source directory
    relative to which  the output subdirectory can be found.

    "type" values of STATIC_LIB or SHARED_LIB append the necessary
    prefixes and suffixes to a platform-independent library base name.
    """
    result = []
    chdir = kw.get('chdir')
    if chdir:
      result.append(chdir)
    result.append(self.configuration_dirname())
    if type == self.STATIC_LIB:
      result.append('lib')
    result.append(self.built_file_basename(name, type, **kw))
    return self.workpath(*result)


class TestGypSCons(TestGypBase):
  """
  Subclass for testing the GYP SCons generator.
  """
  format = 'scons'
  build_tool_list = ['scons', 'scons.py']
  ALL = 'all'
  def build(self, gyp_file, target=None, **kw):
    """
    Runs a scons build using the SCons configuration generated from the
    specified gyp_file.
    """
    arguments = kw.get('arguments', [])[:]
    dirname = os.path.dirname(gyp_file)
    if dirname:
      arguments.extend(['-C', dirname])
    if self.configuration:
      arguments.append('--mode=' + self.configuration)
    if target not in (None, self.DEFAULT):
      arguments.append(target)
    kw['arguments'] = arguments
    return self.run(program=self.build_tool, **kw)
  def up_to_date(self, gyp_file, target=None, **kw):
    """
    Verifies that a build of the specified SCons target is up to date.
    """
    if target in (None, self.DEFAULT):
      up_to_date_targets = 'all'
    else:
      up_to_date_targets = target
    up_to_date_lines = []
    for arg in up_to_date_targets.split():
      up_to_date_lines.append("scons: `%s' is up to date.\n" % arg)
    kw['stdout'] = ''.join(up_to_date_lines)
    arguments = kw.get('arguments', [])[:]
    arguments.append('-Q')
    kw['arguments'] = arguments
    return self.build(gyp_file, target, **kw)
  def run_built_executable(self, name, *args, **kw):
    """
    Runs an executable built by scons.
    """
    configuration = self.configuration_dirname()
    os.environ['LD_LIBRARY_PATH'] = os.path.join(configuration, 'lib')
    # Enclosing the name in a list avoids prepending the original dir.
    program = [self.built_file_path(name, type=self.EXECUTABLE, **kw)]
    return self.run(program=program, *args, **kw)
  def built_file_path(self, name, type=None, **kw):
    """
    Returns a path to the specified file name, of the specified type,
    as built by Scons.

    Built files are in a subdirectory that matches the configuration
    name.  The default is 'Default'.

    A chdir= keyword argument specifies the source directory
    relative to which  the output subdirectory can be found.

    "type" values of STATIC_LIB or SHARED_LIB append the necessary
    prefixes and suffixes to a platform-independent library base name.
    """
    result = []
    chdir = kw.get('chdir')
    if chdir:
      result.append(chdir)
    result.append(self.configuration_dirname())
    if type in (self.STATIC_LIB, self.SHARED_LIB):
      result.append('lib')
    result.append(self.built_file_basename(name, type, **kw))
    return self.workpath(*result)


class TestGypXcode(TestGypBase):
  """
  Subclass for testing the GYP Xcode generator.
  """
  format = 'xcode'
  build_tool_list = ['xcodebuild']

  phase_script_execution = ("\n"
                            "PhaseScriptExecution /\\S+/Script-[0-9A-F]+\\.sh\n"
                            "    cd /\\S+\n"
                            "    /bin/sh -c /\\S+/Script-[0-9A-F]+\\.sh\n"
                            "(make: Nothing to be done for `all'\\.\n)?")

  strip_up_to_date_expressions = [
    # Various actions or rules can run even when the overall build target
    # is up to date.  Strip those phases' GYP-generated output.
    re.compile(phase_script_execution, re.S),

    # The message from distcc_pump can trail the "BUILD SUCCEEDED"
    # message, so strip that, too.
    re.compile('__________Shutting down distcc-pump include server\n', re.S),
  ]

  up_to_date_endings = (
    'Checking Dependencies...\n** BUILD SUCCEEDED **\n', # Xcode 3.0/3.1
    'Check dependencies\n** BUILD SUCCEEDED **\n\n',     # Xcode 3.2
  )

  def build(self, gyp_file, target=None, **kw):
    """
    Runs an xcodebuild using the .xcodeproj generated from the specified
    gyp_file.
    """
    # Be sure we're working with a copy of 'arguments' since we modify it.
    # The caller may not be expecting it to be modified.
    arguments = kw.get('arguments', [])[:]
    arguments.extend(['-project', gyp_file.replace('.gyp', '.xcodeproj')])
    if target == self.ALL:
      arguments.append('-alltargets',)
    elif target not in (None, self.DEFAULT):
      arguments.extend(['-target', target])
    if self.configuration:
      arguments.extend(['-configuration', self.configuration])
    symroot = kw.get('SYMROOT', '$SRCROOT/build')
    if symroot:
      arguments.append('SYMROOT='+symroot)
    kw['arguments'] = arguments
    return self.run(program=self.build_tool, **kw)
  def up_to_date(self, gyp_file, target=None, **kw):
    """
    Verifies that a build of the specified Xcode target is up to date.
    """
    result = self.build(gyp_file, target, **kw)
    if not result:
      output = self.stdout()
      for expression in self.strip_up_to_date_expressions:
        output = expression.sub('', output)
      if not output.endswith(self.up_to_date_endings):
        self.report_not_up_to_date()
        self.fail_test()
    return result
  def run_built_executable(self, name, *args, **kw):
    """
    Runs an executable built by xcodebuild.
    """
    configuration = self.configuration_dirname()
    os.environ['DYLD_LIBRARY_PATH'] = os.path.join('build', configuration)
    # Enclosing the name in a list avoids prepending the original dir.
    program = [self.built_file_path(name, type=self.EXECUTABLE, **kw)]
    return self.run(program=program, *args, **kw)
  def built_file_path(self, name, type=None, **kw):
    """
    Returns a path to the specified file name, of the specified type,
    as built by Xcode.

    Built files are in the subdirectory 'build/{configuration}'.
    The default is 'build/Default'.

    A chdir= keyword argument specifies the source directory
    relative to which  the output subdirectory can be found.

    "type" values of STATIC_LIB or SHARED_LIB append the necessary
    prefixes and suffixes to a platform-independent library base name.
    """
    result = []
    chdir = kw.get('chdir')
    if chdir:
      result.append(chdir)
    configuration = self.configuration_dirname()
    result.extend(['build', configuration])
    result.append(self.built_file_basename(name, type, **kw))
    return self.workpath(*result)


format_class_list = [
  TestGypGypd,
  TestGypMake,
  TestGypMSVS,
  TestGypSCons,
  TestGypXcode,
]

def TestGyp(*args, **kw):
  """
  Returns an appropriate TestGyp* instance for a specified GYP format.
  """
  format = kw.get('format')
  if format:
    del kw['format']
  else:
    format = os.environ.get('TESTGYP_FORMAT')
  for format_class in format_class_list:
    if format == format_class.format:
      return format_class(*args, **kw)
  raise Exception, "unknown format %r" % format
