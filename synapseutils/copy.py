import synapseclient
from synapseclient import File, Project, Folder, Table, Schema, Link, Wiki, Entity, Activity, exceptions
import time
from synapseclient.exceptions import *
import tempfile
import re
import json
############################################################
##                 Copy Functions                         ##
############################################################
def copyFileHandles(syn, fileHandles, associateObjectTypes, associateObjectIds, newContentTypes=None, newFileNames=None):
    """
    Given a list of fileHandle Objects, copy the fileHandles

    :param fileHandles:          List of fileHandle Objects

    :param associateObjectTypes: List of associated object types: FileEntity, TableEntity, WikiAttachment, UserProfileAttachment, MessageAttachment, TeamAttachment, SubmissionAttachment, VerificationSubmission (Must be the same length as fileHandles)
    
    :param associateObjectIds:   List of associated object Ids: If copying a file, the objectId is the synapse id, and if copying a wiki attachment, the object id is the wiki subpage id. (Must be the same length as fileHandles)
    
    :param newContentTypes:      List of new content types (Can change a filetype of a filehandle). Defaults to None, keeping the old filetype

    :param newFileNames:         List of new filenames (Can change a filename of a filehandle). Defaults to None, keeping the old filename
    
    :return:                     List of batch filehandle copy results
    """

    newContentTypes = [None]*len(fileHandles) if newContentTypes is None else newContentTypes
    newFileNames = [None]*len(fileHandles) if newFileNames is None else newFileNames
    if (len(fileHandles) != len(associateObjectTypes) or len(fileHandles) != len(associateObjectIds) or
        len(fileHandles) != len(newContentTypes) or len(fileHandles) != len(newFileNames)):
        raise ValueError("Length of fileHandles, associateObjectTypes, and associateObjectIds must be the same")
    copyFileHandleRequest = {"copyRequests":[]}
    for filehandle, newContentType, newFileName, associateObjectType, associateObjectId in zip(fileHandles, newContentTypes, newFileNames, associateObjectTypes, associateObjectIds):
        if newContentType is not None:
            filehandle['contentType'] = newContentType
        if newFileName is not None:
            filehandle['fileName'] = newFileName
        copyFileHandleRequest['copyRequests'].append({"newContentType":filehandle['contentType'],
                                                      "newFileName":filehandle['fileName'],
                                                      "originalFile":{"associateObjectType":associateObjectType,
                                                                      "fileHandleId":filehandle['id'],
                                                                      "associateObjectId":associateObjectId}})
    copiedFileHandle = syn.restPOST('/filehandles/copy',body=json.dumps(copyFileHandleRequest),endpoint=syn.fileHandleEndpoint)
    return(copiedFileHandle)

def copy(syn, entity, destinationId, copyWikiPage=True, copyAnnotations=True, **kwargs):
    """
    - This function will assist users in copying entities (Tables, Links, Files, Folders, Projects),
      and will recursively copy everything in directories.
    - A Mapping of the old entities to the new entities will be created and all the wikis of each entity
      will also be copied over and links to synapse Ids will be updated.

    :param syn:             A synapse object: syn = synapseclient.login()- Must be logged into synapse

    :param entity:          A synapse entity ID

    :param destinationId:   Synapse ID of a folder/project that the copied entity is being copied to

    :param copyWikiPage:    Determines whether the wiki of the entity is copied over
                            Default is True

    :param copyAnnotations: Determines whether annotations of a File/Folder is copied over
                            Default is True

    Examples::                        
    import synapseutils
    import synapseclient
    syn = synapseclient.login()
    synapseutils.copy(syn, ...)

    Examples and extra parameters unique to each copy function
    -- COPYING FILES

    :param version:         Can specify version of a file. 
                            Default to None

    :param updateExisting:  When the destination has an entity that has the same name, 
                            users can choose to update that entity.  
                            It must be the same entity type
                            Default to False
    
    :param setProvenance:   Has three values to set the provenance of the copied entity:
                                traceback: Sets to the source entity
                                existing: Sets to source entity's original provenance (if it exists)
                                None: No provenance is set

    Examples::
    synapseutils.copy(syn, "syn12345", "syn45678", updateExisting=False, setProvenance = "traceback",version=None)

    -- COPYING FOLDERS/PROJECTS

    :param excludeTypes:    Accepts a list of entity types (file, table, link) which determines which entity types to not copy.
                            Defaults to an empty list.

    Examples::
    #This will copy everything in the project into the destinationId except files and tables.
    synapseutils.copy(syn, "syn123450","syn345678",excludeTypes=["file","table"])

    :returns: a mapping between the original and copied entity: {'syn1234':'syn33455'}
    """
    updateLinks = kwargs.get('updateLinks', True)
    updateSynIds = kwargs.get('updateSynIds', True)
    entitySubPageId = kwargs.get('entitySubPageId',None)
    destinationSubPageId = kwargs.get('destinationSubPageId',None)

    mapping = _copyRecursive(syn, entity, destinationId, copyAnnotations = copyAnnotations, **kwargs)
    if copyWikiPage:
        for oldEnt in mapping:
            newWikig = copyWiki(syn, oldEnt, mapping[oldEnt], entitySubPageId = entitySubPageId,
                                destinationSubPageId = destinationSubPageId, updateLinks = updateLinks, 
                                updateSynIds = updateSynIds, entityMap = mapping)
    return(mapping)

