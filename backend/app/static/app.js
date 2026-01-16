const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("message");
const replyText = document.getElementById("replyText");
const replyMeta = document.getElementById("replyMeta");
const providersList = document.getElementById("providersList");
const slotsList = document.getElementById("slotsList");
const bookingStatus = document.getElementById("bookingStatus");
const clearBtn = document.getElementById("clearBtn");
const voiceUrl = document.getElementById("voiceUrl");
const startRecording = document.getElementById("startRecording");
const stopRecording = document.getElementById("stopRecording");
const playReply = document.getElementById("playReply");
const voiceStatus = document.getElementById("voiceStatus");
const voiceTranscript = document.getElementById("voiceTranscript");
const voiceReply = document.getElementById("voiceReply");

let selectedSlot = null;
let lastReason = null;
let conversationId = null;
let selectedProvider = null;
let mediaStream = null;
let mediaRecorder = null;
let audioChunks = [];
let recorderMimeType = "audio/webm";
let lastVoiceReply = "";

const formatSlotTime = (iso) => {
  if (!iso) return "Unknown time";
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
};

const setStatus = (message, type = "info") => {
  bookingStatus.textContent = message;
  bookingStatus.dataset.type = type;
};

const renderMeta = (chat) => {
  replyMeta.innerHTML = "";
  const items = [
    ["intent", chat.intent],
    ["department", chat.department || "none"],
    ["urgent_case", chat.urgent_case_id || "none"],
  ];
  items.forEach(([label, value]) => {
    const span = document.createElement("span");
    span.textContent = `${label}: ${value}`;
    replyMeta.appendChild(span);
  });
};

const renderProviders = (providers) => {
  providersList.innerHTML = "";
  selectedProvider = null;
  if (!providers || providers.length === 0) {
    return;
  }

  providers.forEach((provider, index) => {
    const card = document.createElement("div");
    card.className = "provider-card disabled";
    const location = [provider.city, provider.state].filter(Boolean).join(" ");
    card.innerHTML = `
      <div class="provider-title">${provider.name}</div>
      <div class="provider-meta">${location || "Location unavailable"}</div>
      <div class="provider-meta">Provider ${index + 1}</div>
    `;
    providersList.appendChild(card);
  });
};

const renderSlots = (slots) => {
  slotsList.innerHTML = "";
  selectedSlot = null;
  if (!slots || slots.length === 0) {
    const empty = document.createElement("p");
    empty.className = "fineprint";
    empty.textContent = "No available slots yet.";
    slotsList.appendChild(empty);
    return;
  }

  slots.forEach((slot, index) => {
    const card = document.createElement("div");
    card.className = "slot-card";
    card.innerHTML = `
      <div class="slot-title">${slot.department} with ${slot.provider}</div>
      <div class="slot-meta">${formatSlotTime(slot.start_time)}</div>
      <div class="slot-meta">Slot ${index + 1}</div>
    `;
    card.addEventListener("click", () => {
      document
        .querySelectorAll(".slot-card")
        .forEach((el) => el.classList.remove("selected"));
      card.classList.add("selected");
      selectedSlot = slot;
      setStatus(`Selected ${slot.department} at ${formatSlotTime(slot.start_time)}.`);
    });
    slotsList.appendChild(card);
  });
};

const updateVoiceUrl = () => {
  if (!voiceUrl) return;
  const origin = window.location.origin;
  voiceUrl.textContent = `${origin}/api/voice/inbound`;
};

const setVoiceStatus = (message) => {
  if (!voiceStatus) return;
  voiceStatus.textContent = message;
};

