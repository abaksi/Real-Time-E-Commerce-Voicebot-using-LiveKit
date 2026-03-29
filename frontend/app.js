
// DOM Elements
const connectBtn = document.getElementById('connectBtn');
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const errorMessage = document.getElementById('errorMessage');
const connectionTimer = document.getElementById('connectionTimer');
const timeElapsedEl = document.getElementById('timeElapsed');
const chatMessages = document.getElementById('chatMessages');
const remoteAudio = document.getElementById('remoteAudio');

let room = null;
let isConnected = false;
let startTime = null;
let timerInterval = null;
let pendingAudioUnlock = false;
let readySignalTimeout = null;
let pendingConnectionMessageEl = null;

// Typing indicator state
let _typingIndicatorEl = null;
let _typingIndicatorTimer = null;

function showTypingIndicator() {
    if (_typingIndicatorEl) return;
    const row = document.createElement('div');
    row.className = 'chat-row typing-row';
    row.id = 'typingIndicatorRow';
    const avatar = document.createElement('div');
    avatar.className = 'bot-avatar';
    avatar.innerHTML = '<i class="fas fa-robot"></i>';
    row.appendChild(avatar);
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble chat-bot typing-bubble';
    bubble.innerHTML = '<span class="typing-label">checking</span><span class="dot"></span><span class="dot"></span><span class="dot"></span>';
    row.appendChild(bubble);
    chatMessages.appendChild(row);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    _typingIndicatorEl = row;
}

function hideTypingIndicator() {
    if (_typingIndicatorTimer) {
        clearTimeout(_typingIndicatorTimer);
        _typingIndicatorTimer = null;
    }
    if (_typingIndicatorEl) {
        _typingIndicatorEl.remove();
        _typingIndicatorEl = null;
    }
}

function clearReadySignalTimeout() {
    if (readySignalTimeout) {
        clearTimeout(readySignalTimeout);
        readySignalTimeout = null;
    }
}

function clearPendingConnectionMessage() {
    if (pendingConnectionMessageEl) {
        pendingConnectionMessageEl.remove();
        pendingConnectionMessageEl = null;
    }
}

function startReadySignalTimeout() {
    clearReadySignalTimeout();
    readySignalTimeout = setTimeout(() => {
        if (!isConnected) return;
        updateStatus('Agent not responding', 'disconnected');
        showError('The browser connected to the backend, but the LiveKit agent did not finish joining. Use Chrome or Edge instead of the VS Code browser, then reconnect.');
    }, 15000);
}

function scheduleTypingIndicator(delayMs = 1500) {
    hideTypingIndicator(); // cancel any previous
    _typingIndicatorTimer = setTimeout(() => {
        _typingIndicatorTimer = null;
        showTypingIndicator();
    }, delayMs);
}

// Help handle various LiveKit global name variations from different UMD versions
let LiveKitClient = window.LiveKitClient || window.LiveKit || window.LivekitClient;

console.log('SDK Detection:', {
    LiveKitClient: !!window.LiveKitClient,
    LiveKit: !!window.LiveKit,
    LivekitClient: !!window.LivekitClient
});

const BACKEND_URL = window.location.origin;

