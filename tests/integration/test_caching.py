import filecmp, os, sys, traceback, logging, requests
import thread, time, random
from threading import Lock
from Queue import Queue

import synapseclient
import synapseclient.utils as utils
import synapseclient.cache as cache
from synapseclient.utils import MB, GB
from synapseclient import Activity, Entity, Project, Folder, File, Data

import integration
from integration import create_project, schedule_for_cleanup


def setup(module):
    print '\n'
    print '~' * 60
    print os.path.basename(__file__)
    print '~' * 60
    module.syn = integration.syn
    
    # Use the module-level syn object to communicate between main and child threads
    # - Read-only objects (for the children)
    module.syn.test_parent = create_project()
    module.syn.test_keepRunning = True
    
    # - Child writeable objects
    module.syn.test_errors = Queue()
    module.syn.test_runCountMutex = Lock()
    module.syn.test_threadsRunning = 0
    
def teardown(module):
    del module.syn.test_parent
    del module.syn.test_keepRunning
    del module.syn.test_errors
    del module.syn.test_runCountMutex
    del module.syn.test_threadsRunning
    
    
def test_slow_unlocker():
    """Manually grabs a lock and makes sure the get/store methods are blocked."""
    
    # Make a file to manually lock
    project = create_project()
    path = utils.make_bogus_data_file()
    schedule_for_cleanup(path)
    contention = File(path, parent=project)
    contention = syn.store(contention)
    
    # Lock the Cache Map
    cacheDir = cache.determine_cache_directory(contention['dataFileHandleId'])
    cache.obtain_lock(cacheDir)
    
    # Start a few calls to get/store that should not complete yet
    thread.start_new_thread(start_thread, (lambda: store_catch_412_HTTPError(contention), ))
    thread.start_new_thread(start_thread, (lambda: syn.get(contention), ))
    time.sleep(cache.CACHE_LOCK_TIME / 2)
    
    # Make sure the threads did not finish
    assert syn.test_threadsRunning > 0
    cache.release_lock(cacheDir)
    
    # Let the threads go
    while syn.test_threadsRunning > 0:
        time.sleep(1)
    collect_errors_and_fail()
    

def test_threaded_access():
    """Starts multiple threads to perform store and get calls randomly."""
    ## Doesn't this test look like a DOS attack on Synapse?
    ## Maybe it should be called explicity...
    
    # Suppress most of the output from the many REST calls
    #   Otherwise, it flood the screen with irrelevant data upon error
    requests_log = logging.getLogger("requests")
    requests_originalLevel = requests_log.getEffectiveLevel()
    requests_log.setLevel(logging.WARNING)
    
    print "Starting threads"
    thread.start_new_thread(start_thread, (thread_keep_storing_one_File, ))
    thread.start_new_thread(start_thread, (thread_keep_storing_one_File, ))
    thread.start_new_thread(start_thread, (thread_keep_storing_one_File, ))
    thread.start_new_thread(start_thread, (thread_keep_storing_one_File, ))
    thread.start_new_thread(start_thread, (thread_get_files_from_Project, ))
    thread.start_new_thread(start_thread, (thread_get_files_from_Project, ))
    thread.start_new_thread(start_thread, (thread_get_files_from_Project, ))
    thread.start_new_thread(start_thread, (thread_get_files_from_Project, ))
    thread.start_new_thread(start_thread, (thread_get_and_update_file_from_Project, ))
    thread.start_new_thread(start_thread, (thread_get_and_update_file_from_Project, ))
    
    # Give the threads some time to wreak havoc on the cache
    time.sleep(cache.CACHE_LOCK_TIME * 2)
    
    print "Terminating threads"
    syn.test_keepRunning = False
    while syn.test_threadsRunning > 0:
        time.sleep(1)

    # Reset the requests logging level
    requests_log.setLevel(requests_originalLevel)
        
    collect_errors_and_fail()
  
#############
## Helpers ##
#############

def start_thread(function):
    """Runs the given function after tying into the main thread."""
    
    syn.test_runCountMutex.acquire()
    syn.test_threadsRunning += 1
    syn.test_runCountMutex.release()
    
    try:
        function()
    except Exception:
        syn.test_errors.put(traceback.format_exc())
        
    syn.test_runCountMutex.acquire()
    syn.test_threadsRunning -= 1
    syn.test_runCountMutex.release()
    
def collect_errors_and_fail():
    """Pulls error traces from the error queue and fails if the queue is not empty."""
    failures = []
    for i in range(syn.test_errors.qsize()):
        failures.append(syn.test_errors.get())
    if len(failures) > 0:
        raise Exception('\n' + '\n'.join(failures))
    
######################
## Thread Behaviors ##    
######################

def thread_keep_storing_one_File():
    """Makes one file and stores it over and over again."""
    
    # Make a local file to continuously store
    path = utils.make_bogus_data_file()
    schedule_for_cleanup(path)
    myPrecious = File(path, parent=syn.test_parent, description='This bogus file is MINE', mwa="hahahah")
    
    while syn.test_keepRunning:
        stored = store_catch_412_HTTPError(myPrecious)
        if stored is not None:
            myPrecious = stored
            print "I've stored %s" % myPrecious.id
        else: 
            myPrecious = syn.get(myPrecious)
            print "Grrr... Someone modified my %s" % myPrecious.id
                
        sleep_for_a_bit()

        
def thread_get_files_from_Project():
    """Continually polls and fetches items from the Project."""
    
    while syn.test_keepRunning:
        for id in get_all_ids_from_Project():
            print "I got %s" % id
            
        sleep_for_a_bit()
        
def thread_get_and_update_file_from_Project():
    """Fetches one item from the Project and updates it with a new file."""
    
    while syn.test_keepRunning:
        id = get_all_ids_from_Project()
        if len(id) <= 0:
            continue
            
        id = id[random.randrange(len(id))]
        entity = syn.get(id)
        
        # Replace the file and re-store
        path = utils.make_bogus_data_file()
        schedule_for_cleanup(path)
        entity.path = path
        entity = store_catch_412_HTTPError(entity)
        if entity is not None:
            print "I updated %s" % entity.id
            assert os.stat(entity.path) == os.stat(path)
            
        sleep_for_a_bit()
    
####################
## Thread Helpers ##
####################
    
def sleep_for_a_bit():
    """Sleeps for a random amount of seconds between 1 and 5 inclusive."""
    
    time.sleep(random.randint(1, 5))

def get_all_ids_from_Project():
    """Fetches all currently available Synapse IDs from the parent Project."""
    
    others = syn.chunkedQuery('select id from entity where parentId=="%s"' % syn.test_parent.id)
    ids = []
    for result in others:
        ids.append(result['entity.id'])
    return ids
    
def store_catch_412_HTTPError(entity):
    """Returns the stored Entity if the function succeeds or None if the 412 is caught."""
    try:
        return syn.store(entity)
    except requests.exceptions.HTTPError as err:
        # Some other thread modified the Entity, so try again
        if err.response.status_code == 412:
            return None
        else:
            raise err