def _copyRecursive(syn, entity, destinationId, mapping=None, copyAnnotations = True, **kwargs):
    """
    Recursively copies synapse entites, but does not copy the wikis

    :param entity:             A synapse entity ID

    :param destinationId:      Synapse ID of a folder/project that the copied entity is being copied to
    
    :returns: a mapping between the original and copied entity: {'syn1234':'syn33455'}
    """

    version = kwargs.get('version', None)
    setProvenance = kwargs.get('setProvenance', "traceback")
    excludeTypes = kwargs.get('excludeTypes',[])
    updateExisting = kwargs.get('updateExisting',False)
    copiedId = None
    if mapping is None:
        mapping=dict()
    #Check that passed in excludeTypes is file, table, and link
    if not isinstance(excludeTypes,list):
        raise ValueError("Excluded types must be a list") 
    elif not all([i in ["file","link","table"] for i in excludeTypes]):
        raise ValueError("Excluded types can only be a list of these values: file, table, and link") 

    ent = syn.get(entity,downloadFile=False)
    if ent.id == destinationId:
        raise ValueError("destinationId cannot be the same as entity id")

    if (isinstance(ent, Project) or isinstance(ent, Folder)) and version is not None:
        raise ValueError("Cannot specify version when copying a project of folder")

    if not isinstance(ent, (Project, Folder, File, Link, Schema, Entity)):
        raise ValueError("Not able to copy this type of file")

    if isinstance(ent, Project):
        if not isinstance(syn.get(destinationId),Project):
            raise ValueError("You must give a destinationId of a new project to copy projects")
        copiedId = destinationId
        entities = syn.chunkedQuery('select id, name from entity where parentId=="%s"' % ent.id)
        for i in entities:
            mapping = _copyRecursive(syn, i['entity.id'], destinationId, mapping = mapping, copyAnnotations = copyAnnotations, **kwargs)
    elif isinstance(ent, Folder):
        copiedId = _copyFolder(syn, ent.id, destinationId, mapping = mapping, copyAnnotations = copyAnnotations, **kwargs)
    elif isinstance(ent, File) and "file" not in excludeTypes:
        copiedId = _copyFile(syn, ent.id, destinationId, version = version, updateExisting = updateExisting, 
                             setProvenance = setProvenance, copyAnnotations = copyAnnotations)
    elif isinstance(ent, Link) and "link" not in excludeTypes:
        copiedId = _copyLink(syn, ent.id, destinationId, updateExisting = updateExisting)
    elif isinstance(ent, Schema) and "table" not in excludeTypes:
        copiedId = _copyTable(syn, ent.id, destinationId, updateExisting = updateExisting)

    if copiedId is not None:
        mapping[ent.id] = copiedId
        print("Copied %s to %s" % (ent.id,copiedId))
    else:
        print("%s not copied" % ent.id)
    return(mapping)

