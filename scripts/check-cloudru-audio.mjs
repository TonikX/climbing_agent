const baseUrl = "https://foundation-models.api.cloud.ru/v1";
const apiKey = process.env.CLOUDRU_API_KEY;
const model = "openai/whisper-large-v3";

if (!apiKey) throw new Error("CLOUDRU_API_KEY is not set");

async function responseBody(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function silentWav(durationMs = 1000, sampleRate = 16000) {
  const samples = Math.floor((durationMs * sampleRate) / 1000);
  const dataLength = samples * 2;
  const wav = Buffer.alloc(44 + dataLength);
  wav.write("RIFF", 0);
  wav.writeUInt32LE(36 + dataLength, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(sampleRate, 24);
  wav.writeUInt32LE(sampleRate * 2, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(dataLength, 40);
  return wav;
}

const modelsResponse = await fetch(`${baseUrl}/models`, {
  headers: { Authorization: `Bearer ${apiKey}` },
});
const modelsBody = await responseBody(modelsResponse);
const modelInfo = Array.isArray(modelsBody.data)
  ? modelsBody.data.find((item) => item.id === model)
  : undefined;

console.log(JSON.stringify({
  modelsStatus: modelsResponse.status,
  modelAvailable: Boolean(modelInfo),
  modelType: modelInfo?.metadata?.type,
}));

if (!modelsResponse.ok || !modelInfo) process.exit(1);

const form = new FormData();
form.append("model", model);
form.append("file", new Blob([silentWav()], { type: "audio/wav" }), "silence.wav");

const transcriptionResponse = await fetch(`${baseUrl}/audio/transcriptions`, {
  method: "POST",
  headers: { Authorization: `Bearer ${apiKey}` },
  body: form,
});
const transcriptionBody = await responseBody(transcriptionResponse);

console.log(JSON.stringify({
  transcriptionStatus: transcriptionResponse.status,
  text: typeof transcriptionBody === "object" ? transcriptionBody.text : undefined,
  error: transcriptionResponse.ok ? undefined : transcriptionBody,
}));

if (!transcriptionResponse.ok) process.exit(1);
