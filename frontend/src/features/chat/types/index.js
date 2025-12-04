/**
 * @typedef {Object} Message
 * @property {string} role - The role of the message sender ('user', 'assistant', 'system')
 * @property {string} content - The content of the message
 */

/**
 * @typedef {Object} EmotionState
 * @property {string} current_emotion - The current emotion of the bot
 * @property {string} emotion_intensity - The intensity of the emotion
 * @property {string} internal_thought - The internal thought process
 */

/**
 * @typedef {Object} ChatState
 * @property {Message[]} messages - List of chat messages
 * @property {string} input - Current input value
 * @property {boolean} isLoading - Whether the bot is typing
 * @property {EmotionState|null} emotionState - Current emotion state
 */