def _copyFolder(syn, entity, destinationId, mapping=None, copyAnnotations=True, **kwargs):
    """
    Copies synapse folders

    :param entity:          A synapse ID of a Folder entity

    :param destinationId:   Synapse ID of a project/folder that the folder wants to be copied to
    
    :param excludeTypes:    Accepts a list of entity types (file, table, link) which determines which entity types to not copy.
                            Defaults to an empty list.
    """
    oldFolder = syn.get(entity)
    updateExisting = kwargs.get('updateExisting',False)

    if mapping is None:
        mapping=dict()
    #CHECK: If Folder name already exists, raise value error
    if not updateExisting:
        existingEntity = syn._findEntityIdByNameAndParent(oldFolder.name, parent=destinationId)
        if existingEntity is not None:
            raise ValueError('An entity named "%s" already exists in this location. Folder could not be copied'%oldFolder.name)

    newFolder = Folder(name = oldFolder.name, parent = destinationId)
    if copyAnnotations:
        newFolder.annotations = oldFolder.annotations
    newFolder = syn.store(newFolder)
    entities = syn.chunkedQuery('select id, name from entity where parentId=="%s"'% entity)
    for ent in entities:
        copied = _copyRecursive(syn, ent['entity.id'],newFolder.id,mapping, **kwargs)
    return(newFolder.id)

def _copyFile(syn, entity, destinationId, version=None, updateExisting=False, setProvenance="traceback", copyAnnotations=True):
    """
    Copies most recent version of a file to a specified synapse ID.

    :param entity:          A synapse ID of a File entity

    :param destinationId:   Synapse ID of a folder/project that the file wants to be copied to

    :param version:         Can specify version of a file. 
                            Default to None

    :param updateExisting:  Can choose to update files that have the same name 
                            Default to False
    
    :param setProvenance:   Has three values to set the provenance of the copied entity:
                                traceback: Sets to the source entity
                                existing: Sets to source entity's original provenance (if it exists)
                                None: No provenance is set
    """
    ent = syn.get(entity, downloadFile=False, version=version, followLink=False)
    #CHECK: If File is in the same parent directory (throw an error) (Can choose to update files)
    if not updateExisting:
        existingEntity = syn._findEntityIdByNameAndParent(ent.name, parent=destinationId)
        if existingEntity is not None:
            raise ValueError('An entity named "%s" already exists in this location. File could not be copied'%ent.name)
    profile = syn.getUserProfile()
    # get provenance earlier to prevent errors from being called in the end
    # If traceback, set activity to old entity
    if setProvenance == "traceback":
        act = Activity("Copied file", used=ent)
    # if existing, check if provenance exists
    elif setProvenance == "existing":
        try:
            act = syn.getProvenance(ent.id)
        except SynapseHTTPError as e:
            if e.response.status_code == 404:
                act = None
            else:
                raise e
    elif setProvenance is None or setProvenance.lower() == 'none':
        act = None
    else:
        raise ValueError('setProvenance must be one of None, existing, or traceback')
    #Grab entity bundle
    bundle = syn._getEntityBundle(ent.id, version=ent.versionNumber, bitFlags=0x800|0x1)
    fileHandle = synapseclient.utils.find_data_file_handle(bundle)
    createdBy = fileHandle['createdBy']
    #CHECK: If the user created the file, copy the file by using fileHandleId else copy the fileHandle
    if profile.ownerId == createdBy:
        newdataFileHandleId = ent.dataFileHandleId
    else:
        copiedFileHandle = copyFileHandles(syn, [fileHandle], ["FileEntity"], [bundle['entity']['id']])
        newdataFileHandleId = copiedFileHandle['copyResults'][0]['newFileHandle']['id']

    new_ent = File(dataFileHandleId=newdataFileHandleId,  name=ent.name, parentId=destinationId)
    #Set annotations here
    if copyAnnotations:
        new_ent.annotations = ent.annotations
    #Store provenance if act is not None
    if act is not None:
        new_ent = syn.store(new_ent, activity=act)
    else:
        new_ent = syn.store(new_ent)
    #Leave this return statement for test
    return new_ent['id']

def _copyTable(syn, entity, destinationId, updateExisting=False):
    """
    Copies synapse Tables

    :param entity:          A synapse ID of Table Schema

    :param destinationId:   Synapse ID of a project that the Table wants to be copied to

    """

    print("Getting table %s" % entity)
    myTableSchema = syn.get(entity)
    #CHECK: If Table name already exists, raise value error
    existingEntity = syn._findEntityIdByNameAndParent(myTableSchema.name, parent=destinationId)
    if existingEntity is not None:
        raise ValueError('An entity named "%s" already exists in this location. Table could not be copied'%myTableSchema.name)

    d = syn.tableQuery('select * from %s' % myTableSchema.id, includeRowIdAndRowVersion=False)

    colIds = myTableSchema.columnIds

    newTableSchema = Schema(name = myTableSchema.name,
                           parent = destinationId,
                           columns=colIds)

    print("Created new table using schema %s" % newTableSchema.name)
    newTable = Table(schema=newTableSchema,values=d.filepath)
    newTable = syn.store(newTable)
    return(newTable.schema.id)

