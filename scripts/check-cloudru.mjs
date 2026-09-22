const baseUrl = "https://foundation-models.api.cloud.ru/v1";
const apiKey = process.env.CLOUDRU_API_KEY;
const model = "deepseek-ai/DeepSeek-V4-Flash";

if (!apiKey) throw new Error("CLOUDRU_API_KEY is not set");

async function responseBody(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const headers = { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" };
const modelsResponse = await fetch(`${baseUrl}/models`, { headers });
const modelsBody = await responseBody(modelsResponse);
console.log(JSON.stringify({
  modelsStatus: modelsResponse.status,
  modelAvailable: Array.isArray(modelsBody.data) && modelsBody.data.some((item) => item.id === model),
  error: modelsResponse.ok ? undefined : modelsBody,
}));

if (!modelsResponse.ok) process.exit(1);

const completionResponse = await fetch(`${baseUrl}/chat/completions`, {
  method: "POST",
  headers,
  body: JSON.stringify({
    model,
    messages: [{ role: "user", content: "Reply with exactly: OK" }],
    max_tokens: 16,
    stream: false,
  }),
});
const completionBody = await responseBody(completionResponse);
console.log(JSON.stringify({
  completionStatus: completionResponse.status,
  model: typeof completionBody === "object" ? completionBody.model : undefined,
  answer: typeof completionBody === "object" ? completionBody.choices?.[0]?.message?.content : undefined,
  error: completionResponse.ok ? undefined : completionBody,
}));

if (!completionResponse.ok) process.exit(1);
