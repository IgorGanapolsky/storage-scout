import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(MaterialApp(
    home: StorageScoutEntry(),
    theme: ThemeData.dark().copyWith(
      scaffoldBackgroundColor: const Color(0xFF121212),
      primaryColor: Colors.greenAccent,
    ),
  ));
}

class StorageScoutEntry extends StatefulWidget {
  const StorageScoutEntry({super.key});

  @override
  State<StorageScoutEntry> createState() => _StorageScoutEntryState();
}

class _StorageScoutEntryState extends State<StorageScoutEntry> {
  final _formKey = GlobalKey<FormState>();

  // --- CONFIGURATION ---
  // TODO: Replace with your actual secrets from a .env file or secure storage
  static const String ghToken = 'YOUR_GITHUB_TOKEN';
  static const String ghUser = 'YOUR_USERNAME';
  static const String ghRepo = 'YOUR_REPO_NAME';
  static const String ntfyTopic = 'coral_springs_storage_alerts';

  // --- STATE VARIABLES ---
  String facilityName = '';
  String zipCode = '33071';
  double price10x20 = 0.0;
  double neighborRate = 65.0; // Benchmark P2P rate for 5x5
  bool hasInsuranceWaiver = false; // Toggle for the $12 fee
  bool isSyncing = false;

  // --- LOGIC ---
  double get calculatedSpread {
    double revenue = neighborRate * 4;
    double cost = price10x20 + (hasInsuranceWaiver ? 0.0 : 12.0);
    return revenue - cost;
  }

  bool get isHighPriority => calculatedSpread >= 120;

