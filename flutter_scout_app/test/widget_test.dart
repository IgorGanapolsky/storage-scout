// Basic widget test for Storage Scout app

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:storage_scout/main.dart';

void main() {
  testWidgets('StorageScoutApp renders bottom navigation', (WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(
      home: const StorageScoutApp(),
      theme: ThemeData.dark(),
    ));

    // Verify bottom navigation items exist
    expect(find.text('Scout'), findsOneWidget);
    expect(find.text('Deals'), findsOneWidget);
    expect(find.text('Listing'), findsOneWidget);
  });
}
