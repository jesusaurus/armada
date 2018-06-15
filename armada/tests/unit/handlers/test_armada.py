# Copyright 2017 AT&T Intellectual Property.  All other rights reserved.
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

import mock
import yaml

from armada import const
from armada.handlers import armada
from armada.tests.unit import base
from armada.utils.release import release_prefixer
from armada.exceptions.armada_exceptions import ProtectedReleaseException

TEST_YAML = """
---
schema: armada/Manifest/v1
metadata:
  schema: metadata/Document/v1
  name: example-manifest
data:
  release_prefix: armada
  chart_groups:
    - example-group
---
schema: armada/ChartGroup/v1
metadata:
  schema: metadata/Document/v1
  name: example-group
data:
  description: this is a test
  sequenced: False
  chart_group:
    - example-chart-1
    - example-chart-2
    - example-chart-3
---
schema: armada/Chart/v1
metadata:
  schema: metadata/Document/v1
  name: example-chart-3
data:
    chart_name: test_chart_3
    release: test_chart_3
    namespace: test
    values: {}
    source:
      type: local
      location: /tmp/dummy/armada
      subpath: chart_3
    dependencies: []
    protected:
      continue_processing: false
    wait:
      timeout: 10
    upgrade:
      no_hooks: false
      options:
        force: true
        recreate_pods: true
---
schema: armada/Chart/v1
metadata:
  schema: metadata/Document/v1
  name: example-chart-2
data:
    chart_name: test_chart_2
    release: test_chart_2
    namespace: test
    values: {}
    source:
      type: local
      location: /tmp/dummy/armada
      subpath: chart_2
    dependencies: []
    protected:
      continue_processing: true
    wait:
      timeout: 10
    upgrade:
      no_hooks: false
      options:
        force: true
        recreate_pods: true
---
schema: armada/Chart/v1
metadata:
  schema: metadata/Document/v1
  name: example-chart-1
data:
    chart_name: test_chart_1
    release: test_chart_1
    namespace: test
    values: {}
    source:
      type: git
      location: git://github.com/dummy/armada
      subpath: chart_1
      reference: master
    dependencies: []
    wait:
      timeout: 10
"""

CHART_SOURCES = [('git://github.com/dummy/armada', 'chart_1'),
                 ('/tmp/dummy/armada', 'chart_2'),
                 ('/tmp/dummy/armada', 'chart_3')]