// Handle LiveKit data channel messages (transcript, bot replies, status)
function handleDataReceived(payload) {
    try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (!msg || !msg.type) return;

        if (msg.type === 'user') {
            hideTypingIndicator();
            addMessage(msg.text, 'user');
            scheduleTypingIndicator(1500); // Show spinner if LLM takes > 1.5s
        } else if (msg.type === 'bot') {
            clearPendingConnectionMessage();
            hideTypingIndicator();
            addMessage(msg.text, 'bot');
            if (isConnected) updateStatus('Connected — speak now', 'connected');
        } else if (msg.type === 'error') {
            clearPendingConnectionMessage();
            hideTypingIndicator();
            addMessage(`⚠️ ${msg.text}`, 'bot');
            showError(msg.text);
        } else if (msg.type === 'disconnect') {
            clearPendingConnectionMessage();
            hideTypingIndicator();
            addMessage('👋 Thank you for chatting! You will be disconnected shortly.', 'bot');
            updateStatus('Ending session…', 'disconnected');
            setTimeout(() => {
                disconnectRoom();
            }, 5000);
        } else if (msg.type === 'status') {
            scheduleTypingIndicator(250); // Show spinner quickly when backend is processing
            updateStatus('Processing…', 'connecting');
        } else if (msg.type === 'status_clear') {
            hideTypingIndicator();
            if (isConnected) updateStatus('Connected — speak now', 'connected');
        } else if (msg.type === 'ready') {
            clearReadySignalTimeout();
            clearPendingConnectionMessage();
            hideTypingIndicator();
            updateStatus('Connected — speak now 🎙️', 'connected');
            // No extra bubble — the intro speech just finished, status bar is enough
        }
    } catch (e) {
        console.warn('Failed to parse data message:', e);
    }
}

async function connectToRoom() {
    try {
        // Health check backend before proceeding
        updateStatus('Connecting to our assistant…', 'connecting');
        errorMessage.textContent = '';
        const healthResp = await fetch(`${BACKEND_URL}/health`).catch(() => null);
        if (!healthResp || !healthResp.ok) {
            errorMessage.textContent = 'Our assistant is currently unavailable. Please try again in a few moments.';
            updateStatus('Assistant Unavailable', 'disconnected');
            showError('Sorry, something went wrong connecting to the assistant. Please try again later.');
            return;
        }

        // Re-check just in case it loaded later (support all UMD variations)
        LiveKitClient = LiveKitClient || window.LiveKitClient || window.LiveKit || window.LivekitClient;

        if (!LiveKitClient) {
            throw new Error('LiveKit SDK missing. Please refresh (Ctrl+F5).');
        }

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error('Microphone API not available in this browser.');
        }

        const preflightStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        preflightStream.getTracks().forEach((t) => t.stop());

        updateStatus('Connecting...', 'connecting');

        // 1. Get Token from Backend
        const response = await fetch(`${BACKEND_URL}/token?identity=user_${Math.floor(Math.random() * 1000)}`);
        const data = await response.json();

        if (!data.token) throw new Error('Failed to get token');

        // 2. Connect to LiveKit Room
        room = new LiveKitClient.Room({
            adaptiveStream: true,
            dynacast: true,
        });

        // Set up event listeners

        room
            .on(LiveKitClient.RoomEvent.TrackSubscribed, handleTrackSubscribed)
            .on(LiveKitClient.RoomEvent.Disconnected, handleDisconnect)
            .on(LiveKitClient.RoomEvent.ActiveSpeakersChanged, handleActiveSpeakers)
            .on(LiveKitClient.RoomEvent.DataReceived, handleDataReceived);

        console.log('Connecting to LiveKit URL:', data.url);
        await room.connect(data.url, data.token);
        console.log('Connected to room successfully:', room.name);

        // 3. Publish Microphone
        updateStatus('Requesting Mic...', 'connecting');
        console.log('Requesting microphone access...');

        try {
            // Try newer method first, then fallback
            if (room.localParticipant.setMicrophoneEnabled) {
                await room.localParticipant.setMicrophoneEnabled(true);
            } else {
                await room.localParticipant.enableCameraAndMicrophone(false, true);
            }
            console.log('Microphone published successfully');
        } catch (micError) {
            console.error('Microphone access denied or failed:', micError);
            throw new Error('Microphone access denied. Please allow microphone access in your browser and refresh.');
        }

        // Update UI
        isConnected = true;
        // Show "initialising" until the agent sends its "ready" signal.
        // The ready handler in handleDataReceived updates this to "speak now".
        updateStatus('Initialising VoiceBot Assistant…', 'connecting');
        startReadySignalTimeout();
        connectBtn.innerHTML = '❌'; // Hangup icon
        connectBtn.classList.add('recording'); // Red pulse
        startTimer();

        pendingConnectionMessageEl = addMessage('⏳ Connecting you to our assistant. Please wait…', 'bot');

    } catch (error) {
        console.error('Connection failed:', error);
        showError('Connection failed: ' + error.message);
        disconnectRoom();
    }
}

