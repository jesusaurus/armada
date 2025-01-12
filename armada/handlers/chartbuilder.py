# Copyright 2017 The Armada Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re

from google.protobuf.any_pb2 import Any
from hapi.chart.chart_pb2 import Chart
from hapi.chart.config_pb2 import Config
from hapi.chart.metadata_pb2 import Metadata
from hapi.chart.template_pb2 import Template
from oslo_config import cfg
from oslo_log import log as logging
import yaml

from armada.exceptions import chartbuilder_exceptions
from armada import const

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class ChartBuilder(object):
    '''
    This class handles taking chart intentions as a parameter and turning those
    into proper ``protoc`` Helm charts that can be pushed to Tiller.
    '''

    @classmethod
    def from_chart_doc(cls, chart):
        '''
        Returns a ChartBuilder defined by an Armada Chart doc.

        :param chart: Armada Chart doc for which to build the Helm chart.
        '''

        name = chart['metadata']['name']
        chart_data = chart[const.KEYWORD_DATA]
        source_dir = chart_data.get('source_dir')
        source_directory = os.path.join(*source_dir)
        dependencies = chart_data.get('dependencies')
        if dependencies is not None:
            dependency_builders = []
            for chart_dep in dependencies:
                builder = ChartBuilder.from_chart_doc(chart_dep)
                dependency_builders.append(builder)

            return cls(name, source_directory, dependency_builders)

        return cls.from_source(name, source_directory)

    @classmethod
    def from_source(cls, name, source_directory):
        '''
        Returns a ChartBuilder, which gets it dependencies from within the Helm
        chart itself.

        :param name: A name to use for the chart.
        :param source_directory: The source directory of the Helm chart.
        '''
        dependency_builders = []
        charts_dir = os.path.join(source_directory, 'charts')
        if os.path.isdir(charts_dir):
            for f in os.scandir(charts_dir):
                if not f.is_dir():
                    # TODO: Support ".tgz" dependency charts.

                    # Ignore regular files.
                    continue

                # Ignore directories that start with "." or "_".
                if re.match(r'^[._]', f.name):
                    continue

                builder = ChartBuilder.from_source(f.name, f.path)
                dependency_builders.append(builder)

        return cls(name, source_directory, dependency_builders)

    def __init__(self, name, source_directory, dependency_builders):
        '''
        :param name: A name to use for the chart.
        :param source_directory: The source directory of the Helm chart.
        :param dependency_builders: ChartBuilders to use to build the Helm
               chart's dependency charts.
        '''
        self.name = name
        self.source_directory = source_directory
        self.dependency_builders = dependency_builders

        # cache for generated protoc chart object
        self._helm_chart = None

        # load ignored files from .helmignore if present
        self.ignored_files = self.get_ignored_files()

    def get_ignored_files(self):
        '''Load files to ignore from .helmignore if present.'''
        try:
            ignored_files = []
            if os.path.exists(os.path.join(self.source_directory,
                                           '.helmignore')):
                with open(os.path.join(self.source_directory,
                                       '.helmignore')) as f:
                    ignored_files = f.readlines()
            return [filename.strip() for filename in ignored_files]
        except Exception:
            raise chartbuilder_exceptions.IgnoredFilesLoadException()

    def ignore_file(self, filename):
        '''Returns whether a given ``filename`` should be ignored.

        :param filename: Filename to compare against list of ignored files.
        :returns: True if file matches an ignored file wildcard or exact name,
                  False otherwise.
        '''
        for ignored_file in self.ignored_files:
            if (ignored_file.startswith('*')
                    and filename.endswith(ignored_file.strip('*'))):
                return True
            elif ignored_file == filename:
                return True
        return False

    def get_metadata(self):
        '''Extract metadata from Chart.yaml to construct an instance of
        :class:`hapi.chart.metadata_pb2.Metadata`.
        '''
        try:
            with open(os.path.join(self.source_directory, 'Chart.yaml')) as f:
                chart_yaml = yaml.safe_load(f.read().encode('utf-8'))

        except Exception:
            raise chartbuilder_exceptions.MetadataLoadException()

        # Construct Metadata object.
        return Metadata(
            description=chart_yaml.get('description'),
            name=chart_yaml.get('name'),
            version=chart_yaml.get('version'))

    def get_files(self):
        '''
        Return (non-template) files in this chart.

        Non-template files include all files *except* Chart.yaml, values.yaml,
        values.toml, and any file nested under charts/ or templates/. The only
        exception to this rule is charts/.prov

        The class :class:`google.protobuf.any_pb2.Any` is wrapped around
        each file as that is what Helm uses.

        For more information, see:
        https://github.com/kubernetes/helm/blob/fa06dd176dbbc247b40950e38c09f978efecaecc/pkg/chartutil/load.go

        :returns: List of non-template files.
        :rtype: List[:class:`google.protobuf.any_pb2.Any`]
        '''

        files_to_ignore = ['Chart.yaml', 'values.yaml', 'values.toml']
        non_template_files = []

        def _append_file_to_result(root, rel_folder_path, file):
            abspath = os.path.abspath(os.path.join(root, file))
            relpath = os.path.join(rel_folder_path, file)

            encodings = ('utf-8', 'latin1')
            unicode_errors = []

            for encoding in encodings:
                try:
                    with open(abspath, 'r') as f:
                        file_contents = f.read().encode(encoding)
                except OSError as e:
                    LOG.debug(
                        'Failed to open and read file %s in the helm '
                        'chart directory.', abspath)
                    raise chartbuilder_exceptions.FilesLoadException(
                        file=abspath, details=e)
                except UnicodeError as e:
                    LOG.debug(
                        'Attempting to read %s using encoding %s.', abspath,
                        encoding)
                    msg = "(encoding=%s) %s" % (encoding, str(e))
                    unicode_errors.append(msg)
                else:
                    break

            if len(unicode_errors) == 2:
                LOG.debug(
                    'Failed to read file %s in the helm chart directory.'
                    ' Ensure that it is encoded using utf-8.', abspath)
                raise chartbuilder_exceptions.FilesLoadException(
                    file=abspath,
                    clazz=unicode_errors[0].__class__.__name__,
                    details='\n'.join(e for e in unicode_errors))

            non_template_files.append(
                Any(type_url=relpath, value=file_contents))

        for root, dirs, files in os.walk(self.source_directory):
            relfolder = os.path.split(root)[-1]
            rel_folder_path = os.path.relpath(root, self.source_directory)

            if not any(root.startswith(os.path.join(self.source_directory, x))
                       for x in ['templates', 'charts']):
                for file in files:
                    if (file not in files_to_ignore
                            and file not in non_template_files):
                        _append_file_to_result(root, rel_folder_path, file)
            elif relfolder == 'charts' and '.prov' in files:
                _append_file_to_result(root, rel_folder_path, '.prov')

        return non_template_files

    def get_values(self):
        '''Return the chart's (default) values.'''

        # create config object representing unmarshaled values.yaml
        if os.path.exists(os.path.join(self.source_directory, 'values.yaml')):
            with open(os.path.join(self.source_directory, 'values.yaml')) as f:
                raw_values = f.read()
        else:
            LOG.warn(
                "No values.yaml in %s, using empty values",
                self.source_directory)
            raw_values = ''

        return Config(raw=raw_values)

    def get_templates(self):
        '''Return all the chart templates.

        Process all files in templates/ as a template to attach to the chart,
        building a :class:`hapi.chart.template_pb2.Template` object.
        '''
        chart_name = self.name
        templates = []
        if not os.path.exists(os.path.join(self.source_directory,
                                           'templates')):
            LOG.warn(
                "Chart %s has no templates directory. "
                "No templates will be deployed", chart_name)
        for root, _, files in os.walk(os.path.join(self.source_directory,
                                                   'templates'), topdown=True):
            for tpl_file in files:
                tname = os.path.relpath(
                    os.path.join(root, tpl_file),
                    os.path.join(self.source_directory, 'templates'))
                if self.ignore_file(tname):
                    LOG.debug('Ignoring file %s', tname)
                    continue

                with open(os.path.join(root, tpl_file)) as f:
                    templates.append(
                        Template(name=tname, data=f.read().encode()))

        return templates

    def get_helm_chart(self):
        '''Return a Helm chart object.

        Constructs a :class:`hapi.chart.chart_pb2.Chart` object from the
        ``chart`` intentions, including all dependencies.
        '''
        if not self._helm_chart:
            self._helm_chart = self._get_helm_chart()

        return self._helm_chart

    def _get_helm_chart(self):
        LOG.info(
            "Building chart %s from path %s", self.name, self.source_directory)
        dependencies = []
        for dep_builder in self.dependency_builders:
            LOG.info(
                "Building dependency chart %s for chart %s.", dep_builder.name,
                self.name)
            try:
                dependencies.append(dep_builder.get_helm_chart())
            except Exception:
                raise chartbuilder_exceptions.DependencyException(self.name)

        try:
            helm_chart = Chart(
                metadata=self.get_metadata(),
                templates=self.get_templates(),
                dependencies=dependencies,
                values=self.get_values(),
                files=self.get_files())
        except Exception as e:
            raise chartbuilder_exceptions.HelmChartBuildException(
                self.name, details=e)

        return helm_chart

    def dump(self):
        '''Dumps a chart object as a serialized string so that we can perform a
        diff.

        It recurses into dependencies.
        '''
        return self.get_helm_chart().SerializeToString()
