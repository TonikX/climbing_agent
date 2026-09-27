export function bindTelegramUser(params: unknown, context: {
  messageChannel?: string;
  deliveryContext?: { channel?: string };
  requesterSenderId?: string;
}): Record<string, unknown> {
  const input = { ...(params as Record<string, unknown>) };
  if ((context.messageChannel ?? context.deliveryContext?.channel) !== "telegram" || !("user" in input)) return input;
  const id = context.requesterSenderId?.trim();
  if (!id) throw new Error("Telegram sender identity is missing; refusing an unbound journal operation");
  input.user = { externalRefs: [{ system: "telegram", id }] };
  return input;
}