def _copyLink(syn, entity, destinationId, updateExisting=False):
    """
    Copies Link entities

    :param entity:          A synapse ID of a Link entity

    :param destinationId:   Synapse ID of a folder/project that the file wants to be copied to
    """
    ent = syn.get(entity)
    #CHECK: If Link is in the same parent directory (throw an error)
    if not updateExisting:
        existingEntity = syn._findEntityIdByNameAndParent(ent.name, parent=destinationId)
        if existingEntity is not None:
            raise ValueError('An entity named "%s" already exists in this location. Link could not be copied'%ent.name)

    newLink = Link(ent.linksTo['targetId'],parent=destinationId,targetVersion=ent.linksTo['targetVersionNumber'])
    try:
        newLink = syn.store(newLink)
        return(newLink.id)
    except SynapseHTTPError as e:
        if e.response.status_code == 404:
            print("WARNING: The target of this link %s no longer exists" % ent.id)
            return(None)
        else:
            raise e

def _getSubWikiHeaders(wikiHeaders,subPageId,mapping=None):
    """
    Function to assist in getting wiki headers of subwikipages
    """
    subPageId = str(subPageId)
    for i in wikiHeaders:
        # This is for the first match 
        # If it isnt the actual parent, it will turn the first match into a parent node which will not have a parentId
        if i['id'] == subPageId:
            if mapping is None:
                i.pop("parentId",None)
                mapping = [i]
            else:
                mapping.append(i)
        elif i.get('parentId') == subPageId:
            mapping = _getSubWikiHeaders(wikiHeaders,subPageId=i['id'],mapping=mapping)
    return(mapping)


def _updateSynIds(newWikis, wikiIdMap, entityMap):
    print("Updating Synapse references:\n")
    for oldWikiId in wikiIdMap.keys():
        # go through each wiki page once more:
        newWikiId = wikiIdMap[oldWikiId]
        newWiki = newWikis[newWikiId]
        print('Updated Synapse references for Page: %s\n' %newWikiId)
        s = newWiki.markdown

        for oldSynId in entityMap.keys():
            # go through each wiki page once more:
            newSynId = entityMap[oldSynId]
            oldSynId = oldSynId + "\\b"
            s = re.sub(oldSynId, newSynId, s)
        print("Done updating Synpase IDs.\n")
        newWikis[newWikiId].markdown = s
    return(newWikis)


def _updateInternalLinks(newWikis, wikiIdMap, entity, destinationId ):
    print("Updating internal links:\n")
    for oldWikiId in wikiIdMap.keys():
        # go through each wiki page once more:
        newWikiId=wikiIdMap[oldWikiId]
        newWiki=newWikis[newWikiId]
        print("\tUpdating internal links for Page: %s\n" % newWikiId)
        s=newWiki.markdown
        # in the markdown field, replace all occurrences of entity/wiki/abc with destinationId/wiki/xyz,
        # where wikiIdMap maps abc->xyz
        # replace <entity>/wiki/<oldWikiId> with <destinationId>/wiki/<newWikiId> 
        for oldWikiId2 in wikiIdMap.keys():
            oldProjectAndWikiId = "%s/wiki/%s\\b" % (entity, oldWikiId2)
            newProjectAndWikiId = "%s/wiki/%s" % (destinationId, wikiIdMap[oldWikiId2])
            s=re.sub(oldProjectAndWikiId, newProjectAndWikiId, s)
        # now replace any last references to entity with destinationId
        s=re.sub(entity, destinationId, s)
        newWikis[newWikiId].markdown=s
    return(newWikis)


