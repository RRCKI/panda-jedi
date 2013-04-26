import os
import sys
import time
import signal
import types
import multiprocessing
import multiprocessing.reduction

#import multiprocessing, logging
#logger = multiprocessing.log_to_stderr()
#logger.setLevel(multiprocessing.SUBDEBUG)

###########################################################
#
# status codes for IPC
#

# class for status code
class StatusCode(object):
    def __init__(self,value):
        self.value = value

    def __str__(self):
        return "%s" % self.value

    # comparator
    def __eq__(self,other):
        return self.value == other.value

    def __ne__(self,other):
        return self.value != other.value


    
# mapping to accessors   
statusCodeMap = {'SC_SUCCEEDED': StatusCode(0),
                 'SC_FAILED'   : StatusCode(1),
                 'SC_FATAL'    : StatusCode(2),
                 }


# install the list of status codes to a class
def installSC(cls):
    for sc,val in statusCodeMap.iteritems():
        setattr(cls,sc,val)


# install SCs in this module
installSC(sys.modules[ __name__ ])

        
###########################################################
#
# classes for IPC
#

# object class for command
class CommandObject(object):
    
    # constructor    
    def __init__(self,methodName,argList,argMap):
        self.methodName = methodName
        self.argList = argList
        self.argMap = argMap



# object class for response
class ReturnObject(object):

    # constructor
    def __init__(self):
        self.statusCode  = None
        self.errorValue  = None
        self.returnValue = None



# process class
class ProcessClass(object):
    # constructor
    def __init__(self,pid,connection):
        self.pid = pid
        self.nused = 0
        # reduce connection to make it picklable
        self.reduced_pipe = multiprocessing.reduction.reduce_connection(connection)

    # get connection
    def connection(self):
        # rebuild connection
        return self.reduced_pipe[0](*self.reduced_pipe[1])

    # reduce connection
    def reduceConnection(self,connection):
        self.reduced_pipe = multiprocessing.reduction.reduce_connection(connection)


                     
# method class
class MethodClass(object):
    # constructor
    def __init__(self,className,methodName,vo,connectionQueue,voIF):
        self.className = className
        self.methodName = methodName
        self.vo = vo
        self.connectionQueue = connectionQueue
        self.voIF = voIF
        self.pipeList = []

    # method emulation
    def __call__(self,*args,**kwargs):
        commandObj = CommandObject(self.methodName,
                                   args,kwargs)
        nTry = 3
        for iTry in range(nTry):
            # exceptions
            retException = None
            strException = None
            try:
                # get child process
                child_process = self.connectionQueue.get()
                # get pipe
                pipe = child_process.connection()
                # send command
                pipe.send(commandObj)
                # wait response
                timeoutPeriod = 180
                if not pipe.poll(timeoutPeriod):
                    raise JEDITimeoutError,"didn't return response for %ssec" % timeoutPeriod
                # get response
                ret = pipe.recv()
                # set exception type based on error
                if ret.statusCode == SC_FAILED:
                    retException = JEDITemporaryError
                elif ret.statusCode == SC_FATAL:
                    retException = JEDIFatalError
            except:
                errtype,errvalue = sys.exc_info()[:2]
                retException = errtype
                strException = 'VO=%s type=%s : %s.%s %s' % \
                               (self.vo,errtype.__name__,self.className,self.methodName,errvalue)
            # increment nused
            child_process.nused += 1
            # kill old or problematic process
            if child_process.nused > 5000 or not retException in [None,JEDITemporaryError,JEDIFatalError]:
                # close connection
                try:
                    pipe.close()
                except:
                    pass
                # terminate child process
                try:
                    os.kill(child_process.pid,signal.SIGKILL)
                    os.waitpid(child_process.pid,0)
                except:
                    pass
                # make new child process
                self.voIF.launchChild()
            else:
                # reduce process object to avoid deadlock due to rebuilding of connection 
                child_process.reduceConnection(pipe)
                self.connectionQueue.put(child_process)
            # success, fatal error, or maximally attempted    
            if retException in [None,JEDIFatalError] or (iTry+1 == nTry):
                break
            # sleep
            time.sleep(1) 
        # raise exception
        if retException != None:
            if strException == None:
                strException = 'VO={0} {1}'.format(self.vo,ret.errorValue)
            raise retException,strException
        # return
        if ret.statusCode == SC_SUCCEEDED:
            return ret.returnValue
        else:
            raise retException,'VO=%s %s' % (self.vo,ret.errorValue)
        


