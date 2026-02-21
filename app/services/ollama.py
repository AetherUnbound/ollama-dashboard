from flask import current_app
import requests
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateutil_parser
import time
import json
import os
from app.services.format_utils import format_size, format_relative_time, format_duration

class OllamaService:
    def __init__(self, app=None):
        self.app = app
        self._previous_model_names = set()
        if app is not None:
            self.init_app(app)
        else:
            self.history = []

    def init_app(self, app):
        """Initialize the service with the Flask app"""
        self.app = app
        with self.app.app_context():
            self.history = self.load_history()
            # Seed _previous_model_names from any currently-open sessions
            self._previous_model_names = {
                s['model_name'] for s in self.history if s.get('ended_at') is None
            }

    def get_api_url(self):
        try:
            host = self.app.config.get('OLLAMA_HOST')
            port = self.app.config.get('OLLAMA_PORT')
            if not host or not port:
                raise ValueError(f"Missing configuration: OLLAMA_HOST={host}, OLLAMA_PORT={port}")
            return f"http://{host}:{port}/api/ps"
        except Exception as e:
            raise Exception(f"Failed to connect to Ollama server: {str(e)}. Please ensure Ollama is running and accessible.")

    def format_size(self, size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

    def calculate_memory_split(self, total_size, vram_size):
        """Calculate CPU/GPU memory split with formatted sizes and percentages"""
        if total_size == 0:
            return {
                'cpu_size': '0 B',
                'cpu_percent': 0,
                'gpu_size': '0 B',
                'gpu_percent': 0,
                'display': 'N/A'
            }
        
        # Handle edge cases
        vram_size = vram_size or 0
        if vram_size > total_size:
            vram_size = total_size
        
        cpu_bytes = total_size - vram_size
        gpu_bytes = vram_size
        
        cpu_percent = round((cpu_bytes / total_size) * 100)
        gpu_percent = round((gpu_bytes / total_size) * 100)
        
        cpu_size_formatted = format_size(cpu_bytes)
        gpu_size_formatted = format_size(gpu_bytes)
        
        # Build display string - only show non-zero components
        if cpu_percent == 0:
            display = f"{gpu_size_formatted} (100% GPU)"
        elif gpu_percent == 0:
            display = f"{cpu_size_formatted} (100% CPU)"
        else:
            display = f"{cpu_size_formatted} ({cpu_percent}%) / {gpu_size_formatted} ({gpu_percent}%)"
        
        return {
            'cpu_size': cpu_size_formatted,
            'cpu_percent': cpu_percent,
            'gpu_size': gpu_size_formatted,
            'gpu_percent': gpu_percent,
            'display': display
        }

    def format_relative_time(self, target_dt):
        now = datetime.now(timezone.utc)
        diff = target_dt - now
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        if days > 0:
            if hours > 12:
                days += 1
            return f"about {days} {'day' if days == 1 else 'days'}"
        elif hours > 0:
            if minutes > 30:
                hours += 1
            return f"about {hours} {'hour' if hours == 1 else 'hours'}"
        elif minutes > 0:
            if minutes < 5:
                return "a few minutes"
            elif minutes < 15:
                return "about 10 minutes"
            elif minutes < 25:
                return "about 20 minutes"
            elif minutes < 45:
                return "about 30 minutes"
            else:
                return "about an hour"
        else:
            return "less than a minute"

    def get_running_models(self):
        try:
            response = requests.get(self.get_api_url(), timeout=5)
            response.raise_for_status()
            data = response.json()
            models = data.get('models', [])
            
            current_models = []
            for model in models:
                # Format size
                model['formatted_size'] = format_size(model['size'])
                
                # Calculate CPU/GPU memory split
                size_vram = model.get('size_vram', 0)
                memory_split = self.calculate_memory_split(model['size'], size_vram)
                model['memory_split'] = memory_split
                
                # Format families
                families = model.get('details', {}).get('families', [])
                if families:
                    model['families_str'] = ', '.join(families)
                else:
                    model['families_str'] = model.get('details', {}).get('family', 'Unknown')
                
                # Format expiration times
                if model.get('expires_at'):
                    if model['expires_at'] == 'Stopping':
                        model['expires_at'] = {
                            'local': 'Stopping...',
                            'relative': 'Process is stopping'
                        }
                    else:
                        try:
                            expires_dt = dateutil_parser.isoparse(model['expires_at'])
                            local_dt = expires_dt.astimezone()
                            relative_time = format_relative_time(expires_dt)
                            tz_abbr = time.strftime('%Z')
                            model['expires_at'] = {
                                'local': local_dt.strftime(f'%-I:%M %p, %b %-d ({tz_abbr})'),
                                'relative': relative_time
                            }
                        except Exception as e:
                            model['expires_at'] = {
                                'local': 'Invalid date',
                                'relative': 'Unknown'
                            }
                
                current_models.append({
                    'name': model['name'],
                    'families': model.get('families_str', ''),
                    'parameter_size': model.get('details', {}).get('parameter_size', ''),
                    'size': model.get('formatted_size', ''),
                    'cpu_gpu_split': memory_split['display']
                })
            
            if current_models:
                self.update_history(current_models)
            else:
                self.update_history([])
            
            return models
        except requests.exceptions.ConnectionError:
            raise Exception("Could not connect to Ollama server. Please ensure it's running and accessible.")
        except requests.exceptions.Timeout:
            raise Exception("Connection to Ollama server timed out. Please check your network connection.")
        except Exception as e:
            raise Exception(f"Error fetching models: {str(e)}")

    def load_history(self):
        try:
            history_file = self.app.config['HISTORY_FILE']
            retention_days = self.app.config.get('HISTORY_RETENTION_DAYS', 30)

            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    history = json.load(f)

                # Detect old format (list of dicts with 'timestamp' + 'models' keys)
                if history and isinstance(history, list) and 'timestamp' in history[0] and 'models' in history[0]:
                    history = []

                # Prune entries older than retention window
                cutoff = datetime.now() - timedelta(days=retention_days)
                cutoff_iso = cutoff.isoformat()
                history = [s for s in history if s.get('started_at', '') >= cutoff_iso]

                # Close orphan sessions (ended_at is None) — we don't know real end time
                for session in history:
                    if session.get('ended_at') is None:
                        session['ended_at'] = session['started_at']

                return history
            else:
                with open(history_file, 'w') as f:
                    json.dump([], f)
                return []
        except Exception as e:
            print(f"Error handling history file: {str(e)}")
            return []

    def update_history(self, models):
        current_names = {m['name'] for m in models}
        changed = False
        now = datetime.now().isoformat()

        # Build lookup for current model data
        model_data = {}
        for m in models:
            model_data[m['name']] = m

        # New models → create sessions
        new_names = current_names - self._previous_model_names
        for name in new_names:
            m = model_data[name]
            self.history.insert(0, {
                'model_name': name,
                'started_at': now,
                'ended_at': None,
                'families': m.get('families', ''),
                'parameter_size': m.get('parameter_size', ''),
                'size': m.get('size', ''),
                'cpu_gpu_split': m.get('cpu_gpu_split', ''),
            })
            changed = True

        # Removed models → close sessions
        removed_names = self._previous_model_names - current_names
        for name in removed_names:
            for session in self.history:
                if session['model_name'] == name and session['ended_at'] is None:
                    session['ended_at'] = now
                    changed = True
                    break

        self._previous_model_names = current_names
        if changed:
            self.save_history()

    def save_history(self):
        with open(self.app.config['HISTORY_FILE'], 'w') as f:
            json.dump(self.history, f)

    def get_history(self):
        """Return the history sorted newest-first by started_at, with duration computed."""
        sessions = sorted(self.history, key=lambda s: s.get('started_at', ''), reverse=True)
        for session in sessions:
            session['duration'] = format_duration(session['started_at'], session.get('ended_at'))
        return sessions 