def copyWiki(syn, entity, destinationId, entitySubPageId=None, destinationSubPageId=None, updateLinks=True, updateSynIds=True, entityMap=None):
    """
    Copies wikis and updates internal links

    :param syn:                     A synapse object: syn = synapseclient.login()- Must be logged into synapse

    :param entity:                  A synapse ID of an entity whose wiki you want to copy

    :param destinationId:           Synapse ID of a folder/project that the wiki wants to be copied to
    
    :param updateLinks:             Update all the internal links. (e.g. syn1234/wiki/34345 becomes syn3345/wiki/49508)
                                    Defaults to True

    :param updateSynIds:            Update all the synapse ID's referenced in the wikis. (e.g. syn1234 becomes syn2345)
                                    Defaults to True but needs an entityMap

    :param entityMap:               An entity map {'oldSynId','newSynId'} to update the synapse IDs referenced in the wiki
                                    Defaults to None 

    :param entitySubPageId:         Can specify subPageId and copy all of its subwikis
                                    Defaults to None, which copies the entire wiki
                                    subPageId can be found: https://www.synapse.org/#!Synapse:syn123/wiki/1234
                                    In this case, 1234 is the subPageId. 

    :param destinationSubPageId:    Can specify destination subPageId to copy wikis to
                                    Defaults to None

    :returns: A list of Objects with three fields: id, title and parentId.
    """
    oldOwn = syn.get(entity,downloadFile=False)
    # getWikiHeaders fails when there is no wiki
    try:
        oldWikiHeaders = syn.getWikiHeaders(oldOwn)
    except SynapseHTTPError as e:
        if e.response.status_code == 404:
            return([])
        else:
            raise e

    if entitySubPageId is not None:
        oldWikiHeaders = _getSubWikiHeaders(oldWikiHeaders,entitySubPageId)
        #If entitySubPageId is given but not destinationSubPageId, set the pageId to "" (will get the root page)
        if destinationSubPageId is None:
            destinationSubPageId = ""
    newOwn =syn.get(destinationId,downloadFile=False)
    wikiIdMap = dict()
    newWikis = dict()

    for wikiHeader in oldWikiHeaders:
        wiki = syn.getWiki(oldOwn, wikiHeader.id)
        print('Got wiki %s' % wikiHeader.id)
        if wiki['attachmentFileHandleIds'] == []:
            new_file_handles = []
        elif wiki['attachmentFileHandleIds'] != []:
            results = [syn._getFileHandleDownload(filehandleId, wiki.id, objectType='WikiAttachment') for filehandleId in wiki['attachmentFileHandleIds']]
            #Get rid of the previews
            nopreviews = [attach['fileHandle'] for attach in results if attach['fileHandle']['concreteType'] != "org.sagebionetworks.repo.model.file.PreviewFileHandle"]
            copiedFileHandles = copyFileHandles(syn, nopreviews, ["WikiAttachment"]*len(nopreviews), [wiki.id]*len(nopreviews))
            new_file_handles = [filehandle['newFileHandle']['id'] for filehandle in copiedFileHandles['copyResults']]

        #for some reason some wikis don't have titles?
        if hasattr(wikiHeader, 'parentId'):
            newWikiPage = Wiki(owner=newOwn, title=wiki.get('title',''), markdown=wiki.markdown, fileHandles=new_file_handles, parentWikiId=wikiIdMap[wiki.parentWikiId])
            newWikiPage = syn.store(newWikiPage)
        else:
            if destinationSubPageId is not None:
                newWikiPage = syn.getWiki(newOwn, destinationSubPageId)
                newWikiPage.fileHandles = new_file_handles
                newWikiPage.markdown = wiki.markdown
                newWikiPage.title = wiki.get('title','')
                #Need to add logic to update titles here
                newWikiPage = syn.store(newWikiPage)
            else:
                newWikiPage = Wiki(owner=newOwn, title=wiki.get('title',''), markdown=wiki.markdown, fileHandles=new_file_handles, parentWikiId=destinationSubPageId)
                newWikiPage = syn.store(newWikiPage)
        newWikis[newWikiPage.id]=newWikiPage
        wikiIdMap[wiki.id] =newWikiPage.id

    if updateLinks:
        newWikis = _updateInternalLinks(newWikis, wikiIdMap, entity, destinationId)

    if updateSynIds and entityMap is not None:
        newWikis = _updateSynIds(newWikis, wikiIdMap, entityMap)
    
    print("Storing new Wikis\n")
    for oldWikiId in wikiIdMap.keys():
        newWikiId = wikiIdMap[oldWikiId]
        newWikis[newWikiId] = syn.store(newWikis[newWikiId])
        print("\tStored: %s\n" % newWikiId)
    newWh = syn.getWikiHeaders(newOwn)
    return(newWh)
