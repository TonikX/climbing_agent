export type TelegramActor = { telegramId: string };

export function toolActor(context: {
  messageChannel?: string;
  deliveryContext?: { channel?: string };
  requesterSenderId?: string;
}): TelegramActor {
  if ((context.messageChannel ?? context.deliveryContext?.channel) !== "telegram") {
    throw new Error("Journal tools require a Telegram sender");
  }
  return actor(context.requesterSenderId);
}

export function commandActor(context: {
  channel: string;
  senderId?: string;
  isAuthorizedSender: boolean;
}): TelegramActor {
  if (context.channel !== "telegram" || !context.isAuthorizedSender) {
    throw new Error("Telegram sender is not authorized");
  }
  return actor(context.senderId);
}

function actor(value?: string): TelegramActor {
  const id = value?.trim();
  if (!id || !/^[1-9][0-9]{0,19}$/.test(id)) throw new Error("Telegram sender identity is missing or invalid");
  return { telegramId: id };
}
