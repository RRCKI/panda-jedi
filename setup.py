#
#
# Setup prog for JEDI
#
#
# set PYTHONPATH to use the current directory first
import sys
sys.path.insert(0,'.')

# get release version
import os
import PandaPkgInfo
release_version = PandaPkgInfo.release_version
if os.environ.has_key('BUILD_NUMBER'):
    release_version = '{0}.{1}'.format(release_version,os.environ['BUILD_NUMBER'])

# define user name and group
panda_user = 'atlpan'
panda_group = 'zp'
panda_home = '/srv/panda/'

import re
import sys
import commands
from distutils.core import setup
from distutils.command.install import install as install_org
from distutils.command.install_data import install_data as install_data_org

# get panda specific params
optPanda = {}
newArgv  = []
idx = 0
while idx < len(sys.argv):
    tmpArg = sys.argv[idx]
    if tmpArg.startswith('--panda_'):
        # panda params
        idx += 1            
        if len(tmpArg.split('=')) == 2:
            # split to par and val if = is contained
            tmpVal = tmpArg.split('=')[-1]
            tmpArg = tmpArg.split('=')[0]
        elif len(tmpArg.split('=')) == 1:
            tmpVal = sys.argv[idx]
            idx += 1
        else:
            raise RuntimeError,"invalid panda option : %s" % tmpArg
        # get key             
        tmpKey = re.sub('--panda_','',tmpArg)
        # set params
        optPanda[tmpKey] = tmpVal
    else:
        # normal opts
        idx += 1
        newArgv.append(tmpArg)
# set new argv
sys.argv = newArgv


# set overall prefix for bdist_rpm
class install_panda(install_org):
    def initialize_options (self):
        install_org.initialize_options(self)


# generates files using templates and install them
class install_data_panda (install_data_org):

    def initialize_options (self):
        install_data_org.initialize_options (self)
        self.install_purelib = None
        self.panda_user = panda_user
        self.panda_group = panda_group
        
    def finalize_options (self):
        # set install_purelib
        self.set_undefined_options('install',
                                   ('install_purelib','install_purelib'))
        # set reaming params
        install_data_org.finalize_options(self)
        # set hostname
        if optPanda.has_key('hostname') and optPanda['hostname'] != '':
            self.hostname = optPanda['hostname']
        else:
            self.hostname = commands.getoutput('hostname -f')
        # set user and group
        if optPanda.has_key('username') and optPanda['username'] != '':
            self.username  = optPanda['username']
        else:
            self.username  = commands.getoutput('id -un')
        if optPanda.has_key('usergroup') and optPanda['usergroup'] != '':
            self.usergroup = optPanda['usergroup']
        else:
            self.usergroup = commands.getoutput('id -gn')             
        
    
    def run (self):
        # remove /usr for bdist/bdist_rpm
        match = re.search('(build/[^/]+/dumb)/usr',self.install_dir)
        if match != None:
            self.install_dir = re.sub(match.group(0),match.group(1),self.install_dir)
        # remove /var/tmp/*-buildroot for bdist_rpm
        match = re.search('(/var/tmp/.*-buildroot)/usr',self.install_dir)
        if match != None:
            self.install_dir = re.sub(match.group(0),match.group(1),self.install_dir)
        # create tmp area
        tmpDir = 'build/tmp'
        self.mkpath(tmpDir)
        new_data_files = []
        for destDir,dataFiles in self.data_files:
            newFilesList = []
            destDir=panda_home+destDir
            for srcFile in dataFiles:
                # check extension
                if not srcFile.endswith('.template'):
                    raise RuntimeError,"%s doesn't have the .template extension" % srcFile
                # dest filename
                destFile = re.sub('(\.exe)*\.template$','',srcFile)
                destFile = re.sub(r'^templates/', '', destFile)
                destFile = '%s/%s' % (tmpDir,destFile)
                # open src
                inFile = open(srcFile)
                # read
                filedata=inFile.read()
                # close
                inFile.close()
                # replace patterns
                for item in re.findall('@@([^@]+)@@',filedata):
                    if not hasattr(self,item):
                        raise RuntimeError,'unknown pattern %s in %s' % (item,srcFile)
                    # get pattern
                    patt = getattr(self,item)
                    # remove install root, if any
                    if self.root is not None and patt.startswith(self.root):
                        patt = patt[len(self.root):]
                    # remove build/*/dump for bdist
                    patt = re.sub('build/[^/]+/dumb','',patt)
                    # remove /var/tmp/*-buildroot for bdist_rpm
                    patt = re.sub('/var/tmp/.*-buildroot','',patt)                    
                    # replace
                    filedata = filedata.replace('@@%s@@' % item, patt)
                # write to dest
                if '/' in destFile:
                    destSubDir = os.path.dirname(destFile)
                    if not os.path.exists(destSubDir):
                        os.makedirs(destSubDir)
                oFile = open(destFile,'w')
                oFile.write(filedata)
                oFile.close()
                # chmod for exe
                if srcFile.endswith('.exe.template'):
                    commands.getoutput('chmod +x %s' % destFile)
                # append
                newFilesList.append(destFile)
            # replace dataFiles to install generated file
            new_data_files.append((destDir,newFilesList))
        # install
        self.data_files = new_data_files
        install_data_org.run(self)
        
        
# setup for distutils
setup(
    name="panda-jedi",
    version=release_version,
    description='JEDI Package',
    long_description='''This package contains JEDI components''',
    license='GPL',
    author='Panda Team',
    author_email='atlas-adc-panda@cern.ch',
    url='https://twiki.cern.ch/twiki/bin/view/Atlas/PanDA',
    packages=[ 'pandajedi',
               'pandajedi.jedicore',
               'pandajedi.jediexec',
               'pandajedi.jeditest',               
               'pandajedi.jedidog',
               'pandajedi.jediddm',
               'pandajedi.jedigen',
               'pandajedi.jedisetup',
               'pandajedi.jediorder',               
               'pandajedi.jediconfig',
               'pandajedi.jedirefine',               
               'pandajedi.jedithrottle',
               'pandajedi.jedibrokerage',
               'pandajedi.jedipprocess',
              ],
    data_files=[
                # config and cron files
                ('/etc/panda', ['templates/panda_jedi.cfg.rpmnew.template',
                                'templates/panda_jedi.cron.template',
                                'templates/logrotate.d/panda_jedi.template',
                               ]
                 ),
                # sysconfig
                ('/etc/sysconfig', ['templates/sysconfig/panda_jedi.template',
                                   ]
                 ),
                # init script
                ('/etc/rc.d/init.d', ['templates/init.d/panda_jedi.exe.template',
                                   ]
                 ),
                # exec
                ('/usr/bin', ['templates/panda_jedi-reniceJEDI.exe.template',
                             ]
                 ),
                ],
    cmdclass={'install': install_panda,
              'install_data': install_data_panda}
)
