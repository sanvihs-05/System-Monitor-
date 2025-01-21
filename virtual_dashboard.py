import streamlit as st
import psutil
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
import time
import humanize
from typing import Dict
import os

# Page configuration
st.set_page_config(
    page_title="System Monitor Dashboard",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .stApp {
        background-color: #1E1E1E;
        color: white;
    }
    .metric-card {
        background-color: #2D2D2D;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        margin-bottom: 1rem;
        color: white;
    }
    .warning { color: #ff4b4b; font-weight: bold; }
    .success { color: #00c853; font-weight: bold; }
    .info { color: #1e88e5; font-weight: bold; }
    .st-emotion-cache-1y4p8pa {max-width: 100%;}
    </style>
""", unsafe_allow_html=True)

class SystemMonitorDashboard:
    def __init__(self):
        self.initialize_session_state()
        
    @staticmethod
    def initialize_session_state():
        """Initialize session state variables"""
        if 'history' not in st.session_state:
            st.session_state.history = {
                'timestamps': [],
                'cpu': [],
                'memory': [],
                'disk': [],
                'network_sent': [],
                'network_recv': []
            }
        if 'alert_config' not in st.session_state:
            st.session_state.alert_config = {
                'cpu_threshold': 80.0,
                'memory_threshold': 80.0,
                'disk_threshold': 90.0,
                'enabled': True
            }

    def get_system_metrics(self) -> Dict:
        """Get current system metrics"""
        cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
        virtual_memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()
        
        return {
            'cpu': {
                'cpu_percent': cpu_percent,
                'physical_cores': psutil.cpu_count(logical=False)
            },
            'memory': {
                'virtual': {
                    'total': virtual_memory.total,
                    'available': virtual_memory.available,
                    'percent': virtual_memory.percent
                }
            },
            'disk': {
                'partitions': [{
                    'usage': {
                        'total': disk.total,
                        'used': disk.used,
                        'free': disk.free,
                        'percent': disk.percent
                    }
                }]
            },
            'network': {
                'io_counters': {
                    'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv
                }
            }
        }

    def create_metric_card(self, title: str, value: str, description: str = "",
                         warning_threshold: float = None,
                         current_value: float = None):
        """Create a metric card with consistent styling"""
        status_class = 'warning' if warning_threshold and current_value and current_value > warning_threshold else 'success'
        st.markdown(f"""
            <div class="metric-card">
                <h3>{title}</h3>
                <h2 class="{status_class}">{value}</h2>
                <p>{description}</p>
            </div>
        """, unsafe_allow_html=True)

    def plot_gauge_chart(self, value: float, title: str, threshold: float = 80) -> go.Figure:
        """Create a gauge chart"""
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=value,
            title={'text': title, 'font': {'color': 'white'}},
            gauge={
                'axis': {'range': [None, 100], 'tickfont': {'color': 'white'}},
                'bar': {'color': "#00c853"},
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': threshold
                }
            }
        ))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font={'color': 'white'}
        )
        return fig

    def plot_system_metrics(self):
        """Plot all system metrics"""
        # Fetch current system metrics
        system_info = self.get_system_metrics()

        # Create three columns for main metrics
        col1, col2, col3 = st.columns(3)

        with col1:
            cpu_percent = sum(system_info['cpu']['cpu_percent']) / len(system_info['cpu']['cpu_percent'])
            self.create_metric_card(
                "CPU Usage",
                f"{cpu_percent:.1f}%",
                f"Physical cores: {system_info['cpu']['physical_cores']}",
                warning_threshold=80,
                current_value=cpu_percent
            )
            st.plotly_chart(self.plot_gauge_chart(cpu_percent, "CPU Usage"), use_container_width=True)

        with col2:
            memory_percent = system_info['memory']['virtual']['percent']
            self.create_metric_card(
                "Memory Usage",
                f"{memory_percent:.1f}%",
                f"Total: {humanize.naturalsize(system_info['memory']['virtual']['total'])}",
                warning_threshold=80,
                current_value=memory_percent
            )
            st.plotly_chart(self.plot_gauge_chart(memory_percent, "Memory Usage"), use_container_width=True)

        with col3:
            disk_percent = system_info['disk']['partitions'][0]['usage']['percent']
            self.create_metric_card(
                "Disk Usage",
                f"{disk_percent:.1f}%",
                f"Total: {humanize.naturalsize(system_info['disk']['partitions'][0]['usage']['total'])}",
                warning_threshold=90,
                current_value=disk_percent
            )
            st.plotly_chart(self.plot_gauge_chart(disk_percent, "Disk Usage", 90), use_container_width=True)

        # Update history
        current_time = datetime.now()
        st.session_state.history['timestamps'].append(current_time)
        st.session_state.history['cpu'].append(cpu_percent)
        st.session_state.history['memory'].append(memory_percent)
        st.session_state.history['disk'].append(disk_percent)
        st.session_state.history['network_sent'].append(system_info['network']['io_counters']['bytes_sent'])
        st.session_state.history['network_recv'].append(system_info['network']['io_counters']['bytes_recv'])

        # Keep last hour of data
        cutoff_time = current_time - timedelta(hours=1)
        while (st.session_state.history['timestamps'] and 
               st.session_state.history['timestamps'][0] < cutoff_time):
            for key in st.session_state.history:
                st.session_state.history[key].pop(0)

        # Plot historical trends
        self.plot_historical_trends()

    def plot_historical_trends(self):
        """Plot historical trends of system metrics"""
        st.subheader("System Resource Trends")
        
        df = pd.DataFrame({
            'timestamp': st.session_state.history['timestamps'],
            'CPU Usage (%)': st.session_state.history['cpu'],
            'Memory Usage (%)': st.session_state.history['memory'],
            'Disk Usage (%)': st.session_state.history['disk']
        })
        
        # Create line chart for CPU, Memory, and Disk usage
        fig = px.line(df.melt(id_vars=['timestamp'], 
                            var_name='Metric', 
                            value_name='Usage (%)'),
                     x='timestamp', 
                     y='Usage (%)',
                     color='Metric',
                     title='System Resource Usage Over Time')
        
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Network traffic
        network_df = pd.DataFrame({
            'timestamp': st.session_state.history['timestamps'],
            'Sent': [x/1024/1024 for x in st.session_state.history['network_sent']],  # Convert to MB
            'Received': [x/1024/1024 for x in st.session_state.history['network_recv']]  # Convert to MB
        })
        
        fig_network = px.line(network_df.melt(id_vars=['timestamp'], 
                                            var_name='Direction', 
                                            value_name='Traffic (MB)'),
                            x='timestamp', 
                            y='Traffic (MB)',
                            color='Direction',
                            title='Network Traffic Over Time')
        
        fig_network.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            height=400
        )
        st.plotly_chart(fig_network, use_container_width=True)

    def show_process_table(self):
        """Display process information in a sortable table"""
        st.subheader("Running Processes")
        
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                pinfo = proc.info
                processes.append({
                    'pid': pinfo['pid'],
                    'name': pinfo['name'],
                    'cpu_percent': pinfo['cpu_percent'],
                    'memory_percent': pinfo['memory_percent']
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        df_processes = pd.DataFrame(processes)
        df_processes = df_processes.sort_values('memory_percent', ascending=False)
        
        st.dataframe(
            df_processes,
            use_container_width=True,
            hide_index=True
        )

    def configure_alerts(self):
        """Configure system alerts"""
        st.sidebar.subheader("Alert Configuration")
        
        st.session_state.alert_config['enabled'] = st.sidebar.checkbox(
            "Enable Alerts",
            value=st.session_state.alert_config['enabled']
        )
        
        if st.session_state.alert_config['enabled']:
            st.session_state.alert_config['cpu_threshold'] = st.sidebar.slider(
                "CPU Alert Threshold (%)",
                0, 100,
                value=int(st.session_state.alert_config['cpu_threshold'])
            )
            st.session_state.alert_config['memory_threshold'] = st.sidebar.slider(
                "Memory Alert Threshold (%)",
                0, 100,
                value=int(st.session_state.alert_config['memory_threshold'])
            )
            st.session_state.alert_config['disk_threshold'] = st.sidebar.slider(
                "Disk Alert Threshold (%)",
                0, 100,
                value=int(st.session_state.alert_config['disk_threshold'])
            )
    def show_large_files(self):
        """Display large files analysis"""
        st.subheader("Large Files Analysis")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            min_size = st.slider("Minimum file size (MB)", 100, 1000, 100)
            
        with col2:
            st.write("")  # Empty space for alignment
            scan_button = st.button("Scan for Large Files")
        
        if scan_button:
            with st.spinner("Scanning for large files..."):
                try:
                    # Get list of files
                    files_data = []
                    root_path = "C:\\" if os.name == 'nt' else "/"
                    
                    for dirpath, _, filenames in os.walk(root_path):
                        for f in filenames:
                            try:
                                file_path = os.path.join(dirpath, f)
                                size = os.path.getsize(file_path)
                                
                                if size > min_size * 1024 * 1024:  # Convert MB to bytes
                                    files_data.append({
                                        'path': file_path,
                                        'size': size / (1024 * 1024),  # Convert to MB
                                        'last_modified': datetime.fromtimestamp(
                                            os.path.getmtime(file_path)
                                        ).strftime('%Y-%m-%d %H:%M:%S')
                                    })
                            except (PermissionError, FileNotFoundError):
                                continue
                            
                            if len(files_data) >= 1000:  # Limit to 1000 files
                                break
                    
                    if files_data:
                        # Convert to DataFrame
                        df = pd.DataFrame(files_data)
                        df = df.sort_values('size', ascending=False)
                        
                        # Create treemap visualization
                        fig = px.treemap(
                            df,
                            path=[px.Constant("all"), df['path'].apply(lambda x: os.path.dirname(x)), 
                                 df['path'].apply(lambda x: os.path.basename(x))],
                            values='size',
                            title='Large Files Distribution',
                            custom_data=['path', 'size', 'last_modified']
                        )
                        
                        fig.update_traces(
                            hovertemplate="<br>".join([
                                "Path: %{customdata[0]}",
                                "Size: %{customdata[1]:.2f} MB",
                                "Modified: %{customdata[2]}",
                            ])
                        )
                        
                        fig.update_layout(
                            template='plotly_dark',
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                        
                        # Display detailed table
                        st.subheader("Detailed File List")
                        
                        # Format size to include 'MB' and sort by size
                        df['size'] = df['size'].apply(lambda x: f"{x:.2f} MB")
                        
                        st.dataframe(
                            df,
                            column_config={
                                "path": "File Path",
                                "size": "Size",
                                "last_modified": "Last Modified"
                            },
                            hide_index=True,
                            use_container_width=True
                        )
                        
                        # Add cleanup options
                        if st.checkbox("Show File Management Options"):
                            selected_file = st.selectbox(
                                "Select file to delete:",
                                options=files_data,
                                format_func=lambda x: f"{x['path']} ({x['size']:.2f} MB)"
                            )
                            
                            if selected_file:
                                if st.button("Delete Selected File", type="secondary"):
                                    try:
                                        os.remove(selected_file['path'])
                                        st.success(f"Successfully deleted: {selected_file['path']}")
                                        time.sleep(2)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error deleting file: {str(e)}")
                    else:
                        st.info(f"No files larger than {min_size} MB found.")
                
                except Exception as e:
                    st.error(f"Error scanning files: {str(e)}")
    def show_memory_leak_analysis(self):
        st.subheader("Memory Leak Detection")
        col1, col2 = st.columns([3, 1])
        with col2:
            analyze_button = st.button("Analyze Memory Leaks")
            threshold_mb = st.number_input(
            "Memory Threshold (MB)",
            min_value=50,
            max_value=1000,
            value=100
        )
        with col1:
            if analyze_button:
                with st.spinner("Analyzing memory usage patterns..."):
                    suspicious_processes = []
                
                # Analyze each process's memory history
                for pid in st.session_state.history.get('process_memory', {}):
                    # Get last 5 memory measurements
                    memory_trend = st.session_state.history['process_memory'][pid][-5:]
                    
                    # Check if we have enough data points
                    if len(memory_trend) >= 5:
                        # Check if memory usage is consistently increasing
                        if all(b > a for a, b in zip(memory_trend, memory_trend[1:])):
                            try:
                                # Get current process information
                                process = psutil.Process(pid)
                                memory_mb = process.memory_info().rss / (1024 * 1024)
                                
                                # Check if memory usage exceeds threshold
                                if memory_mb > threshold_mb:
                                    suspicious_processes.append({
                                        'pid': pid,
                                        'name': process.name(),
                                        'memory_mb': memory_mb,
                                        'trend': memory_trend
                                    })
                            except psutil.NoSuchProcess:
                                continue
                
                # Display results
                if suspicious_processes:
                    # Create DataFrame for suspicious processes
                    df = pd.DataFrame(suspicious_processes)
                    
                    # Create memory trend visualization
                    fig = go.Figure()
                    for proc in suspicious_processes:
                        fig.add_trace(
                            go.Scatter(
                                y=proc['trend'],
                                name=f"{proc['name']} (PID: {proc['pid']})",
                                mode='lines+markers'
                            )
                        )
                    
                    # Configure plot layout
                    fig.update_layout(
                        title='Memory Usage Trends for Suspicious Processes',
                        xaxis_title='Time Points',
                        yaxis_title='Memory Usage (%)',
                        template='plotly_dark',
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                    )
                    
                    # Display the plot
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Display detailed process information
                    st.dataframe(
                        df,
                        column_config={
                            "pid": "Process ID",
                            "name": "Process Name",
                            "memory_mb": st.column_config.NumberColumn(
                                "Memory Usage (MB)",
                                format="%.2f"
                            )
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    # Display warnings for concerning processes
                    for proc in suspicious_processes:
                        if proc['memory_mb'] > threshold_mb * 2:
                            st.warning(
                                f"⚠️ Process {proc['name']} (PID: {proc['pid']}) "
                                f"shows significant memory growth!"
                            )
                else:
                    st.success("No memory leaks detected above the specified threshold.")

    def run(self):
        """Main method to run the dashboard"""
        st.title("🖥️ System Monitor Dashboard")
        
        # Sidebar configuration
        st.sidebar.title("Dashboard Settings")
        refresh_rate = st.sidebar.slider("Refresh rate (seconds)", 1, 60, 5)
        display_mode = st.sidebar.radio("Display Mode", ["Basic", "Advanced"])
        
        # Configure alerts
        self.configure_alerts()
        
        # Main content
        self.plot_system_metrics()
        
        if display_mode == "Advanced":
            # Show process table
            self.show_process_table()
            self.show_memory_leak_analysis() 
        self.show_large_files()
        
        
        # Auto-refresh
        time.sleep(refresh_rate)
        st.rerun()

if __name__ == "__main__":
    dashboard = SystemMonitorDashboard()
    dashboard.run()