class ArmadaHandlerTestCase(base.ArmadaTestCase):

    def _test_pre_flight_ops(self, armada_obj):
        armada_obj.pre_flight_ops()

        expected_config = {
            'armada': {
                'release_prefix': 'armada',
                'chart_groups': [
                    {
                        'chart_group': [
                            {
                                'chart': {
                                    'dependencies': [],
                                    'chart_name': 'test_chart_1',
                                    'namespace': 'test',
                                    'release': 'test_chart_1',
                                    'source': {
                                        'location': (
                                            'git://github.com/dummy/armada'),
                                        'reference': 'master',
                                        'subpath': 'chart_1',
                                        'type': 'git'
                                    },
                                    'source_dir': CHART_SOURCES[0],
                                    'values': {},
                                    'wait': {
                                        'timeout': 10
                                    }
                                }
                            },
                            {
                                'chart': {
                                    'dependencies': [],
                                    'chart_name': 'test_chart_2',
                                    'namespace': 'test',
                                    'protected': {
                                        'continue_processing': True
                                    },
                                    'release': 'test_chart_2',
                                    'source': {
                                        'location': '/tmp/dummy/armada',
                                        'subpath': 'chart_2',
                                        'type': 'local'
                                    },
                                    'source_dir': CHART_SOURCES[1],
                                    'values': {},
                                    'wait': {
                                        'timeout': 10
                                    },
                                    'upgrade': {
                                        'no_hooks': False,
                                        'options': {
                                            'force': True,
                                            'recreate_pods': True
                                        }
                                    }
                                }
                            },
                            {
                                'chart': {
                                    'dependencies': [],
                                    'chart_name': 'test_chart_3',
                                    'namespace': 'test',
                                    'protected': {
                                        'continue_processing': False
                                    },
                                    'release': 'test_chart_3',
                                    'source': {
                                        'location': '/tmp/dummy/armada',
                                        'subpath': 'chart_3',
                                        'type': 'local'
                                    },
                                    'source_dir': CHART_SOURCES[2],
                                    'values': {},
                                    'wait': {
                                        'timeout': 10
                                    },
                                    'upgrade': {
                                        'no_hooks': False,
                                        'options': {
                                            'force': True,
                                            'recreate_pods': True
                                        }
                                    }
                                }
                            }
                        ],
                        'description': 'this is a test',
                        'name': 'example-group',
                        'sequenced': False
                    }
                ]
            }
        }

        self.assertTrue(hasattr(armada_obj, 'manifest'))
        self.assertIsInstance(armada_obj.manifest, dict)
        self.assertIn('armada', armada_obj.manifest)
        self.assertEqual(expected_config, armada_obj.manifest)

    @mock.patch.object(armada, 'source')
    @mock.patch('armada.handlers.armada.Tiller')
    def test_pre_flight_ops(self, mock_tiller, mock_source):
        """Test pre-flight checks and operations."""
        yaml_documents = list(yaml.safe_load_all(TEST_YAML))
        armada_obj = armada.Armada(yaml_documents)

        # Mock methods called by `pre_flight_ops()`.
        m_tiller = mock_tiller.return_value
        m_tiller.tiller_status.return_value = True
        mock_source.git_clone.return_value = CHART_SOURCES[0][0]

        self._test_pre_flight_ops(armada_obj)

        mock_tiller.assert_called_once_with(tiller_host=None,
                                            tiller_namespace='kube-system',
                                            tiller_port=44134,
                                            dry_run=False)
        mock_source.git_clone.assert_called_once_with(
            'git://github.com/dummy/armada', 'master', auth_method=None,
            proxy_server=None)

    @mock.patch.object(armada, 'source')
    @mock.patch('armada.handlers.armada.Tiller')
    def test_post_flight_ops(self, mock_tiller, mock_source):
        """Test post-flight operations."""
        yaml_documents = list(yaml.safe_load_all(TEST_YAML))
        armada_obj = armada.Armada(yaml_documents)

        # Mock methods called by `pre_flight_ops()`.
        m_tiller = mock_tiller.return_value
        m_tiller.tiller_status.return_value = True
        mock_source.git_clone.return_value = CHART_SOURCES[0][0]

        self._test_pre_flight_ops(armada_obj)

        armada_obj.post_flight_ops()

        for group in armada_obj.manifest['armada']['chart_groups']:
            for counter, chart in enumerate(group.get('chart_group')):
                if chart.get('chart').get('source').get('type') == 'git':
                    mock_source.source_cleanup.assert_called_with(
                        CHART_SOURCES[counter][0])

    def _test_sync(self, known_releases):
        """Test install functionality from the sync() method."""

        @mock.patch.object(armada.Armada, 'post_flight_ops')
        @mock.patch.object(armada.Armada, 'pre_flight_ops')
        @mock.patch('armada.handlers.armada.ChartBuilder')
        @mock.patch('armada.handlers.armada.Tiller')
        def _do_test(mock_tiller, mock_chartbuilder, mock_pre_flight,
                     mock_post_flight):
            # Instantiate Armada object.
            yaml_documents = list(yaml.safe_load_all(TEST_YAML))
            armada_obj = armada.Armada(yaml_documents)
            armada_obj.show_diff = mock.Mock()

            charts = armada_obj.manifest['armada']['chart_groups'][0][
                'chart_group']

            m_tiller = mock_tiller.return_value
            m_tiller.list_charts.return_value = known_releases

            # Stub out irrelevant methods called by `armada.sync()`.
            mock_chartbuilder.get_source_path.return_value = None
            mock_chartbuilder.get_helm_chart.return_value = None

            armada_obj.sync()

            expected_install_release_calls = []
            expected_update_release_calls = []
            expected_uninstall_release_calls = []

            for c in charts:
                chart = c['chart']
                release = chart['release']
                prefix = armada_obj.manifest['armada']['release_prefix']
                release_name = release_prefixer(prefix, release)
                # Simplified check because the actual code uses logical-or's
                # multiple conditions, so this is enough.
                this_chart_should_wait = chart['wait']['timeout'] > 0

                if release_name not in [x[0] for x in known_releases]:
                    expected_install_release_calls.append(
                        mock.call(
                            mock_chartbuilder().get_helm_chart(),
                            "{}-{}".format(armada_obj.manifest['armada'][
                                           'release_prefix'],
                                           chart['release']),
                            chart['namespace'],
                            values=yaml.safe_dump(chart['values']),
                            wait=this_chart_should_wait,
                            timeout=chart['wait']['timeout']
                        )
                    )
                else:
                    target_release = None
                    for known_release in known_releases:
                        if known_release[0] == release_name:
                            target_release = known_release
                            break
                    if target_release:
                        status = target_release[4]
                        if status == const.STATUS_FAILED:
                            protected = chart.get('protected', {})
                            if not protected:
                                expected_uninstall_release_calls.append(
                                    mock.call(release_name))
                                expected_install_release_calls.append(
                                    mock.call(
                                        mock_chartbuilder().get_helm_chart(),
                                        "{}-{}".format(
                                            armada_obj.manifest['armada'][
                                                'release_prefix'],
                                            chart['release']),
                                        chart['namespace'],
                                        values=yaml.safe_dump(chart['values']),
                                        wait=this_chart_should_wait,
                                        timeout=chart['wait']['timeout']
                                    )
                                )
                            else:
                                p_continue = protected.get(
                                    'continue_processing', False)
                                if p_continue:
                                    continue
                                else:
                                    break

                        if status == const.STATUS_DEPLOYED:
                            upgrade = chart.get('upgrade', {})
                            disable_hooks = upgrade.get('no_hooks', False)
                            force = upgrade.get('force', False)
                            recreate_pods = upgrade.get('recreate_pods', False)

                            expected_update_release_calls.append(
                                mock.call(
                                    mock_chartbuilder().get_helm_chart(),
                                    "{}-{}".format(
                                        armada_obj.manifest['armada'][
                                            'release_prefix'],
                                        chart['release']),
                                    chart['namespace'],
                                    pre_actions={},
                                    post_actions={},
                                    disable_hooks=disable_hooks,
                                    force=force,
                                    recreate_pods=recreate_pods,
                                    values=yaml.safe_dump(chart['values']),
                                    wait=this_chart_should_wait,
                                    timeout=chart['wait']['timeout']
                                )
                            )

            # Verify that at least 1 release is either installed or updated.
            self.assertTrue(
                len(expected_install_release_calls) >= 1 or
                len(expected_update_release_calls) >= 1)
            # Verify that the expected number of non-deployed releases are
            # installed with expected arguments.
            self.assertEqual(len(expected_install_release_calls),
                             m_tiller.install_release.call_count)
            m_tiller.install_release.assert_has_calls(
                expected_install_release_calls)
            # Verify that the expected number of deployed releases are
            # updated with expected arguments.
            self.assertEqual(len(expected_update_release_calls),
                             m_tiller.update_release.call_count)
            m_tiller.update_release.assert_has_calls(
                expected_update_release_calls)

        _do_test()

    def _get_chart_by_name(self, name):
        name = name.split('armada-')[-1]
        yaml_documents = list(yaml.safe_load_all(TEST_YAML))
        return [c for c in yaml_documents
                if c['data'].get('chart_name') == name][0]

    def test_armada_sync_with_no_deployed_releases(self):
        known_releases = []
        self._test_sync(known_releases)

    def test_armada_sync_with_one_deployed_release(self):
        c1 = 'armada-test_chart_1'

        known_releases = [
            [c1, None, self._get_chart_by_name(c1), None,
             const.STATUS_DEPLOYED]
        ]
        self._test_sync(known_releases)

    def test_armada_sync_with_both_deployed_releases(self):
        c1 = 'armada-test_chart_1'
        c2 = 'armada-test_chart_2'

        known_releases = [
            [c1, None, self._get_chart_by_name(c1), None,
             const.STATUS_DEPLOYED],
            [c2, None, self._get_chart_by_name(c2), None,
             const.STATUS_DEPLOYED]
        ]
        self._test_sync(known_releases)

    def test_armada_sync_with_unprotected_releases(self):
        c1 = 'armada-test_chart_1'

        known_releases = [
            [c1, None, self._get_chart_by_name(c1), None,
             const.STATUS_FAILED]
        ]
        self._test_sync(known_releases)

    def test_armada_sync_with_protected_releases_continue(self):
        c1 = 'armada-test_chart_1'
        c2 = 'armada-test_chart_2'

        known_releases = [
            [c2, None, self._get_chart_by_name(c2), None,
             const.STATUS_FAILED],
            [c1, None, self._get_chart_by_name(c1), None,
             const.STATUS_FAILED]
        ]
        self._test_sync(known_releases)

    def test_armada_sync_with_protected_releases_halt(self):
        c3 = 'armada-test_chart_3'

        known_releases = [
            [c3, None, self._get_chart_by_name(c3), None,
             const.STATUS_FAILED]
        ]

        def _test_method():
            self._test_sync(known_releases)

        self.assertRaises(
            ProtectedReleaseException,
            _test_method)

    @mock.patch.object(armada.Armada, 'post_flight_ops')
    @mock.patch.object(armada.Armada, 'pre_flight_ops')
    @mock.patch('armada.handlers.armada.ChartBuilder')
    @mock.patch('armada.handlers.armada.Tiller')
    def test_install(self, mock_tiller, mock_chartbuilder, mock_pre_flight,
                     mock_post_flight):
        '''Test install functionality from the sync() method'''

        # Instantiate Armada object.
        yaml_documents = list(yaml.safe_load_all(TEST_YAML))
        armada_obj = armada.Armada(yaml_documents)

        charts = armada_obj.manifest['armada']['chart_groups'][0][
            'chart_group']
        chart_1 = charts[0]['chart']
        chart_2 = charts[1]['chart']

        # Mock irrelevant methods called by `armada.sync()`.
        mock_tiller.list_charts.return_value = []
        mock_chartbuilder.get_source_path.return_value = None
        mock_chartbuilder.get_helm_chart.return_value = None

        armada_obj.sync()

        # Check params that should be passed to `tiller.install_release()`.
        method_calls = [
            mock.call(
                mock_chartbuilder().get_helm_chart(),
                "{}-{}".format(armada_obj.manifest['armada']['release_prefix'],
                               chart_1['release']),
                chart_1['namespace'],
                values=yaml.safe_dump(chart_1['values']),
                timeout=10,
                wait=True),
            mock.call(
                mock_chartbuilder().get_helm_chart(),
                "{}-{}".format(armada_obj.manifest['armada']['release_prefix'],
                               chart_2['release']),
                chart_2['namespace'],
                values=yaml.safe_dump(chart_2['values']),
                timeout=10,
                wait=True)
        ]
        mock_tiller.return_value.install_release.assert_has_calls(method_calls)