  Future<void> syncAndNotify() async {
    setState(() => isSyncing = true);

    try {
      // 1. GET current file to find SHA
      final getRes = await http.get(
        Uri.parse(
            'https://api.github.com/repos/$ghUser/$ghRepo/contents/storage_spreads.csv'),
        headers: {
          'Authorization': 'Bearer $ghToken',
          'Accept': 'application/vnd.github+json',
        },
      );

      String? sha;
      String currentContent = '';

      if (getRes.statusCode == 200) {
        final decoded = jsonDecode(getRes.body);
        sha = decoded['sha'];
        currentContent = utf8
            .decode(base64.decode(decoded['content'].replaceAll('\n', '')));
      } else if (getRes.statusCode == 404) {
        // File doesn't exist - create with header
        currentContent =
            'date,zip,facility,cost,revenue,spread,insurance_waived\n';
      }

      // 2. APPEND new row
      String date = DateTime.now().toString().split(' ')[0];
      String newRow =
          '$date,$zipCode,$facilityName,$price10x20,${(neighborRate * 4)},${calculatedSpread.toStringAsFixed(2)},$hasInsuranceWaiver\n';
      String updatedContent = currentContent.trimRight() + '\n' + newRow;

      // 3. PUT update back to GitHub
      final putRes = await http.put(
        Uri.parse(
            'https://api.github.com/repos/$ghUser/$ghRepo/contents/storage_spreads.csv'),
        headers: {
          'Authorization': 'Bearer $ghToken',
          'Accept': 'application/vnd.github+json',
        },
        body: jsonEncode({
          'message': 'Scout Entry: $facilityName',
          'content': base64Encode(utf8.encode(updatedContent)),
          if (sha != null) 'sha': sha,
        }),
      );

      if (putRes.statusCode != 200 && putRes.statusCode != 201) {
        throw Exception('GitHub API error: ${putRes.statusCode}');
      }

      // 4. NTFY ALERT (High Profit Only)
      if (isHighPriority) {
        await http.post(
          Uri.parse('https://ntfy.sh/$ntfyTopic'),
          body:
              'DEAL FOUND: $facilityName spread is \$${calculatedSpread.toStringAsFixed(0)}/mo!',
          headers: {
            'Title': 'Arbitrage Alert',
            'Priority': 'high',
            'Tags': 'moneybag',
          },
        );
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(isHighPriority
                ? '✅ Synced + Alert Sent!'
                : '✅ Synced to Dashboard!'),
            backgroundColor: Colors.green,
          ),
        );
        _formKey.currentState!.reset();
        setState(() {
          price10x20 = 0;
          hasInsuranceWaiver = false;
          facilityName = '';
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ Error: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      setState(() => isSyncing = false);
    }
  }

  // --- UI ---
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Storage Scout'),
        backgroundColor: Colors.black,
      ),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // HEADER: THE SPREAD
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.grey[900],
                  borderRadius: BorderRadius.circular(15),
                  border: Border.all(
                    color: calculatedSpread > 100
                        ? Colors.greenAccent
                        : Colors.grey[700]!,
                    width: 2,
                  ),
                ),
                child: Column(
                  children: [
                    const Text(
                      'ESTIMATED SPREAD',
                      style: TextStyle(
                        color: Colors.grey,
                        fontSize: 12,
                        letterSpacing: 1.5,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '\$${calculatedSpread.toStringAsFixed(2)}',
                      style: const TextStyle(
                        fontSize: 42,
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                    Text(
                      'per month',
                      style: TextStyle(color: Colors.grey[600], fontSize: 12),
                    ),
                    if (isHighPriority) ...[
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 4),
                        decoration: BoxDecoration(
                          color: Colors.greenAccent,
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: const Text(
                          'HIGH PRIORITY',
                          style: TextStyle(
                            color: Colors.black,
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 30),

              // INPUTS
              TextFormField(
                decoration: const InputDecoration(
                  labelText: 'Facility Name',
                  prefixIcon: Icon(Icons.store, color: Colors.grey),
                ),
                style: const TextStyle(color: Colors.white),
                validator: (v) => v?.isEmpty ?? true ? 'Required' : null,
                onChanged: (val) => setState(() => facilityName = val),
              ),
              const SizedBox(height: 15),

              TextFormField(
                decoration: const InputDecoration(
                  labelText: 'Zip Code',
                  prefixIcon: Icon(Icons.location_on, color: Colors.grey),
                ),
                initialValue: zipCode,
                style: const TextStyle(color: Colors.white),
                keyboardType: TextInputType.number,
                onChanged: (val) => setState(() => zipCode = val),
              ),
              const SizedBox(height: 15),

              TextFormField(
                decoration: const InputDecoration(
                  labelText: '10x20 Monthly Rate',
                  prefixIcon: Icon(Icons.attach_money, color: Colors.grey),
                ),
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(color: Colors.white),
                validator: (v) {
                  if (v?.isEmpty ?? true) return 'Required';
                  if (double.tryParse(v!) == null) return 'Invalid number';
                  return null;
                },
                onChanged: (val) =>
                    setState(() => price10x20 = double.tryParse(val) ?? 0.0),
              ),
              const SizedBox(height: 15),

              TextFormField(
                decoration: const InputDecoration(
                  labelText: 'P2P 5x5 Rate (Neighbor avg)',
                  prefixIcon: Icon(Icons.people, color: Colors.grey),
                ),
                initialValue: neighborRate.toString(),
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(color: Colors.white),
                onChanged: (val) =>
                    setState(() => neighborRate = double.tryParse(val) ?? 65.0),
              ),

              const SizedBox(height: 20),

              // WAIVER TOGGLE
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text(
                  'Insurance Waiver Provided?',
                  style: TextStyle(color: Colors.white, fontSize: 16),
                ),
                subtitle: const Text(
                  'Removes \$12.00 monthly fee',
                  style: TextStyle(color: Colors.grey),
                ),
                value: hasInsuranceWaiver,
                activeColor: Colors.greenAccent,
                onChanged: (val) => setState(() => hasInsuranceWaiver = val),
              ),

              // Formula reference
              Container(
                margin: const EdgeInsets.only(top: 10),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.grey[850],
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Text(
                  'Formula: (P2P × 4) - 10x20 - Insurance',
                  style: TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 11,
                    color: Colors.grey,
                  ),
                ),
              ),

              const Spacer(),

              // SYNC BUTTON
              SizedBox(
                width: double.infinity,
                height: 55,
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: calculatedSpread > 0
                        ? Colors.greenAccent
                        : Colors.grey[800],
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  onPressed: isSyncing
                      ? null
                      : () {
                          if (_formKey.currentState!.validate()) {
                            syncAndNotify();
                          }
                        },
                  icon: isSyncing
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.black,
                          ),
                        )
                      : const Icon(Icons.cloud_upload, color: Colors.black),
                  label: Text(
                    isSyncing ? 'SYNCING...' : 'LOG DEAL TO GITHUB',
                    style: const TextStyle(
                      color: Colors.black,
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
