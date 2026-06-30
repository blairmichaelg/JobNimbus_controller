/**
 * Truck Server Frontend Logic
 * Vanilla JS implementation to avoid React/Webpack overhead on field devices.
 */

// --- State ---
let currentJobId = null;

// --- UI Elements ---
const intakeFormContainer = document.getElementById('intake-form-container');
const intakeForm = document.getElementById('intake-form');
const intakeSubmitBtn = document.getElementById('intake-submit-btn');

const jobActionsContainer = document.getElementById('job-actions-container');
const activeHomeownerName = document.getElementById('active-homeowner-name');
const activeJobIdDisplay = document.getElementById('active-job-id');

const cameraInput = document.getElementById('camera-input');
const cameraBtn = document.getElementById('camera-btn');
const queueCountEl = document.getElementById('queue-count');
const spinnerEl = document.getElementById('upload-spinner');
const statusDot = document.getElementById('status-indicator');
const toastEl = document.getElementById('toast');
const toastMsg = document.getElementById('toast-msg');

// --- Helper Functions ---
function showToast(msg, isError = false) {
    toastMsg.textContent = msg;
    toastEl.classList.remove('opacity-0');
    if (isError) {
        toastEl.classList.replace('bg-slate-800', 'bg-red-600');
    } else {
        toastEl.classList.replace('bg-red-600', 'bg-slate-800');
    }
    setTimeout(() => {
        toastEl.classList.add('opacity-0');
    }, 3000);
}

function getJobId() {
    if (!currentJobId) {
        showToast("Please complete intake first", true);
        return null;
    }
    return currentJobId;
}

// --- Intake Logic (Directive 3) ---
intakeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    intakeSubmitBtn.disabled = true;
    
    const originalText = intakeSubmitBtn.innerHTML;
    intakeSubmitBtn.innerHTML = `<span class="animate-pulse">Creating Lead...</span>`;

    const payload = {
        homeowner_name: document.getElementById('intake-name').value.trim(),
        address_line1: document.getElementById('intake-address').value.trim(),
        city: document.getElementById('intake-city').value.trim(),
        state: document.getElementById('intake-state').value.trim(),
        postal_code: document.getElementById('intake-zip').value.trim(),
        phone: document.getElementById('intake-phone').value.trim(),
        email: document.getElementById('intake-email').value.trim() || null,
        insurer_name: document.getElementById('intake-insurer').value.trim() || null,
        claim_number: document.getElementById('intake-claim').value.trim() || null
    };

    try {
        const res = await fetch('/api/field/jobs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'ngrok-skip-browser-warning': '1'
            },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        currentJobId = data.job_id;
        
        // SPA Swap
        intakeFormContainer.classList.add('hidden');
        activeHomeownerName.textContent = payload.homeowner_name;
        activeJobIdDisplay.textContent = currentJobId;
        jobActionsContainer.classList.remove('hidden');

        showToast(`Lead Captured: ${currentJobId}`);
    } catch (err) {
        console.error(err);
        showToast("Failed to create lead", true);
        intakeSubmitBtn.disabled = false;
        intakeSubmitBtn.innerHTML = originalText;
    }
});

// --- Upload Queue (Directive 3) ---
class UploadQueue {
    constructor() {
        this.queue = [];
        this.isProcessing = false;
    }

    addFiles(files) {
        const jobId = getJobId();
        if (!jobId) return;

        for (let file of files) {
            this.queue.push({
                file: file,
                jobId: jobId,
                retries: 0,
                maxRetries: 3
            });
        }
        
        this.updateUI();
        
        if (!this.isProcessing) {
            this.processQueue();
        }
    }

    updateUI() {
        queueCountEl.textContent = this.queue.length;
        if (this.queue.length > 0 || this.isProcessing) {
            spinnerEl.classList.remove('hidden');
            statusDot.classList.replace('bg-green-500', 'bg-amber-500');
            statusDot.classList.replace('shadow-[0_0_8px_rgba(34,197,94,0.8)]', 'shadow-[0_0_8px_rgba(245,158,11,0.8)]');
        } else {
            spinnerEl.classList.add('hidden');
            statusDot.classList.replace('bg-amber-500', 'bg-green-500');
            statusDot.classList.replace('shadow-[0_0_8px_rgba(245,158,11,0.8)]', 'shadow-[0_0_8px_rgba(34,197,94,0.8)]');
        }
    }

