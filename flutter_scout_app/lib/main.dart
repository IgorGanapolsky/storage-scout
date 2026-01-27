import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(MaterialApp(
    home: const StorageScoutApp(),
    theme: ThemeData.dark().copyWith(
      scaffoldBackgroundColor: const Color(0xFF121212),
      primaryColor: Colors.greenAccent,
    ),
  ));
}

class StorageScoutApp extends StatefulWidget {
  const StorageScoutApp({super.key});

  @override
  State<StorageScoutApp> createState() => _StorageScoutAppState();
}

class _StorageScoutAppState extends State<StorageScoutApp> {
  int _currentIndex = 0;

  final List<Widget> _screens = [
    const ScoutScreen(),
    const DealsScreen(),
    const ListingGeneratorScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _screens[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (i) => setState(() => _currentIndex = i),
        backgroundColor: Colors.black,
        selectedItemColor: Colors.greenAccent,
        unselectedItemColor: Colors.grey,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.search), label: 'Scout'),
          BottomNavigationBarItem(icon: Icon(Icons.handshake), label: 'Deals'),
          BottomNavigationBarItem(icon: Icon(Icons.edit_note), label: 'Listing'),
        ],
      ),
    );
  }
}

// ============================================================================
// SCOUT SCREEN - Price Entry & Spread Calculation
// ============================================================================
class ScoutScreen extends StatefulWidget {
  const ScoutScreen({super.key});

  @override
  State<ScoutScreen> createState() => _ScoutScreenState();
}

class _ScoutScreenState extends State<ScoutScreen> {
  final _formKey = GlobalKey<FormState>();

  static const String ghToken = String.fromEnvironment('GITHUB_TOKEN');
  static const String ghUser = 'IgorGanapolsky';
  static const String ghRepo = 'storage-scout';
  static const String ntfyTopic = 'igor_storage_alerts';

  String facilityName = '';
  String zipCode = '33071';
  double price10x20 = 0.0;
  double neighborRate = 65.0;
  bool hasInsuranceWaiver = false;
  bool isSyncing = false;

  double get calculatedSpread {
    double revenue = neighborRate * 4;
    double cost = price10x20 + (hasInsuranceWaiver ? 0.0 : 12.0);
    return revenue - cost;
  }

  bool get isHighPriority => calculatedSpread >= 120;

