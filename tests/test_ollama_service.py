import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from app.services.ollama import OllamaService
from app.services.format_utils import format_duration
import json
import os
import tempfile
from datetime import datetime, timedelta

class TestOllamaService(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.ollama_service = OllamaService(self.app)

    def test_ping_endpoint(self):
        response = self.client.get('/ping')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_api_test_endpoint(self):
        response = self.client.get('/api/test')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"message": "API is working"})

    @patch('app.services.ollama.requests.get')
    def test_index_route_no_models(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {'models': []}
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No models currently running', response.data)

    def test_calculate_memory_split_full_gpu(self):
        """Test when model is fully on GPU"""
        result = self.ollama_service.calculate_memory_split(7000000000, 7000000000)
        self.assertEqual(result['cpu_percent'], 0)
        self.assertEqual(result['gpu_percent'], 100)
        self.assertIn('100% GPU', result['display'])
        self.assertNotIn('CPU', result['display'])

    def test_calculate_memory_split_full_cpu(self):
        """Test when model is fully on CPU"""
        result = self.ollama_service.calculate_memory_split(7000000000, 0)
        self.assertEqual(result['cpu_percent'], 100)
        self.assertEqual(result['gpu_percent'], 0)
        self.assertIn('100% CPU', result['display'])
        self.assertNotIn('GPU', result['display'])

    def test_calculate_memory_split_mixed(self):
        """Test when model is split between CPU and GPU"""
        result = self.ollama_service.calculate_memory_split(7000000000, 1200000000)
        self.assertEqual(result['cpu_percent'], 83)
        self.assertEqual(result['gpu_percent'], 17)
        self.assertIn('83%', result['display'])
        self.assertIn('17%', result['display'])

    def test_calculate_memory_split_zero_size(self):
        """Test edge case with zero size"""
        result = self.ollama_service.calculate_memory_split(0, 0)
        self.assertEqual(result['cpu_percent'], 0)
        self.assertEqual(result['gpu_percent'], 0)

    def test_calculate_memory_split_vram_exceeds_size(self):
        """Test edge case where VRAM exceeds total size (shouldn't happen but be defensive)"""
        result = self.ollama_service.calculate_memory_split(1000000000, 2000000000)
        self.assertEqual(result['cpu_percent'], 0)
        self.assertEqual(result['gpu_percent'], 100)

    @patch('app.services.ollama.requests.get')
    def test_get_running_models_with_vram(self, mock_get):
        """Test that get_running_models properly extracts and formats VRAM data"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [{
                'name': 'llama3:latest',
                'size': 7000000000,
                'size_vram': 1200000000,
                'details': {
                    'parameter_size': '7B',
                    'quantization_level': 'Q4_0',
                    'families': ['llama']
                },
                'expires_at': '2026-02-14T12:00:00Z'
            }]
        }
        mock_get.return_value = mock_response
        
        with self.app.app_context():
            models = self.ollama_service.get_running_models()
            self.assertEqual(len(models), 1)
            self.assertIn('memory_split', models[0])
            self.assertEqual(models[0]['memory_split']['cpu_percent'], 83)
            self.assertEqual(models[0]['memory_split']['gpu_percent'], 17)


class TestHistorySessionTracking(unittest.TestCase):
    """Tests for the session-based history system."""

    def setUp(self):
        self.app = create_app()
        # Use a temp file for history to avoid polluting the real one
        self.history_fd, self.history_path = tempfile.mkstemp(suffix='.json')
        with open(self.history_path, 'w') as f:
            json.dump([], f)
        self.app.config['HISTORY_FILE'] = self.history_path
        self.service = OllamaService(self.app)

    def tearDown(self):
        os.close(self.history_fd)
        os.unlink(self.history_path)

    def _make_model(self, name):
        return {
            'name': name,
            'families': 'llama',
            'parameter_size': '7B',
            'size': '7.31 GB',
            'cpu_gpu_split': '7.31 GB (100% GPU)',
        }

    def test_new_model_creates_session(self):
        """When a model appears, a session with ended_at=None is created."""
        self.service.update_history([self._make_model('llama3:latest')])
        history = self.service.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['model_name'], 'llama3:latest')
        self.assertIsNone(history[0]['ended_at'])

    def test_model_disappears_closes_session(self):
        """When a model disappears, its open session is closed."""
        self.service.update_history([self._make_model('llama3:latest')])
        self.service.update_history([])  # model gone
        history = self.service.get_history()
        self.assertEqual(len(history), 1)
        self.assertIsNotNone(history[0]['ended_at'])

    def test_same_models_no_new_entries(self):
        """Identical model set across ticks should not create new entries."""
        self.service.update_history([self._make_model('llama3:latest')])
        self.service.update_history([self._make_model('llama3:latest')])
        self.service.update_history([self._make_model('llama3:latest')])
        history = self.service.get_history()
        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0]['ended_at'])

    def test_multiple_models_simultaneous(self):
        """Multiple models starting simultaneously creates multiple sessions."""
        models = [self._make_model('llama3:latest'), self._make_model('mistral:7b')]
        self.service.update_history(models)
        history = self.service.get_history()
        self.assertEqual(len(history), 2)
        names = {s['model_name'] for s in history}
        self.assertEqual(names, {'llama3:latest', 'mistral:7b'})

    def test_one_model_stops_other_continues(self):
        """When one model stops but another continues, only the stopped one is closed."""
        models = [self._make_model('llama3:latest'), self._make_model('mistral:7b')]
        self.service.update_history(models)
        self.service.update_history([self._make_model('llama3:latest')])
        history = self.service.get_history()
        llama = next(s for s in history if s['model_name'] == 'llama3:latest')
        mistral = next(s for s in history if s['model_name'] == 'mistral:7b')
        self.assertIsNone(llama['ended_at'])
        self.assertIsNotNone(mistral['ended_at'])

    def test_model_restart_creates_new_session(self):
        """A model that stops and starts again gets a new session."""
        self.service.update_history([self._make_model('llama3:latest')])
        self.service.update_history([])  # stop
        self.service.update_history([self._make_model('llama3:latest')])  # restart
        history = self.service.get_history()
        self.assertEqual(len(history), 2)
        # The newer session should be open, the older one closed
        open_sessions = [s for s in history if s['ended_at'] is None]
        closed_sessions = [s for s in history if s['ended_at'] is not None]
        self.assertEqual(len(open_sessions), 1)
        self.assertEqual(len(closed_sessions), 1)

    def test_old_format_detection_and_wipe(self):
        """Old format history (with 'timestamp' and 'models' keys) is wiped on load."""
        old_data = [{'timestamp': '2026-01-01T00:00:00', 'models': [{'name': 'test'}]}]
        with open(self.history_path, 'w') as f:
            json.dump(old_data, f)
        with self.app.app_context():
            history = self.service.load_history()
        self.assertEqual(history, [])

    def test_retention_pruning(self):
        """Sessions older than retention window are pruned on load."""
        old_time = (datetime.now() - timedelta(days=60)).isoformat()
        recent_time = datetime.now().isoformat()
        data = [
            {'model_name': 'old:v1', 'started_at': old_time, 'ended_at': old_time,
             'families': '', 'parameter_size': '', 'size': '', 'cpu_gpu_split': ''},
            {'model_name': 'new:v1', 'started_at': recent_time, 'ended_at': recent_time,
             'families': '', 'parameter_size': '', 'size': '', 'cpu_gpu_split': ''},
        ]
        with open(self.history_path, 'w') as f:
            json.dump(data, f)
        with self.app.app_context():
            history = self.service.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['model_name'], 'new:v1')

    def test_orphan_sessions_closed_on_load(self):
        """Sessions with ended_at=None are closed on load (crash recovery)."""
        now = datetime.now().isoformat()
        data = [
            {'model_name': 'orphan:v1', 'started_at': now, 'ended_at': None,
             'families': '', 'parameter_size': '', 'size': '', 'cpu_gpu_split': ''},
        ]
        with open(self.history_path, 'w') as f:
            json.dump(data, f)
        with self.app.app_context():
            history = self.service.load_history()
        self.assertEqual(len(history), 1)
        self.assertIsNotNone(history[0]['ended_at'])

    def test_format_duration_minutes(self):
        start = '2026-02-13T22:00:00'
        end = '2026-02-13T22:15:00'
        self.assertEqual(format_duration(start, end), '15 minutes')

    def test_format_duration_hours_and_minutes(self):
        start = '2026-02-13T20:00:00'
        end = '2026-02-13T22:30:00'
        self.assertEqual(format_duration(start, end), '2 hours, 30 minutes')

    def test_format_duration_less_than_a_minute(self):
        start = '2026-02-13T22:00:00'
        end = '2026-02-13T22:00:30'
        self.assertEqual(format_duration(start, end), 'less than a minute')

    def test_history_persisted_to_file(self):
        """History changes are written to the JSON file."""
        self.service.update_history([self._make_model('llama3:latest')])
        with open(self.history_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['model_name'], 'llama3:latest')


if __name__ == '__main__':
    unittest.main() 