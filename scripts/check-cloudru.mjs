const baseUrl = "https://foundation-models.api.cloud.ru/v1";
const apiKey = process.env.CLOUDRU_API_KEY;
const model = "deepseek-ai/DeepSeek-V4-Flash";

if (!apiKey) throw new Error("CLOUDRU_API_KEY is not set");

const headers = { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" };
const modelsResponse = await fetch(`${baseUrl}/models`, { headers });
const modelsBody = await modelsResponse.json();
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
const completionBody = await completionResponse.json();
console.log(JSON.stringify({
  completionStatus: completionResponse.status,
  model: completionBody.model,
  answer: completionBody.choices?.[0]?.message?.content,
  error: completionResponse.ok ? undefined : completionBody,
}));

if (!completionResponse.ok) process.exit(1);
