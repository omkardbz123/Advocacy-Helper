document.addEventListener('DOMContentLoaded', () => {
    // 1. Initial State Check
    checkScraperStatus();
    
    // 2. Setup WebSocket connections
    const socket = io();

    const logContainer = document.getElementById('log-container');
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const platformSelect = document.getElementById('platform-select');
    const graderSelect = document.getElementById('grader-select');
    const statusIndicator = document.getElementById('status-indicator');
    const queryIndicator = document.getElementById('query-indicator');

    socket.on('connection_response', (data) => {
        console.log('WS Connection Response:', data);
    });

    // Handle incoming logs
    socket.on('scraper_log', (data) => {
        // Remove placeholder if present
        const placeholder = logContainer.querySelector('.log-placeholder');
        if (placeholder) {
            logContainer.innerHTML = '';
        }

        const logRow = document.createElement('div');
        logRow.className = `log-row ${data.level || 'info'}`;
        
        // Format timestamp
        const date = new Date(data.timestamp);
        const timeStr = date.toTimeString().split(' ')[0];
        
        logRow.innerText = `[${timeStr}] [${data.action.toUpperCase()}] ${data.detail}`;
        logContainer.insertBefore(logRow, logContainer.firstChild);
    });

    let activePlatform = 'youtube';

    // Handle status updates
    socket.on('scraper_status', (data) => {
        if (data.running) {
            activePlatform = data.platform;
        }
        updateUIStatus(data.running, data.platform, data.current_query);
    });

    // Start button handler
    if (startBtn) {
        startBtn.addEventListener('click', () => {
            const platform = platformSelect.value;
            const geminiMode = graderSelect.value;
            activePlatform = platform;

            // Disable controls while request processes
            startBtn.disabled = true;

            fetch('/api/start-scraper', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ platform, gemini_mode: geminiMode })
            })
            .then(res => res.json())
            .then(data => {
                startBtn.disabled = false;
                if (data.error) {
                    alert(data.error);
                } else {
                    updateUIStatus(true, platform, 'Starting...');
                }
            })
            .catch(err => {
                startBtn.disabled = false;
                console.error('Error starting scraper:', err);
            });
        });
    }

    // Stop button handler
    if (stopBtn) {
        stopBtn.addEventListener('click', () => {
            const platform = activePlatform;

            stopBtn.disabled = true;

            fetch('/api/stop-scraper', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ platform })
            })
            .then(res => res.json())
            .then(data => {
                stopBtn.disabled = false;
                if (data.error) {
                    alert(data.error);
                } else {
                    updateUIStatus(false, platform, 'Stopping...');
                }
            })
            .catch(err => {
                stopBtn.disabled = false;
                console.error('Error stopping scraper:', err);
            });
        });
    }

    function checkScraperStatus() {
        fetch('/api/scraper-status')
            .then(res => res.json())
            .then(data => {
                // If either is running, show running UI for that platform
                if (data.youtube.running) {
                    activePlatform = 'youtube';
                    updateUIStatus(true, 'youtube', 'Running...');
                } else if (data.instagram.running) {
                    activePlatform = 'instagram';
                    updateUIStatus(true, 'instagram', 'Running...');
                } else {
                    updateUIStatus(false);
                }
            })
            .catch(err => console.error('Error checking scraper status:', err));
    }

    function updateUIStatus(running, platform = 'youtube', currentQuery = '') {
        if (running) {
            statusIndicator.innerText = `Running (${platform.toUpperCase()})`;
            statusIndicator.className = 'status-val running';
            
            if (currentQuery) {
                queryIndicator.innerText = `Target: ${currentQuery}`;
                queryIndicator.style.display = 'inline-block';
            } else {
                queryIndicator.style.display = 'none';
            }

            if (startBtn) startBtn.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'inline-block';
            if (platformSelect) {
                platformSelect.value = platform;
                platformSelect.disabled = true;
            }
            if (graderSelect) graderSelect.disabled = true;
        } else {
            statusIndicator.innerText = 'Stopped';
            statusIndicator.className = 'status-val stopped';
            queryIndicator.style.display = 'none';

            if (startBtn) startBtn.style.display = 'inline-block';
            if (stopBtn) stopBtn.style.display = 'none';
            if (platformSelect) platformSelect.disabled = false;
            if (graderSelect) graderSelect.disabled = false;
        }
    }
});
