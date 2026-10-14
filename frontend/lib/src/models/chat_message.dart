/// Who authored a chat message.
enum ChatRole { user, assistant }

/// A single turn in the conversation.
class ChatMessage {
  const ChatMessage({required this.role, required this.text});

  final ChatRole role;
  final String text;

  /// Wire format expected by the backend (`{"role": ..., "content": ...}`).
  Map<String, String> toJson() => {'role': role.name, 'content': text};
}
