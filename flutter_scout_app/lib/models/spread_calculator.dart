/// Business logic for storage arbitrage spread calculation
class SpreadCalculator {
  static const double floridaInsurance = 12.0;
  static const double highPriorityThreshold = 120.0;

  final double neighborRate;
  final double commercialPrice;
  final bool hasInsuranceWaiver;

  SpreadCalculator({
    required this.neighborRate,
    required this.commercialPrice,
    this.hasInsuranceWaiver = false,
  });

  /// Calculate monthly spread
  /// Formula: (P2P_Rate × 4) - Commercial_Price - Insurance
  double get spread {
    final revenue = neighborRate * 4;
    final insurance = hasInsuranceWaiver ? 0.0 : floridaInsurance;
    return revenue - commercialPrice - insurance;
  }

  /// Revenue from 4x 5x5 sub-rentals
  double get revenue => neighborRate * 4;

  /// Total monthly cost including insurance
  double get cost => commercialPrice + (hasInsuranceWaiver ? 0.0 : floridaInsurance);

  /// Whether spread meets high-priority threshold
  bool get isHighPriority => spread >= highPriorityThreshold;

  /// Whether the deal is profitable at all
  bool get isProfitable => spread > 0;
}

/// Validation utilities for user input
class InputValidator {
  static bool isValidZipCode(String zip) {
    if (zip.length != 5) return false;
    return int.tryParse(zip) != null;
  }

  static bool isValidPrice(String price) {
    final parsed = double.tryParse(price);
    return parsed != null && parsed >= 0;
  }

  static bool isValidFacilityName(String name) {
    return name.trim().isNotEmpty;
  }
}

/// CSV row generator for GitHub storage
class CsvRowGenerator {
  static const String header = 'date,zip,facility,cost,revenue,spread,insurance_waived';

  static String generateRow({
    required DateTime date,
    required String zipCode,
    required String facilityName,
    required double commercialPrice,
    required double neighborRate,
    required double spread,
    required bool hasInsuranceWaiver,
  }) {
    final dateStr = date.toIso8601String().split('T')[0];
    final revenue = neighborRate * 4;
    return '$dateStr,$zipCode,$facilityName,$commercialPrice,$revenue,${spread.toStringAsFixed(2)},$hasInsuranceWaiver';
  }
}
