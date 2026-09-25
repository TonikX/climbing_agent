# Voice flow

Cloud.ru `openai/whisper-large-v3` преобразует voice в короткий transcript.
Journal skill трактует transcript так же, как текст.

В DeepSeek не требуются Telegram update, `message_id`, `chat_id`, `file_id`, MIME,
размер файла, путь, длительность и diagnostics провайдера. Эти данные могут
использоваться transport-слоем, но не должны добавляться к journal arguments.

Для «Ещё одна, до четырнадцатого, один срыв» достаточно вызвать
`append_climbing_attempt` с `continueCurrentRoute=true`, `highPoint=14` и
`falls=1`. FastAPI восстановит тренировку, трассу, сектор, локацию и номер
попытки из PostgreSQL.
