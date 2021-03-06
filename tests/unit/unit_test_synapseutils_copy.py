# coding=utf-8
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from mock import patch, call
from nose.tools import assert_raises, assert_equals
import unit
import uuid

from synapseclient import Project, File
import synapseutils

def setup(module):
    module.syn = unit.syn


def test_copyWiki_empty_Wiki():
    entity = {"id": "syn123"}
    with patch.object(syn, "getWikiHeaders", return_value=None), \
            patch.object(syn, "get", return_value=entity):
        synapseutils.copyWiki(syn, "syn123", "syn456", updateLinks=False)

def test_copyWiki_input_validation():
    to_copy=[{'id': '8688', 'title': 'A Test Wiki'},
             {'id': '8689', 'title': 'A sub-wiki', 'parentId': '8688'},
             {'id': '8690', 'title': 'A sub-sub-wiki', 'parentId': '8689'}]
    wiki={"id": "8786",
          "title": "A Test Wiki",
          "markdown": "some text"
         }
    entity={"id":"syn123"}
    expected_calls=[call({'id': 'syn123'}, '4'),
                    call({'id': 'syn123'}, '8688'),
                    call({'id': 'syn123'}, '8689'),
                    call({'id': 'syn123'}, '8690')]
    with patch.object(syn, "getWikiHeaders", return_value=to_copy),\
            patch.object(syn, "get", return_value=entity),\
            patch.object(syn, "getWiki", return_value=wiki) as mock_getWiki,\
            patch.object(syn, "store", return_value=wiki):
        synapseutils.copyWiki(syn, "syn123", "syn456", entitySubPageId="8688", destinationSubPageId="4",
                              updateLinks=False)
        mock_getWiki.assert_has_calls(expected_calls)

        synapseutils.copyWiki(syn, "syn123", "syn456", entitySubPageId=8688.0, destinationSubPageId=4.0,
                              updateLinks=False)
        mock_getWiki.assert_has_calls(expected_calls)

        assert_raises(ValueError, synapseutils.copyWiki, syn, "syn123", "syn456", entitySubPageId="some_string",
                      updateLinks=False)


class TestCopyPermissions:
    """Test copy entities with different permissions"""
    def setup(self):
        self.project_entity = Project(name=str(uuid.uuid4()), id="syn1234")
        self.second_project = Project(name=str(uuid.uuid4()), id="syn2345")
        self.file_ent = File(name='File', parent=self.project_entity.id,
                             id="syn3456")

    def test_dont_copy_read_permissions(self):
        """Entities with READ permissions not copied"""
        permissions = ["READ"]
        with patch.object(syn, "get",
                         return_value=self.file_ent) as patch_syn_get,\
             patch.object(syn, "getPermissions",
                          return_value=permissions) as patch_syn_permissions:
            copied_file = synapseutils.copy(syn, self.file_ent,
                                            destinationId=self.second_project.id,
                                            skipCopyWikiPage=True)
            assert_equals(copied_file, dict())
            patch_syn_get.assert_called_once_with(self.file_ent,
                                                  downloadFile=False)
            patch_syn_permissions.assert_called_once_with(self.file_ent,
                                                          syn.username)


class TestCopyAccessRestriction:
    """Test that entities with access restrictions aren't copied"""
    def setup(self):
        self.project_entity = Project(name=str(uuid.uuid4()), id="syn1234")
        self.second_project = Project(name=str(uuid.uuid4()), id="syn2345")
        self.file_ent = File(name='File', parent=self.project_entity.id)
        self.file_ent.id = "syn3456"

    def test_copy_entity_access_requirements(self):
        # TEST: Entity with access requirement not copied
        access_requirements = {'results': ["fee", "fi"]}
        permissions = ["DOWNLOAD"]
        with patch.object(syn, "get",
                          return_value=self.file_ent) as patch_syn_get,\
             patch.object(syn, "getPermissions",
                          return_value=permissions) as patch_syn_permissions,\
             patch.object(syn, "restGET",
                          return_value=access_requirements) as patch_restget:
            copied_file = synapseutils.copy(syn, self.file_ent,
                                            destinationId=self.second_project.id,
                                            skipCopyWikiPage=True)
            assert_equals(copied_file, dict())
            patch_syn_get.assert_called_once_with(self.file_ent,
                                                  downloadFile=False)
            patch_restget.assert_called_once_with('/entity/{}/accessRequirement'.format(self.file_ent.id))


class TestCopy:
    """Test that entities with access restrictions aren't copied"""
    def setup(self):
        self.project_entity = Project(name=str(uuid.uuid4()), id="syn1234")
        self.second_project = Project(name=str(uuid.uuid4()), id="syn2345")
        self.file_ent = File(name='File', parent=self.project_entity.id)
        self.file_ent.id = "syn3456"

    def test_no_copy_types(self):
        """Docker repositories and EntityViews aren't copied"""
        access_requirements = {'results': []}
        permissions = ["DOWNLOAD"]
        with patch.object(syn, "get",
                          return_value=self.project_entity) as patch_syn_get,\
             patch.object(syn, "getPermissions",
                          return_value=permissions) as patch_syn_permissions,\
             patch.object(syn, "restGET",
                          return_value=access_requirements) as patch_restget,\
             patch.object(syn, "getChildren") as patch_get_children:
            copied_file = synapseutils.copy(syn, self.project_entity,
                                            destinationId=self.second_project.id,
                                            skipCopyWikiPage=True)
            assert_equals(copied_file, {self.project_entity.id:
                                        self.second_project.id})
            calls = [call(self.project_entity, downloadFile=False),
                     call(self.second_project.id)]
            patch_syn_get.assert_has_calls(calls)
            patch_restget.assert_called_once_with('/entity/{}/accessRequirement'.format(self.project_entity.id))
            patch_get_children.assert_called_once_with(self.project_entity,
                                                       includeTypes=['folder', 'file',
                                                                     'table', 'link'])
