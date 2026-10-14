import 'package:flutter/material.dart';

import 'src/screens/chat_screen.dart';

void main() {
  runApp(const LeynaApp());
}

class LeynaApp extends StatelessWidget {
  const LeynaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Leyna Assistant',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF6750A4),
      ),
      home: const ChatScreen(),
    );
  }
}