  Future<void> syncAndNotify() async {
    setState(() => isSyncing = true);

    try {
      final getRes = await http.get(
        Uri.parse('https://api.github.com/repos/$ghUser/$ghRepo/contents/storage_spreads.csv'),
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
        currentContent = utf8.decode(base64.decode(decoded['content'].replaceAll('\n', '')));
      } else if (getRes.statusCode == 404) {
        currentContent = 'date,zip,facility,cost,revenue,spread,insurance_waived,status\n';
      }

      String date = DateTime.now().toString().split(' ')[0];
      String newRow = '$date,$zipCode,$facilityName,$price10x20,${(neighborRate * 4)},${calculatedSpread.toStringAsFixed(2)},$hasInsuranceWaiver,scouted\n';
      String updatedContent = currentContent.trimRight() + '\n' + newRow;

      final putRes = await http.put(
        Uri.parse('https://api.github.com/repos/$ghUser/$ghRepo/contents/storage_spreads.csv'),
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

      if (isHighPriority) {
        await http.post(
          Uri.parse('https://ntfy.sh/$ntfyTopic'),
          body: 'DEAL FOUND: $facilityName spread is \$${calculatedSpread.toStringAsFixed(0)}/mo!',
          headers: {'Title': 'Arbitrage Alert', 'Priority': 'high', 'Tags': 'moneybag'},
        );
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(isHighPriority ? '✅ Synced + Alert Sent!' : '✅ Synced to Dashboard!'),
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scout Prices'), backgroundColor: Colors.black),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // SPREAD DISPLAY
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.grey[900],
                  borderRadius: BorderRadius.circular(15),
                  border: Border.all(
                    color: calculatedSpread > 100 ? Colors.greenAccent : Colors.grey[700]!,
                    width: 2,
                  ),
                ),
                child: Column(
                  children: [
                    const Text('ESTIMATED SPREAD', style: TextStyle(color: Colors.grey, fontSize: 12, letterSpacing: 1.5)),
                    const SizedBox(height: 5),
                    Text('\$${calculatedSpread.toStringAsFixed(2)}', style: const TextStyle(fontSize: 42, fontWeight: FontWeight.bold, color: Colors.white)),
                    Text('per month', style: TextStyle(color: Colors.grey[600], fontSize: 12)),
                    if (isHighPriority) ...[
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                        decoration: BoxDecoration(color: Colors.greenAccent, borderRadius: BorderRadius.circular(20)),
                        child: const Text('HIGH PRIORITY', style: TextStyle(color: Colors.black, fontSize: 10, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 30),

              // INPUTS
              TextFormField(
                decoration: const InputDecoration(labelText: 'Facility Name', prefixIcon: Icon(Icons.store, color: Colors.grey)),
                style: const TextStyle(color: Colors.white),
                validator: (v) => v?.isEmpty ?? true ? 'Required' : null,
                onChanged: (val) => setState(() => facilityName = val),
              ),
              const SizedBox(height: 15),
              TextFormField(
                decoration: const InputDecoration(labelText: 'Zip Code', prefixIcon: Icon(Icons.location_on, color: Colors.grey)),
                initialValue: zipCode,
                style: const TextStyle(color: Colors.white),
                keyboardType: TextInputType.number,
                onChanged: (val) => setState(() => zipCode = val),
              ),
              const SizedBox(height: 15),
              TextFormField(
                decoration: const InputDecoration(labelText: '10x20 Monthly Rate', prefixIcon: Icon(Icons.attach_money, color: Colors.grey)),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(color: Colors.white),
                validator: (v) {
                  if (v?.isEmpty ?? true) return 'Required';
                  if (double.tryParse(v!) == null) return 'Invalid number';
                  return null;
                },
                onChanged: (val) => setState(() => price10x20 = double.tryParse(val) ?? 0.0),
              ),
              const SizedBox(height: 15),
              TextFormField(
                decoration: const InputDecoration(labelText: 'P2P 5x5 Rate (Neighbor avg)', prefixIcon: Icon(Icons.people, color: Colors.grey)),
                initialValue: neighborRate.toString(),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(color: Colors.white),
                onChanged: (val) => setState(() => neighborRate = double.tryParse(val) ?? 65.0),
              ),
              const SizedBox(height: 20),

              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Insurance Waiver Provided?', style: TextStyle(color: Colors.white, fontSize: 16)),
                subtitle: const Text('Removes \$12.00 monthly fee', style: TextStyle(color: Colors.grey)),
                value: hasInsuranceWaiver,
                activeColor: Colors.greenAccent,
                onChanged: (val) => setState(() => hasInsuranceWaiver = val),
              ),

              const SizedBox(height: 20),

              SizedBox(
                width: double.infinity,
                height: 55,
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: calculatedSpread > 0 ? Colors.greenAccent : Colors.grey[800],
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: isSyncing ? null : () {
                    if (_formKey.currentState!.validate()) syncAndNotify();
                  },
                  icon: isSyncing
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                      : const Icon(Icons.cloud_upload, color: Colors.black),
                  label: Text(isSyncing ? 'SYNCING...' : 'LOG DEAL TO GITHUB', style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 16)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ============================================================================
// DEALS SCREEN - Track Active Leases & Revenue
// ============================================================================
class DealsScreen extends StatefulWidget {
  const DealsScreen({super.key});

  @override
  State<DealsScreen> createState() => _DealsScreenState();
}

class _DealsScreenState extends State<DealsScreen> {
  List<Deal> deals = [];
  bool isLoading = true;

  static const String ghToken = String.fromEnvironment('GITHUB_TOKEN');
  static const String ghUser = 'IgorGanapolsky';
  static const String ghRepo = 'storage-scout';

  @override
  void initState() {
    super.initState();
    loadDeals();
  }

  Future<void> loadDeals() async {
    setState(() => isLoading = true);
    try {
      final res = await http.get(
        Uri.parse('https://api.github.com/repos/$ghUser/$ghRepo/contents/active_deals.csv'),
        headers: {'Authorization': 'Bearer $ghToken', 'Accept': 'application/vnd.github+json'},
      );

      if (res.statusCode == 200) {
        final decoded = jsonDecode(res.body);
        String content = utf8.decode(base64.decode(decoded['content'].replaceAll('\n', '')));
        List<String> lines = content.split('\n').where((l) => l.trim().isNotEmpty).toList();

        if (lines.length > 1) {
          deals = lines.skip(1).map((line) {
            List<String> cols = line.split(',');
            return Deal(
              facility: cols.length > 0 ? cols[0] : '',
              leaseCost: cols.length > 1 ? double.tryParse(cols[1]) ?? 0 : 0,
              tenants: cols.length > 2 ? int.tryParse(cols[2]) ?? 0 : 0,
              rentPerTenant: cols.length > 3 ? double.tryParse(cols[3]) ?? 0 : 0,
              startDate: cols.length > 4 ? cols[4] : '',
            );
          }).toList();
        }
      }
    } catch (e) {
      // File doesn't exist yet - that's ok
    }
    setState(() => isLoading = false);
  }

  double get totalMonthlyRevenue => deals.fold(0.0, (sum, d) => sum + d.monthlyProfit);
  double get totalAnnualRevenue => totalMonthlyRevenue * 12;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Active Deals'), backgroundColor: Colors.black),
      body: isLoading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                // REVENUE SUMMARY
                Container(
                  width: double.infinity,
                  margin: const EdgeInsets.all(16),
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(colors: [Colors.green[900]!, Colors.green[700]!]),
                    borderRadius: BorderRadius.circular(15),
                  ),
                  child: Column(
                    children: [
                      const Text('TOTAL MONTHLY PROFIT', style: TextStyle(color: Colors.white70, fontSize: 12, letterSpacing: 1.5)),
                      const SizedBox(height: 5),
                      Text('\$${totalMonthlyRevenue.toStringAsFixed(2)}', style: const TextStyle(fontSize: 38, fontWeight: FontWeight.bold, color: Colors.white)),
                      const SizedBox(height: 10),
                      Text('Annual: \$${totalAnnualRevenue.toStringAsFixed(2)}', style: const TextStyle(color: Colors.white70, fontSize: 14)),
                      const SizedBox(height: 5),
                      Text('${deals.length} active deal(s)', style: const TextStyle(color: Colors.white54, fontSize: 12)),
                    ],
                  ),
                ),

                // DEALS LIST
                Expanded(
                  child: deals.isEmpty
                      ? Center(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.storefront, size: 64, color: Colors.grey[700]),
                              const SizedBox(height: 16),
                              Text('No active deals yet', style: TextStyle(color: Colors.grey[600], fontSize: 18)),
                              const SizedBox(height: 8),
                              Text('Scout prices, find a spread ≥\$120, sign a lease!', style: TextStyle(color: Colors.grey[700], fontSize: 14)),
                            ],
                          ),
                        )
                      : ListView.builder(
                          itemCount: deals.length,
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          itemBuilder: (ctx, i) {
                            final deal = deals[i];
                            return Card(
                              color: Colors.grey[900],
                              margin: const EdgeInsets.only(bottom: 12),
                              child: ListTile(
                                leading: CircleAvatar(
                                  backgroundColor: Colors.greenAccent,
                                  child: Text('${deal.tenants}', style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
                                ),
                                title: Text(deal.facility, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                                subtitle: Text('Lease: \$${deal.leaseCost}/mo • ${deal.tenants} tenants @ \$${deal.rentPerTenant}', style: const TextStyle(color: Colors.grey)),
                                trailing: Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  crossAxisAlignment: CrossAxisAlignment.end,
                                  children: [
                                    Text('+\$${deal.monthlyProfit.toStringAsFixed(0)}', style: const TextStyle(color: Colors.greenAccent, fontWeight: FontWeight.bold, fontSize: 18)),
                                    const Text('/mo', style: TextStyle(color: Colors.grey, fontSize: 10)),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showAddDealDialog(context),
        backgroundColor: Colors.greenAccent,
        child: const Icon(Icons.add, color: Colors.black),
      ),
    );
  }

  void _showAddDealDialog(BuildContext context) {
    String facility = '';
    double leaseCost = 0;
    int tenants = 0;
    double rentPerTenant = 0;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text('Add Active Deal', style: TextStyle(color: Colors.white)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                decoration: const InputDecoration(labelText: 'Facility Name'),
                style: const TextStyle(color: Colors.white),
                onChanged: (v) => facility = v,
              ),
              TextField(
                decoration: const InputDecoration(labelText: 'Monthly Lease Cost'),
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                onChanged: (v) => leaseCost = double.tryParse(v) ?? 0,
              ),
              TextField(
                decoration: const InputDecoration(labelText: 'Number of Tenants'),
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                onChanged: (v) => tenants = int.tryParse(v) ?? 0,
              ),
              TextField(
                decoration: const InputDecoration(labelText: 'Rent per Tenant'),
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                onChanged: (v) => rentPerTenant = double.tryParse(v) ?? 0,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.greenAccent),
            onPressed: () async {
              Navigator.pop(ctx);
              await _saveDeal(facility, leaseCost, tenants, rentPerTenant);
            },
            child: const Text('Save Deal', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  Future<void> _saveDeal(String facility, double leaseCost, int tenants, double rentPerTenant) async {
    try {
      final getRes = await http.get(
        Uri.parse('https://api.github.com/repos/$ghUser/$ghRepo/contents/active_deals.csv'),
        headers: {'Authorization': 'Bearer $ghToken', 'Accept': 'application/vnd.github+json'},
      );

      String? sha;
      String currentContent = '';

      if (getRes.statusCode == 200) {
        final decoded = jsonDecode(getRes.body);
        sha = decoded['sha'];
        currentContent = utf8.decode(base64.decode(decoded['content'].replaceAll('\n', '')));
      } else {
        currentContent = 'facility,lease_cost,tenants,rent_per_tenant,start_date\n';
      }

      String date = DateTime.now().toString().split(' ')[0];
      String newRow = '$facility,$leaseCost,$tenants,$rentPerTenant,$date\n';
      String updatedContent = currentContent.trimRight() + '\n' + newRow;

      await http.put(
        Uri.parse('https://api.github.com/repos/$ghUser/$ghRepo/contents/active_deals.csv'),
        headers: {'Authorization': 'Bearer $ghToken', 'Accept': 'application/vnd.github+json'},
        body: jsonEncode({
          'message': 'Add deal: $facility',
          'content': base64Encode(utf8.encode(updatedContent)),
          if (sha != null) 'sha': sha,
        }),
      );

      loadDeals();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Deal saved!'), backgroundColor: Colors.green),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ Error: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }
}

class Deal {
  final String facility;
  final double leaseCost;
  final int tenants;
  final double rentPerTenant;
  final String startDate;

  Deal({required this.facility, required this.leaseCost, required this.tenants, required this.rentPerTenant, required this.startDate});

  double get monthlyProfit => (tenants * rentPerTenant) - leaseCost - 12; // -12 for insurance
}

// ============================================================================
// LISTING GENERATOR - Auto-generate Neighbor.com listing text
// ============================================================================
class ListingGeneratorScreen extends StatefulWidget {
  const ListingGeneratorScreen({super.key});

  @override
  State<ListingGeneratorScreen> createState() => _ListingGeneratorScreenState();
}

class _ListingGeneratorScreenState extends State<ListingGeneratorScreen> {
  String unitSize = '5x5';
  String zipCode = '33071';
  double monthlyRate = 65;
  bool hasClimateControl = false;
  bool has24hrAccess = true;

  String get generatedTitle => '$unitSize Climate-${hasClimateControl ? "Controlled" : "Free"} Storage in Coral Springs';

  String get generatedDescription => '''
Secure $unitSize storage space available in Coral Springs, FL ($zipCode).

✓ ${hasClimateControl ? "Climate-controlled" : "Standard temperature"}
✓ ${has24hrAccess ? "24/7 access" : "Business hours access"}
✓ Ground-level unit - no stairs!
✓ Well-lit facility
✓ Month-to-month - no long-term commitment

Perfect for:
- Seasonal items
- Small furniture
- Boxes and bins
- Sports equipment

\$${monthlyRate.toStringAsFixed(0)}/month - Reserve your space today!

Message me to schedule a viewing.
''';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Listing Generator'), backgroundColor: Colors.black),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Configure Your Listing', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 20),

            // Unit Size Dropdown
            DropdownButtonFormField<String>(
              value: unitSize,
              dropdownColor: Colors.grey[900],
              decoration: const InputDecoration(labelText: 'Unit Size'),
              style: const TextStyle(color: Colors.white),
              items: ['5x5', '5x10', '10x10', '10x15'].map((s) => DropdownMenuItem(value: s, child: Text(s))).toList(),
              onChanged: (v) => setState(() => unitSize = v!),
            ),
            const SizedBox(height: 15),

            TextFormField(
              initialValue: zipCode,
              decoration: const InputDecoration(labelText: 'Zip Code'),
              style: const TextStyle(color: Colors.white),
              onChanged: (v) => setState(() => zipCode = v),
            ),
            const SizedBox(height: 15),

            TextFormField(
              initialValue: monthlyRate.toString(),
              decoration: const InputDecoration(labelText: 'Monthly Rate (\$)'),
              keyboardType: TextInputType.number,
              style: const TextStyle(color: Colors.white),
              onChanged: (v) => setState(() => monthlyRate = double.tryParse(v) ?? 65),
            ),
            const SizedBox(height: 15),

            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Climate Controlled', style: TextStyle(color: Colors.white)),
              value: hasClimateControl,
              activeColor: Colors.greenAccent,
              onChanged: (v) => setState(() => hasClimateControl = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('24/7 Access', style: TextStyle(color: Colors.white)),
              value: has24hrAccess,
              activeColor: Colors.greenAccent,
              onChanged: (v) => setState(() => has24hrAccess = v),
            ),

            const SizedBox(height: 30),
            const Text('Preview', style: TextStyle(color: Colors.grey, fontSize: 14)),
            const SizedBox(height: 10),

            // TITLE PREVIEW
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.grey[900], borderRadius: BorderRadius.circular(8)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('TITLE', style: TextStyle(color: Colors.grey, fontSize: 10)),
                  const SizedBox(height: 4),
                  Text(generatedTitle, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                ],
              ),
            ),
            const SizedBox(height: 10),

            // DESCRIPTION PREVIEW
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.grey[900], borderRadius: BorderRadius.circular(8)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('DESCRIPTION', style: TextStyle(color: Colors.grey, fontSize: 10)),
                  const SizedBox(height: 4),
                  Text(generatedDescription, style: const TextStyle(color: Colors.white, fontSize: 13)),
                ],
              ),
            ),

            const SizedBox(height: 20),

            // COPY BUTTONS
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.grey[800]),
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: generatedTitle));
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Title copied!')));
                    },
                    icon: const Icon(Icons.copy, size: 18),
                    label: const Text('Copy Title'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.greenAccent),
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: generatedDescription));
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Description copied!')));
                    },
                    icon: const Icon(Icons.copy, size: 18, color: Colors.black),
                    label: const Text('Copy Description', style: TextStyle(color: Colors.black)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