const stopStream = () => {
  if (mediaRecorder) {
    mediaRecorder.ondataavailable = null;
    mediaRecorder.onstop = null;
    mediaRecorder = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
};

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;
  messageInput.value = "";
  replyText.textContent = "Thinking...";
  replyMeta.innerHTML = "";
  slotsList.innerHTML = "";
  providersList.innerHTML = "";
  lastReason = null;
  selectedSlot = null;

  try {
    const headers = { "Content-Type": "application/json" };
    const response = await fetch("/api/chat", {
      method: "POST",
      headers,
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        patient_name: null,
        patient_email: null,
      }),
    });
    if (!response.ok) {
      throw new Error("Chat failed");
    }
    const data = await response.json();
    conversationId = data.conversation_id || conversationId;
    replyText.textContent = data.reply || "No reply received.";
    lastReason = data.reason || message;
    renderMeta(data);
    renderProviders(data.suggested_providers || []);
    renderSlots(data.suggested_slots || []);
    if (data.intent === "URGENT") {
      setStatus("Urgent case logged. Follow safety guidance.", "warn");
    } else {
      setStatus("Select a slot to book.", "info");
    }
  } catch (err) {
    replyText.textContent =
      "Sorry, I could not reach the receptionist service.";
    setStatus("Chat failed. Check the API server.", "error");
  }
});

clearBtn.addEventListener("click", () => {
  messageInput.value = "";
  replyText.textContent = "Waiting for input.";
  replyMeta.innerHTML = "";
  providersList.innerHTML = "";
  slotsList.innerHTML = "";
  selectedSlot = null;
  selectedProvider = null;
  conversationId = null;
  setStatus("Select a slot above before booking.");
});

updateVoiceUrl();

if (startRecording && stopRecording && playReply) {
  startRecording.addEventListener("click", async () => {
    if (!voiceTranscript || !voiceReply) return;
  try {
    voiceTranscript.textContent = "Listening...";
    voiceReply.textContent = "Waiting for input.";
    playReply.disabled = true;
    lastVoiceReply = "";
    audioChunks = [];
    setVoiceStatus("Recording. Speak clearly and tap stop.");

    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorderMimeType = "audio/webm";
    if (!MediaRecorder.isTypeSupported(recorderMimeType)) {
      recorderMimeType = "audio/webm;codecs=opus";
    }
    if (!MediaRecorder.isTypeSupported(recorderMimeType)) {
      recorderMimeType = "audio/ogg;codecs=opus";
    }
    mediaRecorder = new MediaRecorder(mediaStream, {
      mimeType: recorderMimeType,
    });
    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };
    mediaRecorder.start();

    startRecording.disabled = true;
    stopRecording.disabled = false;
  } catch (err) {
    setVoiceStatus("Microphone access failed.");
  }
  });

  stopRecording.addEventListener("click", async () => {
    if (!voiceTranscript || !voiceReply) return;
  stopRecording.disabled = true;
  startRecording.disabled = false;
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    setVoiceStatus("No audio captured.");
    stopStream();
    return;
  }

  const stopped = new Promise((resolve) => {
    mediaRecorder.onstop = () => resolve();
  });
  mediaRecorder.stop();
  await stopped;
  stopStream();

  if (audioChunks.length === 0) {
    setVoiceStatus("No audio captured.");
    return;
  }

  setVoiceStatus("Transcribing...");
  const blob = new Blob(audioChunks, { type: recorderMimeType });
  const extension = recorderMimeType.includes("ogg") ? "ogg" : "webm";

  try {
    const formData = new FormData();
    formData.append("file", blob, `recording.${extension}`);
    const response = await fetch("/api/voice/transcribe", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      let detail = "Transcription failed";
      try {
        const body = await response.json();
        if (body && body.detail) {
          detail = body.detail;
        }
      } catch (err) {
        detail = "Transcription failed";
      }
      throw new Error(detail);
    }
    const data = await response.json();
    voiceTranscript.textContent = data.text || "No transcript returned.";

    setVoiceStatus("Routing message...");
    const chatResponse = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: data.text || "" }),
    });
    if (!chatResponse.ok) throw new Error("Chat failed");
    const chatData = await chatResponse.json();
    voiceReply.textContent = chatData.reply || "No reply received.";
    lastVoiceReply = chatData.reply || "";
    playReply.disabled = !lastVoiceReply;
    setVoiceStatus("Done. You can play the reply.");
  } catch (err) {
    voiceTranscript.textContent =
      err.message || "Sorry, we could not process that audio.";
    setVoiceStatus("Voice flow failed.");
  }
  });

  playReply.addEventListener("click", () => {
  if (!lastVoiceReply) return;
  const utterance = new SpeechSynthesisUtterance(lastVoiceReply);
  speechSynthesis.speak(utterance);
  });
}