    async processQueue() {
        if (this.queue.length === 0) {
            this.isProcessing = false;
            this.updateUI();
            showToast("All photos uploaded successfully");
            return;
        }

        this.isProcessing = true;
        this.updateUI();

        // FIFO pop
        const task = this.queue.shift();
        
        try {
            await this.uploadSingleFile(task);
            // Success, proceed to next immediately
            this.updateUI();
            this.processQueue();
        } catch (error) {
            console.error(`Upload failed: ${error.message}`);
            
            if (task.retries < task.maxRetries) {
                task.retries++;
                const backoffMs = Math.pow(2, task.retries) * 1000 + Math.random() * 500;
                console.log(`Retrying in ${Math.round(backoffMs)}ms (Attempt ${task.retries}/${task.maxRetries})`);
                
                // Put back at the front of the queue
                this.queue.unshift(task);
                
                setTimeout(() => {
                    this.processQueue();
                }, backoffMs);
            } else {
                showToast(`Failed to upload ${task.file.name} after 3 retries`, true);
                // Drop the file, proceed with the rest
                this.updateUI();
                this.processQueue();
            }
        }
    }

    async uploadSingleFile(task) {
        // Must use FormData to stream bytes. DO NOT use toDataURL on mobile for 40 photos (OOM risk).
        const formData = new FormData();
        formData.append("files", task.file);

        // Directive 3: Inject ngrok-skip-browser-warning
        const response = await fetch(`/api/field/jobs/${task.jobId}/photos`, {
            method: 'POST',
            headers: {
                "ngrok-skip-browser-warning": "1"
            },
            body: formData
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
    }
}

const queue = new UploadQueue();

// --- Camera Integration ---
cameraBtn.addEventListener('click', () => {
    if (getJobId()) {
        cameraInput.click();
    }
});

cameraInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
        queue.addFiles(e.target.files);
        // Reset input so taking another photo triggers 'change' again
        e.target.value = ''; 
    }
});


// --- DPI-Correct Signature Pad (Directive 4) ---
const canvas = document.getElementById('signature-pad');
let signaturePad;

function resizeCanvas() {
    // When zoomed out to 100%, it just sets it to the width.
    // When on retina screens, devicePixelRatio is > 1.
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    
    // This part causes the canvas to be cleared
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    canvas.getContext("2d").scale(ratio, ratio);
    
    if (signaturePad) {
        signaturePad.clear(); // otherwise drawn points are stretched
    }
}

// Wait for CDN to load SignaturePad
window.addEventListener('load', () => {
    resizeCanvas();
    signaturePad = new SignaturePad(canvas, {
        penColor: 'rgb(15, 23, 42)', // slate-900 to match theme
        backgroundColor: 'rgb(248, 250, 252)' // slate-50
    });
});

// Re-resize on orientation change
window.addEventListener('resize', resizeCanvas);

document.getElementById('clear-sig-btn').addEventListener('click', () => {
    if (signaturePad) {
        signaturePad.clear();
    }
});

document.getElementById('submit-sig-btn').addEventListener('click', async () => {
    const jobId = getJobId();
    if (!jobId) return;

    if (signaturePad.isEmpty()) {
        showToast("Please provide a signature first", true);
        return;
    }

    // toDataURL is fine here because a signature canvas is small
    const dataURL = signaturePad.toDataURL('image/png');
    const b64Data = dataURL.split(',')[1];
    
    const originalText = document.getElementById('submit-sig-btn').innerHTML;
    document.getElementById('submit-sig-btn').innerHTML = `<span class="animate-pulse">Submitting...</span>`;

    try {
        const response = await fetch('/api/field/sign', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'ngrok-skip-browser-warning': '1'
            },
            body: JSON.stringify({
                job_id: jobId,
                image_base64: b64Data
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        showToast("Agreement signed successfully!");
        signaturePad.clear();
    } catch (e) {
        showToast("Failed to submit signature", true);
        console.error(e);
    } finally {
        document.getElementById('submit-sig-btn').innerHTML = originalText;
    }
});