function disconnectRoom() {
    if (room) {
        room.disconnect();
    }
    handleDisconnect();
}

function handleDisconnect() {
    clearReadySignalTimeout();
    clearPendingConnectionMessage();
    isConnected = false;
    room = null;
    updateStatus('Assistant Disconnected', '');
    connectBtn.innerHTML = '📞'; // Call icon
    connectBtn.classList.remove('recording');
    stopTimer();
    // Only add disconnect message if not already present as last message
    const lastMsg = chatMessages.lastElementChild;
    if (!lastMsg || !lastMsg.textContent.includes('disconnected')) {
        addMessage('You have been disconnected from the assistant.', 'bot');
    }
}

function handleTrackSubscribed(track, publication, participant) {
    if (track.kind === LiveKitClient.Track.Kind.Audio) {
        // Attach remote audio to the DOM element
        track.attach(remoteAudio);
        remoteAudio.play().catch((err) => {
            console.warn('Remote audio autoplay blocked or delayed:', err);
            pendingAudioUnlock = true;
            showError('Tap anywhere on the page to enable assistant audio playback.');
        });
        // No bubble — audio track is an implementation detail, not user-facing
    }
}

function handleActiveSpeakers(speakers) {
    // Optional: Visual feedback when bot is speaking
    /*
    speakers.forEach(speaker => {
       if (speaker.identity !== room.localParticipant.identity) {
           // Bot is speaking
       }
    });
    */
}

// UI Helpers
function updateStatus(text, className) {
    statusText.textContent = text;
    statusIndicator.className = 'status-indicator ' + className;
}

function showError(msg) {
    errorMessage.textContent = msg;
    errorMessage.style.display = 'block';
    setTimeout(() => errorMessage.style.display = 'none', 5000);
}

function startTimer() {
    startTime = Date.now();
    connectionTimer.style.display = 'block';
    timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
        const secs = (elapsed % 60).toString().padStart(2, '0');
        timeElapsedEl.textContent = `${mins}:${secs}`;
    }, 1000);
}

function stopTimer() {
    clearInterval(timerInterval);
    connectionTimer.style.display = 'none';
}


function addMessage(text, sender) {
    const row = document.createElement('div');
    row.className = 'chat-row ' + (sender === 'user' ? 'chat-row-user' : 'chat-row-bot');
    if (sender === 'bot') {
        const avatar = document.createElement('div');
        avatar.className = 'bot-avatar';
        avatar.innerHTML = '<i class="fas fa-robot"></i>';
        row.appendChild(avatar);
    }
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble ' + (sender === 'user' ? 'chat-user' : 'chat-bot');
    bubble.textContent = text;
    row.appendChild(bubble);
    if (sender === 'user') {
        const avatar = document.createElement('div');
        avatar.className = 'user-avatar';
        avatar.innerHTML = '<i class="fas fa-user"></i>';
        row.appendChild(avatar);
    }
    chatMessages.appendChild(row);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return row;
}

// Event Listeners
connectBtn.addEventListener('click', () => {
    if (isConnected) {
        disconnectRoom();
    } else {
        connectToRoom();
    }
});

document.addEventListener('click', async () => {
    if (!pendingAudioUnlock) return;
    try {
        await remoteAudio.play();
        pendingAudioUnlock = false;
        errorMessage.style.display = 'none';
    } catch (e) {
        console.warn('Audio unlock retry failed:', e);
    }
});