# interface class to send command
class CommandSendInterface(object):
    # constructor
    def __init__(self,vo,maxChild,moduleName,className):
        self.vo = vo
        self.maxChild = maxChild
        self.connectionQueue = multiprocessing.Queue(maxChild)
        self.moduleName = moduleName
        self.className  = className
        

    # factory method
    def __getattr__(self,attrName):
        return MethodClass(self.className,attrName,self.vo,self.connectionQueue,self)


    # launcher for child processe
    def launcher(self,channel):
        # import module
        mod = __import__(self.moduleName)
        for subModuleName in self.moduleName.split('.')[1:]:
            mod = getattr(mod,subModuleName)
        # get class
        cls = getattr(mod,self.className)
        # start child process
        cls(channel).start()
            

    # launch child processes to interact with DDM
    def launchChild(self):
        # make pipe
        parent_conn, child_conn = multiprocessing.Pipe()
        # make child process
        child_process = multiprocessing.Process(target=self.launcher,
                                                args=(child_conn,))
        # start child process
        child_process.daemon = True
        child_process.start()
        # keep process in queue        
        processObj = ProcessClass(child_process.pid,parent_conn)
        self.connectionQueue.put(processObj)


    # initialize
    def initialize(self):
        for i in range(self.maxChild):
            self.launchChild()



# interface class to receive command
class CommandReceiveInterface(object):

    # constructor
    def __init__(self,con):
        self.con = con


    # main loop    
    def start(self):
        while True:
            # get command
            commandObj = self.con.recv()
            # make return
            retObj = ReturnObject()
            # get class name
            className = self.__class__.__name__
            # check method name
            if not hasattr(self,commandObj.methodName):
                # method not found
                retObj.statusCode = self.SC_FATAL
                retObj.errorValue = 'type=AttributeError : %s instance has no attribute %s' % \
                    (className,commandObj.methodName)
            else:
                try:
                    # get function
                    functionObj = getattr(self,commandObj.methodName)
                    # exec
                    tmpRet = apply(functionObj,commandObj.argList,commandObj.argMap)
                    if isinstance(tmpRet,StatusCode):
                        # only status code was returned
                        retObj.statusCode = tmpRet
                    elif (isinstance(tmpRet,types.TupleType) or isinstance(tmpRet,types.ListType)) \
                       and len(tmpRet) > 0 and isinstance(tmpRet[0],StatusCode):
                            retObj.statusCode = tmpRet[0]
                            # status code + return values
                            if len(tmpRet) > 1:
                                if retObj.statusCode == self.SC_SUCCEEDED:
                                    if len(tmpRet) == 2:
                                        retObj.returnValue = tmpRet[1]
                                    else:
                                        retObj.returnValue = tmpRet[1:]
                                else:
                                    if len(tmpRet) == 2:
                                        retObj.errorValue = tmpRet[1]
                                    else:
                                        retObj.errorValue = tmpRet[1:]
                    else:        
                        retObj.statusCode = self.SC_SUCCEEDED
                        retObj.returnValue = tmpRet
                except:
                    errtype,errvalue = sys.exc_info()[:2]
                    # failed
                    retObj.statusCode = self.SC_FATAL
                    retObj.errorValue = 'type=%s : %s.%s : %s' % \
                                        (errtype.__name__,className,
                                         commandObj.methodName,errvalue)
            # return
            self.con.send(retObj)
            

# install SCs
installSC(CommandReceiveInterface)




###########################################################
#
# exceptions for IPC
#

# exception for temporary error
class JEDITemporaryError(Exception):
    pass


# exception for fatal error
class JEDIFatalError(Exception):
    pass


# exception for timeout error
class JEDITimeoutError(Exception):
    pass


