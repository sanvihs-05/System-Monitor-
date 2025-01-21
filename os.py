from flask import Flask, jsonify, request
import psutil
import os
from datetime import datetime, timedelta
import logging
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import platform
from pathlib import Path
import threading
import time
import gc
import tracemalloc
from collections import defaultdict
import json
import socket
import numpy as np
from typing import Dict, List

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('system_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per minute"]
)

# Global variables for monitoring
memory_history: List[Dict] = []
process_history = defaultdict(list)
cpu_history: List[Dict] = []
disk_io_history: List[Dict] = []
network_history: List[Dict] = []

# Start tracemalloc for memory leak detection
tracemalloc.start(25)  # Keep 25 frames
snapshot1 = tracemalloc.take_snapshot()

class SystemMonitor:
    @staticmethod
    def get_size_format(bytes_value: int) -> str:
        """Convert bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0

    @staticmethod
    def get_process_details(pid: int) -> Dict:
        """Get detailed information about a specific process"""
        try:
            process = psutil.Process(pid)
            return {
                'pid': pid,
                'name': process.name(),
                'status': process.status(),
                'cpu_percent': process.cpu_percent(),
                'memory_percent': process.memory_percent(),
                'memory_usage': SystemMonitor.get_size_format(process.memory_info().rss),
                'create_time': datetime.fromtimestamp(process.create_time()).isoformat(),
                'username': process.username(),
                'cmdline': ' '.join(process.cmdline()),
                'num_threads': process.num_threads(),
                'open_files': len(process.open_files()),
                'connections': len(process.connections())
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    @staticmethod
    def analyze_memory_leak(threshold_mb: float = 100.0) -> List[Dict]:
        """Analyze potential memory leaks in processes"""
        suspicious_processes = []
        for pid in process_history:
            if len(process_history[pid]) >= 5:  # Need at least 5 data points
                memory_trend = [x['memory_percent'] for x in process_history[pid][-5:]]
                if all(b > a for a, b in zip(memory_trend, memory_trend[1:])):
                    try:
                        process = psutil.Process(pid)
                        memory_mb = process.memory_info().rss / (1024 * 1024)
                        if memory_mb > threshold_mb:
                            suspicious_processes.append({
                                'pid': pid,
                                'name': process.name(),
                                'memory_mb': memory_mb,
                                'trend': memory_trend
                            })
                    except psutil.NoSuchProcess:
                        continue
        return suspicious_processes

def background_monitor():
    """Background task to monitor system metrics"""
    while True:
        try:
            current_time = datetime.now()
            
            # Memory monitoring
            memory = psutil.virtual_memory()
            memory_history.append({
                'timestamp': current_time.isoformat(),
                'percent': memory.percent,
                'used': memory.used,
                'available': memory.available
            })
            
            # CPU monitoring
            cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
            cpu_history.append({
                'timestamp': current_time.isoformat(),
                'percent': cpu_percent,
                'avg': sum(cpu_percent) / len(cpu_percent)
            })
            
            # Disk I/O monitoring
            disk_io = psutil.disk_io_counters()
            disk_io_history.append({
                'timestamp': current_time.isoformat(),
                'read_bytes': disk_io.read_bytes,
                'write_bytes': disk_io.write_bytes
            })
            
            # Network monitoring
            network = psutil.net_io_counters()
            network_history.append({
                'timestamp': current_time.isoformat(),
                'bytes_sent': network.bytes_sent,
                'bytes_recv': network.bytes_recv
            })
            
            # Process monitoring
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    process_history[proc.info['pid']].append({
                        'timestamp': current_time.isoformat(),
                        'memory_percent': proc.info['memory_percent']
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Cleanup old data (keep last 24 hours)
            cutoff_time = current_time - timedelta(hours=24)
            memory_history[:] = [x for x in memory_history if datetime.fromisoformat(x['timestamp']) > cutoff_time]
            cpu_history[:] = [x for x in cpu_history if datetime.fromisoformat(x['timestamp']) > cutoff_time]
            disk_io_history[:] = [x for x in disk_io_history if datetime.fromisoformat(x['timestamp']) > cutoff_time]
            network_history[:] = [x for x in network_history if datetime.fromisoformat(x['timestamp']) > cutoff_time]
            
            # Clean up process history (keep last hour)
            process_cutoff = current_time - timedelta(hours=1)
            for pid in list(process_history.keys()):
                process_history[pid] = [x for x in process_history[pid] 
                                      if datetime.fromisoformat(x['timestamp']) > process_cutoff]
                if not process_history[pid]:
                    del process_history[pid]
                    
            time.sleep(60)  # Update every minute
            
        except Exception as e:
            logger.error(f"Error in background monitor: {str(e)}")
            time.sleep(60)  # Wait before retrying

# Start background monitoring
monitoring_thread = threading.Thread(target=background_monitor, daemon=True)
monitoring_thread.start()

@app.route('/api/memory/leaks', methods=['GET'])
def detect_memory_leaks():
    """Detect potential memory leaks"""
    global snapshot1
    snapshot2 = tracemalloc.take_snapshot()
    
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    suspicious_processes = SystemMonitor.analyze_memory_leak()
    
    # Update baseline snapshot
    snapshot1 = snapshot2
    
    return jsonify({
        'status': 'success',
        'data': {
            'memory_leaks': [str(stat) for stat in top_stats[:10]],
            'suspicious_processes': suspicious_processes,
            'memory_trend': memory_history[-10:]
        }
    })

@app.route('/api/system/overview', methods=['GET'])
def get_system_overview():
    """Get comprehensive system overview"""
    try:
        cpu_freq = psutil.cpu_freq()
        cpu_stats = psutil.cpu_stats()
        
        return jsonify({
            'status': 'success',
            'data': {
                'cpu': {
                    'physical_cores': psutil.cpu_count(logical=False),
                    'total_cores': psutil.cpu_count(logical=True),
                    'max_frequency': f"{cpu_freq.max:.2f}MHz" if cpu_freq else "N/A",
                    'current_frequency': f"{cpu_freq.current:.2f}MHz" if cpu_freq else "N/A",
                    'cpu_percent': psutil.cpu_percent(interval=1, percpu=True),
                    'ctx_switches': cpu_stats.ctx_switches,
                    'interrupts': cpu_stats.interrupts,
                },
                'memory': {
                    'virtual': {k: getattr(psutil.virtual_memory(), k) 
                              for k in ['total', 'available', 'percent', 'used', 'free']},
                    'swap': {k: getattr(psutil.swap_memory(), k) 
                            for k in ['total', 'used', 'free', 'percent']}
                },
                'disk': {
                    'partitions': [{
                        'device': p.device,
                        'mountpoint': p.mountpoint,
                        'fstype': p.fstype,
                        'usage': {k: getattr(psutil.disk_usage(p.mountpoint), k) 
                                for k in ['total', 'used', 'free', 'percent']}
                    } for p in psutil.disk_partitions(all=False)],
                    'io_counters': {k: getattr(psutil.disk_io_counters(), k) 
                                  for k in ['read_bytes', 'write_bytes', 'read_count', 'write_count']}
                },
                'network': {
                    'interfaces': [{'name': name, 'addresses': addresses} 
                                 for name, addresses in psutil.net_if_addrs().items()],
                    'io_counters': {k: getattr(psutil.net_io_counters(), k) 
                                  for k in ['bytes_sent', 'bytes_recv', 'packets_sent', 'packets_recv']}
                },
                'boot_time': datetime.fromtimestamp(psutil.boot_time()).isoformat()
            }
        })
    except Exception as e:
        logger.error(f"Error getting system overview: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/processes', methods=['GET'])
def get_processes():
    """Get detailed process information"""
    try:
        sort_by = request.args.get('sort', 'memory_percent')
        limit = int(request.args.get('limit', 50))
        
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
            try:
                pinfo = SystemMonitor.get_process_details(proc.pid)
                if pinfo:
                    processes.append(pinfo)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        processes.sort(key=lambda x: x.get(sort_by, 0), reverse=True)
        
        return jsonify({
            'status': 'success',
            'data': processes[:limit]
        })
    except Exception as e:
        logger.error(f"Error getting process information: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/process/<int:pid>', methods=['GET'])
def get_process_info(pid):
    """Get detailed information about a specific process"""
    try:
        process_info = SystemMonitor.get_process_details(pid)
        if process_info:
            return jsonify({
                'status': 'success',
                'data': process_info
            })
        return jsonify({'status': 'error', 'message': 'Process not found'}), 404
    except Exception as e:
        logger.error(f"Error getting process info: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/files/large/<int:min_size_mb>', methods=['GET'])
@limiter.limit("10 per minute")
def get_large_files(min_size_mb):
    """Get list of large files"""
    try:
        large_files = []
        start_path = str(Path.home()) if platform.system() != "Windows" else "C:\\"
        
        for dirpath, dirnames, filenames in os.walk(start_path):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            
            for f in filenames:
                if f.startswith('.'):
                    continue
                    
                fp = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(fp)
                    if size > min_size_mb * 1024 * 1024:
                        large_files.append({
                            'path': fp,
                            'size': SystemMonitor.get_size_format(size),
                            'size_bytes': size,
                            'last_modified': datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()
                        })
                except (PermissionError, FileNotFoundError, OSError):
                    continue
                
                if len(large_files) >= 1000:
                    break
                    
        return jsonify({
            'status': 'success',
            'data': sorted(large_files, key=lambda x: x['size_bytes'], reverse=True)
        })
    except Exception as e:
        logger.error(f"Error scanning for large files: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/files/delete/<path:file_path>', methods=['DELETE'])
def delete_file(file_path):
    """Delete specified file"""
    try:
        os.remove(file_path)
        logger.info(f"Successfully deleted file: {file_path}")
        return jsonify({
            'status': 'success',
            'message': f'Successfully deleted: {file_path}'
        })
    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/history', methods=['GET'])

def get_history():
    """Get historical system metrics"""
    try:
        hours = int(request.args.get('hours', 24))
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        return jsonify({
            'status': 'success',
            'data': {
                'memory': [x for x in memory_history 
                          if datetime.fromisoformat(x['timestamp']) > cutoff_time],
                'cpu': [x for x in cpu_history 
                       if datetime.fromisoformat(x['timestamp']) > cutoff_time],
                'disk_io': [x for x in disk_io_history 
                           if datetime.fronisoformat(x['timestamp']) > cutoff_time],
                'network': [x for x in network_history 
                           if datetime.fronisoformat(x['timestamp']) > cutoff_time]
            }
        })
    except Exception as e:
        logger.error(f"Error getting history: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/alerts/configure', methods=['POST'])
def configure_alerts():
    """Configure system resource alerts"""
    try:
        config = request.get_json()
        
        # Validate configuration
        required_fields = ['cpu_threshold', 'memory_threshold', 'disk_threshold']
        if not all(field in config for field in required_fields):
            return jsonify({
                'status': 'error',
                'message': f'Missing required fields. Required: {required_fields}'
            }), 400
            
        # Store configuration in app config
        app.config['ALERTS'] = {
            'cpu_threshold': float(config['cpu_threshold']),
            'memory_threshold': float(config['memory_threshold']),
            'disk_threshold': float(config['disk_threshold']),
            'enabled': config.get('enabled', True)
        }
        
        return jsonify({
            'status': 'success',
            'message': 'Alert configuration updated',
            'data': app.config['ALERTS']
        })
    except Exception as e:
        logger.error(f"Error configuring alerts: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/temperature', methods=['GET'])
def get_temperature():
    """Get system temperature information if available"""
    try:
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
        
        # Format temperature data
        temp_data = {}
        for hardware, entries in temps.items():
            temp_data[hardware] = [{
                'label': entry.label or f'Sensor {i}',
                'current': entry.current,
                'high': entry.high,
                'critical': entry.critical
            } for i, entry in enumerate(entries)]
        
        return jsonify({
            'status': 'success',
            'data': temp_data
        })
    except Exception as e:
        logger.error(f"Error getting temperature info: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/battery', methods=['GET'])
def get_battery_info():
    """Get battery information if available"""
    try:
        battery = psutil.sensors_battery()
        if battery:
            return jsonify({
                'status': 'success',
                'data': {
                    'percent': battery.percent,
                    'power_plugged': battery.power_plugged,
                    'remaining_time': battery.secsleft if battery.secsleft != -1 else None
                }
            })
        return jsonify({
            'status': 'success',
            'data': None,
            'message': 'No battery information available'
        })
    except Exception as e:
        logger.error(f"Error getting battery info: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/users', methods=['GET'])
def get_users():
    """Get information about logged-in users"""
    try:
        users = []
        for user in psutil.users():
            users.append({
                'name': user.name,
                'terminal': user.terminal,
                'host': user.host,
                'started': datetime.fromtimestamp(user.started).isoformat(),
                'pid': user.pid if hasattr(user, 'pid') else None
            })
        
        return jsonify({
            'status': 'success',
            'data': users
        })
    except Exception as e:
        logger.error(f"Error getting user info: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/network/connections', methods=['GET'])
def get_network_connections():
    """Get detailed network connection information"""
    try:
        connections = []
        for conn in psutil.net_connections(kind='inet'):
            try:
                process = psutil.Process(conn.pid) if conn.pid else None
                connections.append({
                    'fd': conn.fd,
                    'family': conn.family,
                    'type': conn.type,
                    'local_addr': f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else None,
                    'remote_addr': f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else None,
                    'status': conn.status,
                    'pid': conn.pid,
                    'process_name': process.name() if process else None
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        return jsonify({
            'status': 'success',
            'data': connections
        })
    except Exception as e:
        logger.error(f"Error getting network connections: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/services', methods=['GET'])
def get_services():
    """Get system services/daemons information (Windows only)"""
    try:
        if platform.system() != 'Windows':
            return jsonify({
                'status': 'error',
                'message': 'This endpoint is only available on Windows systems'
            }), 400
            
        services = []
        for service in psutil.win_service_iter():
            try:
                service_info = service.as_dict()
                services.append({
                    'name': service_info['name'],
                    'display_name': service_info['display_name'],
                    'status': service_info['status'],
                    'start_type': service_info['start_type'],
                    'username': service_info['username']
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        return jsonify({
            'status': 'success',
            'data': services
        })
    except Exception as e:
        logger.error(f"Error getting services info: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """API health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'uptime': time.time() - psutil.boot_time()
    })

@app.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    return jsonify({
        'status': 'error',
        'message': 'Rate limit exceeded',
        'retry_after': e.description
    }), 429

@app.errorhandler(500)
def internal_error(e):
    """Handle internal server errors"""
    logger.error(f"Internal server error: {str(e)}")
    return jsonify({
        'status': 'error',
        'message': 'Internal server error',
        'error_id': str(time.time())
    }), 500

if __name__ == '__main__':
    # Configure initial alert thresholds
    app.config['ALERTS'] = {
        'cpu_threshold': 80.0,
        'memory_threshold': 80.0,
        'disk_threshold': 90.0,
        'enabled': True
    }
    
    # Start the Flask application
    app.run(host='0.0.0.0', port=5000, threaded=True)