import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from app.services.ollama import OllamaService

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

    @patch('app.routes.requests.get')
    def test_index_route_no_models(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []
        
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

if __name__ == '__main__':
    unittest.main() 